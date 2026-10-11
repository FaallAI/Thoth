"""Audience comments for the video: a port of Scout's multi-source merge.

Sources come in priority order (the main's own post first). Sticker-only and link-first
comments carry nothing for narration and are dropped; the dedupe key is the author plus the
first 60 characters, both lowercased (`dedupeKey` in `scout/lib/comment_engine.ts`).
Ranking is by likes, stable, so ties keep source order.
"""

from __future__ import annotations

import re
from collections.abc import Sequence
from typing import Literal

from thoth_control_plane.acquisition.models import CardArtifact, SourceReport
from thoth_control_plane.assembly.models import MAX_COMMENTS, Comment, MediaRef

STICKER = re.compile(r"^\[\s*sti?c?ker\s*\]$", re.IGNORECASE)
LINK_FIRST = re.compile(r"^https?://", re.IGNORECASE)
Source = Literal["input", "original"]


def card_ref(card: CardArtifact | None) -> MediaRef | None:
    if card is None:
        return None
    return MediaRef(
        location=card.location,
        media_type=card.media_type,
        checksum=card.checksum,
        bytes=card.bytes,
        width=card.width,
        height=card.height,
    )


def merge_comments(sources: Sequence[tuple[Source, SourceReport]]) -> list[Comment]:
    seen: set[str] = set()
    merged: list[Comment] = []
    for source, report in sources:
        for item in report.comments:
            text = item.text.strip()
            if not text or STICKER.match(text) or LINK_FIRST.match(text):
                continue
            key = f"{item.author.lower()}|{text[:60].lower()}"
            if key in seen:
                continue
            seen.add(key)
            merged.append(
                Comment(
                    text=item.text,
                    author=item.author,
                    likes=item.likes,
                    source=source,
                    card=card_ref(item.card),
                )
            )
    merged.sort(key=lambda comment: -comment.likes)
    return merged[:MAX_COMMENTS]
