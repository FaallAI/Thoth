"""Threads URL identity and pure post parsing over synthetic documents."""

from __future__ import annotations

import json

import pytest

from thoth_control_plane.acquisition.adapters.threads import (
    ThreadsUrlError,
    canonicalize_threads_post_url,
    json_roots,
    parse_documents,
)
from thoth_control_plane.acquisition.models import MAX_POST_TEXT

IDENTITY = canonicalize_threads_post_url("https://www.threads.com/@user_001/post/code_001")


def _node(**extra: object) -> dict[str, object]:
    return {
        "code": "code_001",
        "user": {"username": "user_001"},
        "caption": {"text": "hello world"},
        "taken_at": 1_700_000_000,
        "like_count": 12,
        "text_post_app_info": {
            "direct_reply_count": 3,
            "repost_count": 2,
            "quote_count": 1,
            "reshare_count": 4,
        },
        "image_versions2": {"candidates": []},
        **extra,
    }


def _doc(node: dict[str, object]) -> dict[str, object]:
    return {"require": [{"data": {"thread_items": [{"post": node}]}}]}


def _image(n: int) -> dict[str, object]:
    return {
        "image_versions2": {
            "candidates": [
                {"url": f"https://img.example.test/{n}-small.jpg", "width": 320, "height": 320},
                {"url": f"https://img.example.test/{n}-large.jpg", "width": 1080, "height": 1350},
            ]
        }
    }


@pytest.mark.parametrize(
    "url",
    [
        "https://www.threads.com/@user_001/post/code_001",
        "https://www.threads.net/@user_001/post/code_001/",
        "https://threads.net/@user_001/post/code_001?xmt=abc&slof=1",
        "https://m.threads.com/@user_001/post/code_001#frag",
        "https://WWW.THREADS.NET/@user_001/post/code_001",
    ],
)
def test_canonicalize_threads_post_url_accepts_variants(url: str) -> None:
    identity = canonicalize_threads_post_url(url)
    assert str(identity.canonical_url) == "https://www.threads.com/@user_001/post/code_001"
    assert (identity.post_id, identity.owner_handle) == ("code_001", "user_001")


@pytest.mark.parametrize(
    "url",
    [
        "http://www.threads.com/@user_001/post/code_001",
        "https://www.threads.com/@user_001",
        "https://www.threads.com/@user_001/post/code/001",
        "https://www.instagram.com/@user_001/post/code_001",
        "https://user:pw@www.threads.com/@user_001/post/code_001",
        "https://www.threads.com:8443/@user_001/post/code_001",
        "https://[::1",
    ],
)
def test_canonicalize_threads_post_url_rejects_other_shapes(url: str) -> None:
    with pytest.raises(ThreadsUrlError):
        canonicalize_threads_post_url(url)


def test_text_only_post_parses_without_media() -> None:
    parsed = parse_documents([_doc(_node())], IDENTITY)
    assert parsed is not None
    assert parsed.post.text == "hello world"
    assert parsed.media == []
    assert parsed.post.published_at == "2023-11-14T22:13:20Z"
    assert parsed.post.engagement == {"like": 12, "comment": 3, "repost": 2, "quote": 1, "share": 4}


def test_video_post_yields_one_video() -> None:
    node = _node(video_versions=[{"url": "https://v.example.test/1.mp4"}], **_image(0))
    parsed = parse_documents([_doc(node)], IDENTITY)
    assert parsed is not None
    assert [item.kind for item in parsed.media] == ["video"]
    assert parsed.media[0].ephemeral_url.get_secret_value() == "https://v.example.test/1.mp4"


def test_carousel_keeps_every_item_and_picks_the_largest_image() -> None:
    node = _node(carousel_media=[_image(n) for n in range(22)])
    parsed = parse_documents([_doc(node)], IDENTITY)
    assert parsed is not None
    assert len(parsed.media) == 22  # the acquirer caps; the parser reports what it saw
    assert {item.kind for item in parsed.media} == {"image"}
    assert parsed.media[0].media_type is None
    assert (
        parsed.media[0].ephemeral_url.get_secret_value() == "https://img.example.test/0-large.jpg"
    )


@pytest.mark.parametrize(
    "node",
    [
        {k: v for k, v in _node().items() if k != "user"},
        _node(code="other_code"),
    ],
)
def test_parse_returns_none_without_the_matching_post(node: dict[str, object]) -> None:
    assert parse_documents([_doc(node)], IDENTITY) is None


def test_missing_optional_fields_degrade_to_defaults() -> None:
    node = {"code": "code_001", "user": {"username": "user_001"}}
    parsed = parse_documents([_doc(node)], IDENTITY)
    assert parsed is not None
    assert (parsed.post.text, parsed.post.published_at, parsed.post.engagement) == ("", None, {})


def test_text_is_truncated_to_the_contract_limit() -> None:
    node = _node(caption={"text": "x" * (MAX_POST_TEXT + 10)})
    parsed = parse_documents([_doc(node)], IDENTITY)
    assert parsed is not None
    assert len(parsed.post.text) == MAX_POST_TEXT


def test_json_roots_skips_non_json_texts() -> None:
    assert json_roots(["not json", json.dumps({"a": 1}), ""]) == [{"a": 1}]
