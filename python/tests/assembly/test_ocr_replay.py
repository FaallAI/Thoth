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


def test_a_blank_sample_amid_text_is_read_again_a_second_later() -> None:
    # Colour bars at the 5 s sample once left the captions around it unblurred (rev 18).
    frames = [
        *captions_with_a_blank_at_five(),
        {"t": 6.0, "boxes": [["mike", 0.2, 0.7, 0.8, 0.75]]},
    ]

    ocr = replay(case(duration=39.0, frames=frames, vision=None))

    assert ocr.valid_frames == 12
    assert [(region.start, region.end) for region in ocr.subtitle_blur] == [(0.0, 39.0)]


def test_a_blank_sample_with_nothing_readable_after_it_stays_blank() -> None:
    ocr = replay(case(duration=39.0, frames=captions_with_a_blank_at_five(), vision=None))

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
