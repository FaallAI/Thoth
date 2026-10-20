"""Plans, allowance and checkout for the caller's workspace (spec 2026-10-20 billing)."""

from __future__ import annotations

import asyncio
from datetime import UTC, date, datetime, timedelta
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Query, Request, status

from thoth_control_plane.api.dependencies import (
    current_principal,
    platform_actor,
    require_write,
)
from thoth_control_plane.auth.models import BOOTSTRAP_WORKSPACE_ID, Principal, is_platform_admin
from thoth_control_plane.billing import InvalidPlan, PlanConflict, UnknownPlan
from thoth_control_plane.domain import Actor
from thoth_control_plane.domain.models import StrictModel
from thoth_control_plane.infrastructure.billing_store import BillingStore
from thoth_control_plane.infrastructure.xendit import PaymentProviderUnavailable
from thoth_control_plane.metering import estimate

router = APIRouter(tags=["billing"])
Caller = Annotated[Principal, Depends(current_principal)]
Admin = Annotated[Actor, Depends(platform_actor)]
#: Usage counted for its own sake, never billed by a provider: no unit price is needed.
COUNTERS = frozenset({"workflow_completed"})


class CheckoutRequest(StrictModel):
    plan_id: str


class CheckoutView(StrictModel):
    invoice_id: str | None
    invoice_url: str | None
    applied: bool


def _store(request: Request) -> BillingStore:
    store = request.app.state.billing_store
    if store is None:
        raise HTTPException(status.HTTP_503_SERVICE_UNAVAILABLE, "billing_unavailable")
    return store


@router.post("/billing/checkout", response_model=CheckoutView)
async def checkout(request: Request, body: CheckoutRequest, principal: Caller) -> CheckoutView:
    """Buy or renew a plan (spec 2.1): owners and admins of the workspace only."""
    require_write(request, principal)
    if principal.role not in ("owner", "admin") and not is_platform_admin(principal):
        raise HTTPException(status.HTTP_403_FORBIDDEN, "Not authorized")
    if principal.workspace_id == BOOTSTRAP_WORKSPACE_ID:
        raise HTTPException(status.HTTP_409_CONFLICT, "operator_workspace")
    store = _store(request)
    plan = await asyncio.to_thread(store.plan, body.plan_id)
    if plan is None or not plan.active:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "unknown_plan")
    if plan.price_idr == 0:
        try:
            await asyncio.to_thread(store.choose_free_plan, principal.workspace_id, plan.plan_id)
        except PlanConflict as conflict:
            raise HTTPException(status.HTTP_409_CONFLICT, conflict.code) from None
        return CheckoutView(invoice_id=None, invoice_url=None, applied=True)
    payments = getattr(request.app.state, "payments", None)
    if payments is None:
        raise HTTPException(status.HTTP_503_SERVICE_UNAVAILABLE, "billing_unavailable")
    try:
        invoice = await asyncio.to_thread(store.open_invoice, principal.workspace_id, plan.plan_id)
    except UnknownPlan:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "unknown_plan") from None
    back = f"{request.app.state.settings.THOTH_SITE_ORIGIN}/billing"
    try:
        made = await payments.create(
            external_id=invoice.invoice_id,
            amount_idr=invoice.amount_idr,
            payer_email=principal.email or "",
            description=plan.name,
            success_url=back,
            failure_url=back,
        )
    except PaymentProviderUnavailable:
        await asyncio.to_thread(store.fail_invoice, invoice.invoice_id)
        raise HTTPException(status.HTTP_502_BAD_GATEWAY, "payment_provider_unavailable") from None
    await asyncio.to_thread(store.attach_invoice, invoice.invoice_id, made.id, made.invoice_url)
    return CheckoutView(invoice_id=invoice.invoice_id, invoice_url=made.invoice_url, applied=False)


class PlanOut(StrictModel):
    plan_id: str
    name: str
    price_idr: int
    workflows_per_period: int
    videos_per_period: int
    period_days: int
    active: bool


class PlanEdit(StrictModel):
    name: str
    price_idr: int
    workflows_per_period: int
    videos_per_period: int
    period_days: int | None = None  # None keeps the stored value
    active: bool | None = None  # None keeps the stored value


class RateEdit(StrictModel):
    idr_per_usd: float


class InvoiceOut(StrictModel):
    invoice_id: str
    plan_id: str
    amount_idr: int
    status: str
    invoice_url: str | None
    created_at: datetime
    paid_at: datetime | None


class BillingView(StrictModel):
    workspace_id: str
    unlimited: bool
    plan: PlanOut | None
    period_start: datetime | None
    period_end: datetime | None
    workflows_used: int
    workflows_allowed: int | None
    videos_used: int
    videos_allowed: int | None
    plans: list[PlanOut]
    invoices: list[InvoiceOut]


class PlanMargin(StrictModel):
    plan_id: str
    price_idr: int
    workflows_per_period: int
    videos_per_period: int
    cost_per_workflow_usd: float | None
    cost_per_video_usd: float | None
    full_use_cost_usd: float | None
    full_use_cost_idr: int | None
    margin_idr: int | None


class MarginView(StrictModel):
    start: date
    end: date
    idr_per_usd: float | None
    complete: bool  # false while any usage has no unit price, or no exchange rate is set
    plans: list[PlanMargin]


@router.get("/billing", response_model=BillingView)
async def my_billing(request: Request, principal: Caller) -> BillingView:
    """The caller's plan, this period's allowance and invoices (spec 2.4)."""
    store = _store(request)
    view = await asyncio.to_thread(store.allowance, principal.workspace_id)
    plans = await asyncio.to_thread(store.plans, True)
    invoices = await asyncio.to_thread(store.invoices, principal.workspace_id)
    return BillingView(
        workspace_id=principal.workspace_id,
        unlimited=view.unlimited,
        plan=None if view.plan is None else PlanOut(**vars(view.plan)),
        period_start=view.period_start,
        period_end=view.period_end,
        workflows_used=view.workflows_used,
        workflows_allowed=view.workflows_allowed,
        videos_used=view.videos_used,
        videos_allowed=view.videos_allowed,
        plans=[PlanOut(**vars(p)) for p in plans],
        invoices=[
            InvoiceOut(
                **{**vars(i), "invoice_url": i.invoice_url if i.status == "pending" else None}
            )
            for i in invoices
        ],
    )


@router.get("/admin/plans", response_model=list[PlanOut])
async def list_plans(request: Request, _: Admin) -> list[PlanOut]:
    return [PlanOut(**vars(p)) for p in await asyncio.to_thread(_store(request).plans)]


@router.put("/admin/plans/rate", response_model=RateEdit)
async def set_rate(request: Request, edit: RateEdit, _: Admin) -> RateEdit:
    """Rupiah per US dollar for the margin report (spec 1.5). Declared before the plan route."""
    try:
        rate = await asyncio.to_thread(_store(request).set_usd_idr_rate, edit.idr_per_usd)
    except InvalidPlan:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, "invalid_rate") from None
    return RateEdit(idr_per_usd=rate)


@router.get("/admin/plans/margin", response_model=MarginView)
async def plan_margin(
    request: Request,
    _: Admin,
    start: Annotated[date | None, Query(alias="from")] = None,
    end: Annotated[date | None, Query(alias="to")] = None,
) -> MarginView:
    """Each plan's price against metered cost, in rupiah at the admin rate (spec 1.5)."""
    from thoth_control_plane.api.routes.usage import _bucket

    store = _store(request)
    usage = request.app.state.usage_store
    today = datetime.now(UTC).date()
    begin, finish = start or today.replace(day=1), end or today
    since = datetime.combine(begin, datetime.min.time(), tzinfo=UTC)
    until = datetime.combine(finish, datetime.min.time(), tzinfo=UTC) + timedelta(days=1)
    totals = (
        []
        if usage is None
        else [
            total
            for rows in (await asyncio.to_thread(usage.totals_by_workspace, since, until)).values()
            for total in rows
        ]
    )
    prices = (
        {}
        if usage is None
        else {
            (p.kind, p.key, p.unit): p.usd_per_unit for p in await asyncio.to_thread(usage.prices)
        }
    )
    result = estimate(totals, prices)
    spent = {"workflow": 0.0, "video": 0.0}
    unpriced: set[str] = set()  # a bucket with unpriced usage has no honest per-unit cost
    for total, line in zip(totals, result.lines, strict=True):
        bucket = _bucket(total)
        if bucket in spent:
            if line.usd is not None:
                spent[bucket] += line.usd
            elif total.kind not in COUNTERS:
                unpriced.add(bucket)
    workflows = sum(t.events for t in totals if t.kind == "workflow_completed")
    videos = sum(t.events for t in totals if t.kind == "video_rendered")
    per_workflow = (
        spent["workflow"] / workflows if workflows and "workflow" not in unpriced else None
    )
    per_video = spent["video"] / videos if videos and "video" not in unpriced else None
    rate = await asyncio.to_thread(store.usd_idr_rate)
    margins = []
    for plan in await asyncio.to_thread(store.plans, True):
        full = (
            None
            if per_workflow is None or per_video is None
            else plan.workflows_per_period * per_workflow + plan.videos_per_period * per_video
        )
        full_idr = None if full is None or rate is None else round(full * rate)
        margins.append(
            PlanMargin(
                plan_id=plan.plan_id,
                price_idr=plan.price_idr,
                workflows_per_period=plan.workflows_per_period,
                videos_per_period=plan.videos_per_period,
                cost_per_workflow_usd=per_workflow,
                cost_per_video_usd=per_video,
                full_use_cost_usd=full,
                full_use_cost_idr=full_idr,
                margin_idr=None if full_idr is None else plan.price_idr - full_idr,
            )
        )
    return MarginView(
        start=begin,
        end=finish,
        idr_per_usd=rate,
        complete=rate is not None
        and not any(line.kind not in COUNTERS for line in result.unpriced),
        plans=margins,
    )


@router.put("/admin/plans/{plan_id}", response_model=PlanOut)
async def edit_plan(request: Request, plan_id: str, edit: PlanEdit, _: Admin) -> PlanOut:
    """Create or change a plan without a deploy (spec 1.1)."""
    store = _store(request)
    try:
        saved = await asyncio.to_thread(
            lambda: store.set_plan(
                plan_id,
                name=edit.name,
                price_idr=edit.price_idr,
                workflows=edit.workflows_per_period,
                videos=edit.videos_per_period,
                period_days=edit.period_days,
                active=edit.active,
            )
        )
    except InvalidPlan:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, "invalid_plan") from None
    return PlanOut(**vars(saved))
