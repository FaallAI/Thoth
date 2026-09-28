"""Golden TikTok discovery captures: sanitizer, leak check, and parser replay."""

import json
import re
from datetime import datetime
from pathlib import Path

import pytest

from thoth_control_plane.acquisition.discovery import _assemble, parse_discovery_page
from thoth_control_plane.operations import tiktok_discovery_fixture as fixture_module
from thoth_control_plane.operations.tiktok_comment_fixture import ID_BASE
from thoth_control_plane.operations.tiktok_discovery_fixture import (
    COUNTER_DIGITS,
    MAX_FIXTURE_PAGES,
    SYNTHETIC_EPOCH,
    SYNTHETIC_EPOCH_STEP,
    fixture_page_bytes,
    main,
    replay_page,
    sanitize_capture,
)

RAW_ITEM = {
    "id": "7412345678901234567",
    "desc": "Secret caption #kitten",
    "createTime": 1709287200,
    "author": {
        "uniqueId": "real.creator",
        "secUid": "MS4wLjABAAAAsecret",
        "nickname": "Real Creator",
        "avatarThumb": "https://p16.example/avatar.jpg",
    },
    "stats": {
        "playCount": 10,
        "diggCount": 5,
        "commentCount": 2,
        "shareCount": 1,
        "collectCount": 3,
        "whateverCount": 9,
    },
    "statsV2": {"playCount": "10", "diggCount": "5"},
    "video": {"duration": 15, "playAddr": "https://v16.example/p.mp4"},
    "challenges": [{"title": "kitten", "id": "123", "coverLarger": "https://p16.example/k.jpg"}],
    "music": {"title": "a song"},
}
PAGE = {"statusCode": 0, "hasMore": True, "itemList": [RAW_ITEM], "cursor": "1709287200000"}


def _raw(kind: str, pages: list) -> dict:
    return {
        "kind": kind,
        "pages": [page if isinstance(page, str) else json.dumps(page) for page in pages],
    }


def test_items_keep_only_parser_keys_with_pseudonymized_values() -> None:
    [page] = sanitize_capture(_raw("profile", [PAGE]))["pages"]

    assert set(page) == {"statusCode", "hasMore", "itemList"}
    [item] = page["itemList"]
    assert item == {
        "id": str(ID_BASE),
        "desc": item["desc"],
        "createTime": SYNTHETIC_EPOCH,
        "stats": {
            "playCount": 10,
            "diggCount": 5,
            "commentCount": 2,
            "shareCount": 1,
            "collectCount": 3,
        },
        "statsV2": {"playCount": "10", "diggCount": "5"},
        "video": {"duration": 15},
        "author": {"uniqueId": "user_001"},
        "challenges": [{"title": item["challenges"][0]["title"]}],
    }
    assert len(item["desc"]) == len(RAW_ITEM["desc"]) and item["desc"] != RAW_ITEM["desc"]
    assert len(item["challenges"][0]["title"]) == 6
    assert item["challenges"][0]["title"] != "kitten"


def test_search_entries_are_reduced_to_type_and_item() -> None:
    page = {
        "status_code": 0,
        "has_more": 1,
        "data": [
            {"type": 1, "item": RAW_ITEM, "common": {"doc_id_str": "x"}},
            {"type": 4, "user_list": [{"uniqueId": "real.creator"}]},
        ],
    }

    [sanitized] = sanitize_capture(_raw("keyword", [page]))["pages"]

    assert set(sanitized) == {"status_code", "has_more", "data"}
    assert [entry["type"] for entry in sanitized["data"]] == [1, 4]
    assert set(sanitized["data"][0]) == {"type", "item"}
    assert sanitized["data"][1] == {"type": 4}


def test_expected_records_the_replay_of_the_sanitized_pages() -> None:
    items = [
        RAW_ITEM,
        {**RAW_ITEM, "id": "7412345678901234568", "isAd": True},
        {**RAW_ITEM, "id": "7412345678901234569", "imagePost": {"images": [{"url": "https://x"}]}},
        {**RAW_ITEM, "id": 7412345678901234570},
    ]
    page = {"statusCode": 0, "hasMore": False, "itemList": items}

    fixture = sanitize_capture(_raw("profile", [page]))

    [expected] = fixture["expected"]
    assert fixture["expected"] == [
        replay_page("profile", fixture_page_bytes(page)) for page in fixture["pages"]
    ]
    assert expected["drops"] == {"ads": 1, "photo_posts": 1, "invalid": 1}
    assert expected["has_more"] is False
    assert expected["reason"] is None
    assert expected["videos"] == [
        {
            "published_at": "2023-11-14T22:13:20Z",
            "duration_seconds": 15.0,
            "engagement": {"play": 10, "like": 5, "comment": 2, "share": 1, "collect": 3},
            "caption_length": 22,
            "hashtags": 1,
        }
    ]
    assert fixture["pages"][0]["itemList"][1]["isAd"] is True
    assert fixture["pages"][0]["itemList"][2]["imagePost"] == {}


def test_create_time_becomes_a_synthetic_epoch_in_its_raw_type() -> None:
    """Epochs follow first appearance, so duplicates stay equal; a value the normalizer
    rejects replays as no `published_at` whether it is kept or dropped, so it is dropped."""
    times = [1709287200, "1709287200", 1709290800, 0, 1709287200.5]
    items = [{**RAW_ITEM, "createTime": time} for time in times]
    page = {"statusCode": 0, "hasMore": False, "itemList": items}

    [sanitized] = sanitize_capture(_raw("profile", [page]))["pages"]

    assert [item.get("createTime") for item in sanitized["itemList"]] == [
        SYNTHETIC_EPOCH,
        str(SYNTHETIC_EPOCH),
        SYNTHETIC_EPOCH + SYNTHETIC_EPOCH_STEP,
        None,
        None,
    ]


def test_counters_keep_two_significant_digits_in_their_raw_type() -> None:
    """Flooring keeps each counter's digit count (995 never carries to 1000), keeps zero, and
    keeps a `stats` value equal to its `statsV2` twin; rejected values are dropped."""
    item = {
        **RAW_ITEM,
        "stats": {
            "playCount": 912345678,
            "diggCount": 0,
            "commentCount": 99,
            "shareCount": 995,
            "collectCount": 12.5,
        },
        "statsV2": {"playCount": "912345678", "diggCount": -4},
    }
    page = {"statusCode": 0, "hasMore": False, "itemList": [item]}

    fixture = sanitize_capture(_raw("profile", [page]))

    [out_item] = fixture["pages"][0]["itemList"]
    assert out_item["stats"] == {
        "playCount": 910000000,
        "diggCount": 0,
        "commentCount": 99,
        "shareCount": 990,
    }
    assert out_item["statsV2"] == {"playCount": "910000000"}
    [video] = fixture["expected"][0]["videos"]
    assert video["engagement"] == {"play": 910000000, "like": 0, "comment": 99, "share": 990}


def test_an_unreadable_envelope_keeps_its_keys_as_sentinels() -> None:
    """Dropping a present `statusCode` or `hasMore` would let the parser fall back to its
    snake_case twin and replay differently; a sentinel keeps the key and the outcome."""
    blocked = {"statusCode": "err", "status_code": 0, "hasMore": True, "itemList": [RAW_ITEM]}
    open_ended = {"statusCode": 0, "hasMore": None, "has_more": 1, "itemList": [RAW_ITEM]}

    fixture = sanitize_capture(_raw("profile", [blocked, open_ended]))

    first, second = fixture["pages"]
    assert (first["statusCode"], first["status_code"]) == (-1, 0)
    assert (second["hasMore"], second["has_more"]) == (None, 1)
    assert fixture["expected"][0]["reason"] == "blocked"
    assert fixture["expected"][1]["has_more"] is False


def test_a_non_json_page_becomes_null_and_replays_as_captcha() -> None:
    fixture = sanitize_capture(_raw("keyword", ["<html>verify</html>"]))

    assert fixture["pages"] == [None]
    assert fixture["expected"][0]["reason"] == "captcha"


def test_only_the_first_pages_are_kept() -> None:
    fixture = sanitize_capture(_raw("profile", [PAGE, PAGE, PAGE]))

    assert len(fixture["pages"]) == len(fixture["expected"]) == MAX_FIXTURE_PAGES == 2


def test_main_writes_a_leak_free_lf_fixture(tmp_path, capsys) -> None:
    source = tmp_path / "raw.json"
    target = tmp_path / "fixture.json"
    source.write_text(json.dumps(_raw("profile", [PAGE])), encoding="utf-8")

    assert main([str(source), str(target)]) == 0

    assert capsys.readouterr().out == "checked=16 leaks=0\n"
    data = target.read_bytes()
    assert b"\r\n" not in data
    for secret in (b"real.creator", b"Secret caption", b"7412345678901234567", b"http"):
        assert secret not in data


def test_main_refuses_to_write_when_an_original_survives(tmp_path, capsys, monkeypatch) -> None:
    def passthrough(raw: dict) -> dict:
        return {"kind": raw["kind"], "pages": [json.loads(page) for page in raw["pages"]]}

    monkeypatch.setattr(fixture_module, "sanitize_capture", passthrough)
    source = tmp_path / "raw.json"
    target = tmp_path / "fixture.json"
    source.write_text(json.dumps(_raw("profile", [PAGE])), encoding="utf-8")

    assert main([str(source), str(target)]) == 1

    assert not target.exists()
    assert "leaks=0" not in capsys.readouterr().out


ENCLOSED_ALPHANUMERICS = "Ⓢⓔⓒⓡⓔⓣ"  # circled "Secret"


def test_enclosed_alphanumeric_caption_is_fully_pseudonymized(tmp_path, capsys) -> None:
    """Stylized letters (Unicode category So), which `str.isalnum()` misses, must not survive."""
    item = {
        **RAW_ITEM,
        "desc": f"{ENCLOSED_ALPHANUMERICS} post",
        "challenges": [{"title": ENCLOSED_ALPHANUMERICS[:3]}],
    }
    page = {"statusCode": 0, "hasMore": True, "itemList": [item]}
    raw = _raw("profile", [page])

    [sanitized] = sanitize_capture(raw)["pages"]
    [out_item] = sanitized["itemList"]
    for char in ENCLOSED_ALPHANUMERICS:
        assert char not in out_item["desc"]
    for char in ENCLOSED_ALPHANUMERICS[:3]:
        assert char not in out_item["challenges"][0]["title"]

    source, target = tmp_path / "raw.json", tmp_path / "fixture.json"
    source.write_text(json.dumps(raw), encoding="utf-8")
    assert main([str(source), str(target)]) == 0
    assert capsys.readouterr().out.strip().endswith("leaks=0")


def test_leak_report_catches_a_token_from_an_unknown_raw_key() -> None:
    """`_originals` must not be limited to the fields the sanitizer already pseudonymizes."""
    item = {**RAW_ITEM, "music": {"title": "Moonlight Serenade Unknown"}}
    page = {"statusCode": 0, "hasMore": True, "itemList": [item]}
    raw = _raw("profile", [page])
    leaking_text = json.dumps({"note": "a Moonlight Serenade Unknown tribute"})

    _checked, leaks = fixture_module.leak_report(raw, leaking_text)

    assert leaks >= 1


def test_leak_report_catches_a_partial_stylized_survival() -> None:
    """Whole-value matching misses a stylized token embedded in an otherwise-clean caption."""
    item = {**RAW_ITEM, "desc": f"{ENCLOSED_ALPHANUMERICS} post"}
    page = {"statusCode": 0, "hasMore": True, "itemList": [item]}
    raw = _raw("profile", [page])
    partially_sanitized = json.dumps({"desc": f"{ENCLOSED_ALPHANUMERICS} zzz"})

    _checked, leaks = fixture_module.leak_report(raw, partially_sanitized)

    assert leaks >= 1


def test_invalid_numeric_slot_values_are_dropped() -> None:
    """Stats/createTime/duration slots copy only int/float (not bool) or `isdecimal()` strings."""
    item = {
        **RAW_ITEM,
        "createTime": "not-a-number",
        "stats": {"playCount": {"nested": "dict"}, "diggCount": 5},
        "video": {"duration": "fifteen", "playAddr": "https://v16.example/p.mp4"},
    }
    page = {"statusCode": 0, "hasMore": True, "itemList": [item]}

    [sanitized] = sanitize_capture(_raw("profile", [page]))["pages"]

    [out_item] = sanitized["itemList"]
    assert "createTime" not in out_item
    assert out_item["stats"] == {"diggCount": 5}
    assert "video" not in out_item


def test_main_writes_when_a_caption_token_matches_its_own_derived_published_at(
    tmp_path, capsys
) -> None:
    """`expected` is a pure replay of the sanitized pages; a caption token (e.g. a year) that
    only coincides with its own derived `published_at` date must not block the write."""
    item = {**RAW_ITEM, "desc": "Filmed on 2023-11-14T22:13:20Z again"}
    page = {"statusCode": 0, "hasMore": True, "itemList": [item]}
    raw = _raw("profile", [page])
    fixture = sanitize_capture(raw)
    assert fixture["expected"][0]["videos"][0]["published_at"] == "2023-11-14T22:13:20Z"
    source, target = tmp_path / "raw.json", tmp_path / "fixture.json"
    source.write_text(json.dumps(raw), encoding="utf-8")

    assert main([str(source), str(target)]) == 0

    assert capsys.readouterr().out.strip().endswith("leaks=0")
    assert target.exists()


def test_main_writes_when_an_author_stats_v2_counter_coincides_with_item_stats(
    tmp_path, capsys
) -> None:
    """Raw `authorStatsV2` (never a NUMERIC_KEYS slot, so never copied by the sanitizer) can
    share digits with the item's own `statsV2` counters in a real capture. The
    output scan must skip NUMERIC_KEYS slots the same way the raw side already does, so this
    numeric coincidence must not block the write."""
    item = {
        **RAW_ITEM,
        "statsV2": {"playCount": "912345678", "diggCount": "1234567"},
        "authorStatsV2": {"heartCount": "1234567", "followerCount": "912345"},
    }
    page = {"statusCode": 0, "hasMore": True, "itemList": [item]}
    raw = _raw("trending", [page])
    source, target = tmp_path / "raw.json", tmp_path / "fixture.json"
    source.write_text(json.dumps(raw), encoding="utf-8")

    assert main([str(source), str(target)]) == 0

    assert capsys.readouterr().out.strip().endswith("leaks=0")
    assert target.exists()


def test_leak_report_still_catches_a_raw_id_in_a_non_numeric_value() -> None:
    """The NUMERIC_KEYS exclusion added to the output scan must not blind it to a raw id
    (never a numeric slot) surviving into an ordinary output string like `desc`."""
    raw = _raw("profile", [PAGE])
    leaking_text = json.dumps({"desc": f"copy of {RAW_ITEM['id']} here"})

    _checked, leaks = fixture_module.leak_report(raw, leaking_text)

    assert leaks >= 1


def _profile_with(**changes: object) -> dict:
    return _raw("profile", [{"statusCode": 0, "itemList": [{**RAW_ITEM, **changes}]}])


def test_leak_report_catches_a_short_handle_kept_in_an_identity_slot() -> None:
    raw = _profile_with(author={"uniqueId": "ab"})

    _checked, leaks = fixture_module.leak_report(raw, json.dumps({"uniqueId": "ab"}))

    assert leaks == 1


def test_leak_report_ignores_a_pseudonymous_handle_that_contains_a_raw_word() -> None:
    """Identity slots match whole values only: `user_001` is not a leak of a raw `user`."""
    raw = _profile_with(music={"title": "user"})

    _checked, leaks = fixture_module.leak_report(raw, json.dumps({"uniqueId": "user_001"}))

    assert leaks == 0


def test_leak_report_matches_a_short_caption_word_left_in_place() -> None:
    """Pseudonyms keep a string's length and word positions, so a surviving short word sits
    where it was; the same letters elsewhere are an unrelated pseudonym, not a leak."""
    raw = _profile_with(desc="ok sip # mantap")

    def leaks(desc: str) -> int:
        return fixture_module.leak_report(raw, json.dumps({"desc": desc}))[1]

    assert leaks("zz sip # xxxxxx") == 1
    assert leaks("zz xsipx # yyy") == 0
    assert leaks("sip zz # xxxxxx") == 0
    assert leaks("sip") == 0


def test_leak_report_checks_a_one_character_token_only_as_an_id_or_handle() -> None:
    raw = _profile_with(desc="x marks", author={"uniqueId": "x"})

    _checked, word = fixture_module.leak_report(raw, json.dumps({"desc": "x yyyyy"}))
    _checked, handle = fixture_module.leak_report(raw, json.dumps({"uniqueId": "x"}))

    assert word == 0
    assert handle == 1


FIXTURES = Path(__file__).resolve().parent.parent / "fixtures" / "tiktok" / "discovery"
GOLDEN = {"profile": "profile.json", "keyword": "search.json", "trending": "explore.json"}
GOLDEN_PAGES = {"profile": 2, "keyword": 1, "trending": 2}
ISO_UTC = re.compile(r"[0-9]{4}-[0-9]{2}-[0-9]{2}T[0-9]{2}:[0-9]{2}:[0-9]{2}Z")
PSEUDONYMOUS_URL = re.compile(r"https://www\.tiktok\.com/@user_[0-9]{3}/video/7[0-9]{18}")
ENGAGEMENT_KEYS = {"play", "like", "comment", "share", "collect"}


def _golden(kind: str) -> dict:
    return json.loads((FIXTURES / GOLDEN[kind]).read_text(encoding="utf-8"))


@pytest.mark.parametrize("kind", list(GOLDEN))
def test_golden_pages_replay_exactly(kind: str) -> None:
    fixture = _golden(kind)

    assert fixture["kind"] == kind
    assert len(fixture["pages"]) == GOLDEN_PAGES[kind]
    replayed = [replay_page(kind, fixture_page_bytes(page)) for page in fixture["pages"]]
    assert replayed == fixture["expected"]


@pytest.mark.parametrize("kind", list(GOLDEN))
def test_golden_pages_yield_normalized_pseudonymous_videos(kind: str) -> None:
    fixture = _golden(kind)

    videos = [
        video
        for page in fixture["pages"]
        for video in parse_discovery_page(kind, fixture_page_bytes(page)).videos
    ]

    assert videos
    for video in videos:
        assert PSEUDONYMOUS_URL.fullmatch(str(video.canonical_url))
        for count in video.engagement.values():
            assert len(str(count).rstrip("0")) <= COUNTER_DIGITS
        if video.published_at is not None:
            assert ISO_UTC.fullmatch(video.published_at)
            epoch = int(datetime.fromisoformat(video.published_at).timestamp())
            assert (epoch - SYNTHETIC_EPOCH) % SYNTHETIC_EPOCH_STEP == 0
    assert any(len(video.engagement) == 5 and video.published_at for video in videos)


@pytest.mark.parametrize("kind", list(GOLDEN))
def test_golden_pages_assemble_without_a_reason(kind: str) -> None:
    fixture = _golden(kind)
    pages = [parse_discovery_page(kind, fixture_page_bytes(page)) for page in fixture["pages"]]

    result = _assemble(kind, 100, pages, captcha=False, timed_out=False)

    assert result.pages == GOLDEN_PAGES[kind]
    assert result.reason is None
