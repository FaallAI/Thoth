"""Sanitized golden fixtures replay through the X parsers, the merge, and discovery."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from thoth_control_plane.acquisition import x_service
from thoth_control_plane.acquisition.adapters.x import (
    XPostIdentity,
    parse_page,
    parse_syndication,
    with_page,
)
from thoth_control_plane.acquisition.instagram_discovery import rank_videos
from thoth_control_plane.acquisition.x_discovery import parse_profile

FIXTURE_DIR = Path(__file__).resolve().parent.parent / "fixtures" / "x"
FIXTURES = {
    path.stem: json.loads(path.read_text(encoding="utf-8"))
    for path in sorted(FIXTURE_DIR.glob("*.json"))
}
POST_KINDS = ("video", "image", "text", "replies")


def test_all_five_kinds_are_present() -> None:
    assert set(FIXTURES) == {"video", "image", "text", "replies", "profile"}


@pytest.mark.parametrize("kind", POST_KINDS)
def test_post_fixture_replays_to_its_expected_parse(kind: str) -> None:
    fixture = FIXTURES[kind]
    identity = XPostIdentity(post_id=fixture["post_id"])
    document = fixture["document"]
    page = parse_page([document["page"]], identity)
    parsed = parse_syndication(document["syndication"], identity, page.videos)
    assert parsed is not None
    merged = with_page(parsed, page)
    assert {
        "owner_handle": merged.post.owner_handle,
        "text": merged.post.text,
        "media_kinds": [item.kind for item in merged.media],
        "engagement": merged.post.engagement,
        "published_at": merged.post.published_at,
        "comments": [c.model_dump(mode="json", exclude={"card"}) for c in page.comments],
    } == fixture["expected"]


def test_post_kinds_have_their_shape() -> None:
    assert "video" in FIXTURES["video"]["expected"]["media_kinds"]
    assert set(FIXTURES["image"]["expected"]["media_kinds"]) == {"image"}
    assert FIXTURES["text"]["expected"]["media_kinds"] == []
    assert any(FIXTURES[kind]["expected"]["comments"] for kind in POST_KINDS)
    assert all("play" in FIXTURES[kind]["expected"]["engagement"] for kind in POST_KINDS)


def test_content_is_request_by_construction() -> None:
    assert x_service.CONTENT_METHOD == "request"
    assert {FIXTURES[kind]["method"] for kind in FIXTURES} == {"request"}


def test_profile_fixture_replays_ranked() -> None:
    fixture = FIXTURES["profile"]
    result = parse_profile([fixture["document"]], fixture["handle"], 30)
    assert [video.post_id for video in result.videos] == fixture["expected"]["post_ids"]
    assert result.drops.model_dump() == fixture["expected"]["drops"]
    assert rank_videos(result.videos) == result.videos
