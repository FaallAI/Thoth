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
    ReportComment,
)

logger = logging.getLogger(__name__)

PNG_SIGNATURE = b"\x89PNG\r\n\x1a\n"
# Scout keeps a crop only when rect.w > 30 and rect.h > 12.
MIN_CARD_WIDTH = 31
MIN_CARD_HEIGHT = 13
MAX_CARD_SIDE = 4_096
# Scout's black-crop guard (scout/lib/crop_guard.ts): a real card runs ~0.09-0.15 bytes per
# pixel, a flat or blank crop ~0.005.
MIN_CARD_BPP = 0.02


class CardRejected(ValueError):
    """The crop is not a usable PNG card."""


def png_size(data: bytes) -> tuple[int, int]:
    """Width and height from the PNG IHDR chunk."""
    if len(data) < 24 or not data.startswith(PNG_SIGNATURE) or data[12:16] != b"IHDR":
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
) -> tuple[list[ReportComment], CardArtifact | None]:
    """Report comments and the profile card for a headless snapshot, with cards on disk."""
    if snapshot is None:
        return [], None
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
    if counts["rejected"] or counts["failed"]:
        logger.warning(
            "tiktok card crops: written=%d rejected=%d failed=%d",
            counts["written"],
            counts["rejected"],
            counts["failed"],
        )
    return comments, profile_card
