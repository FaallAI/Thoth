"""Sanitize a one-time live TikTok comment capture into a public golden fixture.

The repository is public. A fixture keeps only what the comment reducer reads
(`comments[].cid`, `unique_id`, `text`, `digg_count`) and replaces every id, handle, and text
with a stable pseudonym. Pseudonyms preserve what the reducer depends on: id and handle
validity, duplicates, text length, emoji and punctuation, sticker markers, and text equality
after strip between API entries and card texts. Card images never enter a fixture; only
their width, height, and byte size do.

Usage: python -m thoth_control_plane.operations.tiktok_comment_fixture RAW.json FIXTURE.json
"""

from __future__ import annotations

import itertools
import json
import re
import string
import sys
import unicodedata
from collections.abc import Callable
from pathlib import Path
from typing import Any

from thoth_control_plane.acquisition.browser import STICKER_ONLY

ENTRY_KEYS = ("cid", "unique_id", "text", "digg_count")
INVALID_ID = "invalid-id"
INVALID_HANDLE = "invalid handle"
ID_BASE = 7_000_000_000_000_000_000
COMMENT_ID = re.compile(r"[0-9]{5,32}")
HANDLE = re.compile(r"[A-Za-z0-9._-]{1,64}")
STAT_KEYS = ("width", "height", "bytes")
FILL_ALPHABET = string.ascii_lowercase + string.digits
FILL_WIDTH = 3


def _fill(index: int) -> itertools.cycle[str]:
    size = len(FILL_ALPHABET)
    return itertools.cycle(
        FILL_ALPHABET[(index // size**place) % size] for place in range(FILL_WIDTH)
    )


def _is_letter(char: str) -> bool:
    """Alphanumerics, combining marks (vowel signs, diacritics), and stylized letters are
    original text; emoji variation selectors and other symbols are not.

    A stylized letter (circled, squared, parenthesized, regional indicator) is category `So`,
    which `str.isalnum()` misses; its Unicode name spells `LETTER <x>`, unlike emoji such as
    LOVE LETTER.
    """
    if "\ufe00" <= char <= "\ufe0f":
        return False
    category = unicodedata.category(char)
    if category == "So":
        return " LETTER " in unicodedata.name(char, "")
    return char.isalnum() or category in {"Mn", "Mc"}


def _stat(stat: dict[str, Any]) -> dict[str, Any]:
    return {key: stat[key] for key in STAT_KEYS}


class _Pseudonyms:
    def __init__(self, fill: Callable[[str], bool] = _is_letter) -> None:
        self._ids: dict[str, str] = {}
        self._handles: dict[str, str] = {}
        self._texts: dict[str, str] = {}
        self._fill = fill

    def comment_id(self, value: Any) -> str | None:
        if value is None:
            return None
        key = str(value)
        if not COMMENT_ID.fullmatch(key):
            return INVALID_ID
        return self._ids.setdefault(key, str(ID_BASE + len(self._ids)))

    def handle(self, value: Any) -> str | None:
        if not isinstance(value, str):
            return None
        if not HANDLE.fullmatch(value):
            return INVALID_HANDLE
        return self._handles.setdefault(value, f"user_{len(self._handles) + 1:03d}")

    def text(self, value: Any) -> str | None:
        if not isinstance(value, str):
            return None
        core = value.strip()
        leading = value[: len(value) - len(value.lstrip())]
        trailing = value[len(value.rstrip()) :]
        return leading + self._core(core) + trailing

    def _core(self, core: str) -> str:
        if core in self._texts:
            return self._texts[core]
        if not core or STICKER_ONLY.fullmatch(core):
            self._texts[core] = core
            return core
        used = set(self._texts.values())
        for index in range(len(self._texts), len(FILL_ALPHABET) ** FILL_WIDTH):
            fill = _fill(index)
            pseudonym = "".join(next(fill) if self._fill(char) else char for char in core)
            if pseudonym not in used:
                self._texts[core] = pseudonym
                return pseudonym
        raise ValueError("cannot keep comment texts distinct; capture another post")


def _entry(names: _Pseudonyms, entry: Any) -> dict[str, Any] | None:
    if not isinstance(entry, dict):
        return None
    likes = entry.get("digg_count")
    return {
        "cid": names.comment_id(entry.get("cid")),
        "unique_id": names.handle(entry.get("unique_id")),
        "text": names.text(entry.get("text")),
        "digg_count": likes if isinstance(likes, int) else None,
    }


def sanitize_capture(raw: dict[str, Any]) -> dict[str, Any]:
    names = _Pseudonyms()
    pages: list[dict[str, Any] | None] = []
    for page in raw["pages"]:
        entries = page.get("comments") if isinstance(page, dict) else None
        if not isinstance(entries, list):
            pages.append(None)
            continue
        pages.append({"comments": [_entry(names, entry) for entry in entries]})
    return {
        "pages": pages,
        "card_texts": [names.text(text) for text in raw["card_texts"]],
        "card_stats": [_stat(stat) for stat in raw["card_stats"]],
        "profile_card_stats": (
            None if raw["profile_card_stats"] is None else _stat(raw["profile_card_stats"])
        ),
        "expected": [
            {"comment_id": names.comment_id(item["comment_id"]), "card": item["card"]}
            for item in raw["expected"]
        ],
    }


def main(argv: list[str] | None = None) -> int:
    source, target = argv if argv is not None else sys.argv[1:]
    raw = json.loads(Path(source).read_text(encoding="utf-8"))
    Path(target).write_text(
        json.dumps(sanitize_capture(raw), ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
        newline="\n",
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
