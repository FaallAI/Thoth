"""Build a video's preview proxy with the image's own ffmpeg (spec 2026-11-18).

The Player decodes from the keyframe before each cut; a stored source keeps up to ten seconds
between keyframes, so short cuts stall the preview. The proxy has one keyframe a second, 30 fps,
the long side at most 960 px, and the same duration: only the Player reads it, the render keeps
the original. The source is opened with the glance's whitelists.
"""

from __future__ import annotations

import asyncio
from pathlib import Path

from thoth_control_plane.infrastructure.asset_glance_builder import FORMATS
from thoth_control_plane.infrastructure.media_probe import FILE_PROTOCOLS, URL_PROTOCOLS

#: A long main video takes a minute or two at this preset; anything slower is a failed build.
PROXY_TIMEOUT_SECONDS = 600
LONG_SIDE = 960

ENCODE = (
    *("-map", "0:v:0", "-map", "0:a:0?"),
    "-vf",
    f"scale=w='min({LONG_SIDE},iw)':h='min({LONG_SIDE},ih)'"
    ":force_original_aspect_ratio=decrease:force_divisible_by=2",
    *("-r", "30", "-c:v", "libx264", "-preset", "veryfast", "-crf", "23", "-pix_fmt", "yuv420p"),
    *("-g", "30", "-keyint_min", "30", "-sc_threshold", "0"),
    *("-c:a", "aac", "-b:a", "128k", "-movflags", "+faststart", "-threads", "2"),
)


class ProxyBuildFailed(Exception):
    """ffmpeg is missing, refused the source, timed out, or wrote nothing."""


async def build_preview_proxy(ffmpeg: str, source: str, media_type: str, destination: Path) -> None:
    """Write the proxy to `destination`; on failure nothing is left there."""
    remote = source.startswith(("http://", "https://"))
    try:
        process = await asyncio.create_subprocess_exec(
            ffmpeg,
            *("-v", "error", "-y"),
            *("-protocol_whitelist", URL_PROTOCOLS if remote else FILE_PROTOCOLS),
            *("-format_whitelist", FORMATS.get(media_type, "mov")),
            *("-i", source),
            *ENCODE,
            *("-f", "mp4", str(destination)),
            stdin=asyncio.subprocess.DEVNULL,
            stdout=asyncio.subprocess.DEVNULL,
            stderr=asyncio.subprocess.DEVNULL,
        )
    except OSError as error:
        raise ProxyBuildFailed("ffmpeg could not start") from error
    try:
        await asyncio.wait_for(process.wait(), PROXY_TIMEOUT_SECONDS)
    except TimeoutError as error:
        raise ProxyBuildFailed("timeout") from error
    finally:
        if process.returncode is None:  # a timeout or a cancelled build: ffmpeg never outlives it
            process.kill()
            await process.wait()
        if process.returncode != 0:
            destination.unlink(missing_ok=True)
    if process.returncode != 0 or not destination.is_file() or destination.stat().st_size == 0:
        destination.unlink(missing_ok=True)
        raise ProxyBuildFailed("ffmpeg refused the source")
