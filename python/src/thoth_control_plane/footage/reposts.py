"""Originals before reposts (footage library spec 2026-11-15, 4.5): the account a repost
credits, whether an account belongs to a card person, and the credit a clip carries."""

from __future__ import annotations

import re
from collections.abc import Sequence
from dataclasses import dataclass
from itertools import pairwise

from thoth_control_plane.attribution.credit import (
    AT_HANDLE,
    PLACEHOLDERS,
    normalize,
    text_handles,
    text_rule_credit,
)
from thoth_control_plane.domain.planner import STOP_WORDS
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
# "YouTube/curhatbang", "via YouTube/CURHAT BANG", "via @kompastv", "Dok. YouTube/FFI". A bare
# "via" is prose ("Merbabu via Tekhelan", "via WA") and a bare "Dok." can be personal ("Dok.
# Pribadi"), so each counts only before "@" or a platform word.
NAMED_CREDIT = re.compile(
    rf"(?:\b(?:sumber|source|kredit|credit|cr|sc|dok\.?)\s*(?:(?P<plat>{_PLATFORM})\s*)?:"
    rf"|\b(?P<yt>youtube|yt)\s*[/:]"
    rf"|\bvia\s*:|\b(?:via|dok\.)\s+(?=@|(?:{_PLATFORM})\b))"
    r"\s*(?P<label>[^|\n#]{2,60})",
    re.IGNORECASE,
)
PLATFORM_WORD = re.compile(rf"^({_PLATFORM})\b\s*/?\s*", re.IGNORECASE)
URL_START = ("http://", "https://", "www.")
YOUTUBE_WORD = re.compile(r"youtube|\byt\b", re.IGNORECASE)
MIN_ACCOUNT_NAME = 6
# A box holding only a credit prefix ("Sumber", "Dok.", "YouTube/"): OCR often reads the label
# it introduces as the next box. A lone "via" is a subtitle word, never a prefix.
CREDIT_PREFIX = re.compile(
    rf"^(?:(?:sumber|source|kredit|credit|cr|sc|dok\.?)(?:\s*(?:{_PLATFORM}))?"
    r"|youtube|yt)\s*[:/]?$",
    re.IGNORECASE,
)
# A frame credit's label is a short name; a longer one, or one with a function word ("di",
# "ada", "dia"), is a spoken subtitle line.
MAX_FRAME_LABEL_WORDS = 5
WORD = re.compile(r"[a-z0-9]+")
# Corner labels on news frames that name no account ("Dok. Istimewa", "Sumber: Internet").
FRAME_PLACEHOLDERS = PLACEHOLDERS | frozenset(
    {
        "istimewa",
        "pribadi",
        "dokumentasi",
        "arsip",
        "net",
        "internet",
        "repro",
        "dokpribadi",
        "dokistimewa",
    }
)


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
    ref = _explicit_credit(text)
    if ref is not None:
        return ref
    handles = text_handles(text)
    if not handles:
        return None
    handle = handles[0].lstrip("@").rstrip(".")
    return CreditRef(handle, handle, "youtube" if YOUTUBE_WORD.search(text) else None)


def _rule_credit(text: str) -> CreditRef | None:
    rule = text_rule_credit(text)
    if rule is None:
        return None
    handle = rule[0].lstrip("@").rstrip(".")
    return CreditRef(handle, handle, rule[1])


def _explicit_credit(text: str) -> CreditRef | None:
    """A caption convention or a named credit; never a bare @handle."""
    rule = _rule_credit(text)
    if rule is not None:
        return rule
    for match in NAMED_CREDIT.finditer(text):
        ref = _named(match)
        if ref is not None:
            return ref
    return None


def _frame_credit(text: str) -> CreditRef | None:
    """A credit box: it starts with the credit, "via" only before an @handle, and its label is
    a short name, not a subtitle line ("kata dia via YouTube kemarin")."""
    rule = _rule_credit(text)
    if rule is not None:
        return rule
    match = NAMED_CREDIT.match(text)
    if match is None:
        return None
    if text[:3].lower() == "via" and not match.group("label").lstrip().startswith("@"):
        return None
    ref = _named(match)
    if ref is None:
        return None
    words = WORD.findall(ref.display.lower())
    if len(words) > MAX_FRAME_LABEL_WORDS or any(word in STOP_WORDS for word in words):
        return None
    return ref


def frame_credited_source(frames: Sequence[Sequence[str]]) -> CreditRef | None:
    """The source burned into a repost's frames (spec 2026-11-27 ocr video credit, 3.2): each
    frame's lines, and a prefix box joined to its neighbour in the same frame; the first YouTube
    credit across frames, else the first credit. A bare @handle is the uploader's watermark."""
    first: CreditRef | None = None
    for lines in frames:
        texts = [line.strip() for line in lines]
        candidates = list(texts)
        for prefix, label in pairwise(texts):
            if CREDIT_PREFIX.match(prefix):
                joint = " " if prefix.endswith((":", "/")) else ": "
                candidates.append(f"{prefix}{joint}{label}")
        for text in candidates:
            ref = _frame_credit(text)
            if ref is None or normalize(ref.account) in FRAME_PLACEHOLDERS:
                continue
            if ref.platform == "youtube":
                return ref
            first = first or ref
    return first


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
