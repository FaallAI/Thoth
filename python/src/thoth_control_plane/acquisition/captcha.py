"""Solve the TikTok captcha modal that rises over a listing page.

TikTok raises this modal when its risk engine refuses the session's signed list request; the
grid under it never loads until the challenge is answered. The two drag subtypes are solved
from the modal's own images: ``slide`` (fit the puzzle piece into the gap) and ``whirl``
(rotate the inner disc upright) — OpenCV for the where, one humanized pointer drag for the
how. The 2026 whirl modal (a TUXModal) labels none of its moving parts, so the images are
picked by rendered size, the track is found through the handle's draggable wrapper, and the
slider's degrees-per-pixel is measured live in mid-drag.

The 3D click subtype ("select 2 objects of the same shape") is answered by the local
solver in :mod:`captcha_shapes`: two points on the one challenge image, clicked
humanized, then Confirm — behind the ``THOTH_CAPTCHA_CLICK_SOLVER`` switch
(``off``/``local``/``local_vision``; the paid vision fallback in ``local_vision`` only
runs when the local solver refuses and an OpenRouter key is set). Icon and unknown click
subtypes are classified but never answered, and every modal the solver cannot answer
leaves one sanitized sample for the record (see :data:`SAMPLE_LIMIT`).

Solving is best effort and never raises: without OpenCV, on an unsupported subtype, or after
the attempt budget, :func:`solve` returns False and the caller keeps its captcha behaviour.
Every call ends in exactly one INFO outcome line — the place production counts the solver's
success rate from. Selectors follow the ones every maintained solver documents (EulerStream,
ScrapeCreators, arc298's solver); both spellings of the container class appear across TikTok
builds.
"""

from __future__ import annotations

import asyncio
import base64
import json
import logging
import math
import os
import random
import re
import shutil
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from pydantic import BaseModel, Field

import thoth_control_plane.metering as metering

logger = logging.getLogger(__name__)

CONTAINER_SELECTOR = ".captcha_verify_container, .captcha-verify-container"
IMAGE_SELECTOR = "#captcha-verify-image"
WHIRL_IMAGE_SELECTOR = f"{CONTAINER_SELECTOR} img"
PIECE_SELECTOR = ".captcha_verify_img_slide"
TRACK_SELECTOR = ".captcha_verify_slide--slidebar"
HANDLE_SELECTOR = ".secsdk-captcha-drag-icon"
#: The 3D modal's parts: the one challenge image and the Confirm button, both inside the
#: modal's ``.cap-relative`` column. Structure, not wording, says this is a click modal —
#: it works with ``blob:`` sources and any locale.
CLICK_IMAGE_SELECTOR = f"{CONTAINER_SELECTOR} .cap-relative img"
CONFIRM_SELECTOR = f"{CONTAINER_SELECTOR} .cap-relative button.cap-w-full"
#: One recorded 2026 modal has no refresh id, only TikTok's refresh glyph (the SVG path
#: every recorded refresh button carries); the glyph selector is the fallback.
REFRESH_SELECTOR = "#captcha_refresh_button"
REFRESH_GLYPH_SELECTOR = f"{CONTAINER_SELECTOR} button:has(path[d^='M56.62 21'])"
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
#: production really meets. The Indonesian "bentuknya sama" (added 2026-11-06 for Phase B)
#: is unverified wording too: it is the leading guess at what production's
#: subtype=unknown met, and no primary source carries an Indonesian prompt.
CLICK_PROMPTS: dict[str, tuple[str, ...]] = {
    "3d": ("same shape", "bentuk yang sama", "bentuknya sama", "3d"),
    "icon": ("icon", "ikon", "sesuai", "match"),
}
#: The 3D solver's switch: ``off`` keeps today's classify-capture-refuse, ``local`` adds
#: the free local solver (the default: the offline evaluation shows no wrong answer at the
#: chosen margin), ``local_vision`` also falls back to the paid vision model on a refusal.
CLICK_SOLVER_ENV = "THOTH_CAPTCHA_CLICK_SOLVER"
CLICK_SOLVERS = ("off", "local", "local_vision")
#: The vision fallback rides the project's one OpenRouter key (config's
#: THOTH_OPENROUTER_API_KEY) and its own model setting; no key means no call.
OPENROUTER_KEY_ENV = "THOTH_OPENROUTER_API_KEY"
VISION_MODEL_ENV = "THOTH_CAPTCHA_VISION_MODEL"
DEFAULT_VISION_MODEL = "qwen/qwen3-vl-30b-a3b-instruct"
CONFIRM_TIMEOUT_MS = 3_000
CONFIRM_POLL_MS = 120
ATTEMPTS = 2
MIN_MATCH = 0.25
#: After a drag the modal can take seconds to close on a right answer (live, signed in,
#: 2026-10-23: it outlasted a fixed 1.5 s check, and the solve was logged as a failure), so
#: the check polls until the modal is gone or the budget runs out.
VERIFY_TIMEOUT_MS = 6_000
VERIFY_POLL_MS = 250
#: Evidence capture: one sanitized sample per modal the solver cannot answer, the newest
#: SAMPLE_LIMIT kept. Samples land under the worker's artifact root only when the environment
#: names one (compose sets THOTH_CONTROL_PLANE_ARTIFACT_ROOT on stage1); an unset root means
#: no capture and no writes anywhere. No click modal was ever recorded (2026-11-06 and
#: earlier), so the samples are the evidence a click solver will be built from.
SAMPLE_LIMIT = 50
CAPTURE_BUDGET_S = 5.0
MAX_SAMPLE_IMAGES = 12
DOM_JS = "el => el.outerHTML"
BOXES_JS = (
    "root => { const out = [];"
    " for (const el of root.querySelectorAll('img, canvas, button, span')) {"
    "  if (el.tagName === 'SPAN' &&"
    "      (el.textContent.trim().length <= 8 || el.closest('button'))) continue;"
    "  const r = el.getBoundingClientRect();"
    "  out.push({tag: el.tagName.toLowerCase(),"
    "   box: {x: r.x, y: r.y, width: r.width, height: r.height}}); }"
    " return out; }"
)
CANVAS_JS = "el => el.toDataURL('image/png')"
_SCRUB = re.compile(r"""([\w:-]+)=("[^"]*"|'[^']*')""")
_URL_IN_STYLE = re.compile(r"url\([^)]*\)")
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
    answered: set[str] = set()  # every challenge image this call already answered
    for attempt in range(1, attempts + 1):
        try:
            subtype, reason, solved = await _attempt(page, rng, answered)
        except Exception as error:
            logger.debug("tiktok captcha attempt failed error=%s", type(error).__name__)
            reason = "error"
        else:
            if solved:
                _outcome(subtype, True, attempt, "none")
                return True
            if reason in ("unsupported", "unconfident", "no_vision"):
                break  # nothing a retry changes: no solver, or a deterministic refusal
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


async def _attempt(page: Any, rng: random.Random, answered: set[str]) -> tuple[str, str, bool]:
    """One try: the subtype it saw, why it fell short ("none" when it did not), and success."""
    if await page.query_selector(CONTAINER_SELECTOR) is None:
        return "unknown", "no_images", False
    handle = await page.query_selector(HANDLE_SELECTOR)
    subtype = await _classify(page)
    if handle is None:
        # No drag handle: a click modal, answered by the 3D solver when it is one and the
        # switch allows; whatever happens, one sanitized sample keeps the record.
        return await _click_attempt(page, rng, subtype, answered)
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


def _click_mode() -> str:
    """The click-solver switch's value, with an unknown value landing on the safe side."""
    mode = os.environ.get(CLICK_SOLVER_ENV, "local")
    if mode not in CLICK_SOLVERS:
        logger.warning("tiktok captcha click solver mode unknown, staying off")
        return "off"
    return mode


async def _click_attempt(
    page: Any, rng: random.Random, subtype: str, answered: set[str]
) -> tuple[str, str, bool]:
    """A click modal: structural parts first, then the 3D solver when the switch allows."""
    image = await page.query_selector(CLICK_IMAGE_SELECTOR)
    confirm = await page.query_selector(CONFIRM_SELECTOR)
    if image is None or confirm is None or subtype != "3d" or _click_mode() == "off":
        # Icon and unknown stay unhandled; `off` keeps today's classify-capture-refuse.
        await _capture_sample(page, subtype, "unsupported")
        return subtype, "unsupported", False
    return await _shapes_attempt(page, rng, image, confirm, subtype, answered)


async def _shapes_attempt(
    page: Any, rng: random.Random, image: Any, confirm: Any, subtype: str, answered: set[str]
) -> tuple[str, str, bool]:
    """Answer one 3D challenge: solve locally, fall back to vision on a refusal, click."""
    src = await image.get_attribute("src")
    box = await image.bounding_box()
    if not isinstance(src, str) or not src or not box or not box["width"]:
        return subtype, "no_images", False
    if src in answered:
        # This exact image was already answered and the modal stayed: without a fresh
        # challenge the same image is never answered twice.
        logger.debug("tiktok captcha image unchanged; not answering it twice")
        await _capture_sample(page, subtype, "modal_stayed")
        return subtype, "modal_stayed", False
    decoded = _decode(await _src_bytes(page, image))
    if decoded is None:
        return subtype, "no_images", False
    from thoth_control_plane.acquisition.captcha_shapes import (
        MAX_MARKS,
        marked_image,
        same_shape_pair,
    )

    result = same_shape_pair(decoded)
    points = result.points
    if points is None and _click_mode() == "local_vision":
        key = os.environ.get(OPENROUTER_KEY_ENV, "")
        if not key:
            await _capture_sample(page, subtype, "no_vision")
            return subtype, "no_vision", False
        marked = marked_image(decoded, result.objects) if len(result.objects) >= 2 else b""
        pick = await _vision_answer(marked, key) if marked else None
        marks = min(len(result.objects), MAX_MARKS)
        if pick is not None and pick.first != pick.second and max(pick.first, pick.second) <= marks:
            first, second = result.objects[pick.first - 1], result.objects[pick.second - 1]
            points = (first.centroid, second.centroid)
    if points is None:
        await _capture_sample(page, subtype, "unconfident")
        return subtype, "unconfident", False
    answered.add(src)
    await _click_answer(page, rng, image, box, decoded.shape, points, confirm)
    gone = await _closed(page)
    if gone:
        return subtype, "none", True
    await _capture_sample(page, subtype, "modal_stayed")
    await _press_refresh(page, rng)
    return subtype, "modal_stayed", False


async def _press_refresh(page: Any, rng: random.Random) -> Any:
    """Click the modal's Refresh button: the recorded id first, then the glyph selector."""
    for selector in (REFRESH_SELECTOR, REFRESH_GLYPH_SELECTOR):
        button = await page.query_selector(selector)
        box = await button.bounding_box() if button is not None else None
        if button is None or box is None:
            continue
        await _human_click(
            page,
            page.mouse,
            box["x"],
            box["y"] - 30,
            box["x"] + box["width"] / 2,
            box["y"] + box["height"] / 2,
            rng,
        )
        return button
    logger.debug("tiktok captcha refresh button not found; the next attempt sees the same image")
    return None


async def _click_answer(
    page: Any,
    rng: random.Random,
    image: Any,
    box: dict,
    shape: tuple,
    points: tuple[tuple[float, float], tuple[float, float]],
    confirm: Any,
) -> None:
    """Two humanized clicks at the image points, then Confirm once it enables.

    Image pixels become page points through the image's rendered box, so whatever size the
    modal shows the challenge at, the answer lands where the solver saw it.
    """
    height, width = shape[:2]
    mouse = page.mouse
    last_x = box["x"] + rng.uniform(-40, 10)
    last_y = max(0.0, box["y"] - rng.uniform(20, 60))  # the hand comes from above the card
    for index, (px, py) in enumerate(points):
        x = box["x"] + px / width * box["width"]
        y = box["y"] + py / height * box["height"]
        await _human_click(page, mouse, last_x, last_y, x, y, rng)
        last_x, last_y = x, y
        if index == 0:
            await page.wait_for_timeout(rng.randint(150, 400))
    await _wait_confirm(page, confirm)
    confirm_box = await confirm.bounding_box()
    if confirm_box:
        await _human_click(
            page,
            mouse,
            last_x,
            last_y,
            confirm_box["x"] + confirm_box["width"] / 2,
            confirm_box["y"] + confirm_box["height"] / 2,
            rng,
        )


async def _wait_confirm(page: Any, confirm: Any) -> None:
    """Wait for Confirm to enable after the clicks; a disabled Confirm is clicked anyway
    (a no-op) and the modal poll decides the attempt."""
    for _ in range(CONFIRM_TIMEOUT_MS // CONFIRM_POLL_MS):
        disabled = await confirm.get_attribute("aria-disabled")
        klass = await confirm.get_attribute("class")
        if disabled != "true" and "TUXButton--disabled" not in (klass or ""):
            return
        await page.wait_for_timeout(CONFIRM_POLL_MS)
    logger.debug("tiktok captcha confirm never enabled after the clicks")


async def _human_click(
    page: Any, mouse: Any, from_x: float, from_y: float, x: float, y: float, rng: random.Random
) -> None:
    """One humanized click: an eased, wobbling approach onto a jittered landing, a short
    hold. Whatever happens after the press, the button comes back up."""
    land_x = x + rng.uniform(-2.0, 2.0)
    land_y = y + rng.uniform(-2.0, 2.0)
    distance = math.hypot(land_x - from_x, land_y - from_y)
    steps = max(8, min(24, int(distance / 9) or 1))
    for index in range(1, steps + 1):
        eased = 1.0 - (1.0 - index / steps) ** 4
        wobble = rng.uniform(-1.0, 1.0) if index < steps else 0.0
        await mouse.move(
            from_x + (land_x - from_x) * eased + wobble, from_y + (land_y - from_y) * eased + wobble
        )
        await page.wait_for_timeout(int(4 + 14 * (1.0 - eased)))
    await mouse.down()
    try:
        await page.wait_for_timeout(rng.randint(50, 140))
    finally:
        await mouse.up()


async def _capture_sample(page: Any, subtype: str, reason: str) -> None:
    """Save one sanitized sample of a modal the solver cannot answer, best effort.

    The sample — sanitized DOM, prompt candidates, image and button boxes, the images as
    served — is the only record of a click modal, because none was ever captured before
    2026-11-06. Nothing here may raise, delay the solver past CAPTURE_BUDGET_S, or keep a
    cookie, page URL or creator handle: attribute values that look like tokens or links are
    blanked in the saved DOM, and only the modal's own parts are read. Unset artifact root:
    no capture at all.
    """
    root = os.environ.get("THOTH_CONTROL_PLANE_ARTIFACT_ROOT")
    if not root:
        return
    try:
        await asyncio.wait_for(_write_sample(page, subtype, reason, Path(root)), CAPTURE_BUDGET_S)
    except Exception:
        logger.debug("tiktok captcha sample not saved")


async def _write_sample(page: Any, subtype: str, reason: str, root: Path) -> None:
    container = await page.query_selector(CONTAINER_SELECTOR)
    if container is None:
        return
    prompts = await container.evaluate(PROMPT_JS)
    dom = await container.evaluate(DOM_JS)
    boxes = await container.evaluate(BOXES_JS)
    entries: list[dict[str, Any]] = []
    blobs: list[tuple[str, bytes]] = []
    for element in (await page.query_selector_all(WHIRL_IMAGE_SELECTOR))[:MAX_SAMPLE_IMAGES]:
        src = await element.get_attribute("src")
        entry: dict[str, Any] = {"src_hint": _src_hint(src if isinstance(src, str) else "")}
        try:
            data = await _src_bytes(page, element)
        except Exception:  # one unfetchable image must not lose the sample
            data = b""
        if data:
            name = f"image-{len(blobs)}.{_image_ext(data)}"
            entry["file"] = name
            blobs.append((name, data))
        entries.append(entry)
    # The picture the sample falls back to when the challenge is not an <img> at all: the
    # modal's own content clipped out — never the page behind an overlay container.
    visuals: dict[str, Any] = {"modal": None, "canvases": []}
    for canvas in await container.query_selector_all("canvas"):
        try:
            url = await canvas.evaluate(CANVAS_JS)
        except Exception:  # a tainted canvas refuses; it stays unrecorded
            continue
        if isinstance(url, str) and url.startswith("data:"):
            name = f"canvas-{len(visuals['canvases'])}.png"
            visuals["canvases"].append({"file": name})
            blobs.append((name, base64.b64decode(url.split(",", 1)[1])))
    clip = _union_box(boxes)
    if clip is not None and _covers_viewport(clip, getattr(page, "viewport_size", None)):
        clip = None  # a full-screen overlay's union is the page behind it: no picture
    if clip is not None:
        try:
            png = await page.screenshot(clip=clip, scale="css", timeout=2_000)
        except Exception:  # a failed screenshot must not lose the rest of the sample
            png = None
        if png:
            visuals["modal"] = {"clip": clip, "file": "modal.png"}
            blobs.append(("modal.png", png))
    now = datetime.now(UTC)
    sample = root / "captcha-samples" / now.strftime("%Y%m%dT%H%M%S%fZ")
    sample.mkdir(parents=True, exist_ok=True)
    (sample / "sample.json").write_text(
        json.dumps(
            {
                "captured_at": now.isoformat(),
                "subtype": subtype,
                "reason": reason,
                "prompt_candidates": prompts if isinstance(prompts, list) else [],
                "boxes": boxes if isinstance(boxes, list) else [],
                "images": entries,
                "visuals": visuals,
            },
            indent=2,
        ),
        encoding="utf-8",
    )
    (sample / "dom.html").write_text(
        _sanitize_dom(dom if isinstance(dom, str) else ""), encoding="utf-8"
    )
    for name, data in blobs:
        (sample / name).write_bytes(data)
    _prune_samples(sample.parent)


def _union_box(boxes: Any) -> dict[str, float] | None:
    """The clip covering every rendered element box, or None when nothing rendered."""
    if not isinstance(boxes, list):
        return None
    visible = [
        entry["box"]
        for entry in boxes
        if isinstance(entry, dict)
        and isinstance(entry.get("box"), dict)
        and entry["box"].get("width", 0) + entry["box"].get("height", 0) > 0
    ]
    if not visible:
        return None
    left = min(box["x"] for box in visible)
    top = min(box["y"] for box in visible)
    return {
        "x": left,
        "y": top,
        "width": max(box["x"] + box["width"] for box in visible) - left,
        "height": max(box["y"] + box["height"] for box in visible) - top,
    }


def _covers_viewport(clip: dict[str, float], viewport: Any) -> bool:
    """Whether the clip's area covers more than half the viewport.

    The 2026 container can be a full-screen overlay over the creator's profile: when the
    modal's own boxes grow that large, the clipped picture would carry the page behind it,
    so none is saved. A page that names no viewport never skips."""
    if not isinstance(viewport, dict) or not viewport.get("width") or not viewport.get("height"):
        return False
    return clip["width"] * clip["height"] > 0.5 * viewport["width"] * viewport["height"]


def _src_hint(src: str) -> str:
    """The subtype marker TikTok bakes into some captcha image URLs, when present.

    Data and blob URLs carry no marker, and a base64 payload can contain any bytes, so
    only real URL paths are read.
    """
    if src.startswith(("data:", "blob:")):
        return ""
    if "/3d" in src:
        return "3d"
    if "/icon" in src:
        return "icon"
    return ""


def _sanitize_dom(dom: str) -> str:
    """Attribute values that look like tokens or links blanked; the modal's shape stays."""

    def blank(match: re.Match[str]) -> str:
        name, quoted = match.group(1), match.group(2)
        value = quoted[1:-1]
        if name.lower() == "style":
            value = _URL_IN_STYLE.sub("url()", value)
        if value.startswith(("data:", "//", "blob:")) or "://" in value or len(value) > 200:
            return f'{name}=""'
        return f"{name}={quoted[0]}{value}{quoted[-1]}" if value != quoted[1:-1] else match.group(0)

    return _SCRUB.sub(blank, dom)[:200_000]


def _image_ext(data: bytes) -> str:
    if data.startswith(b"\x89PNG"):
        return "png"
    if data.startswith(b"\xff\xd8\xff"):
        return "jpg"
    if data[:4] == b"RIFF" and data[8:12] == b"WEBP":
        return "webp"
    if data.startswith(b"GIF8"):
        return "gif"
    return "bin"


def _prune_samples(parent: Path) -> None:
    for old in sorted(path for path in parent.iterdir() if path.is_dir())[:-SAMPLE_LIMIT]:
        shutil.rmtree(old, ignore_errors=True)


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
    """The click subtype (3d, icon) from the modal's own signals, or "unknown".

    A click modal carries no drag handle, so the subtype comes from what is left: the URL
    marker TikTok bakes into http(s) sources (a ``blob:`` or data source has none), then
    the prompt's shape — the number 2 without a question mark is the 3D ask, a trailing
    question mark the icon ask — then the keyword table, which is seller documentation, not
    recorded evidence (see :data:`CLICK_PROMPTS`). Where the decision came from is logged
    at debug. Either way an unhandled subtype is never clicked at random.
    """
    container = await page.query_selector(CONTAINER_SELECTOR)
    if container is None:
        return "unknown"
    image = await page.query_selector(CLICK_IMAGE_SELECTOR)
    if image is not None:
        src = await image.get_attribute("src")
        hint = _src_hint(src if isinstance(src, str) else "")
        if hint:
            logger.debug("tiktok captcha subtype=%s source=url", hint)
            return hint
    try:
        prompts = await container.evaluate(PROMPT_JS)
    except Exception:
        prompts = None
    text = " ".join(prompts if isinstance(prompts, list) else []).strip().lower()
    subtype, source = "unknown", "structure"
    if text.endswith("?"):
        subtype, source = "icon", "prompt"
    elif re.search(r"\b2\b", text):
        subtype, source = "3d", "prompt"
    else:
        for name, words in CLICK_PROMPTS.items():
            if any(word in text for word in words):
                subtype, source = name, "keywords"
                break
    logger.debug("tiktok captcha subtype=%s source=%s", subtype, source)
    return subtype


class _VisionPick(BaseModel):
    """The vision fallback's strict reply: two numbered candidates, nothing else."""

    first: int = Field(ge=1)
    second: int = Field(ge=1)


VISION_PROMPT = (
    "This captcha image shows numbered red boxes over 3D objects. Reply with the numbers of "
    "exactly TWO boxes whose objects are the same shape (colour and size may differ; a "
    "mirrored or slightly rotated copy counts as the same shape). Answer in JSON with the "
    "fields first and second."
)


async def _run_vision_agent(marked: bytes, key: str, model: str) -> Any:
    """One OpenRouter call over the set-of-marks picture; raises on any failure."""
    import httpx

    from thoth_control_plane.attribution.adapters.vision import OPENROUTER_BASE_URL

    # Built like AgnoVisionReader's _run: agno over OpenAI-compatible OpenRouter, a strict
    # output schema, json mode, no telemetry, and an httpx client this code closes itself.
    http = httpx.AsyncClient(timeout=60.0)
    try:
        from agno.agent import Agent
        from agno.media import Image
        from agno.models.openai.like import OpenAILike

        agent = Agent(
            model=OpenAILike(
                id=model,
                api_key=key,
                base_url=OPENROUTER_BASE_URL,
                timeout=60.0,
                max_retries=1,
                http_client=http,
            ),
            output_schema=_VisionPick,
            use_json_mode=True,
            telemetry=False,
        )
        images = [Image(content=marked, mime_type="image/png")]
        return await agent.arun(input=VISION_PROMPT, images=images)
    finally:
        await http.aclose()


async def _vision_answer(marked: bytes, key: str) -> _VisionPick | None:
    """The fallback's pick of two candidate numbers, or None when it is unusable.

    One metered call per attempt — recorded into usage_events exactly like the attribution
    vision reader's runs — and a reply that does not parse under the strict schema is a
    refusal, never a guess.
    """
    model = os.environ.get(VISION_MODEL_ENV, DEFAULT_VISION_MODEL)
    try:
        run = await _run_vision_agent(marked, key, model)
    except Exception:
        logger.warning("tiktok captcha vision fallback unavailable")
        return None
    await metering.record_model_run(model, run)
    if isinstance(run.content, _VisionPick):
        return run.content
    logger.debug("tiktok captcha vision reply unusable")
    return None


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
