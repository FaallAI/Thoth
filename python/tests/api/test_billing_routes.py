"""A workspace's billing view; plans, the rate and the margin for admins (spec 1.5, 2.4)."""

from datetime import UTC, datetime

import httpx
import pytest
from sqlalchemy import create_engine
from sqlalchemy.pool import StaticPool

from tests.api.test_auth_principal import SERVICE, bearer_for
from thoth_control_plane.api import create_app
from thoth_control_plane.auth.models import BOOTSTRAP_WORKSPACE_ID
from thoth_control_plane.config import Settings
from thoth_control_plane.infrastructure import (  # noqa: F401
    account_models,
    billing_models,
    usage_models,
)
from thoth_control_plane.infrastructure.account_models import WorkspaceRow
from thoth_control_plane.infrastructure.account_store import AccountStore
from thoth_control_plane.infrastructure.billing_models import PlanRow
from thoth_control_plane.infrastructure.billing_store import BillingStore
from thoth_control_plane.infrastructure.source_account_models import Base
from thoth_control_plane.infrastructure.usage_store import UsageStore
from thoth_control_plane.metering import UsageRecord


@pytest.fixture
def world(gateway):
    engine = create_engine(
        "sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool
    )
    Base.metadata.create_all(engine)
    now = datetime.now(UTC)
    with engine.begin() as connection:
        connection.execute(
            WorkspaceRow.__table__.insert().values(
                workspace_id=BOOTSTRAP_WORKSPACE_ID, name="Thoth", created_at=now
            )
        )
        connection.execute(
            PlanRow.__table__.insert().values(
                plan_id="free",
                name="Free",
                price_idr=0,
                workflows_per_period=3,
                videos_per_period=1,
                period_days=30,
                active=True,
                updated_at=now,
            )
        )
    accounts, billing, usage = AccountStore(engine), BillingStore(engine), UsageStore(engine)
    billing.set_plan(
        "pro", name="Pro", price_idr=99000, workflows=50, videos=20, period_days=30, active=True
    )
    app = create_app(
        Settings(THOTH_CONTROL_PLANE_API_KEY="test-key"),
        gateway,
        account_store=accounts,
        billing_store=billing,
        usage_store=usage,
    )
    accounts.ensure_user("alice@acme.test", "Alice")
    bob = bearer_for(accounts, "bob@acme.test")
    bob_ws = accounts.ensure_user("bob@acme.test", "Bob").workspace_id
    return app, billing, usage, bob, bob_ws


async def _call(app, method, path, headers=None, body=None):
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        return await client.request(method, path, headers=headers or {}, json=body)


async def test_a_workspace_sees_its_plan_allowance_and_invoices(world) -> None:
    app, billing, _usage, bob, bob_ws = world
    billing.consume(bob_ws, "workflow", "r1")
    body = (await _call(app, "GET", "/api/v1/billing", bob)).json()
    assert body["unlimited"] is False
    assert (body["plan"]["plan_id"], body["workflows_used"], body["workflows_allowed"]) == (
        "free",
        1,
        3,
    )
    assert [p["plan_id"] for p in body["plans"]] == ["free", "pro"]
    assert body["invoices"] == []


async def test_the_operator_workspace_is_unlimited(world) -> None:
    app, *_ = world
    assert (await _call(app, "GET", "/api/v1/billing", SERVICE)).json()["unlimited"] is True


async def test_an_admin_edits_plans_and_a_user_cannot(world) -> None:
    app, billing, _usage, bob, _ = world
    plan = {
        "name": "Starter",
        "price_idr": 49000,
        "workflows_per_period": 20,
        "videos_per_period": 5,
        "period_days": 30,
        "active": True,
    }
    refused = await _call(app, "PUT", "/api/v1/admin/plans/starter", bob, plan)
    made = await _call(app, "PUT", "/api/v1/admin/plans/starter", SERVICE, plan)
    bad = await _call(app, "PUT", "/api/v1/admin/plans/free", SERVICE, {**plan, "active": False})
    assert refused.status_code == 403
    assert made.status_code == 200 and billing.plan("starter").price_idr == 49000
    assert (bad.status_code, bad.json()) == (422, {"detail": "invalid_plan"})


async def test_the_margin_report_is_incomplete_without_unit_prices(world) -> None:
    app, _billing, usage, *_ = world
    usage.record(UsageRecord("ws_x", "video_rendered", "p", 30, "second"))
    body = (await _call(app, "GET", "/api/v1/admin/plans/margin", SERVICE)).json()
    pro = next(p for p in body["plans"] if p["plan_id"] == "pro")
    assert body["complete"] is False and body["idr_per_usd"] is None
    assert (pro["price_idr"], pro["cost_per_video_usd"], pro["margin_idr"]) == (99000, None, None)


async def test_the_margin_converts_metered_cost_with_the_admin_rate(world) -> None:
    app, _billing, usage, *_ = world
    usage.set_price("account_lease", "*", "session", 0.10)
    usage.set_price("video_rendered", "*", "second", 0.01)
    usage.set_price("workflow_completed", "*", "workflow", 0)
    usage.record(
        UsageRecord("ws_x", "workflow_completed", "source_investigation", 1, "workflow", "wf_1")
    )
    usage.record(UsageRecord("ws_x", "account_lease", "instagram", 1, "session", "wf_1"))
    usage.record(UsageRecord("ws_x", "video_rendered", "p", 30, "second"))
    refused = await _call(app, "PUT", "/api/v1/admin/plans/rate", SERVICE, {"idr_per_usd": 0})
    rate = await _call(app, "PUT", "/api/v1/admin/plans/rate", SERVICE, {"idr_per_usd": 16000})
    body = (await _call(app, "GET", "/api/v1/admin/plans/margin", SERVICE)).json()
    pro = next(p for p in body["plans"] if p["plan_id"] == "pro")
    assert (refused.status_code, refused.json()) == (422, {"detail": "invalid_rate"})
    assert rate.json() == {"idr_per_usd": 16000.0}
    assert body["complete"] is True and body["idr_per_usd"] == 16000.0
    # 50 workflows x $0.10 + 20 videos x $0.30 = $11 = Rp176.000; Rp99.000 - Rp176.000
    assert (pro["full_use_cost_idr"], pro["margin_idr"]) == (176000, -77000)


async def test_completed_workflows_are_a_counter_and_need_no_price(world) -> None:
    app, _billing, usage, *_ = world
    usage.set_price("account_lease", "*", "session", 0.10)
    usage.record(
        UsageRecord("ws_x", "workflow_completed", "source_investigation", 1, "workflow", "wf_1")
    )
    usage.record(UsageRecord("ws_x", "account_lease", "instagram", 1, "session", "wf_1"))
    await _call(app, "PUT", "/api/v1/admin/plans/rate", SERVICE, {"idr_per_usd": 16000})
    body = (await _call(app, "GET", "/api/v1/admin/plans/margin", SERVICE)).json()
    pro = next(p for p in body["plans"] if p["plan_id"] == "pro")
    assert body["complete"] is True
    assert pro["cost_per_workflow_usd"] == pytest.approx(0.10)
