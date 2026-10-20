"""Usage for the caller's workspace; costs, quotas and prices for platform admins
(spec 2026-10-20 metering, 1.5 and 2.4)."""

from __future__ import annotations

import asyncio
import math
from datetime import UTC, date, datetime, timedelta
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Query, Request, status
from pydantic import Field

from thoth_control_plane.api.dependencies import current_principal, platform_actor
from thoth_control_plane.auth.models import BOOTSTRAP_WORKSPACE_ID, Principal
from thoth_control_plane.domain import Actor
from thoth_control_plane.domain.models import StrictModel
from thoth_control_plane.infrastructure.usage_store import UsageStore, UsageTotal
from thoth_control_plane.metering import CostLine, estimate

router = APIRouter(tags=["usage"])
Caller = Annotated[Principal, Depends(current_principal)]
Admin = Annotated[Actor, Depends(platform_actor)]
MONTH = r"^\d{4}-(0[1-9]|1[0-2])$"


class PlatformQuota(StrictModel):
    platform: str
    daily_leases: int | None  # None: the operator's workspace has no quota
    used_today: int
    remaining_today: int | None


class UsageView(StrictModel):
    workspace_id: str
    month: str
    workflows: int
    videos: int
    rendered_seconds: float
    stored_bytes: int
    leases: dict[str, int]
    quotas: list[PlatformQuota]


class CostLineView(StrictModel):
    bucket: str  # workflow, video or other: every cost is in exactly one
    kind: str
    key: str
    unit: str
    quantity: float
    usd: float | None


class WorkspaceCostView(StrictModel):
    workspace_id: str
    workflows: int
    videos: int
    estimated_usd: float
    workflow_usd: float
    video_usd: float
    other_usd: float
    per_workflow_usd: float | None
    per_video_usd: float | None
    complete: bool  # false while an event has no unit price: the estimate is too low
    lines: list[CostLineView]
    unpriced: list[CostLineView]


class AdminUsageView(StrictModel):
    start: date
    end: date
    workspaces: list[WorkspaceCostView]


class QuotaView(StrictModel):
    workspace_id: str
    quotas: dict[str, int]


class QuotaChange(StrictModel):
    platform: str
    daily_leases: Annotated[int, Field(ge=0)] | None  # None clears the override


class PriceView(StrictModel):
    kind: str
    key: Annotated[str, Field(min_length=1, max_length=200)]
    unit: str
    usd_per_unit: Annotated[float, Field(ge=0)]


def _store(request: Request) -> UsageStore:
    store = request.app.state.usage_store
    if store is None:
        raise HTTPException(status.HTTP_503_SERVICE_UNAVAILABLE, "usage_unavailable")
    return store


def _month_range(month: str | None) -> tuple[str, datetime, datetime]:
    now = datetime.now(UTC)
    year, number = (int(part) for part in (month or now.strftime("%Y-%m")).split("-"))
    start = datetime(year, number, 1, tzinfo=UTC)
    end = datetime(year + number // 12, number % 12 + 1, 1, tzinfo=UTC)
    return f"{year:04d}-{number:02d}", start, end


def _sum(totals: list[UsageTotal], kind: str) -> float:
    return sum(t.quantity for t in totals if t.kind == kind)


def _count(totals: list[UsageTotal], kind: str) -> int:
    return sum(t.events for t in totals if t.kind == kind)


def _bucket(total: UsageTotal) -> str:
    """Spec 2.4: no cost counts toward both the per-workflow and the per-video figure."""
    if total.in_workflow:
        return "workflow"
    if total.kind == "video_rendered" or (total.kind == "media_stored" and total.key == "renders"):
        return "video"
    return "other"


def _line(bucket: str, line: CostLine) -> CostLineView:
    return CostLineView(
        bucket=bucket,
        kind=line.kind,
        key=line.key,
        unit=line.unit,
        quantity=line.quantity,
        usd=line.usd,
    )


@router.get("/usage", response_model=UsageView)
async def my_usage(
    request: Request,
    principal: Caller,
    month: Annotated[str | None, Query(pattern=MONTH)] = None,
) -> UsageView:
    store = _store(request)
    label, start, end = _month_range(month)
    workspace = principal.workspace_id
    totals = await asyncio.to_thread(store.totals, workspace, start, end)
    today = await asyncio.to_thread(store.leases_today, workspace)
    quotas = await asyncio.to_thread(store.quotas, workspace)
    exempt = workspace == BOOTSTRAP_WORKSPACE_ID
    leases: dict[str, int] = {}
    for total in totals:
        if total.kind == "account_lease":
            leases[total.key] = leases.get(total.key, 0) + total.events
    return UsageView(
        workspace_id=workspace,
        month=label,
        workflows=_count(totals, "workflow_completed"),
        videos=_count(totals, "video_rendered"),
        rendered_seconds=_sum(totals, "video_rendered"),
        stored_bytes=int(_sum(totals, "media_stored")),
        leases=leases,
        quotas=[
            PlatformQuota(
                platform=platform,
                daily_leases=None if exempt else limit,
                used_today=today.get(platform, 0),
                remaining_today=None if exempt else max(0, limit - today.get(platform, 0)),
            )
            for platform, limit in quotas.items()
        ],
    )


@router.get("/admin/usage", response_model=AdminUsageView)
async def admin_usage(
    request: Request,
    _: Admin,
    start: Annotated[date | None, Query(alias="from")] = None,
    end: Annotated[date | None, Query(alias="to")] = None,
) -> AdminUsageView:
    """`from` and `to` are UTC days, both included; the default is the current month."""
    store = _store(request)
    _label, month_start, month_end = _month_range(None)
    begin = start or month_start.date()
    finish = end or (month_end - timedelta(days=1)).date()
    since = datetime.combine(begin, datetime.min.time(), tzinfo=UTC)
    until = datetime.combine(finish, datetime.min.time(), tzinfo=UTC) + timedelta(days=1)
    by_workspace = await asyncio.to_thread(store.totals_by_workspace, since, until)
    prices = {
        (p.kind, p.key, p.unit): p.usd_per_unit for p in await asyncio.to_thread(store.prices)
    }
    views = []
    for workspace, totals in sorted(by_workspace.items()):
        result = estimate(totals, prices)
        buckets = [_bucket(total) for total in totals]
        spent = {
            name: math.fsum(
                line.usd
                for bucket, line in zip(buckets, result.lines, strict=True)
                if bucket == name and line.usd is not None
            )
            for name in ("workflow", "video", "other")
        }
        workflows, videos = _count(totals, "workflow_completed"), _count(totals, "video_rendered")
        lines = [_line(b, line) for b, line in zip(buckets, result.lines, strict=True)]
        views.append(
            WorkspaceCostView(
                workspace_id=workspace,
                workflows=workflows,
                videos=videos,
                estimated_usd=result.usd,
                workflow_usd=spent["workflow"],
                video_usd=spent["video"],
                other_usd=spent["other"],
                per_workflow_usd=spent["workflow"] / workflows if workflows else None,
                per_video_usd=spent["video"] / videos if videos else None,
                complete=not result.unpriced,
                lines=lines,
                unpriced=[line for line in lines if line.usd is None],
            )
        )
    return AdminUsageView(start=begin, end=finish, workspaces=views)


@router.get("/admin/workspaces/{workspace_id}/quotas", response_model=QuotaView)
async def workspace_quotas(request: Request, workspace_id: str, _: Admin) -> QuotaView:
    quotas = await asyncio.to_thread(_store(request).quotas, workspace_id)
    return QuotaView(workspace_id=workspace_id, quotas=quotas)


@router.put("/admin/workspaces/{workspace_id}/quotas", response_model=QuotaView)
async def change_quota(
    request: Request, workspace_id: str, change: QuotaChange, _: Admin
) -> QuotaView:
    store = _store(request)
    try:
        if change.daily_leases is None:
            await asyncio.to_thread(store.clear_quota, workspace_id, change.platform)
        else:
            await asyncio.to_thread(
                store.set_quota, workspace_id, change.platform, change.daily_leases
            )
    except ValueError:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, "invalid_quota") from None
    except LookupError:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "unknown_workspace") from None
    return QuotaView(
        workspace_id=workspace_id, quotas=await asyncio.to_thread(store.quotas, workspace_id)
    )


@router.get("/admin/prices", response_model=list[PriceView])
async def list_prices(request: Request, _: Admin) -> list[PriceView]:
    return [PriceView(**vars(p)) for p in await asyncio.to_thread(_store(request).prices)]


@router.put("/admin/prices", response_model=PriceView)
async def set_price(request: Request, price: PriceView, _: Admin) -> PriceView:
    try:
        saved = await asyncio.to_thread(
            _store(request).set_price, price.kind, price.key, price.unit, price.usd_per_unit
        )
    except ValueError:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, "invalid_price") from None
    return PriceView(**vars(saved))
