"""Instagram fixture tooling: sanitizing, leak checking, and the method decisions."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest

from thoth_control_plane.acquisition.adapters.instagram import (
    canonicalize_instagram_post_url,
    parse_post,
)
from thoth_control_plane.acquisition.instagram_discovery import TIMELINE_KEY, parse_profile
from thoth_control_plane.operations import instagram_fixture
from thoth_control_plane.operations.instagram_fixture import (
    build_post,
    build_profile,
    decide_share,
    main,
)
from thoth_control_plane.operations.threads_fixture import _leaves, leak_count

SECRETS = (
    "realperson",
    "Secret caption about Jakarta",
    "scontent.cdninstagram",
    "Xy9Qk2Lm",
    "fanatic_one",
    "Totally private comment",
    "3141592653589793",
)
IDENTITY = canonicalize_instagram_post_url("https://www.instagram.com/p/code_001/")


def _raw_node(**extra: Any) -> dict[str, Any]:
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
        "comment_count": 56,
        "media_type": 8,
        "carousel_media": [
            {
                "media_type": 1,
                "image_versions2": {
                    "candidates": [
                        {
                            "url": "https://scontent.cdninstagram.com/a.jpg?sig=1",
                            "width": 1080,
                            "height": 1350,
                        }
                    ]
                },
            },
            {
                "media_type": 2,
                "video_versions": [
                    {
                        "url": "https://scontent.cdninstagram.com/v.mp4?sig=3",
                        "width": 720,
                        "height": 1280,
                    }
                ],
            },
        ],
        **extra,
    }


def _raw_comment() -> dict[str, Any]:
    return {
        "pk": "17900000000000001",
        "text": "Totally private comment",
        "comment_like_count": 7,
        "user": {"username": "fanatic_one"},
    }


def _doc(node: dict[str, Any], comments: list[dict[str, Any]] | None) -> str:
    media: dict[str, Any] = {"if_not_gated_logged_out": node}
    if comments is not None:
        media["comments_connection"] = {"edges": [{"node": c} for c in comments]}
    return json.dumps({"require": [{"xig_polaris_media": media}]})


def _raw(request: dict[str, Any] | None = None) -> dict[str, Any]:
    full = _doc(_raw_node(), [_raw_comment()])
    return {
        "kind": "carousel",
        "post_id": "Xy9Qk2Lm",
        "request": request or {"status": "ok", "script_texts": [full]},
        "headless": {"status": "ok", "script_texts": [full]},
        "cards": None,
    }


def _no_leak(fixture: dict[str, Any], scope: dict[str, Any]) -> None:
    text = json.dumps(fixture, ensure_ascii=False)
    assert [secret for secret in SECRETS if secret in text] == []
    assert leak_count(scope, "\n".join(sorted(_leaves(fixture)))) == 0


def test_post_fixture_carries_no_original_value_and_still_parses() -> None:
    fixture, scope = build_post(_raw())
    _no_leak(fixture, scope)
    assert fixture["method"] == "request"

    parsed = parse_post([fixture["document"]], IDENTITY)
    assert parsed is not None
    assert parsed.post.owner_handle == "user_001"
    assert [item.kind for item in parsed.media] == ["image", "video"]
    assert parsed.post.engagement == {"like": 1_200, "comment": 56}
    assert [(c.author, c.likes) for c in parsed.comments] == [("user_002", 7)]
    assert fixture["expected"]["comments"] == [
        c.model_dump(mode="json", exclude={"card"}) for c in parsed.comments
    ]
    assert fixture["expected"]["media_kinds"] == ["image", "video"]


def test_request_without_comments_loses_to_headless() -> None:
    weaker = {"status": "ok", "script_texts": [_doc(_raw_node(), None)]}
    fixture, _ = build_post(_raw(weaker))
    assert fixture["method"] == "headless"
    assert fixture["counts"]["request"]["comments"] == 0
    assert fixture["counts"]["headless"]["comments"] == 1


def test_blocked_request_uses_the_headless_document() -> None:
    fixture, _ = build_post(_raw({"status": "request_blocked", "script_texts": []}))
    assert fixture["method"] == "headless"
    assert fixture["counts"]["request"] is None


def _grid_node(code: str, pk: str, media_type: int, likes: int) -> dict[str, Any]:
    return {
        "code": code,
        "pk": pk,
        "media_type": media_type,
        "user": {"username": "realperson"},
        "caption": {"text": "Secret caption about Jakarta"},
        "taken_at": 1_726_000_123,
        "like_count": likes,
        "comment_count": 3,
    }


def test_profile_fixture_replays_like_sorted_videos() -> None:
    nodes = [
        _grid_node("AbC123xyz", "3141592653589001", 2, 900),
        _grid_node("DeF456xyz", "3141592653589002", 1, 5_000),
        _grid_node("GhI789xyz", "3141592653589003", 2, 4_000),
    ]
    user = {"username": "realperson", TIMELINE_KEY: {"edges": [{"node": n} for n in nodes]}}
    raw = {
        "kind": "profile",
        "handle": "realperson",
        "request": {
            "status": "ok",
            "script_texts": [json.dumps({"require": [{"xig_user_by_username": user}]})],
        },
    }
    fixture, scope = build_profile(raw)
    _no_leak(fixture, scope)
    assert fixture["handle"] == "user_001"
    assert set(fixture["expected"]) == {"post_ids", "drops"}
    assert fixture["expected"]["drops"] == {"ads": 0, "photo_posts": 1, "invalid": 0}
    result = parse_profile([fixture["document"]], fixture["handle"], 30)
    assert [v.post_id for v in result.videos] == fixture["expected"]["post_ids"]
    assert [v.engagement["like"] for v in result.videos] == [4_000, 900]


@pytest.mark.parametrize(
    ("request_result", "method"),
    [
        ({"status": "ok", "lands_on_post": True}, "request"),
        ({"status": "ok", "lands_on_post": False}, "headless"),
        ({"status": "request_blocked", "lands_on_post": False}, "headless"),
    ],
)
def test_decide_share(request_result: dict[str, Any], method: str) -> None:
    raw = {
        "kind": "share",
        "request": request_result,
        "headless": {"status": "ok", "lands_on_post": True},
    }
    assert decide_share(raw) == method


def test_main_writes_a_clean_fixture(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    raw_path, out = tmp_path / "carousel.json", tmp_path / "out.json"
    raw_path.write_text(json.dumps(_raw()), encoding="utf-8")
    assert main(["--raw", str(raw_path), "--out", str(out)]) == 0
    printed = capsys.readouterr().out
    assert json.loads(printed)["leaks"] == 0
    assert [secret for secret in SECRETS if secret in printed] == []
    assert json.loads(out.read_text(encoding="utf-8"))["kind"] == "carousel"


def test_main_writes_a_fixture_whose_emoji_only_comment_survives(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    # The pseudonymizer keeps symbols by design; a letterless comment identifies no one.
    raw = _raw()
    emoji = {**_raw_comment(), "pk": "17900000000000002", "text": "🔥🔥🔥🔥🔥"}
    full = _doc(_raw_node(), [_raw_comment(), emoji])
    raw["request"] = raw["headless"] = {"status": "ok", "script_texts": [full]}
    raw_path, out = tmp_path / "carousel.json", tmp_path / "out.json"
    raw_path.write_text(json.dumps(raw), encoding="utf-8")
    assert main(["--raw", str(raw_path), "--out", str(out)]) == 0
    assert json.loads(capsys.readouterr().out)["leaks"] == 0
    assert out.exists()


def test_main_refuses_to_write_a_leaking_fixture(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    leaking = (
        {"kind": "image", "method": "request", "document": {"x": "realperson"}},
        {"u": "realperson"},
    )
    monkeypatch.setattr(instagram_fixture, "build", lambda raw: leaking)
    raw_path, out = tmp_path / "image.json", tmp_path / "out.json"
    raw_path.write_text("{}", encoding="utf-8")
    assert main(["--raw", str(raw_path), "--out", str(out)]) == 1
    assert not out.exists()
