"""Pure engagement and publication-time normalization shared by TikTok adapters.

A value that is not what it claims to be is skipped, never guessed. A count must be a
non-negative integer or an ASCII decimal string of one. A publication time must be a positive
integer epoch in seconds, or an ASCII decimal string of one. Both are bounded by `MAX_INT64`,
whether they arrive as a JSON number or as a decimal string (at most 19 digits).
"""

from __future__ import annotations

from datetime import UTC, datetime

# Engagement key -> accepted source names: camelCase from TikTok's web API, snake_case from TikWM.
ENGAGEMENT_KEYS: dict[str, tuple[str, ...]] = {
    "play": ("playCount", "play_count"),
    "like": ("diggCount", "digg_count"),
    "comment": ("commentCount", "comment_count"),
    "share": ("shareCount", "share_count"),
    "collect": ("collectCount", "collect_count"),
}
# Signed 64-bit bound for every integer read here, so a later store never overflows.
MAX_INT64 = 2**63 - 1
MAX_INT64_DIGITS = len(str(MAX_INT64))


def _decimal(value: str) -> int | None:
    # The length check runs first: `int()` of a very long digit string is slow or refused.
    if value.isascii() and value.isdecimal() and len(value) <= MAX_INT64_DIGITS:
        number = int(value)
        return number if number <= MAX_INT64 else None
    return None


def _count(value: object) -> int | None:
    if isinstance(value, bool):
        return None
    if isinstance(value, int):
        return value if 0 <= value <= MAX_INT64 else None
    if isinstance(value, str):
        return _decimal(value)
    return None


def _pick(source: object, names: tuple[str, ...]) -> int | None:
    if not isinstance(source, dict):
        return None
    for name in names:
        count = _count(source.get(name))
        if count is not None:
            return count
    return None


def normalize_engagement(stats: object, stats_v2: object) -> dict[str, int]:
    """Map TikTok counters to engagement keys, preferring the precise `statsV2` per key."""
    engagement: dict[str, int] = {}
    for key, names in ENGAGEMENT_KEYS.items():
        count = _pick(stats_v2, names)
        if count is None:
            count = _pick(stats, names)
        if count is not None:
            engagement[key] = count
    return engagement


def published_at_from_epoch(value: object) -> str | None:
    """Return a positive epoch-seconds value as `YYYY-MM-DDTHH:MM:SSZ`, else `None`."""
    if isinstance(value, str):
        value = _decimal(value)
    if isinstance(value, bool) or not isinstance(value, int) or value <= 0:
        return None
    try:
        return datetime.fromtimestamp(value, tz=UTC).strftime("%Y-%m-%dT%H:%M:%SZ")
    except (OverflowError, OSError, ValueError):
        return None
