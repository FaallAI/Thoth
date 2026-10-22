"""Persist real TikTok card crops as checksummed report artifacts.

Cards are best effort. A crop that is not a usable PNG, or whose write fails, is dropped and
its comment keeps `card=None`; nothing here fails acquisition. Nothing from a comment (text,
handle, id, path) reaches the log: the single warning carries counts only.
"""

from __future__ import annotations

import contextlib
import hashlib
import logging
import os
import struct
from pathlib import Path, PurePosixPath

from thoth_control_plane.acquisition.models import (
    MAX_CARD_BYTES,
    BrowserSnapshot,
    CardArtifact,
    MediaBox,
    ReportComment,
)

logger = logging.getLogger(__name__)

PNG_SIGNATURE = b"\x89PNG\r\n\x1a\n"
# The IEND chunk: zero length, type, and its fixed CRC.
PNG_IEND = b"\x00\x00\x00\x00IEND\xaeB`\x82"
# Scout keeps a crop only when rect.w > 30 and rect.h > 12.
MIN_CARD_WIDTH = 31
MIN_CARD_HEIGHT = 13
MAX_CARD_SIDE = 4_096
# Scout's black-crop guard (scout/lib/crop_guard.ts): a real card runs ~0.09-0.15 bytes per
# pixel, a flat or blank crop ~0.005.
MIN_CARD_BPP = 0.02


# The post card's media box (spec 5c-2, G1): every video and every image at least this share of
# the card's width, joined. Platform class names churn, and X's 2026 DOM has no test ids, so
# the media is found by shape, not by a selector; avatars and emoji stay below the share.
MEDIA_BOX_JS = """(selector) => {
  const card = document.querySelector(selector);
  if (!card) return null;
  const box = e => {
    const b = e.getBoundingClientRect();
    return {x: b.left, y: b.top, width: b.width, height: b.height};
  };
  const c = box(card);
  const media = [...card.querySelectorAll('video, img')].map(box)
    .filter(b => b.width >= 0.3 * c.width && b.height > 0);
  if (!media.length) return {card: c, media: null};
  const x1 = Math.min(...media.map(b => b.x)), y1 = Math.min(...media.map(b => b.y));
  const x2 = Math.max(...media.map(b => b.x + b.width));
  const y2 = Math.max(...media.map(b => b.y + b.height));
  return {card: c, media: {x: x1, y: y1, width: x2 - x1, height: y2 - y1}};
}"""

# The profile page card (spec 5c-2, G2): the profile header and the first `rows` rows of the
# post grid, as one clip in page coordinates; null while the grid has no visible item. The
# header comes as Playwright's bounding box (viewport coordinates), so a Playwright-only
# selector such as X's :has-text can find it (live check, 2026-10-22).
PROFILE_PAGE_JS = """([head, items, rows]) => {
  const visible = [...document.querySelectorAll(items)].filter(e => {
    const b = e.getBoundingClientRect();
    return b.width > 0 && b.height > 0;
  });
  if (!head || !visible.length) return null;
  const top = e => Math.round(e.getBoundingClientRect().top + scrollY);
  const kept = [...new Set(visible.map(top))].sort((a, b) => a - b).slice(0, rows);
  const rects = [
    {left: head.x, top: head.y, right: head.x + head.width, bottom: head.y + head.height},
    ...visible.filter(e => kept.includes(top(e))).map(e => e.getBoundingClientRect()),
  ];
  const x1 = Math.min(...rects.map(b => b.left)) + scrollX;
  const y1 = Math.min(...rects.map(b => b.top)) + scrollY;
  const x2 = Math.max(...rects.map(b => b.right)) + scrollX;
  const y2 = Math.max(...rects.map(b => b.bottom)) + scrollY;
  return {x: Math.max(0, x1), y: Math.max(0, y1), width: x2 - x1, height: y2 - y1};
}"""


def media_box(card: dict[str, float] | None, media: dict[str, float] | None) -> MediaBox | None:
    """The media's box as fractions of the card's, or None when it is empty or falls outside."""
    if not card or not media or card["width"] <= 0 or card["height"] <= 0:
        return None
    try:
        return MediaBox(
            x=round((media["x"] - card["x"]) / card["width"], 4),
            y=round((media["y"] - card["y"]) / card["height"], 4),
            w=round(media["width"] / card["width"], 4),
            h=round(media["height"] / card["height"], 4),
        )
    except ValueError:
        return None


class CardRejected(ValueError):
    """The crop is not a usable PNG card."""


def png_size(data: bytes) -> tuple[int, int]:
    """Width and height from the PNG IHDR chunk; a crop cut off before IEND is rejected."""
    if (
        len(data) < 24
        or not data.startswith(PNG_SIGNATURE)
        or data[12:16] != b"IHDR"
        or not data.endswith(PNG_IEND)
    ):
        raise CardRejected("not a png")
    width, height = struct.unpack(">II", data[16:24])
    return width, height


def card_problem(width: int, height: int, size: int) -> str | None:
    if not 0 < size <= MAX_CARD_BYTES:
        return "size"
    if not (
        MIN_CARD_WIDTH <= width <= MAX_CARD_SIDE and MIN_CARD_HEIGHT <= height <= MAX_CARD_SIDE
    ):
        return "dimensions"
    if size / (width * height) < MIN_CARD_BPP:
        return "flat"
    return None


def write_card(data: bytes, artifact_root: Path, location: PurePosixPath) -> CardArtifact:
    """Validate, then write atomically; a retry overwrites the same deterministic name."""
    width, height = png_size(data)
    problem = card_problem(width, height, len(data))
    if problem is not None:
        raise CardRejected(problem)
    destination = artifact_root / location
    part_path = destination.with_name(destination.name + ".part")
    try:
        destination.parent.mkdir(parents=True, exist_ok=True)
        part_path.write_bytes(data)
        os.replace(part_path, destination)
    except BaseException:
        with contextlib.suppress(OSError):
            part_path.unlink(missing_ok=True)
        raise
    return CardArtifact(
        location=location,
        bytes=len(data),
        checksum=f"sha256:{hashlib.sha256(data).hexdigest()}",
        width=width,
        height=height,
    )


def persist_cards(
    snapshot: BrowserSnapshot | None, workflow_id: str, artifact_root: Path
) -> tuple[list[ReportComment], CardArtifact | None, CardArtifact | None]:
    """Report comments, the profile card and the post card of a headless snapshot, on disk."""
    if snapshot is None:
        return [], None, None
    card_dir = PurePosixPath("reports") / workflow_id / "cards"
    counts = {"written": 0, "rejected": 0, "failed": 0}

    def persist(data: bytes | None, name: str) -> CardArtifact | None:
        if data is None:
            return None
        try:
            artifact = write_card(data, artifact_root, card_dir / name)
        except CardRejected:
            counts["rejected"] += 1
            return None
        except OSError:
            counts["failed"] += 1
            return None
        counts["written"] += 1
        return artifact

    comments = [
        ReportComment(
            comment_id=comment.comment_id,
            author=comment.author,
            text=comment.text,
            likes=comment.likes,
            card=persist(comment.card_png, f"comment-{comment.comment_id}.png"),
        )
        for comment in snapshot.comments
    ]
    profile_card = persist(snapshot.profile_card_png, "profile.png")
    post_card = persist(snapshot.post_card_png, "post.png")
    if counts["rejected"] or counts["failed"]:
        logger.warning(
            "tiktok card crops: written=%d rejected=%d failed=%d",
            counts["written"],
            counts["rejected"],
            counts["failed"],
        )
    return comments, profile_card, post_card
