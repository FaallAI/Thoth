"""A draft's own copy of a stored library object, reused by checksum (spec 2026-11-13)."""

from __future__ import annotations

import asyncio
from pathlib import Path
from typing import Any

from thoth_control_plane.application.sfx_library import SfxAssets


class FolderMedia:
    def __init__(self) -> None:
        self.copies: list[tuple[str, str]] = []

    def copy(self, source: str, destination: str) -> None:
        self.copies.append((source, destination))

    def probe_source(self, location: str) -> str:
        return location


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


async def audio_report(_: Any) -> dict[str, Any]:
    return {"streams": [{"codec_type": "audio"}], "format": {"duration": "1.0"}}


def test_a_project_copies_a_library_object_once_and_another_project_gets_its_own(
    tmp_path: Path,
) -> None:
    assets, media = Assets(), FolderMedia()
    library = SfxAssets(assets=assets, media=media, probe=audio_report)
    source = {
        "location": "library/ws_a/lib_1.mp3",
        "checksum": "sha256:" + "A" * 64,
        "media_type": "audio/mpeg",
        "kind": "audio",
        "suffix": ".mp3",
    }

    first = asyncio.run(library.ensure_project_asset("project_a", **source))
    again = asyncio.run(library.ensure_project_asset("project_a", **source))
    other = asyncio.run(library.ensure_project_asset("project_b", **source))

    assert first == again and first.kind == "audio" and first.project_id == "project_a"
    assert first.checksum == "sha256:" + "a" * 64
    assert other.project_id == "project_b" and other.asset_id != first.asset_id
    assert len(media.copies) == 2
    assert all(dest.startswith("uploads/") and dest.endswith(".mp3") for _, dest in media.copies)
