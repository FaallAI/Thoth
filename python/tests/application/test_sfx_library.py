"""The SFX library: licence-gated, loudness-normalised seeding and per-project copies (Task 10)."""

from __future__ import annotations

import asyncio
import json
import re
import shutil
import subprocess
from pathlib import Path
from typing import Any

import pytest

from thoth_control_plane.application.sfx_library import (
    ALLOWED_SFX_LICENCES,
    SfxAssets,
    seed_sfx,
)
from thoth_control_plane.domain.narration import SfxEntry

REPO = Path(__file__).parents[3]
FFMPEG = shutil.which("ffmpeg")
needs_ffmpeg = pytest.mark.skipif(FFMPEG is None, reason="ffmpeg is not installed")


class MemoryStore:
    def __init__(self) -> None:
        self.entries: dict[str, SfxEntry] = {}

    async def list_sfx(self) -> list[SfxEntry]:
        return sorted(self.entries.values(), key=lambda entry: entry.sfx_id)

    async def upsert_sfx(self, entry: SfxEntry) -> bool:
        if any(item.checksum == entry.checksum for item in self.entries.values()):
            return False
        self.entries[entry.sfx_id] = entry
        return True


class FolderMedia:
    def __init__(self, root: Path) -> None:
        self.root = root
        self.copies: list[tuple[str, str]] = []

    def put_file(self, location: str, path: Path) -> None:
        target = self.root / location
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(path, target)

    def copy(self, source: str, destination: str) -> None:
        self.copies.append((source, destination))

    def probe_source(self, location: str) -> str:
        return location


def sfx_dir(tmp_path: Path, licences: dict[str, Any]) -> Path:
    directory = tmp_path / "sfx"
    shutil.copytree(REPO / "assets/sfx", directory)
    (directory / "LICENSES.json").write_text(json.dumps(licences), "utf-8")
    return directory


def lufs(path: Path) -> float:
    run = subprocess.run(
        [FFMPEG or "ffmpeg", "-hide_banner", "-i", str(path), "-af", "ebur128", "-f", "null", "-"],
        capture_output=True,
        text=True,
        check=True,
    )
    return float(re.findall(r"I:\s+(-?[\d.]+) LUFS", run.stderr)[-1])


@needs_ffmpeg
def test_only_licensed_files_are_seeded_normalised_and_once(tmp_path: Path) -> None:
    licences = {
        "impact-hit.mp3": {"licence": "CC0-1.0", "source_url": "https://example.org/impact"},
        "notification.mp3": {"licence": "Pixabay", "source_url": "https://example.org/ding"},
        "vine-boom.mp3": {"licence": "All rights reserved", "source_url": "https://example.org/v"},
    }
    directory = sfx_dir(tmp_path, licences)
    store, media = MemoryStore(), FolderMedia(tmp_path / "bucket")

    first = asyncio.run(
        seed_sfx(store, media, REPO / "assets/asset_catalog.json", directory, Path(FFMPEG or ""))
    )
    second = asyncio.run(
        seed_sfx(store, media, REPO / "assets/asset_catalog.json", directory, Path(FFMPEG or ""))
    )

    assert (first.added, first.unchanged, len(first.skipped)) == (2, 0, 19)
    assert (second.added, second.unchanged) == (0, 2)
    entry = store.entries["impact-hit"]
    assert entry.labels["licence"] == "CC0-1.0"
    assert entry.labels["source_url"] == "https://example.org/impact"
    assert entry.labels["category"] == "impact_stinger"
    assert "env_curve" not in entry.labels
    assert entry.location.startswith("sfx/") and entry.location.endswith(".mp3")
    assert abs(lufs(media.root / entry.location) - -16.0) <= 1.5


def test_the_licence_gate_allows_only_free_licences() -> None:
    assert frozenset({"CC0-1.0", "Pixabay", "Mixkit-SFX"}) == ALLOWED_SFX_LICENCES


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


def test_a_project_copies_a_library_sfx_once_and_another_project_gets_its_own(
    tmp_path: Path,
) -> None:
    entry = SfxEntry(
        sfx_id="impact-hit",
        file_name="impact-hit.mp3",
        location="sfx/" + "a" * 64 + ".mp3",
        checksum="sha256:" + "a" * 64,
        duration_seconds=1.0,
    )
    assets, media = Assets(), FolderMedia(tmp_path)
    library = SfxAssets(assets=assets, media=media, probe=audio_report)

    first = asyncio.run(library.ensure_project_sfx("project_a", entry))
    again = asyncio.run(library.ensure_project_sfx("project_a", entry))
    other = asyncio.run(library.ensure_project_sfx("project_b", entry))

    assert first == again and first.kind == "audio" and first.project_id == "project_a"
    assert other.project_id == "project_b" and other.asset_id != first.asset_id
    assert len(media.copies) == 2
    assert all(dest.startswith("uploads/") for _, dest in media.copies)
