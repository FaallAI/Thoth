"""Originals before reposts (footage library spec 2026-11-15, 4.5): the account a repost
credits, whether an account belongs to a card person, and the credit a clip carries."""

from __future__ import annotations

import re
from dataclasses import dataclass

from thoth_control_plane.attribution.credit import (
    AT_HANDLE,
    PLACEHOLDERS,
    normalize,
    text_handles,
    text_rule_credit,
)
from thoth_control_plane.footage.context import ContextCard, card_names

_PLATFORMS = {
    "youtube": "youtube",
    "yt": "youtube",
    "tiktok": "tiktok",
    "tt": "tiktok",
    "instagram": "instagram",
    "ig": "instagram",
    "x": "x",
    "twitter": "x",
}
_PLATFORM = "|".join(_PLATFORMS)
# "Sumber YT : Ernest Prakasa", "sc: KompasTV", "cr: @denny.sumargo", "yt: DPR RI",
# "YouTube/curhatbang", "via YouTube/CURHAT BANG", "via @kompastv". A bare "via" is prose
# ("Merbabu via Tekhelan", "via WA"), so it counts only before "@" or a platform word.
NAMED_CREDIT = re.compile(
    rf"(?:\b(?:sumber|source|kredit|credit|cr|sc)\s*(?:(?P<plat>{_PLATFORM})\s*)?:"
    rf"|\b(?P<yt>youtube|yt)\s*[/:]"
    rf"|\bvia\s*:|\bvia\s+(?=@|(?:{_PLATFORM})\b))"
    r"\s*(?P<label>[^|\n#]{2,60})",
    re.IGNORECASE,
)
PLATFORM_WORD = re.compile(rf"^({_PLATFORM})\b\s*/?\s*", re.IGNORECASE)
URL_START = ("http://", "https://", "www.")
YOUTUBE_WORD = re.compile(r"youtube|\byt\b", re.IGNORECASE)
MIN_ACCOUNT_NAME = 6


@dataclass(frozen=True)
class CreditRef:
    """A credited source: `account` is an @handle as written (no "@", dots kept, so it can be
    listed) or a normalised name; `display` is what a search can use; `platform` is the one the
    caption names, if any."""

    account: str
    display: str
    platform: str | None


def credited_source(text: str) -> CreditRef | None:
    """The source a caption credits (spec 2026-11-27, 4.1): a caption convention, then a named
    credit, then the first usable @handle."""
    rule = text_rule_credit(text)
    if rule is not None:
        handle = rule[0].lstrip("@").rstrip(".")
        return CreditRef(handle, handle, rule[1])
    for match in NAMED_CREDIT.finditer(text):
        ref = _named(match)
        if ref is not None:
            return ref
    handles = text_handles(text)
    if not handles:
        return None
    handle = handles[0].lstrip("@").rstrip(".")
    return CreditRef(handle, handle, "youtube" if YOUTUBE_WORD.search(text) else None)


def _named(match: re.Match[str]) -> CreditRef | None:
    label = match.group("label").strip()
    if label.lower().startswith(URL_START):
        return None
    word = match.group("plat") or match.group("yt")
    platform = _PLATFORMS[word.lower()] if word else None
    leading = PLATFORM_WORD.match(label)
    if leading is not None:
        platform = platform or _PLATFORMS[leading.group(1).lower()]
        label = label[leading.end() :].strip()
    handle = AT_HANDLE.match(label)
    if handle is not None:
        account = display = handle.group(1).rstrip(".")
    else:
        display = label
        account = normalize(label)
    key = normalize(account)
    if not key or key in PLACEHOLDERS:
        return None
    return CreditRef(account, display, platform)


def credited_account(text: str) -> str | None:
    """The account a caption credits, or None (see `credited_source`)."""
    ref = credited_source(text)
    return ref.account if ref is not None else None


def is_own_account(owner_handle: str, card: ContextCard) -> bool:
    """An account listed for a card person, or one carrying a card name (6+ characters)."""
    owner = normalize(owner_handle)
    if not owner:
        return False
    listed = {normalize(account) for person in card.people for account in person.accounts}
    if owner in listed:
        return True
    names = (name.replace(" ", "") for name in card_names(card))
    return any(len(name) >= MIN_ACCOUNT_NAME and name in owner for name in names)


def credit_label(platform: str | None, handle: str | None) -> str | None:
    if not handle or not handle.strip().lstrip("@"):
        return None
    bare = handle.strip().lstrip("@")
    return f"YouTube/{bare}" if platform == "youtube" else f"@{bare}"
