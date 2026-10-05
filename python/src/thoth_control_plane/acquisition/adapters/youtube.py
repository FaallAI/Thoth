"""SSRF-safe YouTube URL identity and pure parsing of yt-dlp's extracted info.

yt-dlp (a library, run by the service) answers metadata, formats, and first-page comments;
everything here only reads its dicts. The format choice takes the highest of 1080p, 720p,
and 480p whose MP4 video and M4A audio fit the download cap. Nothing here performs I/O.
"""

from __future__ import annotations

import re
from collections.abc import Iterable, Sequence
from dataclasses import dataclass
from typing import Any
from urllib.parse import parse_qs, urlsplit

from pydantic import HttpUrl

from thoth_control_plane.acquisition.adapters.threads import _match_safe_path
from thoth_control_plane.acquisition.models import (
    MAX_COMMENTS,
    MAX_POST_TEXT,
    ReportComment,
    SourcePost,
)
from thoth_control_plane.acquisition.normalize import _count, published_at_from_epoch
from thoth_control_plane.acquisition.platforms import bare_host
from thoth_control_plane.domain.models import StrictModel

CANONICAL_BASE = "https://www.youtube.com"
VIDEO_ID = re.compile(r"[A-Za-z0-9_-]{11}")
ANY_PATH = re.compile(r"/.*")
WATCH_PATH = re.compile(r"/watch/?")
ID_PATH = re.compile(r"/(?:shorts|embed|live)/(?P<id>[A-Za-z0-9_-]{11})/?")
SHORT_LINK_PATH = re.compile(r"/(?P<id>[A-Za-z0-9_-]{11})/?")
HANDLE = re.compile(r"[A-Za-z0-9._-]{1,64}")
CHANNEL_ID = re.compile(r"UC[A-Za-z0-9_-]{22}")
MAX_COMMENT_TEXT = 2_000
UNFINISHED = ("is_live", "is_upcoming")
TARGET_HEIGHTS = (1080, 720, 480)
MAX_DOWNLOAD_BYTES = 450 * 1024 * 1024


class YouTubeUrlError(ValueError):
    """Raised when a URL is not a safe, supported public YouTube video URL."""


class YouTubeIdentity(StrictModel):
    canonical_url: HttpUrl
    video_id: str


class YouTubeParse(StrictModel):
    post: SourcePost
    comments: list[ReportComment]
    dropped_comments: int = 0
    duration_seconds: float | None = None
    # The owner's channel page, for the profile card: by channel id, else by handle.
    channel_url: str


@dataclass(frozen=True)
class FormatChoice:
    video_format: str
    audio_format: str
    short_side: int
    estimated_bytes: int


def canonicalize_youtube_url(url: str) -> YouTubeIdentity:
    """Reduce a watch, Shorts, embed, live, or youtu.be URL to `/watch?v=<id>`."""
    _match_safe_path(url, ANY_PATH, "youtube", YouTubeUrlError)
    parts = urlsplit(url)
    found: str | None = None
    if bare_host(parts.hostname or "") == "youtu.be":
        match = SHORT_LINK_PATH.fullmatch(parts.path)
        found = match.group("id") if match else None
    elif WATCH_PATH.fullmatch(parts.path):
        values = parse_qs(parts.query).get("v", [])
        found = values[0] if len(values) == 1 and VIDEO_ID.fullmatch(values[0]) else None
    else:
        match = ID_PATH.fullmatch(parts.path)
        found = match.group("id") if match else None
    if found is None:
        raise YouTubeUrlError("invalid_source_url")
    return YouTubeIdentity(canonical_url=video_url(found), video_id=found)


def video_url(video_id: str) -> str:
    return f"{CANONICAL_BASE}/watch?v={video_id}"


def _handle(value: object) -> str | None:
    if not isinstance(value, str):
        return None
    handle = value.removeprefix("@")
    return handle if HANDLE.fullmatch(handle) else None


def _comment(node: object) -> ReportComment | None:
    if not isinstance(node, dict) or node.get("parent") != "root":
        return None
    text = node.get("text")
    author = _handle(node.get("author")) or _handle(node.get("author_id"))
    if not isinstance(text, str) or not text.strip() or author is None:
        return None
    try:
        return ReportComment(
            comment_id=str(node.get("id")),
            author=author,
            text=text[:MAX_COMMENT_TEXT],
            likes=_count(node.get("like_count")) or 0,
        )
    except ValueError:
        return None


def _comments(nodes: object) -> tuple[list[ReportComment], int]:
    comments: list[ReportComment] = []
    seen: set[str] = set()
    dropped = 0
    for node in nodes if isinstance(nodes, list) else []:
        if isinstance(node, dict) and node.get("parent") not in (None, "root"):
            continue  # A reply; first-page top-level comments only.
        if len(comments) == MAX_COMMENTS:
            break
        comment = _comment(node)
        if comment is None or comment.comment_id in seen:
            dropped += 1
            continue
        seen.add(comment.comment_id)
        comments.append(comment)
    return comments, dropped


def parse_info(info: object, identity: YouTubeIdentity) -> YouTubeParse | None:
    """Parse yt-dlp's info for the identity's video; None for another id, a live or upcoming
    stream (no final video yet), or no valid owner."""
    if not isinstance(info, dict) or info.get("id") != identity.video_id:
        return None
    if info.get("live_status") in UNFINISHED:
        return None
    owner = _handle(info.get("uploader_id")) or _handle(info.get("channel_id"))
    if owner is None:
        return None
    channel_id = info.get("channel_id")
    channel = (
        f"{CANONICAL_BASE}/channel/{channel_id}"
        if isinstance(channel_id, str) and CHANNEL_ID.fullmatch(channel_id)
        else f"{CANONICAL_BASE}/@{owner}"
    )
    parts = [info.get(key) for key in ("title", "description")]
    text = "\n\n".join(part for part in parts if isinstance(part, str) and part.strip())
    names = (("play", "view_count"), ("like", "like_count"), ("comment", "comment_count"))
    engagement = {
        key: count for key, name in names if (count := _count(info.get(name))) is not None
    }
    duration = info.get("duration")
    comments, dropped = _comments(info.get("comments"))
    return YouTubeParse(
        post=SourcePost(
            post_id=identity.video_id,
            owner_handle=owner,
            text=text[:MAX_POST_TEXT],
            published_at=published_at_from_epoch(info.get("timestamp")),
            engagement=engagement,
        ),
        comments=comments,
        dropped_comments=dropped,
        duration_seconds=float(duration)
        if isinstance(duration, (int, float)) and not isinstance(duration, bool) and duration >= 0
        else None,
        channel_url=channel,
    )


def _number(value: object) -> float | None:
    if isinstance(value, bool) or not isinstance(value, (int, float)) or value <= 0:
        return None
    return float(value)


def _size(fmt: dict[str, Any], duration: float | None) -> int | None:
    """Declared bytes, else bitrate (kbit/s) x duration."""
    for key in ("filesize", "filesize_approx"):
        if (declared := _number(fmt.get(key))) is not None:
            return int(declared)
    bitrate = _number(fmt.get("tbr"))
    if bitrate is None or duration is None:
        return None
    return int(bitrate * 1000 / 8 * duration)


def _short_side(fmt: dict[str, Any]) -> int | None:
    """The resolution class: 1080 for both 1920x1080 and a vertical 1080x1920 Short."""
    sides = [int(n) for n in (fmt.get("width"), fmt.get("height")) if _number(n) is not None]
    if not sides:
        return None
    return min(sides) if len(sides) == 2 else sides[0]


def _plain_https(fmt: object) -> bool:
    return (
        isinstance(fmt, dict)
        and fmt.get("protocol") == "https"
        and isinstance(fmt.get("format_id"), str)
        and bool(fmt.get("url"))
    )


def select_formats(formats: object, duration: float | None) -> FormatChoice | None:
    """The highest of 1080p, 720p, 480p whose MP4 video plus M4A audio stays under the cap."""
    listed = [f for f in (formats if isinstance(formats, list) else []) if _plain_https(f)]
    audios = [
        f
        for f in listed
        if f.get("vcodec") == "none"
        and f.get("acodec") not in (None, "none")
        and f.get("ext") == "m4a"
        and _size(f, duration) is not None
    ]
    if not audios:
        return None
    audio = max(audios, key=lambda f: _number(f.get("tbr")) or 0.0)
    audio_bytes = _size(audio, duration) or 0
    videos = [
        f
        for f in listed
        if f.get("acodec") == "none"
        and f.get("vcodec") not in (None, "none")
        and f.get("ext") == "mp4"
        and _short_side(f) is not None
        and _size(f, duration) is not None
    ]
    for target in TARGET_HEIGHTS:
        fitting = [f for f in videos if (_short_side(f) or 0) <= target]
        if not fitting:
            continue
        video = max(fitting, key=lambda f: (_short_side(f) or 0, _number(f.get("tbr")) or 0.0))
        total = (_size(video, duration) or 0) + audio_bytes
        if total < MAX_DOWNLOAD_BYTES:
            return FormatChoice(
                video_format=video["format_id"],
                audio_format=audio["format_id"],
                short_side=_short_side(video) or 0,
                estimated_bytes=total,
            )
    return None


def channel_candidates(listings: Iterable[object], limit: int) -> list[str]:
    """Video ids from flat channel listings, the most viewed first, each once."""
    views: dict[str, int] = {}
    for listing in listings:
        entries = listing.get("entries") if isinstance(listing, dict) else None
        for entry in entries if isinstance(entries, list) else []:
            video_id = entry.get("id") if isinstance(entry, dict) else None
            count = _count(entry.get("view_count")) if isinstance(entry, dict) else None
            if isinstance(video_id, str) and VIDEO_ID.fullmatch(video_id) and count is not None:
                views.setdefault(video_id, count)
    ranked: Sequence[str] = sorted(views, key=lambda video_id: -views[video_id])
    return list(ranked[:limit])
