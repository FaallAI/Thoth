"""Instagram URL identity and pure parsing of anonymous page JSON."""

from __future__ import annotations

from typing import Any

import pytest

from thoth_control_plane.acquisition.adapters.instagram import (
    InstagramUrlError,
    canonical_instagram_share_url,
    canonicalize_instagram_post_url,
    login_required,
    parse_post,
)

CANONICAL = "https://www.instagram.com/p/code_001/"
IDENTITY = canonicalize_instagram_post_url(CANONICAL)


def _post(**extra: Any) -> dict[str, Any]:
    return {
        "code": "code_001",
        "pk": "3000000000000000001",
        "user": {"username": "user_001"},
        "caption": {"text": "hello world"},
        "taken_at": 1_700_000_000,
        "like_count": 1_200,
        "comment_count": 34,
        "media_type": 1,
        "image_versions2": {
            "candidates": [
                {"url": "https://img.example.test/small.jpg", "width": 320, "height": 320},
                {"url": "https://img.example.test/big.jpg", "width": 1080, "height": 1080},
            ]
        },
        **extra,
    }


def _raw_comment(n: int, **extra: Any) -> dict[str, Any]:
    return {
        "pk": str(18_000_000_000_000_000 + n),
        "text": f"comment {n}",
        "comment_like_count": n,
        "user": {"username": f"fan_{n:03d}"},
        **extra,
    }


def _connection(*nodes: object) -> dict[str, Any]:
    return {"edges": [{"node": node} for node in nodes]}


def _doc(post: dict[str, Any], connection: dict[str, Any] | None = None) -> dict[str, Any]:
    media: dict[str, Any] = {"if_not_gated_logged_out": post}
    if connection is not None:
        media["comments_connection"] = connection
    return {"require": [{"data": {"xig_polaris_media": media}}]}


def _urls(parsed) -> list[str]:
    return [item.ephemeral_url.get_secret_value() for item in parsed.media]


@pytest.mark.parametrize(
    "url",
    [
        "https://www.instagram.com/p/code_001/",
        "https://instagram.com/reel/code_001",
        "https://m.instagram.com/reels/code_001/?igsh=abc",
        "https://www.instagram.com/tv/code_001/#frag",
        "https://www.instagram.com/user_001/reel/code_001/",
        "https://www.instagram.com/user_001/p/code_001",
        "https://WWW.Instagram.COM./p/code_001/",
    ],
)
def test_post_url_shapes_canonicalize(url: str) -> None:
    identity = canonicalize_instagram_post_url(url)
    assert str(identity.canonical_url) == CANONICAL
    assert identity.post_id == "code_001"


@pytest.mark.parametrize(
    "url",
    [
        "https://www.instagram.com/user_001/",
        "https://instagr.am/p/code_001/",
        "http://www.instagram.com/p/code_001/",
        "https://www.instagram.com/p/bad*code/",
        "https://www.instagram.com:8443/p/code_001/",
        "https://user@www.instagram.com/p/code_001/",
        "https://notinstagram.com/p/code_001/",
        "https://www.instagram.com/stories/user_001/1234567/",
        "https://www.instagram.com/share/p/tok_001/",
        "https://www.instagram.com/share/tok_001/",
        "https://[::1",
    ],
)
def test_non_post_urls_are_rejected(url: str) -> None:
    with pytest.raises(InstagramUrlError):
        canonicalize_instagram_post_url(url)


@pytest.mark.parametrize(
    ("url", "share"),
    [
        ("https://www.instagram.com/share/tok_001/", "https://www.instagram.com/share/tok_001/"),
        (
            "https://www.instagram.com/share/reel/tok_001?igsh=x",
            "https://www.instagram.com/share/reel/tok_001/",
        ),
        ("https://instagram.com/share/p/tok_001/", "https://www.instagram.com/share/p/tok_001/"),
    ],
)
def test_share_url_shapes_canonicalize(url: str, share: str) -> None:
    assert canonical_instagram_share_url(url) == share


@pytest.mark.parametrize(
    "url",
    [
        "https://www.instagram.com/share/x/tok_001/",
        "https://www.instagram.com/p/code_001/",
        "http://www.instagram.com/share/tok_001/",
    ],
)
def test_non_share_urls_are_rejected(url: str) -> None:
    with pytest.raises(InstagramUrlError):
        canonical_instagram_share_url(url)


def test_image_post_parses_fields_and_the_widest_candidate() -> None:
    parsed = parse_post([_doc(_post())], IDENTITY)
    assert parsed is not None
    assert parsed.post.post_id == "code_001"
    assert parsed.post.owner_handle == "user_001"
    assert parsed.post.text == "hello world"
    assert parsed.post.published_at == "2023-11-14T22:13:20Z"
    assert parsed.post.engagement == {"like": 1_200, "comment": 34}
    assert [item.kind for item in parsed.media] == ["image"]
    assert _urls(parsed) == ["https://img.example.test/big.jpg"]
    assert parsed.comments == []


def test_video_post_takes_the_widest_video_version() -> None:
    versions = [
        {"url": "https://video.example.test/low.mp4", "width": 480, "height": 854},
        {"url": "https://video.example.test/high.mp4", "width": 720, "height": 1280},
    ]
    parsed = parse_post([_doc(_post(media_type=2, video_versions=versions))], IDENTITY)
    assert parsed is not None
    assert [item.kind for item in parsed.media] == ["video"]
    assert _urls(parsed) == ["https://video.example.test/high.mp4"]


def test_carousel_skips_urlless_items_in_order() -> None:
    carousel = [
        {"image_versions2": {"candidates": [{"url": "https://img.example.test/a.jpg"}]}},
        {"image_versions2": {"candidates": [{"url": "http://img.example.test/insecure.jpg"}]}},
        {"video_versions": [{"url": "https://video.example.test/b.mp4"}]},
        "not a dict",
        {"image_versions2": {"candidates": [{"url": "https://img.example.test/c.jpg"}]}},
    ]
    parsed = parse_post([_doc(_post(media_type=8, carousel_media=carousel))], IDENTITY)
    assert parsed is not None
    assert [item.kind for item in parsed.media] == ["image", "video", "image"]
    assert _urls(parsed) == [
        "https://img.example.test/a.jpg",
        "https://video.example.test/b.mp4",
        "https://img.example.test/c.jpg",
    ]


def test_carousel_is_capped_at_twenty() -> None:
    carousel = [
        {"image_versions2": {"candidates": [{"url": f"https://img.example.test/{n}.jpg"}]}}
        for n in range(25)
    ]
    parsed = parse_post([_doc(_post(carousel_media=carousel))], IDENTITY)
    assert parsed is not None
    assert len(parsed.media) == 20


def test_disabled_counts_give_empty_engagement() -> None:
    parsed = parse_post([_doc(_post(like_and_view_counts_disabled=True))], IDENTITY)
    assert parsed is not None
    assert parsed.post.engagement == {}


def test_null_caption_is_empty_text() -> None:
    parsed = parse_post([_doc(_post(caption=None))], IDENTITY)
    assert parsed is not None
    assert parsed.post.text == ""


def test_comments_parse_in_order_and_cap_at_fifty() -> None:
    comments = [_raw_comment(n) for n in range(1, 56)]
    parsed = parse_post([_doc(_post(), _connection(*comments))], IDENTITY)
    assert parsed is not None
    assert len(parsed.comments) == 50
    first = parsed.comments[0]
    assert (first.comment_id, first.author, first.text, first.likes, first.card) == (
        "18000000000000001",
        "fan_001",
        "comment 1",
        1,
        None,
    )
    assert parsed.dropped_comments == 0


def test_duplicate_comment_pk_keeps_the_first() -> None:
    connection = _connection(_raw_comment(1), _raw_comment(1, text="later copy"))
    parsed = parse_post([_doc(_post(), connection)], IDENTITY)
    assert parsed is not None
    assert [c.text for c in parsed.comments] == ["comment 1"]
    assert parsed.dropped_comments == 1


def test_invalid_comments_are_dropped_and_counted() -> None:
    connection = _connection(
        _raw_comment(1, pk="not-numeric"),
        _raw_comment(2, text="   "),
        _raw_comment(3, text="x" * 2_001),
        _raw_comment(4, user={"username": "bad name"}),
        _raw_comment(5, user=None),
        "not a dict",
        _raw_comment(6),
    )
    parsed = parse_post([_doc(_post(), connection)], IDENTITY)
    assert parsed is not None
    assert [c.author for c in parsed.comments] == ["fan_006"]
    assert parsed.dropped_comments == 6


def test_a_connection_outside_the_post_holder_is_used() -> None:
    loose = {"xig_polaris_media": {"comments_connection": _connection(_raw_comment(1))}}
    parsed = parse_post([_doc(_post()), loose], IDENTITY)
    assert parsed is not None
    assert [c.author for c in parsed.comments] == ["fan_001"]


@pytest.mark.parametrize("user", [{}, {"username": None}, {"username": "bad name"}])
def test_missing_or_invalid_owner_is_no_parse(user: dict[str, Any]) -> None:
    assert parse_post([_doc(_post(user=user))], IDENTITY) is None


def test_other_post_code_is_no_parse() -> None:
    assert parse_post([_doc(_post(code="other_01"))], IDENTITY) is None


def test_login_required_reads_root_documents_only() -> None:
    assert login_required([{"message": "x", "require_login": True, "status": "fail"}])
    assert not login_required([_doc(_post())])
    assert not login_required([{"data": {"require_login": True}}])
