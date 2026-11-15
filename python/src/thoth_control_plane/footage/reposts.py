"""Originals before reposts (footage library spec 2026-11-15, 4.5): the account a repost
credits, whether an account belongs to a card person, and the credit a clip carries."""

from __future__ import annotations

import re

from thoth_control_plane.attribution.credit import normalize, text_handles, text_rule_credit
from thoth_control_plane.footage.context import ContextCard, card_names

# "Sumber: YouTube Curhat Bang | Tribun", "via YouTube/CURHAT BANG", "YouTube/curhatbang"
NAMED_CREDIT = re.compile(
    r"(?:\bsumber\s*:|\bsource\s*:|\bvia\b|\byoutube\s*/)\s*([^|\n#]{2,60})", re.IGNORECASE
)
PLATFORM_WORD = re.compile(r"^(?:youtube|yt|tiktok|tt|instagram|ig|x|twitter)\b\s*/?\s*", re.I)
MIN_ACCOUNT_NAME = 6


def credited_account(text: str) -> str | None:
    """The account a caption credits, normalised, or None."""
    rule = text_rule_credit(text)
    if rule is not None:
        return normalize(rule[0])
    handles = text_handles(text)
    if handles:
        return normalize(handles[0])
    match = NAMED_CREDIT.search(text)
    if match is None:
        return None
    name = normalize(PLATFORM_WORD.sub("", match.group(1).strip()))
    return name or None


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
