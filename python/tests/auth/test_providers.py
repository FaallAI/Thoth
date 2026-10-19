"""Google and GitHub through Authlib with faked endpoints (spec section 5, testing)."""

import time
from urllib.parse import parse_qs, urlsplit

import httpx
from authlib.jose import JsonWebKey, jwt
from starlette.applications import Starlette
from starlette.middleware.sessions import SessionMiddleware
from starlette.responses import JSONResponse
from starlette.routing import Route

from thoth_control_plane.auth.models import SignInRefused
from thoth_control_plane.auth.providers import (
    GitHubProvider,
    GoogleProvider,
    build_providers,
    oauth_http,
)
from thoth_control_plane.config import Settings

CALLBACK = "http://testserver/callback"


def harness(provider) -> Starlette:
    async def login(request):
        return await provider.redirect(request, CALLBACK)

    async def callback(request):
        try:
            identity = await provider.identity(request)
        except SignInRefused as refused:
            return JSONResponse({"refused": refused.code})
        return JSONResponse({"subject": identity.subject, "email": identity.email})

    app = Starlette(routes=[Route("/login", login), Route("/callback", callback)])
    app.add_middleware(SessionMiddleware, secret_key="test-secret")
    return app


def client(app) -> httpx.AsyncClient:
    return httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://testserver")


def query(response: httpx.Response) -> dict[str, str]:
    return {k: v[0] for k, v in parse_qs(urlsplit(response.headers["location"]).query).items()}


def github_api(*, state: str | None = "active") -> oauth_http.MockTransport:
    def handler(request: oauth_http.Request) -> oauth_http.Response:
        url = str(request.url)
        if url == "https://github.com/login/oauth/access_token":
            return oauth_http.Response(200, json={"access_token": "t", "token_type": "bearer"})
        if url == "https://api.github.com/user":
            return oauth_http.Response(200, json={"id": 42, "login": "alice", "name": "Alice"})
        if url == "https://api.github.com/user/emails":
            return oauth_http.Response(
                200, json=[{"email": "Alice@Acme.test", "primary": True, "verified": True}]
            )
        if url == "https://api.github.com/user/memberships/orgs/acme" and state:
            return oauth_http.Response(
                200, json={"state": state, "organization": {"login": "acme"}}
            )
        return oauth_http.Response(404, json={"message": "Not Found"})

    return oauth_http.MockTransport(handler)


async def test_github_signs_in_an_active_member_through_a_real_redirect() -> None:
    app = harness(GitHubProvider("gh-id", "gh-secret", "acme", transport=github_api()))
    async with client(app) as http:
        login = await http.get("/login")
        assert login.headers["location"].startswith("https://github.com/login/oauth/authorize")
        params = query(login)
        assert params["code_challenge_method"] == "S256"
        assert "read:org" in params["scope"]
        result = (await http.get(f"/callback?code=c&state={params['state']}")).json()
    assert result == {"subject": "42", "email": "alice@acme.test"}


async def test_github_refuses_a_pending_member() -> None:
    app = harness(
        GitHubProvider("gh-id", "gh-secret", "acme", transport=github_api(state="pending"))
    )
    async with client(app) as http:
        state = query(await http.get("/login"))["state"]
        assert (await http.get(f"/callback?code=c&state={state}")).json() == {
            "refused": "not_allowed"
        }


async def test_a_replayed_or_foreign_callback_is_a_provider_error_not_a_crash() -> None:
    app = harness(GitHubProvider("gh-id", "gh-secret", "acme", transport=github_api()))
    async with client(app) as http:
        state = query(await http.get("/login"))["state"]
        await http.get(f"/callback?code=c&state={state}")
        replay = await http.get(f"/callback?code=c&state={state}")
    assert replay.json() == {"refused": "provider_error"}
    async with client(app) as stranger:  # no state cookie at all: another tab or browser
        foreign = await stranger.get("/callback?code=c&state=forged")
    assert foreign.json() == {"refused": "provider_error"}


KEY = JsonWebKey.generate_key("RSA", 2048, is_private=True, options={"kid": "k1"})
ISSUER = "https://accounts.test"


def google_api(nonce: dict[str, str], **claims) -> oauth_http.MockTransport:
    def handler(request: oauth_http.Request) -> oauth_http.Response:
        url = str(request.url)
        if url == f"{ISSUER}/.well-known/openid-configuration":
            return oauth_http.Response(
                200,
                json={
                    "issuer": ISSUER,
                    "authorization_endpoint": f"{ISSUER}/auth",
                    "token_endpoint": f"{ISSUER}/token",
                    "jwks_uri": f"{ISSUER}/jwks",
                    "id_token_signing_alg_values_supported": ["RS256"],
                },
            )
        if url == f"{ISSUER}/jwks":
            return oauth_http.Response(200, json={"keys": [KEY.as_dict(is_private=False)]})
        if url == f"{ISSUER}/token":
            now = int(time.time())
            body = {
                "iss": ISSUER,
                "aud": "g-id",
                "sub": "g-123",
                "iat": now,
                "exp": now + 600,
                "nonce": nonce["value"],
                "email": "alice@acme.test",
                "email_verified": True,
                "hd": "acme.test",
                "name": "Alice",
            } | claims
            token = jwt.encode({"alg": "RS256", "kid": "k1"}, body, KEY).decode()
            return oauth_http.Response(
                200,
                json={
                    "access_token": "a",
                    "token_type": "Bearer",
                    "expires_in": 600,
                    "id_token": token,
                },
            )
        return oauth_http.Response(404)

    return oauth_http.MockTransport(handler)


async def google_sign_in(**claims) -> dict:
    nonce: dict[str, str] = {}
    provider = GoogleProvider(
        "g-id",
        "g-secret",
        "acme.test",
        metadata_url=f"{ISSUER}/.well-known/openid-configuration",
        transport=google_api(nonce, **claims),
    )
    async with client(harness(provider)) as http:
        params = query(await http.get("/login"))
        nonce["value"] = params["nonce"]
        return (await http.get(f"/callback?code=c&state={params['state']}")).json()


async def test_google_signs_in_a_verified_domain_account_from_a_signed_id_token() -> None:
    assert await google_sign_in() == {"subject": "g-123", "email": "alice@acme.test"}


async def test_google_refuses_an_unverified_or_foreign_account() -> None:
    assert await google_sign_in(email_verified=False) == {"refused": "unverified_email"}
    assert await google_sign_in(email="eve@evil.test", hd=None) == {"refused": "not_allowed"}


async def test_google_refuses_a_token_for_another_audience() -> None:
    assert await google_sign_in(aud="someone-else") == {"refused": "provider_error"}


def test_only_fully_configured_providers_are_built() -> None:
    base = dict(
        THOTH_CONTROL_PLANE_API_KEY="k",
        THOTH_EDITOR_DATABASE_URL="postgresql://u:p@db/x",
        THOTH_AUTH_SECRET="s" * 32,
        THOTH_SMTP_HOST="smtp.test",
        THOTH_SMTP_FROM="no-reply@acme.test",
    )
    assert build_providers(Settings(**base)) == {}
    both = build_providers(
        Settings(
            **base,
            THOTH_AUTH_GOOGLE_CLIENT_ID="g",
            THOTH_AUTH_GOOGLE_CLIENT_SECRET="s",
            THOTH_AUTH_GOOGLE_DOMAIN="acme.test",
            THOTH_AUTH_GITHUB_CLIENT_ID="h",
            THOTH_AUTH_GITHUB_CLIENT_SECRET="s",
            THOTH_AUTH_GITHUB_ORG="acme",
        )
    )
    assert sorted(both) == ["github", "google"]
