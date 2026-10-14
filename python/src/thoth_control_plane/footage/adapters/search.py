"""Footage search per platform (spec 2026-10-14, F4): TikTok and YouTube per query under the
platform's access mode; X in one signed-in session per run (operator, 2026-10-15, option A)."""

from __future__ import annotations

import logging
from collections.abc import Callable, Mapping, Sequence
from pathlib import Path
from typing import Any

from thoth_control_plane.acquisition.accounts.access import SessionAccess
from thoth_control_plane.acquisition.accounts.policy import Outcome
from thoth_control_plane.acquisition.models import DiscoveredVideo, KeywordDiscovery
from thoth_control_plane.attribution.adapters.discovery import (
    AccountLeases,
    DiscoveryFactory,
    ProfileDiscoverer,
    _tiktok,
)
from thoth_control_plane.attribution.adapters.frames import ToolMissing
from thoth_control_plane.footage.models import SearchBatch

logger = logging.getLogger(__name__)


def _youtube(access: SessionAccess | None, scratch: Path) -> Any:
    from thoth_control_plane.acquisition.registry import _yt_dlp_factory
    from thoth_control_plane.acquisition.youtube_service import YtDlpClient
    from thoth_control_plane.footage.adapters.youtube import YouTubeSearchDiscovery

    factory = _yt_dlp_factory(access, scratch)
    return YouTubeSearchDiscovery(YtDlpClient(factory, signed_in=access is not None))


def _x_search(access: SessionAccess | None) -> Any:
    from thoth_control_plane.acquisition.registry import _browser_factory
    from thoth_control_plane.footage.adapters.x_search import XSearchDiscovery

    return XSearchDiscovery(_browser_factory(access))


SEARCH_FACTORIES: Mapping[str, DiscoveryFactory] = {"tiktok": _tiktok, "youtube": _youtube}


def _valid(query: str) -> bool:
    try:
        KeywordDiscovery(query=query, limit=1)
    except ValueError:
        logger.warning("footage query refused by the search contract")
        return False
    return True


class PlatformSearch:
    def __init__(
        self,
        discoverer: ProfileDiscoverer,
        leases: AccountLeases | None,
        *,
        x_search: Callable[[SessionAccess | None], Any] = _x_search,
    ) -> None:
        self._discoverer = discoverer
        self._leases = leases
        self._x_search = x_search

    async def search(self, platform: str, queries: Sequence[str], limit: int) -> SearchBatch:
        valid = [query for query in queries if _valid(query)]
        if platform == "x":
            return await self._x(valid, limit)
        found: dict[str, list[DiscoveredVideo]] = {}
        for query in valid:
            try:
                found[query] = await self._discoverer.list(
                    platform, KeywordDiscovery(query=query, limit=limit)
                )
            except ToolMissing:
                raise
            except Exception:
                logger.warning("footage search stopped platform=%s", platform)
                return SearchBatch(found=found, failed=True)
        return SearchBatch(found=found, failed=False)

    async def _x(self, queries: Sequence[str], limit: int) -> SearchBatch:
        if not queries:
            return SearchBatch(found={}, failed=False)
        lease = await self._leases.lease("x") if self._leases is not None else None
        if lease is None:
            # Signed out, X search returns nothing; never spend a browser on it.
            logger.info("no X account free for footage search")
            return SearchBatch(found={}, failed=True)
        outcome: Outcome | None = None
        try:
            batch = await self._x_search(lease.access).search_many(queries, limit)
            if batch.refused:
                outcome = "blocked"
            elif any(batch.found.values()):
                outcome = "success"
        finally:
            assert self._leases is not None
            await self._leases.release(lease, outcome)
        logger.info(
            "x footage search queries=%d answered=%d outcome=%s",
            len(queries),
            len(batch.found),
            outcome,
        )
        failed = batch.refused or (batch.unavailable and not batch.found)
        return SearchBatch(found=batch.found, failed=failed)


def build_platform_search(leases: AccountLeases | None) -> PlatformSearch:
    return PlatformSearch(ProfileDiscoverer(SEARCH_FACTORIES, leases=leases), leases)
