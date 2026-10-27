"""The inbox: approvals after settling, unacknowledged failures, admin-only accounts (G5, D4)."""

import json
from datetime import UTC, datetime, timedelta

import httpx
import pytest
import pytest_asyncio

from tests.sqlite_support import sqlite_engine
from thoth_control_plane.api import create_app
from thoth_control_plane.config import Settings
from thoth_control_plane.domain.models import WorkflowSummary
from thoth_control_plane.domain.workflow_runs import StoredRun
from thoth_control_plane.infrastructure import run_models  # noqa: F401  (workflow_runs rows)
from thoth_control_plane.infrastructure.project_store import ProjectStore
from thoth_control_plane.infrastructure.report_store import ReportStore
from thoth_control_plane.infrastructure.source_account_models import Base
from thoth_control_plane.infrastructure.source_account_store import AccountView
from thoth_control_plane.infrastructure.workflow_run_store import WorkflowRunStore

AUTH = {"Authorization": "Bearer test-key"}
REQUEST = {
    "source": {"url": "https://www.tiktok.com/@a/video/1", "intent": "identify_original"},
    "style": {"preset_id": "news-vertical"},
    "output": {"format": "vertical_video", "language": "id"},
    "review": {"require_publish_approval": True},
}
T0 = datetime(2026, 10, 26, 12, tzinfo=UTC)


class AccountViews:
    """The source-account store surface the inbox reads."""

    def __init__(self, views: list[AccountView]) -> None:
        self.views = views

    def accounts(self) -> list[AccountView]:
        return self.views


def view(account_id: str, status: str, cooldown_until: datetime | None = None) -> AccountView:
    return AccountView(
        id=account_id,
        platform="tiktok",
        label=f"Account {account_id}",
        status=status,
        cooldown_until=cooldown_until,
        last_used_at=None,
        last_outcome=None,
        success_count=0,
        failure_count=0,
        cookie_names=("sessionid",),
        cookies_earliest_expiry=None,
        proxy_id="prox_1",
        proxy_display="socks5 proxy",
        created_at=T0 - timedelta(days=30),
        updated_at=T0,
    )


@pytest.fixture
def stores():
    engine = sqlite_engine()
    Base.metadata.create_all(engine)
    return ProjectStore(engine), WorkflowRunStore(engine), ReportStore(engine)


@pytest.fixture
def accounts() -> AccountViews:
    now = datetime.now(UTC)
    return AccountViews(
        [
            view("acct_cooldown", "cooldown", now + timedelta(hours=2)),
            view("acct_expired", "expired"),
            view("acct_lagging", "healthy", now + timedelta(hours=1)),
            view("acct_clean", "healthy"),
            # Deliberately off: a disabled account never joins the inbox.
            view("acct_disabled", "disabled", now + timedelta(hours=3)),
        ]
    )


def build_app(gateway, stores, accounts=None):
    projects, runs, reports = stores
    return create_app(
        Settings(THOTH_CONTROL_PLANE_API_KEY="test-key"),
        gateway,
        project_store=projects,
        workflow_run_store=runs,
        report_store=reports,
        source_account_store=accounts,
    )


@pytest_asyncio.fixture
async def api(gateway, stores, accounts):
    transport = httpx.ASGITransport(app=build_app(gateway, stores, accounts))
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        yield client


def summary_at(status: str, *, updated_at: datetime = T0) -> WorkflowSummary:
    return WorkflowSummary.model_validate_json(
        json.dumps(
            {
                "workflow_id": "wf_001",
                "status": status,
                "created_at": (updated_at - timedelta(hours=1)).isoformat(),
                "updated_at": updated_at.isoformat(),
                "source": {"display_url": "https://x.test/v", "platform": "tiktok"},
                "stages": [],
                **(
                    {
                        "failure": {
                            "code": "source_failed",
                            "message": "The source could not be read.",
                        }
                    }
                    if status == "failed"
                    else {}
                ),
            }
        )
    )


def failed_run(workflow_id: str, *, updated_at: datetime, acknowledged: datetime | None = None):
    return StoredRun(
        workflow_id=workflow_id,
        project_id=None,
        actor_type="user",
        actor_id="owner",
        display_url="https://x.test/v",
        platform="tiktok",
        status="failed",
        history_expired=True,
        summary=summary_at("failed", updated_at=updated_at),
        created_at=updated_at - timedelta(hours=1),
        updated_at=updated_at,
        acknowledged_at=acknowledged,
    )


@pytest.mark.asyncio
async def test_approvals_settle_a_stale_running_row_first(api, stores, gateway) -> None:
    await api.post("/api/v1/workflows", json=REQUEST, headers={**AUTH, "Idempotency-Key": "in1"})
    gateway.workflows["wf_001"] = summary_at("running")
    listing = await api.get("/api/v1/workflows?unassigned=true", headers=AUTH)
    assert listing.status_code == 200
    settled = stores[1].get("wf_001")
    assert settled is not None and settled.status == "running"  # the stale row
    gateway.workflows["wf_001"] = summary_at("awaiting_approval")

    response = await api.get("/api/v1/inbox", headers=AUTH)

    assert response.status_code == 200
    inbox = response.json()
    assert [run["workflow_id"] for run in inbox["approvals"]] == ["wf_001"]
    assert inbox["approvals"][0]["status"] == "awaiting_approval"


@pytest.mark.asyncio
async def test_failures_list_only_unacknowledged_runs_newest_first(api, stores) -> None:
    runs = stores[1]
    runs.insert_missing(failed_run("wf_ack", updated_at=T0, acknowledged=T0))
    runs.insert_missing(failed_run("wf_fail_a", updated_at=T0 - timedelta(hours=2)))
    runs.insert_missing(failed_run("wf_fail_b", updated_at=T0 - timedelta(hours=1)))

    detail = await api.get("/api/v1/workflows/wf_fail_b", headers=AUTH)
    assert detail.status_code == 200  # opening a failed run never acknowledges it (G5)

    inbox = (await api.get("/api/v1/inbox", headers=AUTH)).json()

    assert [run["workflow_id"] for run in inbox["failures"]] == ["wf_fail_b", "wf_fail_a"]
    assert inbox["failures"][0]["failure_code"] == "source_failed"
    assert inbox["failures"][1]["failure_code"] == "source_failed"
    assert runs.get("wf_fail_b").acknowledged_at is None


@pytest.mark.asyncio
async def test_accounts_list_for_a_platform_admin_without_any_secret(api) -> None:
    response = await api.get("/api/v1/inbox", headers=AUTH)  # the service key is an admin

    assert response.status_code == 200
    inbox = response.json()
    assert [account["account_id"] for account in inbox["accounts"]] == [
        "acct_cooldown",
        "acct_expired",
        "acct_lagging",  # healthy but its cooldown has not elapsed yet
    ]
    assert set(inbox["accounts"][0]) == {
        "account_id",
        "platform",
        "label",
        "status",
        "cooldown_until",
    }
    assert set(inbox["approvals"]) == set()  # nothing else to show
    for secret in ("cookie", "proxy", "password", "token"):
        assert secret not in response.text.lower()


@pytest.mark.asyncio
async def test_accounts_need_a_platform_admin_principal(gateway, stores, accounts, monkeypatch):
    from thoth_control_plane.api import dependencies
    from thoth_control_plane.auth.models import Principal

    async def member(request, authorization):
        return Principal(
            "u1",
            "ws_one",
            frozenset({"read", "write"}),
            "token",
            "member@example.test",
            role="member",
        )

    monkeypatch.setattr(dependencies, "resolve_principal", member)
    transport = httpx.ASGITransport(app=build_app(gateway, stores, accounts))
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.get("/api/v1/inbox", headers=AUTH)

    assert response.status_code == 200
    assert response.json()["accounts"] == []


@pytest.mark.asyncio
async def test_an_inbox_without_stores_is_empty_but_serves(gateway) -> None:
    app = create_app(Settings(THOTH_CONTROL_PLANE_API_KEY="test-key"), gateway)
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.get("/api/v1/inbox", headers=AUTH)

    assert response.status_code == 200
    assert response.json() == {"approvals": [], "failures": [], "accounts": []}
