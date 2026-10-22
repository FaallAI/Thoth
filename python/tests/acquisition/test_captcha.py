"""The captcha solver: image math on synthetic puzzles, drag shape, and page wiring.

The image fixtures are generated, not recorded: a background with a framed gap and its exact
patch for `slide`, an analytically rotated disc for `whirl`. The fakes mirror the modal's DOM
as every maintained solver documents it and clear themselves when a drag lands where the
puzzle says it must.
"""

import base64
import random
import sys

import pytest

from thoth_control_plane.acquisition.captcha import (
    CONTAINER_SELECTOR,
    HANDLE_SELECTOR,
    IMAGE_SELECTOR,
    PIECE_SELECTOR,
    TRACK_SELECTOR,
    _decode,
    _drag,
    gap_offset,
    solve,
    whirl_angle,
)

cv2 = pytest.importorskip("cv2", reason="the solver's image math needs OpenCV")
numpy = pytest.importorskip("numpy", reason="the solver's image math needs NumPy")


NOTCH_X = 200
SLIDE_BOXES = {"image": (100, 50, 340, 190), "piece": (104, 110, 48, 60)}


def _slide_arrays(notch_x: int = NOTCH_X):
    """A noisy background with a framed gap at `notch_x`, and the patch that fills it."""
    rng = numpy.random.default_rng(7)
    background = rng.integers(0, 255, (190, 340, 3), dtype=numpy.uint8)
    patch = background[60 : 60 + 60, notch_x : notch_x + 48].copy()
    cv2.rectangle(background, (notch_x, 60), (notch_x + 48, 60 + 60), (0, 0, 0), 2)
    piece = numpy.dstack([patch, numpy.full((60, 48), 255, numpy.uint8)])
    return background, piece


def _png(image) -> bytes:
    ok, encoded = cv2.imencode(".png", image)
    assert ok
    return encoded.tobytes()


def _data_url(image) -> str:
    return "data:image/png;base64," + base64.b64encode(_png(image)).decode()


def _whirl_arrays(angle: float = 35.0):
    """A disc with an angular pattern, and the same disc rotated by `-angle`.

    The pattern mixes coprime frequencies so no rotation other than the exact one can match.
    """
    yy, xx = numpy.mgrid[:200, :200]
    theta = numpy.arctan2(yy - 100.0, xx - 100.0)
    disc = (
        (numpy.sin(theta * 2) + 0.6 * numpy.sin(theta * 3) + 0.3 * numpy.sin(theta * 7) + 1.9) * 63
    ).astype(numpy.uint8)
    matrix = cv2.getRotationMatrix2D((100.0, 100.0), -angle, 1.0)
    return cv2.warpAffine(disc, matrix, (200, 200)), disc


def test_gap_offset_finds_the_framed_gap() -> None:
    background, piece = _slide_arrays()

    assert abs(gap_offset(background, piece) - NOTCH_X) <= 3


def test_gap_offset_ignores_transparent_margins_on_the_piece() -> None:
    background, piece = _slide_arrays()
    padded = numpy.zeros((100, 96, 4), numpy.uint8)
    padded[20:80, 24:72] = piece

    assert abs(gap_offset(background, padded) - NOTCH_X) <= 3


def test_gap_offset_rejects_an_invisible_piece() -> None:
    background, piece = _slide_arrays()
    piece[:, :, 3] = 0

    assert gap_offset(background, piece) is None


def test_whirl_angle_recovers_a_known_rotation() -> None:
    inner, outer = _whirl_arrays(35.0)

    assert abs(whirl_angle(inner, outer) - 35.0) <= 3


def test_whirl_angle_rejects_images_too_small_to_hold_a_ring() -> None:
    blank = numpy.zeros((20, 20), numpy.uint8)
    assert whirl_angle(blank, blank) is None


class FakeMouse:
    def __init__(self, on_up=None) -> None:
        self.moves: list[tuple[float, float]] = []
        self.downs = 0
        self.ups = 0
        self._on_up = on_up

    async def move(self, x: float, y: float) -> None:
        self.moves.append((x, y))

    async def down(self) -> None:
        self.downs += 1

    async def up(self) -> None:
        self.ups += 1
        if self._on_up is not None:
            self._on_up()


class FakeElement:
    def __init__(self, box: tuple[float, float, float, float], src: str = "") -> None:
        self._box = dict(zip(("x", "y", "width", "height"), box, strict=True))
        self._src = src

    async def bounding_box(self) -> dict:
        return dict(self._box)

    async def get_attribute(self, name: str) -> str | None:
        return self._src if name == "src" else None


class FakeCaptchaPage:
    """The modal as `solve` sees it; a drag clears it only when it lands on the puzzle's answer."""

    def __init__(self, elements: dict, imgs: list, accept: list[float]) -> None:
        self.elements = elements
        self.imgs = imgs
        self.accept = list(accept)  # the final pointer x each attempt must land on
        self.cleared = False
        self.mouse = FakeMouse(on_up=self._landed)

    def _landed(self) -> None:
        if not self.accept:
            return
        if abs(self.mouse.moves[-1][0] - self.accept[0]) <= 3:
            self.cleared = True
        else:
            self.accept.pop(0)

    async def query_selector(self, selector: str):
        if selector == CONTAINER_SELECTOR:
            return None if self.cleared else object()
        return self.elements.get(selector)

    async def query_selector_all(self, selector: str):
        assert selector == "img"
        return list(self.imgs)

    async def wait_for_timeout(self, timeout: int) -> None:
        return None


def _slide_page(accept: list[float]) -> FakeCaptchaPage:
    background, piece = _slide_arrays()
    image = FakeElement(SLIDE_BOXES["image"], _data_url(background))
    return FakeCaptchaPage(
        {
            IMAGE_SELECTOR: image,
            PIECE_SELECTOR: FakeElement(SLIDE_BOXES["piece"], _data_url(piece)),
            HANDLE_SELECTOR: FakeElement((120, 294, 40, 24)),
        },
        [image],
        accept,
    )


async def test_solve_drags_the_piece_into_the_gap_and_clears_the_modal() -> None:
    # handle centre 140 + drag (image x 100 + gap 200 - piece x 104) = 336.
    page = _slide_page(accept=[336])

    assert await solve(page, rng=random.Random(1)) is True
    assert page.cleared is True
    assert page.mouse.downs == 1 and page.mouse.ups == 1


async def test_solve_reports_failure_when_the_modal_stays() -> None:
    page = _slide_page(accept=[500])  # the puzzle's answer is 336, so both attempts miss

    assert await solve(page, rng=random.Random(1)) is False
    assert page.cleared is False
    assert page.mouse.ups == 2


async def test_solve_skips_a_subtype_with_nothing_to_drag() -> None:
    background, _ = _slide_arrays()
    image = FakeElement(SLIDE_BOXES["image"], _data_url(background))
    page = FakeCaptchaPage(
        {IMAGE_SELECTOR: image, HANDLE_SELECTOR: FakeElement((120, 294, 40, 24))},
        [image],  # no piece, no second image: neither drag subtype applies
        accept=[],
    )

    assert await solve(page, rng=random.Random(1)) is False
    assert page.mouse.downs == 0


async def test_solve_flips_the_whirl_direction_on_the_second_attempt() -> None:
    inner, outer = _whirl_arrays(35.0)
    outer_image = FakeElement((100, 50, 200, 200), _data_url(outer))
    page = FakeCaptchaPage(
        {
            IMAGE_SELECTOR: outer_image,
            TRACK_SELECTOR: FakeElement((100, 300, 340, 8)),
            HANDLE_SELECTOR: FakeElement((100, 294, 40, 24)),
        },
        [outer_image, FakeElement((140, 90, 120, 120), _data_url(inner))],
        # span 300: first attempt 300*35/360 lands at 120+29.2, second 300*325/360 at 120+270.8.
        accept=[199.2, 390.8],
    )

    assert await solve(page, rng=random.Random(1)) is True
    assert page.cleared is True


async def test_solve_degrades_to_false_without_opencv(monkeypatch, caplog) -> None:
    monkeypatch.setitem(sys.modules, "cv2", None)
    page = _slide_page(accept=[336])
    import logging

    with caplog.at_level(logging.WARNING, logger="thoth_control_plane.acquisition.captcha"):
        assert await solve(page, rng=random.Random(1)) is False
    assert "opencv" in " ".join(record.getMessage() for record in caplog.records)
    assert page.mouse.downs == 0


async def test_the_drag_eases_out_overshoots_and_settles_on_the_target() -> None:
    class Page:
        def __init__(self) -> None:
            self.mouse = FakeMouse()

        async def wait_for_timeout(self, timeout: int) -> None:
            return None

    page = Page()
    handle = FakeElement((120, 294, 40, 24))
    await _drag(page, handle, 196.0, random.Random(1))

    moves = page.mouse.moves
    assert len(moves) >= 36
    assert moves[0] == (140.0, 306.0)  # starts on the handle's centre
    assert abs(moves[-1][0] - 336.0) <= 0.5  # settles on the exact target
    assert all(abs(y - 306.0) <= 2.0 for _, y in moves)
    backwards = [a[0] - b[0] for a, b in zip(moves[1:], moves[:-1], strict=True) if b[0] > a[0]]
    assert backwards and max(backwards) < 12  # the overshoot, then a settle back
    assert page.mouse.downs == 1 and page.mouse.ups == 1


def test_decode_reads_png_bytes() -> None:
    background, _ = _slide_arrays()

    assert _decode(_png(background)).shape[:2] == (190, 340)
