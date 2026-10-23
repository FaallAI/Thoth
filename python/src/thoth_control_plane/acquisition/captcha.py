"""Solve the TikTok captcha modal that rises over a listing page.

TikTok raises this modal when its risk engine refuses the session's signed list request; the
grid under it never loads until the challenge is answered. The two drag subtypes are solved
from the modal's own images: ``slide`` (fit the puzzle piece into the gap) and ``whirl``
(rotate the inner disc upright) — OpenCV for the where, one humanized pointer drag for the
how. The 2026 whirl modal (a TUXModal) labels none of its moving parts, so the images are
picked by rendered size, the track is found through the handle's draggable wrapper, and the
slider's degrees-per-pixel is measured live in mid-drag. Click subtypes (icon matching, 3D
shapes) are classified but not solved yet; an unhandled subtype is never clicked at random.

Solving is best effort and never raises: without OpenCV, on an unsupported subtype, or after
the attempt budget, :func:`solve` returns False and the caller keeps its captcha behaviour.
Every call ends in exactly one INFO outcome line — the place production counts the solver's
success rate from. Selectors follow the ones every maintained solver documents (EulerStream,
ScrapeCreators, arc298's solver); both spellings of the container class appear across TikTok
builds.
"""

from __future__ import annotations

import base64
import logging
import random
import re
from typing import Any

logger = logging.getLogger(__name__)

CONTAINER_SELECTOR = ".captcha_verify_container, .captcha-verify-container"
IMAGE_SELECTOR = "#captcha-verify-image"
WHIRL_IMAGE_SELECTOR = f"{CONTAINER_SELECTOR} img"
PIECE_SELECTOR = ".captcha_verify_img_slide"
TRACK_SELECTOR = ".captcha_verify_slide--slidebar"
HANDLE_SELECTOR = ".secsdk-captcha-drag-icon"
#: The 2026 modal hides the track behind Tailwind classes; from the handle it is two hops up
#: (the draggable wrapper, then the wrapper's parent). Returns 0 when that shape is absent.
TRACK_WIDTH_JS = (
    "el => { const wrap = el.closest('[draggable=true]');"
    " const track = wrap ? wrap.parentElement : null;"
    " return track ? track.getBoundingClientRect().width : 0; }"
)
ROTATION_JS = "el => el.style.transform || ''"
PROMPT_JS = (
    "root => { const title = document.querySelector('.captcha_verify_title');"
    " if (title) return [title.textContent];"
    " return [...root.querySelectorAll('span')]"
    "  .filter(s => s.textContent.trim().length > 8 && !s.closest('button'))"
    "  .map(s => s.textContent.trim()); }"
)
#: Click-subtype prompt keywords, from what the maintained sellers document (Capzy,
#: SadCaptcha, 2026-10): 3D asks for the two objects of the same shape, icon for the icons
#: that match the instruction — English first, the modal follows the session locale. No
#: click modal rose within the 2026-10-23 recording budget (three anonymous sessions, no
#: challenge at all), so the table is unvalidated; the outcome line is what will show what
#: production really meets.
CLICK_PROMPTS: dict[str, tuple[str, ...]] = {
    "3d": ("same shape", "bentuk yang sama", "3d"),
    "icon": ("icon", "ikon", "sesuai", "match"),
}
ATTEMPTS = 2
MIN_MATCH = 0.25
#: After a drag the modal can take seconds to close on a right answer (live, signed in,
#: 2026-10-23: it outlasted a fixed 1.5 s check, and the solve was logged as a failure), so
#: the check polls until the modal is gone or the budget runs out.
VERIFY_TIMEOUT_MS = 6_000
VERIFY_POLL_MS = 250
#: The 2026 whirl modal maps slider travel to disc rotation at an unstated rate and direction,
#: so every drag measures both: this many pixels of travel with the button held, then read the
#: two images' inline transforms and compute the rest of the drag from the answer.
CALIBRATION_PX = 30.0
_ROTATIONS = re.compile(r"rotate\((-?\d+(?:\.\d+)?)deg\)")


async def solve(page: Any, attempts: int = ATTEMPTS, rng: random.Random | None = None) -> bool:
    """Drag the modal's slider until TikTok removes it; False when the modal stays.

    Never raises: any surprise (missing OpenCV, unsupported subtype, detached element) is
    logged and treated as an unsolved attempt. Every call ends in exactly one INFO outcome
    line, so production logs count the solver's success rate without any other signal.
    """
    try:
        import cv2  # noqa: F401
        import numpy  # noqa: F401
    except ImportError:
        logger.warning("tiktok captcha solver unavailable: opencv is not installed")
        _outcome("unknown", False, 0, "error")
        return False
    rng = rng or random.Random()
    subtype, reason, attempt = "unknown", "error", 0
    for attempt in range(1, attempts + 1):
        try:
            subtype, reason, solved = await _attempt(page, rng)
        except Exception as error:
            logger.debug("tiktok captcha attempt failed error=%s", type(error).__name__)
            reason = "error"
        else:
            if solved:
                _outcome(subtype, True, attempt, "none")
                return True
            if reason == "unsupported":  # a subtype with no solver never retries
                break
        if attempt < attempts:
            await page.wait_for_timeout(400)
    _outcome(subtype, False, attempt, reason)
    return False


def _outcome(subtype: str, solved: bool, attempts: int, reason: str) -> None:
    """The one INFO line every solve call ends in: what rose, whether it fell, and why not."""
    logger.info(
        "tiktok captcha outcome subtype=%s solved=%s attempts=%d reason=%s",
        subtype,
        str(solved).lower(),
        attempts,
        reason,
    )


async def _attempt(page: Any, rng: random.Random) -> tuple[str, str, bool]:
    """One try: the subtype it saw, why it fell short ("none" when it did not), and success."""
    if await page.query_selector(CONTAINER_SELECTOR) is None:
        return "unknown", "no_images", False
    handle = await page.query_selector(HANDLE_SELECTOR)
    subtype = await _classify(page)
    if handle is None:
        # No drag handle: a click subtype, which nothing here answers.
        return subtype, "unsupported", False
    if subtype not in ("slide", "whirl"):
        # A drag handle whose images have not rendered yet: worth the retry.
        return subtype, "no_images", False
    if subtype == "slide":
        piece = await page.query_selector(PIECE_SELECTOR)
        if piece is None:
            return "slide", "no_images", False
        drag = await _slide_drag(page, piece)
        if drag is None or abs(drag) < 1:
            logger.debug("tiktok captcha slide subtype gave no drag distance")
            return "slide", "no_distance", False
        await _drag(page, handle, drag, rng)
    else:
        failure = await _whirl_drag(page, handle, rng)
        if failure is not None:
            return "whirl", failure, False
    gone = await _closed(page)
    return subtype, ("none" if gone else "modal_stayed"), gone


async def _closed(page: Any) -> bool:
    """Whether the modal goes away within VERIFY_TIMEOUT_MS of the drag."""
    for _ in range(VERIFY_TIMEOUT_MS // VERIFY_POLL_MS):
        await page.wait_for_timeout(VERIFY_POLL_MS)
        if await page.query_selector(CONTAINER_SELECTOR) is None:
            return True
    return False


async def _classify(page: Any) -> str:
    """The modal's subtype from its own DOM: what it offers to drag, or what it asks to click."""
    if await page.query_selector(HANDLE_SELECTOR) is None:
        return await _click_subtype(page)
    if await page.query_selector(PIECE_SELECTOR) is not None:
        return "slide"
    if await _whirl_images(page) is not None:
        return "whirl"
    return "unknown"


async def _click_subtype(page: Any) -> str:
    """The click subtype (icon, 3D) from the modal's prompt, or "unknown".

    A click modal carries no drag handle, so the prompt is the only signal left. The keyword
    table is seller documentation, not recorded evidence — see :data:`CLICK_PROMPTS`. Either
    way an unhandled subtype is never clicked at random.
    """
    container = await page.query_selector(CONTAINER_SELECTOR)
    if container is None:
        return "unknown"
    try:
        prompts = await container.evaluate(PROMPT_JS)
    except Exception:
        return "unknown"
    text = " ".join(prompts if isinstance(prompts, list) else []).lower()
    for subtype, words in CLICK_PROMPTS.items():
        if any(word in text for word in words):
            return subtype
    return "unknown"


async def _src_bytes(page: Any, element: Any) -> bytes:
    """The element's own image bytes, straight from its src: data URLs decode, links fetch.

    An element screenshot would bake whatever overlaps the image into the pixels — on the
    modal the piece sits over the background, and the match would find the piece's starting
    position instead of the gap. The in-page fetch rides the session's own cookies.
    """
    src = await element.get_attribute("src")
    if not isinstance(src, str) or not src:
        return b""
    if src.startswith("data:"):
        return base64.b64decode(src.split(",", 1)[1])
    data = await page.evaluate(
        "async url => { const r = await fetch(url, {credentials: 'include'});"
        " return Array.from(new Uint8Array(await r.arrayBuffer())); }",
        src,
    )
    return bytes(data)


async def _slide_drag(page: Any, piece: Any) -> float | None:
    """The pointer distance that puts the piece into the gap, in page CSS pixels."""
    image = await page.query_selector(IMAGE_SELECTOR)
    if image is None:
        return None
    image_box, piece_box = await image.bounding_box(), await piece.bounding_box()
    if not image_box or not piece_box:
        return None
    background = _decode(await _src_bytes(page, image))
    gap = gap_offset(background, _decode(await _src_bytes(page, piece)))
    if background is None or gap is None or not image_box["width"]:
        return None
    gap_css = gap * image_box["width"] / background.shape[1]
    return image_box["x"] + gap_css - piece_box["x"]


async def _whirl_images(page: Any) -> list[tuple[float, Any]] | None:
    """The whirl modal's two images with their rendered widths, largest first: ring, then disc."""
    images = []
    for element in await page.query_selector_all(WHIRL_IMAGE_SELECTOR):
        box = await element.bounding_box()
        if box and box["width"] > 0:
            images.append((box["width"], element))
    images.sort(key=lambda item: item[0], reverse=True)
    if len(images) < 2 or images[1][0] >= images[0][0]:
        return None
    return images[:2]


async def _track_width(page: Any, handle: Any) -> float:
    """The slider track's width, from the handle: the 2026 modal's draggable wrapper's parent,
    or the older builds' slidebar element."""
    width = await handle.evaluate(TRACK_WIDTH_JS)
    if isinstance(width, (int, float)) and width > 0:
        return float(width)
    track = await page.query_selector(TRACK_SELECTOR)
    box = await track.bounding_box() if track is not None else None
    return float(box["width"]) if box else 0.0


async def _rotation(element: Any) -> float:
    style = await element.evaluate(ROTATION_JS)
    return _rotation_deg(style if isinstance(style, str) else "")


def _rotation_deg(style: str) -> float:
    """The transform style's total rotation: every `rotate(...deg)` term summed, 0 when none."""
    return sum(float(match) for match in _ROTATIONS.findall(style or ""))


async def _whirl_drag(page: Any, handle: Any, rng: random.Random) -> str | None:
    """Drag the slider until the disc's measured rotation reaches the computed angle.

    How many degrees a pixel of travel turns the disc is a convention the page never states
    and may flip between challenges, so the drag measures it live instead of trusting a
    constant: a short move with the button held, both images' inline transforms read mid-drag,
    and the remaining travel computed from that reading. One continuous drag does the whole
    job, whichever way the slider turns the disc. Returns None once the drag is done, or the
    outcome line's reason it stopped short — the button always comes back up.
    """
    images = await _whirl_images(page)
    handle_box = await handle.bounding_box()
    if images is None or handle_box is None:
        return "no_images"
    (outer_w, outer), (inner_w, inner) = images
    span = max(1.0, (await _track_width(page, handle)) - handle_box["width"])
    outer_image = _decode(await _src_bytes(page, outer))
    inner_image = _decode(await _src_bytes(page, inner))
    # The hole the disc fills, in the ring's own pixels: the two native resolutions need not
    # match, so the hole comes from the rendered sizes (inner ÷ outer on screen) applied to
    # the ring's native width.
    hole = inner_w / outer_w * outer_image.shape[1] / 2.0 if outer_image is not None else None
    angle = whirl_angle(inner_image, outer_image, hole)
    if angle is None:
        return "no_angle"
    mouse = page.mouse
    x = handle_box["x"] + handle_box["width"] / 2
    y = handle_box["y"] + handle_box["height"] / 2
    inner0, outer0 = await _rotation(inner), await _rotation(outer)
    await mouse.move(x, y)
    await mouse.down()
    try:
        reached = await _glide(
            page, mouse, x, x + CALIBRATION_PX, y, rng, steps=max(8, min(20, int(CALIBRATION_PX)))
        )
        await page.wait_for_timeout(120)
        inner1, outer1 = await _rotation(inner), await _rotation(outer)
        # `reached` is where the pointer really stopped (the glide overshoots a few pixels), so
        # the ratio below uses the travel that actually happened, not the one asked for.
        per_px = ((inner1 - inner0) - (outer1 - outer0)) / (reached - x)
        logger.info(
            "tiktok whirl angle=%.1f over %.1fpx: inner=%+.2fdeg outer=%+.2fdeg -> %+.3fdeg/px",
            angle,
            reached - x,
            inner1 - inner0,
            outer1 - outer0,
            per_px,
        )
        distance = whirl_distance(angle, per_px, span)
        if distance is None or distance < 1:
            logger.debug("tiktok whirl gave no drag distance per_px=%.3f", per_px)
            return "no_distance"
        logger.info("tiktok whirl dragging %.1fpx of %.0fpx span", distance, span)
        travel = int(abs(x + distance - reached))
        overshoot = await _glide(
            page, mouse, reached, x + distance, y, rng, steps=max(12, min(40, travel))
        )
        await page.wait_for_timeout(rng.randint(120, 260))
        await _settle(page, mouse, overshoot, x + distance, y, rng)
        await page.wait_for_timeout(rng.randint(80, 180))
        return None
    finally:
        await mouse.up()


def whirl_distance(angle: float, degrees_per_px: float, span: float) -> float | None:
    """The forward slider travel that turns the disc by `angle`, given the measured deg/px.

    The slider cannot travel backwards, so when forward travel rotates the disc the wrong way
    the equivalent angle one full turn away is used instead. Returns None when the drag
    rotates nothing or no candidate rotation fits within the span.
    """
    if abs(degrees_per_px) < 1e-6:
        return None
    candidates = [(angle + 360.0 * turn) / degrees_per_px for turn in (-1, 0, 1)]
    fitting = [distance for distance in candidates if 0.0 <= distance <= span]
    return min(fitting, key=abs) if fitting else None


async def _drag(page: Any, handle: Any, distance: float, rng: random.Random) -> None:
    """One humanized drag: fast then slow, a small overshoot, then a settle on the target.

    A steady constant-speed slide is the trajectory TikTok's detection rejects, so the pointer
    eases out, wobbles slightly, passes the target by a few pixels and backs onto it. Whatever
    happens mid-drag, the button comes back up.
    """
    box = await handle.bounding_box()
    if not box:
        return
    mouse = page.mouse
    x = box["x"] + box["width"] / 2
    y = box["y"] + box["height"] / 2
    await mouse.move(x, y)
    await mouse.down()
    try:
        overshoot = await _glide(
            page, mouse, x, x + distance, y, rng, steps=max(24, min(60, int(abs(distance))))
        )
        await page.wait_for_timeout(rng.randint(120, 260))
        await _settle(page, mouse, overshoot, x + distance, y, rng)
        await page.wait_for_timeout(rng.randint(80, 180))
    finally:
        await mouse.up()


async def _glide(
    page: Any, mouse: Any, x: float, target: float, y: float, rng: random.Random, steps: int
) -> float:
    """Eased, wobbling pointer moves from `x` towards `target`; returns the overshoot point."""
    overshoot = target + rng.uniform(2.0, 6.0) * (1 if target > x else -1)
    for index in range(1, steps + 1):
        eased = 1.0 - (1.0 - index / steps) ** 4
        wobble = rng.uniform(-0.8, 0.8) if index < steps else 0.0
        await mouse.move(x + (overshoot - x) * eased + wobble, y + rng.uniform(-2.0, 2.0))
        await page.wait_for_timeout(int(4 + 14 * (1.0 - eased)))
    return overshoot


async def _settle(
    page: Any, mouse: Any, overshoot: float, target: float, y: float, rng: random.Random
) -> None:
    """The small correction that backs the pointer from the overshoot onto the target."""
    for index in range(1, 13):
        await mouse.move(overshoot + (target - overshoot) * index / 12, y + rng.uniform(-1.0, 1.0))
        await page.wait_for_timeout(8)


def _decode(png: bytes) -> Any:
    import cv2
    import numpy

    image = cv2.imdecode(numpy.frombuffer(png, dtype=numpy.uint8), cv2.IMREAD_UNCHANGED)
    return image if image is not None and image.ndim in (2, 3) else None


def _gray(image: Any) -> Any:
    import cv2

    if image.ndim == 3:
        if image.shape[2] == 4:
            image = cv2.cvtColor(image, cv2.COLOR_BGRA2BGR)
        image = cv2.cvtColor(image, cv2.COLOR_BGR2GRAY)
    return image


def _opaque(image: Any) -> Any:
    """Crop an RGBA piece to the pixels it actually shows; fully hidden pieces are None."""
    import numpy

    if image.ndim != 3 or image.shape[2] != 4:
        return image
    ys, xs = numpy.nonzero(image[:, :, 3])
    if not len(ys):
        return None
    return image[ys.min() : ys.max() + 1, xs.min() : xs.max() + 1]


def _edges_sobel(gray: Any) -> Any:
    import cv2

    blurred = cv2.GaussianBlur(gray, (3, 3), 0)
    gx = cv2.Sobel(blurred, cv2.CV_16S, 1, 0, ksize=3)
    gy = cv2.Sobel(blurred, cv2.CV_16S, 0, 1, ksize=3)
    mixed = cv2.addWeighted(cv2.convertScaleAbs(gx), 0.5, cv2.convertScaleAbs(gy), 0.5, 0)
    return cv2.normalize(mixed, None, 0, 255, cv2.NORM_MINMAX).astype("uint8")


def _edges_canny(gray: Any) -> Any:
    import cv2

    return cv2.Canny(gray, 50, 150)


def gap_offset(background: Any, piece: Any) -> int | None:
    """The piece's x offset inside the background image, in the arrays' own pixels.

    Both are reduced to edge maps first: the piece is mostly transparent, and edges make the
    match insensitive to the textures around the gap. Returns None when no placement scores.
    """
    if background is None or piece is None:
        return None
    piece = _opaque(piece)
    if piece is None:
        return None
    background_gray, piece_gray = _gray(background), _gray(piece)
    best_score, best_x = 0.0, None
    for edges in (_edges_sobel, _edges_canny):
        hay, needle = edges(background_gray), edges(piece_gray)
        if needle.shape[0] > hay.shape[0] or needle.shape[1] > hay.shape[1]:
            continue
        import cv2

        result = cv2.matchTemplate(hay, needle, cv2.TM_CCOEFF_NORMED)
        _, score, _, location = cv2.minMaxLoc(result)
        if score > best_score:
            best_score, best_x = score, location[0]
    return best_x if best_score >= MIN_MATCH else None


def _ring(image: Any, radius_lo: float, radius_hi: float) -> Any:
    """The image sampled around its centre as (radii, degrees, channels), floats.

    Degrees run clockwise on screen (image y grows downwards), so a circular shift of the
    ring by `n` is exactly an `n`-degree clockwise rotation of the sampled pattern.
    """
    import numpy

    height, width = image.shape[:2]
    cy, cx = (height - 1) / 2.0, (width - 1) / 2.0
    phis = numpy.deg2rad(numpy.arange(360))
    rows = []
    for radius in numpy.linspace(radius_lo, radius_hi, 5):
        ys = numpy.clip(numpy.round(cy + radius * numpy.sin(phis)).astype(int), 0, height - 1)
        xs = numpy.clip(numpy.round(cx + radius * numpy.cos(phis)).astype(int), 0, width - 1)
        rows.append(image[ys, xs].reshape(360, -1).astype(float))
    return numpy.stack(rows)


def whirl_angle(inner: Any, outer: Any, hole_radius: float | None = None) -> float | None:
    """The clockwise rotation that turns the inner disc to match the outer ring, degrees 0..360.

    The outer image is a ring around the white hole the disc fills, so the images are compared
    where they meet: the disc's rim (a band just inside its edge) against the ring just
    outside the hole, both sampled as colour rings. The hole's radius in the ring's own pixels
    comes from the modal's rendered sizes — `hole_radius`, the disc's on-screen share of the
    ring applied to the ring's native width — because the two images' native resolutions need
    not match; without rendered sizes the disc's own native radius is the stand-in. The best
    circular shift of one ring against the other is the rotation; one degree of resolution
    sits well inside the puzzle's own tolerance.
    """
    if inner is None or outer is None:
        return None
    import numpy

    side = min(inner.shape[:2])
    if side < 40:
        return None
    radius = side / 2.0
    hole = radius if hole_radius is None else hole_radius
    if min(outer.shape[:2]) < 2 * hole + 16:
        return None
    inner_rim = _ring(inner, radius - 7, radius - 2)
    outer_rim = _ring(outer, hole + 2, hole + 7)
    errors = [
        float(numpy.abs(numpy.roll(inner_rim, shift, axis=1) - outer_rim).mean())
        for shift in range(360)
    ]
    return float(min(range(360), key=errors.__getitem__))
