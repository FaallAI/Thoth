"""One copy of a recording (footage library spec 2026-11-15, 9.4 and 9.9): ORB matches in time
order tell a copy from another moment on the same set."""

from __future__ import annotations

import pytest

from thoth_control_plane.attribution.adapters.visual import OrbMatcher
from thoth_control_plane.attribution.matching import TextBox
from thoth_control_plane.attribution.ports import Frame
from thoth_control_plane.footage.recording import (
    CopyFacts,
    is_copy,
    keep_first,
    text_share,
    triggered,
)


def test_a_copy_lines_up_in_time() -> None:
    matrix = [[40 if j == i + 2 else 3 for j in range(20)] for i in range(18)]
    assert is_copy(matrix)


def test_the_same_set_at_another_moment_is_no_copy() -> None:  # spike: 9/9 matched, 1.2x peak
    matrix = [[30 + (i * j) % 7 for j in range(9)] for i in range(9)]
    assert not is_copy(matrix)


def test_too_few_matched_frames_is_no_copy() -> None:
    assert not is_copy([[40, 0], [0, 0], [0, 0]])
    assert not is_copy([])


def test_the_trigger_needs_25_inliers() -> None:
    assert triggered([3, 25])
    assert not triggered([24, 0])
    assert not triggered([])


def test_an_original_beats_a_cleaner_copy() -> None:
    assert keep_first(CopyFacts("a", True, 0.3, None), CopyFacts("b", False, 0.0, "2026-11-01"))


def test_the_cleaner_copy_wins_then_the_earlier() -> None:
    assert not keep_first(CopyFacts("a", False, 0.2, None), CopyFacts("b", False, 0.05, None))
    assert keep_first(
        CopyFacts("a", False, 0.1, "2026-11-01"), CopyFacts("b", False, 0.1, "2026-11-02")
    )
    assert not keep_first(
        CopyFacts("a", False, 0.1, None), CopyFacts("b", False, 0.1, "2026-11-02")
    )


def test_text_share_sums_boxes() -> None:
    box = TextBox(text="JawaPos", top=0.0, bottom=0.1, left=0.0, right=0.5)
    assert text_share([[box], []]) == pytest.approx(0.025)
    assert text_share([]) == 0.0


def _texture(seed: int) -> object:
    import cv2
    import numpy as np

    small = np.random.default_rng(seed).integers(0, 255, (107, 60), dtype=np.uint8)
    return cv2.resize(small, (480, 854), interpolation=cv2.INTER_CUBIC)


def _frame(image: object) -> Frame:
    import cv2

    return Frame(second=0.0, jpeg=cv2.imencode(".jpg", image)[1].tobytes())


async def test_orb_finds_a_cropped_overlaid_copy() -> None:
    import cv2

    original = _texture(1)
    copy = cv2.resize(original[85:769, 48:432], (480, 854))  # cropped 10%, zoomed back
    cv2.rectangle(copy, (0, 0), (480, 90), 255, -1)  # a header bar
    cv2.putText(copy, "JawaPos", (20, 60), cv2.FONT_HERSHEY_SIMPLEX, 2, 0, 3)
    matcher = OrbMatcher(step=1)
    a = await matcher.prepare([_frame(original)])
    b = await matcher.prepare([_frame(copy)])
    other = await matcher.prepare([_frame(_texture(2))])
    assert max(max(row) for row in await matcher.matrix(a, b)) >= 25
    assert max(max(row) for row in await matcher.matrix(a, other)) < 25
