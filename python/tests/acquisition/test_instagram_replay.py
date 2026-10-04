"""Sanitized golden fixtures replay through the Instagram parsers and method decisions."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from thoth_control_plane.acquisition import instagram_service
from thoth_control_plane.acquisition.adapters.instagram import (
    canonicalize_instagram_post_url,
    parse_post,
)
from thoth_control_plane.acquisition.instagram_discovery import parse_profile, rank_videos
from thoth_control_plane.operations.threads_fixture import decide

FIXTURE_DIR = Path(__file__).resolve().parent.parent / "fixtures" / "instagram"
FIXTURES = {
    path.stem: json.loads(path.read_text(encoding="utf-8"))
    for path in sorted(FIXTURE_DIR.glob("*.json"))
}
POST_KINDS = ("video", "image", "carousel")
IDENTITY = canonicalize_instagram_post_url("https://www.instagram.com/p/code_001/")


def test_all_four_kinds_are_present() -> None:
    # App share links arrive as plain post URLs, so there is no share fixture (spec 6.1).
    assert set(FIXTURES) == {"video", "image", "carousel", "profile"}


@pytest.mark.parametrize("kind", POST_KINDS)
def test_post_fixture_replays_to_its_expected_parse(kind: str) -> None:
    fixture = FIXTURES[kind]
    parsed = parse_post([fixture["document"]], IDENTITY)
    assert parsed is not None
    assert {
        "text": parsed.post.text,
        "media_kinds": [item.kind for item in parsed.media],
        "engagement": parsed.post.engagement,
        "published_at": parsed.post.published_at,
        "comments": [c.model_dump(mode="json", exclude={"card"}) for c in parsed.comments],
    } == fixture["expected"]


def test_post_kinds_have_their_shape() -> None:
    assert "video" in FIXTURES["video"]["expected"]["media_kinds"]
    assert FIXTURES["image"]["expected"]["media_kinds"] == ["image"]
    assert len(FIXTURES["carousel"]["expected"]["media_kinds"]) > 1
    assert any(FIXTURES[kind]["expected"]["comments"] for kind in POST_KINDS)


def test_content_method_matches_recorded_comparison() -> None:
    pairs = [
        (FIXTURES[kind]["counts"]["request"], FIXTURES[kind]["counts"]["headless"])
        for kind in POST_KINDS
    ]
    assert decide(pairs) == instagram_service.CONTENT_METHOD


def test_profile_fixture_replays_in_ranked_grid_order() -> None:
    fixture = FIXTURES["profile"]
    result = parse_profile([fixture["document"]], fixture["handle"], 30)
    assert [video.post_id for video in result.videos] == fixture["expected"]["post_ids"]
    assert result.drops.model_dump() == fixture["expected"]["drops"]
    assert len(result.videos) == 12
    # The anonymous grid carries no ranking signal, so the grid order stands.
    assert all(v.engagement == {} and v.published_at is None for v in result.videos)
    assert rank_videos(result.videos) == result.videos
