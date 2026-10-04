"""Turn one raw Threads capture into a sanitized golden fixture and compare the methods.

Operator-run after an authorized capture. Only allowlisted keys survive; handles, codes,
and text are pseudonymized, media URLs replaced, timestamps moved to a synthetic grid, and
counters floored. Output reports counts only; raw values are never printed.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any, Literal

from thoth_control_plane.acquisition.adapters.threads import (
    ThreadsParse,
    canonicalize_threads_post_url,
    find_post_node,
    json_roots,
    parse_documents,
)
from thoth_control_plane.operations.tiktok_comment_fixture import _is_letter, _Pseudonyms
from thoth_control_plane.operations.tiktok_discovery_fixture import (
    MIN_SECRET_LENGTH,
    SYNTHETIC_EPOCH,
    _floor,
)

CODE = "code_001"
COUNT_KEYS = ("found", "text_chars", "media", "videos", "engagement_keys", "published_at")
COUNTER_KEYS = ("like_count",)
INFO_KEYS = ("direct_reply_count", "repost_count", "quote_count", "reshare_count")
MEDIA_HOST = "https://media.example.test"


def counts(parsed: ThreadsParse | None) -> dict[str, int] | None:
    if parsed is None:
        return None
    return {
        "found": 1,
        "text_chars": len(parsed.post.text),
        "media": len(parsed.media),
        "videos": sum(item.kind == "video" for item in parsed.media),
        "engagement_keys": len(parsed.post.engagement),
        "published_at": int(parsed.post.published_at is not None),
    }


def decide(
    pairs: list[tuple[dict[str, int] | None, dict[str, int] | None]],
) -> Literal["request", "headless"]:
    """Request wins only if, on every post, it was not blocked and never counted less."""
    for request, headless in pairs:
        if request is None:
            return "headless"
        if headless is not None and any(request.get(k, 0) < v for k, v in headless.items()):
            return "headless"
    return "request"


def method_roots(raw: dict[str, Any], method: str) -> list[object]:
    capture = raw.get(method) or {}
    if capture.get("status") != "ok":
        return []
    return [*capture.get("xhr_bodies", []), *json_roots(capture.get("script_texts", []))]


class _Sanitizer:
    def __init__(self) -> None:
        self.names = _Pseudonyms()
        self.urls = 0

    def _url(self, kind: str, ext: str) -> str:
        self.urls += 1
        return f"{MEDIA_HOST}/{kind}/{self.urls}.{ext}"

    def _media(self, item: dict[str, Any]) -> dict[str, Any]:
        out: dict[str, Any] = {}
        versions = item.get("video_versions")
        if isinstance(versions, list):
            out["video_versions"] = [
                {"url": self._url("video", "mp4")}
                for v in versions
                if isinstance(v, dict) and v.get("url")
            ]
        container = item.get("image_versions2")
        candidates = container.get("candidates") if isinstance(container, dict) else None
        if isinstance(candidates, list):
            out["image_versions2"] = {
                "candidates": [
                    {
                        "url": self._url("image", "jpg"),
                        **{k: c[k] for k in ("width", "height") if isinstance(c.get(k), int)},
                    }
                    for c in candidates
                    if isinstance(c, dict) and c.get("url")
                ]
            }
        return out

    def node(self, node: dict[str, Any]) -> dict[str, Any]:
        user = node.get("user") if isinstance(node.get("user"), dict) else {}
        out: dict[str, Any] = {
            "code": CODE,
            "user": {"username": self.names.handle(user.get("username"))},
        }
        caption = node.get("caption")
        if isinstance(caption, dict) and isinstance(caption.get("text"), str):
            out["caption"] = {"text": self.names.text(caption["text"])}
        if node.get("taken_at") is not None:
            out["taken_at"] = SYNTHETIC_EPOCH
        for key in COUNTER_KEYS:
            if isinstance(node.get(key), int):
                out[key] = _floor(node[key])
        info = node.get("text_post_app_info")
        if isinstance(info, dict):
            out["text_post_app_info"] = {
                k: _floor(info[k]) for k in INFO_KEYS if isinstance(info.get(k), int)
            }
        out.update(self._media(node))
        carousel = node.get("carousel_media")
        if isinstance(carousel, list):
            out["carousel_media"] = [
                self._media(item) for item in carousel if isinstance(item, dict)
            ]
        return out


def sanitize(raw_node: dict[str, Any]) -> dict[str, Any]:
    """The post node alone, sanitized, under a neutral wrapper the parser walks through."""
    return {"data": {"thread_items": [{"post": _Sanitizer().node(raw_node)}]}}


def _leaves(value: object) -> set[str]:
    if isinstance(value, dict):
        return set().union(*(_leaves(v) for v in value.values())) if value else set()
    if isinstance(value, list):
        return set().union(*(_leaves(v) for v in value)) if value else set()
    return {value} if isinstance(value, str) and len(value) >= MIN_SECRET_LENGTH else set()


def leak_count(raw_node: dict[str, Any], text: str) -> int:
    """Raw leaves that survive in `text`; a leaf with no letter or digit (an emoji-only
    comment) is kept by the pseudonymizer by design and identifies no one."""
    return sum(leaf in text for leaf in _leaves(raw_node) if any(map(_is_letter, leaf)))


def build_fixture(raw: dict[str, Any]) -> dict[str, Any]:
    identity = canonicalize_threads_post_url(
        f"https://www.threads.com/@{raw['owner']}/post/{raw['post_id']}"
    )
    parses = {m: parse_documents(method_roots(raw, m), identity) for m in ("request", "headless")}
    method = decide([(counts(parses["request"]), counts(parses["headless"]))])
    raw_node = find_post_node(method_roots(raw, method), identity.post_id)
    if raw_node is None:
        raise ValueError("neither method captured the post")
    document = sanitize(raw_node)
    # The pseudonymized handle is `user_001`: the sanitizer sees exactly one handle.
    owner = document["data"]["thread_items"][0]["post"]["user"]["username"]
    replay = canonicalize_threads_post_url(f"https://www.threads.com/@{owner}/post/{CODE}")
    parsed = parse_documents([document], replay)
    if parsed is None:
        raise ValueError("the sanitized document no longer parses")
    return {
        "kind": raw["kind"],
        "method": method,
        "identity": {"post_id": CODE, "owner_handle": parsed.post.owner_handle},
        "counts": {m: counts(p) for m, p in parses.items()},
        "document": document,
        "expected": {
            "text": parsed.post.text,
            "media_kinds": [item.kind for item in parsed.media],
            "engagement": parsed.post.engagement,
            "published_at": parsed.post.published_at,
        },
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--raw", type=Path, required=True)
    parser.add_argument("--out", type=Path, required=True)
    args = parser.parse_args(argv)
    raw = json.loads(args.raw.read_text(encoding="utf-8"))
    fixture = build_fixture(raw)
    text = json.dumps(fixture, indent=2, ensure_ascii=False) + "\n"
    raw_node = find_post_node(method_roots(raw, fixture["method"]), raw["post_id"]) or {}
    leaks = leak_count(raw_node, text)
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
    args.out.write_bytes(text.encode("utf-8"))
    return 0


if __name__ == "__main__":
    sys.exit(main())
