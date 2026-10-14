"""Footage text gates, ported from Scout's build_footage.ts and footage_queries.ts.

None of them touches media. The regexes are Scout's verbatim (tests read Scout's source).
"""

from __future__ import annotations

import re
from collections.abc import Iterable
from dataclasses import dataclass

from thoth_control_plane.acquisition.models import DiscoveredVideo
from thoth_control_plane.footage.models import RejectReason

# Reaction/repost content = someone reacting to other footage, not b-roll (Scout).
REACTION_RE = re.compile(
    r"\b(reaction|reaksi|bereaksi|ngereact|nge-?react|react(?:ing|s|ed)?|reupload|nonton bareng)\b",
    re.IGNORECASE,
)
SPAM_LEAD = re.compile(r"^https?:\/\/")
SPAM_DOMAINS = re.compile(
    r"vidku\.|t\.me\/|bit\.ly|tinyurl|cutt\.ly|\.fun\b|\.xyz\b", re.IGNORECASE
)
VIDEO_IDS = (
    re.compile(r"/video/(\d{6,})"),
    re.compile(r"[?&]v=([\w-]{6,})"),
    re.compile(r"youtu\.be/([\w-]+)"),
    re.compile(r"/(?:reel|reels|p|tv)/([\w-]+)"),
)
NON_WORD = re.compile(r"[^a-z0-9 ]+")
MIN_SECONDS = 3.0
MAX_SECONDS = 900.0


def norm(text: str) -> str:
    return " ".join(NON_WORD.sub(" ", (text or "").lower()).split())


def video_id(url: str) -> str:
    for pattern in VIDEO_IDS:
        match = pattern.search(url or "")
        if match:
            return match.group(1)
    return ""


def compose_query(obj: str, subject: str) -> str:
    """Scout's composeQuery: append the subject unless the object already names it."""
    if not subject:
        return obj
    lowered = (obj or "").lower()
    if any(len(token) >= 3 and token in lowered for token in subject.lower().split()):
        return obj
    return f"{obj} {subject}"


def looks_spam(text: str) -> bool:
    lowered = (text or "").lower().strip()
    return bool(SPAM_LEAD.search(lowered) or SPAM_DOMAINS.search(lowered))


def looks_reaction(text: str) -> bool:
    return bool(REACTION_RE.search(text or ""))


@dataclass(frozen=True)
class MainIdentity:
    urls: frozenset[str]
    video_id: str
    caption: str

    @classmethod
    def of(cls, url: str, other_urls: Iterable[str], text: str) -> MainIdentity:
        # Scout: mainCap = norm(`${title} ${description}`), title being the first 120 characters.
        return cls(
            urls=frozenset([url, *other_urls]),
            video_id=video_id(url),
            caption=norm(f"{text[:120]} {text}"),
        )


def same_as_main(main: MainIdentity, url: str, caption: str) -> bool:
    if url in main.urls:
        return True
    candidate = video_id(url)
    if candidate and main.video_id and candidate == main.video_id:
        return True
    text = norm(caption)
    return bool(
        text
        and len(text) > 20
        and main.caption
        and (text in main.caption or main.caption[:80] in text)
    )


def text_gate(
    url: str, video: DiscoveredVideo, main: MainIdentity, aggregators: frozenset[str]
) -> RejectReason | None:
    """Spec F5 steps 1 and 3-6 in order; the story gate runs apart (it needs embeddings)."""
    if same_as_main(main, url, video.caption):
        return "main"
    if video.owner_handle.lower() in aggregators:
        return "aggregator"
    if looks_spam(video.caption):
        return "spam"
    if looks_reaction(video.caption):
        return "reaction_text"
    duration = video.duration_seconds
    if duration is not None and not MIN_SECONDS <= duration <= MAX_SECONDS:
        return "duration"
    return None
