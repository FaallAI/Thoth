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
from collections.abc import Iterator
from pathlib import Path
from typing import Any

from thoth_control_plane.acquisition.discovery import parse_discovery_page
from thoth_control_plane.operations.tiktok_comment_fixture import _Pseudonyms

MAX_FIXTURE_PAGES = 2
STAT_KEYS = ("playCount", "diggCount", "commentCount", "shareCount", "collectCount")
MIN_SECRET_LENGTH = 4
# Keys whose values the sanitizer copies verbatim by design (never pseudonymized), so a raw
# leak check must not tokenize them and a leak check comparison must accept whatever type the
# parser reads for them.
VERBATIM_KEYS = frozenset(
    {
        "statusCode",
        "status_code",
        "hasMore",
        "has_more",
        "stats",
        "statsV2",
        "createTime",
        "duration",
    }
)


def _fill_caption_char(char: str) -> bool:
    """Pseudonymize every caption/hashtag character except whitespace and the structural
    `#`/`@` markers a hashtag or mention needs to stay recognizable as one.

    Unlike the comment reducer's `_is_letter`, this covers stylized Unicode (enclosed
    alphanumerics, fullwidth letters, etc., category `So`) that `str.isalnum()` misses, so no
    original character survives in a caption or hashtag title.
    """
    return not char.isspace() and char not in "#@"


def _numeric(value: Any) -> bool:
    """What `parse_discovery_page` accepts for a counter, timestamp, or duration slot: a
    non-bool int/float, or an ASCII decimal string."""
    if isinstance(value, bool):
        return False
    if isinstance(value, (int, float)):
        return True
    return isinstance(value, str) and value.isascii() and value.isdecimal()


def _stats(value: Any) -> dict[str, Any] | None:
    if not isinstance(value, dict):
        return None
    return {key: value[key] for key in STAT_KEYS if key in value and _numeric(value[key])}


def _envelope(payload: dict[str, Any]) -> dict[str, Any]:
    kept: dict[str, Any] = {}
    for key in ("statusCode", "status_code"):
        if key in payload and _numeric(payload[key]):
            kept[key] = payload[key]
    for key in ("hasMore", "has_more"):
        if key in payload and (isinstance(payload[key], bool) or _numeric(payload[key])):
            kept[key] = payload[key]
    return kept


def _item(names: _Pseudonyms, item: Any) -> dict[str, Any] | None:
    if not isinstance(item, dict):
        return None
    kept: dict[str, Any] = {}
    if isinstance(item.get("id"), str):
        kept["id"] = names.comment_id(item["id"])
    if isinstance(item.get("desc"), str):
        kept["desc"] = names.text(item["desc"])
    if _numeric(item.get("createTime")):
        kept["createTime"] = item["createTime"]
    for key in ("stats", "statsV2"):
        stats = _stats(item.get(key))
        if stats is not None:
            kept[key] = stats
    video = item.get("video")
    if isinstance(video, dict) and _numeric(video.get("duration")):
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
    page = _envelope(payload)
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
    names = _Pseudonyms(fill=_fill_caption_char)
    texts = raw["pages"][:MAX_FIXTURE_PAGES]
    pages = [_page(names, kind, text) for text in texts]
    expected = [replay_page(kind, text.encode("utf-8")) for text in texts]
    if [replay_page(kind, fixture_page_bytes(page)) for page in pages] != expected:
        raise ValueError("sanitized pages do not replay like the capture")
    return {"kind": kind, "pages": pages, "expected": expected}


def _strings(value: Any, exclude: frozenset[str] = frozenset()) -> Iterator[str]:
    """Every string leaf in a JSON-shaped value, skipping subtrees under an excluded key."""
    if isinstance(value, str):
        yield value
    elif isinstance(value, list):
        for item in value:
            yield from _strings(item, exclude)
    elif isinstance(value, dict):
        for key, sub in value.items():
            if key not in exclude:
                yield from _strings(sub, exclude)


def _originals(raw: dict[str, Any]) -> set[str]:
    """Every whitespace-split token, long enough to identify a source, in any raw string leaf
    outside the slots the sanitizer keeps verbatim by design — independent of which fields the
    sanitizer happens to pseudonymize, so an unpseudonymized or unknown key is still checked."""
    tokens: set[str] = set()
    for text in raw["pages"]:
        payload = _payload(text)
        if payload is None:
            continue
        for leaf in _strings(payload, VERBATIM_KEYS):
            tokens.update(token for token in leaf.split() if len(token) >= MIN_SECRET_LENGTH)
    return tokens


def leak_report(raw: dict[str, Any], text: str) -> tuple[int, int]:
    """Count original tokens that survive as a substring of any sanitized string value, plus
    any URL. A whole-value match would miss a token embedded in an otherwise-clean string."""
    tokens = _originals(raw)
    try:
        values = list(_strings(json.loads(text)))
    except (ValueError, RecursionError):
        values = [text]
    leaks = sum(any(token in value for value in values) for token in tokens)
    return len(tokens), leaks + ("http" in text)


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
