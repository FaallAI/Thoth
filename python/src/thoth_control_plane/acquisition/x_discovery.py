"""X profile discovery: the handle's own media posts, from FxEmbed's profile media listing.

X's signed-out profile page stopped embedding its timeline in October 2026 (spec 2026-10-23),
so one FxEmbed GET replaces it; no account is needed. Never raises; every failure is a
`DiscoveryResult` with a reason.
"""

from __future__ import annotations

import logging

from thoth_control_plane.acquisition.adapters.fxembed import fx_profile
from thoth_control_plane.acquisition.adapters.x import (
    HANDLE,
)
from thoth_control_plane.acquisition.discovery import _empty
from thoth_control_plane.acquisition.instagram_discovery import _reason
from thoth_control_plane.acquisition.models import (
    DiscoveryReason,
    DiscoveryResult,
    ProfileDiscovery,
)
from thoth_control_plane.acquisition.threads_service import RequestFetchError
from thoth_control_plane.acquisition.x_fxembed import FxEmbedClient

logger = logging.getLogger(__name__)


class XProfileDiscovery:
    """A profile's own media posts, from FxEmbed (spec 2026-10-23): X's signed-out profile page
    no longer embeds its timeline, and no account is needed."""

    def __init__(self, fxembed: FxEmbedClient | None = None) -> None:
        self._fxembed = fxembed or FxEmbedClient()

    async def discover(self, request: ProfileDiscovery) -> DiscoveryResult:
        result = await self._collect(request)
        reason = result.reason.value if result.reason is not None else "none"
        logger.info(
            "x discovery finished kind=profile videos=%d photos=%d photo_posts=%d invalid=%d"
            " reason=%s",
            len(result.videos),
            len(result.photos),
            result.drops.photo_posts,
            result.drops.invalid,
            reason,
        )
        if result.reason is not None:
            logger.warning("x discovery stopped early kind=profile reason=%s", reason)
        return result

    async def _collect(self, request: ProfileDiscovery) -> DiscoveryResult:
        if HANDLE.fullmatch(request.handle) is None:
            # A handle X cannot have names no profile; skip the fetch.
            return _empty("profile", DiscoveryReason.NO_DATA)
        try:
            payload = await self._fxembed.profile_media(request.handle, request.limit)
        except RequestFetchError as error:
            return _empty("profile", _reason(error))
        try:
            return fx_profile(payload, request.handle, request.limit)
        except Exception:
            # Defense in depth: discovery never raises on an unforeseen answer shape.
            return _empty("profile", DiscoveryReason.NO_DATA)
