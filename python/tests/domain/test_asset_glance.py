"""Tier 3b: an asset's glance, a filmstrip or its peaks, and the maths that bounds it."""

from __future__ import annotations

import struct

import pytest
from pydantic import ValidationError

from thoth_control_plane.domain.asset_glance import (
    MAX_PEAKS,
    AssetGlance,
    GlancePeaks,
    GlanceStrip,
    peak_seconds,
    peaks_from_pcm,
    strip_plan,
)


def test_strip_plan_spaces_frames_a_second_apart_up_to_sixty() -> None:
    assert strip_plan(10) == (10, 1)
    assert strip_plan(80) == (40, 2)
    assert strip_plan(600) == (60, 10)
    assert strip_plan(0.4) == (1, 1)


def test_peak_seconds_has_a_floor_and_a_ceiling_on_count() -> None:
    assert peak_seconds(80) == 0.1
    assert peak_seconds(600) == pytest.approx(0.3)


def pcm(samples: list[int]) -> bytes:
    return struct.pack(f"<{len(samples)}h", *samples)


def test_peaks_from_pcm_take_the_loudest_sample_of_each_stretch() -> None:
    # 8000 Hz in 0.1 s stretches is 800 samples each; the third stretch is partial.
    samples = [0] * 800 + [16384, -16384] * 400 + [-32768] * 10
    assert peaks_from_pcm(pcm(samples), 8000, 0.1) == [0, 50, 100]


def test_a_ten_minute_track_stays_inside_the_limits() -> None:
    values = peaks_from_pcm(b"\0\0" * 8000 * 600, 8000, peak_seconds(600))
    assert 0 < len(values) <= MAX_PEAKS


def test_a_glance_refuses_more_than_sixty_frames_or_out_of_range_peaks() -> None:
    image = "data:image/jpeg;base64,AAAA"
    with pytest.raises(ValidationError):
        GlanceStrip(image=image, frame_width=40, frame_height=72, frames=61, seconds_per_frame=1)
    with pytest.raises(ValidationError):
        GlancePeaks(seconds_per_peak=0.1, values=[101])
    with pytest.raises(ValidationError):
        GlanceStrip(
            image="https://example.com/x.jpg",
            frame_width=40,
            frame_height=72,
            frames=1,
            seconds_per_frame=1,
        )
    peaks = GlancePeaks(seconds_per_peak=0.1, values=[0, 50])
    glance = AssetGlance(asset_id="asset_1", peaks=peaks)
    assert glance.strip is None
