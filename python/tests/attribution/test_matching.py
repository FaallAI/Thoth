"""Frame-hash matching and burned-in speech detection, without any model."""

from __future__ import annotations

from thoth_control_plane.attribution.matching import (
    FrameHash,
    TextBox,
    distance,
    looks_like_burned_in_speech,
    match_share,
)

A, B, C = 0x0F0F0F0F0F0F0F0F, 0xF0F0F0F0F0F0F0F0, 0x00FF00FF00FF00FF
FAR = 0xAAAAAAAAAAAAAAAA


def _hashes(*values: int) -> list[FrameHash]:
    return [FrameHash(float(second), value) for second, value in enumerate(values)]


def test_distance_counts_differing_bits() -> None:
    assert distance(A, A) == 0
    assert distance(A, B) == 64
    assert distance(A, A ^ 0b111) == 3


def test_a_cut_of_the_original_matches_fully_and_another_video_does_not() -> None:
    repost = _hashes(A, B, C)
    original = _hashes(FAR, A ^ 0b11, B, C, FAR)

    assert match_share(repost, original, max_distance=10) == 1.0
    assert match_share(repost, _hashes(FAR, FAR ^ 1), max_distance=10) == 0.0
    assert match_share(repost, _hashes(A), max_distance=10) == 1 / 3


def test_no_frames_on_either_side_is_unmeasured() -> None:
    assert match_share([], _hashes(A), max_distance=10) is None
    assert match_share(_hashes(A), [], max_distance=10) is None


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
