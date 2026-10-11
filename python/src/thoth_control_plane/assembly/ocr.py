"""Final OCR of a video main: Scout's sampling and coverage rule over local RapidOCR boxes.

Only complete coverage may produce a verdict: a frame that cannot be read is unknown, never
clean. A missing ffmpeg or ffprobe keeps its own code (operator, 2026-10-11).
"""

from __future__ import annotations

import logging
from datetime import datetime
from pathlib import Path

from thoth_control_plane.assembly.models import BlurRegion, MainOcr
from thoth_control_plane.assembly.ports import (
    AssemblyError,
    DurationProbe,
    FrameSampler,
    TextReader,
)
from thoth_control_plane.assembly.subtitles import (
    OcrBox,
    OcrFrame,
    build_sample_times,
    classify_ocr_frames,
)
from thoth_control_plane.attribution.adapters.frames import DurationError, FrameError, ToolMissing
from thoth_control_plane.attribution.ports import Frame

logger = logging.getLogger(__name__)

FRAME_WIDTH = 720  # RapidOCR's detector scales the short side to 736 anyway
RECOVERY_OFFSETS = (0.0, 0.25, 0.5, 1.0)
EXTRACTION_ATTEMPTS = 2


def recovery_seconds(requested: float, previous: float | None) -> list[float]:
    """Scout's `frameRecoveryTimes`: step back, never behind the previous sample."""
    seconds: list[float] = []
    for offset in RECOVERY_OFFSETS:
        second = round(max(0.0, requested - offset), 6)
        if second not in seconds and (previous is None or second > previous):
            seconds.append(second)
    return seconds


async def _frame(
    frames: FrameSampler, video: Path, requested: float, previous: float | None
) -> Frame | None:
    for second in recovery_seconds(requested, previous):
        for _ in range(EXTRACTION_ATTEMPTS):
            try:
                return await frames.frame_at(video, second, width=FRAME_WIDTH)
            except ToolMissing as missing:
                raise AssemblyError(missing.code) from None
            except FrameError:
                continue
    return None


async def analyze_main_ocr(
    video: Path,
    duration: float | None,
    *,
    frames: FrameSampler,
    probe: DurationProbe,
    text: TextReader,
    max_frames: int,
    now: datetime,
) -> MainOcr:
    if not duration or duration <= 0:
        try:
            duration = await probe.duration(video)
        except ToolMissing as missing:
            raise AssemblyError(missing.code) from None
        except (DurationError, FrameError):
            raise AssemblyError("duration_probe_failed") from None

    requested = build_sample_times(duration, max_frames)
    read: list[OcrFrame] = []
    for second in requested:
        previous = read[-1].t if read else None
        frame = await _frame(frames, video, second, previous)
        if frame is None:
            read.append(OcrFrame(second, error="frame_extract"))
            continue
        try:
            boxes = await text.read(frame)
        except ImportError:
            raise AssemblyError("rapidocr_missing") from None
        except Exception:
            read.append(OcrFrame(frame.second, error="ocr_failed"))
            continue
        read.append(
            OcrFrame(
                frame.second,
                tuple(OcrBox(b.text, b.left, b.top, b.right, b.bottom) for b in boxes),
            )
        )

    valid = sum(1 for frame in read if frame.error is None)
    if valid != len(requested):
        logger.warning("main OCR incomplete: %d of %d frames", valid, len(requested))
        raise AssemblyError("incomplete_frame_coverage")

    verdict = classify_ocr_frames(read, duration)
    return MainOcr(
        analyzed_at=now,
        requested_frames=len(requested),
        valid_frames=valid,
        outcome=verdict.outcome,
        trim_start=verdict.trim_start,
        mute_audio=verdict.mute_audio,
        subtitle_blur=[
            BlurRegion(x=r.x, y=r.y, w=r.w, h=r.h, start=r.start, end=r.end)
            for r in verdict.subtitle_blur
        ],
    )
