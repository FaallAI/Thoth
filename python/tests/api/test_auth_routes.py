"""The sign-in round trip with a fake provider and a fake mailer (spec section 2)."""

import re
from datetime import UTC, datetime

import httpx
import pytest
from sqlalchemy import create_engine
from sqlalchemy.pool import StaticPool
from starlette.responses import RedirectResponse

from thoth_control_plane.api import create_app
from thoth_control_plane.auth.models import BOOTSTRAP_WORKSPACE_ID, SignInRefused, VerifiedIdentity
from thoth_control_plane.config import Settings
from thoth_control_plane.infrastructure import account_models  # noqa: F401
from thoth_control_plane.infrastructure.account_models import WorkspaceRow
from thoth_control_plane.infrastructure.account_store import AccountStore
from thoth_control_plane.infrastructure.source_account_models import Base

ORIGIN = "http://localhost:8088"
SAME_SITE = {"Origin": ORIGIN}
ALICE = VerifiedIdentity("google", "g1", "alice@acme.test", "Alice")


class FakeProvider:
    name = "google"

    def __init__(self) -> None:
        self.identity_or_error: VerifiedIdentity | str = ALICE

    async def redirect(self, request, redirect_uri):
        request.session["started"] = True
        return RedirectResponse(f"https://idp.test/authorize?redirect_uri={redirect_uri}", 302)

    async def identity(self, request):
        if isinstance(self.identity_or_error, str):
            raise SignInRefused(self.identity_or_error)
        return self.identity_or_error


class FakeMailer:
    def __init__(self) -> None:
        self.bodies: list[str] = []

    async def send(self, to, subject, body):
        self.bodies.append(body)

    @property
    def code(self) -> str:
        return re.search(r"\b(\d{6})\b", self.bodies[-1]).group(1)


@pytest.fixture
def provider() -> FakeProvider:
    return FakeProvider()


@pytest.fixture
def mailer() -> FakeMailer:
    return FakeMailer()


@pytest.fixture
async def api(gateway, provider, mailer):
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
    settings = Settings(
        THOTH_CONTROL_PLANE_API_KEY="test-key", THOTH_SITE_ORIGIN=ORIGIN, THOTH_AUTH_SECRET="s" * 32
    )
    app = create_app(
        settings,
        gateway,
        account_store=AccountStore(engine),
        mailer=mailer,
        identity_providers={"google": provider},
    )
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url=ORIGIN) as client:
        yield client


async def callback(api) -> httpx.Response:
    await api.get("/auth/login/google?next=/studio")
    return await api.get("/auth/callback/google?code=c&state=s")


async def sign_in(api, mailer, *, trust=True) -> None:
    await callback(api)
    done = await api.post(
        "/auth/verify",
        json={"code": mailer.code, "trust_device": trust, "next": "/studio"},
        headers=SAME_SITE,
    )
    assert done.status_code == 200 and done.json() == {"next": "/studio"}


async def test_providers_lists_only_the_configured_ones(api) -> None:
    assert (await api.get("/auth/providers")).json() == {"providers": ["google"]}


async def test_an_unknown_provider_is_not_configured(api) -> None:
    response = await api.get("/auth/login/okta")
    assert (response.status_code, response.headers["location"]) == (
        303,
        "/login?error=not_configured",
    )


async def test_a_refused_identity_returns_to_login_with_its_code(api, provider) -> None:
    provider.identity_or_error = "not_allowed"
    response = await callback(api)
    assert response.headers["location"] == "/login?error=not_allowed"
    assert "thoth_session" not in response.cookies


async def test_the_first_sign_in_asks_for_the_emailed_code(api, mailer) -> None:
    response = await callback(api)
    assert response.headers["location"] == "/login/verify?next=/studio"
    assert "thoth_challenge" in response.cookies and len(mailer.bodies) == 1
    assert (await api.get("/auth/me")).status_code == 401


async def test_the_code_signs_in_and_the_browser_is_then_trusted(api, mailer) -> None:
    await sign_in(api, mailer)
    me = (await api.get("/auth/me")).json()
    assert (me["email"], me["display_name"], me["workspace_id"]) == (
        "alice@acme.test",
        "Alice",
        BOOTSTRAP_WORKSPACE_ID,
    )
    api.cookies.delete("thoth_session")
    again = await callback(api)
    assert again.headers["location"] == "/studio" and len(mailer.bodies) == 1


async def test_a_wrong_code_a_cross_site_verify_and_a_missing_challenge_are_refused(
    api, mailer
) -> None:
    await callback(api)
    wrong = "000000" if mailer.code != "000000" else "111111"
    bad = await api.post("/auth/verify", json={"code": wrong}, headers=SAME_SITE)
    assert (bad.status_code, bad.json()) == (400, {"detail": "wrong_code"})
    cross = await api.post("/auth/verify", json={"code": mailer.code})
    assert (cross.status_code, cross.json()) == (403, {"detail": "cross_site_request"})
    api.cookies.delete("thoth_challenge", path="/auth")
    gone = await api.post("/auth/verify", json={"code": mailer.code}, headers=SAME_SITE)
    assert (gone.status_code, gone.json()) == (400, {"detail": "expired"})


async def test_resend_is_throttled(api, mailer) -> None:
    await callback(api)
    response = await api.post("/auth/resend", headers=SAME_SITE)
    assert (response.status_code, response.json()) == (429, {"detail": "resend_too_soon"})


@pytest.mark.parametrize("target", ["//evil.test/x", "https://evil.test", "evil", "/\\evil.test"])
async def test_next_never_leaves_the_site(api, mailer, target) -> None:
    await api.get("/auth/login/google", params={"next": target})
    response = await api.get("/auth/callback/google?code=c&state=s")
    assert response.headers["location"] == "/login/verify?next=/workflows"


async def test_logout_ends_the_session_and_can_forget_the_browser(api, mailer) -> None:
    await sign_in(api, mailer)
    out = await api.post("/auth/logout", json={"forget_device": True}, headers=SAME_SITE)
    assert out.status_code == 204
    assert (await api.get("/auth/me")).status_code == 401
    await callback(api)
    assert len(mailer.bodies) == 2  # the browser is no longer trusted


async def test_me_accepts_a_developer_token_for_the_local_dashboard(api, mailer) -> None:
    response = await api.get("/auth/me", headers={"Authorization": "Bearer test-key"})
    assert response.status_code == 200 and response.json()["user_id"] is None
