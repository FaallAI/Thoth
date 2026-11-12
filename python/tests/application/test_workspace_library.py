"""A workspace's asset library: upload, import, delete and copy into a draft (spec 2026-11-13)."""

from __future__ import annotations

import asyncio
import re
import shutil
import subprocess
from pathlib import Path
from typing import Any

import pytest

from thoth_control_plane.application.editor_asset_ports import EditorAssetMediaInvalid
from thoth_control_plane.application.sfx_library import SfxAssets
from thoth_control_plane.application.workspace_library import (
    LibraryItemNotFound,
    LibraryUnavailable,
    WorkspaceLibraryService,
    display_name,
    library_kind,
)
from thoth_control_plane.domain.workspace_assets import WorkspaceAsset, WorkspaceAssetRecord
from thoth_control_plane.infrastructure.artifact_root import LocalArtifactRoot
from thoth_control_plane.infrastructure.media_store import LocalMediaStore

REPO = Path(__file__).parents[3]
FFMPEG = shutil.which("ffmpeg")
needs_ffmpeg = pytest.mark.skipif(FFMPEG is None, reason="ffmpeg is not installed")

# Small synthetic payloads: a real signature, then filler. Nothing here is operator media.
MP4 = b"\x00\x00\x00\x18ftypisom" + b"\x00" * 24
VIDEO_REPORT = {
    "streams": [
        {"codec_type": "video", "width": 1080, "height": 1920, "avg_frame_rate": "30/1"},
        {"codec_type": "audio"},
    ],
    "format": {"duration": "2.0"},
}
NULL_OUT = ("-f", "null", "-")
AUDIO_REPORT = {"streams": [{"codec_type": "audio"}], "format": {"duration": "1.3"}}


class MemoryLibrary:
    def __init__(self) -> None:
        self.records: dict[tuple[str, str], WorkspaceAssetRecord] = {}

    async def list(self, workspace_id: str) -> list[WorkspaceAsset]:
        return [r.asset for (ws, _), r in self.records.items() if ws == workspace_id]

    async def get(self, workspace_id: str, asset_id: str) -> WorkspaceAssetRecord | None:
        return self.records.get((workspace_id, asset_id))

    async def add(self, record: WorkspaceAssetRecord) -> WorkspaceAssetRecord:
        asset = record.asset
        for (ws, _), existing in self.records.items():
            if ws == asset.workspace_id and existing.asset.checksum == asset.checksum:
                return existing
        self.records[(asset.workspace_id, asset.asset_id)] = record
        return record

    async def update(self, workspace_id: str, asset_id: str, **changes: Any) -> Any:
        raise NotImplementedError

    async def delete(self, workspace_id: str, asset_id: str) -> str | None:
        record = self.records.pop((workspace_id, asset_id), None)
        return None if record is None else record.location


class Assets:
    def __init__(self) -> None:
        self.records: list[Any] = []

    async def find_ready_by_checksum(self, *, project_id: str, checksum: str) -> Any:
        return next(
            (
                record
                for record in self.records
                if record.asset.project_id == project_id and record.asset.checksum == checksum
            ),
            None,
        )

    async def register_ready(self, record: Any) -> None:
        self.records.append(record)


def canned(report: dict[str, Any]):
    async def probe(_: Any) -> dict[str, Any]:
        return report

    return probe


def build(
    tmp_path: Path, report: dict[str, Any]
) -> tuple[WorkspaceLibraryService, MemoryLibrary, Assets, Path]:
    root = tmp_path / "root"
    root.mkdir()
    media = LocalMediaStore(root)
    library, assets = MemoryLibrary(), Assets()
    service = WorkspaceLibraryService(
        library,
        LocalArtifactRoot(root, media),
        canned(report),
        media,
        SfxAssets(assets=assets, media=media, probe=canned(report)),
        Path(FFMPEG or "ffmpeg"),
    )
    return service, library, assets, root


async def chunks_of(payload: bytes):
    yield payload[:5]
    yield payload[5:]


def test_short_audio_is_sfx_and_long_audio_is_backsound() -> None:
    assert library_kind("audio", 15.0) == "sfx"
    assert library_kind("audio", 15.1) == "backsound"
    assert library_kind("video", 3.0) == "clip"
    assert library_kind("image", None) == "image"


def test_display_name_strips_paths_and_trims() -> None:
    assert display_name("../../a/b/Vine Boom.mp3") == "Vine Boom"
    assert display_name("C:\\memes\\yea boi.mp4") == "yea boi"
    assert len(display_name("x" * 300 + ".mp3")) == 120
    assert display_name(".mp3") == "untitled"
    assert display_name("bad\x00name\n.mp3") == "badname"


def test_upload_publishes_under_the_workspace_library_prefix(tmp_path: Path) -> None:
    service, library, _, root = build(tmp_path, VIDEO_REPORT)
    asset = asyncio.run(service.upload("ws_a", "video/mp4", chunks_of(MP4), "../evil/Yea Boi.mp4"))
    assert (asset.kind, asset.name, asset.workspace_id) == ("clip", "Yea Boi", "ws_a")
    assert asset.duration_seconds == pytest.approx(2.0)
    location = library.records[("ws_a", asset.asset_id)].location
    assert re.fullmatch(r"library/ws_a/lib_[0-9a-f]{32}\.mp4", location)
    assert (root / location).read_bytes() == MP4
    assert not list((root / "temp").rglob("*.part"))


def test_the_same_file_twice_is_one_item_and_leaves_no_second_object(tmp_path: Path) -> None:
    service, _, _, root = build(tmp_path, VIDEO_REPORT)
    first = asyncio.run(service.upload("ws_a", "video/mp4", chunks_of(MP4), "a.mp4"))
    again = asyncio.run(service.upload("ws_a", "video/mp4", chunks_of(MP4), "b.mp4"))
    other = asyncio.run(service.upload("ws_b", "video/mp4", chunks_of(MP4), "a.mp4"))
    assert again.asset_id == first.asset_id and other.asset_id != first.asset_id
    assert len(list((root / "library" / "ws_a").iterdir())) == 1


def test_an_unsupported_or_mismatched_upload_is_refused(tmp_path: Path) -> None:
    service, library, _, _ = build(tmp_path, VIDEO_REPORT)
    with pytest.raises(EditorAssetMediaInvalid) as unsupported:
        asyncio.run(service.upload("ws_a", "text/plain", chunks_of(b"hello"), "a.txt"))
    assert unsupported.value.code == "unsupported_media_type"
    with pytest.raises(EditorAssetMediaInvalid) as mismatch:
        asyncio.run(service.upload("ws_a", "video/mp4", chunks_of(b"not a video"), "a.mp4"))
    assert mismatch.value.code == "media_type_mismatch"
    assert library.records == {}


def test_a_library_without_storage_is_unavailable(tmp_path: Path) -> None:
    service = WorkspaceLibraryService(None, None, canned(VIDEO_REPORT), None, None, Path("ffmpeg"))
    with pytest.raises(LibraryUnavailable):
        asyncio.run(service.upload("ws_a", "video/mp4", chunks_of(MP4), "a.mp4"))
    with pytest.raises(LibraryUnavailable):
        asyncio.run(service.list("ws_a"))


@needs_ffmpeg
def test_an_imported_sfx_is_loudness_normalised(tmp_path: Path) -> None:
    service, library, _, root = build(tmp_path, AUDIO_REPORT)
    asset = asyncio.run(
        service.import_file("ws_a", REPO / "assets/sfx/bruh.mp3", {"category": "meme_vocal"})
    )
    assert (asset.kind, asset.name, asset.labels) == ("sfx", "bruh", {"category": "meme_vocal"})
    stored = root / library.records[("ws_a", asset.asset_id)].location
    run = subprocess.run(
        [FFMPEG or "ffmpeg", "-hide_banner", "-i", str(stored), "-af", "ebur128", *NULL_OUT],
        capture_output=True,
        text=True,
        check=True,
    )
    measured = float(re.findall(r"I:\s+(-?[\d.]+) LUFS", run.stderr)[-1])
    assert abs(measured - -16.0) <= 1.0


def test_import_file_rejects_an_unknown_suffix(tmp_path: Path) -> None:
    service, _, _, _ = build(tmp_path, VIDEO_REPORT)
    note = tmp_path / "notes.txt"
    note.write_text("hello", "utf-8")
    with pytest.raises(EditorAssetMediaInvalid) as refused:
        asyncio.run(service.import_file("ws_a", note, {}))
    assert refused.value.code == "unsupported_media_type"


def test_add_to_project_copies_and_reuses_by_checksum(tmp_path: Path) -> None:
    service, _, assets, root = build(tmp_path, VIDEO_REPORT)
    item = asyncio.run(service.upload("ws_a", "video/mp4", chunks_of(MP4), "clip.mp4"))
    first = asyncio.run(service.add_to_project("ws_a", "project_a", item.asset_id))
    again = asyncio.run(service.add_to_project("ws_a", "project_a", item.asset_id))
    assert first.asset_id == again.asset_id and first.kind == "video"
    assert len(assets.records) == 1
    copied = assets.records[0].artifact_location
    assert copied.startswith("uploads/project_a/") and (root / copied).read_bytes() == MP4


def test_delete_keeps_a_drafts_copy(tmp_path: Path) -> None:
    service, library, assets, root = build(tmp_path, VIDEO_REPORT)
    item = asyncio.run(service.upload("ws_a", "video/mp4", chunks_of(MP4), "clip.mp4"))
    location = library.records[("ws_a", item.asset_id)].location
    asyncio.run(service.add_to_project("ws_a", "project_a", item.asset_id))
    assert asyncio.run(service.delete("ws_a", item.asset_id)) is True
    assert library.records == {} and not (root / location).exists()
    assert (root / assets.records[0].artifact_location).read_bytes() == MP4
    assert asyncio.run(service.delete("ws_a", item.asset_id)) is False


def test_another_workspaces_item_is_not_found(tmp_path: Path) -> None:
    service, _, _, _ = build(tmp_path, VIDEO_REPORT)
    item = asyncio.run(service.upload("ws_a", "video/mp4", chunks_of(MP4), "clip.mp4"))
    with pytest.raises(LibraryItemNotFound):
        asyncio.run(service.add_to_project("ws_b", "project_b", item.asset_id))
    assert asyncio.run(service.delete("ws_b", item.asset_id)) is False
