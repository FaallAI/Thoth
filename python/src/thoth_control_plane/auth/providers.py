"""Google (OpenID Connect) and GitHub (OAuth 2) through Authlib's Starlette client.

Every provider failure, including a missing or replayed state, becomes `provider_error`; the
provider's own text never reaches the caller.
"""

from __future__ import annotations

from typing import Protocol
from urllib.parse import quote

from authlib.common.errors import AuthlibBaseError
from authlib.integrations.starlette_client import OAuth
from joserfc.errors import JoseError
from starlette.requests import Request
from starlette.responses import Response

from thoth_control_plane.auth.models import SignInRefused, VerifiedIdentity
from thoth_control_plane.auth.rules import github_identity, google_identity
from thoth_control_plane.config import Settings

try:  # Authlib's own choice: httpx2 when installed, else httpx (authlib httpx_client._compat).
    import httpx2 as oauth_http
except ImportError:  # pragma: no cover - depends on the installed extras
    import httpx as oauth_http  # type: ignore[no-redef]

GOOGLE_METADATA = "https://accounts.google.com/.well-known/openid-configuration"
#: Failures a provider round trip can raise; all of them mean `provider_error`.
#: An invalid id_token raises joserfc's JoseError, which is not an Authlib error.
PROVIDER_FAILURES = (
    AuthlibBaseError,
    JoseError,
    oauth_http.HTTPError,
    KeyError,
    TypeError,
    ValueError,
)


class IdentityProvider(Protocol):
    name: str

    async def redirect(self, request: Request, redirect_uri: str) -> Response: ...

    async def identity(self, request: Request) -> VerifiedIdentity: ...


def _client_kwargs(scope: str, transport: oauth_http.AsyncBaseTransport | None) -> dict[str, object]:
    kwargs: dict[str, object] = {"scope": scope, "code_challenge_method": "S256"}
    if transport is not None:
        kwargs["transport"] = transport
    return kwargs


class GoogleProvider:
    name = "google"

    def __init__(
        self,
        client_id: str,
        client_secret: str,
        domain: str,
        *,
        metadata_url: str = GOOGLE_METADATA,
        transport: oauth_http.AsyncBaseTransport | None = None,
    ) -> None:
        self._domain = domain
        self._client = OAuth().register(
            "google",
            client_id=client_id,
            client_secret=client_secret,
            server_metadata_url=metadata_url,
            client_kwargs=_client_kwargs("openid email profile", transport),
        )

    async def redirect(self, request: Request, redirect_uri: str) -> Response:
        return await self._client.authorize_redirect(request, redirect_uri)

    async def identity(self, request: Request) -> VerifiedIdentity:
        try:
            token = await self._client.authorize_access_token(request)
        except PROVIDER_FAILURES:
            raise SignInRefused("provider_error") from None
        return google_identity(token.get("userinfo") or {}, self._domain)


class GitHubProvider:
    name = "github"

    def __init__(
        self,
        client_id: str,
        client_secret: str,
        org: str,
        *,
        transport: oauth_http.AsyncBaseTransport | None = None,
    ) -> None:
        self._org = org
        self._client = OAuth().register(
            "github",
            client_id=client_id,
            client_secret=client_secret,
            access_token_url="https://github.com/login/oauth/access_token",
            authorize_url="https://github.com/login/oauth/authorize",
            api_base_url="https://api.github.com/",
            client_kwargs=_client_kwargs("read:user user:email read:org", transport),
        )

    async def redirect(self, request: Request, redirect_uri: str) -> Response:
        return await self._client.authorize_redirect(request, redirect_uri)

    async def identity(self, request: Request) -> VerifiedIdentity:
        try:
            token = await self._client.authorize_access_token(request)
            user = await self._client.get("user", token=token)
            user.raise_for_status()
            emails = await self._client.get("user/emails", token=token)
            emails.raise_for_status()
            membership = await self._client.get(
                f"user/memberships/orgs/{quote(self._org, safe='')}", token=token
            )
            found = membership.json() if membership.status_code == 200 else None
            listed = emails.json()
            return github_identity(
                user.json(), listed if isinstance(listed, list) else [], found, self._org
            )
        except PROVIDER_FAILURES:
            raise SignInRefused("provider_error") from None


def build_providers(
    settings: Settings, transport: oauth_http.AsyncBaseTransport | None = None
) -> dict[str, IdentityProvider]:
    """Only providers whose client, rule, secret, database and mail are all configured."""
    providers: dict[str, IdentityProvider] = {}
    if settings.google_sign_in_enabled:
        providers["google"] = GoogleProvider(
            settings.THOTH_AUTH_GOOGLE_CLIENT_ID or "",
            settings.THOTH_AUTH_GOOGLE_CLIENT_SECRET.get_secret_value(),  # type: ignore[union-attr]
            settings.THOTH_AUTH_GOOGLE_DOMAIN or "",
            transport=transport,
        )
    if settings.github_sign_in_enabled:
        providers["github"] = GitHubProvider(
            settings.THOTH_AUTH_GITHUB_CLIENT_ID or "",
            settings.THOTH_AUTH_GITHUB_CLIENT_SECRET.get_secret_value(),  # type: ignore[union-attr]
            settings.THOTH_AUTH_GITHUB_ORG or "",
            transport=transport,
        )
    return providers
