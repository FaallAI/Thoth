"""Final OCR of a video main: Scout's sampling and coverage rule over local RapidOCR boxes.

Only complete coverage may produce a verdict: a frame that cannot be read is unknown, never
clean. A missing ffmpeg or ffprobe keeps its own code (operator, 2026-10-11). After Scout's
verdict, `refine.py` corrects it (spec amendment, 2026-10-12): a trim only for a possible
repost, measured by the region tracker; overlays keep the audio; scene text is dropped; the
caption judge confirms captions before the audio is muted. Captions are then read every half
second, so that each blur window opens and closes with its text (operator, 2026-11-02), and
each edge is read again inside its half-second gap (operator, 2026-11-03).
"""

from __future__ import annotations

import logging
from collections.abc import Awaitable, Callable, Sequence
from dataclasses import replace
from datetime import datetime
from pathlib import Path

from thoth_control_plane.assembly.models import BlurRegion, MainOcr
from thoth_control_plane.assembly.ports import (
    AssemblyError,
    BandReader,
    CaptionJudge,
    DurationProbe,
    FrameDecoder,
    FrameSampler,
    RegionTracker,
    TextReader,
)
from thoth_control_plane.assembly.refine import (
    EdgeGap,
    Windows,
    edge_gaps,
    edge_seconds,
    follow_captions,
    follow_seconds,
    headline_span,
    holds_caption,
    retrim,
    settle,
    sort_windows,
    without_trim,
)
from thoth_control_plane.assembly.subtitles import (
    OcrBox,
    OcrFrame,
    Region,
    Verdict,
    build_sample_times,
    classify_ocr_frames,
)
from thoth_control_plane.attribution.adapters.frames import DurationError, FrameError, ToolMissing
from thoth_control_plane.attribution.matching import TextBox
from thoth_control_plane.attribution.ports import Frame

logger = logging.getLogger(__name__)

FRAME_WIDTH = 720  # RapidOCR's detector scales the short side to 736 anyway
RECOVERY_OFFSETS = (0.0, 0.25, 0.5, 1.0)
EXTRACTION_ATTEMPTS = 2
MAX_BLUR_REGIONS = 200  # MainOcr.subtitle_blur
EDGE_ROUNDS = 3  # a half-second gap narrows to 1/16 s, an edge to within about one frame
# ponytail: past this, every edge stays within half a second; reading only some would make
# windows of one video differ. About 2.5 minutes, kept inside the assembly activity's limit.
EDGE_MAX_READS = 180
BAND_MARGIN = 0.02  # above and below the caption lines, more than a line wanders (TRACK_Y)


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


async def _read_at(
    frames: FrameSampler, video: Path, text: TextReader, second: float, previous: float | None
) -> tuple[OcrFrame, Frame | None]:
    frame = await _frame(frames, video, second, previous)
    if frame is None:
        return OcrFrame(second, error="frame_extract"), None
    row = await _boxes(frame, text.read)
    return row, None if row.error else frame


async def _boxes(frame: Frame, read: Callable[[Frame], Awaitable[list[TextBox]]]) -> OcrFrame:
    try:
        boxes = await read(frame)
    except ToolMissing as missing:
        raise AssemblyError(missing.code) from None
    except ImportError:
        raise AssemblyError("rapidocr_missing") from None
    except Exception:
        return OcrFrame(frame.second, error="ocr_failed")
    return OcrFrame(
        frame.second, tuple(OcrBox(b.text, b.left, b.top, b.right, b.bottom) for b in boxes)
    )


async def _decoded(
    decoder: FrameDecoder | None,
    video: Path,
    seconds: Sequence[float],
    *,
    top: float = 0.0,
    bottom: float = 1.0,
) -> dict[float, Frame]:
    """One pass over the video; without it each frame is extracted alone, the same but slower."""
    if decoder is None or not seconds:
        return {}
    try:
        return await decoder.decode(video, seconds, width=FRAME_WIDTH, top=top, bottom=bottom)
    except Exception as error:
        logger.warning("decode pass failed (%s); frames are extracted alone", type(error).__name__)
        return {}


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
    follow: bool = True,
    decoder: FrameDecoder | None = None,
    bands: BandReader | None = None,
) -> MainOcr:
    """`follow`: False for a caller that only needs the verdict, not the windows to blur."""
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
        row, frame = await _read_at(frames, video, text, second, read[-1].t if read else None)
        read.append(row)
        if frame is not None:
            images[frame.second] = frame

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
    if follow and windows.captions and confirmed is not False:
        verdict, windows = await _follow_text(
            video, read, duration, verdict, windows, frames, text, decoder, bands
        )
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


async def _follow_text(
    video: Path,
    read: list[OcrFrame],
    duration: float,
    verdict: Verdict,
    windows: Windows,
    frames: FrameSampler,
    text: TextReader,
    decoder: FrameDecoder | None,
    bands: BandReader | None,
) -> tuple[Verdict, Windows]:
    """Windows that hold only while their text does; without full coverage, the sampled ones."""
    rows = {frame.t: frame for frame in read}
    seconds = follow_seconds(verdict.trim_start, duration)
    decoded = await _decoded(decoder, video, [second for second in seconds if second not in rows])
    previous = None
    for second in seconds:
        if second not in rows:
            frame = decoded.get(second)
            if frame is None:
                row, _ = await _read_at(frames, video, text, second, previous)
            else:
                row = await _boxes(frame, text.read)
            if row.error:
                logger.warning("caption frame %.2f unread; the sampled blur windows stay", second)
                return verdict, windows
            rows[row.t] = row
            second = row.t
        previous = second
    followed = follow_captions(list(rows.values()), verdict.trim_start, duration)
    if len(followed) + len(windows.overlays) > MAX_BLUR_REGIONS:
        logger.warning("%d caption windows; the sampled blur windows stay", len(followed))
        return verdict, windows
    followed = await _sharpen(
        video, rows, followed, verdict.trim_start, frames, text, decoder, bands
    )
    return (
        replace(verdict, subtitle_blur=(*windows.overlays, *followed)),
        replace(windows, captions=followed),
    )


async def _sharpen(
    video: Path,
    rows: dict[float, OcrFrame],
    followed: tuple[Region, ...],
    trim_start: float,
    frames: FrameSampler,
    text: TextReader,
    decoder: FrameDecoder | None,
    bands: BandReader | None,
) -> tuple[Region, ...]:
    """The windows with each edge read out of the half-second gap it falls in."""
    gaps = [edge_gaps(list(rows.values()), region, trim_start) for region in followed]
    found = [gap for pair in gaps for gap in pair if gap]
    if len(found) * EDGE_ROUNDS > EDGE_MAX_READS:
        logger.warning("%d caption edges; they stay within half a second", len(found))
        return followed
    # Every caption line lies in this band, so the detector has far fewer pixels to read.
    top = max(0.0, min((region.y for region in followed), default=0.0) - BAND_MARGIN)
    bottom = min(1.0, max((r.y + r.h for r in followed), default=1.0) + BAND_MARGIN)
    cut: dict[float, Frame] = {}
    if bands is not None:
        wanted = sorted({second for gap in found for second in edge_seconds(gap, EDGE_ROUNDS)})
        cut = await _decoded(decoder, video, wanted, top=top, bottom=bottom)

    async def read_second(second: float) -> OcrFrame:
        frame = cut.get(second)
        if frame is None or bands is None:
            # `previous` just below: recovery must not answer with a frame from outside the gap.
            row, _ = await _read_at(frames, video, text, second, second - 0.001)
            return row
        return await _boxes(frame, lambda band: bands.read_band(band, top, bottom))

    sharp = []
    for region, (opening, closing) in zip(followed, gaps, strict=True):
        start = await _edge(rows, opening, read_second) if opening else region.start
        end = await _edge(rows, closing, read_second) if closing else region.end
        sharp.append(replace(region, start=start, end=end))
    return tuple(sharp)


async def _edge(
    rows: dict[float, OcrFrame], gap: EdgeGap, read_second: Callable[[float], Awaitable[OcrFrame]]
) -> float:
    """Halve the gap; lines of one caption ask for the same seconds, so `rows` saves the reads."""
    outside, inside = gap.outside, gap.inside
    for _ in range(EDGE_ROUNDS):
        second = round((outside + inside) / 2, 6)
        row = rows.get(second)
        if row is None:
            row = await read_second(second)
            if row.error:
                logger.warning("caption edge %.2f unread; it stays within its gap", second)
                return (outside + inside) / 2
            rows[second] = row
        if holds_caption(gap.reference, row):
            inside = second
        else:
            outside = second
    # A read stands for the frame at or after its second, so text can outlast a midpoint by a
    # frame, never open before one: a window closes on the first read without its text.
    return max(outside, (outside + inside) / 2)


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
