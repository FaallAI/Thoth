"""Which comments belong in the video (spec 2026-10-24, D2): Jev answers one yes/no question per
comment, "relevant to the post and says something?", with a calibrated probability; code keeps
the ones at or above the threshold, in the likes order the merge already gave them.

The noise check (`acquisition/substance.py`) has already removed emoji, bare mentions or links,
laughter, and filler, so Jev weighs only relevance and content.
"""

from __future__ import annotations

from collections.abc import Sequence

from thoth_control_plane.assembly.models import MAX_COMMENTS, Comment

MAX_CANDIDATES = 50
KEEP_THRESHOLD = 0.5
COMMENT_CHARS = 300


def judge_inputs(post: str, headline: str, comments: Sequence[Comment]) -> list[str] | None:
    """The comment texts Jev is asked about; None when there is no post or no comment."""
    if not (post.strip() or headline.strip()) or not comments:
        return None
    return [" ".join(item.text.split())[:COMMENT_CHARS] for item in comments[:MAX_CANDIDATES]]


def judged(candidates: Sequence[Comment], probabilities: Sequence[float]) -> list[Comment]:
    kept = [
        item
        for item, probability in zip(candidates, probabilities, strict=False)
        if probability >= KEEP_THRESHOLD
    ]
    return kept[:MAX_COMMENTS]
