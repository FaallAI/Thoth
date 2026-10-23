"""FxEmbed (the FxTwitter API) answers as Thoth's X models (spec 2026-10-23 X via FxEmbed).

X's signed-out pages stopped embedding tweet JSON in October 2026; FxEmbed serves the same post,
its replies, and a profile's media posts as plain JSON. These parsers are pure: the client in
`x_fxembed` fetches, they shape.
"""

from __future__ import annotations

from typing import Any

from thoth_control_plane.acquisition.adapters.threads import _https
from thoth_control_plane.acquisition.adapters.x import (
    MAX_COMMENT_TEXT,
    XPageParse,
    _best_mp4,
    _get,
    _handle,
    display_text,
    post_url,
)
from thoth_control_plane.acquisition.discovery import MAX_CAPTION, _empty
from thoth_control_plane.acquisition.instagram_discovery import rank_videos
from thoth_control_plane.acquisition.models import (
    MAX_COMMENTS,
    DiscoveredPhoto,
    DiscoveredVideo,
    DiscoveryDrops,
    DiscoveryReason,
    DiscoveryResult,
    ReportComment,
)
from thoth_control_plane.acquisition.normalize import _count, numeric_id, published_at_from_epoch

VIDEO_TYPES = ("video", "gif")


def _media(status: dict[str, Any], key: str) -> list[dict[str, Any]]:
    items = _get(status, "media", key)
    return [item for item in items if isinstance(item, dict)] if isinstance(items, list) else []


def fx_videos(status: dict[str, Any]) -> list[str]:
    """The best MP4 of each video, in post order; a video with none is skipped."""
    urls: list[str] = []
    for video in _media(status, "videos"):
        if video.get("type") not in VIDEO_TYPES:
            continue
        formats = video.get("formats") if isinstance(video.get("formats"), list) else []
        variants = [
            {"url": item.get("url"), "content_type": "video/mp4"}
            for item in formats
            if isinstance(item, dict) and item.get("container") == "mp4"
        ]
        url = _best_mp4(variants, "url", "content_type")
        if url is None:
            plain = _https(video.get("url"))
            url = plain if plain and plain.split("?", 1)[0].endswith(".mp4") else None
        if url is not None:
            urls.append(url)
    return urls


def fx_engagement(status: dict[str, Any]) -> dict[str, int]:
    pairs = (
        ("like", status.get("likes")),
        ("comment", status.get("replies")),
        ("share", status.get("reposts")),
        ("play", status.get("views")),
    )
    return {key: count for key, value in pairs if (count := _count(value)) is not None}


def fx_text(status: dict[str, Any]) -> str | None:
    """The post's own words; `text` is FxEmbed's display text (`raw_text` keeps t.co links)."""
    text = status.get("text")
    return display_text(text) if isinstance(text, str) else None


def _comment(reply: dict[str, Any], post_id: str) -> ReportComment | None:
    target = _get(reply, "replying_to", "status")
    if target is not None and target != post_id:
        return None  # a reply to a reply belongs to another thread
    author, text = _handle(_get(reply, "author", "screen_name")), fx_text(reply)
    reply_id = numeric_id(reply.get("id"))
    if author is None or not text or reply_id is None:
        return None
    try:
        return ReportComment(
            comment_id=reply_id,
            author=author,
            text=text[:MAX_COMMENT_TEXT],
            likes=_count(reply.get("likes")) or 0,
        )
    except ValueError:
        return None


def fx_page(
    status: dict[str, Any] | None, replies: list[dict[str, Any]], post_id: str
) -> XPageParse:
    """The post's videos, counters and text, and its direct replies (at most MAX_COMMENTS)."""
    comments: list[ReportComment] = []
    dropped = 0
    for reply in replies:
        if len(comments) == MAX_COMMENTS:
            break
        comment = _comment(reply, post_id) if isinstance(reply, dict) else None
        if comment is None:
            dropped += 1
            continue
        comments.append(comment)
    if status is None:
        return XPageParse(comments=comments, dropped_comments=dropped)
    return XPageParse(
        engagement=fx_engagement(status),
        text=fx_text(status),
        comments=comments,
        dropped_comments=dropped,
        videos=fx_videos(status),
    )


def _published(status: dict[str, Any]) -> str | None:
    seconds = status.get("created_timestamp")
    if isinstance(seconds, bool) or not isinstance(seconds, int):
        return None
    return published_at_from_epoch(seconds)


def _video(status: dict[str, Any], owner: str, post_id: str) -> DiscoveredVideo | None:
    try:
        return DiscoveredVideo(
            post_id=post_id,
            owner_handle=owner,
            canonical_url=post_url(owner, post_id),
            caption=(fx_text(status) or "")[:MAX_CAPTION],
            published_at=_published(status),
            engagement=fx_engagement(status),
        )
    except ValueError:
        return None


def _photo(status: dict[str, Any], owner: str, post_id: str) -> DiscoveredPhoto | None:
    images = [url for item in _media(status, "photos") if (url := _https(item.get("url")))]
    if not images:
        return None
    try:
        return DiscoveredPhoto(
            post_id=post_id,
            owner_handle=owner,
            canonical_url=post_url(owner, post_id),
            caption=(fx_text(status) or "")[:MAX_CAPTION],
            published_at=_published(status),
            image_urls=images[:20],
        )
    except ValueError:
        return None


def fx_profile(payload: object, handle: str, limit: int) -> DiscoveryResult:
    """A profile's own media posts: video posts ranked, photo posts kept for creator photos."""
    results = payload.get("results") if isinstance(payload, dict) else None
    statuses = (
        [item for item in results if isinstance(item, dict)] if isinstance(results, list) else []
    )
    if not statuses:
        return _empty("profile", DiscoveryReason.NO_DATA)
    videos: list[DiscoveredVideo] = []
    photos: list[DiscoveredPhoto] = []
    photo_posts = invalid = 0
    for status in statuses:
        owner = _handle(_get(status, "author", "screen_name"))
        post_id = numeric_id(status.get("id"))
        # Another author's post (a repost's original, a quote) is not the handle's own.
        if (
            owner is None
            or post_id is None
            or owner.lower() != handle.lower()
            or status.get("reposted_by")
        ):
            invalid += 1
            continue
        if not fx_videos(status):
            photo_posts += 1
            if (photo := _photo(status, owner, post_id)) is not None:
                photos.append(photo)
            continue
        video = _video(status, owner, post_id)
        if video is None:
            invalid += 1
            continue
        videos.append(video)
    return DiscoveryResult(
        kind="profile",
        videos=rank_videos(videos)[:limit],
        pages=1,
        exhausted=False,
        drops=DiscoveryDrops(photo_posts=photo_posts, invalid=invalid),
        photos=photos[:limit],
    )
