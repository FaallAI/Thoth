"""The reaction rule (operator, 2026-10-11 and 2026-10-13), pure: who spoke, how the post did.

A reaction is an original when it adds a new viewpoint or issue AND its comments discuss the
creator's take AND it beat its account's usual engagement. Anything unmeasured keeps it a
repost, so attribution goes on to look for the video it shows.
"""

from __future__ import annotations

import statistics
from collections import Counter
from collections.abc import Mapping, Sequence
from dataclasses import dataclass

from thoth_control_plane.acquisition.models import DiscoveredVideo
from thoth_control_plane.attribution.ports import Assessment, Transcript, Turn
from thoth_control_plane.attribution.scenes import Shot

CREATOR_LABELS = frozenset({"creator", "both"})
MIN_BASELINE = 3


@dataclass(frozen=True)
class Speech:
    creator: str
    subject: str


@dataclass(frozen=True)
class ReactionCall:
    original: bool
    reason: str


def _overlap(a_start: float, a_end: float, b_start: float, b_end: float) -> float:
    return max(0.0, min(a_end, b_end) - max(a_start, b_start))


def split_speech(transcript: Transcript, turns: Sequence[Turn], cut: Sequence[Shot]) -> Speech:
    """Creator speech against the subject's own audio playing inside the reaction.

    The creator is the speaker heard most while the creator is on screen; in a voice-over,
    where no frame shows the creator, the speaker heard most overall. Speech no turn covers
    is the creator's.
    """
    if not turns:
        return Speech(" ".join(segment.text for segment in transcript.segments), "")
    on_camera: Counter[int] = Counter()
    total: Counter[int] = Counter()
    for turn in turns:
        total[turn.speaker] += turn.end - turn.start
        for shot in cut:
            if shot.shows in CREATOR_LABELS:
                on_camera[turn.speaker] += _overlap(turn.start, turn.end, shot.start, shot.end)
    ranked = on_camera if any(value > 0 for value in on_camera.values()) else total
    creator = ranked.most_common(1)[0][0]
    mine: list[str] = []
    theirs: list[str] = []
    for segment in transcript.segments:
        best = max(turns, key=lambda t: _overlap(segment.start, segment.end, t.start, t.end))
        heard = _overlap(segment.start, segment.end, best.start, best.end) > 0
        (mine if not heard or best.speaker == creator else theirs).append(segment.text)
    return Speech(" ".join(mine), " ".join(theirs))


def engagement_ratio(
    post_id: str,
    engagement: Mapping[str, int],
    videos: Sequence[DiscoveredVideo],
    *,
    url: str | None = None,
) -> float | None:
    """The post's plays over the median of the owner's other videos; likes when plays are
    hidden; None below `MIN_BASELINE` other videos or with a zero baseline.

    The post is left out by id or by URL: an Instagram report's id is the shortcode while its
    profile listing uses the numeric id.
    """
    own_url = url.rstrip("/") if url else None
    others = [
        video
        for video in videos
        if video.post_id != post_id and str(video.canonical_url).rstrip("/") != own_url
    ]
    for key in ("play", "like"):
        own = engagement.get(key)
        baseline = [video.engagement[key] for video in others if key in video.engagement]
        if own is None or len(baseline) < MIN_BASELINE:
            continue
        median = statistics.median(baseline)
        return own / median if median > 0 else None
    return None


def judge(
    assessment: Assessment,
    ratio: float | None,
    *,
    contribution: float,
    discussion: float,
    engagement: float,
) -> ReactionCall:
    if assessment.contribution < contribution:
        return ReactionCall(False, "no_new_contribution")
    if assessment.discussion is None:
        return ReactionCall(False, "no_comments")
    if assessment.discussion < discussion:
        return ReactionCall(False, "comments_not_about_creator")
    if ratio is None:
        return ReactionCall(False, "engagement_unknown")
    if ratio < engagement:
        return ReactionCall(False, "engagement_below_baseline")
    return ReactionCall(True, "original_reaction")
