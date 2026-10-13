"""The reaction rule (operator, 2026-10-11 and 2026-10-13), pure: who spoke, how the post did.

A reaction is an original when it adds a new viewpoint or issue AND its comments discuss the
creator's take AND it beat its account's usual engagement at the same age. A reaction too
young to measure is judged without engagement. Anything else unmeasured keeps it a repost, so
attribution goes on to look for the video it shows.
"""

from __future__ import annotations

import math
import statistics
from collections import Counter
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import datetime
from itertools import pairwise

from thoth_control_plane.acquisition.models import DiscoveredVideo
from thoth_control_plane.attribution.candidates import parse_time
from thoth_control_plane.attribution.ports import Assessment, Transcript, Turn
from thoth_control_plane.attribution.scenes import Shot

CREATOR_LABELS = frozenset({"creator", "both"})
MIN_BASELINE = 3
# Hours for 63% of a video's lifetime views, from the published accrual curves (research
# 2026-10-13: Instagram ~30% on day one, ~65-70% in 72 h; TikTok surges over 1-5 days;
# YouTube settles in ~10 days). Recalibrate from Thoth's own snapshots.
TAU_HOURS = {"tiktok": 36.0, "instagram": 67.0, "youtube": 96.0, "x": 12.0}
DEFAULT_TAU_HOURS = 36.0


@dataclass(frozen=True)
class Speech:
    creator: str
    subject: str


@dataclass(frozen=True)
class Engagement:
    ratio: float | None
    too_early: bool = False


@dataclass(frozen=True)
class ReactionCall:
    original: bool
    reason: str


def _overlap(a_start: float, a_end: float, b_start: float, b_end: float) -> float:
    return max(0.0, min(a_end, b_end) - max(a_start, b_start))


def creator_speaker(turns: Sequence[Turn], cut: Sequence[Shot]) -> int | None:
    """The speaker heard most while the creator is on screen; in a voice-over, where no
    frame shows the creator, the speaker heard most overall."""
    if not turns:
        return None
    on_camera: Counter[int] = Counter()
    total: Counter[int] = Counter()
    for turn in turns:
        total[turn.speaker] += turn.end - turn.start
        for shot in cut:
            if shot.shows in CREATOR_LABELS:
                on_camera[turn.speaker] += _overlap(turn.start, turn.end, shot.start, shot.end)
    ranked = on_camera if any(value > 0 for value in on_camera.values()) else total
    return ranked.most_common(1)[0][0]


def subject_moves(
    seconds: Sequence[float], changes: Sequence[float], cut: Sequence[Shot], *, threshold: float
) -> bool:
    """Spec 5.8: two consecutive frames inside one `subject` shot differ: not a still image."""
    for (before, after), change in zip(pairwise(seconds), changes, strict=False):
        if change <= threshold:
            continue
        for shot in cut:
            if shot.shows == "subject" and shot.start <= before and after < shot.end:
                return True
    return False


def subject_heard(turns: Sequence[Turn], cut: Sequence[Shot], *, minimum: float = 1.0) -> bool:
    """Spec 5.8: someone other than the creator talks inside a `subject` shot: not silent."""
    creator = creator_speaker(turns, cut)
    for turn in turns:
        if turn.speaker == creator:
            continue
        heard = sum(
            _overlap(turn.start, turn.end, shot.start, shot.end)
            for shot in cut
            if shot.shows == "subject"
        )
        if heard >= minimum:
            return True
    return False


def split_speech(transcript: Transcript, turns: Sequence[Turn], cut: Sequence[Shot]) -> Speech:
    """Creator speech against the subject's own audio playing inside the reaction.

    Speech no turn covers is the creator's.
    """
    if not turns:
        return Speech(" ".join(segment.text for segment in transcript.segments), "")
    creator = creator_speaker(turns, cut)
    mine: list[str] = []
    theirs: list[str] = []
    for segment in transcript.segments:
        best = max(turns, key=lambda t: _overlap(segment.start, segment.end, t.start, t.end))
        heard = _overlap(segment.start, segment.end, best.start, best.end) > 0
        (mine if not heard or best.speaker == creator else theirs).append(segment.text)
    return Speech(" ".join(mine), " ".join(theirs))


def lifetime_share(platform: str, hours: float) -> float:
    """The expected share of a video's lifetime views at `hours` of age (spec 5.7)."""
    if hours <= 0:
        return 0.0
    return 1.0 - math.exp(-hours / TAU_HOURS.get(platform, DEFAULT_TAU_HOURS))


def _age_hours(published_at: str | None, now: datetime) -> float | None:
    published = parse_time(published_at)
    return None if published is None else (now - published).total_seconds() / 3600


def engagement_ratio(
    post_id: str,
    engagement: Mapping[str, int],
    videos: Sequence[DiscoveredVideo],
    *,
    url: str | None,
    platform: str,
    published_at: str | None,
    now: datetime,
    min_age_hours: float,
) -> Engagement:
    """The post's plays over the median of the owner's other videos scaled to its age.

    Views accrue for days, so each baseline video's count is scaled by the share of lifetime
    views it had at the reaction's age (operator, 2026-10-13). Likes stand in when plays are
    hidden. The post is left out by id or URL: an Instagram report's id is the shortcode while
    its profile listing uses the numeric id.
    """
    age = _age_hours(published_at, now)
    if age is None:
        return Engagement(None)
    if age < min_age_hours:
        return Engagement(None, too_early=True)
    share = lifetime_share(platform, age)
    own_url = url.rstrip("/") if url else None
    others = [
        video
        for video in videos
        if video.post_id != post_id and str(video.canonical_url).rstrip("/") != own_url
    ]
    for key in ("play", "like"):
        own = engagement.get(key)
        scaled = []
        for video in others:
            if key not in video.engagement:
                continue
            video_age = _age_hours(video.published_at, now)
            video_share = 1.0 if video_age is None else lifetime_share(platform, video_age)
            if video_share > 0:
                scaled.append(video.engagement[key] * share / video_share)
        if own is None or len(scaled) < MIN_BASELINE:
            continue
        median = statistics.median(scaled)
        return Engagement(own / median if median > 0 else None)
    return Engagement(None)


def judge(
    assessment: Assessment,
    engagement: Engagement,
    *,
    contribution: float,
    discussion: float,
    engagement_threshold: float,
) -> ReactionCall:
    if assessment.contribution < contribution:
        return ReactionCall(False, "no_new_contribution")
    if assessment.discussion is None:
        return ReactionCall(False, "no_comments")
    if assessment.discussion < discussion:
        return ReactionCall(False, "comments_not_about_creator")
    if engagement.too_early:
        return ReactionCall(True, "original_reaction_early")
    if engagement.ratio is None:
        return ReactionCall(False, "engagement_unknown")
    if engagement.ratio < engagement_threshold:
        return ReactionCall(False, "engagement_below_baseline")
    return ReactionCall(True, "original_reaction")
