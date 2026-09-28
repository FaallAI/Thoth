"""Threads fixture tooling: sanitizing, leak checking, and the method decision."""

from __future__ import annotations

import json

import pytest

from thoth_control_plane.acquisition.adapters.threads import (
    canonicalize_threads_post_url,
    parse_documents,
)
from thoth_control_plane.operations.threads_fixture import (
    build_fixture,
    counts,
    decide,
    leak_count,
)

SECRETS = ("realperson", "Secret caption about Jakarta", "scontent.cdninstagram", "Xy9Qk2Lm")


def _raw_node() -> dict[str, object]:
    return {
        "code": "Xy9Qk2Lm",
        "pk": "3141592653589793",
        "user": {
            "username": "realperson",
            "profile_pic_url": "https://scontent.cdninstagram.com/p.jpg",
        },
        "caption": {"text": "Secret caption about Jakarta"},
        "taken_at": 1_726_000_123,
        "like_count": 1_234,
        "text_post_app_info": {
            "direct_reply_count": 56,
            "repost_count": 7,
            "quote_count": 0,
            "reshare_count": 89,
        },
        "carousel_media": [
            {
                "image_versions2": {
                    "candidates": [
                        {
                            "url": "https://scontent.cdninstagram.com/a.jpg?sig=1",
                            "width": 1080,
                            "height": 1350,
                        },
                        {
                            "url": "https://scontent.cdninstagram.com/b.jpg?sig=2",
                            "width": 320,
                            "height": 400,
                        },
                    ]
                }
            },
            {"video_versions": [{"url": "https://scontent.cdninstagram.com/v.mp4?sig=3"}]},
        ],
    }


def _raw(request_status: str = "ok") -> dict[str, object]:
    document = json.dumps({"require": [{"thread_items": [{"post": _raw_node()}]}]})
    return {
        "kind": "image",
        "post_id": "Xy9Qk2Lm",
        "owner": "realperson",
        "request": {
            "status": request_status,
            "script_texts": [document] if request_status == "ok" else [],
        },
        "headless": {"status": "ok", "xhr_bodies": [], "script_texts": [document], "card": True},
    }


def test_fixture_carries_no_original_value_and_still_parses() -> None:
    fixture = build_fixture(_raw())
    text = json.dumps(fixture, ensure_ascii=False)

    assert [secret for secret in SECRETS if secret in text] == []
    assert leak_count(_raw_node(), text) == 0
    assert fixture["identity"] == {"post_id": "code_001", "owner_handle": "user_001"}
    assert fixture["method"] == "request"

    identity = canonicalize_threads_post_url("https://www.threads.com/@user_001/post/code_001")
    parsed = parse_documents([fixture["document"]], identity)
    assert parsed is not None
    assert [item.kind for item in parsed.media] == ["image", "video"]
    assert parsed.post.engagement == {
        "like": 1_200,
        "comment": 56,
        "repost": 7,
        "quote": 0,
        "share": 89,
    }
    assert fixture["expected"]["media_kinds"] == ["image", "video"]
    assert fixture["expected"]["text"] == parsed.post.text != "Secret caption about Jakarta"


def test_blocked_request_falls_back_to_the_headless_document() -> None:
    fixture = build_fixture(_raw(request_status="request_blocked"))
    assert fixture["method"] == "headless"
    assert fixture["counts"]["request"] is None
    assert fixture["counts"]["headless"]["media"] == 2


def test_weaker_request_document_falls_back_to_headless() -> None:
    """Request parses but with fewer media items than headless; decide() should pick headless."""
    # Simulate request capturing only the first media item
    document_weak = json.dumps(
        {
            "require": [
                {
                    "thread_items": [
                        {
                            "post": {
                                **_raw_node(),
                                "carousel_media": [_raw_node()["carousel_media"][0]],
                            }
                        }
                    ]
                }
            ]
        }
    )
    raw = {
        "kind": "image",
        "post_id": "Xy9Qk2Lm",
        "owner": "realperson",
        "request": {"status": "ok", "script_texts": [document_weak]},
        "headless": {
            "status": "ok",
            "xhr_bodies": [],
            "script_texts": [json.dumps({"require": [{"thread_items": [{"post": _raw_node()}]}]})],
            "card": True,
        },
    }
    fixture = build_fixture(raw)
    assert fixture["method"] == "headless"
    assert fixture["counts"]["request"]["media"] == 1
    assert fixture["counts"]["headless"]["media"] == 2
    assert fixture["expected"]["media_kinds"] == ["image", "video"]


def test_leak_count_flags_a_surviving_value() -> None:
    assert leak_count(_raw_node(), "... realperson ...") == 1


def test_counts_of_a_missing_parse_are_none() -> None:
    assert counts(None) is None


@pytest.mark.parametrize(
    ("pairs", "method"),
    [
        ([({"found": 1, "media": 2}, {"found": 1, "media": 2})], "request"),
        ([({"found": 1, "media": 3}, {"found": 1, "media": 2})], "request"),
        ([({"found": 1, "media": 1}, {"found": 1, "media": 2})], "headless"),
        ([(None, {"found": 1, "media": 2})], "headless"),
        ([({"found": 1, "media": 2}, None)], "request"),
        (
            [
                ({"found": 1, "media": 2}, {"found": 1, "media": 2}),
                (None, {"found": 1, "media": 0}),
            ],
            "headless",
        ),
    ],
)
def test_decide_prefers_request_only_when_it_never_loses(pairs, method) -> None:
    assert decide(pairs) == method
