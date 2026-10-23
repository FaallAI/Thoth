"""SSRF-safe X URL identity and pure parsing of X's anonymous data.

The core of a post is the public syndication JSON
(`cdn.syndication.twimg.com/tweet-result`). The page's seroval-decoded data adds the
first-page replies, views, and reposts; it is an enrichment, so nothing missing there is an
error. Nothing here performs I/O.
"""

from __future__ import annotations

import html
import re
from collections.abc import Iterable, Iterator, Sequence
from datetime import UTC, datetime
from typing import Any

from pydantic import Field

from thoth_control_plane.acquisition.adapters.threads import _https, _match_safe_path
from thoth_control_plane.acquisition.models import (
    MAX_COMMENTS,
    MAX_MEDIA_ITEMS,
    MAX_POST_TEXT,
    ReportComment,
    ResolvedMedia,
    SourcePost,
)
from thoth_control_plane.acquisition.normalize import _count, numeric_id, published_at_from_epoch
from thoth_control_plane.domain.models import StrictModel

CANONICAL_BASE = "https://x.com"
POST_PATH = re.compile(
    r"^/(?:[A-Za-z0-9_]{1,15}/status(?:es)?|i/web/status|i/status)/(?P<id>[0-9]{1,19})"
    r"(?:/(?:photo|video)/[1-4])?/?$"
)
HANDLE = re.compile(r"[A-Za-z0-9_]{1,15}")
SIZE = re.compile(r"/(\d{2,5})x(\d{2,5})/")
LEADING_MENTIONS = re.compile(r"^(?:@[A-Za-z0-9_]{1,15}\s+)+")
TRAILING_LINKS = re.compile(r"(?:\s*https://t\.co/[A-Za-z0-9]+)+\s*$")
MAX_COMMENT_TEXT = 2_000
VIDEO_TYPES = ("video", "animated_gif")


class XUrlError(ValueError):
    """Raised when a URL is not a safe, supported public X post URL."""


class XPostIdentity(StrictModel):
    post_id: str


class XParse(StrictModel):
    post: SourcePost
    media: list[ResolvedMedia]
    # A long tweet: the syndication text is cut short; the page's text of the post wins.
    long_text: bool = False


class XPageParse(StrictModel):
    engagement: dict[str, int] = Field(default_factory=dict)
    text: str | None = None
    comments: list[ReportComment] = Field(default_factory=list)
    dropped_comments: int = 0
    videos: list[str] = Field(default_factory=list)


def canonicalize_x_post_url(url: str) -> XPostIdentity:
    """Reduce any accepted X post URL to its numeric id; the author comes from the data."""
    return XPostIdentity(post_id=_match_safe_path(url, POST_PATH, "x", XUrlError).group("id"))


def post_url(handle: str, post_id: str) -> str:
    return f"{CANONICAL_BASE}/{handle}/status/{post_id}"


def _get(node: object, *keys: str) -> object:
    for key in keys:
        if not isinstance(node, dict):
            return None
        node = node.get(key)
    return node


def _handle(value: object) -> str | None:
    return value if isinstance(value, str) and HANDLE.fullmatch(value) else None


def _best_mp4(variants: object, url_key: str, type_key: str) -> str | None:
    """The largest-resolution https MP4; the first wins a tie or when no size is named."""
    best: tuple[int, str] | None = None
    for variant in variants if isinstance(variants, list) else []:
        if not isinstance(variant, dict) or variant.get(type_key) != "video/mp4":
            continue
        url = _https(variant.get(url_key))
        if url is None:
            continue
        size = SIZE.search(url)
        area = int(size.group(1)) * int(size.group(2)) if size else 0
        if best is None or area > best[0]:
            best = (area, url)
    return best[1] if best else None


def _published(value: object) -> str | None:
    if not isinstance(value, str):
        return None
    try:
        moment = datetime.fromisoformat(value)
    except ValueError:
        return None
    if moment.tzinfo is None:
        return None
    return moment.astimezone(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")


def syndication_author(data: object) -> str | None:
    return _handle(_get(data, "user", "screen_name"))


def _syndication_media(data: dict[str, Any], page_videos: Sequence[str]) -> list[ResolvedMedia]:
    details = data.get("mediaDetails")
    listed = details if isinstance(details, list) else []
    items = [item for item in listed if isinstance(item, dict)]
    videos = [item for item in items if item.get("type") in VIDEO_TYPES]
    lone = _best_mp4(_get(data, "video", "variants"), "src", "type") if len(videos) == 1 else None
    media: list[ResolvedMedia] = []
    seen_videos = 0
    for item in items:
        if item.get("type") == "photo":
            url = _https(item.get("media_url_https"))
            if url is not None:
                original = url if "?" in url else f"{url}?name=orig"
                media.append(ResolvedMedia(kind="image", ephemeral_url=original, media_type=None))
        elif item.get("type") in VIDEO_TYPES:
            paged = page_videos[seen_videos] if seen_videos < len(page_videos) else None
            seen_videos += 1
            url = paged or lone
            if url is not None:
                media.append(ResolvedMedia(kind="video", ephemeral_url=url))
    # The enrichment can name more videos than syndication lists (it carries one video's
    # renditions only); none of them may be dropped.
    for url in page_videos[seen_videos:]:
        media.append(ResolvedMedia(kind="video", ephemeral_url=url))
    return media[:MAX_MEDIA_ITEMS]


def parse_syndication(
    data: object, identity: XPostIdentity, page_videos: Sequence[str] = ()
) -> XParse | None:
    """Parse the tweet named by `identity`; None for a tombstone, another id, or a bad author."""
    if not isinstance(data, dict) or data.get("__typename") != "Tweet":
        return None
    if data.get("id_str") != identity.post_id:
        return None
    author = syndication_author(data)
    if author is None:
        return None
    # Tweet text arrives HTML-escaped (`&amp;`); its ranges count the unescaped text.
    text = html.unescape(data["text"]) if isinstance(data.get("text"), str) else ""
    span = data.get("display_text_range")
    if (
        isinstance(span, list)
        and len(span) == 2
        and all(isinstance(i, int) and not isinstance(i, bool) for i in span)
    ):
        # X counts UTF-16 code units (an emoji is two); slicing code points would overrun.
        units = text.encode("utf-16-le")
        text = units[2 * span[0] : 2 * span[1]].decode("utf-16-le", "ignore")
    engagement = {
        key: count
        for key, name in (("like", "favorite_count"), ("comment", "conversation_count"))
        if (count := _count(data.get(name))) is not None
    }
    return XParse(
        post=SourcePost(
            post_id=identity.post_id,
            owner_handle=author,
            text=text[:MAX_POST_TEXT],
            published_at=_published(data.get("created_at")),
            engagement=engagement,
        ),
        media=_syndication_media(data, page_videos),
        long_text=isinstance(data.get("note_tweet"), dict),
    )


def _walk(roots: Iterable[object]) -> Iterator[dict[str, Any]]:
    """Every dict in document order, each once; decoded seroval data can be cyclic."""
    stack: list[object] = list(reversed(list(roots)))
    seen: set[int] = set()
    while stack:
        value = stack.pop()
        if not isinstance(value, (dict, list)) or id(value) in seen:
            continue
        seen.add(id(value))
        if isinstance(value, dict):
            yield value
            stack.extend(reversed(list(value.values())))
        else:
            stack.extend(reversed(value))


def page_tweets(roots: Iterable[object]) -> list[dict[str, Any]]:
    """Each distinct `Tweet` in document order; X repeats a tweet across timeline entries."""
    tweets: list[dict[str, Any]] = []
    seen: set[str] = set()
    for node in _walk(roots):
        rest_id = node.get("rest_id")
        if node.get("__typename") == "Tweet" and isinstance(rest_id, str) and rest_id not in seen:
            seen.add(rest_id)
            tweets.append(node)
    return tweets


def author_of(tweet: dict[str, Any]) -> str | None:
    return _handle(_get(tweet, "core", "user_results", "result", "core", "screen_name"))


def display_text(text: str) -> str:
    """A tweet's own words: no leading reply mentions, no trailing `t.co` links."""
    return TRAILING_LINKS.sub("", LEADING_MENTIONS.sub("", text)).strip()


def tweet_text(tweet: dict[str, Any]) -> str | None:
    """A long tweet's note text, else its full text, without mentions and media links."""
    note = _get(tweet, "note_tweet", "note_tweet_results", "result", "text")
    text = note if isinstance(note, str) else _get(tweet, "details", "full_text")
    return display_text(html.unescape(text)) if isinstance(text, str) else None


def tweet_published(tweet: dict[str, Any]) -> str | None:
    millis = _get(tweet, "details", "created_at_ms")
    if isinstance(millis, bool) or not isinstance(millis, int):
        return None
    return published_at_from_epoch(millis // 1000)


def tweet_engagement(tweet: dict[str, Any]) -> dict[str, int]:
    pairs = (
        ("like", _get(tweet, "counts", "favorite_count")),
        ("comment", _get(tweet, "counts", "reply_count")),
        ("share", _get(tweet, "counts", "retweet_count")),
        ("play", _get(tweet, "views", "count")),
    )
    return {key: count for key, value in pairs if (count := _count(value)) is not None}


def tweet_photos(tweet: dict[str, Any]) -> list[str]:
    """The https URL of each photo entity, in order (spec 5c-2, G4)."""
    entities = tweet.get("media_entities2")
    photos: list[str] = []
    for entity in entities if isinstance(entities, list) else []:
        if isinstance(entity, dict) and entity.get("type") == "photo":
            url = _https(entity.get("media_url_https"))
            if url is not None:
                photos.append(url)
    return photos


def tweet_videos(tweet: dict[str, Any]) -> list[str]:
    """The best MP4 of each video entity, in order."""
    entities = tweet.get("media_entities2")
    videos: list[str] = []
    for entity in entities if isinstance(entities, list) else []:
        if isinstance(entity, dict) and entity.get("type") in VIDEO_TYPES:
            url = _best_mp4(_get(entity, "video_info", "variants"), "url", "content_type")
            if url is not None:
                videos.append(url)
    return videos


def _comment(tweet: dict[str, Any]) -> ReportComment | None:
    author, text = author_of(tweet), tweet_text(tweet)
    rest_id = numeric_id(tweet["rest_id"])
    if author is None or not text or rest_id is None:
        return None
    try:
        return ReportComment(
            comment_id=rest_id,
            author=author,
            text=text[:MAX_COMMENT_TEXT],
            likes=_count(_get(tweet, "counts", "favorite_count")) or 0,
        )
    except ValueError:
        return None


def parse_page(roots: Iterable[object], identity: XPostIdentity) -> XPageParse:
    """Replies to the post and its page-only counters; an empty parse when none are found."""
    tweets = page_tweets(roots)
    post = next((tweet for tweet in tweets if tweet["rest_id"] == identity.post_id), None)
    comments: list[ReportComment] = []
    dropped = 0
    for tweet in tweets:
        if tweet is post or _get(tweet, "reply_to_results", "rest_id") != identity.post_id:
            continue
        if len(comments) == MAX_COMMENTS:
            break
        comment = _comment(tweet)
        if comment is None:
            dropped += 1
            continue
        comments.append(comment)
    if post is None:
        return XPageParse(comments=comments, dropped_comments=dropped)
    return XPageParse(
        engagement=tweet_engagement(post),
        text=tweet_text(post),
        comments=comments,
        dropped_comments=dropped,
        videos=tweet_videos(post),
    )


def with_page(parsed: XParse, page: XPageParse) -> XParse:
    """Add the page's views and reposts; a long tweet takes the page's full text."""
    text = page.text if parsed.long_text and page.text else parsed.post.text
    extra = {key: value for key, value in page.engagement.items() if key in ("play", "share")}
    post = parsed.post.model_copy(
        update={"text": text[:MAX_POST_TEXT], "engagement": {**parsed.post.engagement, **extra}}
    )
    return parsed.model_copy(update={"post": post})
