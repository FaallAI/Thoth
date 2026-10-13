"""Frames sampled by ffmpeg; local and model-free."""

from __future__ import annotations

import asyncio
import re
import tempfile
from pathlib import Path

from thoth_control_plane.attribution.ports import Frame

TIMEOUT_SECONDS = 120.0
SCENE_THRESHOLD = 0.3
# Shots past this span never reach the cover call; a full scan of a long video timed out.
SCENE_SECONDS = 600.0
PTS_TIME = re.compile(rb"pts_time:(\d+(?:\.\d+)?)")


class FrameError(Exception):
    """ffmpeg could not sample the video."""


class ToolMissing(Exception):
    """A required binary is not installed: never a media failure (operator, 2026-10-11)."""

    def __init__(self, code: str) -> None:
        super().__init__(code)
        self.code = code


class DurationError(Exception):
    """ffprobe ran but could not read a duration."""


async def _run(argv: list[str], missing: str, *, capture: bool = False) -> tuple[int, bytes]:
    try:
        process = await asyncio.create_subprocess_exec(
            *argv,
            stdout=asyncio.subprocess.PIPE if capture else asyncio.subprocess.DEVNULL,
            stderr=asyncio.subprocess.DEVNULL,
        )
    except FileNotFoundError:
        raise ToolMissing(missing) from None
    try:
        output, _ = await asyncio.wait_for(process.communicate(), TIMEOUT_SECONDS)
    except TimeoutError:
        raise FrameError("ffmpeg_timeout") from None
    finally:
        if process.returncode is None:
            process.kill()
            await process.wait()
    return process.returncode or 0, output or b""


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
            try:
                process = await asyncio.create_subprocess_exec(
                    *argv, stdout=asyncio.subprocess.DEVNULL, stderr=asyncio.subprocess.DEVNULL
                )
            except FileNotFoundError:
                raise ToolMissing("ffmpeg_missing") from None
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

    async def frame_at(self, video: Path, second: float, *, width: int) -> Frame:
        """One JPEG at `second`, `width` px wide; FrameError when nothing decodes there."""
        with tempfile.TemporaryDirectory(prefix="thoth-frame-") as directory:
            target = Path(directory) / "frame.jpg"
            code, _ = await _run(
                [
                    self._ffmpeg,
                    "-nostdin",
                    "-v",
                    "error",
                    "-ss",
                    f"{second:.6f}",
                    "-i",
                    str(video),
                    "-frames:v",
                    "1",
                    "-vf",
                    f"scale={width}:-2",
                    "-q:v",
                    "2",
                    str(target),
                ],
                "ffmpeg_missing",
            )
            if code != 0 or not target.is_file() or target.stat().st_size == 0:
                raise FrameError("ffmpeg_failed")
            return Frame(second, target.read_bytes())


class FfprobeDuration:
    def __init__(self, ffprobe: str = "ffprobe") -> None:
        self._ffprobe = ffprobe

    async def duration(self, video: Path) -> float:
        code, output = await _run(
            [
                self._ffprobe,
                "-v",
                "error",
                "-show_entries",
                "format=duration",
                "-of",
                "default=noprint_wrappers=1:nokey=1",
                str(video),
            ],
            "ffprobe_missing",
            capture=True,
        )
        try:
            value = float(output.decode().strip())
        except ValueError:
            raise DurationError("duration_probe_failed") from None
        if code != 0 or not value > 0:
            raise DurationError("duration_probe_failed")
        return value


class FfmpegSceneDetector:
    """Shot cuts from ffmpeg's scene score, printed to stdout by the metadata filter."""

    def __init__(self, ffmpeg: str = "ffmpeg") -> None:
        self._ffmpeg = ffmpeg

    async def cuts(self, video: Path) -> list[float]:
        from thoth_control_plane.attribution.ports import AttributionError

        argv = [
            self._ffmpeg,
            "-v",
            "error",
            "-t",
            f"{SCENE_SECONDS:g}",
            "-i",
            str(video),
            "-an",
            "-vf",
            f"scale=360:-2,select='gt(scene,{SCENE_THRESHOLD})',metadata=print:file=-",
            "-f",
            "null",
            "-",
        ]
        try:
            code, output = await _run(argv, "ffmpeg_missing", capture=True)
        except FrameError:
            raise AttributionError("scene_detection_failed") from None
        if code != 0:
            raise AttributionError("scene_detection_failed")
        return [float(match.group(1)) for match in PTS_TIME.finditer(output)]
