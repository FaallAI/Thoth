"""A Content Set projected for Studio: items, trims, stills, and what Studio leaves out."""

from __future__ import annotations

import hashlib
import json
from typing import Any

from tests.assembly.test_models import OCR, VIDEO, content_set
from thoth_control_plane.assembly.models import ContentSet
from thoth_control_plane.assembly.studio import project_content_set, workflow_source_key
from thoth_control_plane.domain.studio_imports import inventory
from thoth_control_plane.domain.studio_layout import reading_seconds

IMAGE = {
    "location": "reports/wf_a/media/slide-1.jpg",
    "media_type": "image/jpeg",
    "checksum": "sha256:" + "b" * 64,
    "bytes": 900,
    "width": 1080,
    "height": 1350,
}
REGION = {"x": 0.1, "y": 0.7, "w": 0.8, "h": 0.1, "start": 0.0, "end": 4.0}


def footage(index: int, **changes: Any) -> dict[str, Any]:
    item: dict[str, Any] = {
        "source": "search",
        "url": f"https://www.tiktok.com/@kreator/video/740000000000000000{index}",
        "platform": "tiktok",
        "owner_handle": "kreator",
        "query": "banjir jakarta",
        "description": f"Footage {index}",
        "video": {
            "location": f"reports/wf_a/footage/clip-{index}.mp4",
            "media_type": "video/mp4",
            "checksum": "sha256:" + "cd"[index] * 64,
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


def parse(data: dict[str, Any]) -> ContentSet:
    # Strict models: a dict goes in as JSON, exactly as the stored row does.
    return ContentSet.model_validate_json(json.dumps(data))


def test_a_video_main_becomes_the_main_item_with_its_trim() -> None:
    data = content_set(
        ocr=OCR | {"outcome": "cover", "trim_start": 2.5},
        url="https://www.tiktok.com/@creator/video/1234567890?lang=id#top",
    )
    projected = project_content_set(parse(data))
    [main] = projected.projection.items
    assert (main.role, main.order, main.media_kind) == ("main", 0, "video")
    assert main.trim_start_seconds == 2.5
    assert main.source_url == "https://www.tiktok.com/@creator/video/1234567890"
    assert (main.title, main.text, main.platform) == ("judul", "judul panjang", "tiktok")
    assert projected.media["main_000"].location.as_posix() == VIDEO["location"]
    assert projected.projection.unsupported == []


def test_a_clean_main_has_no_trim() -> None:
    [main] = project_content_set(parse(content_set())).projection.items
    assert main.trim_start_seconds is None


def test_profile_card_and_slides_are_projected() -> None:
    second = IMAGE | {"location": "reports/wf_a/media/slide-2.jpg"}
    third = IMAGE | {"location": "reports/wf_a/media/slide-3.jpg"}
    data = content_set(
        kind="images", video=None, ocr=None, images=[IMAGE, second, third], profile_card=IMAGE
    )
    projected = project_content_set(parse(data))
    items = projected.projection.items
    assert [(i.role, i.order, i.media_kind) for i in items] == [
        ("main", 0, "image"),
        ("slide", 0, "image"),
        ("slide", 1, "image"),
        ("profile_card", 0, "image"),
    ]
    assert items[3].title == "@creator"
    # The first slide item is the carousel's second image.
    assert [i.title for i in items[1:3]] == ["Slide 2", "Slide 3"]
    assert projected.media["main_000"].location.as_posix() == IMAGE["location"]
    assert projected.media["slide_001"].location.as_posix() == third["location"]
    assert "profile_card_000" in projected.media
    assert projected.projection.unsupported == []


def test_a_card_main_is_a_still() -> None:
    data = content_set(kind="card", video=None, ocr=None, card=IMAGE)
    projected = project_content_set(parse(data))
    assert projected.projection.items[0].media_kind == "image"
    assert projected.media["main_000"].media_type == "image/jpeg"


def test_footage_and_comments_follow_the_main_in_order() -> None:
    data = content_set() | {
        "footage": [footage(0, ocr=OCR | {"outcome": "cover", "trim_start": 1.0}), footage(1)],
        "footage_status": "ok",
        "comments": [{"text": "wow", "author": "viewer", "source": "input"}],
    }
    projected = project_content_set(parse(data))
    items = projected.projection.items
    assert [(i.role, i.order, i.media_kind) for i in items] == [
        ("main", 0, "video"),
        ("footage", 0, "video"),
        ("footage", 1, "video"),
        ("comment", 0, "none"),
    ]
    assert [i.trim_start_seconds for i in items[1:3]] == [1.0, None]
    assert (items[1].title, items[1].text) == ("@kreator", "Footage 0")
    assert (items[3].title, items[3].text, items[3].source_url) == ("@viewer", "wow", None)
    media_items = {i.item_id for i in inventory(projected.projection) if i.media_kind != "none"}
    assert media_items == set(projected.media) == {"main_000", "footage_000", "footage_001"}


def test_subtitle_main_carries_mute_and_blur() -> None:
    second = REGION | {"start": 5.0, "end": 9.0}
    subtitled = OCR | {"outcome": "subtitle", "mute_audio": True, "subtitle_blur": [REGION, second]}
    data = content_set(ocr=subtitled) | {
        "figures": [{"name": "Prabowo", "type": "person"}],
        "figures_status": "ok",
    }
    projected = project_content_set(parse(data))
    [main] = projected.projection.items
    assert main.mute_audio is True
    assert [(r.start, r.end) for r in main.blur_regions] == [(0.0, 4.0), (5.0, 9.0)]
    assert [(u.field, u.role) for u in projected.projection.unsupported] == [("figures", None)]


def test_comment_cards_follow_likes_and_carry_reading_time() -> None:
    comments = [
        {"text": "pertama", "author": "satu", "likes": 5, "source": "input", "card": IMAGE},
        {
            "text": "kedua lebih panjang",
            "author": "dua",
            "likes": 50,
            "source": "input",
            "card": IMAGE,
        },
        {"text": "ketiga", "author": "tiga", "likes": 50, "source": "input", "card": IMAGE},
    ]
    projected = project_content_set(parse(content_set() | {"comments": comments}))
    cards = [i for i in projected.projection.items if i.role == "comment_card"]
    assert [(i.order, i.title) for i in cards] == [(0, "@dua"), (1, "@tiga"), (2, "@satu")]
    assert [i.reading_seconds for i in cards] == [
        reading_seconds(c["text"]) for c in (comments[1], comments[2], comments[0])
    ]
    assert {"comment_card_000", "comment_card_001", "comment_card_002"} <= set(projected.media)
    assert not [i for i in projected.projection.items if i.role == "comment"]


def test_a_comment_without_a_card_stays_a_text_scene() -> None:
    comments = [
        {"text": "ada kartu", "author": "satu", "source": "input", "card": IMAGE},
        {"text": "tanpa kartu", "author": "dua", "source": "input"},
    ]
    items = project_content_set(parse(content_set() | {"comments": comments})).projection.items
    assert [(i.role, i.order, i.title) for i in items[1:]] == [
        ("comment_card", 0, "@satu"),
        ("comment", 0, "@dua"),
    ]


def test_a_description_past_the_text_limit_is_reported_not_cut() -> None:
    data = content_set(description="x" * 2_001)
    projected = project_content_set(parse(data))
    assert projected.projection.items[0].text is None
    assert [u.field for u in projected.projection.unsupported] == ["main.description"]


def test_the_workflow_source_key_is_per_workflow_and_per_content() -> None:
    digest = hashlib.sha256(b"content").hexdigest()
    key = workflow_source_key("wf_a", digest)
    assert key == hashlib.sha256(f"workflow:wf_a:{digest}".encode()).hexdigest()
    assert key != workflow_source_key("wf_b", digest)
    assert key != workflow_source_key("wf_a", hashlib.sha256(b"other").hexdigest())


def test_a_youtube_watch_link_keeps_its_video_id() -> None:
    clips = [
        footage(0, url="https://www.youtube.com/watch?v=dQw4w9WgXcQ&t=10s", platform="youtube"),
        footage(1, url="https://m.youtube.com/watch?feature=share", platform="youtube"),
    ]
    data = content_set() | {"footage": clips, "footage_status": "ok"}
    items = project_content_set(parse(data)).projection.items
    assert items[1].source_url == "https://youtu.be/dQw4w9WgXcQ"
    assert items[2].source_url == "https://m.youtube.com/watch"


# --- Stage 5c-2: style A materials (spec 2026-10-22, G5) ---

POST = IMAGE | {
    "location": "reports/wf_a/cards/post.png",
    "media_type": "image/png",
    "media_box": {"x": 0.0, "y": 0.3, "w": 1.0, "h": 0.5},
}
PAGE = IMAGE | {"location": "reports/wf_a/cards/profile-page.png", "media_type": "image/png"}
PHOTO = {
    "source": "creator",
    "url": "https://www.tiktok.com/@creator/photo/7600000000000000001",
    "platform": "tiktok",
    "owner_handle": "creator",
    "caption": "foto banjir",
    "image": IMAGE | {"location": "reports/wf_a/footage/photo-1.jpg"},
    "story_score": 0.6,
}


def style_a_set() -> dict[str, Any]:
    return content_set(post_card=POST, profile_page=PAGE) | {
        "footage": [footage(0, source="creator", query="creator:@creator"), footage(1)],
        "footage_status": "ok",
        "photos": [PHOTO],
        "style_a": True,
    }


def test_projection_orders_the_new_roles() -> None:
    projected = project_content_set(parse(style_a_set()))
    items = projected.projection.items
    assert [(i.role, i.order) for i in items] == [
        ("main", 0),
        ("post_card", 0),
        ("profile_page", 0),
        ("creator_footage", 0),
        ("creator_photo", 0),
        ("footage", 0),
    ]
    assert items[1].reading_seconds == reading_seconds("judul panjang")
    scenes = {i.item_id: i.scene_id for i in inventory(projected.projection)}
    assert scenes == {
        "main_000": "scene_001",
        "post_card_000": "scene_001",
        "profile_page_000": "scene_002",
        "creator_footage_000": "scene_003",
        "creator_photo_000": "scene_004",
        "footage_000": "scene_005",
    }
    assert projected.projection.unsupported == []
    assert projected.media["post_card_000"].location.as_posix() == POST["location"]


def test_a_missing_post_card_is_reported_in_the_gate() -> None:
    projected = project_content_set(parse(content_set() | {"style_a": True}))
    reported = {(u.field, u.reason) for u in projected.projection.unsupported}
    assert reported == {
        ("main.post_card", "Not captured: post card"),
        ("main.profile_page", "Not captured: profile page"),
    }
    youtube = content_set(platform="youtube", url="https://www.youtube.com/shorts/abcdefghijk")
    projected = project_content_set(parse(youtube | {"style_a": True}))
    assert {u.field for u in projected.projection.unsupported} == {"main.profile_page"}


def test_an_old_content_set_places_as_before() -> None:
    projected = project_content_set(parse(content_set()))
    assert [(i.role, i.order) for i in projected.projection.items] == [("main", 0)]
    assert projected.projection.unsupported == []
