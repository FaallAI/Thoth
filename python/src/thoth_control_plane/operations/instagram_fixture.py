"""Turn one raw Instagram capture into a sanitized golden fixture and compare the methods.

Operator-run after an authorized capture. Only allowlisted keys survive; handles, `pk`,
codes, and text are pseudonymized, media URLs replaced, timestamps moved to a synthetic
one-hour grid, and counters floored. Output reports counts only; raw values are never
printed, and a fixture with any surviving raw value is not written.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any, Literal

from thoth_control_plane.acquisition.adapters.instagram import (
    InstagramParse,
    canonicalize_instagram_post_url,
    find_instagram_media,
    parse_post,
)
from thoth_control_plane.acquisition.instagram_discovery import (
    TIMELINE_KEY,
    _timeline,
    parse_profile,
)
from thoth_control_plane.operations.threads_fixture import (
    MEDIA_HOST,
    _leaves,
    decide,
    method_roots,
)
from thoth_control_plane.operations.tiktok_comment_fixture import _is_letter, _Pseudonyms
from thoth_control_plane.operations.tiktok_discovery_fixture import (
    SYNTHETIC_EPOCH,
    SYNTHETIC_EPOCH_STEP,
    _floor,
)

CODE = "code_001"
COUNTER_KEYS = ("like_count", "comment_count")
Fixture = tuple[dict[str, Any], dict[str, Any]]


def counts(parsed: InstagramParse | None) -> dict[str, int] | None:
    if parsed is None:
        return None
    return {
        "found": 1,
        "text_chars": len(parsed.post.text),
        "media": len(parsed.media),
        "videos": sum(item.kind == "video" for item in parsed.media),
        "engagement_keys": len(parsed.post.engagement),
        "published_at": int(parsed.post.published_at is not None),
        "comments": len(parsed.comments),
    }


def _int(value: object) -> bool:
    return isinstance(value, int) and not isinstance(value, bool)


class _Sanitizer:
    def __init__(self) -> None:
        self.names = _Pseudonyms()
        self.urls = 0
        self.epochs = 0

    def _url(self, kind: str, ext: str) -> str:
        self.urls += 1
        return f"{MEDIA_HOST}/{kind}/{self.urls}.{ext}"

    def _epoch(self) -> int:
        self.epochs += 1
        return SYNTHETIC_EPOCH + self.epochs * SYNTHETIC_EPOCH_STEP

    def _versions(self, versions: list[Any], kind: str, ext: str) -> list[dict[str, Any]]:
        return [
            {
                "url": self._url(kind, ext),
                **{k: v[k] for k in ("width", "height") if _int(v.get(k))},
            }
            for v in versions
            if isinstance(v, dict) and v.get("url")
        ]

    def _media(self, item: dict[str, Any]) -> dict[str, Any]:
        out: dict[str, Any] = {}
        if _int(item.get("media_type")):
            out["media_type"] = item["media_type"]
        if isinstance(item.get("video_versions"), list):
            out["video_versions"] = self._versions(item["video_versions"], "video", "mp4")
        container = item.get("image_versions2")
        candidates = container.get("candidates") if isinstance(container, dict) else None
        if isinstance(candidates, list):
            out["image_versions2"] = {"candidates": self._versions(candidates, "image", "jpg")}
        return out

    def node(self, node: dict[str, Any], code: str) -> dict[str, Any]:
        user = node.get("user") if isinstance(node.get("user"), dict) else {}
        out: dict[str, Any] = {
            "code": code,
            "pk": self.names.comment_id(node.get("pk")),
            "user": {"username": self.names.handle(user.get("username"))},
        }
        caption = node.get("caption")
        if isinstance(caption, dict) and isinstance(caption.get("text"), str):
            out["caption"] = {"text": self.names.text(caption["text"])}
        if node.get("taken_at") is not None:
            out["taken_at"] = self._epoch()
        for key in COUNTER_KEYS:
            if _int(node.get(key)):
                out[key] = _floor(node[key])
        if isinstance(node.get("like_and_view_counts_disabled"), bool):
            out["like_and_view_counts_disabled"] = node["like_and_view_counts_disabled"]
        out.update(self._media(node))
        carousel = node.get("carousel_media")
        if isinstance(carousel, list):
            out["carousel_media"] = [
                self._media(item) for item in carousel if isinstance(item, dict)
            ]
        return out

    def comment(self, node: dict[str, Any]) -> dict[str, Any]:
        user = node.get("user") if isinstance(node.get("user"), dict) else {}
        out: dict[str, Any] = {
            "pk": self.names.comment_id(node.get("pk")),
            "user": {"username": self.names.handle(user.get("username"))},
        }
        if isinstance(node.get("text"), str):
            out["text"] = self.names.text(node["text"])
        if _int(node.get("comment_like_count")):
            out["comment_like_count"] = _floor(node["comment_like_count"])
        return out


def post_document(post: dict[str, Any], comments: list[dict[str, Any]] | None) -> dict[str, Any]:
    media: dict[str, Any] = {"if_not_gated_logged_out": post}
    if comments is not None:
        media["comments_connection"] = {"edges": [{"node": node} for node in comments]}
    return {"data": {"xig_polaris_media": media}}


def build_post(raw: dict[str, Any]) -> Fixture:
    identity = canonicalize_instagram_post_url(f"https://www.instagram.com/p/{raw['post_id']}/")
    parses = {m: parse_post(method_roots(raw, m), identity) for m in ("request", "headless")}
    method = decide([(counts(parses["request"]), counts(parses["headless"]))])
    found = find_instagram_media(method_roots(raw, method), identity.post_id)
    if found is None:
        raise ValueError("neither method captured the post")
    raw_node, raw_connection = found
    sanitizer = _Sanitizer()
    # The owner is sanitized first, so it is always `user_001`.
    post = sanitizer.node(raw_node, CODE)
    comments = None
    if raw_connection is not None:
        edges = raw_connection.get("edges")
        comments = [
            sanitizer.comment(edge["node"])
            for edge in (edges if isinstance(edges, list) else [])
            if isinstance(edge, dict) and isinstance(edge.get("node"), dict)
        ]
    document = post_document(post, comments)
    replay = canonicalize_instagram_post_url(f"https://www.instagram.com/p/{CODE}/")
    parsed = parse_post([document], replay)
    if parsed is None:
        raise ValueError("the sanitized document no longer parses")
    fixture = {
        "kind": raw["kind"],
        "method": method,
        "counts": {m: counts(p) for m, p in parses.items()},
        "document": document,
        "expected": {
            "text": parsed.post.text,
            "media_kinds": [item.kind for item in parsed.media],
            "engagement": parsed.post.engagement,
            "published_at": parsed.post.published_at,
            "comments": [c.model_dump(mode="json", exclude={"card"}) for c in parsed.comments],
        },
    }
    return fixture, {"node": raw_node, "connection": raw_connection}


def build_profile(raw: dict[str, Any]) -> Fixture:
    found = _timeline(method_roots(raw, "request"), raw["handle"])
    if found is None:
        raise ValueError("the profile capture holds no timeline")
    owner, edges = found
    sanitizer = _Sanitizer()
    alias = sanitizer.names.handle(owner)
    raw_nodes = [
        e["node"] for e in edges if isinstance(e, dict) and isinstance(e.get("node"), dict)
    ]
    nodes = [sanitizer.node(node, f"code_{n:03d}") for n, node in enumerate(raw_nodes, start=1)]
    document = {
        "data": {
            "xig_user_by_username": {
                "username": alias,
                TIMELINE_KEY: {"edges": [{"node": node} for node in nodes]},
            }
        }
    }
    result = parse_profile([document], alias, 30)
    fixture = {
        "kind": "profile",
        "method": "request",
        "handle": alias,
        "counts": {"raw_edges": len(edges), "sanitized_edges": len(nodes)},
        "document": document,
        "expected": {
            "post_ids": [video.post_id for video in result.videos],
            "likes": [video.engagement.get("like", 0) for video in result.videos],
            "drops": result.drops.model_dump(),
        },
    }
    return fixture, {"handle": raw["handle"], "edges": edges}


def decide_share(raw: dict[str, Any]) -> Literal["request", "headless"]:
    """Share links resolve by request only when the request itself lands on a post."""
    return "request" if raw["request"].get("lands_on_post") is True else "headless"


def build_share(raw: dict[str, Any]) -> Fixture:
    results = {
        m: {"status": raw[m]["status"], "lands_on_post": raw[m]["lands_on_post"]}
        for m in ("request", "headless")
    }
    return {"kind": "share", "method": decide_share(raw), "results": results}, {}


def build(raw: dict[str, Any]) -> Fixture:
    if raw["kind"] == "share":
        return build_share(raw)
    if raw["kind"] == "profile":
        return build_profile(raw)
    return build_post(raw)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--raw", type=Path, required=True)
    parser.add_argument("--out", type=Path, required=True)
    args = parser.parse_args(argv)
    raw = json.loads(args.raw.read_text(encoding="utf-8"))
    fixture, scope = build(raw)
    # Compare raw string leaves with fixture string leaves, not JSON text: escaping in the
    # JSON text would hide a surviving value that contains a quote or a newline. A raw leaf
    # with no letter or digit (an emoji-only comment) is kept by the pseudonymizer by design.
    text = "\n".join(sorted(_leaves(fixture)))
    leaks = sum(leaf in text for leaf in _leaves(scope) if any(map(_is_letter, leaf)))
    print(
        json.dumps(
            {
                "kind": fixture["kind"],
                "method": fixture["method"],
                "counts": fixture.get("counts"),
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
