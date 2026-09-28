"""SSRF-safe Threads URL identity and pure parsing of Threads post documents.

The documents are either the page's embedded `application/json` scripts (request method)
or captured GraphQL bodies (headless method); both nest the same post node, found by its
`code`. Nothing here performs I/O.
"""

from __future__ import annotations

import json
import re
from collections.abc import Iterable, Iterator
from typing import Any
from urllib.parse import urlsplit

from pydantic import HttpUrl

from thoth_control_plane.acquisition.models import (
    MAX_POST_TEXT,
    ResolvedMedia,
    SourcePost,
)
from thoth_control_plane.acquisition.normalize import _count, _pick, published_at_from_epoch
from thoth_control_plane.acquisition.platforms import PYTHON_PLATFORM_HOSTS, bare_host
from thoth_control_plane.domain.models import StrictModel

CANONICAL_BASE = "https://www.threads.com"
POST_PATH = re.compile(r"^/@(?P<owner>[A-Za-z0-9._]{1,64})/post/(?P<code>[A-Za-z0-9_-]{1,64})/?$")
HANDLE = re.compile(r"[A-Za-z0-9._]{1,64}")
SHARE_PATH = re.compile(r"^/share/(?P<token>[A-Za-z0-9_-]{1,64})/?$")
ENGAGEMENT_KEYS = {
    "like": ("like_count",),
    "comment": ("direct_reply_count",),
    "repost": ("repost_count",),
    "quote": ("quote_count",),
    "share": ("reshare_count",),
}


class ThreadsUrlError(ValueError):
    """Raised when a URL is not a safe, supported public Threads post URL."""


class ThreadsPostIdentity(StrictModel):
    canonical_url: HttpUrl
    post_id: str
    owner_handle: str


class ThreadsParse(StrictModel):
    post: SourcePost
    media: list[ResolvedMedia]


def _match_safe_path(url: str, pattern: re.Pattern[str]) -> re.Match[str]:
    """Match `pattern` against the path of a safe https Threads URL, or raise."""
    try:
        parsed = urlsplit(url)
        host = (parsed.hostname or "").lower()
        port = parsed.port
    except ValueError:
        # The bare ValueError embeds the raw offending substring; never chain it.
        raise ThreadsUrlError("invalid_source_url") from None
    match = pattern.fullmatch(parsed.path)
    if (
        parsed.scheme != "https"
        or bare_host(host) not in PYTHON_PLATFORM_HOSTS["threads"]
        or parsed.username is not None
        or parsed.password is not None
        or port not in {None, 443}
        or match is None
    ):
        raise ThreadsUrlError("invalid_source_url")
    return match


def canonicalize_threads_post_url(url: str) -> ThreadsPostIdentity:
    """Reduce any accepted Threads post URL (query, fragment, slash, host alias) to its identity."""
    match = _match_safe_path(url, POST_PATH)
    owner, code = match.group("owner"), match.group("code")
    return ThreadsPostIdentity(
        canonical_url=f"{CANONICAL_BASE}/@{owner}/post/{code}", post_id=code, owner_handle=owner
    )


def canonical_threads_share_url(url: str) -> str:
    """Reduce a Threads share link to its token URL. A share link names no post: only a
    browser following its client-side redirect learns the post identity."""
    token = _match_safe_path(url, SHARE_PATH).group("token")
    return f"{CANONICAL_BASE}/share/{token}/"


def json_roots(texts: Iterable[str]) -> list[object]:
    roots: list[object] = []
    for text in texts:
        try:
            roots.append(json.loads(text))
        except ValueError:
            continue
    return roots


def _walk(value: object) -> Iterator[dict[str, Any]]:
    stack = [value]
    while stack:
        current = stack.pop()
        if isinstance(current, dict):
            yield current
            stack.extend(reversed(list(current.values())))
        elif isinstance(current, list):
            stack.extend(reversed(current))


def find_post_node(roots: Iterable[object], code: str) -> dict[str, Any] | None:
    for root in roots:
        for node in _walk(root):
            if node.get("code") == code and isinstance(node.get("user"), dict):
                return node
    return None


def _https(value: object) -> str | None:
    return value if isinstance(value, str) and value.startswith("https://") else None


def _video_url(item: dict[str, Any]) -> str | None:
    versions = item.get("video_versions")
    if isinstance(versions, list) and versions and isinstance(versions[0], dict):
        return _https(versions[0].get("url"))
    return None


def _largest_image_url(item: dict[str, Any]) -> str | None:
    container = item.get("image_versions2")
    candidates = container.get("candidates") if isinstance(container, dict) else None
    best: tuple[int, str] | None = None
    for candidate in candidates if isinstance(candidates, list) else []:
        if not isinstance(candidate, dict) or (url := _https(candidate.get("url"))) is None:
            continue
        area = (_count(candidate.get("width")) or 0) * (_count(candidate.get("height")) or 0)
        if best is None or area > best[0]:
            best = (area, url)
    return best[1] if best else None


def _media_of(node: dict[str, Any]) -> list[ResolvedMedia]:
    carousel = node.get("carousel_media")
    items = carousel if isinstance(carousel, list) and carousel else [node]
    media: list[ResolvedMedia] = []
    for item in items:
        if not isinstance(item, dict):
            continue
        if (video := _video_url(item)) is not None:
            media.append(ResolvedMedia(kind="video", ephemeral_url=video))
        elif (image := _largest_image_url(item)) is not None:
            media.append(ResolvedMedia(kind="image", ephemeral_url=image, media_type=None))
    return media


def parse_documents(roots: Iterable[object], identity: ThreadsPostIdentity) -> ThreadsParse | None:
    """Parse the post named by `identity`; None when no document holds it."""
    node = find_post_node(roots, identity.post_id)
    if node is None:
        return None
    caption = node.get("caption")
    text = caption.get("text") if isinstance(caption, dict) else None
    info = node.get("text_post_app_info")
    counters = {**node, **info} if isinstance(info, dict) else node
    # The post's author wins over the URL's @owner, which a pasted link may get wrong.
    username = node["user"].get("username")
    owner = username if isinstance(username, str) and HANDLE.fullmatch(username) else None
    engagement = {
        key: value
        for key, names in ENGAGEMENT_KEYS.items()
        if (value := _pick(counters, names)) is not None
    }
    return ThreadsParse(
        post=SourcePost(
            post_id=identity.post_id,
            owner_handle=owner or identity.owner_handle,
            text=text[:MAX_POST_TEXT] if isinstance(text, str) else "",
            published_at=published_at_from_epoch(node.get("taken_at")),
            engagement=engagement,
        ),
        media=_media_of(node),
    )
