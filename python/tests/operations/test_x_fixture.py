"""X fixture tooling: sanitizing, leak checking, and the replay of sanitized documents."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest

from thoth_control_plane.acquisition.adapters.x import (
    XPostIdentity,
    parse_page,
    parse_syndication,
    with_page,
)
from thoth_control_plane.acquisition.x_discovery import parse_profile
from thoth_control_plane.operations import x_fixture
from thoth_control_plane.operations.threads_fixture import _leaves, leak_count
from thoth_control_plane.operations.x_fixture import build_post, build_profile, main

POST_ID = "1800000000000000001"
REPLY_ID = "1800000000000000101"
SECRETS = (
    "realperson",
    "Secret caption about Jakarta",
    "SECRETMEDIA",
    "SECRETVID",
    "fan_one",
    "Totally private comment",
    POST_ID,
    REPLY_ID,
    "2024-05-01T12:34:56",
    "4537",
)


def _syndication() -> dict[str, Any]:
    return {
        "__typename": "Tweet",
        "id_str": POST_ID,
        "text": "Secret caption about Jakarta https://t.co/abcd",
        "display_text_range": [0, 28],
        "created_at": "2024-05-01T12:34:56.000Z",
        "favorite_count": 1_234,
        "conversation_count": 56,
        "user": {"screen_name": "realperson", "name": "Real Person"},
        "mediaDetails": [
            {"type": "photo", "media_url_https": "https://pbs.twimg.com/media/SECRETMEDIA.jpg"},
            {"type": "video"},
        ],
        "video": {
            "variants": [
                {"type": "video/mp4", "src": "https://video.twimg.com/vid/1280x720/SECRETVID.mp4"}
            ]
        },
    }


def _tweet(rest_id: str, author: str, text: str, reply_to: str | None) -> dict[str, Any]:
    node: dict[str, Any] = {
        "__typename": "Tweet",
        "rest_id": rest_id,
        "core": {"user_results": {"result": {"core": {"screen_name": author}}}},
        "details": {"full_text": text, "created_at_ms": 1_714_566_896_000},
        "counts": {"favorite_count": 7, "reply_count": 1, "retweet_count": 23},
        "views": {"count": "4537"},
    }
    if reply_to is not None:
        node["reply_to_results"] = {"rest_id": reply_to}
    return node


def _html(*tweets: dict[str, Any]) -> str:
    root = json.dumps({"entries": list(tweets)}, separators=(",", ":"))
    return f'<script>($R=>$R[0].next({root}))($R["k"])</script>'


def _post_raw() -> dict[str, Any]:
    post = _tweet(POST_ID, "realperson", "Secret caption about Jakarta", None)
    video = {
        "type": "video",
        "video_info": {
            "variants": [
                {
                    "content_type": "video/mp4",
                    "url": "https://video.twimg.com/vid/1280x720/SECRETVID.mp4",
                }
            ]
        },
    }
    post["media_entities2"] = [{"type": "photo"}, video]
    reply = _tweet(REPLY_ID, "fan_one", "@realperson Totally private comment", POST_ID)
    return {
        "kind": "video",
        "post_id": POST_ID,
        "syndication": {"status": "ok", "data": _syndication()},
        "page": {"status": "ok", "html": _html(post, reply)},
        "cards": None,
    }


def _no_leak(fixture: dict[str, Any], scope: dict[str, Any]) -> None:
    text = json.dumps(fixture, ensure_ascii=False)
    assert [secret for secret in SECRETS if secret in text] == []
    leaves = "\n".join(sorted(_leaves(fixture)))
    assert leak_count(x_fixture._without_enums(scope), leaves) == 0


def test_post_fixture_carries_no_original_value_and_replays() -> None:
    fixture, scope = build_post(_post_raw())
    _no_leak(fixture, scope)
    identity = XPostIdentity(post_id=fixture["post_id"])
    document = fixture["document"]
    page = parse_page([document["page"]], identity)
    parsed = with_page(parse_syndication(document["syndication"], identity, page.videos), page)
    assert parsed.post.owner_handle == "user_001"
    assert [item.kind for item in parsed.media] == ["image", "video"]
    video_url = parsed.media[1].ephemeral_url.get_secret_value()
    assert "/1280x720/" in video_url and video_url.startswith("https://media.example.test/")
    assert parsed.post.engagement == {"like": 1_200, "comment": 56, "share": 23, "play": 4_500}
    assert [(c.author, c.likes) for c in page.comments] == [("user_002", 7)]
    assert fixture["expected"]["media_kinds"] == ["image", "video"]
    assert fixture["expected"]["comments"] == [
        c.model_dump(mode="json", exclude={"card"}) for c in page.comments
    ]
    assert fixture["counts"]["replies"] == 1


def test_a_missing_tweet_is_refused() -> None:
    raw = _post_raw()
    raw["syndication"] = {"status": "ok", "data": None}
    with pytest.raises(ValueError):
        build_post(raw)


def test_profile_fixture_keeps_own_videos_and_the_page_spelling() -> None:
    def video(n: int, author: str, likes: int) -> dict[str, Any]:
        node = _tweet(str(1_800_000_000_000_000_000 + n), author, f"post {n}", None)
        node["counts"]["favorite_count"] = likes
        variants = [{"content_type": "video/mp4", "url": f"https://video.twimg.com/{n}.mp4"}]
        node["media_entities2"] = [{"type": "video", "video_info": {"variants": variants}}]
        return node

    tweets = [video(1, "RealPerson", 900), video(2, "someone_else", 5), video(3, "RealPerson", 50)]
    page = {"status": "ok", "html": _html(*tweets)}
    fixture, _ = build_profile({"kind": "profile", "handle": "realperson", "page": page})
    assert fixture["handle"] == "user_001"
    assert len(fixture["expected"]["post_ids"]) == 2
    assert fixture["expected"]["drops"] == {"ads": 0, "photo_posts": 0, "invalid": 1}
    result = parse_profile([fixture["document"]], fixture["handle"], 30)
    assert [v.post_id for v in result.videos] == fixture["expected"]["post_ids"]
    assert "RealPerson" not in json.dumps(fixture)


def test_main_writes_a_clean_fixture(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    raw_path, out = tmp_path / "video.json", tmp_path / "out.json"
    raw_path.write_text(json.dumps(_post_raw()), encoding="utf-8")
    assert main(["--raw", str(raw_path), "--out", str(out)]) == 0
    printed = capsys.readouterr().out
    assert json.loads(printed)["leaks"] == 0
    assert [secret for secret in SECRETS if secret in printed] == []
    assert json.loads(out.read_text(encoding="utf-8"))["kind"] == "video"


def test_main_refuses_to_write_a_leaking_fixture(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    leaking = (
        {"kind": "video", "method": "request", "counts": {}, "document": {"x": "realperson"}},
        {"u": "realperson"},
    )
    monkeypatch.setattr(x_fixture, "build", lambda raw: leaking)
    raw_path, out = tmp_path / "video.json", tmp_path / "out.json"
    raw_path.write_text("{}", encoding="utf-8")
    assert main(["--raw", str(raw_path), "--out", str(out)]) == 1
    assert not out.exists()
