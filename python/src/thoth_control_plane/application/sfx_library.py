"""The shared SFX library: what Thoth bundles, and each project's copy of what a draft uses.

Spec 2026-10-31, decisions 7-8. Every bundled SFX must be licence-free (operator, 2026-10-31):
``assets/sfx/LICENSES.json`` names each file's licence and source, and a file whose licence is
not one of ``ALLOWED_SFX_LICENCES`` is never seeded. Seeded files are loudness-normalised so a
meme stinger never drowns the narrator. Files users upload are theirs and are not seeded here.
"""

from __future__ import annotations

import asyncio
import hashlib
import json
import re
import subprocess
import tempfile
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any
from uuid import uuid4

from thoth_control_plane.application.editor_asset_uploads import (
    PROVENANCE,
    MediaProbe,
    described_asset,
)
from thoth_control_plane.domain.edit_document_v2 import AssetRef
from thoth_control_plane.domain.editor_assets import EditorAssetRecord
from thoth_control_plane.domain.narration import SfxEntry

ALLOWED_SFX_LICENCES = frozenset({"CC0-1.0", "Pixabay", "Mixkit-SFX"})
LICENCE_FILE = "LICENSES.json"
TARGET_LUFS = -16.0
TRUE_PEAK = -1.0
LOUDNESS_RANGE = 11.0
#: Catalog fields that describe placement and meaning; signal curves stay out of the labels.
_DROPPED_LABELS = frozenset({"file", "env_curve"})


@dataclass
class SeedReport:
    added: int = 0
    unchanged: int = 0
    skipped: list[str] = field(default_factory=list)


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1 << 20), b""):
            digest.update(chunk)
    return f"sha256:{digest.hexdigest()}"


def _loudnorm(ffmpeg: Path, source: Path, target: Path) -> dict[str, Any]:
    """Two-pass EBU R128 normalisation; returns the first pass's measurement of the source."""
    settings = f"I={TARGET_LUFS}:TP={TRUE_PEAK}:LRA={LOUDNESS_RANGE}"
    probe = subprocess.run(
        [
            str(ffmpeg),
            "-hide_banner",
            "-nostdin",
            "-i",
            str(source),
            "-af",
            f"loudnorm={settings}:print_format=json",
            "-f",
            "null",
            "-",
        ],
        capture_output=True,
        text=True,
        check=True,
    )
    measured = json.loads(re.findall(r"\{[^{}]*\}", probe.stderr)[-1])
    subprocess.run(
        [
            str(ffmpeg),
            "-hide_banner",
            "-nostdin",
            "-y",
            "-i",
            str(source),
            "-af",
            f"loudnorm={settings}:measured_I={measured['input_i']}:measured_TP={measured['input_tp']}"
            f":measured_LRA={measured['input_lra']}:measured_thresh={measured['input_thresh']}"
            ":linear=true",
            "-ar",
            "44100",
            "-codec:a",
            "libmp3lame",
            "-q:a",
            "2",
            "-map_metadata",
            "-1",
            str(target),
        ],
        capture_output=True,
        check=True,
    )
    return measured


async def seed_sfx(
    store: Any, media: Any, catalog: Path, directory: Path, ffmpeg: Path
) -> SeedReport:
    """Seed every licensed catalog SFX into object storage and the library; idempotent."""
    licences = (
        json.loads((directory / LICENCE_FILE).read_text("utf-8"))
        if (directory / LICENCE_FILE).is_file()
        else {}
    )
    rows = [
        row
        for row in json.loads(catalog.read_text("utf-8"))["assets"]
        if str(row.get("file", "")).startswith("assets/sfx/")
    ]
    existing = {entry.sfx_id: entry for entry in await store.list_sfx()}
    report = SeedReport()
    for row in rows:
        name = Path(row["file"]).name
        source = directory / name
        licence = licences.get(name) or {}
        if licence.get("licence") not in ALLOWED_SFX_LICENCES or not source.is_file():
            report.skipped.append(name)
            continue
        sfx_id = source.stem
        source_checksum = _sha256(source)
        known = existing.get(sfx_id)
        if known is not None and known.labels.get("source_checksum") == source_checksum:
            report.unchanged += 1
            continue
        with tempfile.TemporaryDirectory() as work:
            normalised = Path(work) / f"{sfx_id}.mp3"
            measured = await asyncio.to_thread(_loudnorm, ffmpeg, source, normalised)
            checksum = _sha256(normalised)
            location = f"sfx/{checksum.removeprefix('sha256:')}.mp3"
            await asyncio.to_thread(media.put_file, location, normalised)
        labels = {key: value for key, value in row.items() if key not in _DROPPED_LABELS}
        labels |= {
            "licence": licence["licence"],
            "source_url": licence.get("source_url", ""),
            "source_checksum": source_checksum,
            "input_lufs": float(measured["input_i"]),
        }
        added = await store.upsert_sfx(
            SfxEntry(
                sfx_id=sfx_id,
                file_name=name,
                location=location,
                checksum=checksum,
                duration_seconds=float(row.get("duration_sec") or 1.0),
                labels=labels,
            )
        )
        if added:
            report.added += 1
        else:
            report.unchanged += 1
    return report


class SfxAssets:
    """A project's editor asset for a library SFX: copied on first use, reused by checksum."""

    def __init__(self, *, assets: Any, media: Any, probe: MediaProbe) -> None:
        self._assets = assets
        self._media = media
        self._probe = probe

    async def ensure_project_sfx(self, project_id: str, entry: SfxEntry) -> AssetRef:
        return (await self.ensure_project_asset(project_id, entry)).to_asset_ref()

    async def ensure_project_asset(self, project_id: str, entry: SfxEntry) -> Any:
        checksum = entry.checksum.lower()
        found = await self._assets.find_ready_by_checksum(project_id=project_id, checksum=checksum)
        if found is not None:
            return found.asset
        source = await asyncio.to_thread(self._media.probe_source, entry.location)
        asset = described_asset(
            asset_id=f"asset_{uuid4().hex}",
            project_id=project_id,
            media_type="audio/mpeg",
            kind="audio",
            checksum=checksum,
            report=await self._probe(source),
        )
        destination = f"uploads/{project_id}/{asset.asset_id}.mp3"
        await asyncio.to_thread(self._media.copy, entry.location, destination)
        await self._assets.register_ready(
            EditorAssetRecord(asset=asset, artifact_location=destination, provenance=PROVENANCE)
        )
        return asset
