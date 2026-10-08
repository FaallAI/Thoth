"""The Stage 3 profile discoverers behind one call, with a source account when needed.

The platform's access mode decides, as it does for acquisition (operator, 2026-10-09):
`anonymous` never leases; `always` leases first and runs anonymously when no account is
free; `fallback` runs anonymously and leases once when the platform answered with a captcha
or a block. TikTok profile pages captcha an anonymous browser, so they need an account.
Threads has no profile discovery yet.
"""

from __future__ import annotations

import asyncio
import logging
import tempfile
from collections.abc import Callable, Mapping
from pathlib import Path
from typing import Any, Protocol

from thoth_control_plane.acquisition.accounts.access import SessionAccess
from thoth_control_plane.acquisition.accounts.policy import Mode, Outcome
from thoth_control_plane.acquisition.models import (
    DiscoveredVideo,
    DiscoveryReason,
    DiscoveryResult,
    ProfileDiscovery,
)
from thoth_control_plane.attribution.models import Platform
from thoth_control_plane.infrastructure.source_account_store import (
    AccountLease,
    SourceAccountStore,
)

logger = logging.getLogger(__name__)

PROFILE_LIMIT = 30
RETRY_REASONS = frozenset({DiscoveryReason.CAPTCHA, DiscoveryReason.BLOCKED})
DiscoveryFactory = Callable[[SessionAccess | None, Path], Any]


class AccountLeases(Protocol):
    async def mode(self, platform: Platform) -> Mode: ...

    async def lease(self, platform: Platform) -> AccountLease | None: ...

    async def release(self, lease: AccountLease, outcome: Outcome | None) -> None: ...


class StoreLeases:
    """Leases from the source-account store; a store failure means "no account"."""

    def __init__(self, store: SourceAccountStore) -> None:
        self._store = store

    async def mode(self, platform: Platform) -> Mode:
        try:
            return (await asyncio.to_thread(self._store.policy, platform)).mode
        except Exception:
            logger.warning("source account policy unavailable; discovery runs anonymously")
            return "anonymous"

    async def lease(self, platform: Platform) -> AccountLease | None:
        try:
            return await asyncio.to_thread(self._store.lease, platform)
        except Exception:
            logger.warning("source account lease unavailable; discovery runs anonymously")
            return None

    async def release(self, lease: AccountLease, outcome: Outcome | None) -> None:
        try:
            await asyncio.to_thread(
                self._store.report, lease.account_id, outcome, lease.leased_until
            )
        except Exception:
            logger.warning("source account release failed; its lease expires on its own")


def _tiktok(access: SessionAccess | None, scratch: Path) -> Any:
    from thoth_control_plane.acquisition.discovery import ScraplingDiscoveryBrowser
    from thoth_control_plane.acquisition.registry import _browser_factory

    return ScraplingDiscoveryBrowser(_browser_factory(access))


def _instagram(access: SessionAccess | None, scratch: Path) -> Any:
    from thoth_control_plane.acquisition.instagram_discovery import InstagramProfileDiscovery
    from thoth_control_plane.acquisition.instagram_service import InstagramRequestFetcher
    from thoth_control_plane.acquisition.registry import _request_get

    return InstagramProfileDiscovery(InstagramRequestFetcher(_request_get(access)))


def _x(access: SessionAccess | None, scratch: Path) -> Any:
    from thoth_control_plane.acquisition.registry import _request_get
    from thoth_control_plane.acquisition.x_discovery import XProfileDiscovery
    from thoth_control_plane.acquisition.x_service import XRequestFetcher

    return XProfileDiscovery(XRequestFetcher(_request_get(access)))


def _youtube(access: SessionAccess | None, scratch: Path) -> Any:
    from thoth_control_plane.acquisition.registry import _yt_dlp_factory
    from thoth_control_plane.acquisition.youtube_discovery import YouTubeChannelDiscovery
    from thoth_control_plane.acquisition.youtube_service import YtDlpClient

    factory = _yt_dlp_factory(access, scratch)
    return YouTubeChannelDiscovery(YtDlpClient(factory, signed_in=access is not None))


DEFAULT_FACTORIES: Mapping[str, DiscoveryFactory] = {
    "tiktok": _tiktok,
    "instagram": _instagram,
    "x": _x,
    "youtube": _youtube,
}


class ProfileDiscoverer:
    def __init__(
        self,
        factories: Mapping[str, DiscoveryFactory] | None = None,
        *,
        leases: AccountLeases | None = None,
    ) -> None:
        self._factories = factories if factories is not None else DEFAULT_FACTORIES
        self._leases = leases

    def supports(self, platform: Platform) -> bool:
        return platform in self._factories

    async def discover(self, platform: Platform, handle: str) -> list[DiscoveredVideo]:
        mode: Mode = await self._leases.mode(platform) if self._leases else "anonymous"
        if mode != "always":
            anonymous = await self._run(platform, handle, None)
            if mode == "anonymous" or anonymous.videos or anonymous.reason not in RETRY_REASONS:
                return list(anonymous.videos)
        assert self._leases is not None  # a leasing mode implies a lease source
        lease = await self._leases.lease(platform)
        if lease is None:
            logger.info("no source account for discovery platform=%s mode=%s", platform, mode)
            if mode == "always":
                return list((await self._run(platform, handle, None)).videos)
            return []
        outcome: Outcome | None = None
        try:
            result = await self._run(platform, handle, lease.access)
            if result.videos:
                outcome = "success"
            elif result.reason in RETRY_REASONS:
                outcome = "blocked"
        finally:
            await self._leases.release(lease, outcome)
        logger.info("discovery used a source account platform=%s outcome=%s", platform, outcome)
        return list(result.videos)

    async def _run(
        self, platform: Platform, handle: str, access: SessionAccess | None
    ) -> DiscoveryResult:
        # A private directory for yt-dlp's cookie file, removed with everything in it.
        with tempfile.TemporaryDirectory(prefix="thoth-discovery-") as scratch:
            discovery = self._factories[platform](access, Path(scratch))
            return await discovery.discover(ProfileDiscovery(handle=handle, limit=PROFILE_LIMIT))
