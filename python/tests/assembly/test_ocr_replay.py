"""A recorded calibration case replays through the production OCR path, offline."""

from __future__ import annotations

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


def test_replay_reproduces_recovered_seconds_and_no_answers() -> None:
    ocr = replay(case(tracker=None, vision=None))

    assert ocr.valid_frames == 12
    assert (ocr.outcome, ocr.trim_refined, ocr.mute_audio) == ("subtitle", False, True)
    assert replay(case(trim_allowed=False, vision=None)).trim_start == 0.0
