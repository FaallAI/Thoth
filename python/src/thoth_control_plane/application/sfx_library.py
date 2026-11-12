"""SFX loudness and each project's copy of a stored library object.

The global, seed-only SFX library (spec 2026-10-31, decisions 7-8) was retired for each
workspace's own asset library (spec 2026-11-13, `application/workspace_library.py`). What stays
here is shared with it: the loudness normalisation that keeps a meme stinger from drowning the
narrator, and the copy that gives a draft its own object.
"""

from __future__ import annotations

import asyncio
import hashlib
import json
import re
import subprocess
from pathlib import Path
from typing import Any, Literal
from uuid import uuid4

from thoth_control_plane.application.editor_asset_uploads import (
    PROVENANCE,
    MediaProbe,
    described_asset,
)
from thoth_control_plane.domain.editor_assets import EditorAssetRecord

TARGET_LUFS = -16.0
TRUE_PEAK = -1.0
LOUDNESS_RANGE = 11.0


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


class SfxAssets:
    """A project's editor asset for a stored library object: copied once, reused by checksum."""

    def __init__(self, *, assets: Any, media: Any, probe: MediaProbe) -> None:
        self._assets = assets
        self._media = media
        self._probe = probe

    async def ensure_project_asset(
        self,
        project_id: str,
        *,
        location: str,
        checksum: str,
        media_type: str,
        kind: Literal["image", "video", "audio"],
        suffix: str,
    ) -> Any:
        """The project's copy of one stored object: reused by checksum, else copied once."""
        checksum = checksum.lower()
        found = await self._assets.find_ready_by_checksum(project_id=project_id, checksum=checksum)
        if found is not None:
            return found.asset
        source = await asyncio.to_thread(self._media.probe_source, location)
        asset = described_asset(
            asset_id=f"asset_{uuid4().hex}",
            project_id=project_id,
            media_type=media_type,
            kind=kind,
            checksum=checksum,
            report=await self._probe(source),
        )
        destination = f"uploads/{project_id}/{asset.asset_id}{suffix}"
        await asyncio.to_thread(self._media.copy, location, destination)
        await self._assets.register_ready(
            EditorAssetRecord(asset=asset, artifact_location=destination, provenance=PROVENANCE)
        )
        return asset
