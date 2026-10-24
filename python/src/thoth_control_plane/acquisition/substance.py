"""Whether a comment is more than noise (spec 2026-10-24, D1): free, deterministic, every
platform.

Mentions, links, emoji, and punctuation carry nothing on their own; laughter and stock filler
("first", "mantap", "wkwk") neither. Anything with a real word left passes, short reactions
included ("curiga suaminya", "Negara aneh"): on 236 stored comments a three-word floor dropped
the most-liked of them. Whether a comment is relevant and says something is the assembly
judge's call (Jev, D2); this check only spares it the noise and stands in when it is down.
"""

from __future__ import annotations

import re

MIN_WORDS = 1
MIN_LETTERS = 4
MENTION = re.compile(r"@\w+")
LINK = re.compile(r"(?i)\b(?:https?://|www\.)\S+|\bpic\.x\.com/\S+")
WORD = re.compile(r"[^\W\d_]+")
LAUGH = re.compile(r"(?i)^(?:w+k+[wk]*|h+[aeiou]+h[aeiouh]*|(?:a?wo?k){2,}|x+i+x[xi]*|k+w+k[kw]*)$")
FILLER = frozenset(
    {
        "first", "pertamax", "up", "nyimak", "hadir", "mantap", "mantab", "keren", "sedih",
        "semangat", "nice", "wow", "lol", "gg", "anjir", "njir", "anjay", "asli", "sip",
        "oke", "ok", "yes", "ya", "iya", "hmm", "btw", "dong", "deh", "sih", "kak", "min", "bang",
    }
)  # fmt: skip


def is_substantive(text: str) -> bool:
    plain = LINK.sub(" ", MENTION.sub(" ", text))
    words = [
        word for word in WORD.findall(plain) if word.lower() not in FILLER and not LAUGH.match(word)
    ]
    return len(words) >= MIN_WORDS and sum(len(word) for word in words) >= MIN_LETTERS
