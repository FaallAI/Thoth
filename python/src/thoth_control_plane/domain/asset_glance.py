"""An asset's glance (Tier 3b): a filmstrip of a video or image, or the peaks of an audio track.

A glance is small and derived: a strip of at most 60 frames 72 px tall, or at most 2000 peak
values. The Timeline draws the part of it each clip plays; nothing here is the media itself.
"""

from __future__ import annotations

import math
from array import array
from sys import byteorder
from typing import Annotated

from pydantic import Field, PositiveInt

from thoth_control_plane.domain.models import OpaqueId, StrictModel

#: The strip's height in pixels: twice a lane's clip height, so it stays sharp.
STRIP_HEIGHT = 72
MAX_STRIP_FRAMES = 60
MAX_PEAKS = 2000
MIN_PEAK_SECONDS = 0.1
#: Peaks only need the loudness envelope, so the audio is read at a low rate.
PEAK_SAMPLE_RATE = 8000
_FULL_SCALE = 32768


def strip_plan(duration_seconds: float) -> tuple[int, int]:
    """How many frames the strip holds, and how many seconds apart they are (at least one)."""
    seconds_per_frame = max(1, math.ceil(duration_seconds / MAX_STRIP_FRAMES))
    frames = max(1, math.ceil(duration_seconds / seconds_per_frame))
    return min(frames, MAX_STRIP_FRAMES), seconds_per_frame


def peak_seconds(duration_seconds: float) -> float:
    """The stretch each peak covers: a tenth of a second, longer for a long track."""
    return max(MIN_PEAK_SECONDS, duration_seconds / MAX_PEAKS)


def peaks_from_pcm(pcm: bytes, sample_rate: int, seconds_per_peak: float) -> list[int]:
    """The loudest sample of each stretch, 0 to 100 of full scale, from signed 16-bit mono LE."""
    samples = array("h")
    samples.frombytes(pcm[: len(pcm) - len(pcm) % 2])
    if byteorder == "big":
        samples.byteswap()
    stretch = max(1, round(sample_rate * seconds_per_peak))
    values = [
        round(100 * max(abs(sample) for sample in samples[start : start + stretch]) / _FULL_SCALE)
        for start in range(0, len(samples), stretch)
    ]
    return values[:MAX_PEAKS]


JpegDataUrl = Annotated[str, Field(pattern=r"^data:image/jpeg;base64,[A-Za-z0-9+/=]+$")]


class GlanceStrip(StrictModel):
    """Frames side by side in one JPEG, the first at the source's start."""

    image: JpegDataUrl
    frame_width: PositiveInt
    frame_height: PositiveInt
    frames: Annotated[int, Field(ge=1, le=MAX_STRIP_FRAMES)]
    seconds_per_frame: PositiveInt


class GlancePeaks(StrictModel):
    """The loudest sample of each stretch of the track, from its start."""

    seconds_per_peak: Annotated[float, Field(gt=0)]
    values: Annotated[list[Annotated[int, Field(ge=0, le=100)]], Field(max_length=MAX_PEAKS)]


class AssetGlance(StrictModel):
    """What a clip of this asset shows: a video or image has a strip, an audio track its peaks."""

    asset_id: OpaqueId
    strip: GlanceStrip | None = None
    peaks: GlancePeaks | None = None
