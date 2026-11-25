"""Inline ElevenLabs audio tags such as ``[curious]`` (spec 2026-11-24, section 5.1).

A script beat may carry tags before the words they colour. Only Eleven v4 reads them; every
place that counts, times or shows spoken words strips them first.
"""

from __future__ import annotations

import re

#: An audio tag: 1 to 40 ASCII letters and spaces in brackets, so ``[2026]`` is not one.
AUDIO_TAG_RE = re.compile(r"\[[A-Za-z][A-Za-z ]{0,39}\]")
_BRACKETED = re.compile(r"\[([^\[\]]+)\]")
_REMOVED = "\x00"
_BEFORE_PUNCTUATION = re.compile(r"\s*\x00(?=[.,!?;:])")


def supports_audio_tags(model_id: str | None) -> bool:
    """Eleven v4 only: v3 reads tags too but cannot stitch requests (spec 5.4)."""
    return bool(model_id) and model_id.startswith("eleven_v4")


def _tidy(text: str) -> str:
    text = _BEFORE_PUNCTUATION.sub("", text).replace(_REMOVED, " ")
    return " ".join(text.split())


def strip_audio_tags(text: str) -> str:
    """The spoken words only; other brackets and an unclosed ``[`` are kept as written."""
    return _tidy(AUDIO_TAG_RE.sub(_REMOVED, text))


def sanitize_script_tags(text: str, allowed: frozenset[str], *, max_tags: int | None = None) -> str:
    """Keep the first ``max_tags`` allowed tags, lower-cased; drop every other bracketed span
    whole. A model's stage note (``[tertawa]``, ``[musik dramatis mulai]``) must never be read
    aloud in a paid voice, even at the cost of a word it wrapped by mistake (spec 5.1)."""
    kept = 0

    def keep_or_drop(match: re.Match[str]) -> str:
        nonlocal kept
        tag = " ".join(match.group(1).lower().split())
        if tag in allowed and (max_tags is None or kept < max_tags):
            kept += 1
            return f"[{tag}]"
        return _REMOVED

    return _tidy(_BRACKETED.sub(keep_or_drop, text))
