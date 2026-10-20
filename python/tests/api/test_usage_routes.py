"""Usage for a workspace, costs for platform admins (spec 2026-10-20, 2.4)."""

from datetime import UTC, datetime

import httpx
import pytest
from sqlalchemy import create_engine
from sqlalchemy.pool import StaticPool

from tests.api.test_auth_principal import SERVICE, bearer_for
from thoth_control_plane.api import create_app
from thoth_control_plane.auth.models import BOOTSTRAP_WORKSPACE_ID
from thoth_control_plane.config import Settings
from thoth_control_plane.infrastructure import account_models, usage_models  # noqa: F401
from thoth_control_plane.infrastructure.account_models import WorkspaceRow
from thoth_control_plane.infrastructure.account_store import AccountStore
from thoth_control_plane.infrastructure.source_account_models import Base
from thoth_control_plane.infrastructure.usage_store import UsageStore
from thoth_control_plane.metering import UsageRecord


@pytest.fixture
def engine():
    engine = create_engine(
        "sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool
    )
    Base.metadata.create_all(engine)
    with engine.begin() as connection:
        connection.execute(
            WorkspaceRow.__table__.insert().values(
                workspace_id=BOOTSTRAP_WORKSPACE_ID, name="Thoth", created_at=datetime.now(UTC)
            )
        )
    return engine


@pytest.fixture
def setup(gateway, engine):
    accounts, usage = AccountStore(engine), UsageStore(engine)
    app = create_app(
        Settings(THOTH_CONTROL_PLANE_API_KEY="test-key"),
        gateway,
        account_store=accounts,
        usage_store=usage,
    )
    accounts.ensure_user("alice@acme.test", "Alice")  # the bootstrap owner
    bob = bearer_for(accounts, "bob@acme.test")
    bob_workspace = accounts.ensure_user("bob@acme.test", "Bob").workspace_id
    return app, usage, bob, bob_workspace


async def _call(app, method, path, headers, body=None):
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        return await client.request(method, path, headers=headers, json=body)


async def test_a_workspace_sees_its_own_usage_and_quota_without_money(setup) -> None:
    app, usage, bob, bob_ws = setup
    usage.record(UsageRecord(bob_ws, "video_rendered", "p", 12.5, "second"))
    usage.record(UsageRecord(bob_ws, "account_lease", "instagram", 1, "session", "wf_1"))
    usage.record(UsageRecord(bob_ws, "account_lease", "instagram", 1, "session"))
    usage.record(UsageRecord(BOOTSTRAP_WORKSPACE_ID, "video_rendered", "p", 99, "second"))
    body = (await _call(app, "GET", "/api/v1/usage", bob)).json()
    assert (body["workspace_id"], body["videos"], body["rendered_seconds"]) == (bob_ws, 1, 12.5)
    assert body["leases"] == {"instagram": 2}
    instagram = next(q for q in body["quotas"] if q["platform"] == "instagram")
    assert instagram == {
        "platform": "instagram",
        "daily_leases": 3,
        "used_today": 2,
        "remaining_today": 1,
    }
    assert "usd" not in str(body)


async def test_the_operators_workspace_has_no_quota(setup) -> None:
    app, *_ = setup
    body = (await _call(app, "GET", "/api/v1/usage", SERVICE)).json()
    assert {q["daily_leases"] for q in body["quotas"]} == {None}


async def test_admin_routes_refuse_a_workspace_user(setup) -> None:
    app, _usage, bob, bob_ws = setup
    for path in (
        "/api/v1/admin/usage",
        "/api/v1/admin/prices",
        f"/api/v1/admin/workspaces/{bob_ws}/quotas",
    ):
        assert (await _call(app, "GET", path, bob)).status_code == 403


async def test_the_admin_estimate_splits_workflow_video_and_other_costs(setup) -> None:
    app, usage, _bob, bob_ws = setup
    usage.set_price("account_lease", "*", "session", 0.05)
    usage.set_price("video_rendered", "*", "second", 0.01)
    usage.set_price("provider_call", "*", "call", 0.02)
    for _ in range(2):
        usage.record(UsageRecord(bob_ws, "account_lease", "instagram", 1, "session", "wf_1"))
    usage.record(
        UsageRecord(bob_ws, "workflow_completed", "source_investigation", 1, "workflow", "wf_1")
    )
    usage.record(UsageRecord(bob_ws, "video_rendered", "p", 30, "second", None, "p1"))
    usage.record(UsageRecord(bob_ws, "provider_call", "voice", 1, "call"))  # Studio: other
    body = (await _call(app, "GET", "/api/v1/admin/usage", SERVICE)).json()
    (bob,) = [w for w in body["workspaces"] if w["workspace_id"] == bob_ws]
    assert bob["workflow_usd"] == pytest.approx(0.10)
    assert bob["video_usd"] == pytest.approx(0.30)
    assert bob["other_usd"] == pytest.approx(0.02)
    assert bob["estimated_usd"] == pytest.approx(0.42)
    assert bob["per_workflow_usd"] == pytest.approx(0.10)  # never includes the render
    assert bob["per_video_usd"] == pytest.approx(0.30)  # never includes the leases
    assert bob["complete"] is False  # workflow_completed has no price
    assert [line["kind"] for line in bob["unpriced"]] == ["workflow_completed"]


async def test_an_admin_sets_a_quota_and_a_price(setup) -> None:
    app, usage, _bob, bob_ws = setup
    quota = await _call(
        app,
        "PUT",
        f"/api/v1/admin/workspaces/{bob_ws}/quotas",
        SERVICE,
        {"platform": "instagram", "daily_leases": 0},
    )
    price = await _call(
        app,
        "PUT",
        "/api/v1/admin/prices",
        SERVICE,
        {"kind": "provider_call", "key": "*", "unit": "call", "usd_per_unit": 0.001},
    )
    assert quota.json()["quotas"]["instagram"] == 0
    assert price.status_code == 200 and usage.prices()[0].usd_per_unit == 0.001
    bad = await _call(
        app,
        "PUT",
        "/api/v1/admin/prices",
        SERVICE,
        {"kind": "teleport", "key": "*", "unit": "call", "usd_per_unit": 1},
    )
    assert bad.status_code == 422
