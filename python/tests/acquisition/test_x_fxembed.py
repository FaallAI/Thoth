"""FxEmbed (FxTwitter API) parsers and client: X posts, replies, and profile media listings."""

from __future__ import annotations

import json
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest

from thoth_control_plane.acquisition.adapters.fxembed import (
    fx_engagement,
    fx_page,
    fx_profile,
    fx_text,
    fx_videos,
)
from thoth_control_plane.acquisition.models import (
    MAX_COMMENTS,
    AcquisitionReason,
    DiscoveryReason,
)
from thoth_control_plane.acquisition.threads_service import RequestFetchError
from thoth_control_plane.acquisition.x_fxembed import FxEmbedClient

FIXTURES = Path(__file__).resolve().parent.parent / "fixtures" / "x_fxembed"
POST_ID = "2110509448032862621"


def load(name: str) -> dict[str, Any]:
    return json.loads((FIXTURES / name).read_text(encoding="utf-8"))


def test_fx_videos_returns_each_video_best_mp4_in_order() -> None:
    urls = fx_videos(load("status_multi_video.json")["status"])
    assert len(urls) == 2
    assert all(".mp4" in url and url.startswith("https://") for url in urls)
    assert urls[0] != urls[1]


def test_fx_videos_is_empty_for_a_text_post() -> None:
    assert fx_videos(load("status_text.json")["status"]) == []


def test_fx_engagement_maps_to_report_keys() -> None:
    engagement = fx_engagement(load("status_multi_video.json")["status"])
    assert engagement == {"like": 6242, "comment": 87, "share": 3848, "play": 185497}


def test_fx_engagement_skips_missing_views() -> None:
    assert "play" not in fx_engagement(load("status_text.json")["status"])


def test_fx_text_is_the_display_text() -> None:
    assert fx_text(load("status_text.json")["status"]) == "just setting up my twttr"
    assert "t.co" not in (fx_text(load("status_single_video.json")["status"]) or "")


def test_fx_page_keeps_direct_replies_and_counts_drops() -> None:
    conversation = load("conversation.json")
    page = fx_page(load("status_multi_video.json")["status"], conversation["replies"], POST_ID)
    assert len(page.comments) == min(12, MAX_COMMENTS)
    assert page.dropped_comments == 2  # the reply to a reply and the author-less one
    assert all(c.comment_id.isdigit() and c.author for c in page.comments)
    assert not any(c.text.startswith("@") for c in page.comments)
    assert page.comments[0].comment_id == "2110532638704595241"
    assert len(page.videos) == 2
    assert page.engagement["play"] == 185497


def test_fx_page_without_status_still_returns_replies() -> None:
    page = fx_page(None, load("conversation.json")["replies"], POST_ID)
    assert page.videos == [] and page.engagement == {}
    assert len(page.comments) == 12


def test_fx_page_caps_comments() -> None:
    reply = load("conversation.json")["replies"][0]
    many = [{**reply, "id": str(3_000_000_000_000_000_000 + i)} for i in range(MAX_COMMENTS + 5)]
    page = fx_page(None, many, POST_ID)
    assert len(page.comments) == MAX_COMMENTS


def test_fx_profile_splits_videos_and_photos_and_drops_others() -> None:
    result = fx_profile(load("profile_media.json"), "InFebriyan128", 30)
    assert result.reason is None
    assert len(result.videos) == 10  # nine video posts and the mixed one
    assert len(result.photos) == 6
    assert result.drops.invalid == 2  # the repost and the other author's post
    assert result.drops.photo_posts == 6
    assert all(v.owner_handle == "InFebriyan128" for v in result.videos)
    assert all(
        str(v.canonical_url).startswith("https://x.com/InFebriyan128/status/")
        for v in result.videos
    )


def test_fx_profile_counts_a_mixed_post_as_video() -> None:
    result = fx_profile(load("profile_media.json"), "infebriyan128", 30)
    ids = {v.post_id for v in result.videos}
    assert "2113999999999999004" in ids
    assert "2113999999999999004" not in {p.post_id for p in result.photos}


def test_fx_profile_respects_the_limit() -> None:
    result = fx_profile(load("profile_media.json"), "InFebriyan128", 3)
    assert len(result.videos) == 3 and len(result.photos) == 3


@pytest.mark.parametrize("payload", [None, {}, {"code": 200, "results": []}])
def test_fx_profile_empty_is_typed_no_data(payload: object) -> None:
    assert fx_profile(payload, "InFebriyan128", 30).reason is DiscoveryReason.NO_DATA


def _response(status: int, body: str) -> SimpleNamespace:
    return SimpleNamespace(status=status, body=body.encode())


def _client(answer: object) -> tuple[FxEmbedClient, list[str]]:
    seen: list[str] = []

    async def get(url: str, **_: Any) -> Any:
        seen.append(url)
        if isinstance(answer, BaseException):
            raise answer
        return answer

    return FxEmbedClient(get, base_url="https://fx.test"), seen


async def test_client_reads_a_status() -> None:
    body = json.dumps(load("status_multi_video.json"))
    client, seen = _client(_response(200, body))
    status = await client.status(POST_ID)
    assert status is not None and status["id"] == POST_ID
    assert seen == [f"https://fx.test/2/status/{POST_ID}"]


async def test_client_reads_replies_and_profile_media() -> None:
    client, seen = _client(_response(200, json.dumps(load("conversation.json"))))
    assert len(await client.replies(POST_ID)) == 14
    client, seen = _client(_response(200, json.dumps(load("profile_media.json"))))
    payload = await client.profile_media("InFebriyan128", 30)
    assert payload is not None and len(payload["results"]) == 18
    assert seen == ["https://fx.test/2/profile/InFebriyan128/media?count=30"]


@pytest.mark.parametrize("status", [429, 500, 503])
async def test_client_refusals_are_blocked(status: int) -> None:
    client, _ = _client(_response(status, "{}"))
    with pytest.raises(RequestFetchError) as raised:
        await client.status(POST_ID)
    assert raised.value.reason is AcquisitionReason.REQUEST_BLOCKED


async def test_client_timeout_is_a_timeout() -> None:
    client, _ = _client(TimeoutError("slow"))
    with pytest.raises(RequestFetchError) as raised:
        await client.status(POST_ID)
    assert raised.value.reason is AcquisitionReason.REQUEST_TIMEOUT


@pytest.mark.parametrize(
    "response",
    [
        _response(404, "{}"),
        _response(200, json.dumps({"code": 404, "message": "NOT_FOUND"})),
        _response(200, "not json"),
    ],
)
async def test_client_missing_or_unreadable_is_none(response: SimpleNamespace) -> None:
    client, _ = _client(response)
    assert await client.status(POST_ID) is None
    assert await client.replies(POST_ID) == []
    assert await client.profile_media("InFebriyan128", 30) is None
