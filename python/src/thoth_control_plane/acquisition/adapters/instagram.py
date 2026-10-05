"""SSRF-safe Instagram URL identity and pure parsing of anonymous Instagram page JSON.

An anonymous post page embeds `application/json` scripts; the post is the
`xig_polaris_media.if_not_gated_logged_out` node whose `code` matches, and the first
comment page is its `comments_connection`. Nothing here performs I/O.
"""

from __future__ import annotations

import re
from collections.abc import Iterable
from typing import Any

from pydantic import HttpUrl

from thoth_control_plane.acquisition.adapters.threads import (
    _match_safe_path,
    _walk,
    _widest,
)
from thoth_control_plane.acquisition.adapters.threads import (
    _media_of as _threads_media_of,
)
from thoth_control_plane.acquisition.models import (
    MAX_COMMENTS,
    MAX_MEDIA_ITEMS,
    MAX_POST_TEXT,
    ReportComment,
    ResolvedMedia,
    SourcePost,
)
from thoth_control_plane.acquisition.normalize import (
    _count,
    _pick,
    numeric_id,
    published_at_from_epoch,
)
from thoth_control_plane.domain.models import StrictModel

CANONICAL_BASE = "https://www.instagram.com"
CODE = re.compile(r"[A-Za-z0-9_-]{1,64}")
# An optional `/<user>/` prefix is accepted, except `share/`, which begins a share link.
POST_PATH = re.compile(
    r"^/(?:(?!share/)[A-Za-z0-9._]{1,64}/)?(?:p|reels?|tv)/(?P<code>[A-Za-z0-9_-]{1,64})/?$"
)
SHARE_PATH = re.compile(r"^/share/(?P<kind>(?:reel|p)/)?(?P<token>[A-Za-z0-9_-]{1,64})/?$")
HANDLE = re.compile(r"[A-Za-z0-9._]{1,64}")
MEDIA_KEY = "xig_polaris_media"
ENGAGEMENT_KEYS = {
    "like": ("like_count",),
    "comment": ("comment_count",),
    # Absent from anonymous pages; a logged-in page carries a play count.
    "play": ("play_count", "ig_play_count", "view_count"),
}


class InstagramUrlError(ValueError):
    """Raised when a URL is not a safe, supported public Instagram post or share URL."""


class InstagramPostIdentity(StrictModel):
    canonical_url: HttpUrl
    post_id: str


class InstagramParse(StrictModel):
    post: SourcePost
    media: list[ResolvedMedia]
    comments: list[ReportComment]
    dropped_comments: int = 0


def canonicalize_instagram_post_url(url: str) -> InstagramPostIdentity:
    """Reduce any accepted Instagram post URL to `https://www.instagram.com/p/<code>/`."""
    code = _match_safe_path(url, POST_PATH, "instagram", InstagramUrlError).group("code")
    return InstagramPostIdentity(canonical_url=f"{CANONICAL_BASE}/p/{code}/", post_id=code)


def canonical_instagram_share_url(url: str) -> str:
    """Reduce an Instagram share link to its token URL; only following it names the post."""
    match = _match_safe_path(url, SHARE_PATH, "instagram", InstagramUrlError)
    return f"{CANONICAL_BASE}/share/{match.group('kind') or ''}{match.group('token')}/"


def find_instagram_media(
    roots: Iterable[object], code: str
) -> tuple[dict[str, Any], dict[str, Any] | None] | None:
    """The post node for `code` and its comment connection (its sibling, else the first seen)."""
    found: tuple[dict[str, Any], dict[str, Any] | None] | None = None
    loose: dict[str, Any] | None = None
    for root in roots:
        for node in _walk(root):
            media = node.get(MEDIA_KEY)
            if not isinstance(media, dict):
                continue
            connection = media.get("comments_connection")
            connection = connection if isinstance(connection, dict) else None
            post = media.get("if_not_gated_logged_out")
            # Only a holder without a post is loose; another post's comments are never borrowed.
            if loose is None and not isinstance(post, dict):
                loose = connection
            if (
                found is None
                and isinstance(post, dict)
                and post.get("code") == code
                and isinstance(post.get("user"), dict)
            ):
                found = (post, connection)
    if found is None:
        return None
    return found[0], found[1] or loose


def login_required(roots: Iterable[object]) -> bool:
    """Instagram answers a logged-out API or page request with a root `require_login` flag."""
    return any(isinstance(root, dict) and root.get("require_login") is True for root in roots)


def engagement_of(node: dict[str, Any]) -> dict[str, int]:
    if node.get("like_and_view_counts_disabled") is True:
        return {}
    return {
        key: value
        for key, names in ENGAGEMENT_KEYS.items()
        if (value := _pick(node, names)) is not None
    }


def _media_of(node: dict[str, Any]) -> list[ResolvedMedia]:
    # Unlike Threads, the video versions arrive unordered: take the widest.
    media = _threads_media_of(node, lambda item: _widest(item.get("video_versions")))
    return media[:MAX_MEDIA_ITEMS]


def _comment(node: object) -> ReportComment | None:
    if not isinstance(node, dict) or not isinstance(node.get("user"), dict):
        return None
    text = node.get("text")
    pk = numeric_id(node.get("pk"))
    if not isinstance(text, str) or not text.strip() or pk is None:
        return None
    try:
        return ReportComment(
            comment_id=pk,
            author=node["user"].get("username"),
            text=text,
            likes=_count(node.get("comment_like_count")) or 0,
        )
    except ValueError:
        return None


def _comments(connection: dict[str, Any] | None) -> tuple[list[ReportComment], int]:
    edges = connection.get("edges") if connection is not None else None
    comments: list[ReportComment] = []
    seen: set[str] = set()
    dropped = 0
    for edge in edges if isinstance(edges, list) else []:
        if len(comments) == MAX_COMMENTS:
            break
        comment = _comment(edge.get("node") if isinstance(edge, dict) else None)
        if comment is None or comment.comment_id in seen:
            dropped += 1
            continue
        seen.add(comment.comment_id)
        comments.append(comment)
    return comments, dropped


def parse_post(roots: Iterable[object], identity: InstagramPostIdentity) -> InstagramParse | None:
    """Parse the post named by `identity`; None when no document holds it with a valid owner."""
    found = find_instagram_media(roots, identity.post_id)
    if found is None:
        return None
    node, connection = found
    username = node["user"].get("username")
    if not isinstance(username, str) or HANDLE.fullmatch(username) is None:
        return None
    caption = node.get("caption")
    text = caption.get("text") if isinstance(caption, dict) else None
    comments, dropped = _comments(connection)
    return InstagramParse(
        post=SourcePost(
            post_id=identity.post_id,
            owner_handle=username,
            text=text[:MAX_POST_TEXT] if isinstance(text, str) else "",
            published_at=published_at_from_epoch(node.get("taken_at")),
            engagement=engagement_of(node),
        ),
        media=_media_of(node),
        comments=comments,
        dropped_comments=dropped,
    )
