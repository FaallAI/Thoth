"""A recorded calibration case replays through the production OCR path, offline."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from tests.assembly.ocr_replay import replay
from thoth_control_plane.assembly.subtitles import build_sample_times


def case(**overrides: object) -> dict[str, object]:
    headline = [["HEADLINE BESAR", 0.09, 0.2, 0.91, 0.26]]
    frames = [
        {"t": t, "boxes": headline if t <= 5 else [[f"kalimat {t}", 0.2, 0.7, 0.8, 0.75]]}
        # The video stream ends before 38.977: production recovered that sample at 38.727.
        for t in [*build_sample_times(39.077)[:-1], 38.727]
    ]
    data: dict[str, object] = {
        "duration": 39.077,
        "frames": frames,
        "trim_allowed": True,
        "tracker": 9.6,
        "vision": False,
    }
    data.update(overrides)
    return data


def test_replay_follows_the_recorded_answers() -> None:
    ocr = replay(case())

    assert (ocr.outcome, ocr.trim_start, ocr.trim_refined) == ("cover", 9.6, True)


def captions_with_a_blank_at_five() -> list[dict[str, object]]:
    lines = [
        "alpha",
        "bravo",
        "charlie",
        "delta",
        "echo",
        "foxtrot",
        "golf",
        "hotel",
        "india",
        "juliet",
        "kilo",
        "lima",
    ]
    return [
        {"t": t, "boxes": [] if t == 5 else [[word, 0.2, 0.7, 0.8, 0.75]]}
        for t, word in zip(build_sample_times(39.0), lines, strict=True)
    ]


def test_a_blank_sample_is_not_read_again_a_second_later() -> None:
    # The retry read a shirt at 6 s and blurred it for 6 s (rev 19); following the text replaced it.
    frames = [
        *captions_with_a_blank_at_five(),
        {"t": 6.0, "boxes": [["mike", 0.2, 0.7, 0.8, 0.75]]},
    ]

    ocr = replay(case(duration=39.0, frames=frames, vision=None))

    assert ocr.valid_frames == 12
    assert len(ocr.subtitle_blur) == 2


def test_a_video_without_text_is_not_read_twice() -> None:
    frames = [{"t": t, "boxes": []} for t in build_sample_times(39.0)]
    frames.append({"t": 1.5, "boxes": [["never read", 0.2, 0.7, 0.8, 0.75]]})

    assert replay(case(duration=39.0, frames=frames, vision=None)).outcome == "clean"


def test_replay_reproduces_recovered_seconds_and_no_answers() -> None:
    ocr = replay(case(tracker=None, vision=None))

    assert ocr.valid_frames == 12
    assert (ocr.outcome, ocr.trim_refined, ocr.mute_audio) == ("subtitle", False, True)
    assert replay(case(trim_allowed=False, vision=None)).trim_start == 0.0


def test_the_rev_18_source_blurs_only_while_its_captions_show() -> None:
    # Word captions on a shot full of signs and shirts, under a watermark the reader misreads. The
    # sampled windows blurred a face and a body for seconds (operator, rev 19, 2026-11-02).
    path = Path(__file__).parents[1] / "fixtures/assembly/ocr_follow/tiktok_rev18_source.json"

    ocr = replay(json.loads(path.read_text(encoding="utf-8")))

    assert (ocr.outcome, ocr.mute_audio) == ("subtitle", True)
    assert [(round(r.start, 2), round(r.end, 2)) for r in ocr.subtitle_blur] == pytest.approx(
        [
            (0.0, 4.75),
            (5.25, 6.25),
            (8.25, 9.25),
            (16.32, 20.75),
            (24.25, 25.75),
            (26.25, 27.14),
            (27.75, 29.25),
            (31.75, 34.25),
            (34.75, 35.75),
            (39.75, 42.75),
            (43.75, 45.25),
            (45.75, 47.25),
            (47.75, 48.75),
            (51.75, 53.75),
            (56.25, 57.75),
            (59.25, 60.25),
            (63.25, 67.75),
        ],
        abs=0.01,
    )
    assert all(r.y >= 0.82 and r.y + r.h <= 0.92 for r in ocr.subtitle_blur)
