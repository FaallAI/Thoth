"""Golden TikTok comment captures: sanitizer and reducer replay."""

import copy
import json
import re
from pathlib import Path

import pytest

from thoth_control_plane.acquisition.browser import _reduce_comments
from thoth_control_plane.operations.tiktok_comment_fixture import (
    ENTRY_KEYS,
    ID_BASE,
    INVALID_HANDLE,
    INVALID_ID,
    main,
    sanitize_capture,
)


def replay(capture: dict) -> list[dict]:
    """Run the reducer over a capture; each card is identified by its index."""
    pngs = [f"card-{index}".encode() for index in range(len(capture["card_texts"]))]
    comments = _reduce_comments(
        capture["pages"], list(zip(capture["card_texts"], pngs, strict=True))
    )
    return [
        {
            "comment_id": comment.comment_id,
            "card": None if comment.card_png is None else pngs.index(comment.card_png),
        }
        for comment in comments
    ]


def raw_capture() -> dict:
    capture = {
        "pages": [
            {
                "comments": [
                    {
                        "cid": "7300000000000000001",
                        "unique_id": "real.handle",
                        "text": "Mantap 123 😂",
                        "digg_count": 5,
                        "nickname": "Real Name",
                    },
                    {
                        "cid": "7300000000000000002",
                        "unique_id": "other_one",
                        "text": " [sticker] ",
                        "digg_count": 0,
                    },
                    {
                        "cid": "7300000000000000001",
                        "unique_id": "real.handle",
                        "text": "Mantap 123 😂",
                        "digg_count": 5,
                    },
                    {"cid": "bad", "unique_id": "has space", "text": None, "digg_count": "7"},
                    {
                        "cid": "7300000000000000003",
                        "unique_id": "real.handle",
                        "text": "ok",
                        "digg_count": 1,
                    },
                    {"cid": "7300000000000000004", "unique_id": "third", "text": "no"},
                    "not a dict",
                ],
                "has_more": 1,
                "cursor": 20,
                "extra": "secret",
            },
            "captcha body",
        ],
        "card_texts": ["Mantap 123 😂 ", "ok", "unmatched words"],
        "card_stats": [{"width": 300, "height": 80, "bytes": 6_000}] * 3,
        "profile_card_stats": {"width": 500, "height": 200, "bytes": 30_000},
    }
    capture["expected"] = replay(capture)
    return capture


def test_raw_capture_exercises_matching_and_duplicates() -> None:
    assert [item["card"] for item in raw_capture()["expected"]] == [0, None, 1, None]


def test_sanitized_capture_replays_like_the_raw_capture() -> None:
    raw = raw_capture()
    sanitized = sanitize_capture(raw)
    assert replay(sanitized) == sanitized["expected"]
    assert [item["card"] for item in sanitized["expected"]] == [0, None, 1, None]
    assert sanitized["card_stats"] == raw["card_stats"]
    assert sanitized["profile_card_stats"] == raw["profile_card_stats"]


def test_sanitized_capture_contains_no_original_identifiers() -> None:
    dumped = json.dumps(sanitize_capture(raw_capture()), ensure_ascii=False)
    for secret in (
        "730000000000000000",
        "real.handle",
        "other_one",
        "third",
        "Mantap",
        "123",
        "Real Name",
        "secret",
        "has space",
        "unmatched",
        "words",
    ):
        assert secret not in dumped


def test_sanitizer_preserves_what_the_reducer_reads() -> None:
    sanitized = sanitize_capture(raw_capture())
    page, captcha = sanitized["pages"]
    assert captcha is None
    assert set(page) == {"comments"}
    entries = page["comments"]
    assert entries[6] is None
    assert all(set(entry) == set(ENTRY_KEYS) for entry in entries[:6])
    first = entries[0]
    assert len(first["text"]) == len("Mantap 123 😂")
    assert first["text"].endswith(" 😂")
    assert first["unique_id"] == entries[4]["unique_id"] == "user_001"
    assert int(first["cid"]) >= ID_BASE
    assert entries[2] == first
    assert entries[1]["text"] == " [sticker] "
    assert entries[3] == {
        "cid": INVALID_ID,
        "unique_id": INVALID_HANDLE,
        "text": None,
        "digg_count": None,
    }
    assert entries[5]["digg_count"] is None
    assert sanitized["card_texts"][0] == first["text"] + " "


def test_sanitizer_is_deterministic() -> None:
    assert sanitize_capture(raw_capture()) == sanitize_capture(raw_capture())


def test_sanitizer_keeps_distinct_texts_distinct() -> None:
    capture = copy.deepcopy(raw_capture())
    singles = [chr(ord("a") + index) for index in range(26)] + [str(digit) for digit in range(10)]
    capture["card_texts"] = singles
    capture["card_stats"] = [{"width": 300, "height": 80, "bytes": 6_000}] * len(singles)
    sanitized = sanitize_capture(capture)
    assert len(set(sanitized["card_texts"])) == len(singles)


def test_sanitizer_refuses_texts_it_cannot_keep_distinct() -> None:
    capture = copy.deepcopy(raw_capture())
    capture["card_texts"] = [chr(ord("a") + index) for index in range(26)]
    capture["card_texts"] += [str(digit) for digit in range(10)] + ["é"]
    with pytest.raises(ValueError, match="distinct"):
        sanitize_capture(capture)


def test_cli_writes_lf_json(tmp_path: Path) -> None:
    source = tmp_path / "raw.json"
    target = tmp_path / "post-1.json"
    source.write_text(json.dumps(raw_capture()), encoding="utf-8")
    assert main([str(source), str(target)]) == 0
    data = target.read_bytes()
    assert b"\r\n" not in data
    assert json.loads(data) == sanitize_capture(raw_capture())
    assert re.search(rb"user_\d{3}", data)
