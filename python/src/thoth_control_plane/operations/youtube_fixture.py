"""Turn one raw YouTube capture into a sanitized golden fixture.

Operator-run after an authorized capture. Only the keys the parsers read survive. Video,
channel, and comment ids, handles, titles, descriptions, and comment text are pseudonymized;
format URLs become synthetic; timestamps move to a synthetic one-hour grid; counters are
floored. The leak check compares the capture's identifying strings (ids, handles, text, URLs)
with the fixture; a fixture with any surviving one is not written. Output reports counts only.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

from thoth_control_plane.acquisition.adapters.youtube import (
    YouTubeIdentity,
    channel_candidates,
    parse_info,
    select_formats,
    video_url,
)
from thoth_control_plane.acquisition.normalize import _count
from thoth_control_plane.operations.threads_fixture import MEDIA_HOST, _leaves, leak_count
from thoth_control_plane.operations.tiktok_comment_fixture import _Pseudonyms
from thoth_control_plane.operations.tiktok_discovery_fixture import (
    SYNTHETIC_EPOCH,
    SYNTHETIC_EPOCH_STEP,
    _floor,
)

FORMAT_KEYS = ("format_id", "protocol", "ext", "vcodec", "acodec", "width", "height", "tbr")
SIZE_KEYS = ("filesize", "filesize_approx")
COUNTERS = ("view_count", "like_count", "comment_count")
# Strings that identify a person or a video: the leak check's whole scope.
SECRET_KEYS = frozenset(
    {
        "id",
        "title",
        "description",
        "uploader",
        "uploader_id",
        "uploader_url",
        "channel",
        "channel_id",
        "channel_url",
        "author",
        "author_id",
        "author_url",
        "author_thumbnail",
        "text",
        "url",
        "webpage_url",
        "thumbnail",
    }
)
Fixture = tuple[dict[str, Any], dict[str, Any]]


def _secrets(value: Any) -> Any:
    """Every identifying string anywhere in the raw capture, kept for the leak check."""
    found: list[str] = []
    stack = [value]
    while stack:
        node = stack.pop()
        if isinstance(node, dict):
            for key, item in node.items():
                if key in SECRET_KEYS and isinstance(item, str):
                    found.append(item)
                    found.append(item.removeprefix("@"))
                else:
                    stack.append(item)
        elif isinstance(node, list):
            stack.extend(node)
    return {"secrets": found}


class _Sanitizer:
    def __init__(self) -> None:
        self.names = _Pseudonyms()
        self.videos: dict[str, str] = {}
        self.channels: dict[str, str] = {}
        self.comments: dict[str, str] = {}
        self.urls = 0
        self.epochs = 0

    def video_id(self, value: object) -> str:
        key = str(value)
        return self.videos.setdefault(key, f"vid{len(self.videos) + 1:08d}")

    def channel_id(self, value: object) -> str:
        key = str(value)
        return self.channels.setdefault(key, f"UC{len(self.channels) + 1:022d}")

    def comment_id(self, value: object) -> str:
        key = str(value)
        return self.comments.setdefault(key, f"Ugz{len(self.comments) + 1:08d}")

    def handle(self, value: object) -> str | None:
        if not isinstance(value, str):
            return None
        alias = self.names.handle(value.removeprefix("@"))
        return f"@{alias}" if value.startswith("@") else alias

    def epoch(self) -> int:
        self.epochs += 1
        return SYNTHETIC_EPOCH + self.epochs * SYNTHETIC_EPOCH_STEP

    def counter(self, value: object) -> int | None:
        count = _count(value)
        return None if count is None else _floor(count)

    def _format(self, fmt: dict[str, Any]) -> dict[str, Any]:
        out = {key: fmt[key] for key in FORMAT_KEYS if key in fmt}
        for key in SIZE_KEYS:
            if (size := self.counter(fmt.get(key))) is not None:
                out[key] = size
        if fmt.get("url"):
            self.urls += 1
            out["url"] = f"{MEDIA_HOST}/youtube/{self.urls}"
        return out

    def _comment(self, comment: dict[str, Any]) -> dict[str, Any]:
        out: dict[str, Any] = {
            "id": self.comment_id(comment.get("id")),
            "parent": comment.get("parent") if comment.get("parent") == "root" else "reply",
            "author": self.handle(comment.get("author")),
            "author_id": self.channel_id(comment.get("author_id")),
            "text": self.names.text(comment.get("text")),
        }
        if (likes := self.counter(comment.get("like_count"))) is not None:
            out["like_count"] = likes
        return out

    def info(self, info: dict[str, Any], *, formats: bool, comments: bool) -> dict[str, Any]:
        out: dict[str, Any] = {
            "id": self.video_id(info.get("id")),
            "uploader_id": self.handle(info.get("uploader_id")),
            "channel_id": self.channel_id(info.get("channel_id")),
            "live_status": info.get("live_status"),
        }
        for key in ("title", "description"):
            if isinstance(info.get(key), str):
                out[key] = self.names.text(info[key])
        if info.get("timestamp") is not None:
            out["timestamp"] = self.epoch()
        if isinstance(info.get("duration"), (int, float)):
            out["duration"] = info["duration"]
        for key in COUNTERS:
            if (count := self.counter(info.get(key))) is not None:
                out[key] = count
        if formats and isinstance(info.get("formats"), list):
            out["formats"] = [self._format(f) for f in info["formats"] if isinstance(f, dict)]
        if comments and isinstance(info.get("comments"), list):
            out["comments"] = [self._comment(c) for c in info["comments"] if isinstance(c, dict)]
        return out

    def listing(self, listing: dict[str, Any]) -> dict[str, Any]:
        entries = listing.get("entries") if isinstance(listing.get("entries"), list) else []
        return {
            "entries": [
                {"id": self.video_id(e.get("id")), "view_count": self.counter(e.get("view_count"))}
                for e in entries
                if isinstance(e, dict)
            ]
        }


def _expected_post(info: dict[str, Any]) -> dict[str, Any]:
    identity = YouTubeIdentity(canonical_url=video_url(info["id"]), video_id=info["id"])
    parsed = parse_info(info, identity)
    if parsed is None:
        raise ValueError("the sanitized info no longer parses")
    choice = select_formats(info.get("formats"), parsed.duration_seconds)
    return {
        "post": parsed.post.model_dump(mode="json"),
        "channel_url": parsed.channel_url,
        "duration_seconds": parsed.duration_seconds,
        "comments": [c.model_dump(mode="json", exclude={"card"}) for c in parsed.comments],
        "dropped_comments": parsed.dropped_comments,
        "choice": None
        if choice is None
        else {
            "video_format": choice.video_format,
            "audio_format": choice.audio_format,
            "short_side": choice.short_side,
        },
    }


def build_post(raw: dict[str, Any]) -> Fixture:
    info = raw["extract"]["info"]
    if not isinstance(info, dict):
        raise ValueError("the capture holds no info")
    document = _Sanitizer().info(info, formats=True, comments=True)
    fixture = {
        "kind": raw["kind"],
        "method": "yt_dlp",
        "counts": {
            "formats": len(info.get("formats") or []),
            "comments": len(info.get("comments") or []),
        },
        "document": document,
        "expected": _expected_post(document),
    }
    return fixture, _secrets(info)


def build_channel(raw: dict[str, Any]) -> Fixture:
    sanitizer = _Sanitizer()
    listings = {
        tab: sanitizer.listing(value["listing"])
        for tab, value in raw["listings"].items()
        if isinstance(value.get("listing"), dict)
    }
    details = {
        sanitizer.video_id(video_id): sanitizer.info(detail, formats=False, comments=False)
        for video_id, detail in raw["details"].items()
        if isinstance(detail, dict) and "error" not in detail
    }
    alias = sanitizer.names.handle(raw["handle"])
    fixture = {
        "kind": "channel",
        "method": "yt_dlp",
        "handle": alias,
        "counts": {
            "entries": sum(len(v["entries"]) for v in listings.values()),
            "details": len(details),
        },
        "document": {"listings": listings, "details": details},
        "expected": {"candidates": channel_candidates(listings.values(), 12)},
    }
    scope = _secrets({"listings": raw["listings"], "details": raw["details"]})
    scope["secrets"].append(raw["handle"])
    return fixture, scope


def build(raw: dict[str, Any]) -> Fixture:
    return build_channel(raw) if raw["kind"] == "channel" else build_post(raw)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--raw", type=Path, required=True)
    parser.add_argument("--out", type=Path, required=True)
    args = parser.parse_args(argv)
    raw = json.loads(args.raw.read_text(encoding="utf-8"))
    fixture, scope = build(raw)
    leaks = leak_count(scope, "\n".join(sorted(_leaves(fixture))))
    summary = {"kind": fixture["kind"], "counts": fixture["counts"], "leaks": leaks}
    print(json.dumps(summary))
    if leaks:
        return 1
    text = json.dumps(fixture, indent=2, ensure_ascii=False) + "\n"
    args.out.write_bytes(text.encode("utf-8"))
    return 0


if __name__ == "__main__":
    sys.exit(main())
