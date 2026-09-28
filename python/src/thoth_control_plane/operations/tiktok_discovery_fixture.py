"""Sanitize a one-time live TikTok discovery capture into a public golden fixture.

The repository is public. A fixture keeps at most two list pages and only the keys the
discovery parser reads. Ids, handles, captions, and hashtags become stable pseudonyms of the
same shape; every URL and every other key is dropped. Engagement counters keep two significant
digits and `createTime` becomes a synthetic epoch, so neither can re-identify a post while the
normalizer is still tested against both. `expected` is the parser's replay of the sanitized
pages; the tool refuses to write if the capture replays to a different shape or if any
original value survives.

Usage: python -m thoth_control_plane.operations.tiktok_discovery_fixture RAW.json FIXTURE.json
"""

from __future__ import annotations

import json
import sys
from collections.abc import Iterator
from pathlib import Path
from typing import Any

from thoth_control_plane.acquisition.discovery import parse_discovery_page
from thoth_control_plane.acquisition.normalize import _count, published_at_from_epoch
from thoth_control_plane.operations.tiktok_comment_fixture import _Pseudonyms

MAX_FIXTURE_PAGES = 2
STAT_KEYS = ("playCount", "diggCount", "commentCount", "shareCount", "collectCount")
MIN_SECRET_LENGTH = 4
# Output slots holding an id or a handle, which only a whole original value can leak.
IDENTITY_KEYS = frozenset({"id", "uniqueId"})
# Synthetic publication epochs: the first distinct `createTime` becomes 2023-11-14T22:13:20Z,
# each later one an hour after the previous.
SYNTHETIC_EPOCH = 1_700_000_000
SYNTHETIC_EPOCH_STEP = 3_600
COUNTER_DIGITS = 2
# Numeric slots: kept as numbers, floored, or replaced by synthetic values, never pseudonymized
# text. The leak check skips them on both sides; a number is not an identifying token.
NUMERIC_KEYS = frozenset(
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

    Unlike the comment reducer's `_is_letter`, this also replaces emoji and other symbols, so
    no original character survives in a caption or hashtag title.
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


def _floor(count: int) -> int:
    """`count` floored to COUNTER_DIGITS significant digits; the digit count never grows."""
    scale = 10 ** max(len(str(count)) - COUNTER_DIGITS, 0)
    return count // scale * scale


def _stats(value: Any) -> dict[str, Any] | None:
    """Counters the normalizer accepts, floored in their raw type. A rejected counter replays
    the same whether it is kept or dropped, so it is dropped."""
    if not isinstance(value, dict):
        return None
    kept: dict[str, Any] = {}
    for key in STAT_KEYS:
        count = _count(value.get(key))
        if count is not None:
            kept[key] = str(_floor(count)) if isinstance(value[key], str) else _floor(count)
    return kept


def _envelope(payload: dict[str, Any]) -> dict[str, Any]:
    """Present envelope keys stay present: dropping one would let the parser fall back to its
    snake_case twin. A value that is not a plain number becomes a sentinel that replays alike."""
    kept: dict[str, Any] = {}
    for key in ("statusCode", "status_code"):
        if key in payload:
            value = payload[key]
            kept[key] = value if value in (None, 0, "0") or _numeric(value) else -1
    for key in ("hasMore", "has_more"):
        if key in payload:
            value = payload[key]
            kept[key] = value if isinstance(value, bool) or _numeric(value) else None
    return kept


class _Names(_Pseudonyms):
    """Caption pseudonyms plus synthetic publication epochs, both stable within one capture."""

    def __init__(self) -> None:
        super().__init__(fill=_fill_caption_char)
        self._epochs: dict[int, int] = {}

    def epoch(self, value: Any) -> int | str | None:
        """A synthetic epoch in the raw value's type, in order of first appearance; `None` for
        a value the normalizer rejects, which replays as no `published_at` either way."""
        if published_at_from_epoch(value) is None:
            return None
        synthetic = self._epochs.setdefault(
            int(value), SYNTHETIC_EPOCH + len(self._epochs) * SYNTHETIC_EPOCH_STEP
        )
        return str(synthetic) if isinstance(value, str) else synthetic


def _item(names: _Names, item: Any) -> dict[str, Any] | None:
    if not isinstance(item, dict):
        return None
    kept: dict[str, Any] = {}
    if isinstance(item.get("id"), str):
        kept["id"] = names.comment_id(item["id"])
    if isinstance(item.get("desc"), str):
        kept["desc"] = names.text(item["desc"])
    epoch = names.epoch(item.get("createTime"))
    if epoch is not None:
        kept["createTime"] = epoch
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


def _entry(names: _Names, entry: Any) -> dict[str, Any] | None:
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


def _page(names: _Names, kind: str, text: str) -> dict[str, Any] | None:
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


def _shape(replay: dict[str, Any]) -> dict[str, Any]:
    """A page replay reduced to what sanitizing must preserve: whether a video has a
    publication time, and its counters at COUNTER_DIGITS significant digits."""
    videos = [
        {
            **video,
            "published_at": video["published_at"] is not None,
            "engagement": {key: _floor(count) for key, count in video["engagement"].items()},
        }
        for video in replay["videos"]
    ]
    return {**replay, "videos": videos}


def sanitize_capture(raw: dict[str, Any]) -> dict[str, Any]:
    kind = raw["kind"]
    if kind not in ("profile", "keyword", "trending"):
        raise ValueError("unknown discovery kind")
    names = _Names()
    texts = raw["pages"][:MAX_FIXTURE_PAGES]
    pages = [_page(names, kind, text) for text in texts]
    expected = [replay_page(kind, fixture_page_bytes(page)) for page in pages]
    captured = [replay_page(kind, text.encode("utf-8")) for text in texts]
    if [_shape(page) for page in captured] != [_shape(page) for page in expected]:
        raise ValueError("sanitized pages do not replay like the capture")
    return {"kind": kind, "pages": pages, "expected": expected}


def _strings(
    value: Any, exclude: frozenset[str] = frozenset(), key: str | None = None
) -> Iterator[tuple[str | None, str]]:
    """Every string leaf in a JSON-shaped value with the key that holds it, skipping subtrees
    under an excluded key."""
    if isinstance(value, str):
        yield key, value
    elif isinstance(value, list):
        for item in value:
            yield from _strings(item, exclude, key)
    elif isinstance(value, dict):
        for name, sub in value.items():
            if name not in exclude:
                yield from _strings(sub, exclude, name)


def _raw_leaves(raw: dict[str, Any]) -> Iterator[str]:
    """Every raw string leaf outside the numeric slots, independent of which fields the
    sanitizer happens to pseudonymize, so an unpseudonymized or unknown key is still checked."""
    for text in raw["pages"]:
        payload = _payload(text)
        if payload is not None:
            for _key, leaf in _strings(payload, NUMERIC_KEYS):
                yield leaf


def _originals(raw: dict[str, Any]) -> set[str]:
    """Every whitespace-split raw token; a token of only the `#`/`@` markers the sanitizer
    keeps is not original text."""
    return {token for leaf in _raw_leaves(raw) for token in leaf.split() if token.strip("#@")}


def _placed(text: str) -> set[tuple[int, int, str]]:
    """Each word of a string with its position and the string's length."""
    return {(len(text), index, word) for index, word in enumerate(text.split())}


def leak_report(raw: dict[str, Any], text: str) -> tuple[int, int]:
    """Count original tokens that survive in the sanitized pages, plus any URL.

    An id or handle slot leaks when its whole value is an original token, so a 2-character
    handle is caught and `user_001` is not a leak of a raw `user`. Elsewhere a token long
    enough to identify a source leaks as a substring, which catches one embedded in an
    otherwise-clean caption. A shorter word leaks when it stays in place: pseudonyms keep a
    string's length and word positions, while the same letters elsewhere are an unrelated
    pseudonym (36 fill characters repeat short words by chance). A one-character word
    identifies nothing, so it is checked only in id and handle slots.
    """
    tokens = _originals(raw)
    try:
        # `expected` is a pure parser replay of `pages`, and `NUMERIC_KEYS` slots hold only
        # numbers; neither carries leak signal beyond `pages` itself.
        leaves = list(_strings(json.loads(text), NUMERIC_KEYS | {"expected"}))
    except (ValueError, RecursionError):
        leaves = [(None, text)]
    identities = {leaf for key, leaf in leaves if key in IDENTITY_KEYS}
    values = [leaf for key, leaf in leaves if key not in IDENTITY_KEYS]
    in_place = {
        word
        for _length, _index, word in {spot for value in values for spot in _placed(value)}
        & {spot for leaf in _raw_leaves(raw) for spot in _placed(leaf)}
    }
    leaks = sum(
        token in identities
        or (
            any(token in value for value in values)
            if len(token) >= MIN_SECRET_LENGTH
            else len(token) > 1 and token in in_place
        )
        for token in tokens
    )
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
