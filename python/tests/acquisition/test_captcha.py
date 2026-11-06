"""The captcha solver: image math on recorded and synthetic puzzles, drag shape, page wiring.

The whirl fixtures are the images TikTok served on 2026-10-23 (a ring around a white hole, and
the disc that fills it); the slide fixtures are generated — a background with a framed gap and
its exact patch. The fakes mirror the modal's DOM as every maintained solver documents it and
clear themselves when a drag lands where the puzzle says it must. The 3D flow is tested the
same way against synthetic challenge images whose same-shape pair is known by construction.
"""

import base64
import json
import logging
import random
import sys
from pathlib import Path
from types import SimpleNamespace
from typing import Any, ClassVar

import pytest

from thoth_control_plane import metering
from thoth_control_plane.acquisition import captcha as captcha
from thoth_control_plane.acquisition.captcha import (
    CLICK_IMAGE_SELECTOR,
    CONFIRM_SELECTOR,
    CONTAINER_SELECTOR,
    HANDLE_SELECTOR,
    IMAGE_SELECTOR,
    PIECE_SELECTOR,
    REFRESH_SELECTOR,
    WHIRL_IMAGE_SELECTOR,
    _decode,
    _drag,
    _rotation_deg,
    _sanitize_dom,
    _VisionPick,
    _whirl_drag,
    gap_offset,
    solve,
    whirl_angle,
    whirl_distance,
)
from thoth_control_plane.metering import MeterScope

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

    async def screenshot(self, clip: dict | None = None, **kwargs: Any) -> bytes:
        self.captured_clip = clip
        return b"\x89PNG\r\n\x1a\nfake"


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


async def test_a_whirl_whose_images_load_late_is_solved_without_spending_an_attempt(
    caplog,
) -> None:
    # Review: an unrendered whirl was classified unknown -> unsupported and never retried.
    # Stage1, 2026-11-06: the fresh challenge after a miss had not rendered within the 400 ms
    # between attempts, so the second attempt ended no_images; the attempt now waits for it.
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
        "tiktok captcha outcome subtype=whirl solved=true attempts=1 reason=none"
    ]


def _capturable_slide_page(accept: list[float]) -> FakeCaptchaPage:
    page = _slide_page(accept)
    page.container = FakeClickModal("Drag the slider to fit the puzzle", CLICK_DOM, [])
    return page


async def test_a_drag_the_modal_survives_leaves_the_challenge_it_answered(
    tmp_path, monkeypatch
) -> None:
    """A failed drag records the challenge as it was before the drag: after a miss TikTok
    loads a fresh one, so a picture taken afterwards would show the wrong challenge."""
    monkeypatch.setenv("THOTH_CONTROL_PLANE_ARTIFACT_ROOT", str(tmp_path))
    page = _capturable_slide_page(accept=[500])  # both attempts miss the 336 answer
    background, _ = _slide_arrays()

    assert await solve(page, rng=random.Random(1)) is False

    dirs = _sample_dirs(tmp_path)
    assert len(dirs) == 2  # one per attempt
    for sample in dirs:
        meta = json.loads((sample / "sample.json").read_text(encoding="utf-8"))
        assert meta["subtype"] == "slide" and meta["reason"] == "modal_stayed"
        assert (sample / "image-0.png").read_bytes() == _png(background)


async def test_a_solved_drag_leaves_no_sample(tmp_path, monkeypatch) -> None:
    monkeypatch.setenv("THOTH_CONTROL_PLANE_ARTIFACT_ROOT", str(tmp_path))
    page = _capturable_slide_page(accept=[336])

    assert await solve(page, rng=random.Random(1)) is True

    assert _sample_dirs(tmp_path) == []


async def test_a_drag_handle_whose_images_never_render_leaves_a_sample(
    tmp_path, monkeypatch
) -> None:
    monkeypatch.setenv("THOTH_CONTROL_PLANE_ARTIFACT_ROOT", str(tmp_path))
    background, _ = _slide_arrays()
    image = FakeElement(SLIDE_BOXES["image"], _data_url(background))
    page = FakeCaptchaPage(
        {IMAGE_SELECTOR: image, HANDLE_SELECTOR: FakeElement((120, 294, 40, 24))},
        [image],
        accept=[],
        container=FakeClickModal("Drag the slider", CLICK_DOM, []),
    )

    assert await solve(page, rng=random.Random(1)) is False

    reasons = [
        json.loads((sample / "sample.json").read_text(encoding="utf-8"))["reason"]
        for sample in _sample_dirs(tmp_path)
    ]
    assert reasons == ["no_images", "no_images"]


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


CLICK_DOM = (
    '<div class="TUXModal captcha-verify-container">'
    '<span class="cap-break-words cap-text-left">Select 2 objects that are the same shape</span>'
    '<img src="data:image/png;base64,AAAA" alt="Verify that you\'re not a robot">'
    '<button class="TUXButton TUXButton--primary" aria-disabled="true">Confirm</button>'
    "</div>"
)


class FakeClickModal(FakeElement):
    """A click modal's container: answers the scripts the evidence capture reads."""

    def __init__(self, prompt: str, outer_html: str, boxes: Any, canvases: Any = ()) -> None:
        super().__init__((100, 50, 340, 190), evaluates=[prompt])
        self._outer_html = outer_html
        self._boxes = boxes
        self._canvases = list(canvases)

    async def evaluate(self, script: str, arg: Any = None) -> Any:
        if "outerHTML" in script:
            return self._outer_html
        if "getBoundingClientRect" in script:
            return self._boxes
        return self._evaluates

    async def query_selector_all(self, selector: str):
        assert selector == "canvas"
        return self._canvases


def _capture_click_page(prompt: str, dom: str) -> FakeCaptchaPage:
    background, _ = _slide_arrays()
    image = FakeElement(SLIDE_BOXES["image"], _data_url(background))
    remote = FakeElement(
        (104, 94, 60, 60), "https://p19-rc-captcha-va.ibyteimg.com/x/3d_2385_0dabbdd1_1.jpg"
    )  # the documented shapes image URL shape; its fetch fails on the fake, hint stays
    return FakeCaptchaPage(
        {IMAGE_SELECTOR: image},
        [image, remote],
        accept=[],
        container=FakeClickModal(
            prompt,
            dom,
            [
                {"tag": "img", "box": {"x": 100.0, "y": 90.0, "width": 340.0, "height": 190.0}},
                {"tag": "button", "box": {"x": 100.0, "y": 300.0, "width": 340.0, "height": 40.0}},
            ],
        ),
    )


def _sample_dirs(root: Path) -> list[Path]:
    samples = root / "captcha-samples"
    return sorted(samples.iterdir()) if samples.exists() else []


async def test_an_unanswerable_modal_saves_one_sanitized_sample(tmp_path, monkeypatch) -> None:
    monkeypatch.setenv("THOTH_CONTROL_PLANE_ARTIFACT_ROOT", str(tmp_path))
    page = _capture_click_page("Select 2 objects that are the same shape", CLICK_DOM)

    assert await solve(page, rng=random.Random(1)) is False

    dirs = _sample_dirs(tmp_path)
    assert len(dirs) == 1
    meta = json.loads((dirs[0] / "sample.json").read_text(encoding="utf-8"))
    assert meta["subtype"] == "3d"  # the documented English shapes prompt classifies
    assert meta["reason"] == "unsupported"
    assert meta["prompt_candidates"] == ["Select 2 objects that are the same shape"]
    assert [box["tag"] for box in meta["boxes"]] == ["img", "button"]
    assert meta["images"] == [
        {"file": "image-0.png", "src_hint": ""},
        {"src_hint": "3d"},  # a URL marker the sanitized DOM no longer carries
    ]
    dom = (dirs[0] / "dom.html").read_text(encoding="utf-8")
    assert "Select 2 objects" in dom
    assert 'src=""' in dom and "data:image/png" not in dom  # token-like values are blanked
    assert (dirs[0] / "image-0.png").read_bytes()[:4] == b"\x89PNG"


async def test_sample_capture_keeps_only_the_newest_fifty(tmp_path, monkeypatch) -> None:
    monkeypatch.setenv("THOTH_CONTROL_PLANE_ARTIFACT_ROOT", str(tmp_path))
    samples = tmp_path / "captcha-samples"
    for index in range(50):
        (samples / f"20200101T000000{index:06d}Z").mkdir(parents=True)
    page = _capture_click_page("Select 2 objects that are the same shape", CLICK_DOM)

    assert await solve(page, rng=random.Random(1)) is False

    dirs = _sample_dirs(tmp_path)
    assert len(dirs) == 50
    assert not (samples / "20200101T000000000000Z").exists()  # the oldest gave way
    assert (dirs[-1] / "sample.json").exists()  # the new sample is the newest kept


async def test_a_failing_capture_never_changes_the_outcome(tmp_path, monkeypatch, caplog) -> None:
    monkeypatch.setenv("THOTH_CONTROL_PLANE_ARTIFACT_ROOT", str(tmp_path))

    class ExplodingContainer(FakeElement):
        async def evaluate(self, script: str, arg: Any = None) -> Any:
            raise RuntimeError("detached")

    background, _ = _slide_arrays()
    image = FakeElement(SLIDE_BOXES["image"], _data_url(background))
    page = FakeCaptchaPage(
        {IMAGE_SELECTOR: image},
        [image],
        accept=[],
        container=ExplodingContainer((100, 50, 340, 190)),
    )

    with caplog.at_level(logging.INFO, logger="thoth_control_plane.acquisition.captcha"):
        assert await solve(page, rng=random.Random(1)) is False

    assert page.mouse.downs == 0
    assert _outcome_lines(caplog) == [
        "tiktok captcha outcome subtype=unknown solved=false attempts=1 reason=unsupported"
    ]


async def test_no_sample_is_written_without_the_artifact_root(tmp_path, monkeypatch) -> None:
    monkeypatch.delenv("THOTH_CONTROL_PLANE_ARTIFACT_ROOT", raising=False)
    monkeypatch.chdir(tmp_path)
    page = _capture_click_page("Select 2 objects that are the same shape", CLICK_DOM)

    assert await solve(page, rng=random.Random(1)) is False

    assert list(tmp_path.rglob("captcha-samples")) == []
    assert not (tmp_path / ".thoth-artifacts").exists()


def test_the_dom_scrub_blanks_protocol_relative_blob_and_style_urls() -> None:
    dom = (
        '<img src="//p16-rc-captcha-va.ibyteimg.com/obj?x-signature=abc123">'
        '<img src="blob:https://m.tiktok.com/7a2f9e">'
        '<div style="background:url(//p16-rc-captcha-va.ibyteimg.com/a.png); color:red"></div>'
        '<div style="transform: rotate(60deg)"></div>'
    )

    scrubbed = _sanitize_dom(dom)

    assert 'src=""' in scrubbed and "x-signature" not in scrubbed
    assert "blob:https" not in scrubbed
    assert "color:red" in scrubbed  # the rest of the style survives
    assert "url(" in scrubbed and "ibyteimg" not in scrubbed  # the url() payload goes
    assert "rotate(60deg)" in scrubbed  # a clean style is untouched


async def test_a_canvas_challenge_still_yields_a_clipped_picture(tmp_path, monkeypatch) -> None:
    """The costliest Phase A failure would be a sample with no picture: if the live modal
    draws on a canvas, the DOM alone is not evidence."""
    monkeypatch.setenv("THOTH_CONTROL_PLANE_ARTIFACT_ROOT", str(tmp_path))
    canvas = FakeElement((100, 80, 340, 190), evaluates=_data_url(_slide_arrays()[0]))
    page = FakeCaptchaPage(
        {},
        [],
        accept=[],
        container=FakeClickModal(
            "Select 2 objects that are the same shape",
            CLICK_DOM,
            [
                {"tag": "canvas", "box": {"x": 100.0, "y": 80.0, "width": 340.0, "height": 190.0}},
                {"tag": "button", "box": {"x": 100.0, "y": 300.0, "width": 340.0, "height": 40.0}},
            ],
            canvases=[canvas],
        ),
    )

    assert await solve(page, rng=random.Random(1)) is False

    dirs = _sample_dirs(tmp_path)
    assert len(dirs) == 1
    meta = json.loads((dirs[0] / "sample.json").read_text(encoding="utf-8"))
    union = {"x": 100.0, "y": 80.0, "width": 340.0, "height": 260.0}
    assert meta["visuals"]["modal"] == {"clip": union, "file": "modal.png"}
    assert meta["visuals"]["canvases"] == [{"file": "canvas-0.png"}]
    assert meta["images"] == []
    assert page.captured_clip == union  # the clip is the elements' union, never the viewport
    assert (dirs[0] / "modal.png").read_bytes()[:4] == b"\x89PNG"
    assert (dirs[0] / "canvas-0.png").read_bytes()[:4] == b"\x89PNG"


async def test_a_failed_screenshot_keeps_the_rest_of_the_sample(tmp_path, monkeypatch) -> None:
    monkeypatch.setenv("THOTH_CONTROL_PLANE_ARTIFACT_ROOT", str(tmp_path))
    page = _capture_click_page("Select 2 objects that are the same shape", CLICK_DOM)

    async def crash(**kwargs: Any) -> bytes:
        raise RuntimeError("target crashed")

    page.screenshot = crash

    assert await solve(page, rng=random.Random(1)) is False

    dirs = _sample_dirs(tmp_path)
    assert len(dirs) == 1
    meta = json.loads((dirs[0] / "sample.json").read_text(encoding="utf-8"))
    assert meta["visuals"]["modal"] is None
    assert (dirs[0] / "sample.json").exists()
    assert (dirs[0] / "dom.html").exists()
    assert (dirs[0] / "image-0.png").read_bytes()[:4] == b"\x89PNG"
    assert not (dirs[0] / "modal.png").exists()


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


# --- The 3D click flow (Phase B): synthetic challenges whose answer is known by construction.


def _star_polygon(cx: int, cy: int, radius: int) -> Any:
    angles = numpy.linspace(0, 2 * numpy.pi, 10, endpoint=False) + numpy.pi / 2
    radii = numpy.where(numpy.arange(10) % 2 == 0, radius, radius * 0.45)
    return numpy.int32(
        [[cx + r * numpy.cos(a), cy + r * numpy.sin(a)] for a, r in zip(angles, radii, strict=True)]
    )


def _shapes_arrays(two_objects: bool = False):
    """A white 552x344 card: two same-shape stars (the answer) among distinct shapes; with
    two_objects, only a star and a disc remain, which the solver must refuse to answer."""
    image = numpy.full((344, 552, 3), 250, numpy.uint8)
    cv2.fillPoly(image, [_star_polygon(90, 100, 42)], (0, 0, 255))
    labels = [(48, 58, 84, 84)]
    if not two_objects:
        cv2.fillPoly(image, [_star_polygon(330, 240, 32)], (255, 0, 0))
        cv2.fillPoly(image, [numpy.int32([(420, 60), (500, 60), (460, 130)])], (0, 255, 0))
        cv2.rectangle(image, (200, 40), (280, 76), (0, 255, 255), -1)
        labels.append((298, 208, 64, 64))
    else:
        cv2.circle(image, (400, 172), 46, (255, 0, 0), -1)
        labels.append((354, 126, 92, 92))  # both objects, so a vision pick can answer
    return image, labels


class FakeConfirm(FakeElement):
    """The Confirm button, disabled until two good clicks enable it."""

    def __init__(self, box: tuple[float, float, float, float], state: dict[str, str]) -> None:
        super().__init__(box)
        self.state = state

    async def get_attribute(self, name: str) -> str | None:
        return self.state.get(name)


def _inside(x: float, y: float, box: dict[str, float]) -> bool:
    return box["x"] <= x <= box["x"] + box["width"] and box["y"] <= y <= box["y"] + box["height"]


class FakeShapesPage:
    """The 3D click modal as solve sees it: clicks map through the image's rendered box,
    two clicks inside the labelled boxes enable Confirm, and Confirm clears the container
    unless stubborn. Refresh keeps the image unless after_refresh names the (src, targets)
    it swaps in."""

    def __init__(
        self,
        src: str,
        targets: list[tuple[int, int, int, int]],
        *,
        native: tuple[int, int] = (552, 344),
        stubborn: bool = False,
        refresh: bool = True,
        prompt: str = "Select 2 objects that are the same shape",
        after_refresh: tuple[str, list[tuple[int, int, int, int]]] | None = None,
    ) -> None:
        self.image = FakeElement((100, 50, 340, 212), src)
        self.image_box = {"x": 100.0, "y": 50.0, "width": 340.0, "height": 212.0}
        self.targets = targets
        self.native = native
        self.stubborn = stubborn
        self.confirm_state = {
            "class": "TUXButton TUXButton--disabled cap-w-full",
            "aria-disabled": "true",
        }
        self.confirm = FakeConfirm((100, 300, 340, 40), self.confirm_state)
        self.refresh = FakeElement((150, 360, 40, 28)) if refresh else None
        self.after_refresh = after_refresh
        self.container = FakeClickModal(prompt, CLICK_DOM, [])
        self.image_clicks = 0
        self.good_clicks = 0
        self.refresh_clicks = 0
        self.cleared = False
        self.mouse = FakeMouse(on_up=self._released)

    def _released(self) -> None:
        x, y = self.mouse.moves[-1]
        if _inside(x, y, self.image_box):
            self.image_clicks += 1
            ix = (x - self.image_box["x"]) / self.image_box["width"] * self.native[0]
            iy = (y - self.image_box["y"]) / self.image_box["height"] * self.native[1]
            if any(bx <= ix <= bx + bw and by <= iy <= by + bh for bx, by, bw, bh in self.targets):
                self.good_clicks += 1
            if self.image_clicks >= 2 and self.good_clicks >= 2:
                self.confirm_state["class"] = "TUXButton cap-w-full"
                self.confirm_state["aria-disabled"] = "false"
        elif _inside(x, y, {"x": 100.0, "y": 300.0, "width": 340.0, "height": 40.0}):
            if self.good_clicks >= 2 and not self.stubborn:
                self.cleared = True
        elif self.refresh is not None and _inside(
            x, y, {"x": 150.0, "y": 360.0, "width": 40.0, "height": 28.0}
        ):
            self.refresh_clicks += 1
            if self.after_refresh is not None:
                self.image._src, self.targets = self.after_refresh

    async def query_selector(self, selector: str):
        if selector == CONTAINER_SELECTOR:
            return None if self.cleared else self.container
        if selector == CLICK_IMAGE_SELECTOR:
            return self.image
        if selector == CONFIRM_SELECTOR:
            return self.confirm
        if selector == REFRESH_SELECTOR:
            return self.refresh
        return None

    async def query_selector_all(self, selector: str):
        assert selector == WHIRL_IMAGE_SELECTOR
        return [self.image]

    async def wait_for_timeout(self, timeout: int) -> None:
        return None


def _shapes_page(two_objects: bool = False, **kwargs) -> FakeShapesPage:
    image, labels = _shapes_arrays(two_objects)
    return FakeShapesPage(_data_url(image), labels, **kwargs)


async def test_solve_answers_a_3d_modal_and_clears_it(caplog) -> None:
    page = _shapes_page()

    with caplog.at_level(logging.INFO, logger="thoth_control_plane.acquisition.captcha"):
        assert await solve(page, rng=random.Random(1)) is True

    assert page.cleared is True
    assert page.image_clicks == 2 and page.good_clicks == 2
    assert page.mouse.downs == 3 and page.mouse.ups == 3  # two points, then Confirm
    assert len(page.mouse.moves) >= 24  # eased approaches, never teleports
    assert len({y for _, y in page.mouse.moves}) > 1  # the approach wobbles
    assert _outcome_lines(caplog) == [
        "tiktok captcha outcome subtype=3d solved=true attempts=1 reason=none"
    ]


async def test_a_3d_modal_without_the_click_structure_stays_unsupported() -> None:
    background, _ = _slide_arrays()
    image = FakeElement(SLIDE_BOXES["image"], _data_url(background))
    page = FakeCaptchaPage(
        {IMAGE_SELECTOR: image},
        [image],
        accept=[],
        container=FakeClickModal("Select 2 objects that are the same shape", CLICK_DOM, []),
    )

    assert await solve(page, rng=random.Random(1)) is False

    assert page.mouse.downs == 0  # an image that is not the modal's own is never clicked


async def test_a_refused_3d_challenge_clicks_nothing_and_saves_a_sample(
    tmp_path, monkeypatch, caplog
) -> None:
    monkeypatch.setenv("THOTH_CONTROL_PLANE_ARTIFACT_ROOT", str(tmp_path))
    monkeypatch.delenv("THOTH_CAPTCHA_CLICK_SOLVER", raising=False)
    page = _shapes_page(two_objects=True)  # two objects: the solver must refuse

    with caplog.at_level(logging.INFO, logger="thoth_control_plane.acquisition.captcha"):
        assert await solve(page, rng=random.Random(1)) is False

    assert page.image_clicks == 0  # never answered
    # A refusal ends as `challenge` for a leased account just like a miss, so it asks for
    # a fresh image; this one keeps the picture, which the second attempt does not re-solve.
    assert page.refresh_clicks == 1 and page.mouse.downs == 1
    assert _outcome_lines(caplog) == [
        "tiktok captcha outcome subtype=3d solved=false attempts=2 reason=unconfident"
    ]
    meta = json.loads((_sample_dirs(tmp_path)[0] / "sample.json").read_text(encoding="utf-8"))
    assert meta["subtype"] == "3d" and meta["reason"] == "unconfident"


async def test_a_refused_3d_challenge_asks_for_a_fresh_one_and_answers_it(caplog) -> None:
    hard, _ = _shapes_arrays(two_objects=True)
    easy, labels = _shapes_arrays()
    page = FakeShapesPage(_data_url(hard), [], after_refresh=(_data_url(easy), labels))

    with caplog.at_level(logging.INFO, logger="thoth_control_plane.acquisition.captcha"):
        assert await solve(page, rng=random.Random(1)) is True

    assert page.refresh_clicks == 1
    assert page.image_clicks == 2 and page.good_clicks == 2  # only the fresh image answered
    assert _outcome_lines(caplog) == [
        "tiktok captcha outcome subtype=3d solved=true attempts=2 reason=none"
    ]


async def test_the_same_picture_under_a_new_src_is_never_answered_twice(caplog) -> None:
    """A blob: URL changes with every render, so the picture, not its src, is the key."""
    image, labels = _shapes_arrays()
    src = _data_url(image)
    again = src.replace("data:image/png;base64,", "data:image/png;v=2;base64,", 1)
    page = FakeShapesPage(src, labels, stubborn=True, after_refresh=(again, labels))

    with caplog.at_level(logging.INFO, logger="thoth_control_plane.acquisition.captcha"):
        assert await solve(page, rng=random.Random(1)) is False

    assert page.image_clicks == 2  # the first answer only
    assert page.refresh_clicks == 1
    assert _outcome_lines(caplog) == [
        "tiktok captcha outcome subtype=3d solved=false attempts=2 reason=modal_stayed"
    ]


async def test_the_off_switch_keeps_the_classify_capture_refuse_behaviour(
    tmp_path, monkeypatch, caplog
) -> None:
    monkeypatch.setenv("THOTH_CONTROL_PLANE_ARTIFACT_ROOT", str(tmp_path))
    monkeypatch.setenv("THOTH_CAPTCHA_CLICK_SOLVER", "off")
    page = _shapes_page()

    with caplog.at_level(logging.INFO, logger="thoth_control_plane.acquisition.captcha"):
        assert await solve(page, rng=random.Random(1)) is False

    assert page.mouse.downs == 0
    assert _outcome_lines(caplog) == [
        "tiktok captcha outcome subtype=3d solved=false attempts=1 reason=unsupported"
    ]
    meta = json.loads((_sample_dirs(tmp_path)[0] / "sample.json").read_text(encoding="utf-8"))
    assert meta["reason"] == "unsupported"


@pytest.mark.parametrize(
    ("src", "prompt", "subtype", "source"),
    [
        (
            "https://p19-rc-captcha-va.ibyteimg.com/x/3d_2385_ab_1.jpg",
            "Select 2 objects that are the same shape",
            "3d",
            "url",
        ),
        (
            "blob:https://www.tiktok.com/87ded5ee",
            "Select 2 objects that are the same shape",
            "3d",
            "prompt",
        ),
        (
            "blob:https://www.tiktok.com/87ded5ee",
            "Which of these objects has a brim?",
            "icon",
            "prompt",
        ),
        (
            "blob:https://www.tiktok.com/87ded5ee",
            "Pilih dua benda yang bentuknya sama",
            "3d",
            "keywords",
        ),
        (
            "blob:https://www.tiktok.com/87ded5ee",
            "Rearrange the tiles until the picture is whole",
            "unknown",
            "structure",
        ),
    ],
)
async def test_click_subtypes_come_from_the_url_the_prompt_or_the_keywords(
    src, prompt, subtype, source, monkeypatch, caplog
) -> None:
    monkeypatch.setenv("THOTH_CAPTCHA_CLICK_SOLVER", "off")
    page = FakeShapesPage(src, [(0, 0, 10, 10)], prompt=prompt)

    with caplog.at_level(logging.DEBUG, logger="thoth_control_plane.acquisition.captcha"):
        assert await solve(page, rng=random.Random(1)) is False

    assert page.mouse.downs == 0
    assert _outcome_lines(caplog) == [
        f"tiktok captcha outcome subtype={subtype} solved=false attempts=1 reason=unsupported"
    ]
    assert f"tiktok captcha subtype={subtype} source={source}" in [
        record.getMessage() for record in caplog.records
    ]


async def test_a_local_vision_switch_without_a_key_refuses_without_a_call(
    tmp_path, monkeypatch, caplog
) -> None:
    monkeypatch.setenv("THOTH_CONTROL_PLANE_ARTIFACT_ROOT", str(tmp_path))
    monkeypatch.setenv("THOTH_CAPTCHA_CLICK_SOLVER", "local_vision")
    monkeypatch.delenv("THOTH_OPENROUTER_API_KEY", raising=False)
    page = _shapes_page(two_objects=True)

    with caplog.at_level(logging.INFO, logger="thoth_control_plane.acquisition.captcha"):
        assert await solve(page, rng=random.Random(1)) is False

    assert page.image_clicks == 0 and page.refresh_clicks == 1
    assert _outcome_lines(caplog) == [
        "tiktok captcha outcome subtype=3d solved=false attempts=2 reason=no_vision"
    ]
    meta = json.loads((_sample_dirs(tmp_path)[0] / "sample.json").read_text(encoding="utf-8"))
    assert meta["reason"] == "no_vision"


def _vision_run(first: int, second: int) -> Any:
    return SimpleNamespace(
        content=_VisionPick(first=first, second=second),
        metrics=SimpleNamespace(input_tokens=90, output_tokens=12),
    )


async def test_the_vision_fallback_answers_through_the_marked_candidates(
    monkeypatch, caplog
) -> None:
    monkeypatch.setenv("THOTH_CAPTCHA_CLICK_SOLVER", "local_vision")
    monkeypatch.setenv("THOTH_OPENROUTER_API_KEY", "test-key")
    asked: list[bytes] = []

    async def fake_agent(marked: bytes, key: str, model: str) -> Any:
        asked.append(marked)
        return _vision_run(1, 2)

    monkeypatch.setattr(captcha, "_run_vision_agent", fake_agent)
    page = _shapes_page(two_objects=True)  # the local solver refuses; the vision pick answers

    with caplog.at_level(logging.INFO, logger="thoth_control_plane.acquisition.captcha"):
        assert await solve(page, rng=random.Random(1)) is True

    assert len(asked) == 1 and asked[0][:4] == b"\x89PNG"  # one call, over the marked picture
    assert page.image_clicks == 2 and page.good_clicks == 2  # the clicked boxes are the picked pair
    assert _outcome_lines(caplog) == [
        "tiktok captcha outcome subtype=3d solved=true attempts=1 reason=none"
    ]


async def test_the_vision_call_is_metered_into_usage_events(monkeypatch) -> None:
    monkeypatch.setenv("THOTH_CAPTCHA_CLICK_SOLVER", "local_vision")
    monkeypatch.setenv("THOTH_OPENROUTER_API_KEY", "test-key")
    monkeypatch.delenv("THOTH_CAPTCHA_VISION_MODEL", raising=False)

    async def fake_agent(marked: bytes, key: str, model: str) -> Any:
        return _vision_run(1, 2)

    monkeypatch.setattr(captcha, "_run_vision_agent", fake_agent)
    sink = _MeteringSink()
    metering.install(sink)
    try:
        with metering.scoped(MeterScope("ws_captcha")):
            assert await solve(_shapes_page(two_objects=True), rng=random.Random(1)) is True
    finally:
        metering.install(None)

    assert [(event.kind, event.key, event.quantity, event.unit) for event in sink.events] == [
        ("provider_call", "qwen/qwen3-vl-30b-a3b-instruct", 1.0, "call"),
        ("provider_call", "qwen/qwen3-vl-30b-a3b-instruct", 90.0, "token_in"),
        ("provider_call", "qwen/qwen3-vl-30b-a3b-instruct", 12.0, "token_out"),
    ]


class _MeteringSink:
    def __init__(self) -> None:
        self.events: list[Any] = []

    def record(self, event: Any) -> None:
        self.events.append(event)


async def test_a_vision_reply_that_is_not_two_distinct_candidates_is_a_refusal(
    monkeypatch, caplog
) -> None:
    monkeypatch.setenv("THOTH_CAPTCHA_CLICK_SOLVER", "local_vision")
    monkeypatch.setenv("THOTH_OPENROUTER_API_KEY", "test-key")

    calls = 0

    async def same_twice(marked: bytes, key: str, model: str) -> Any:
        nonlocal calls
        calls += 1
        return _vision_run(1, 1)

    monkeypatch.setattr(captcha, "_run_vision_agent", same_twice)
    page = _shapes_page(two_objects=True)

    with caplog.at_level(logging.INFO, logger="thoth_control_plane.acquisition.captcha"):
        assert await solve(page, rng=random.Random(1)) is False

    assert page.image_clicks == 0
    assert calls == 1  # the unchanged picture is not paid for twice
    assert _outcome_lines(caplog) == [
        "tiktok captcha outcome subtype=3d solved=false attempts=2 reason=unconfident"
    ]


async def test_a_failing_vision_call_is_a_refusal_and_meters_nothing(monkeypatch, caplog) -> None:
    monkeypatch.setenv("THOTH_CAPTCHA_CLICK_SOLVER", "local_vision")
    monkeypatch.setenv("THOTH_OPENROUTER_API_KEY", "test-key")
    sink = _MeteringSink()
    metering.install(sink)
    try:

        async def crashing(marked: bytes, key: str, model: str) -> Any:
            raise RuntimeError("openrouter down")

        monkeypatch.setattr(captcha, "_run_vision_agent", crashing)
        page = _shapes_page(two_objects=True)

        with caplog.at_level(logging.INFO, logger="thoth_control_plane.acquisition.captcha"):
            assert await solve(page, rng=random.Random(1)) is False

    finally:
        metering.install(None)

    assert page.image_clicks == 0
    assert sink.events == []  # a failed call is not a usage event
    assert _outcome_lines(caplog) == [
        "tiktok captcha outcome subtype=3d solved=false attempts=2 reason=unconfident"
    ]


async def test_a_stubborn_3d_modal_presses_refresh_and_never_answers_twice(
    tmp_path, monkeypatch, caplog
) -> None:
    monkeypatch.setenv("THOTH_CONTROL_PLANE_ARTIFACT_ROOT", str(tmp_path))
    monkeypatch.delenv("THOTH_CAPTCHA_CLICK_SOLVER", raising=False)
    page = _shapes_page(stubborn=True)  # Confirm never clears; Refresh keeps the image

    with caplog.at_level(logging.INFO, logger="thoth_control_plane.acquisition.captcha"):
        assert await solve(page, rng=random.Random(1)) is False

    assert page.image_clicks == 2  # both attempts together: the second never re-answers
    assert page.refresh_clicks == 1  # the wrong answer was followed by Refresh
    assert page.mouse.downs == 4 and page.mouse.ups == 4  # two points, Confirm, Refresh
    assert _outcome_lines(caplog) == [
        "tiktok captcha outcome subtype=3d solved=false attempts=2 reason=modal_stayed"
    ]
    reasons = [
        json.loads((sample / "sample.json").read_text(encoding="utf-8"))["reason"]
        for sample in _sample_dirs(tmp_path)
    ]
    assert reasons == ["modal_stayed", "modal_stayed"]  # one per attempt that saw the modal


async def test_a_stubborn_3d_modal_without_a_refresh_button_still_never_reanswers(
    caplog,
) -> None:
    page = _shapes_page(stubborn=True, refresh=False)

    with caplog.at_level(logging.INFO, logger="thoth_control_plane.acquisition.captcha"):
        assert await solve(page, rng=random.Random(1)) is False

    assert page.image_clicks == 2 and page.mouse.downs == 3  # no Refresh to press
    assert _outcome_lines(caplog) == [
        "tiktok captcha outcome subtype=3d solved=false attempts=2 reason=modal_stayed"
    ]


async def test_the_pointer_is_released_when_a_click_move_fails() -> None:
    class Page:
        def __init__(self) -> None:
            self.mouse = FakeMouse()

        async def wait_for_timeout(self, timeout: int) -> None:
            if timeout >= 50:  # the short hold after the press; the approach waits are 4..18
                raise RuntimeError("detached")

    page = Page()

    with pytest.raises(RuntimeError):
        await captcha._human_click(page, page.mouse, 10.0, 10.0, 200.0, 180.0, random.Random(1))

    assert page.mouse.downs == 1 and page.mouse.ups == 1


class ViewportFakePage(FakeCaptchaPage):
    """A fake page that names its viewport, like Playwright does."""

    viewport_size: ClassVar[dict] = {"width": 800, "height": 820}


async def test_no_modal_picture_when_the_clip_union_covers_the_viewport(
    tmp_path, monkeypatch
) -> None:
    """A full-screen overlay's boxes can union to the page itself; the sample must skip the
    picture rather than keep the profile behind the modal."""
    monkeypatch.setenv("THOTH_CONTROL_PLANE_ARTIFACT_ROOT", str(tmp_path))
    page = ViewportFakePage(
        {},
        [],
        accept=[],
        container=FakeClickModal(
            "Select 2 objects that are the same shape",
            CLICK_DOM,
            [
                {"tag": "img", "box": {"x": 0.0, "y": 0.0, "width": 700.0, "height": 800.0}},
            ],
        ),
    )

    assert await solve(page, rng=random.Random(1)) is False

    dirs = _sample_dirs(tmp_path)
    meta = json.loads((dirs[0] / "sample.json").read_text(encoding="utf-8"))
    assert meta["visuals"]["modal"] is None  # 700x800 covers more than half of 800x820
    assert not (dirs[0] / "modal.png").exists()
    assert (dirs[0] / "dom.html").exists()  # the rest of the sample survives


async def test_a_modal_picture_is_kept_when_the_union_stays_small(tmp_path, monkeypatch) -> None:
    monkeypatch.setenv("THOTH_CONTROL_PLANE_ARTIFACT_ROOT", str(tmp_path))
    page = ViewportFakePage(
        {},
        [],
        accept=[],
        container=FakeClickModal(
            "Select 2 objects that are the same shape",
            CLICK_DOM,
            [{"tag": "img", "box": {"x": 100.0, "y": 80.0, "width": 340.0, "height": 220.0}}],
        ),
    )

    assert await solve(page, rng=random.Random(1)) is False

    meta = json.loads((_sample_dirs(tmp_path)[0] / "sample.json").read_text(encoding="utf-8"))
    assert meta["visuals"]["modal"]["file"] == "modal.png"
