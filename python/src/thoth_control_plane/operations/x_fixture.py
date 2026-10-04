"""Turn one raw X capture into a sanitized golden fixture.

Operator-run after an authorized capture. Only the keys the parsers read survive. Handles,
ids, and text are pseudonymized; media URLs are replaced, keeping their `<w>x<h>` segment;
timestamps move to a synthetic one-hour grid; counters are floored and kept as numbers.
Output reports counts only; raw values are never printed, and a fixture with any surviving
raw value is not written.
"""

from __future__ import annotations

import argparse
import json
import sys
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from thoth_control_plane.acquisition.adapters.seroval import decode_scripts
from thoth_control_plane.acquisition.adapters.x import (
    SIZE,
    VIDEO_TYPES,
    XPostIdentity,
    _get,
    author_of,
    page_tweets,
    parse_page,
    parse_syndication,
    with_page,
)
from thoth_control_plane.acquisition.normalize import _count
from thoth_control_plane.acquisition.x_discovery import parse_profile
from thoth_control_plane.operations.threads_fixture import MEDIA_HOST, _leaves, leak_count
from thoth_control_plane.operations.tiktok_comment_fixture import _Pseudonyms
from thoth_control_plane.operations.tiktok_discovery_fixture import (
    SYNTHETIC_EPOCH,
    SYNTHETIC_EPOCH_STEP,
    _floor,
)

# Values the fixture keeps verbatim: type names, not identifying tokens.
ENUMS = frozenset(
    {
        "Tweet",
        "TweetTombstone",
        "photo",
        "video",
        "animated_gif",
        "video/mp4",
        "application/x-mpegURL",
    }
)
Fixture = tuple[dict[str, Any], dict[str, Any]]


def _without_enums(value: Any) -> Any:
    """The raw scope for the leak check, minus the enum strings the fixture keeps."""
    if isinstance(value, dict):
        return {key: _without_enums(item) for key, item in value.items()}
    if isinstance(value, list):
        return [_without_enums(item) for item in value]
    return None if isinstance(value, str) and value in ENUMS else value


class _Sanitizer:
    def __init__(self) -> None:
        self.names = _Pseudonyms()
        self.urls = 0
        self.epochs = 0

    def url(self, kind: str, original: object, extension: str) -> str:
        self.urls += 1
        size = SIZE.search(original) if isinstance(original, str) else None
        segment = f"/{size.group(1)}x{size.group(2)}" if size else ""
        return f"{MEDIA_HOST}/{kind}/{self.urls}{segment}/m.{extension}"

    def epoch(self) -> int:
        self.epochs += 1
        return SYNTHETIC_EPOCH + self.epochs * SYNTHETIC_EPOCH_STEP

    def counter(self, value: object) -> int | None:
        count = _count(value)
        return None if count is None else _floor(count)

    def syndication(self, data: dict[str, Any], alias: str | None) -> dict[str, Any]:
        out: dict[str, Any] = {
            "__typename": data.get("__typename"),
            "id_str": alias,
            "user": {"screen_name": self.names.handle(_get(data, "user", "screen_name"))},
        }
        if isinstance(data.get("text"), str):
            out["text"] = self.names.text(data["text"])
        span = data.get("display_text_range")
        if isinstance(span, list):
            out["display_text_range"] = span
        if data.get("created_at") is not None:
            moment = datetime.fromtimestamp(self.epoch(), tz=UTC)
            out["created_at"] = moment.strftime("%Y-%m-%dT%H:%M:%S.000Z")
        for key in ("favorite_count", "conversation_count"):
            if (count := self.counter(data.get(key))) is not None:
                out[key] = count
        details = data.get("mediaDetails")
        if isinstance(details, list):
            out["mediaDetails"] = [self._detail(item) for item in details if isinstance(item, dict)]
        variants = _get(data, "video", "variants")
        if isinstance(variants, list):
            out["video"] = {
                "variants": [
                    {"type": v.get("type"), "src": self.url("video", v.get("src"), "mp4")}
                    for v in variants
                    if isinstance(v, dict)
                ]
            }
        if isinstance(data.get("note_tweet"), dict):
            out["note_tweet"] = {"id": "note"}
        return out

    def _detail(self, item: dict[str, Any]) -> dict[str, Any]:
        out: dict[str, Any] = {"type": item.get("type")}
        if item.get("type") == "photo":
            out["media_url_https"] = self.url("image", item.get("media_url_https"), "jpg")
        return out

    def tweet(self, tweet: dict[str, Any]) -> dict[str, Any]:
        screen_name = _get(tweet, "core", "user_results", "result", "core", "screen_name")
        out: dict[str, Any] = {
            "__typename": "Tweet",
            "rest_id": self.names.comment_id(tweet.get("rest_id")),
            "core": {
                "user_results": {
                    "result": {"core": {"screen_name": self.names.handle(screen_name)}}
                }
            },
        }
        details: dict[str, Any] = {}
        text = _get(tweet, "details", "full_text")
        if isinstance(text, str):
            details["full_text"] = self.names.text(text)
        if _get(tweet, "details", "created_at_ms") is not None:
            details["created_at_ms"] = self.epoch() * 1000
        out["details"] = details
        note = _get(tweet, "note_tweet", "note_tweet_results", "result", "text")
        if isinstance(note, str):
            out["note_tweet"] = {"note_tweet_results": {"result": {"text": self.names.text(note)}}}
        counts = {
            key: count
            for key in ("favorite_count", "reply_count", "retweet_count")
            if (count := self.counter(_get(tweet, "counts", key))) is not None
        }
        out["counts"] = counts
        if (views := self.counter(_get(tweet, "views", "count"))) is not None:
            out["views"] = {"count": views}
        reply_to = _get(tweet, "reply_to_results", "rest_id")
        if reply_to is not None:
            out["reply_to_results"] = {"rest_id": self.names.comment_id(reply_to)}
        entities = tweet.get("media_entities2")
        if isinstance(entities, list):
            out["media_entities2"] = [self._entity(e) for e in entities if isinstance(e, dict)]
        if isinstance(tweet.get("retweeted_status_results"), dict):
            out["retweeted_status_results"] = {"result": {}}
        return out

    def _entity(self, entity: dict[str, Any]) -> dict[str, Any]:
        out: dict[str, Any] = {"type": entity.get("type")}
        variants = _get(entity, "video_info", "variants")
        if entity.get("type") in VIDEO_TYPES and isinstance(variants, list):
            out["video_info"] = {
                "variants": [
                    {
                        "content_type": v.get("content_type"),
                        "url": self.url("video", v.get("url"), "mp4"),
                    }
                    for v in variants
                    if isinstance(v, dict)
                ]
            }
        return out


def build_post(raw: dict[str, Any]) -> Fixture:
    identity = XPostIdentity(post_id=raw["post_id"])
    data = raw["syndication"]["data"]
    roots = decode_scripts((raw.get("page") or {}).get("html", ""))
    tweets = page_tweets(roots)
    page = parse_page(roots, identity)
    parsed = parse_syndication(data, identity, page.videos)
    if parsed is None:
        raise ValueError("the syndication capture holds no tweet")
    sanitizer = _Sanitizer()
    # The post id is pseudonymized first, so syndication and page agree on it.
    alias = sanitizer.names.comment_id(raw["post_id"])
    document = {
        "syndication": sanitizer.syndication(data, alias),
        "page": {"tweets": [sanitizer.tweet(tweet) for tweet in tweets]},
    }
    replay = XPostIdentity(post_id=alias)
    replay_page = parse_page([document["page"]], replay)
    replay_parse = parse_syndication(document["syndication"], replay, replay_page.videos)
    if replay_parse is None:
        raise ValueError("the sanitized document no longer parses")
    merged = with_page(replay_parse, replay_page)
    fixture = {
        "kind": raw["kind"],
        "method": "request",
        "post_id": alias,
        "counts": {
            "media": len(parsed.media),
            "videos": sum(item.kind == "video" for item in parsed.media),
            "long_text": parsed.long_text,
            "decoded_tweets": len(tweets),
            "replies": len(page.comments),
            "dropped_replies": page.dropped_comments,
            "page_engagement_keys": sorted(page.engagement),
        },
        "document": document,
        "expected": {
            "owner_handle": merged.post.owner_handle,
            "text": merged.post.text,
            "media_kinds": [item.kind for item in merged.media],
            "engagement": merged.post.engagement,
            "published_at": merged.post.published_at,
            "comments": [c.model_dump(mode="json", exclude={"card"}) for c in replay_page.comments],
        },
    }
    return fixture, {"syndication": data, "tweets": tweets}


def build_profile(raw: dict[str, Any]) -> Fixture:
    tweets = page_tweets(decode_scripts(raw["page"]["html"]))
    if not tweets:
        raise ValueError("the profile capture holds no timeline")
    sanitizer = _Sanitizer()
    # The page's spelling of the handle, so the pseudonym matches the tweets' authors.
    spelled = next(
        (a for t in tweets if (a := author_of(t)) and a.lower() == raw["handle"].lower()),
        raw["handle"],
    )
    alias = sanitizer.names.handle(spelled)
    document = {"timeline": [sanitizer.tweet(tweet) for tweet in tweets]}
    result = parse_profile([document], alias, 30)
    fixture = {
        "kind": "profile",
        "method": "request",
        "handle": alias,
        "counts": {"decoded_tweets": len(tweets), "videos": len(result.videos)},
        "document": document,
        "expected": {
            "post_ids": [video.post_id for video in result.videos],
            "drops": result.drops.model_dump(),
        },
    }
    return fixture, {"handle": raw["handle"], "tweets": tweets}


def build(raw: dict[str, Any]) -> Fixture:
    return build_profile(raw) if raw["kind"] == "profile" else build_post(raw)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--raw", type=Path, required=True)
    parser.add_argument("--out", type=Path, required=True)
    args = parser.parse_args(argv)
    raw = json.loads(args.raw.read_text(encoding="utf-8"))
    fixture, scope = build(raw)
    # Compare raw string leaves with fixture string leaves, not JSON text: escaping in the
    # JSON text would hide a surviving value that contains a quote or a newline.
    leaks = leak_count(_without_enums(scope), "\n".join(sorted(_leaves(fixture))))
    print(
        json.dumps(
            {
                "kind": fixture["kind"],
                "method": fixture["method"],
                "counts": fixture["counts"],
                "leaks": leaks,
            }
        )
    )
    if leaks:
        return 1
    text = json.dumps(fixture, indent=2, ensure_ascii=False) + "\n"
    args.out.write_bytes(text.encode("utf-8"))
    return 0


if __name__ == "__main__":
    sys.exit(main())
