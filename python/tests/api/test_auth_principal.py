"""Sessions and developer tokens on the existing API; data stays the shared `owner`'s (spec 3.6)."""

from datetime import UTC, datetime, timedelta

import httpx
import pytest
from sqlalchemy import create_engine, func, select, text
from sqlalchemy.pool import StaticPool

from thoth_control_plane.api import create_app
from thoth_control_plane.auth.models import BOOTSTRAP_WORKSPACE_ID
from thoth_control_plane.auth.secrets import token_hash
from thoth_control_plane.config import Settings
from thoth_control_plane.infrastructure import account_models, run_models  # noqa: F401
from thoth_control_plane.infrastructure.account_models import AuthEventRow, WorkspaceRow
from thoth_control_plane.infrastructure.account_store import AccountStore, TokenRecord
from thoth_control_plane.infrastructure.project_store import ProjectStore
from thoth_control_plane.infrastructure.report_store import ReportStore
from thoth_control_plane.infrastructure.source_account_models import Base
from thoth_control_plane.infrastructure.workflow_run_store import WorkflowRunStore

ORIGIN = "http://localhost:8088"
SERVICE = {"Authorization": "Bearer test-key"}
REQUEST = {
    "source": {"url": "https://www.tiktok.com/@a/video/1", "intent": "identify_original"},
    "style": {"preset_id": "news-vertical"},
    "output": {"format": "vertical_video", "language": "id"},
    "review": {"require_publish_approval": True},
}


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
def accounts(engine) -> AccountStore:
    return AccountStore(engine)


@pytest.fixture
async def api(gateway, engine, accounts):
    app = create_app(
        Settings(THOTH_CONTROL_PLANE_API_KEY="test-key", THOTH_SITE_ORIGIN=ORIGIN),
        gateway,
        project_store=ProjectStore(engine),
        workflow_run_store=WorkflowRunStore(engine),
        report_store=ReportStore(engine),
        account_store=accounts,
    )
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        yield client


def session_for(accounts: AccountStore, email: str = "alice@acme.test") -> dict[str, str]:
    user = accounts.ensure_user(email, "Alice")
    accounts.create_session(
        user.user_id,
        user.workspace_id,
        token_hash("ses-" + email),
        datetime.now(UTC) + timedelta(hours=1),
    )
    return {"thoth_session": "ses-" + email}


def token_for(
    accounts: AccountStore, scope: str, *, days: int = 1, secret: str = ""
) -> dict[str, str]:
    user = accounts.ensure_user("alice@acme.test", "Alice")
    secret = secret or f"thoth_pat_{scope}"
    now = datetime.now(UTC)
    accounts.create_token(
        TokenRecord(
            f"tok_{scope}{days}",
            "user",
            user.user_id,
            user.workspace_id,
            scope,
            secret[:16],
            scope,
            now - timedelta(days=2),
            now + timedelta(days=days),
            None,
        ),
        token_hash(secret),
    )
    return {"Authorization": f"Bearer {secret}"}


async def test_a_session_reads_and_writes_only_from_its_own_origin(api, accounts) -> None:
    cookies = session_for(accounts)
    assert (await api.get("/api/v1/projects", cookies=cookies)).status_code == 200
    cross = await api.post("/api/v1/projects", json={"name": "News"}, cookies=cookies)
    assert (cross.status_code, cross.json()) == (403, {"detail": "cross_site_request"})
    foreign = await api.post(
        "/api/v1/projects",
        json={"name": "News"},
        cookies=cookies,
        headers={"Origin": "https://evil.test"},
    )
    assert foreign.status_code == 403
    made = await api.post(
        "/api/v1/projects", json={"name": "News"}, cookies=cookies, headers={"Origin": ORIGIN}
    )
    assert made.status_code == 201


async def test_a_token_needs_write_to_mutate_and_no_origin(api, accounts) -> None:
    read = token_for(accounts, "read")
    assert (await api.get("/api/v1/projects", headers=read)).status_code == 200
    refused = await api.post("/api/v1/projects", json={"name": "News"}, headers=read)
    assert (refused.status_code, refused.json()) == (403, {"detail": "insufficient_scope"})
    write = token_for(accounts, "write")
    assert (
        await api.post("/api/v1/projects", json={"name": "News"}, headers=write)
    ).status_code == 201


@pytest.mark.parametrize("case", ["unknown", "expired", "revoked"])
async def test_a_dead_token_is_not_authorized(api, accounts, case) -> None:
    if case == "unknown":
        headers = {"Authorization": "Bearer thoth_pat_unknown"}
    elif case == "expired":
        headers = token_for(accounts, "write", days=-1, secret="thoth_pat_expired")
    else:
        headers = token_for(accounts, "write", secret="thoth_pat_revoked")
        user = accounts.ensure_user("alice@acme.test", "Alice")
        assert accounts.revoke_token("tok_write1", "user", user.user_id)
    response = await api.get("/api/v1/projects", headers=headers)
    assert (response.status_code, response.json()) == (403, {"detail": "Not authorized"})


async def test_a_disabled_users_session_stops_working(api, accounts, engine) -> None:
    cookies = session_for(accounts)
    with engine.begin() as connection:
        connection.execute(text("UPDATE users SET disabled_at = CURRENT_TIMESTAMP"))
    assert (await api.get("/api/v1/projects", cookies=cookies)).status_code == 403


async def test_the_service_key_still_works_and_is_noted_at_most_once_a_minute(api, engine) -> None:
    for _ in range(3):
        assert (await api.get("/api/v1/projects", headers=SERVICE)).status_code == 200
    with engine.connect() as connection:
        noted = connection.scalar(
            select(func.count()).select_from(AuthEventRow).where(AuthEventRow.kind == "service_key")
        )
    assert noted == 1


def bearer_for(accounts: AccountStore, email: str, scope: str = "write") -> dict[str, str]:
    """A personal token of the user with this email, in that user's own workspace."""
    name = email.split("@")[0]
    user = accounts.ensure_user(email, name.title())
    secret = f"thoth_pat_{name}_{scope}"
    now = datetime.now(UTC)
    accounts.create_token(
        TokenRecord(
            f"tok_{name}_{scope}",
            "user",
            user.user_id,
            user.workspace_id,
            scope,
            secret[:16],
            scope,
            now - timedelta(days=1),
            now + timedelta(days=1),
            None,
        ),
        token_hash(secret),
    )
    return {"Authorization": f"Bearer {secret}"}


async def test_a_second_user_cannot_reach_the_first_users_project_or_workflow(
    api, accounts
) -> None:
    alice = bearer_for(accounts, "alice@acme.test")  # first user: the bootstrap workspace
    bob = bearer_for(accounts, "bob@acme.test")  # second user: a personal workspace
    project = (await api.post("/api/v1/projects", json={"name": "News"}, headers=alice)).json()
    started = await api.post(
        f"/api/v1/projects/{project['project_id']}/workflows",
        json=REQUEST,
        headers={**alice, "Idempotency-Key": "k1"},
    )
    workflow_id = started.json()["workflow_id"]

    assert (await api.get(f"/api/v1/workflows/{workflow_id}", headers=SERVICE)).status_code == 200
    foreign_project = await api.get(f"/api/v1/projects/{project['project_id']}", headers=bob)
    assert foreign_project.status_code == 404
    assert foreign_project.json() == {"detail": "project_not_found"}
    assert (await api.get("/api/v1/projects", headers=bob)).json()["items"] == []
    assert (await api.get(f"/api/v1/workflows/{workflow_id}", headers=bob)).status_code == 404
    runs = await api.get(f"/api/v1/projects/{project['project_id']}/workflows", headers=bob)
    assert runs.status_code == 404


async def test_the_data_actor_is_the_callers_workspace(api, accounts, gateway) -> None:
    alice = bearer_for(accounts, "alice@acme.test")
    bob = bearer_for(accounts, "bob@acme.test")
    await api.get("/api/v1/style-presets", headers=alice)
    assert gateway.actors[-1].actor_id == "owner"
    await api.get("/api/v1/style-presets", headers=bob)
    bob_workspace = accounts.ensure_user("bob@acme.test", "Bob").workspace_id
    assert gateway.actors[-1].actor_id == bob_workspace != "owner"


async def test_a_run_cannot_move_into_another_workspaces_project(api, accounts) -> None:
    alice = bearer_for(accounts, "alice@acme.test")
    bob = bearer_for(accounts, "bob@acme.test")
    project = (await api.post("/api/v1/projects", json={"name": "News"}, headers=alice)).json()
    started = await api.post(
        "/api/v1/workflows", json=REQUEST, headers={**bob, "Idempotency-Key": "kb"}
    )
    moved = await api.patch(
        f"/api/v1/workflows/{started.json()['workflow_id']}",
        json={"project_id": project["project_id"]},
        headers=bob,
    )
    assert moved.status_code == 404
    assert moved.json() == {"detail": "project_not_found"}


async def test_source_accounts_are_for_platform_admins_only(api, accounts) -> None:
    alice = bearer_for(accounts, "alice@acme.test", scope="admin")
    alice_write = bearer_for(accounts, "alice@acme.test", scope="write")
    bob = bearer_for(accounts, "bob@acme.test", scope="admin")
    refused = await api.get("/api/v1/source-accounts", headers=bob)
    assert refused.status_code == 403
    assert refused.json() == {"detail": "Not authorized"}
    assert (await api.get("/api/v1/source-accounts", headers=alice_write)).status_code == 403
    assert (await api.get("/api/v1/source-accounts", headers=alice)).status_code != 403
    assert (await api.get("/api/v1/source-accounts", headers=SERVICE)).status_code != 403


@pytest.mark.parametrize(
    ("method", "suffix", "body"),
    [
        ("GET", "/artifacts/art_1", None),
        ("GET", "/events", None),
        ("POST", "/cancel", None),
        ("POST", "/retry", {}),
        ("POST", "/approve", {"approval_id": "apr_1", "decision": "approve"}),
    ],
)
async def test_no_workflow_action_reaches_another_workspaces_run(
    api, accounts, method, suffix, body
) -> None:
    alice = bearer_for(accounts, "alice@acme.test")
    bob = bearer_for(accounts, "bob@acme.test")
    project = (await api.post("/api/v1/projects", json={"name": "News"}, headers=alice)).json()
    started = await api.post(
        f"/api/v1/projects/{project['project_id']}/workflows",
        json=REQUEST,
        headers={**alice, "Idempotency-Key": "k1"},
    )
    url = f"/api/v1/workflows/{started.json()['workflow_id']}{suffix}"
    response = await api.request(method, url, json=body, headers=bob)
    assert response.status_code == 404


async def test_a_workflow_cannot_start_under_another_workspaces_project(api, accounts) -> None:
    alice = bearer_for(accounts, "alice@acme.test")
    bob = bearer_for(accounts, "bob@acme.test")
    project = (await api.post("/api/v1/projects", json={"name": "News"}, headers=alice)).json()
    started = await api.post(
        f"/api/v1/projects/{project['project_id']}/workflows",
        json=REQUEST,
        headers={**bob, "Idempotency-Key": "kb"},
    )
    assert started.status_code == 404
    assert started.json() == {"detail": "project_not_found"}
