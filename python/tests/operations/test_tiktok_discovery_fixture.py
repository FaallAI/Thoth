"""Golden TikTok discovery captures: sanitizer, leak check, and parser replay."""

import json

from thoth_control_plane.operations import tiktok_discovery_fixture as fixture_module
from thoth_control_plane.operations.tiktok_comment_fixture import ID_BASE
from thoth_control_plane.operations.tiktok_discovery_fixture import (
    MAX_FIXTURE_PAGES,
    main,
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
        "createTime": 1709287200,
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


def test_expected_records_the_capture_replay() -> None:
    items = [
        RAW_ITEM,
        {**RAW_ITEM, "id": "7412345678901234568", "isAd": True},
        {**RAW_ITEM, "id": "7412345678901234569", "imagePost": {"images": [{"url": "https://x"}]}},
        {**RAW_ITEM, "id": 7412345678901234570},
    ]
    page = {"statusCode": 0, "hasMore": False, "itemList": items}

    fixture = sanitize_capture(_raw("profile", [page]))

    [expected] = fixture["expected"]
    assert expected["drops"] == {"ads": 1, "photo_posts": 1, "invalid": 1}
    assert expected["has_more"] is False
    assert expected["reason"] is None
    assert expected["videos"] == [
        {
            "published_at": "2024-03-01T10:00:00Z",
            "duration_seconds": 15.0,
            "engagement": {"play": 10, "like": 5, "comment": 2, "share": 1, "collect": 3},
            "caption_length": 22,
            "hashtags": 1,
        }
    ]
    assert fixture["pages"][0]["itemList"][1]["isAd"] is True
    assert fixture["pages"][0]["itemList"][2]["imagePost"] == {}


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

    assert capsys.readouterr().out == "checked=14 leaks=0\n"
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
    """Stylized letters (Unicode category So) must not survive `_is_letter`'s alnum filter."""
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


def test_invalid_verbatim_slot_values_are_dropped() -> None:
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
    item = {**RAW_ITEM, "createTime": 1704067200, "desc": "Filmed in 2024 again"}
    page = {"statusCode": 0, "hasMore": True, "itemList": [item]}
    raw = _raw("profile", [page])
    fixture = sanitize_capture(raw)
    assert fixture["expected"][0]["videos"][0]["published_at"] == "2024-01-01T00:00:00Z"
    source, target = tmp_path / "raw.json", tmp_path / "fixture.json"
    source.write_text(json.dumps(raw), encoding="utf-8")

    assert main([str(source), str(target)]) == 0

    assert capsys.readouterr().out.strip().endswith("leaks=0")
    assert target.exists()


def test_main_writes_when_an_author_stats_v2_counter_coincides_with_item_stats(
    tmp_path, capsys
) -> None:
    """Raw `authorStatsV2` (never a VERBATIM_KEYS slot, so never copied by the sanitizer) can
    share digits with the item's own verbatim-copied `statsV2` counters in a real capture. The
    output scan must skip VERBATIM_KEYS slots the same way the raw side already does, so this
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


def test_leak_report_still_catches_a_raw_id_in_a_non_verbatim_value() -> None:
    """The VERBATIM_KEYS exclusion added to the output scan must not blind it to a raw id
    (never a verbatim slot) surviving into an ordinary output string like `desc`."""
    raw = _raw("profile", [PAGE])
    leaking_text = json.dumps({"desc": f"copy of {RAW_ITEM['id']} here"})

    _checked, leaks = fixture_module.leak_report(raw, leaking_text)

    assert leaks >= 1
