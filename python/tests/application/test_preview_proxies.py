"""Preview proxies (spec 2026-11-18): built once on first need, kept, never fatal."""

from __future__ import annotations

import asyncio
from pathlib import Path

import pytest

from thoth_control_plane.application.preview_proxies import PreviewProxyService, proxy_location
from thoth_control_plane.infrastructure.media_store import MediaUnavailable
from thoth_control_plane.infrastructure.preview_proxy_builder import ProxyBuildFailed

pytestmark = pytest.mark.asyncio


class Media:
    def __init__(self) -> None:
        self.kept: dict[str, bytes] = {}

    def size(self, location: str) -> int:
        if location not in self.kept:
            raise MediaUnavailable(location)
        return len(self.kept[location])

    def probe_source(self, location: str) -> str:
        return f"/store/{location}"

    def put_file(self, location: str, path: Path) -> None:
        self.kept[location] = path.read_bytes()


class Builder:
    def __init__(self, fail: bool = False) -> None:
        self.calls: list[str] = []
        self.fail = fail

    async def __call__(self, _ffmpeg: str, source: str, _type: str, destination: Path) -> None:
        self.calls.append(source)
        await asyncio.sleep(0)
        if self.fail:
            raise ProxyBuildFailed("refused")
        destination.write_bytes(b"proxy")


LOCATION = proxy_location("project_001", "asset_main")
ASK = ("project_001", "asset_main", "uploads/a.mp4", "video/mp4")


async def test_a_requested_proxy_is_built_once_and_kept() -> None:
    media, build = Media(), Builder()
    proxies = PreviewProxyService(media, "ffmpeg", build=build)
    assert not await proxies.ready("project_001", "asset_main")
    proxies.request(*ASK)
    proxies.request(*ASK)  # in flight: not started again
    await proxies.idle()
    assert build.calls == ["/store/uploads/a.mp4"]
    assert media.kept[LOCATION] == b"proxy"
    assert await proxies.ready("project_001", "asset_main")
    proxies.request(*ASK)  # kept already
    await proxies.idle()
    assert build.calls == ["/store/uploads/a.mp4"]


async def test_a_failed_build_keeps_nothing_and_is_not_tried_again() -> None:
    media, build = Media(), Builder(fail=True)
    proxies = PreviewProxyService(media, "ffmpeg", build=build)
    proxies.request(*ASK)
    await proxies.idle()
    proxies.request(*ASK)
    await proxies.idle()
    assert build.calls == ["/store/uploads/a.mp4"]
    assert media.kept == {}


async def test_the_proxy_lives_beside_the_asset_under_previews() -> None:
    assert LOCATION == "previews/project_001/asset_main.v1.mp4"
