"""Tests for the strict version 2 Creator Studio document contract."""

from __future__ import annotations

from copy import deepcopy
from typing import Any

import pytest
from pydantic import TypeAdapter, ValidationError

from tests.domain.edit_document_v2_fixtures import (
    audio_clip_payload,
    clip_by_id,
    document_v2_payload,
    document_with_every_clip_kind,
    mutate,
    track_by_id,
)
from tests.domain.test_edit_documents import valid_document
from thoth_control_plane.domain.edit_document_v2 import EditDocument, EditDocumentV2
from thoth_control_plane.domain.edit_documents import EditDocumentV1

DOCUMENT_ADAPTER: TypeAdapter[Any] = TypeAdapter(EditDocument)


def document_v2_fixture() -> EditDocumentV2:
    return EditDocumentV2.model_validate(document_v2_payload())


def test_version_two_accepts_all_registered_track_and_clip_kinds() -> None:
    document = EditDocumentV2.model_validate(document_with_every_clip_kind())

    assert document.schema_version == 2
    assert {track.kind for track in document.tracks} == {
        "main_video",
        "b_roll",
        "overlay",
        "caption",
        "narration",
        "music",
        "sfx",
    }
    assert {clip.kind for clip in document.clips} == {
        "text",
        "video",
        "caption",
        "overlay",
        "audio",
    }


def test_version_two_round_trips_without_coercion() -> None:
    payload = document_with_every_clip_kind()

    document = EditDocumentV2.model_validate(payload)

    assert EditDocumentV2.model_validate_json(document.model_dump_json()) == document
    # Story mode's fields read back at their defaults, which draw nothing new.
    for clip in payload["clips"]:
        clip["source_role"] = None
        if clip["kind"] == "video":
            clip.update(motion="none", emphasis={"highlight": False, "arrow": False})
        # Narration's fields (2026-10-31) read back at their defaults too.
        if clip["kind"] in {"video", "audio"}:
            clip["volume_keyframes"] = []
        if clip["kind"] == "video":
            clip["hold_after_source"] = False
        for cue in clip.get("cues", []):
            cue["words"] = []
    assert document.model_dump(mode="json") == payload


def cross_project_asset(payload: dict[str, Any]) -> dict[str, Any]:
    return mutate(payload, ("asset_refs", 0, "project_id"), "project_999")


def clip_on_wrong_track(payload: dict[str, Any]) -> dict[str, Any]:
    result = deepcopy(payload)
    clip_by_id(result, "clip_main")["track_id"] = "track_caption"
    track_by_id(result, "track_main_video")["clip_ids"] = []
    track_by_id(result, "track_caption")["clip_ids"] = ["clip_main"]
    return result


def clip_past_canvas(payload: dict[str, Any]) -> dict[str, Any]:
    result = deepcopy(payload)
    clip_by_id(result, "clip_main")["duration_in_frames"] = 301
    return result


def duplicate_track_id(payload: dict[str, Any]) -> dict[str, Any]:
    result = deepcopy(payload)
    track_by_id(result, "track_b_roll")["track_id"] = "track_main_video"
    return result


def clip_past_source(payload: dict[str, Any]) -> dict[str, Any]:
    return mutate(payload, ("asset_refs", 0, "duration_in_frames"), 299)


def unknown_asset(payload: dict[str, Any]) -> dict[str, Any]:
    result = deepcopy(payload)
    clip_by_id(result, "clip_main")["asset_id"] = "asset_missing"
    return result


def audio_clip_on_video_asset(payload: dict[str, Any]) -> dict[str, Any]:
    result = deepcopy(payload)
    track_by_id(result, "track_music")["clip_ids"] = ["clip_music"]
    result["clips"].append(audio_clip_payload(asset_id="asset_main"))
    return result


def overlapping_main_video(payload: dict[str, Any]) -> dict[str, Any]:
    result = deepcopy(payload)
    clip_by_id(result, "clip_main")["duration_in_frames"] = 200
    second = deepcopy(clip_by_id(result, "clip_main"))
    second["clip_id"] = "clip_main_two"
    second["from_frame"] = 100
    second["duration_in_frames"] = 200
    result["clips"].append(second)
    track_by_id(result, "track_main_video")["clip_ids"] = ["clip_main", "clip_main_two"]
    return result


def track_membership_mismatch(payload: dict[str, Any]) -> dict[str, Any]:
    result = deepcopy(payload)
    track_by_id(result, "track_main_video")["clip_ids"] = []
    return result


def duplicate_track_order(payload: dict[str, Any]) -> dict[str, Any]:
    result = deepcopy(payload)
    track_by_id(result, "track_b_roll")["order"] = 0
    return result


def scene_range_escape(payload: dict[str, Any]) -> dict[str, Any]:
    return mutate(payload, ("clips", 0, "duration_in_frames"), 151)


def unknown_scene(payload: dict[str, Any]) -> dict[str, Any]:
    return mutate(payload, ("clips", 0, "scene_id"), "scene_999")


@pytest.mark.parametrize(
    ("mutation", "message"),
    [
        (cross_project_asset, "asset reference project must match document"),
        (clip_on_wrong_track, "clip kind is incompatible with track"),
        (clip_past_canvas, "clip range exceeds canvas"),
        (duplicate_track_id, "duplicate track IDs are not allowed"),
        (clip_past_source, "clip range exceeds source asset duration"),
        (unknown_asset, "clip references an unknown asset"),
        (audio_clip_on_video_asset, "clip kind is incompatible with asset"),
        (overlapping_main_video, "main video clips must not overlap"),
        (track_membership_mismatch, "track clip IDs must match assigned clips"),
        (duplicate_track_order, "track order values must be unique"),
        (scene_range_escape, "clip range must stay inside its scene"),
        (unknown_scene, "clip references an unknown scene"),
    ],
)
def test_version_two_rejects_invalid_structure(mutation: Any, message: str) -> None:
    with pytest.raises(ValidationError, match=message):
        EditDocumentV2.model_validate(mutation(document_v2_payload()))


def test_version_two_rejects_unknown_fields_and_non_integer_timing() -> None:
    with pytest.raises(ValidationError):
        EditDocumentV2.model_validate({**document_v2_payload(), "unsafe": "nope"})

    with pytest.raises(ValidationError):
        EditDocumentV2.model_validate(
            mutate(document_v2_payload(), ("clips", 0, "from_frame"), 0.5)
        )


def test_version_two_rejects_locator_like_asset_fields() -> None:
    payload = document_v2_payload()
    payload["asset_refs"][0]["artifact_location"] = "assets/project_001/asset_main.mp4"

    with pytest.raises(ValidationError):
        EditDocumentV2.model_validate(payload)


def test_asset_reference_exposes_no_artifact_location() -> None:
    document = document_v2_fixture()

    assert "artifact_location" not in document.asset_refs[0].model_dump()
    assert (
        "artifact_location"
        not in EditDocumentV2.model_json_schema()["$defs"]["AssetRef"]["properties"]
    )


def test_version_one_fixture_and_discriminator_still_work() -> None:
    v1_payload = valid_document()

    assert DOCUMENT_ADAPTER.validate_python(v1_payload).schema_version == 1
    assert isinstance(DOCUMENT_ADAPTER.validate_python(v1_payload), EditDocumentV1)
    assert DOCUMENT_ADAPTER.validate_python(document_v2_payload()).schema_version == 2

    with pytest.raises(ValidationError):
        DOCUMENT_ADAPTER.validate_python({**v1_payload, "schema_version": 3})


# --- Narration fields (spec 2026-10-31 auto-draft): optional, defaults draw nothing new. ---


def test_a_document_without_narration_fields_reads_back_at_their_defaults() -> None:
    document = EditDocumentV2.model_validate(document_with_every_clip_kind())
    caption = next(clip for clip in document.clips if clip.kind == "caption")
    main = next(clip for clip in document.clips if clip.clip_id == "clip_main")
    music = next(clip for clip in document.clips if clip.clip_id == "clip_music")
    assert all(cue.words == [] for cue in caption.cues)
    assert (main.volume_keyframes, main.hold_after_source) == ([], False)
    assert music.volume_keyframes == []
    assert EditDocumentV2.model_validate_json(document.model_dump_json()) == document


def test_word_cues_keyframes_and_the_word_highlight_style_validate() -> None:
    payload = document_with_every_clip_kind()
    caption = clip_by_id(payload, "clip_caption")
    caption["style_slot"] = "word_highlight"
    caption["cues"][0]["words"] = [
        {"from_frame": 0, "duration_in_frames": 10, "text": "Halo"},
        {"from_frame": 10, "duration_in_frames": 10, "text": "semua"},
    ]
    clip_by_id(payload, "clip_main")["volume_keyframes"] = [
        {"frame": 0, "volume": 1.0},
        {"frame": 48, "volume": 0.12},
    ]
    clip_by_id(payload, "clip_music")["volume_keyframes"] = [{"frame": 0, "volume": 0.45}]

    document = EditDocumentV2.model_validate(payload)

    assert len(next(c for c in document.clips if c.kind == "caption").cues[0].words) == 2


def test_a_caption_word_outside_its_cue_is_refused() -> None:
    payload = document_with_every_clip_kind()
    cue = clip_by_id(payload, "clip_caption")["cues"][0]
    cue["words"] = [
        {"from_frame": 0, "duration_in_frames": cue["duration_in_frames"] + 1, "text": "x"}
    ]
    with pytest.raises(ValidationError, match="caption words must stay inside their cue"):
        EditDocumentV2.model_validate(payload)


@pytest.mark.parametrize(
    "keyframes",
    [
        [{"frame": 10, "volume": 1.0}, {"frame": 10, "volume": 0.5}],
        [{"frame": 20, "volume": 1.0}, {"frame": 5, "volume": 0.5}],
        [{"frame": 300, "volume": 1.0}],
    ],
)
def test_volume_keyframes_must_be_increasing_and_inside_the_clip(
    keyframes: list[dict[str, Any]],
) -> None:
    payload = document_with_every_clip_kind()
    clip_by_id(payload, "clip_main")["volume_keyframes"] = keyframes
    with pytest.raises(
        ValidationError, match="volume keyframes must be increasing and inside the clip"
    ):
        EditDocumentV2.model_validate(payload)


def test_a_held_video_clip_may_run_past_its_source() -> None:
    payload = document_with_every_clip_kind()
    main = clip_by_id(payload, "clip_main")
    main["source_from_frame"] = 800  # the asset has 900 frames; the clip runs 300

    with pytest.raises(ValidationError, match="clip range exceeds source asset duration"):
        EditDocumentV2.model_validate(deepcopy(payload))
    main["hold_after_source"] = True
    assert EditDocumentV2.model_validate(payload)
