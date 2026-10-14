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
