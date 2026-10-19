"""The caller's account and personal developer tokens (spec 3.3)."""

from datetime import UTC, datetime, timedelta

import httpx
import pytest
from sqlalchemy import create_engine
from sqlalchemy.pool import StaticPool

from thoth_control_plane.api import create_app
from thoth_control_plane.auth.models import BOOTSTRAP_WORKSPACE_ID
from thoth_control_plane.auth.secrets import token_hash
from thoth_control_plane.config import Settings
from thoth_control_plane.infrastructure import account_models  # noqa: F401
from thoth_control_plane.infrastructure.account_models import WorkspaceRow
from thoth_control_plane.infrastructure.account_store import AccountStore
from thoth_control_plane.infrastructure.source_account_models import Base

ORIGIN = "http://localhost:8088"
SAME_SITE = {"Origin": ORIGIN}


def build(gateway, **settings):
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
    accounts = AccountStore(engine)
    user = accounts.ensure_user("alice@acme.test", "Alice")
    accounts.create_session(
        user.user_id, user.workspace_id, token_hash("ses"), datetime.now(UTC) + timedelta(hours=1)
    )
    app = create_app(
        Settings(THOTH_CONTROL_PLANE_API_KEY="test-key", THOTH_SITE_ORIGIN=ORIGIN, **settings),
        gateway,
        account_store=accounts,
    )
    client = httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url=ORIGIN)
    client.cookies.set("thoth_session", "ses")
    return client


@pytest.fixture
async def api(gateway):
    async with build(gateway) as client:
        yield client


async def test_me_names_the_signed_in_user(api) -> None:
    me = (await api.get("/api/v1/me")).json()
    assert (me["email"], me["workspace_id"], me["scopes"]) == (
        "alice@acme.test",
        BOOTSTRAP_WORKSPACE_ID,
        ["admin", "read", "write"],
    )


async def test_a_token_is_shown_once_listed_without_secret_and_revoked(api) -> None:
    made = await api.post(
        "/api/v1/me/tokens",
        json={"name": "laptop", "scope": "write", "days": 30},
        headers=SAME_SITE,
    )
    assert made.status_code == 201
    secret = made.json()["secret"]
    listed = (await api.get("/api/v1/me/tokens")).json()
    assert [t["name"] for t in listed] == ["laptop"] and "secret" not in listed[0]
    bearer = {"Authorization": f"Bearer {secret}"}
    assert (await api.get("/api/v1/me", headers=bearer)).status_code == 200
    token_id = made.json()["token"]["token_id"]
    assert (await api.delete(f"/api/v1/me/tokens/{token_id}", headers=SAME_SITE)).status_code == 204
    assert (await api.get("/api/v1/me", headers=bearer)).status_code == 403
    assert (await api.delete(f"/api/v1/me/tokens/{token_id}", headers=SAME_SITE)).status_code == 404


async def test_a_write_token_cannot_manage_tokens_and_the_service_key_has_no_user(api) -> None:
    made = (await api.post("/api/v1/me/tokens", json={"name": "ci"}, headers=SAME_SITE)).json()
    bearer = {"Authorization": f"Bearer {made['secret']}"}
    refused = await api.get("/api/v1/me/tokens", headers=bearer)
    assert (refused.status_code, refused.json()) == (403, {"detail": "insufficient_scope"})
    service = await api.get("/api/v1/me/tokens", headers={"Authorization": "Bearer test-key"})
    assert (service.status_code, service.json()) == (403, {"detail": "user_required"})


async def test_the_twenty_first_token_is_refused(api) -> None:
    for index in range(20):
        await api.post("/api/v1/me/tokens", json={"name": f"t{index}"}, headers=SAME_SITE)
    over = await api.post("/api/v1/me/tokens", json={"name": "more"}, headers=SAME_SITE)
    assert (over.status_code, over.json()) == (409, {"detail": "token_limit"})


async def test_workspace_tokens_are_refused_until_the_operator_enables_them(gateway) -> None:
    async with build(gateway) as off:
        refused = await off.post(
            "/api/v1/workspace/tokens", json={"name": "partner"}, headers=SAME_SITE
        )
        assert (refused.status_code, refused.json()) == (
            403,
            {"detail": "workspace_tokens_disabled"},
        )
    async with build(gateway, THOTH_AUTH_WORKSPACE_TOKENS=True) as on:
        made = await on.post(
            "/api/v1/workspace/tokens", json={"name": "partner"}, headers=SAME_SITE
        )
        assert made.status_code == 201 and made.json()["token"]["owner_kind"] == "workspace"
