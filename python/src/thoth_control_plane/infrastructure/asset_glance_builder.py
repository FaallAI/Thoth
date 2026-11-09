"""Build an asset's glance with the image's own ffmpeg (Tier 3b).

The source is a local path or a short-lived signed store URL from ``MediaStore.probe_source``,
opened with the same protocol whitelist as the upload probe, so a crafted file cannot pivot
between the network and the filesystem.
"""

from __future__ import annotations

import asyncio
import base64

from thoth_control_plane.domain.asset_glance import (
    MAX_PEAKS,
    PEAK_SAMPLE_RATE,
    STRIP_HEIGHT,
    AssetGlance,
    GlancePeaks,
    GlanceStrip,
    peak_of,
    peak_seconds,
    stretch_bytes,
    strip_plan,
)
from thoth_control_plane.domain.editor_assets import CANVAS_FPS, EditorAsset
from thoth_control_plane.infrastructure.media_probe import FILE_PROTOCOLS, URL_PROTOCOLS

#: A glance of a long video takes seconds; anything slower is treated as a failed build.
GLANCE_TIMEOUT_SECONDS = 60


#: The one demuxer each upload type may open (final review 2026-11-09): a crafted file cannot
#: become a playlist that makes ffmpeg read another file or, from the store, another URL.
FORMATS = {
    "video/mp4": "mov",
    "video/webm": "matroska",
    "image/png": "png_pipe",
    "image/jpeg": "jpeg_pipe",
    "image/webp": "webp_pipe",
    "audio/mpeg": "mp3",
    "audio/wav": "wav",
}


#: Tiles at least this many seconds apart still differ when only keyframes are decoded.
KEYFRAME_STRIP_SECONDS = 10
FULL_DECODE = ("-threads", "2")
KEYFRAMES_ONLY = ("-skip_frame", "nokey", "-threads", "2")


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


async def _start(
    ffmpeg: str,
    source: str,
    formats: str,
    output_args: list[str],
    input_args: tuple[str, ...] = (),
) -> asyncio.subprocess.Process:
    remote = source.startswith(("http://", "https://"))
    try:
        return await asyncio.create_subprocess_exec(
            ffmpeg,
            "-v",
            "error",
            "-protocol_whitelist",
            URL_PROTOCOLS if remote else FILE_PROTOCOLS,
            "-format_whitelist",
            formats,
            *input_args,
            "-i",
            source,
            *output_args,
            stdin=asyncio.subprocess.DEVNULL,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.DEVNULL,
        )
    except OSError as error:  # ffmpeg itself is missing: an installation fault, fail loud
        raise GlanceToolMissing(ffmpeg) from error


async def _run(
    ffmpeg: str,
    source: str,
    formats: str,
    output_args: list[str],
    input_args: tuple[str, ...] = (),
) -> bytes:
    process = await _start(ffmpeg, source, formats, output_args, input_args)
    try:
        stdout, _ = await asyncio.wait_for(process.communicate(), GLANCE_TIMEOUT_SECONDS)
    except TimeoutError as error:
        raise GlanceBuildFailed("timeout") from error
    finally:
        # A timeout or a cancelled request: ffmpeg never outlives the build.
        if process.returncode is None:
            process.kill()
            await process.wait()
    if process.returncode != 0 or not stdout:
        raise GlanceBuildFailed("ffmpeg refused the source")
    return stdout


async def _stream_peaks(
    ffmpeg: str, source: str, formats: str, seconds_per_peak: float
) -> list[int]:
    """Fold each stretch as ffmpeg streams it: constant memory, and the loop is never held."""
    process = await _start(
        ffmpeg,
        source,
        formats,
        ["-vn", "-ac", "1", "-ar", str(PEAK_SAMPLE_RATE), "-f", "s16le", "-"],
    )
    size = stretch_bytes(PEAK_SAMPLE_RATE, seconds_per_peak)
    values: list[int] = []

    async def fold() -> None:
        assert process.stdout is not None
        while len(values) < MAX_PEAKS:
            try:
                values.append(peak_of(await process.stdout.readexactly(size)))
            except asyncio.IncompleteReadError as end:
                if end.partial:
                    values.append(peak_of(end.partial))
                break

    try:
        await asyncio.wait_for(fold(), GLANCE_TIMEOUT_SECONDS)
    except TimeoutError as error:
        raise GlanceBuildFailed("timeout") from error
    finally:
        # Enough peaks, a timeout or a cancelled request: ffmpeg never outlives the build.
        if process.returncode is None:
            process.kill()
        await process.wait()
    if not values or process.returncode not in (0, -9):
        raise GlanceBuildFailed("ffmpeg refused the source")
    return values


async def _video_strip(
    ffmpeg: str, source: str, formats: str, output_args: list[str], seconds_per_frame: int
) -> bytes:
    """Decode in full unless the tiles are further apart than a video's keyframes usually are.

    Measured 2026-11-09: with keyframes 5 s apart, keyframes alone drew 3 different pictures
    across 15 tiles of a 20 s video, while a full decode of 5 minutes of 1080p took 7 s.
    """
    if seconds_per_frame >= KEYFRAME_STRIP_SECONDS:
        try:
            return await _run(ffmpeg, source, formats, output_args, KEYFRAMES_ONLY)
        except GlanceBuildFailed as error:
            if str(error) == "timeout":
                raise
            return await _run(ffmpeg, source, formats, output_args, FULL_DECODE)
    try:
        return await _run(ffmpeg, source, formats, output_args, FULL_DECODE)
    except GlanceBuildFailed as error:
        if str(error) != "timeout":
            raise
        # Too heavy to decode in full: a coarser strip, kept once built, beats none every session.
        return await _run(ffmpeg, source, formats, output_args, KEYFRAMES_ONLY)


def _seconds(asset: EditorAsset) -> float:
    """Durations count canvas frames, whatever the media's own rate (final review 2026-11-09)."""
    return (asset.duration_in_frames or 0) / CANVAS_FPS


async def build_glance(ffmpeg: str, source: str, asset: EditorAsset) -> AssetGlance:
    """A strip for a video or image, peaks for an audio track."""
    formats = FORMATS.get(asset.media_type)
    if formats is None:
        raise GlanceBuildFailed("no glance for this media type")
    if asset.kind == "audio":
        seconds_per_peak = peak_seconds(_seconds(asset))
        values = await _stream_peaks(ffmpeg, source, formats, seconds_per_peak)
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
    output_args = ["-vf", f"{video_filter},format=yuvj420p", *jpeg_out]
    if asset.kind == "video":
        image = await _video_strip(ffmpeg, source, formats, output_args, seconds_per_frame)
    else:
        image = await _run(ffmpeg, source, formats, output_args)
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
