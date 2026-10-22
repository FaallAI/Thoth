"""Whether a creator's other post fits the story (spec 2026-10-22 5c-2, G3a). Pure.

The story gate reads only a caption, and an empty one scores 0, while a creator's own listing
is not filtered by any search query. So the creator path checks in three steps, cheapest first:
the caption with its hashtags read as words; then, for a caption too thin to judge, closeness in
time to the main; and last the frames, which the footage builder's vision judge reads as it
does for every clip.
"""

from __future__ import annotations

import re
from collections.abc import Callable, Sequence
from datetime import datetime, timedelta
from typing import Literal, TypeVar

T = TypeVar("T")

#: Below this many characters of body text a caption cannot be judged (tags and mentions aside).
WEAK_BODY = 15
#: An undecided post is kept only this close to the main, at most CLOSE_CAP of them.
CLOSE_DAYS = 7
CLOSE_CAP = 3
#: The creator's most recent posts listed once per workflow.
CREATOR_LISTING = 24
MAX_PHOTOS = 3

TAGS = re.compile(r"[#@]\S+")
# camelCase and digit boundaries: "BBMLangka2026" reads as "BBM Langka 2026".
WORD_BOUNDARY = re.compile(
    r"(?<=[a-z])(?=[A-Z])|(?<=[A-Z])(?=[A-Z][a-z])|(?<=[A-Za-z])(?=\d)|(?<=\d)(?=[A-Za-z])"
)

Verdict = Literal["pass", "reject", "undecided"]


def creator_query(handle: str) -> str:
    return f"creator:@{handle}"


def enriched_text(caption: str, hashtags: Sequence[str]) -> str:
    """The caption followed by each hashtag split into words."""
    words = [WORD_BOUNDARY.sub(" ", tag.replace("_", " ")) for tag in hashtags]
    return " ".join(part for part in [caption.strip(), *words] if part.strip())


def body_length(caption: str) -> int:
    return len(TAGS.sub("", caption).strip())


def verdict(score: float, caption: str, story_min: float) -> Verdict:
    """A real caption below the bar is about something else; a thin one is undecided."""
    if score >= story_min:
        return "pass"
    return "reject" if body_length(caption) >= WEAK_BODY else "undecided"


def closest(
    undecided: Sequence[T], published: Callable[[T], datetime | None], main: datetime | None
) -> tuple[list[T], list[T]]:
    """(kept, dropped): at most CLOSE_CAP posts within CLOSE_DAYS of the main, nearest first.

    Without the main's date, or a post's, closeness cannot be judged, so nothing is kept.
    """
    if main is None:
        return [], list(undecided)
    window = timedelta(days=CLOSE_DAYS)
    near = sorted(
        (
            (abs(when - main), index)
            for index, post in enumerate(undecided)
            if (when := published(post)) is not None and abs(when - main) <= window
        ),
    )
    keep = [index for _, index in near[:CLOSE_CAP]]
    kept = [undecided[index] for index in keep]
    dropped = [post for index, post in enumerate(undecided) if index not in keep]
    return kept, dropped
