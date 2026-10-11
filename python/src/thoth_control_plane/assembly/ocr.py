"""Final OCR of a video main: Scout's sampling and coverage rule over local RapidOCR boxes.

Only complete coverage may produce a verdict: a frame that cannot be read is unknown, never
clean. A missing ffmpeg or ffprobe keeps its own code (operator, 2026-10-11). After Scout's
verdict, `refine.py` corrects it (spec amendment, 2026-10-12): a trim only for a possible
repost, measured by the region tracker; overlays keep the audio; scene text is dropped; the
caption judge confirms captions before the audio is muted.
"""

from __future__ import annotations

import logging
from datetime import datetime
from pathlib import Path

from thoth_control_plane.assembly.models import BlurRegion, MainOcr
from thoth_control_plane.assembly.ports import (
    AssemblyError,
    CaptionJudge,
    DurationProbe,
    FrameSampler,
    RegionTracker,
    TextReader,
)
from thoth_control_plane.assembly.refine import (
    Windows,
    headline_span,
    retrim,
    settle,
    sort_windows,
    without_trim,
)
from thoth_control_plane.assembly.subtitles import (
    OcrBox,
    OcrFrame,
    Verdict,
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
    trim_allowed: bool = True,
    tracker: RegionTracker | None = None,
    judge: CaptionJudge | None = None,
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
    images: dict[float, Frame] = {}
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
        images[frame.second] = frame
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
    refined = False
    if not trim_allowed:
        verdict = without_trim(verdict)
    elif tracker is not None:
        verdict, refined = await _measure_trim(video, read, verdict, tracker)
    windows = sort_windows(read, verdict)
    confirmed = await _confirm(windows, images, judge) if windows.captions else None
    verdict = settle(verdict, windows, confirmed)
    return MainOcr(
        analyzed_at=now,
        requested_frames=len(requested),
        valid_frames=valid,
        outcome=verdict.outcome,
        trim_start=verdict.trim_start,
        mute_audio=verdict.mute_audio,
        trim_refined=refined,
        subtitle_blur=[
            BlurRegion(x=r.x, y=r.y, w=r.w, h=r.h, start=r.start, end=r.end)
            for r in verdict.subtitle_blur
        ],
    )


async def _measure_trim(
    video: Path, read: list[OcrFrame], verdict: Verdict, tracker: RegionTracker
) -> tuple[Verdict, bool]:
    span = headline_span(read, verdict)
    if span is None:
        return verdict, False
    region, present, absent = span
    try:
        gone = await tracker.first_absent(video, region, present, absent)
    except ToolMissing as missing:
        raise AssemblyError(missing.code) from None
    except Exception:
        gone = None
    if gone is None:
        logger.warning("headline boundary not measured; the sample midpoint stays")
        return verdict, False
    return retrim(verdict, gone), True


async def _confirm(
    windows: Windows, images: dict[float, Frame], judge: CaptionJudge | None
) -> bool | None:
    if judge is None:
        return None
    seconds = sorted(
        {
            t
            for t in images
            for region in windows.captions
            if region.start - 1e-6 <= t <= region.end + 1e-6
        }
    )
    if not seconds:
        return None
    # Three frames spread over the caption windows: first, middle, last.
    picks = sorted({seconds[0], seconds[len(seconds) // 2], seconds[-1]})
    try:
        answer = await judge.speech_captions([images[t] for t in picks])
    except Exception:
        answer = None
    if answer is None:
        logger.warning("caption check unavailable; the rule-based verdict stands")
    return answer
