"""The captcha solver against real Chromium: local pages shaped like TikTok's modal.

The slide page reproduces the documented modal DOM (container, verify image, slide piece,
track, drag handle) with generated puzzle images; the whirl page is the modal DOM recorded on
2026-10-23 with its own WebP images restored. A pointer listener moves the piece — or turns
the disc — with the drag and removes the container only when it lands on the puzzle's answer,
the same contract `solve` relies on in the wild.
"""

import base64
from pathlib import Path

import pytest

cv2 = pytest.importorskip("cv2", reason="the fixture images are generated with OpenCV")
numpy = pytest.importorskip("numpy", reason="the fixture images are generated with NumPy")

from tests.acquisition.browser_support import async_api, launch  # noqa: E402
from thoth_control_plane.acquisition.captcha import solve  # noqa: E402

NOTCH_X = 200  # the gap's offset inside the 340px verify image
FIXTURES = Path(__file__).parent / "fixtures"
WHIRL_TURNS = 360.0 / 284.0  # the shim's disc degrees per slider pixel
WHIRL_ANSWER = 60.0  # the recorded pair's upright rotation, in degrees

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
