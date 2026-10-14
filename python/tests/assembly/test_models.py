"""ContentSet v1: inconsistent OCR, a video without OCR, or a main without media cannot exist."""

from __future__ import annotations

import copy
import json
from typing import Any

import pytest
from pydantic import ValidationError

from thoth_control_plane.assembly.models import MAX_FOOTAGE, ContentSet, Footage

VIDEO = {
    "location": "reports/wf_a/media/tiktok-1.mp4",
    "media_type": "video/mp4",
    "checksum": "sha256:" + "a" * 64,
    "bytes": 20000,
    "duration_seconds": 30.0,
}
OCR = {
    "analyzed_at": "2026-10-11T12:00:00Z",
    "requested_frames": 12,
    "valid_frames": 12,
    "outcome": "clean",
    "trim_start": 0.0,
    "mute_audio": False,
    "subtitle_blur": [],
}


def content_set(**main: Any) -> dict[str, Any]:
    base = {
        "source": "input",
        "url": "https://www.tiktok.com/@creator/video/1234567890",
        "platform": "tiktok",
        "title": "judul",
        "description": "judul panjang",
        "owner_handle": "creator",
        "kind": "video",
        "video": VIDEO,
        "ocr": OCR,
    }
    base.update(main)
    return {
        "workflow_id": "wf_a",
        "attribution_verdict": "none",
        "main": base,
        "comments": [],
        "figures": [],
        "figures_status": "none",
    }


def parse(data: dict[str, Any]) -> ContentSet:
    return ContentSet.model_validate_json(json.dumps(data))


def test_a_clean_video_main_is_valid() -> None:
    parsed = parse(content_set())
    assert parsed.schema_version == 1
    assert parsed.main.ocr is not None and parsed.main.ocr.engine == "rapidocr"
    assert parsed.footage == []


@pytest.mark.parametrize(
    ("ocr", "message"),
    [
        ({"outcome": "clean", "trim_start": 1.0}, "clean"),
        ({"outcome": "clean", "mute_audio": True}, "clean"),
        ({"outcome": "cover", "trim_start": 0.0}, "cover"),
        ({"outcome": "cover", "trim_start": 2.0, "mute_audio": True}, "cover"),
        (
            {
                "outcome": "subtitle",
                "mute_audio": False,
                "subtitle_blur": [{"x": 0.1, "y": 0.7, "w": 0.8, "h": 0.1, "start": 0, "end": 4}],
            },
            "subtitle",
        ),
        ({"outcome": "subtitle", "mute_audio": True, "subtitle_blur": []}, "subtitle"),
        ({"valid_frames": 11}, "coverage"),
    ],
)
def test_inconsistent_ocr_is_rejected(ocr: dict[str, Any], message: str) -> None:
    broken = copy.deepcopy(OCR) | ocr
    with pytest.raises(ValidationError, match=message):
        parse(content_set(ocr=broken))


@pytest.mark.parametrize(
    "region",
    [
        {"x": 0.5, "y": 0.7, "w": 0.6, "h": 0.1},
        {"x": 0.1, "y": 0.95, "w": 0.5, "h": 0.1},
        {"x": 0.1, "y": 0.7, "w": 0.5, "h": 0.1, "start": 1.0},
        {"x": 0.1, "y": 0.7, "w": 0.5, "h": 0.1, "start": 3.0, "end": 2.0},
        {"x": 0.1, "y": 0.7, "w": 0.0, "h": 0.1},
    ],
)
def test_bad_blur_regions_are_rejected(region: dict[str, Any]) -> None:
    ocr = copy.deepcopy(OCR) | {
        "outcome": "subtitle",
        "mute_audio": True,
        "subtitle_blur": [region],
    }
    with pytest.raises(ValidationError):
        parse(content_set(ocr=ocr))


def test_a_subtitle_verdict_may_keep_a_trim() -> None:
    ocr = copy.deepcopy(OCR) | {
        "outcome": "subtitle",
        "trim_start": 4.0,
        "mute_audio": True,
        "subtitle_blur": [{"x": 0.2, "y": 0.75, "w": 0.6, "h": 0.1, "start": 4.0, "end": 12.0}],
    }
    assert parse(content_set(ocr=ocr)).main.ocr.trim_start == 4.0  # type: ignore[union-attr]


@pytest.mark.parametrize(
    "main",
    [
        {"ocr": None},
        {"video": None},
        {"kind": "images", "video": None, "ocr": None, "images": []},
        {"kind": "card", "video": None, "ocr": None, "card": None},
        {"kind": "images", "ocr": None, "images": [VIDEO | {"media_type": "image/jpeg"}]},
        {"kind": "card", "video": None, "ocr": OCR, "card": VIDEO | {"media_type": "image/png"}},
    ],
)
def test_the_main_kind_decides_its_media(main: dict[str, Any]) -> None:
    with pytest.raises(ValidationError):
        parse(content_set(**main))


def test_footage_stays_empty_in_5a() -> None:
    data = content_set() | {"footage": [{"url": "https://example.com"}]}
    with pytest.raises(ValidationError):
        parse(data)


@pytest.mark.parametrize(
    ("figures", "status"),
    [
        ([], "ok"),
        ([{"name": "Prabowo", "type": "person"}], "none"),
        ([{"name": "Prabowo", "type": "person"}], "unavailable"),
    ],
)
def test_figures_status_matches_the_list(figures: list[Any], status: str) -> None:
    with pytest.raises(ValidationError):
        parse(content_set() | {"figures": figures, "figures_status": status})


def test_at_most_twelve_comments() -> None:
    comment = {"text": "mantap", "author": "a", "likes": 1, "source": "input"}
    with pytest.raises(ValidationError):
        parse(content_set() | {"comments": [comment] * 13})


def test_an_overlay_blurs_without_muting() -> None:
    region = {"x": 0.03, "y": 0.58, "w": 0.93, "h": 0.15, "start": 0.0, "end": 39.1}
    ocr = copy.deepcopy(OCR) | {
        "outcome": "overlay",
        "mute_audio": False,
        "subtitle_blur": [region],
        "trim_refined": False,
    }
    assert parse(content_set(ocr=ocr)).main.ocr.outcome == "overlay"  # type: ignore[union-attr]
    for broken in ({"mute_audio": True}, {"subtitle_blur": []}):
        with pytest.raises(ValidationError, match="overlay"):
            parse(content_set(ocr=ocr | broken))


def _footage(**changes: Any) -> dict[str, Any]:
    item: dict[str, Any] = {
        "source": "search",
        "url": "https://www.tiktok.com/@kreator/video/7400000000000000001",
        "platform": "tiktok",
        "owner_handle": "kreator",
        "query": "banjir jakarta",
        "visual": "a flooded street with cars half under water",
        "caption": "banjir lagi",
        "description": "Cars drive through a flooded street.",
        "video": {
            "location": "reports/wf_a/footage/abc.mp4",
            "media_type": "video/mp4",
            "checksum": "sha256:" + "a" * 64,
            "bytes": 2048,
            "duration_seconds": 20.0,
        },
        "clip_start": 3.0,
        "ocr": OCR,
        "story_score": 0.61,
        "shows_object": "yes",
    }
    item.update(changes)
    return item


def _footage_set(**changes: Any) -> dict[str, Any]:
    return content_set() | changes


def test_a_content_set_without_footage_says_disabled() -> None:
    parsed = parse(_footage_set())
    assert parsed.footage == []
    assert parsed.footage_status == "disabled"


def test_footage_status_ok_exactly_when_footage_is_present() -> None:
    parse(_footage_set(footage=[_footage()], footage_status="ok"))
    with pytest.raises(ValidationError):
        parse(_footage_set(footage=[_footage()], footage_status="none"))
    with pytest.raises(ValidationError):
        parse(_footage_set(footage=[], footage_status="ok"))


def test_footage_urls_are_unique_and_never_the_main() -> None:
    with pytest.raises(ValidationError):
        parse(_footage_set(footage=[_footage(), _footage()], footage_status="ok"))
    main_url = content_set()["main"]["url"]
    with pytest.raises(ValidationError):
        parse(_footage_set(footage=[_footage(url=main_url)], footage_status="ok"))


def test_subtitled_footage_is_refused() -> None:
    subtitled = {
        **OCR,
        "outcome": "subtitle",
        "mute_audio": True,
        "subtitle_blur": [{"x": 0.1, "y": 0.8, "w": 0.8, "h": 0.1}],
    }
    with pytest.raises(ValidationError):
        Footage.model_validate_json(json.dumps(_footage(ocr=subtitled)))


def test_footage_holds_at_most_six_items() -> None:
    items = [
        _footage(url=f"https://www.tiktok.com/@kreator/video/740000000000000000{n}")
        for n in range(MAX_FOOTAGE + 1)
    ]
    with pytest.raises(ValidationError):
        parse(_footage_set(footage=items, footage_status="ok"))
