"""Tier 3b: an asset's glance is built once, cached beside the asset, and failures are not kept."""

from __future__ import annotations

import shutil
from pathlib import Path

import pytest

from thoth_control_plane.application.asset_glances import (
    AssetGlanceService,
    GlanceUnavailable,
    glance_location,
)
from thoth_control_plane.application.editor_assets import EditorAssetNotFound, EditorAssetService
from thoth_control_plane.domain.asset_glance import AssetGlance, GlancePeaks
from thoth_control_plane.domain.editor_assets import EditorAsset, EditorAssetRecord
from thoth_control_plane.infrastructure.asset_glance_builder import (
    GlanceBuildFailed,
    GlanceToolMissing,
)
from thoth_control_plane.infrastructure.media_store import MediaUnavailable


def record() -> EditorAssetRecord:
    return EditorAssetRecord(
        asset=EditorAsset(
            asset_id="asset_music",
            project_id="project_001",
            kind="audio",
            media_type="audio/mpeg",
            duration_in_frames=60,
            has_audio=True,
            validation_state="ready",
        ),
        artifact_location="uploads/project_001/asset_music.mp3",
        provenance="operator_upload",
    )


class Repository:
    async def get_ready_record(self, *, project_id: str, asset_id: str):
        return record() if (project_id, asset_id) == ("project_001", "asset_music") else None


class Media:
    """A dict-backed store: enough of MediaStore for the glance."""

    def __init__(self) -> None:
        self.objects: dict[str, bytes] = {}

    def probe_source(self, location: str) -> str:
        return f"/media/{location}"

    def fetch(self, location: str, destination: Path) -> None:
        if location not in self.objects:
            raise MediaUnavailable("media_unavailable")
        destination.write_bytes(self.objects[location])

    def put_file(self, location: str, path: Path) -> None:
        self.objects[location] = path.read_bytes()


GLANCE = AssetGlance(asset_id="asset_music", peaks=GlancePeaks(seconds_per_peak=0.1, values=[3, 9]))


def service(media: Media, build) -> AssetGlanceService:
    return AssetGlanceService(EditorAssetService(Repository()), media, "ffmpeg", build=build)


async def test_a_miss_builds_once_and_a_hit_reads_the_cache() -> None:
    media, calls = Media(), []

    async def build(ffmpeg: str, source: str, asset: EditorAsset) -> AssetGlance:
        calls.append(source)
        return GLANCE

    glances = service(media, build)
    assert await glances.glance("project_001", "asset_music") == GLANCE
    assert await glances.glance("project_001", "asset_music") == GLANCE
    assert calls == ["/media/uploads/project_001/asset_music.mp3"]
    assert glance_location("project_001", "asset_music") == "glance/project_001/asset_music.v1.json"
    assert list(media.objects) == ["glance/project_001/asset_music.v1.json"]


async def test_a_failed_build_is_not_kept() -> None:
    media = Media()

    async def build(*_: object) -> AssetGlance:
        raise GlanceBuildFailed("ffmpeg refused the source")

    with pytest.raises(GlanceUnavailable) as raised:
        await service(media, build).glance("project_001", "asset_music")
    assert raised.value.code == "glance_failed"
    assert media.objects == {}


async def test_a_missing_ffmpeg_is_named() -> None:
    async def build(*_: object) -> AssetGlance:
        raise GlanceToolMissing("ffmpeg")

    with pytest.raises(GlanceUnavailable) as raised:
        await service(Media(), build).glance("project_001", "asset_music")
    assert raised.value.code == "ffmpeg_unavailable"


async def test_an_unknown_or_foreign_asset_is_not_found() -> None:
    async def build(*_: object) -> AssetGlance:
        raise AssertionError("never built")

    with pytest.raises(EditorAssetNotFound):
        await service(Media(), build).glance("project_002", "asset_music")


@pytest.mark.skipif(shutil.which("ffmpeg") is None, reason="ffmpeg is not installed")
def test_the_default_builder_is_the_ffmpeg_one() -> None:
    from thoth_control_plane.infrastructure.asset_glance_builder import build_glance

    glances = AssetGlanceService(EditorAssetService(Repository()), Media(), "ffmpeg")
    assert glances._build is build_glance
