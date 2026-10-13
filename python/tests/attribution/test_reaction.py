"""Who said what, how a post did against its account, and the operator's decision rule."""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

import pytest

from thoth_control_plane.acquisition.models import DiscoveredVideo
from thoth_control_plane.attribution.ports import Assessment, Segment, Transcript, Turn
from thoth_control_plane.attribution.reaction import (
    Engagement,
    ReactionCall,
    engagement_ratio,
    judge,
    lifetime_share,
    split_speech,
    subject_heard,
    subject_moves,
)
from thoth_control_plane.attribution.scenes import Shot

CLIP = Shot(0.0, 10.0, "subject")
TALK = Shot(10.0, 40.0, "creator")
TRANSCRIPT = Transcript(
    "id",
    (
        Segment(1.0, 8.0, "kata orang di video aslinya"),
        Segment(12.0, 30.0, "menurut saya ini masalah baru"),
    ),
)
TURNS = [Turn(0.5, 9.0, 0), Turn(11.0, 35.0, 1)]


def test_the_speaker_of_the_creator_shots_is_the_creator() -> None:
    speech = split_speech(TRANSCRIPT, TURNS, [CLIP, TALK])

    assert speech.creator == "menurut saya ini masalah baru"
    assert speech.subject == "kata orang di video aslinya"


def test_a_voice_over_takes_the_speaker_who_talks_most() -> None:
    speech = split_speech(TRANSCRIPT, TURNS, [Shot(0.0, 40.0, "subject")])

    assert speech.creator == "menurut saya ini masalah baru"


def test_without_turns_all_speech_is_the_creators() -> None:
    speech = split_speech(TRANSCRIPT, [], [CLIP, TALK])

    assert speech.subject == ""
    assert speech.creator == "kata orang di video aslinya menurut saya ini masalah baru"


def test_no_speech_is_empty_on_both_sides() -> None:
    assert split_speech(Transcript(""), TURNS, [CLIP, TALK]) == split_speech(Transcript(""), [], [])


NOW = datetime(2026, 10, 13, 12, 0, tzinfo=UTC)
MATURE = "2026-09-01T00:00:00Z"


def _video(post_id: str, published: str | None = MATURE, **engagement: int) -> DiscoveredVideo:
    return DiscoveredVideo.model_validate(
        {
            "post_id": post_id,
            "owner_handle": "kreator",
            "canonical_url": f"https://www.tiktok.com/@kreator/video/{post_id}",
            "published_at": published,
            "engagement": engagement,
        }
    )


def _ratio(
    engagement: dict[str, int],
    videos: list[DiscoveredVideo],
    *,
    published: str | None = MATURE,
    post_id: str = "99999",
    url: str | None = None,
) -> Engagement:
    return engagement_ratio(
        post_id,
        engagement,
        videos,
        url=url,
        platform="tiktok",
        published_at=published,
        now=NOW,
        min_age_hours=6.0,
    )


def test_the_ratio_compares_plays_with_the_median_of_other_videos() -> None:
    videos = [_video("11111", play=100), _video("22222", play=300), _video("33333", play=200)]

    assert _ratio({"play": 400}, videos).ratio == pytest.approx(2.0, rel=1e-3)


def test_the_post_itself_is_not_its_own_baseline() -> None:
    videos = [_video("99999", play=400), _video("11111", play=100), _video("22222", play=300)]

    assert _ratio({"play": 400}, videos) == Engagement(None)  # two others: too few


def test_likes_stand_in_when_plays_are_hidden() -> None:
    videos = [_video(str(n) * 5, like=10) for n in range(1, 4)]

    assert _ratio({"like": 5}, videos).ratio == pytest.approx(0.5, rel=1e-3)


def test_a_zero_baseline_is_unmeasured() -> None:
    videos = [_video(str(n) * 5, play=0) for n in range(1, 4)]

    assert _ratio({"play": 5}, videos) == Engagement(None)


def test_a_young_reaction_is_measured_against_the_baseline_at_its_age() -> None:
    # Spec 5.7: 400 plays at 9 h lose to a 1,000 lifetime median, but not to the share of it
    # the account's videos had at 9 h.
    videos = [_video(str(n) * 5, play=1000) for n in range(1, 4)]

    result = _ratio({"play": 400}, videos, published="2026-10-13T03:00:00Z")

    assert result.ratio == pytest.approx(400 / (1000 * lifetime_share("tiktok", 9.0)))
    assert result.ratio > 1.0


def test_a_reaction_younger_than_six_hours_is_too_early() -> None:
    videos = [_video(str(n) * 5, play=1000) for n in range(1, 4)]

    assert _ratio({"play": 40}, videos, published="2026-10-13T09:00:00Z") == Engagement(
        None, too_early=True
    )


def test_a_baseline_video_without_a_date_counts_as_mature() -> None:
    videos = [_video(str(n) * 5, published=None, play=200) for n in range(1, 4)]

    assert _ratio({"play": 400}, videos).ratio == pytest.approx(2.0, rel=1e-3)


def test_a_reaction_without_a_date_is_unmeasured() -> None:
    videos = [_video(str(n) * 5, play=200) for n in range(1, 4)]

    assert _ratio({"play": 400}, videos, published=None) == Engagement(None)


def test_the_lifetime_share_rises_from_zero_towards_one() -> None:
    assert lifetime_share("tiktok", 0.0) == 0.0
    assert lifetime_share("instagram", 24.0) == pytest.approx(0.30, abs=0.01)
    assert lifetime_share("tiktok", 10_000.0) == pytest.approx(1.0)


THRESHOLDS: dict[str, Any] = {"contribution": 0.5, "discussion": 0.5, "engagement_threshold": 1.0}


@pytest.mark.parametrize(
    ("assessment", "engagement", "expected"),
    [
        (Assessment(0.8, 0.7), Engagement(2.0), ReactionCall(True, "original_reaction")),
        (Assessment(0.3, 0.7), Engagement(2.0), ReactionCall(False, "no_new_contribution")),
        (Assessment(0.8, None), Engagement(2.0), ReactionCall(False, "no_comments")),
        (
            Assessment(0.8, 0.2),
            Engagement(2.0),
            ReactionCall(False, "comments_not_about_creator"),
        ),
        (Assessment(0.8, 0.7), Engagement(None), ReactionCall(False, "engagement_unknown")),
        (
            Assessment(0.8, 0.7),
            Engagement(0.6),
            ReactionCall(False, "engagement_below_baseline"),
        ),
        (
            Assessment(0.8, 0.7),
            Engagement(None, too_early=True),
            ReactionCall(True, "original_reaction_early"),
        ),
        (
            Assessment(0.3, 0.7),
            Engagement(None, too_early=True),
            ReactionCall(False, "no_new_contribution"),
        ),
    ],
)
def test_each_condition_alone_keeps_a_reaction_a_repost(
    assessment: Assessment, engagement: Engagement, expected: ReactionCall
) -> None:
    assert judge(assessment, engagement, **THRESHOLDS) == expected


def test_the_post_is_excluded_by_its_url_when_the_ids_differ() -> None:
    url = "https://www.instagram.com/p/DeHz54GT4ea/"
    videos = [
        _video("11111", play=100).model_copy(update={"canonical_url": url}),
        _video("22222", play=300),
        _video("33333", play=200),
    ]

    assert _ratio({"play": 400}, videos, post_id="DeHz54GT4ea", url=url) == Engagement(None)


def test_motion_inside_a_subject_shot_contradicts_a_still_label() -> None:
    # Spec 5.8: an image does not move; motion in the creator's own shots says nothing.
    seconds = [0.0, 1.0, 2.0, 3.0, 4.0]
    cut = [Shot(0.0, 2.0, "creator"), Shot(2.0, 5.0, "subject")]

    assert subject_moves(seconds, [0.0, 0.0, 0.3, 0.0], cut, threshold=0.02)
    assert not subject_moves(seconds, [0.3, 0.0, 0.0, 0.0], cut, threshold=0.02)
    assert not subject_moves(seconds, [0.0, 0.0, 0.01, 0.0], cut, threshold=0.02)


def test_another_voice_inside_a_subject_shot_contradicts_a_still_label() -> None:
    # Spec 5.8: an image is silent; the creator talking over it is not a contradiction.
    cut = [Shot(0.0, 10.0, "creator"), Shot(10.0, 20.0, "subject")]

    assert subject_heard([Turn(0.0, 10.0, 0), Turn(11.0, 15.0, 1)], cut)
    assert not subject_heard([Turn(0.0, 10.0, 0), Turn(11.0, 15.0, 0)], cut)
    assert not subject_heard([Turn(0.0, 10.0, 0), Turn(11.0, 11.5, 1)], cut)  # under 1 s
    assert not subject_heard([], cut)
