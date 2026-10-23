"""Map a Python-platform source URL to the acquirer that inspects it."""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from functools import partial
from pathlib import Path
from typing import Any, Protocol

import httpx

from thoth_control_plane.acquisition.accounts.access import SessionAccess
from thoth_control_plane.acquisition.adapters.tikwm import TikWmResolver
from thoth_control_plane.acquisition.browser import (
    ScraplingHeadlessBrowser,
    _default_session_factory,
)
from thoth_control_plane.acquisition.instagram_service import (
    InstagramAcquirer,
    InstagramHeadlessBrowser,
    InstagramRequestFetcher,
)
from thoth_control_plane.acquisition.materializer import MediaMaterializer
from thoth_control_plane.acquisition.models import AcquisitionResult
from thoth_control_plane.acquisition.platforms import platform_of
from thoth_control_plane.acquisition.service import TikTokAcquisitionService
from thoth_control_plane.acquisition.threads_service import (
    ThreadsAcquirer,
    ThreadsHeadlessBrowser,
    ThreadsRequestFetcher,
    _scrapling_get,
)
from thoth_control_plane.acquisition.x_fxembed import FxEmbedClient
from thoth_control_plane.acquisition.x_service import (
    XAcquirer,
    XHeadlessBrowser,
    XRequestFetcher,
)
from thoth_control_plane.acquisition.youtube_service import (
    YouTubeAcquirer,
    YouTubeHeadlessBrowser,
    YtDlpClient,
    _default_factory,
)


class Acquirer(Protocol):
    """One platform's single-post acquisition; it owns and closes its own browser."""

    async def inspect(
        self, *, workflow_id: str, source_url: str, artifact_root: Path
    ) -> AcquisitionResult: ...


def _browser_factory(access: SessionAccess | None) -> Callable[..., Any]:
    if access is None:
        return _default_session_factory
    extra = access.browser_kwargs()
    return lambda **kwargs: _default_session_factory(**kwargs, **extra)


def _request_get(access: SessionAccess | None) -> Callable[..., Awaitable[Any]] | None:
    return None if access is None else partial(_scrapling_get, **access.request_kwargs())


def _yt_dlp_factory(
    access: SessionAccess | None, scratch: Path | None
) -> Callable[[dict[str, Any]], Any] | None:
    if access is None:
        return None
    if scratch is None:
        raise ValueError("a yt-dlp session needs a scratch directory for its cookie file")
    extra = access.yt_dlp_options(scratch)
    return lambda options: _default_factory({**options, **extra})


def acquirer_for(
    source_url: str,
    *,
    client: httpx.AsyncClient,
    materializer: MediaMaterializer,
    access: SessionAccess | None = None,
    scratch: Path | None = None,
) -> Acquirer:
    """The platform's acquirer; with `access`, every request and browser carries the session.

    `scratch` is a private directory the caller removes afterwards; yt-dlp reads its cookie
    file from there.
    """
    platform = platform_of(source_url)
    browser = _browser_factory(access)
    get = _request_get(access)
    if platform == "tiktok":
        return TikTokAcquisitionService(
            ScraplingHeadlessBrowser(browser), TikWmResolver(client), materializer
        )
    if platform == "threads":
        return ThreadsAcquirer(
            ThreadsRequestFetcher(get), ThreadsHeadlessBrowser(browser), materializer
        )
    if platform == "instagram":
        return InstagramAcquirer(
            InstagramRequestFetcher(get), InstagramHeadlessBrowser(browser), materializer
        )
    if platform == "x":
        return XAcquirer(
            XRequestFetcher(get), XHeadlessBrowser(browser), materializer, FxEmbedClient()
        )
    if platform == "youtube":
        return YouTubeAcquirer(
            YtDlpClient(_yt_dlp_factory(access, scratch), signed_in=access is not None),
            YouTubeHeadlessBrowser(browser),
            materializer,
        )
    raise LookupError("no python acquirer for this platform")
