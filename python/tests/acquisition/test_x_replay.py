"""Sanitized golden fixtures replay through the X syndication parser and the FxEmbed merge."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from thoth_control_plane.acquisition import x_service
from thoth_control_plane.acquisition.adapters.fxembed import fx_page
from thoth_control_plane.acquisition.adapters.x import (
    XPostIdentity,
    parse_syndication,
    with_page,
)

FIXTURE_DIR = Path(__file__).resolve().parent.parent / "fixtures" / "x"
FX_DIR = Path(__file__).resolve().parent.parent / "fixtures" / "x_fxembed"
FIXTURES = {
    path.stem: json.loads(path.read_text(encoding="utf-8"))
    for path in sorted(FIXTURE_DIR.glob("*.json"))
}
POST_KINDS = ("video", "image", "text")


def test_all_three_kinds_are_present() -> None:
    assert set(FIXTURES) == set(POST_KINDS)


@pytest.mark.parametrize("kind", POST_KINDS)
def test_post_fixture_replays_to_its_expected_parse(kind: str) -> None:
    fixture = FIXTURES[kind]
    identity = XPostIdentity(post_id=fixture["post_id"])
    parsed = parse_syndication(fixture["document"]["syndication"], identity)
    assert parsed is not None
    assert {
        "owner_handle": parsed.post.owner_handle,
        "text": parsed.post.text,
        "media_kinds": [item.kind for item in parsed.media],
        "engagement": parsed.post.engagement,
        "published_at": parsed.post.published_at,
    } == fixture["expected"]


def test_post_kinds_have_their_shape() -> None:
    assert "video" in FIXTURES["video"]["expected"]["media_kinds"]
    assert set(FIXTURES["image"]["expected"]["media_kinds"]) == {"image"}
    assert FIXTURES["text"]["expected"]["media_kinds"] == []


def test_content_is_request_by_construction() -> None:
    assert x_service.CONTENT_METHOD == "request"
    assert {FIXTURES[kind]["method"] for kind in FIXTURES} == {"request"}


def test_the_fxembed_merge_brings_every_video_views_and_replies() -> None:
    fixture = FIXTURES["video"]
    identity = XPostIdentity(post_id=fixture["post_id"])
    status = json.loads((FX_DIR / "status_multi_video.json").read_text(encoding="utf-8"))
    replies = json.loads((FX_DIR / "conversation.json").read_text(encoding="utf-8"))["replies"]
    page = fx_page(status["status"], replies, status["status"]["id"])
    parsed = parse_syndication(fixture["document"]["syndication"], identity, page.videos)
    assert parsed is not None
    merged = with_page(parsed, page)
    assert [item.kind for item in merged.media].count("video") == 2
    assert {"play", "share"} <= set(merged.post.engagement)
    assert len(page.comments) == 12
