"""Frames sampled by ffmpeg; local and model-free."""

from __future__ import annotations

import asyncio
import tempfile
from pathlib import Path

from thoth_control_plane.attribution.ports import Frame

TIMEOUT_SECONDS = 120.0


class FrameError(Exception):
    """ffmpeg could not sample the video."""


class FfmpegFrameSource:
    def __init__(self, ffmpeg: str = "ffmpeg", width: int = 360) -> None:
        self._ffmpeg = ffmpeg
        self._width = width

    async def frames(self, video: Path, *, fps: float, seconds: float | None = None) -> list[Frame]:
        with tempfile.TemporaryDirectory(prefix="thoth-frames-") as directory:
            pattern = Path(directory) / "f%05d.jpg"
            limit = ["-t", f"{seconds:g}"] if seconds else []
            argv = [
                self._ffmpeg,
                "-nostdin",
                "-v",
                "error",
                *limit,
                "-i",
                str(video),
                "-vf",
                f"fps={fps:g},scale={self._width}:-2",
                "-q:v",
                "4",
                str(pattern),
            ]
            process = await asyncio.create_subprocess_exec(
                *argv, stdout=asyncio.subprocess.DEVNULL, stderr=asyncio.subprocess.DEVNULL
            )
            try:
                code = await asyncio.wait_for(process.wait(), TIMEOUT_SECONDS)
            except TimeoutError:
                raise FrameError("ffmpeg_timeout") from None
            finally:
                if process.returncode is None:
                    process.kill()
                    await process.wait()
            if code != 0:
                raise FrameError("ffmpeg_failed")
            files = sorted(Path(directory).glob("f*.jpg"))
            return [Frame(index / fps, path.read_bytes()) for index, path in enumerate(files)]
