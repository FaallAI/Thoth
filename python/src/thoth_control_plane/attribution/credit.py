"""Credits read from text: caption conventions, handles, and which handles may be a credit.

Pure functions over strings. A handle is returned without its "@", in the case it was written,
and comes only from the text it was found in. Ported from Scout's `trace_source.ts`
(`detectCameraCredit`, `detectTiktokCredit`) and `lib/source_credit.ts` (reply mentions).
"""

from __future__ import annotations

import re
from collections.abc import Iterable, Sequence

from thoth_control_plane.attribution.models import Platform

AT_HANDLE = re.compile(r"(?<![\w@])@([A-Za-z0-9._]{2,30})")
# OCR often reads a burned-in credit as "@ name"; frames tolerate one space after "@".
FRAME_AT_HANDLE = re.compile(r"(?<![\w@])@\s?([A-Za-z0-9._]{2,30})")
PLAIN_HANDLE = re.compile(r"[A-Za-z0-9._]{2,30}")
BARE_TOKEN = re.compile(r"[a-z0-9][a-z0-9._]{1,28}[a-z0-9]")
DOMAIN_SUFFIX = re.compile(r"\.(com|net|org|id|co|tv|me|io|app)$")
CAMERA_CREDIT = re.compile(
    r"(?:📸|📷|🎥|🎬|🎞️|📹)\s*(?:cr\.?|credit|by)?\s*[:-]?\s*@([A-Za-z0-9._]{2,30})",
    re.IGNORECASE,
)
TIKTOK_CREDIT = re.compile(r"\btt\s*[/:]\s*@?([A-Za-z0-9._]{2,30})", re.IGNORECASE)
REPLY_PREFIX = re.compile(r"(?:reply(?:ing)?\s+to|membalas|balasan\s+untuk)\s*$", re.IGNORECASE)
TOKEN_EDGES = "♪•|:,;()[]\"'"
PLACEHOLDERS = frozenset(
    {
        "akun",
        "akunnya",
        "namaakun",
        "pengguna",
        "penggunanya",
        "user",
        "username",
        "unknown",
        "tidakdiketahui",
        "na",
        "none",
        "null",
        "nil",
        "anonim",
        "anonymous",
        "contoh",
        "example",
    }
)
MAX_OPTIONS = 20


def normalize(handle: str) -> str:
    """The comparison key: no "@", lowercase, no dots, underscores, dashes, or spaces."""
    return re.sub(r"[\s._-]", "", handle.lstrip("@").lower())


def text_rule_credit(text: str) -> tuple[str, Platform] | None:
    """A caption convention naming both the account and the platform; camera beats `tt/`."""
    rules: tuple[tuple[re.Pattern[str], Platform], ...] = (
        (CAMERA_CREDIT, "instagram"),
        (TIKTOK_CREDIT, "tiktok"),
    )
    for pattern, platform in rules:
        match = pattern.search(text)
        if match and normalize(match.group(1)) not in PLACEHOLDERS:
            return match.group(1).rstrip("."), platform
    return None


def text_handles(text: str) -> list[str]:
    """`@handles` in a caption, skipping a reply target and placeholders."""
    found = [
        match.group(1).rstrip(".")
        for match in AT_HANDLE.finditer(text)
        if not REPLY_PREFIX.search(text[: match.start()])
    ]
    return _usable(found)


def frame_handles(lines: Iterable[str]) -> list[str]:
    """Handles burned into frames: `@handles`, and bare watermark usernames."""
    found: list[str] = []
    for line in lines:
        found += [match.group(1).rstrip(".") for match in FRAME_AT_HANDLE.finditer(line)]
        for token in line.split():
            bare = token.strip(TOKEN_EDGES)
            if _bare_handle(bare):
                found.append(bare)
    return _usable(found)


def vision_handles(names: Iterable[str]) -> list[str]:
    """Account names the vision model read off the image, with or without "@"."""
    cleaned = [name.strip().lstrip("@").strip().rstrip(".") for name in names]
    return _usable(name for name in cleaned if PLAIN_HANDLE.fullmatch(name))


def near_variants(handle: str, options: Sequence[str], max_distance: int = 2) -> list[str]:
    """Other handles from the evidence that differ by a misread or two (OCR drops a letter)."""
    key = normalize(handle)
    return [
        option
        for option in _usable(options)
        if normalize(option) != key and _distance(normalize(option), key) <= max_distance
    ]


def _distance(a: str, b: str) -> int:
    """Levenshtein distance; handles are at most 30 characters."""
    previous = list(range(len(b) + 1))
    for i, left in enumerate(a, start=1):
        current = [i]
        for j, right in enumerate(b, start=1):
            current.append(
                min(previous[j] + 1, current[j - 1] + 1, previous[j - 1] + (left != right))
            )
        previous = current
    return previous[-1]


def credit_options(
    caption_handles: Sequence[str], found_in_frames: Sequence[str], owner: str
) -> list[str]:
    """Every distinct handle that could be the source credit; never the reposting account."""
    owner_key = normalize(owner)
    usable = _usable([*caption_handles, *found_in_frames])
    return [handle for handle in usable if normalize(handle) != owner_key][:MAX_OPTIONS]


def _bare_handle(token: str) -> bool:
    """A watermark username: lowercase, a letter, and a digit, dot, or underscore; not a domain."""
    return (
        BARE_TOKEN.fullmatch(token) is not None
        and re.search(r"[a-z]", token) is not None
        and re.search(r"[0-9._]", token) is not None
        and DOMAIN_SUFFIX.search(token) is None
    )


def _usable(handles: Iterable[str]) -> list[str]:
    seen: set[str] = set()
    usable: list[str] = []
    for handle in handles:
        key = normalize(handle)
        if len(key) < 2 or key in PLACEHOLDERS or key in seen:
            continue
        seen.add(key)
        usable.append(handle)
    return usable
