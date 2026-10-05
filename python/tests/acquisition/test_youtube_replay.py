"""Sanitized golden fixtures replay through the YouTube parser, the format choice, and discovery."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest

from thoth_control_plane.acquisition import youtube_service
from thoth_control_plane.acquisition.adapters.youtube import (
    MAX_DOWNLOAD_BYTES,
    YouTubeIdentity,
    channel_candidates,
    parse_info,
    select_formats,
    video_url,
)
from thoth_control_plane.acquisition.models import AcquisitionReason, ProfileDiscovery
from thoth_control_plane.acquisition.youtube_discovery import GRID_SIZE, YouTubeChannelDiscovery
from thoth_control_plane.acquisition.youtube_service import YtDlpError

FIXTURE_DIR = Path(__file__).resolve().parent.parent / "fixtures" / "youtube"
FIXTURES = {
    path.stem: json.loads(path.read_text(encoding="utf-8"))
    for path in sorted(FIXTURE_DIR.glob("*.json"))
}
POST_KINDS = ("video", "short")


def test_all_three_kinds_are_present() -> None:
    assert set(FIXTURES) == {"video", "short", "channel"}


@pytest.mark.parametrize("kind", POST_KINDS)
def test_post_fixture_replays_to_its_expected_parse(kind: str) -> None:
    fixture = FIXTURES[kind]
    document = fixture["document"]
    identity = YouTubeIdentity(canonical_url=video_url(document["id"]), video_id=document["id"])
    parsed = parse_info(document, identity)
    assert parsed is not None
    choice = select_formats(document["formats"], parsed.duration_seconds)
    assert choice is not None
    assert {
        "post": parsed.post.model_dump(mode="json"),
        "channel_url": parsed.channel_url,
        "duration_seconds": parsed.duration_seconds,
        "comments": [c.model_dump(mode="json", exclude={"card"}) for c in parsed.comments],
        "dropped_comments": parsed.dropped_comments,
        "choice": {
            "video_format": choice.video_format,
            "audio_format": choice.audio_format,
            "short_side": choice.short_side,
        },
    } == fixture["expected"]
    assert choice.estimated_bytes < MAX_DOWNLOAD_BYTES


def test_post_kinds_have_their_shape() -> None:
    for kind in POST_KINDS:
        expected = FIXTURES[kind]["expected"]
        assert expected["comments"], kind
        assert set(expected["post"]["engagement"]) >= {"play", "like"}
        assert expected["choice"]["short_side"] in (1080, 720, 480)
    # A Short is vertical: its resolution class is its width, the shorter side.
    short = FIXTURES["short"]["document"]
    video_format = FIXTURES["short"]["expected"]["choice"]["video_format"]
    chosen = next(f for f in short["formats"] if f["format_id"] == video_format)
    assert chosen["height"] > chosen["width"]


def test_content_is_yt_dlp_by_construction() -> None:
    assert youtube_service.CONTENT_METHOD == "yt_dlp"
    assert {FIXTURES[kind]["method"] for kind in FIXTURES} == {"yt_dlp"}


class _ReplayClient:
    def __init__(self, document: dict[str, Any]) -> None:
        self._document = document

    async def listing(self, url: str, limit: int) -> dict[str, Any]:
        return self._document["listings"][url.rsplit("/", 1)[1]]

    async def extract(self, url: str, *, comments: bool) -> dict[str, Any]:
        # The fixture keeps only the details the capture read; a missing one failed live.
        detail = self._document["details"].get(url.rsplit("=", 1)[1])
        if detail is None:
            raise YtDlpError(AcquisitionReason.REQUEST_BLOCKED)
        return detail


async def test_channel_fixture_replays_ranked() -> None:
    fixture = FIXTURES["channel"]
    document = fixture["document"]
    candidates = channel_candidates(document["listings"].values(), GRID_SIZE)
    assert candidates == fixture["expected"]["candidates"]

    async def no_sleep(seconds: float) -> None:
        return None

    discovery = YouTubeChannelDiscovery(_ReplayClient(document), no_sleep)  # type: ignore[arg-type]
    result = await discovery.discover(ProfileDiscovery(handle=fixture["handle"], limit=30))
    details = document["details"]
    assert details, "the capture must hold the candidates' details"
    assert {video.post_id for video in result.videos} <= set(candidates) & set(details)
    if set(candidates) <= set(details):
        assert result.reason is None
        assert len(result.videos) + result.drops.invalid == len(candidates)
