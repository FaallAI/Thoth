"""Sanitize a one-time live TikTok discovery capture into a public golden fixture.

The repository is public. A fixture keeps at most two list pages and only the keys the
discovery parser reads. Ids, handles, captions, and hashtags become stable pseudonyms of the
same shape; every URL and every other key is dropped. Engagement counters and `createTime` are
kept: they are public aggregate values the normalizer is tested against. The tool replays the
parser over both forms and refuses to write if they differ or if any original value survives.

Usage: python -m thoth_control_plane.operations.tiktok_discovery_fixture RAW.json FIXTURE.json
"""

from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Any

from thoth_control_plane.acquisition.discovery import parse_discovery_page
from thoth_control_plane.operations.tiktok_comment_fixture import _Pseudonyms

MAX_FIXTURE_PAGES = 2
ENVELOPE_KEYS = ("statusCode", "status_code", "hasMore", "has_more")
STAT_KEYS = ("playCount", "diggCount", "commentCount", "shareCount", "collectCount")
MIN_SECRET_LENGTH = 4


def _stats(value: Any) -> dict[str, Any] | None:
    if not isinstance(value, dict):
        return None
    return {key: value[key] for key in STAT_KEYS if key in value}


def _create_time(value: Any) -> bool:
    if isinstance(value, bool):
        return False
    return isinstance(value, int) or (isinstance(value, str) and value.isdecimal())


def _item(names: _Pseudonyms, item: Any) -> dict[str, Any] | None:
    if not isinstance(item, dict):
        return None
    kept: dict[str, Any] = {}
    if isinstance(item.get("id"), str):
        kept["id"] = names.comment_id(item["id"])
    if isinstance(item.get("desc"), str):
        kept["desc"] = names.text(item["desc"])
    if _create_time(item.get("createTime")):
        kept["createTime"] = item["createTime"]
    for key in ("stats", "statsV2"):
        stats = _stats(item.get(key))
        if stats is not None:
            kept[key] = stats
    video = item.get("video")
    if isinstance(video, dict) and "duration" in video:
        kept["video"] = {"duration": video["duration"]}
    author = item.get("author")
    if isinstance(author, dict) and isinstance(author.get("uniqueId"), str):
        kept["author"] = {"uniqueId": names.handle(author["uniqueId"])}
    challenges = item.get("challenges")
    if isinstance(challenges, list):
        kept["challenges"] = [
            {"title": names.text(challenge["title"])}
            for challenge in challenges
            if isinstance(challenge, dict) and isinstance(challenge.get("title"), str)
        ]
    if item.get("imagePost") is not None:
        kept["imagePost"] = {}
    if isinstance(item.get("isAd"), bool):
        kept["isAd"] = item["isAd"]
    return kept


def _entry(names: _Pseudonyms, entry: Any) -> dict[str, Any] | None:
    if not isinstance(entry, dict):
        return None
    if entry.get("type") == 1:
        return {"type": 1, "item": _item(names, entry.get("item"))}
    entry_type = entry.get("type")
    return {"type": entry_type if isinstance(entry_type, int) else None}


def _payload(text: str) -> dict[str, Any] | None:
    try:
        payload = json.loads(text)
    except (ValueError, RecursionError):
        return None
    return payload if isinstance(payload, dict) else None


def _page(names: _Pseudonyms, kind: str, text: str) -> dict[str, Any] | None:
    payload = _payload(text)
    if payload is None:
        return None
    page = {key: payload[key] for key in ENVELOPE_KEYS if key in payload}
    if kind == "keyword":
        data = payload.get("data")
        if isinstance(data, list):
            page["data"] = [_entry(names, entry) for entry in data]
    else:
        items = payload.get("itemList")
        if isinstance(items, list):
            page["itemList"] = [_item(names, item) for item in items]
    return page


def fixture_page_bytes(page: dict[str, Any] | None) -> bytes:
    """A fixture page as the raw body the parser reads; `null` replays as an empty body."""
    return b"" if page is None else json.dumps(page, ensure_ascii=False).encode("utf-8")


def replay_page(kind: str, body: bytes) -> dict[str, Any]:
    """The parser's view of one page, projected onto values that are never secret."""
    page = parse_discovery_page(kind, body)
    return {
        "has_more": page.has_more,
        "reason": page.reason.value if page.reason is not None else None,
        "drops": page.drops.model_dump(),
        "videos": [
            {
                "published_at": video.published_at,
                "duration_seconds": video.duration_seconds,
                "engagement": dict(video.engagement),
                "caption_length": len(video.caption),
                "hashtags": len(video.hashtags),
            }
            for video in page.videos
        ],
    }


def sanitize_capture(raw: dict[str, Any]) -> dict[str, Any]:
    kind = raw["kind"]
    if kind not in ("profile", "keyword", "trending"):
        raise ValueError("unknown discovery kind")
    names = _Pseudonyms()
    texts = raw["pages"][:MAX_FIXTURE_PAGES]
    pages = [_page(names, kind, text) for text in texts]
    expected = [replay_page(kind, text.encode("utf-8")) for text in texts]
    if [replay_page(kind, fixture_page_bytes(page)) for page in pages] != expected:
        raise ValueError("sanitized pages do not replay like the capture")
    return {"kind": kind, "pages": pages, "expected": expected}


def _raw_items(kind: str, payload: dict[str, Any]) -> list[Any]:
    if kind == "keyword":
        data = payload.get("data")
        return (
            [e.get("item") for e in data if isinstance(e, dict)] if isinstance(data, list) else []
        )
    items = payload.get("itemList")
    return items if isinstance(items, list) else []


def _originals(raw: dict[str, Any]) -> set[str]:
    """Every original id, handle, caption, and hashtag long enough to identify a source."""
    secrets: set[str] = set()
    for text in raw["pages"]:
        payload = _payload(text)
        for item in _raw_items(raw["kind"], payload) if payload is not None else []:
            if not isinstance(item, dict):
                continue
            author = item.get("author") if isinstance(item.get("author"), dict) else {}
            challenges = item.get("challenges") if isinstance(item.get("challenges"), list) else []
            values = [
                item.get("id"),
                item.get("desc"),
                author.get("uniqueId"),
                author.get("secUid"),
                author.get("nickname"),
                *(c.get("title") for c in challenges if isinstance(c, dict)),
            ]
            secrets.update(
                value.strip()
                for value in values
                if isinstance(value, str)
                and len(value.strip()) >= MIN_SECRET_LENGTH
                and any(char.isalnum() for char in value)
            )
    return secrets


def leak_report(raw: dict[str, Any], text: str) -> tuple[int, int]:
    """Count originals that survive into `text`, raw or JSON-escaped, plus any URL."""
    secrets = _originals(raw)
    leaks = sum(
        secret in text or json.dumps(secret, ensure_ascii=False)[1:-1] in text for secret in secrets
    )
    return len(secrets), leaks + ("http" in text)


def main(argv: list[str] | None = None) -> int:
    source, target = argv if argv is not None else sys.argv[1:]
    raw = json.loads(Path(source).read_text(encoding="utf-8"))
    text = json.dumps(sanitize_capture(raw), ensure_ascii=False, indent=2) + "\n"
    checked, leaks = leak_report(raw, text)
    print(f"checked={checked} leaks={leaks}")
    if leaks:
        return 1
    Path(target).write_text(text, encoding="utf-8", newline="\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
