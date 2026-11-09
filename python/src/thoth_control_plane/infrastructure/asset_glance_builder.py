"""Build an asset's glance with the image's own ffmpeg (Tier 3b).

The source is a local path or a short-lived signed store URL from ``MediaStore.probe_source``,
opened with the same protocol whitelist as the upload probe, so a crafted file cannot pivot
between the network and the filesystem.
"""

from __future__ import annotations

import asyncio
import base64

from thoth_control_plane.domain.asset_glance import (
    PEAK_SAMPLE_RATE,
    STRIP_HEIGHT,
    AssetGlance,
    GlancePeaks,
    GlanceStrip,
    peak_seconds,
    peaks_from_pcm,
    strip_plan,
)
from thoth_control_plane.domain.editor_assets import EditorAsset
from thoth_control_plane.infrastructure.media_probe import FILE_PROTOCOLS, URL_PROTOCOLS

#: A glance of a long video takes seconds; anything slower is treated as a failed build.
GLANCE_TIMEOUT_SECONDS = 60
#: The frame rate a duration is counted in when the asset names none.
_DEFAULT_FPS = 30.0


class GlanceToolMissing(Exception):
    """ffmpeg could not start: an installation fault, reported as such."""


class GlanceBuildFailed(Exception):
    """ffmpeg refused the source, timed out, or produced nothing."""


def jpeg_size(data: bytes) -> tuple[int, int]:
    """Width and height from a JPEG's baseline or progressive frame header."""
    index = 2
    while index + 9 < len(data):
        if data[index] != 0xFF:
            index += 1
            continue
        marker = data[index + 1]
        if marker in (0xC0, 0xC2):
            height = int.from_bytes(data[index + 5 : index + 7], "big")
            width = int.from_bytes(data[index + 7 : index + 9], "big")
            return width, height
        length = int.from_bytes(data[index + 2 : index + 4], "big")
        index += 2 + length
    raise GlanceBuildFailed("no JPEG frame header")


async def _run(ffmpeg: str, source: str, output_args: list[str]) -> bytes:
    remote = source.startswith(("http://", "https://"))
    try:
        process = await asyncio.create_subprocess_exec(
            ffmpeg,
            "-v",
            "error",
            "-protocol_whitelist",
            URL_PROTOCOLS if remote else FILE_PROTOCOLS,
            "-i",
            source,
            *output_args,
            stdin=asyncio.subprocess.DEVNULL,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.DEVNULL,
        )
    except OSError as error:  # ffmpeg itself is missing: an installation fault, fail loud
        raise GlanceToolMissing(ffmpeg) from error
    try:
        stdout, _ = await asyncio.wait_for(process.communicate(), GLANCE_TIMEOUT_SECONDS)
    except TimeoutError as error:
        process.kill()
        await process.wait()
        raise GlanceBuildFailed("timeout") from error
    if process.returncode != 0 or not stdout:
        raise GlanceBuildFailed("ffmpeg refused the source")
    return stdout


def _seconds(asset: EditorAsset) -> float:
    return (asset.duration_in_frames or 0) / (asset.fps or _DEFAULT_FPS)


async def build_glance(ffmpeg: str, source: str, asset: EditorAsset) -> AssetGlance:
    """A strip for a video or image, peaks for an audio track."""
    if asset.kind == "audio":
        seconds_per_peak = peak_seconds(_seconds(asset))
        pcm = await _run(
            ffmpeg, source, ["-vn", "-ac", "1", "-ar", str(PEAK_SAMPLE_RATE), "-f", "s16le", "-"]
        )
        values = peaks_from_pcm(pcm, PEAK_SAMPLE_RATE, seconds_per_peak)
        return AssetGlance(
            asset_id=asset.asset_id,
            peaks=GlancePeaks(seconds_per_peak=seconds_per_peak, values=values),
        )
    if asset.kind == "video":
        frames, seconds_per_frame = strip_plan(_seconds(asset))
        video_filter = f"fps=1/{seconds_per_frame},scale=-2:{STRIP_HEIGHT},tile={frames}x1"
    else:
        frames, seconds_per_frame = 1, 1
        video_filter = f"scale=-2:{STRIP_HEIGHT}"
    jpeg_out = ["-frames:v", "1", "-q:v", "5", "-f", "image2pipe", "-vcodec", "mjpeg", "-"]
    image = await _run(ffmpeg, source, ["-vf", video_filter, *jpeg_out])
    width, height = jpeg_size(image)
    return AssetGlance(
        asset_id=asset.asset_id,
        strip=GlanceStrip(
            image="data:image/jpeg;base64," + base64.b64encode(image).decode("ascii"),
            frame_width=max(1, width // frames),
            frame_height=height,
            frames=frames,
            seconds_per_frame=seconds_per_frame,
        ),
    )
