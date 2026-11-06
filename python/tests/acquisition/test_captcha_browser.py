"""The captcha solver against real Chromium: local pages shaped like TikTok's modal.

The slide page reproduces the documented modal DOM (container, verify image, slide piece,
track, drag handle) with generated puzzle images; the whirl page is the modal DOM recorded on
2026-10-23 with its own WebP images restored. A pointer listener moves the piece — or turns
the disc — with the drag and removes the container only when it lands on the puzzle's answer,
the same contract `solve` relies on in the wild. The 3D page is the recorded shapes modal
(gbiz123, operator licence ruling 2026-11-06) with the real challenge image restored: two
clicks inside the hand-labelled "8" boxes enable Confirm, and Confirm clears the container
only then.
"""

import base64
import json
import struct
from pathlib import Path

import pytest

cv2 = pytest.importorskip("cv2", reason="the fixture images are generated with OpenCV")
numpy = pytest.importorskip("numpy", reason="the fixture images are generated with NumPy")

from tests.acquisition.browser_support import async_api, launch  # noqa: E402
from thoth_control_plane.acquisition.captcha import (  # noqa: E402
    CONTAINER_SELECTOR,
    PROMPT_JS,
    solve,
)

NOTCH_X = 200  # the gap's offset inside the 340px verify image
FIXTURES = Path(__file__).parent / "fixtures"
WHIRL_TURNS = 360.0 / 284.0  # the shim's disc degrees per slider pixel
WHIRL_ANSWER = 60.0  # the recorded pair's upright rotation, in degrees
#: The real 3D challenge (shapes_sample.jpg, 552x344) with its two "8"s labelled by hand,
#: in image pixels: the large green one and the small salmon one.
SHAPES_NATIVE = (552, 344)
SHAPES_MARKS = [(110, 152, 55, 87), (204, 230, 36, 54)]

_MODAL_JS = """
const piece = document.querySelector('.captcha_verify_img_slide');
const handle = document.querySelector('.secsdk-captcha-drag-icon');
let drag = null;
handle.addEventListener('pointerdown', e => {
  drag = e.clientX;
  handle.setPointerCapture(e.pointerId);
});
handle.addEventListener('pointermove', e => {
  if (drag === null) return;
  piece.style.left = (104 + e.clientX - drag) + 'px';
});
handle.addEventListener('pointerup', e => {
  const left = 104 + e.clientX - drag;
  drag = null;
  window.__landed = left;
  if (Math.abs(left - __GAP_LEFT__) <= 4 && !window.__stubborn) {
    document.querySelector('.captcha_verify_container').remove();
  }
});
""".replace("__GAP_LEFT__", str(100 + NOTCH_X))


def _slide_arrays():
    rng = numpy.random.default_rng(7)
    background = rng.integers(0, 255, (190, 340, 3), dtype=numpy.uint8)
    patch = background[60 : 60 + 60, NOTCH_X : NOTCH_X + 48].copy()
    cv2.rectangle(background, (NOTCH_X, 60), (NOTCH_X + 48, 60 + 60), (0, 0, 0), 2)
    piece = numpy.dstack([patch, numpy.full((60, 48), 255, numpy.uint8)])
    return background, piece


def _data_url(image) -> str:
    ok, encoded = cv2.imencode(".png", image)
    assert ok
    return "data:image/png;base64," + base64.b64encode(encoded.tobytes()).decode()


def _modal_html() -> str:
    background, piece = _slide_arrays()
    return f"""<!doctype html><html><body style="margin:0">
<div class="captcha_verify_container" style="position:absolute;inset:0">
  <img id="captcha-verify-image" src="{_data_url(background)}"
       style="position:absolute;left:100px;top:50px;width:340px;height:190px">
  <img class="captcha_verify_img_slide" src="{_data_url(piece)}"
       style="position:absolute;left:104px;top:110px;width:48px;height:60px">
  <div class="captcha_verify_slide--slidebar"
       style="position:absolute;left:100px;top:300px;width:340px;height:8px;background:#555"></div>
  <div class="secsdk-captcha-drag-icon"
       style="position:absolute;left:100px;top:294px;width:40px;height:24px;background:#4af"></div>
</div>
<script>{_MODAL_JS}</script></body></html>"""


async def test_solve_clears_a_slide_modal_in_real_chromium() -> None:
    async with async_api.async_playwright() as playwright:
        browser = await launch(playwright)
        try:
            page = await browser.new_page(viewport={"width": 600, "height": 420})
            await page.set_content(_modal_html())
            await page.wait_for_timeout(100)

            assert await solve(page) is True

            landed = await page.evaluate("() => window.__landed")
            assert abs(landed - (100 + NOTCH_X)) <= 4
        finally:
            await browser.close()


async def test_solve_reports_failure_when_the_modal_never_clears() -> None:
    async with async_api.async_playwright() as playwright:
        browser = await launch(playwright)
        try:
            page = await browser.new_page(viewport={"width": 600, "height": 420})
            await page.set_content(_modal_html())
            await page.evaluate("() => (window.__stubborn = true)")
            await page.wait_for_timeout(100)

            assert await solve(page) is False
        finally:
            await browser.close()


# The whirl shim turns the inner image with the drag and clears the recorded modal when the
# disc's rotation relative to the ring reaches the recorded answer (modulo a full turn).
_WHIRL_SHIM_JS = r"""
const root = document.querySelector('.captcha-verify-container');
const imgs = [...root.querySelectorAll('img')];
const outer = imgs.reduce(
  (a, b) => (a.getBoundingClientRect().width >= b.getBoundingClientRect().width ? a : b));
const inner = imgs.find(e => e !== outer);
const handle = document.querySelector('.secsdk-captcha-drag-icon');
const wrap = handle.closest('div[draggable=true]');
const rotation = el => (el.style.transform.match(/rotate\(([-\d.]+)deg\)/g) || [])
  .reduce((sum, m) => sum + parseFloat(m.slice(7)), 0);
let drag = null;
document.addEventListener('dragstart', e => e.preventDefault());  // the page must own the drag
handle.addEventListener('pointerdown', e => {
  drag = e.clientX; handle.setPointerCapture(e.pointerId);
});
handle.addEventListener('pointermove', e => {
  if (drag === null) return;
  const dx = e.clientX - drag;
  wrap.style.transform = 'translateX(' + dx + 'px)';
  inner.style.transform = 'rotate(' + (__K__ * dx) + 'deg)';
});
handle.addEventListener('pointerup', () => {
  const rel = rotation(inner) - rotation(outer);
  drag = null;
  window.__rel = rel;
  const drift = Math.abs(rel - __THETA__) % 360;
  if (!window.__stubborn && Math.min(drift, 360 - drift) <= 4) root.remove();
});
"""


def _whirl_modal_html(degrees_per_px: float) -> str:
    """The recorded modal DOM with its WebP images restored and the drag shim wired in."""
    modal = (FIXTURES / "whirl_modal.html").read_text(encoding="utf-8")
    for name in ("whirl_outer.webp", "whirl_inner.webp"):  # DOM order: the ring comes first
        url = "data:image/webp;base64," + base64.b64encode((FIXTURES / name).read_bytes()).decode()
        modal = modal.replace('src="data:..."', f'src="{url}"', 1)
    shim = _WHIRL_SHIM_JS.replace("__K__", repr(degrees_per_px))
    shim = shim.replace("__THETA__", repr(WHIRL_ANSWER))
    body = f"{modal}<script>{shim}</script>"
    return f'<!doctype html><html><body style="margin:0">{body}</body></html>'


async def _run_whirl_modal(html: str, evaluate: str = "() => window.__rel") -> object:
    async with async_api.async_playwright() as playwright:
        browser = await launch(playwright)
        try:
            page = await browser.new_page(viewport={"width": 800, "height": 820})
            await page.set_content(html)
            await page.wait_for_timeout(100)
            solved = await solve(page)
            return solved, (await page.evaluate(evaluate) if solved else None)
        finally:
            await browser.close()


@pytest.mark.parametrize("degrees_per_px", [-WHIRL_TURNS, WHIRL_TURNS])
async def test_solve_clears_the_recorded_whirl_modal_in_real_chromium(degrees_per_px) -> None:
    solved, rel = await _run_whirl_modal(_whirl_modal_html(degrees_per_px))

    assert solved is True
    drift = abs(rel - WHIRL_ANSWER) % 360.0
    assert min(drift, 360.0 - drift) <= 4


async def test_solve_reports_failure_when_the_whirl_modal_never_clears() -> None:
    solved, _ = await _run_whirl_modal(
        _whirl_modal_html(-WHIRL_TURNS).replace("<script>", "<script>window.__stubborn = true;")
    )

    assert solved is False


async def test_prompt_reading_finds_the_prompt_on_the_recorded_whirl_modal() -> None:
    """The 2026 TUXModal has no `.captcha_verify_title`; this proves the span fallback still
    reads its prompt, so a click modal's `subtype=unknown` is a wording miss, not a reader
    miss (what the samples must settle)."""
    async with async_api.async_playwright() as playwright:
        browser = await launch(playwright)
        try:
            page = await browser.new_page(viewport={"width": 800, "height": 820})
            await page.set_content(_whirl_modal_html(WHIRL_TURNS))
            container = await page.query_selector(CONTAINER_SELECTOR)
            assert container is not None

            prompts = await container.evaluate(PROMPT_JS)

            assert prompts == ["Drag the slider to fit the puzzle"]
        finally:
            await browser.close()


async def test_an_unanswerable_modal_saves_a_sample_in_real_chromium(tmp_path, monkeypatch) -> None:
    """The recorded whirl modal with its slider stripped: a click-shaped page. The sample
    carries the prompt the production reader saw, the rendered boxes, the sanitized DOM and
    both images as served."""
    monkeypatch.setenv("THOTH_CONTROL_PLANE_ARTIFACT_ROOT", str(tmp_path))
    async with async_api.async_playwright() as playwright:
        browser = await launch(playwright)
        try:
            page = await browser.new_page(viewport={"width": 800, "height": 820})
            await page.set_content(_whirl_modal_html(WHIRL_TURNS))
            await page.evaluate(
                "() => document.querySelector('[draggable=true]').closest('div.cap-mt-6').remove()"
            )
            await page.wait_for_timeout(100)

            assert await solve(page) is False

            samples = sorted((tmp_path / "captcha-samples").iterdir())
            assert len(samples) == 1
            meta = json.loads((samples[0] / "sample.json").read_text(encoding="utf-8"))
            assert meta["subtype"] == "unknown"  # the whirl prompt classifies as nothing
            assert meta["reason"] == "unsupported"
            assert meta["prompt_candidates"] == ["Drag the slider to fit the puzzle"]
            tags = [box["tag"] for box in meta["boxes"]]
            assert tags.count("img") == 2 and "button" in tags
            dom = (samples[0] / "dom.html").read_text(encoding="utf-8")
            assert "Drag the slider" in dom
            assert "data:image/webp" not in dom  # the served bytes are blanked out of the DOM
            images = sorted(samples[0].glob("image-*"))
            assert [image.suffix for image in images] == [".webp", ".webp"]
            assert meta["images"] == [
                {"file": "image-0.webp", "src_hint": ""},
                {"file": "image-1.webp", "src_hint": ""},
            ]
        finally:
            await browser.close()


_CANVAS_MODAL_HTML = """<!doctype html><html><body style="margin:0">
<div style="position:fixed;top:12px;left:12px;font-size:20px">@kabinet_rakyat</div>
<div class="TUXModal captcha-verify-container"
     style="position:fixed;inset:0;background:rgba(0,0,0,.45);z-index:8000">
  <div style="position:absolute;left:200px;top:100px;width:380px">
    <span class="cap-break-words cap-text-left"
          style="display:block;height:20px">Select 2 objects that are the same shape</span>
    <canvas id="captcha-canvas" width="340" height="190"
            style="width:340px;height:190px;display:block;margin-top:10px"></canvas>
    <button class="TUXButton TUXButton--primary"
            style="width:340px;height:40px;margin-top:10px">Confirm</button>
  </div>
</div>
<script>
const c = document.getElementById('captcha-canvas').getContext('2d');
c.fillStyle = '#ddd'; c.fillRect(0, 0, 340, 190);
for (let i = 0; i < 6; i++) {
  c.fillStyle = ['#c66', '#6c6', '#66c', '#cc6', '#c6c', '#6cc'][i];
  c.beginPath();
  c.arc(30 + (i % 3) * 110, 30 + Math.floor(i / 3) * 120, 22, 0, 7);
  c.fill();
}
</script>
</body></html>"""


def _png_size(data: bytes) -> tuple[int, int]:
    """The PNG's own IHDR width and height."""
    assert data[:8] == b"\x89PNG\r\n\x1a\n"
    return struct.unpack(">II", data[16:24])


async def test_a_canvas_challenge_on_a_full_screen_overlay_saves_a_clipped_picture(
    tmp_path, monkeypatch
) -> None:
    """The 2026 container can be a full-screen overlay over the creator's profile; the
    sample's picture must be clipped to the modal's own content, never the page behind."""
    monkeypatch.setenv("THOTH_CONTROL_PLANE_ARTIFACT_ROOT", str(tmp_path))
    async with async_api.async_playwright() as playwright:
        browser = await launch(playwright)
        try:
            page = await browser.new_page(viewport={"width": 800, "height": 820})
            await page.set_content(_CANVAS_MODAL_HTML)
            await page.wait_for_timeout(100)

            assert await solve(page) is False

            samples = sorted((tmp_path / "captcha-samples").iterdir())
            assert len(samples) == 1
            meta = json.loads((samples[0] / "sample.json").read_text(encoding="utf-8"))
            assert meta["subtype"] == "3d"  # the documented shapes prompt classifies
            assert meta["visuals"]["canvases"] == [{"file": "canvas-0.png"}]
            width, height = _png_size((samples[0] / "canvas-0.png").read_bytes())
            assert (width, height) == (340, 190)  # the drawn challenge, not a blank frame
            modal = meta["visuals"]["modal"]
            assert modal["file"] == "modal.png"
            clip = modal["clip"]
            assert clip["x"] >= 200 and clip["y"] >= 100  # starts at the modal's content
            assert clip["x"] + clip["width"] <= 580  # the modal's column, not the page
            png_width, png_height = _png_size((samples[0] / "modal.png").read_bytes())
            assert png_width < 800 and png_height < 820  # smaller than the viewport
        finally:
            await browser.close()


# The recorded 3D shapes modal (see fixtures/shapes_modal.html for provenance) with the real
# challenge image restored. The page owns the modal's behaviour: two clicks inside the
# hand-labelled "8" boxes enable the Confirm button, and Confirm removes the container only
# when both clicks were good. The refresh button is found by its TikTok glyph (the recorded
# modal carries no id), the same fallback the solver uses.
_SHAPES_SHIM_JS = """
const root = document.querySelector('.captcha-verify-container');
const img = root.querySelector('.cap-relative img');
const confirm = root.querySelector('.cap-relative button.cap-w-full');
const refresh = [...root.querySelectorAll('button')].find(
  b => [...b.querySelectorAll('path')].some(
    p => (p.getAttribute('d') || '').startsWith('M56.62 21')));
const MARKS = __MARKS__;
window.__clicks = 0; window.__good = 0; window.__refreshes = 0;
img.addEventListener('click', e => {
  window.__clicks++;
  const r = img.getBoundingClientRect();
  const ix = (e.clientX - r.left) / r.width * __W__;
  const iy = (e.clientY - r.top) / r.height * __H__;
  if (MARKS.some(([x, y, w, h]) => ix >= x && ix <= x + w && iy >= y && iy <= y + h)) {
    window.__good++;
  }
  if (window.__clicks >= 2) {
    confirm.classList.remove('TUXButton--disabled');
    confirm.setAttribute('aria-disabled', 'false');
  }
});
confirm.addEventListener('click', () => {
  if (!window.__stubborn && window.__good === 2 && window.__clicks === 2) root.remove();
});
refresh.addEventListener('click', () => { window.__refreshes++; });
"""


def _shapes_modal_html(image: bytes, native: tuple[int, int], marks: list) -> str:
    modal = (FIXTURES / "shapes_modal.html").read_text(encoding="utf-8")
    url = "data:image/jpeg;base64," + base64.b64encode(image).decode()
    modal = modal.replace('src="data:..."', f'src="{url}"', 1)
    shim = (
        _SHAPES_SHIM_JS.replace("__MARKS__", json.dumps([list(mark) for mark in marks]))
        .replace("__W__", str(native[0]))
        .replace("__H__", str(native[1]))
    )
    # Only the two Tailwind classes the solver's mapping depends on are given meaning; the
    # recorded modal renders its image at the column's width, as on TikTok.
    style = "<style>.cap-w-full{width:100%}.cap-h-auto{height:auto}</style>"
    return (
        f'<!doctype html><html><head>{style}</head><body style="margin:0">'
        f"{modal}<script>{shim}</script></body></html>"
    )


def _two_object_jpeg() -> bytes:
    """A 552x344 white card with only a star and a disc: the local solver must refuse it."""
    card = numpy.full((SHAPES_NATIVE[1], SHAPES_NATIVE[0], 3), 250, numpy.uint8)
    angles = numpy.linspace(0, 2 * numpy.pi, 10, endpoint=False) + numpy.pi / 2
    radii = numpy.where(numpy.arange(10) % 2 == 0, 42, 42 * 0.45)
    star = numpy.int32(
        [
            [90 + r * numpy.cos(a), 100 + r * numpy.sin(a)]
            for a, r in zip(angles, radii, strict=True)
        ]
    )
    cv2.fillPoly(card, [star], (0, 0, 255))
    cv2.circle(card, (400, 172), 46, (255, 0, 0), -1)
    ok, encoded = cv2.imencode(".jpg", card)
    assert ok
    return encoded.tobytes()


async def _run_shapes_modal(html: str, evaluate: str | None = None):
    async with async_api.async_playwright() as playwright:
        browser = await launch(playwright)
        try:
            page = await browser.new_page(viewport={"width": 800, "height": 820})
            await page.set_content(html)
            if evaluate:
                await page.evaluate(evaluate)
            await page.wait_for_timeout(100)
            solved = await solve(page)
            state = await page.evaluate(
                "() => ({clicks: window.__clicks, good: window.__good,"
                " refreshes: window.__refreshes,"
                " open: document.querySelector('.captcha-verify-container') !== null})"
            )
            return solved, state
        finally:
            await browser.close()


async def test_solve_clears_the_recorded_3d_modal_in_real_chromium() -> None:
    image = (FIXTURES / "shapes_sample.jpg").read_bytes()

    solved, state = await _run_shapes_modal(_shapes_modal_html(image, SHAPES_NATIVE, SHAPES_MARKS))

    assert solved is True
    assert state == {"clicks": 2, "good": 2, "refreshes": 0, "open": False}


async def test_solve_clears_a_3d_modal_served_from_a_blob_url() -> None:
    """The 2026 modals can serve the challenge from a blob: URL, so no URL marker exists:
    the prompt classifies, and the bytes come from the in-page fetch."""
    image = (FIXTURES / "shapes_sample.jpg").read_bytes()
    to_blob = """async bytes => {
      const blob = new Blob([new Uint8Array(bytes)], {type: 'image/jpeg'});
      document.querySelector('.captcha-verify-container .cap-relative img').src =
        URL.createObjectURL(blob);
    }"""

    async with async_api.async_playwright() as playwright:
        browser = await launch(playwright)
        try:
            page = await browser.new_page(viewport={"width": 800, "height": 820})
            await page.set_content(_shapes_modal_html(image, SHAPES_NATIVE, SHAPES_MARKS))
            await page.evaluate(to_blob, list(image))
            await page.wait_for_timeout(100)

            assert await solve(page) is True

            clicks = await page.evaluate("() => window.__clicks")
            good = await page.evaluate("() => window.__good")
            assert (clicks, good) == (2, 2)
        finally:
            await browser.close()


async def test_solve_refuses_a_3d_modal_it_cannot_answer_without_clicking() -> None:
    solved, state = await _run_shapes_modal(
        _shapes_modal_html(_two_object_jpeg(), SHAPES_NATIVE, SHAPES_MARKS)
    )

    assert solved is False
    assert state == {"clicks": 0, "good": 0, "refreshes": 0, "open": True}


async def test_a_stubborn_3d_modal_gets_refresh_and_is_never_answered_twice() -> None:
    image = (FIXTURES / "shapes_sample.jpg").read_bytes()
    html = _shapes_modal_html(image, SHAPES_NATIVE, SHAPES_MARKS).replace(
        "<script>", "<script>window.__stubborn = true;"
    )

    solved, state = await _run_shapes_modal(html)

    assert solved is False
    assert state["open"] is True
    assert state["clicks"] == 2  # the second attempt refuses the unchanged image
    assert state["good"] == 2
    assert state["refreshes"] == 1  # the wrong answer asked for a new challenge
