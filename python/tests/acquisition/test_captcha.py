"""The captcha solver: image math on recorded and synthetic puzzles, drag shape, page wiring.

The whirl fixtures are the images TikTok served on 2026-10-23 (a ring around a white hole, and
the disc that fills it); the slide fixtures are generated — a background with a framed gap and
its exact patch. The fakes mirror the modal's DOM as every maintained solver documents it and
clear themselves when a drag lands where the puzzle says it must.
"""

import base64
import logging
import random
import sys
from pathlib import Path
from typing import Any

import pytest

from thoth_control_plane.acquisition.captcha import (
    CONTAINER_SELECTOR,
    HANDLE_SELECTOR,
    IMAGE_SELECTOR,
    PIECE_SELECTOR,
    WHIRL_IMAGE_SELECTOR,
    _decode,
    _drag,
    _rotation_deg,
    _whirl_drag,
    gap_offset,
    solve,
    whirl_angle,
    whirl_distance,
)

cv2 = pytest.importorskip("cv2", reason="the solver's image math needs OpenCV")
numpy = pytest.importorskip("numpy", reason="the solver's image math needs NumPy")


FIXTURES = Path(__file__).parent / "fixtures"
NOTCH_X = 200
SLIDE_BOXES = {"image": (100, 50, 340, 190), "piece": (104, 110, 48, 60)}
WHIRL_TURNS = 360.0 / 284.0  # the fake modal's disc degrees per slider pixel


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


def _whirl_arrays(angle: float = 60.0):
    """A textured disc, and the ring whose hole it fills, turned `angle` degrees apart.

    The pattern mixes coprime frequencies so no rotation other than the exact one can align
    the rims: the disc's rim carries the pattern shifted by `angle`, so standing it upright
    takes a clockwise turn of exactly that many degrees. The ring's hole sits where the fake
    page's rendered sizes put it (a 300px ring shown at 210px, its 200px disc at 128px), the
    same on-screen invariant the real modal keeps.
    """

    def pattern(phi):
        return (numpy.sin(2 * phi) + 0.6 * numpy.sin(3 * phi) + 0.3 * numpy.sin(7 * phi) + 1.9) * 63

    yy, xx = numpy.mgrid[:200, :200]
    disc = pattern(numpy.arctan2(yy - 99.5, xx - 99.5) + numpy.deg2rad(angle))
    yo, xo = numpy.mgrid[:300, :300]
    radius = numpy.sqrt((xo - 149.5) ** 2 + (yo - 149.5) ** 2)
    spoke = pattern(numpy.arctan2(yo - 149.5, xo - 149.5))
    ring = numpy.where((radius > 91) & (radius < 160), spoke, 255.0)
    disc3 = numpy.dstack([disc] * 3).astype(numpy.uint8)
    ring3 = numpy.dstack([ring] * 3).astype(numpy.uint8)
    return disc3, ring3


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


def test_whirl_angle_aligns_the_recorded_modal_pair() -> None:
    inner = _decode((FIXTURES / "whirl_inner.webp").read_bytes())
    outer = _decode((FIXTURES / "whirl_outer.webp").read_bytes())

    assert inner is not None and outer is not None
    assert abs(whirl_angle(inner, outer) - 60.0) <= 3


def test_whirl_angle_derives_the_hole_radius_from_the_rendered_ratio() -> None:
    """A disc served at another native resolution still lines up when the hole radius comes
    from the modal's rendered sizes, not from the disc's own pixels."""
    inner = _decode((FIXTURES / "whirl_inner.webp").read_bytes())
    outer = _decode((FIXTURES / "whirl_outer.webp").read_bytes())
    resized = cv2.resize(inner, (160, 160), interpolation=cv2.INTER_AREA)
    hole = (128.0 / 210.0) * outer.shape[1] / 2.0  # the recorded modal's rendered size ratio

    assert abs(whirl_angle(resized, outer, hole_radius=hole) - 60.0) <= 3


def test_whirl_angle_rejects_images_too_small_to_hold_a_ring() -> None:
    blank = numpy.zeros((20, 20), numpy.uint8)
    assert whirl_angle(blank, blank) is None


def test_whirl_distance_follows_the_measured_drag_direction() -> None:
    span, turns = 284.0, 360.0 / 284.0

    assert abs(whirl_distance(60.0, turns, span) - 60.0 / turns) < 0.1  # forward turns the disc
    assert abs(whirl_distance(60.0, -turns, span) - 300.0 / turns) < 0.1  # one full turn back
    assert whirl_distance(60.0, 0.5, 20.0) is None  # no candidate fits the span
    assert whirl_distance(60.0, 0.0, span) is None  # the drag rotates nothing


def test_rotation_deg_reads_the_transform_style() -> None:
    assert _rotation_deg("rotate(0deg)") == 0.0
    assert _rotation_deg("translateX(12px) rotate(-33.5deg)") == -33.5
    assert _rotation_deg("rotate(10deg) rotate(20deg)") == 30.0
    assert _rotation_deg("") == 0.0
    assert _rotation_deg("none") == 0.0


class FakeMouse:
    def __init__(self, on_up=None, on_down=None, on_move=None) -> None:
        self.moves: list[tuple[float, float]] = []
        self.downs = 0
        self.ups = 0
        self._on_up = on_up
        self._on_down = on_down
        self._on_move = on_move

    async def move(self, x: float, y: float) -> None:
        self.moves.append((x, y))
        if self._on_move is not None:
            self._on_move(x, y)

    async def down(self) -> None:
        self.downs += 1
        if self._on_down is not None:
            self._on_down()

    async def up(self) -> None:
        self.ups += 1
        if self._on_up is not None:
            self._on_up()


class FakeElement:
    Box = tuple[float, float, float, float]

    def __init__(self, box: Box, src: str = "", evaluates: Any = None) -> None:
        self._box = dict(zip(("x", "y", "width", "height"), box, strict=True))
        self._src = src
        self._evaluates = evaluates

    async def bounding_box(self) -> dict:
        return dict(self._box)

    async def get_attribute(self, name: str) -> str | None:
        return self._src if name == "src" else None

    async def evaluate(self, script: str, arg: Any = None) -> Any:
        return self._evaluates() if callable(self._evaluates) else self._evaluates


class FakeImage(FakeElement):
    """A modal image whose inline rotation the fake page turns while the pointer is held."""

    def __init__(self, box: tuple[float, float, float, float], src: str) -> None:
        super().__init__(box, src)
        self.rotation = 0.0

    async def evaluate(self, script: str, arg: Any = None) -> Any:
        return f"rotate({self.rotation:.2f}deg)"


class FakeCaptchaPage:
    """The modal as `solve` sees it; a drag clears it only when it lands on the answer."""

    def __init__(self, elements: dict, imgs: list, accept: list[float], container=None) -> None:
        self.elements = elements
        self.imgs = imgs
        self.accept = list(accept)  # the final pointer x each attempt must land on
        self.container = container
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
            if self.cleared:
                return None
            return self.container if self.container is not None else object()
        return self.elements.get(selector)

    async def query_selector_all(self, selector: str):
        assert selector == WHIRL_IMAGE_SELECTOR
        return list(self.imgs)

    async def wait_for_timeout(self, timeout: int) -> None:
        return None


class FakeWhirlPage:
    """The 2026 whirl modal as `solve` sees it: two images sized apart, a handle in a draggable
    wrapper, and a disc that rotates with the pointer until it is released."""

    def __init__(self, imgs: list[FakeImage], degrees_per_px: float) -> None:
        self.elements = {HANDLE_SELECTOR: FakeElement((466, 553, 64, 40), evaluates=348.0)}
        self.imgs = imgs
        self.degrees_per_px = degrees_per_px
        self.cleared = False
        self.mouse = FakeMouse(on_up=self._released, on_down=self._pressed, on_move=self._moved)
        self._held = False
        self._down_x = 0.0

    @property
    def inner(self) -> FakeImage:
        return self.imgs[1]

    def _pressed(self) -> None:
        self._held = True
        self._down_x = self.mouse.moves[-1][0]

    def _moved(self, x: float, y: float) -> None:
        if self._held:
            self.inner.rotation = (x - self._down_x) * self.degrees_per_px

    def _released(self) -> None:
        self._held = False
        drift = abs(self.inner.rotation - 60.0) % 360.0
        if min(drift, 360.0 - drift) <= 3.0:
            self.cleared = True

    async def query_selector(self, selector: str):
        if selector == CONTAINER_SELECTOR:
            return None if self.cleared else object()
        return self.elements.get(selector)

    async def query_selector_all(self, selector: str):
        assert selector == WHIRL_IMAGE_SELECTOR
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


def _whirl_page(degrees_per_px: float) -> FakeWhirlPage:
    disc, ring = _whirl_arrays(60.0)
    return FakeWhirlPage(
        [
            FakeImage((535, 337, 210, 210), _data_url(ring)),
            FakeImage((576, 378, 128, 128), _data_url(disc)),
        ],
        degrees_per_px,
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


def _outcome_lines(caplog) -> list[str]:
    return [
        record.getMessage()
        for record in caplog.records
        if "tiktok captcha outcome" in record.getMessage()
    ]


async def test_solve_ends_in_exactly_one_outcome_line(caplog) -> None:
    page = _slide_page(accept=[336])

    with caplog.at_level(logging.INFO, logger="thoth_control_plane.acquisition.captcha"):
        assert await solve(page, rng=random.Random(1)) is True

    assert _outcome_lines(caplog) == [
        "tiktok captcha outcome subtype=slide solved=true attempts=1 reason=none"
    ]


async def test_solve_outcomes_report_a_modal_that_stays(caplog) -> None:
    page = _slide_page(accept=[500])

    with caplog.at_level(logging.INFO, logger="thoth_control_plane.acquisition.captcha"):
        assert await solve(page, rng=random.Random(1)) is False

    assert _outcome_lines(caplog) == [
        "tiktok captcha outcome subtype=slide solved=false attempts=2 reason=modal_stayed"
    ]


async def test_solve_outcomes_report_a_whirl_with_no_drag_distance(caplog) -> None:
    page = _whirl_page(0.0)

    with caplog.at_level(logging.INFO, logger="thoth_control_plane.acquisition.captcha"):
        assert await solve(page, rng=random.Random(1)) is False

    assert _outcome_lines(caplog) == [
        "tiktok captcha outcome subtype=whirl solved=false attempts=2 reason=no_distance"
    ]


async def test_solve_reports_an_unrecognized_subtype_without_clicking(caplog) -> None:
    background, _ = _slide_arrays()
    image = FakeElement(SLIDE_BOXES["image"], _data_url(background))
    page = FakeCaptchaPage(
        {IMAGE_SELECTOR: image, HANDLE_SELECTOR: FakeElement((120, 294, 40, 24))},
        [image],  # no piece and no image pair: nothing the solver knows how to answer
        accept=[],
    )

    with caplog.at_level(logging.INFO, logger="thoth_control_plane.acquisition.captcha"):
        assert await solve(page, rng=random.Random(1)) is False

    assert page.mouse.downs == 0
    # A drag handle means a drag subtype whose parts have not rendered yet: retried, and
    # reported as missing images, never as unsupported.
    assert _outcome_lines(caplog) == [
        "tiktok captcha outcome subtype=unknown solved=false attempts=2 reason=no_images"
    ]


class LateWhirlPage(FakeWhirlPage):
    """A whirl modal whose images have not rendered on the first look."""

    def __init__(self, imgs: list[FakeImage], degrees_per_px: float) -> None:
        super().__init__(imgs, degrees_per_px)
        self.rendered = False

    async def query_selector_all(self, selector: str):
        return await super().query_selector_all(selector) if self.rendered else []

    async def wait_for_timeout(self, timeout: int) -> None:
        self.rendered = True


async def test_a_whirl_whose_images_load_late_is_solved_on_the_retry(caplog) -> None:
    # Review: an unrendered whirl was classified unknown -> unsupported and never retried.
    disc, ring = _whirl_arrays(60.0)
    page = LateWhirlPage(
        [
            FakeImage((535, 337, 210, 210), _data_url(ring)),
            FakeImage((576, 378, 128, 128), _data_url(disc)),
        ],
        WHIRL_TURNS,
    )
    with caplog.at_level(logging.INFO, logger="thoth_control_plane.acquisition.captcha"):
        assert await solve(page, rng=random.Random(1)) is True
    assert _outcome_lines(caplog) == [
        "tiktok captcha outcome subtype=whirl solved=true attempts=2 reason=none"
    ]


class SlowCloseWhirlPage(FakeWhirlPage):
    """A whirl modal that, once answered, takes `close_ms` of waiting to disappear: live
    2026-10-23 (signed in) the modal outlasted the old fixed 1.5 s check after a right answer."""

    def __init__(self, imgs: list[FakeImage], degrees_per_px: float, close_ms: int) -> None:
        super().__init__(imgs, degrees_per_px)
        self.close_ms = close_ms
        self.waited_after = 0

    def _released(self) -> None:
        super()._released()
        self.answered, self.cleared = self.cleared, False

    async def wait_for_timeout(self, timeout: int) -> None:
        if getattr(self, "answered", False):
            self.waited_after += timeout
            self.cleared = self.waited_after >= self.close_ms


async def test_a_right_answer_whose_modal_closes_slowly_is_a_solve(caplog) -> None:
    disc, ring = _whirl_arrays(60.0)
    page = SlowCloseWhirlPage(
        [
            FakeImage((535, 337, 210, 210), _data_url(ring)),
            FakeImage((576, 378, 128, 128), _data_url(disc)),
        ],
        WHIRL_TURNS,
        close_ms=3_500,
    )
    with caplog.at_level(logging.INFO, logger="thoth_control_plane.acquisition.captcha"):
        assert await solve(page, rng=random.Random(1)) is True
    assert _outcome_lines(caplog) == [
        "tiktok captcha outcome subtype=whirl solved=true attempts=1 reason=none"
    ]


def _click_page(prompt: str) -> FakeCaptchaPage:
    """A click-shaped modal: a prompt, an image, and no drag handle anywhere."""
    background, _ = _slide_arrays()
    image = FakeElement(SLIDE_BOXES["image"], _data_url(background))
    return FakeCaptchaPage(
        {IMAGE_SELECTOR: image},
        [image],
        accept=[],
        container=FakeElement((100, 50, 340, 190), evaluates=[prompt]),
    )


@pytest.mark.parametrize(
    ("prompt", "subtype"),
    [
        ("Select the two objects with the same shape", "3d"),
        ("Klik dua benda dengan bentuk yang sama", "3d"),
        ("Click the icons that match the prompt", "icon"),
        ("Klik semua ikon yang sesuai", "icon"),
        ("Rearrange the tiles until the picture is whole", "unknown"),
    ],
)
async def test_click_subtypes_are_classified_from_the_prompt_and_left_alone(
    prompt, subtype, caplog
) -> None:
    page = _click_page(prompt)

    with caplog.at_level(logging.INFO, logger="thoth_control_plane.acquisition.captcha"):
        assert await solve(page, rng=random.Random(1)) is False

    assert page.mouse.downs == 0  # a click subtype is never answered at random
    assert _outcome_lines(caplog) == [
        f"tiktok captcha outcome subtype={subtype} solved=false attempts=1 reason=unsupported"
    ]


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


@pytest.mark.parametrize("degrees_per_px", [-WHIRL_TURNS, WHIRL_TURNS])
async def test_solve_turns_the_disc_whichever_way_the_slider_rotates_it(degrees_per_px) -> None:
    page = _whirl_page(degrees_per_px)

    assert await solve(page, rng=random.Random(1)) is True
    assert page.cleared is True
    assert page.mouse.downs == 1 and page.mouse.ups == 1


async def test_solve_releases_the_handle_when_the_drag_rotates_nothing() -> None:
    page = _whirl_page(0.0)

    assert await solve(page, rng=random.Random(1)) is False
    assert page.cleared is False
    assert page.mouse.downs == 2 and page.mouse.ups == 2  # both attempts end in a release


async def test_the_drag_releases_the_button_when_a_pointer_move_fails() -> None:
    class Page:
        def __init__(self) -> None:
            self.seen = 0
            self.mouse = FakeMouse(on_move=self._moved)

        def _moved(self, x: float, y: float) -> None:
            self.seen += 1
            if self.seen > 3:
                raise RuntimeError("detached")

        async def wait_for_timeout(self, timeout: int) -> None:
            return None

    page = Page()
    handle = FakeElement((120, 294, 40, 24))

    with pytest.raises(RuntimeError):
        await _drag(page, handle, 196.0, random.Random(1))

    assert page.mouse.downs == 1 and page.mouse.ups == 1


async def test_the_whirl_drag_releases_the_button_when_a_pointer_move_fails() -> None:
    page = _whirl_page(WHIRL_TURNS)
    original = page.mouse._on_move
    seen = 0

    def failing(x: float, y: float) -> None:
        nonlocal seen
        seen += 1
        if seen > 4:  # the first move hovers, the down follows, the failure lands mid-drag
            raise RuntimeError("detached")
        original(x, y)

    page.mouse._on_move = failing

    with pytest.raises(RuntimeError):
        await _whirl_drag(page, page.elements[HANDLE_SELECTOR], random.Random(1))

    assert page.mouse.downs == 1 and page.mouse.ups == 1


async def test_solve_degrades_to_false_without_opencv(monkeypatch, caplog) -> None:
    monkeypatch.setitem(sys.modules, "cv2", None)
    page = _slide_page(accept=[336])
    import logging

    with caplog.at_level(logging.INFO, logger="thoth_control_plane.acquisition.captcha"):
        assert await solve(page, rng=random.Random(1)) is False
    assert "opencv" in " ".join(record.getMessage() for record in caplog.records)
    assert page.mouse.downs == 0
    assert _outcome_lines(caplog) == [
        "tiktok captcha outcome subtype=unknown solved=false attempts=0 reason=error"
    ]


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
