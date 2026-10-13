"""Who said what, how a post did against its account, and the operator's decision rule."""

from __future__ import annotations

from typing import Any

import pytest

from thoth_control_plane.acquisition.models import DiscoveredVideo
from thoth_control_plane.attribution.ports import Assessment, Segment, Transcript, Turn
from thoth_control_plane.attribution.reaction import (
    ReactionCall,
    engagement_ratio,
    judge,
    split_speech,
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


def _video(post_id: str, **engagement: int) -> DiscoveredVideo:
    return DiscoveredVideo.model_validate(
        {
            "post_id": post_id,
            "owner_handle": "kreator",
            "canonical_url": f"https://www.tiktok.com/@kreator/video/{post_id}",
            "engagement": engagement,
        }
    )


def test_the_ratio_compares_plays_with_the_median_of_other_videos() -> None:
    videos = [_video("11111", play=100), _video("22222", play=300), _video("33333", play=200)]

    assert engagement_ratio("99999", {"play": 400}, videos) == pytest.approx(2.0)


def test_the_post_itself_is_not_its_own_baseline() -> None:
    videos = [_video("99999", play=400), _video("11111", play=100), _video("22222", play=300)]

    assert engagement_ratio("99999", {"play": 400}, videos) is None  # two others: too few


def test_likes_stand_in_when_plays_are_hidden() -> None:
    videos = [_video(str(n) * 5, like=10) for n in range(1, 4)]

    assert engagement_ratio("99999", {"like": 5}, videos) == pytest.approx(0.5)


def test_a_zero_baseline_is_unmeasured() -> None:
    videos = [_video(str(n) * 5, play=0) for n in range(1, 4)]

    assert engagement_ratio("99999", {"play": 5}, videos) is None


THRESHOLDS: dict[str, Any] = {"contribution": 0.5, "discussion": 0.5, "engagement": 1.0}


@pytest.mark.parametrize(
    ("assessment", "ratio", "expected"),
    [
        (Assessment(0.8, 0.7), 2.0, ReactionCall(True, "original_reaction")),
        (Assessment(0.3, 0.7), 2.0, ReactionCall(False, "no_new_contribution")),
        (Assessment(0.8, None), 2.0, ReactionCall(False, "no_comments")),
        (Assessment(0.8, 0.2), 2.0, ReactionCall(False, "comments_not_about_creator")),
        (Assessment(0.8, 0.7), None, ReactionCall(False, "engagement_unknown")),
        (Assessment(0.8, 0.7), 0.6, ReactionCall(False, "engagement_below_baseline")),
    ],
)
def test_each_condition_alone_keeps_a_reaction_a_repost(
    assessment: Assessment, ratio: float | None, expected: ReactionCall
) -> None:
    assert judge(assessment, ratio, **THRESHOLDS) == expected
