"""Visual match summaries and burned-in speech detection, without any model."""

from __future__ import annotations

from thoth_control_plane.attribution.matching import (
    TextBox,
    looks_like_burned_in_speech,
    summarize_matches,
)


def test_a_match_counts_the_repost_frames_that_hold_the_candidate() -> None:
    # The reaction case: the original shows only in two sampled frames, but strongly.
    assert summarize_matches([0, 418, 0, 31, 4], min_inliers=25) == (2, 418)
    assert summarize_matches([12, 9, 10], min_inliers=25) == (0, 12)


def test_no_comparable_frames_is_unmeasured() -> None:
    assert summarize_matches([], min_inliers=25) is None


def test_changing_lower_text_is_speech_and_a_static_lower_third_is_not() -> None:
    speech = [
        [TextBox("kata pertama", 0.70, 0.76)],
        [TextBox("kata kedua", 0.70, 0.76)],
        [TextBox("kata ketiga", 0.70, 0.76)],
        [],
    ]
    lower_third = [[TextBox("DETIK JATIM", 0.85, 0.90)] for _ in range(5)]
    headline = [[TextBox(f"BREAKING {n}", 0.05, 0.10)] for n in range(5)]

    assert looks_like_burned_in_speech(speech) is True
    assert looks_like_burned_in_speech(lower_third) is False
    assert looks_like_burned_in_speech(headline) is False
    assert looks_like_burned_in_speech([]) is False
