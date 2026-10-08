"""The Stage 3 profile discoverers behind one call. Threads has no profile discovery yet."""

from __future__ import annotations

from collections.abc import Callable, Mapping
from typing import Any

from thoth_control_plane.acquisition.models import DiscoveredVideo, ProfileDiscovery
from thoth_control_plane.attribution.models import Platform

PROFILE_LIMIT = 30


def _tiktok() -> Any:
    from thoth_control_plane.acquisition.discovery import ScraplingDiscoveryBrowser

    return ScraplingDiscoveryBrowser()


def _instagram() -> Any:
    from thoth_control_plane.acquisition.instagram_discovery import InstagramProfileDiscovery

    return InstagramProfileDiscovery()


def _x() -> Any:
    from thoth_control_plane.acquisition.x_discovery import XProfileDiscovery

    return XProfileDiscovery()


def _youtube() -> Any:
    from thoth_control_plane.acquisition.youtube_discovery import YouTubeChannelDiscovery

    return YouTubeChannelDiscovery()


DEFAULT_FACTORIES: Mapping[str, Callable[[], Any]] = {
    "tiktok": _tiktok,
    "instagram": _instagram,
    "x": _x,
    "youtube": _youtube,
}


class ProfileDiscoverer:
    def __init__(self, factories: Mapping[str, Callable[[], Any]] | None = None) -> None:
        self._factories = factories if factories is not None else DEFAULT_FACTORIES

    def supports(self, platform: Platform) -> bool:
        return platform in self._factories

    async def discover(self, platform: Platform, handle: str) -> list[DiscoveredVideo]:
        result = await self._factories[platform]().discover(
            ProfileDiscovery(handle=handle, limit=PROFILE_LIMIT)
        )
        return list(result.videos)
