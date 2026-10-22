"""Solve the TikTok captcha modal that rises over a listing page.

TikTok raises this modal when its risk engine refuses the session's signed list request; the
grid under it never loads until the challenge is answered. The two drag subtypes are solved
from the modal's own images: ``slide`` (fit the puzzle piece into the gap) and ``whirl``
(rotate the inner disc upright) — OpenCV for the where, one humanized pointer drag for the
how. Click subtypes (icon matching, 3D shapes) are not attempted.

Solving is best effort and never raises: without OpenCV, on an unsupported subtype, or after
the attempt budget, :func:`solve` returns False and the caller keeps its captcha behaviour.
Selectors follow the ones every maintained solver documents (EulerStream, ScrapeCreators,
arc298's solver); both spellings of the container class appear across TikTok builds.
"""

from __future__ import annotations

import base64
import logging
import random
from typing import Any

logger = logging.getLogger(__name__)

CONTAINER_SELECTOR = ".captcha_verify_container, .captcha-verify-container"
IMAGE_SELECTOR = "#captcha-verify-image"
PIECE_SELECTOR = ".captcha_verify_img_slide"
TRACK_SELECTOR = ".captcha_verify_slide--slidebar"
HANDLE_SELECTOR = ".secsdk-captcha-drag-icon"
ATTEMPTS = 2
MIN_MATCH = 0.25
VERIFY_WAIT_MS = 1_500
#: The whirl drag's direction is a UI convention this module cannot read off the images, so
#: the second attempt tries the mirrored angle; one of the two is the upright rotation.
WHIRL_SIDE = 160


async def solve(page: Any, attempts: int = ATTEMPTS, rng: random.Random | None = None) -> bool:
    """Drag the modal's slider until TikTok removes it; False when the modal stays.

    Never raises: any surprise (missing OpenCV, unsupported subtype, detached element) is
    logged and treated as an unsolved attempt.
    """
    try:
        import cv2  # noqa: F401
        import numpy  # noqa: F401
    except ImportError:
        logger.warning("tiktok captcha solver unavailable: opencv is not installed")
        return False
    rng = rng or random.Random()
    for attempt in range(1, attempts + 1):
        try:
            if await _attempt(page, rng, flip=attempt > 1):
                logger.info("tiktok captcha solved attempt=%d", attempt)
                return True
        except Exception as error:
            logger.debug("tiktok captcha attempt failed error=%s", type(error).__name__)
        if attempt < attempts:
            await page.wait_for_timeout(400)
    logger.warning("tiktok captcha unsolved attempts=%d", attempts)
    return False


async def _attempt(page: Any, rng: random.Random, *, flip: bool) -> bool:
    if await page.query_selector(CONTAINER_SELECTOR) is None:
        return False
    handle = await page.query_selector(HANDLE_SELECTOR)
    if handle is None:
        return False
    piece = await page.query_selector(PIECE_SELECTOR)
    if piece is not None:
        subtype, drag = "slide", await _slide_drag(page, piece)
    else:
        subtype, drag = "whirl", await _whirl_drag(page, handle, flip)
    if drag is None or abs(drag) < 1:
        logger.debug("tiktok captcha %s subtype gave no drag distance", subtype)
        return False
    await _drag(page, handle, drag, rng)
    await page.wait_for_timeout(VERIFY_WAIT_MS)
    return await page.query_selector(CONTAINER_SELECTOR) is None


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


async def _whirl_drag(page: Any, handle: Any, flip: bool) -> float | None:
    """The pointer distance that stands the inner disc upright, in page CSS pixels."""
    outer = await page.query_selector(IMAGE_SELECTOR)
    outer_box = await outer.bounding_box() if outer is not None else None
    inner = inner_box = None
    if outer_box:
        for element in await page.query_selector_all("img"):
            box = await element.bounding_box()
            if box and box["width"] and box["width"] < outer_box["width"] * 0.9:
                inner, inner_box = element, box
                break
    track = await page.query_selector(TRACK_SELECTOR)
    track_box = await track.bounding_box() if track is not None else None
    handle_box = await handle.bounding_box()
    if not (outer and inner and outer_box and inner_box and track_box and handle_box):
        return None
    angle = whirl_angle(
        _decode(await _src_bytes(page, inner)), _decode(await _src_bytes(page, outer))
    )
    if angle is None:
        return None
    span = max(1.0, track_box["width"] - handle_box["width"])
    return span * ((360.0 - angle) if flip else angle) / 360.0


async def _drag(page: Any, handle: Any, distance: float, rng: random.Random) -> None:
    """One humanized drag: fast then slow, a small overshoot, then a settle on the target.

    A steady constant-speed slide is the trajectory TikTok's detection rejects, so the pointer
    eases out, wobbles slightly, passes the target by a few pixels and backs onto it.
    """
    box = await handle.bounding_box()
    if not box:
        return
    mouse = page.mouse
    x = box["x"] + box["width"] / 2
    y = box["y"] + box["height"] / 2
    target = x + distance
    overshoot = target + rng.uniform(2.0, 6.0) * (1 if distance > 0 else -1)
    steps = max(24, min(60, int(abs(distance))))
    await mouse.move(x, y)
    await mouse.down()
    for index in range(1, steps + 1):
        eased = 1.0 - (1.0 - index / steps) ** 4
        wobble = rng.uniform(-0.8, 0.8) if index < steps else 0.0
        await mouse.move(x + (overshoot - x) * eased + wobble, y + rng.uniform(-2.0, 2.0))
        await page.wait_for_timeout(int(4 + 14 * (1.0 - eased)))
    await page.wait_for_timeout(rng.randint(120, 260))
    for index in range(1, 13):
        await mouse.move(overshoot + (target - overshoot) * index / 12, y + rng.uniform(-1.0, 1.0))
        await page.wait_for_timeout(8)
    await page.wait_for_timeout(rng.randint(80, 180))
    await mouse.up()


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


def _square(gray: Any) -> Any:
    import cv2

    height, width = gray.shape[:2]
    side = min(height, width)
    if side < 40:
        return None
    top, left = (height - side) // 2, (width - side) // 2
    square = gray[top : top + side, left : left + side]
    return cv2.resize(square, (WHIRL_SIDE, WHIRL_SIDE), interpolation=cv2.INTER_AREA)


def whirl_angle(inner: Any, outer: Any) -> float | None:
    """The rotation that turns the inner disc to match the outer ring, in degrees 0..360.

    The two images are compared over a ring band near the disc's edge, where a misrotation
    shows as the largest brightness mismatch; a coarse sweep then a 1-degree refinement keep
    this cheap. Both directions of TikTok's drag convention are covered by the retry flip.
    """
    if inner is None or outer is None:
        return None
    import cv2
    import numpy

    inner_square, outer_square = _square(_gray(inner)), _square(_gray(outer))
    if inner_square is None or outer_square is None:
        return None
    side = WHIRL_SIDE
    center = (side / 2.0, side / 2.0)
    yy, xx = numpy.ogrid[:side, :side]
    radius = numpy.sqrt((xx - center[0]) ** 2 + (yy - center[1]) ** 2)
    band = (radius >= side * 0.36) & (radius <= side * 0.48)

    def mismatch(angle: float) -> float:
        matrix = cv2.getRotationMatrix2D(center, angle, 1.0)
        rotated = cv2.warpAffine(inner_square, matrix, (side, side))
        difference = numpy.abs(rotated.astype(numpy.int16) - outer_square).astype(numpy.int16)
        return float(difference[band].mean())

    coarse = min(range(0, 360, 3), key=mismatch)
    return (min((coarse + delta for delta in range(-3, 4)), key=mismatch)) % 360.0
