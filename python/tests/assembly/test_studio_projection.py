"""A Content Set projected for Studio: items, trims, stills, and what Studio leaves out."""

from __future__ import annotations

import hashlib
import json
from typing import Any

from tests.assembly.test_models import OCR, VIDEO, content_set
from thoth_control_plane.assembly.models import ContentSet
from thoth_control_plane.assembly.studio import project_content_set, workflow_source_key
from thoth_control_plane.domain.studio_imports import inventory

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


def test_an_images_main_keeps_its_first_slide_and_reports_the_rest() -> None:
    second = IMAGE | {"location": "reports/wf_a/media/slide-2.jpg"}
    data = content_set(kind="images", video=None, ocr=None, images=[IMAGE, second])
    projected = project_content_set(parse(data))
    [main] = projected.projection.items
    assert (main.media_kind, main.trim_start_seconds) == ("image", None)
    assert projected.media["main_000"].location.as_posix() == IMAGE["location"]
    [slides] = projected.projection.unsupported
    assert (slides.field, slides.role, slides.order) == ("main.images", "main", 0)
    assert slides.value_digest is not None


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


def test_what_studio_cannot_show_is_reported_once_each_with_a_digest() -> None:
    subtitled = OCR | {"outcome": "subtitle", "mute_audio": True, "subtitle_blur": [REGION]}
    data = content_set(profile_card=IMAGE, ocr=subtitled) | {
        "comments": [{"text": "wow", "author": "viewer", "source": "input", "card": IMAGE}],
        "figures": [{"name": "Prabowo", "type": "person"}],
        "figures_status": "ok",
    }
    unsupported = project_content_set(parse(data)).projection.unsupported
    assert [(u.field, u.role, u.order) for u in unsupported] == [
        ("main.profile_card", "main", 0),
        ("main.ocr.mute_audio", "main", 0),
        ("main.ocr.subtitle_blur", "main", 0),
        ("comments.card", "comment", 0),
        ("figures", None, None),
    ]
    assert all(u.value_digest and len(u.value_digest) == 64 for u in unsupported)


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
