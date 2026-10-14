from __future__ import annotations

import cv2
import numpy as np

from thoth_control_plane.footage.frames import clip_window, dhash, is_duplicate, vision_seconds


def test_clip_window() -> None:
    assert clip_window(30.0) is None
    assert clip_window(12.5) is None
    assert clip_window(None) == (0.0, 30.0)
    assert clip_window(40.0) == (4.0, 24.0)  # 10% of 40, window of 20
    assert clip_window(31.0) == (3.1, 23.1)
    assert clip_window(600.0) == (60.0, 80.0)
    assert clip_window(35.0) == (3.5, 23.5)


def test_vision_seconds_spread_after_the_trim() -> None:
    assert vision_seconds(0.0, 20.0) == [4.0, 10.0, 16.0]
    assert vision_seconds(5.0, 15.0) == [7.0, 10.0, 13.0]


def _jpeg(seed: int) -> bytes:
    rng = np.random.default_rng(seed)
    image = rng.integers(0, 255, (90, 160, 3), dtype=np.uint8)
    ok, data = cv2.imencode(".jpg", image)
    assert ok
    return data.tobytes()


def test_dhash_matches_itself_and_not_noise() -> None:
    a, b = dhash(_jpeg(1)), dhash(_jpeg(2))
    assert dhash(_jpeg(1)) == a
    assert is_duplicate([a, a, a], [[a]])
    assert not is_duplicate([a, a, a], [[b]])
    assert not is_duplicate([], [[a]])
    assert not is_duplicate([a], [])


def test_the_distance_is_inclusive_at_ten_bits() -> None:
    assert is_duplicate([0], [[(1 << 10) - 1]])
    assert not is_duplicate([0], [[(1 << 11) - 1]])


def test_half_the_frames_must_be_close() -> None:
    far = (1 << 20) - 1
    assert is_duplicate([0, 0, far], [[0]])
    assert not is_duplicate([0, far, far], [[0]])


def test_a_frame_is_close_to_any_frame_of_the_other_clip() -> None:
    far = (1 << 20) - 1
    assert is_duplicate([0], [[far, 0, far]])


def test_a_match_against_a_later_clip_counts() -> None:
    far = (1 << 20) - 1
    assert is_duplicate([0], [[far], [0]])
