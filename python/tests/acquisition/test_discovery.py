import json

import pytest

from thoth_control_plane.acquisition.discovery import parse_discovery_page
from thoth_control_plane.acquisition.models import DiscoveryDrops, DiscoveryReason


def _item(post_id: object = "1000000001", handle: str = "creator", **extra: object) -> dict:
    item = {
        "id": post_id,
        "desc": "a caption #cats",
        "createTime": 1709287200,
        "author": {"uniqueId": handle, "secUid": "MS4wLjABAAAA", "verified": False},
        "stats": {
            "playCount": 10,
            "diggCount": 5,
            "commentCount": 2,
            "shareCount": 1,
            "collectCount": 3,
        },
        "video": {"duration": 15},
        "challenges": [{"title": "cats"}],
    }
    item.update(extra)
    return item


def _list_body(items: list, has_more: object = True) -> bytes:
    return json.dumps({"statusCode": 0, "itemList": items, "hasMore": has_more}).encode()


def _search_body(entries: list, has_more: object = 1) -> bytes:
    return json.dumps({"status_code": 0, "data": entries, "has_more": has_more}).encode()


@pytest.mark.parametrize("kind", ["profile", "trending"])
def test_list_pages_reduce_to_validated_videos(kind: str) -> None:
    page = parse_discovery_page(kind, _list_body([_item()]))

    assert page.reason is None
    assert page.has_more is True
    assert page.drops == DiscoveryDrops()
    [video] = page.videos
    assert video.post_id == "1000000001"
    assert video.owner_handle == "creator"
    assert str(video.canonical_url) == "https://www.tiktok.com/@creator/video/1000000001"
    assert video.caption == "a caption #cats"
    assert video.published_at == "2024-03-01T10:00:00Z"
    assert video.duration_seconds == 15.0
    assert video.engagement == {"play": 10, "like": 5, "comment": 2, "share": 1, "collect": 3}
    assert video.hashtags == ["cats"]


def test_search_pages_keep_only_video_entries() -> None:
    body = _search_body(
        [
            {"type": 1, "item": _item("1000000001"), "common": {}},
            {"type": 4, "user_list": [{"uniqueId": "someone"}]},
            {"type": 1, "item": _item("1000000002"), "common": {}},
        ]
    )

    page = parse_discovery_page("keyword", body)

    assert [video.post_id for video in page.videos] == ["1000000001", "1000000002"]
    assert page.drops == DiscoveryDrops()
    assert page.has_more is True


@pytest.mark.parametrize(
    ("value", "expected"),
    [(True, True), (1, True), (False, False), (0, False), (None, False), ("true", False)],
)
def test_has_more_is_true_only_for_true_or_one(value: object, expected: bool) -> None:
    assert (
        parse_discovery_page("profile", _list_body([_item()], has_more=value)).has_more is expected
    )


def test_ads_photo_posts_and_invalid_items_are_dropped_and_counted() -> None:
    items = [
        _item("1000000001"),
        _item("1000000002", isAd=True),
        _item("1000000003", imagePost={"images": []}),
        _item(1000000004),
        _item("12"),
        _item("1000000006", author={}),
        "junk",
    ]

    page = parse_discovery_page("profile", _list_body(items))

    assert [video.post_id for video in page.videos] == ["1000000001"]
    assert page.drops == DiscoveryDrops(ads=1, photo_posts=1, invalid=4)


def test_an_ad_that_is_also_a_photo_post_counts_as_an_ad() -> None:
    page = parse_discovery_page("profile", _list_body([_item(isAd=True, imagePost={})]))

    assert page.drops == DiscoveryDrops(ads=1)


@pytest.mark.parametrize("body", [b"", b"<html></html>", b"[]", b"\xff\xfe"])
def test_empty_or_non_object_bodies_are_captcha(body: bytes) -> None:
    page = parse_discovery_page("keyword", body)

    assert page.reason is DiscoveryReason.CAPTCHA
    assert page.videos == []
    assert page.has_more is False


@pytest.mark.parametrize(
    ("kind", "payload"),
    [
        ("profile", {"statusCode": 10201, "itemList": [_item()], "hasMore": True}),
        ("keyword", {"status_code": 5, "data": [], "has_more": 1}),
    ],
)
def test_non_zero_status_is_blocked(kind: str, payload: dict) -> None:
    page = parse_discovery_page(kind, json.dumps(payload).encode())

    assert page.reason is DiscoveryReason.BLOCKED
    assert page.videos == []


def test_canonical_url_is_rebuilt_never_taken_from_tiktok() -> None:
    item = _item(shareUrl="https://evil.example/@creator/video/1000000001")

    [video] = parse_discovery_page("profile", _list_body([item])).videos

    assert str(video.canonical_url) == "https://www.tiktok.com/@creator/video/1000000001"


def test_caption_is_truncated_and_a_non_string_desc_is_empty() -> None:
    items = [_item("1000000001", desc="x" * 10_050), _item("1000000002", desc=None)]

    long_caption, no_caption = parse_discovery_page("profile", _list_body(items)).videos

    assert len(long_caption.caption) == 10_000
    assert no_caption.caption == ""


@pytest.mark.parametrize("duration", [True, -1, float("nan"), float("inf"), "15"])
def test_invalid_duration_is_none_and_the_video_is_kept(duration: object) -> None:
    [video] = parse_discovery_page(
        "profile", _list_body([_item(video={"duration": duration})])
    ).videos

    assert video.duration_seconds is None


def test_bad_hashtags_are_dropped_and_the_video_is_kept() -> None:
    challenges = [{"title": ""}, {"title": "x" * 101}, {"title": 5}, "junk", {"title": "ok"}]

    [video] = parse_discovery_page("profile", _list_body([_item(challenges=challenges)])).videos

    assert video.hashtags == ["ok"]


def test_missing_stats_yield_empty_engagement() -> None:
    item = _item()
    del item["stats"]

    [video] = parse_discovery_page("trending", _list_body([item])).videos

    assert video.engagement == {}
