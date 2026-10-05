"""YouTube fixture tooling: sanitizing, leak checking, and the replay of sanitized documents."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest

from thoth_control_plane.acquisition.adapters.youtube import (
    YouTubeIdentity,
    parse_info,
    select_formats,
    video_url,
)
from thoth_control_plane.operations import youtube_fixture
from thoth_control_plane.operations.threads_fixture import _leaves, leak_count
from thoth_control_plane.operations.youtube_fixture import build_channel, build_post, main

MB = 1024 * 1024
SECRETS = (
    "realVideo01",
    "realperson",
    "UCrealchannel0000000000a",
    "Secret title about Jakarta",
    "Secret description",
    "fan_one",
    "Totally private comment",
    "UgzRealCommentId",
    "googlevideo",
    "2024-05-01",
)


def _raw_info() -> dict[str, Any]:
    return {
        "id": "realVideo01",
        "title": "Secret title about Jakarta",
        "description": "Secret description",
        "uploader": "Real Person",
        "uploader_id": "@realperson",
        "uploader_url": "https://www.youtube.com/@realperson",
        "channel_id": "UCrealchannel0000000000a",
        "channel_url": "https://www.youtube.com/channel/UCrealchannel0000000000a",
        "upload_date": "2024-05-01",
        "timestamp": 1_714_566_896,
        "duration": 600,
        "view_count": 4_537,
        "like_count": 123,
        "comment_count": 45,
        "live_status": "not_live",
        "formats": [
            {
                "format_id": "137",
                "protocol": "https",
                "url": "https://rr1.googlevideo.com/videoplayback?sig=secret",
                "ext": "mp4",
                "vcodec": "avc1.640028",
                "acodec": "none",
                "width": 1920,
                "height": 1080,
                "tbr": 2_000.5,
                "filesize": 150 * MB + 7,
            },
            {
                "format_id": "140",
                "protocol": "https",
                "url": "https://rr1.googlevideo.com/audio?sig=secret",
                "ext": "m4a",
                "vcodec": "none",
                "acodec": "mp4a.40.2",
                "tbr": 129.5,
                "filesize": 10 * MB + 3,
            },
        ],
        "comments": [
            {
                "id": "UgzRealCommentId",
                "parent": "root",
                "author": "@fan_one",
                "author_id": "UCfanchannel00000000000a",
                "text": "Totally private comment",
                "like_count": 7,
            }
        ],
    }


def _no_leak(fixture: dict[str, Any], scope: dict[str, Any]) -> None:
    text = json.dumps(fixture, ensure_ascii=False)
    assert [secret for secret in SECRETS if secret in text] == []
    assert leak_count(scope, "\n".join(sorted(_leaves(fixture)))) == 0


def test_post_fixture_carries_no_original_value_and_replays() -> None:
    fixture, scope = build_post({"kind": "video", "extract": {"status": "ok", "info": _raw_info()}})
    _no_leak(fixture, scope)
    document = fixture["document"]
    identity = YouTubeIdentity(canonical_url=video_url(document["id"]), video_id=document["id"])
    parsed = parse_info(document, identity)
    assert parsed is not None
    assert parsed.post.owner_handle == "user_001"
    assert parsed.post.engagement == {"play": 4_500, "like": 120, "comment": 45}
    assert [(c.author, c.likes) for c in parsed.comments] == [("user_002", 7)]
    choice = select_formats(document["formats"], parsed.duration_seconds)
    assert (choice.video_format, choice.audio_format, choice.short_side) == ("137", "140", 1080)
    assert fixture["expected"]["choice"] == {
        "video_format": "137",
        "audio_format": "140",
        "short_side": 1080,
    }
    assert all(f["url"].startswith("https://media.example.test/") for f in document["formats"])


def test_a_capture_without_info_is_refused() -> None:
    with pytest.raises(ValueError):
        build_post({"kind": "video", "extract": {"status": "request_blocked", "info": None}})


def test_channel_fixture_keeps_listings_and_details_consistent() -> None:
    raw = {
        "kind": "channel",
        "handle": "realperson",
        "listings": {
            "videos": {
                "status": "ok",
                "listing": {"entries": [{"id": "realVideo01", "view_count": 999}]},
            },
            "shorts": {"status": "request_blocked", "listing": None},
        },
        "details": {"realVideo01": _raw_info(), "realVideo02": {"error": "request_blocked"}},
    }
    fixture, scope = build_channel(raw)
    _no_leak(fixture, scope)
    document = fixture["document"]
    (alias,) = document["details"]
    assert document["listings"]["videos"]["entries"] == [{"id": alias, "view_count": 990}]
    assert fixture["expected"]["candidates"] == [alias]
    assert fixture["handle"] == "user_001"


def test_main_writes_a_clean_fixture(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    raw_path, out = tmp_path / "video.json", tmp_path / "out.json"
    raw_path.write_text(
        json.dumps({"kind": "video", "extract": {"status": "ok", "info": _raw_info()}}),
        encoding="utf-8",
    )
    assert main(["--raw", str(raw_path), "--out", str(out)]) == 0
    printed = capsys.readouterr().out
    assert json.loads(printed)["leaks"] == 0
    assert [secret for secret in SECRETS if secret in printed] == []
    assert json.loads(out.read_text(encoding="utf-8"))["kind"] == "video"


def test_main_refuses_to_write_a_leaking_fixture(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    leaking = (
        {"kind": "video", "counts": {}, "document": {"x": "realperson"}},
        {"secrets": ["realperson"]},
    )
    monkeypatch.setattr(youtube_fixture, "build", lambda raw: leaking)
    raw_path, out = tmp_path / "video.json", tmp_path / "out.json"
    raw_path.write_text("{}", encoding="utf-8")
    assert main(["--raw", str(raw_path), "--out", str(out)]) == 1
    assert not out.exists()
