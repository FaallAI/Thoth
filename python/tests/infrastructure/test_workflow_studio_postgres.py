"""Opening a workflow in Studio on a disposable PostgreSQL: the real report row, draft,
attach and asset tables, with a local media store and a fake probe."""

from __future__ import annotations

import hashlib
import os
from pathlib import Path

import psycopg
import pytest

from tests.application.test_workflow_studio_imports import (
    ACTOR,
    OCR,
    WF,
    Probe,
    content_set_bytes,
    content_set_data,
    seed_media,
    stored_run,
)
from thoth_control_plane.application.studio_imports import StudioImportService
from thoth_control_plane.application.workflow_studio_imports import (
    WorkflowStudioImportService,
    content_set_location,
)
from thoth_control_plane.domain.studio_layout import (
    CARD_CENTER_Y,
    CARD_GAP,
    profile_slot,
    reaction_beat,
    reading_seconds,
)
from thoth_control_plane.infrastructure.editor_asset_repository import (
    PostgresEditorAssetRepository,
)
from thoth_control_plane.infrastructure.media_store import LocalMediaStore
from thoth_control_plane.infrastructure.project_store import ProjectStore
from thoth_control_plane.infrastructure.report_store import ReportStore
from thoth_control_plane.infrastructure.studio_import_repository import (
    PostgresStudioImportRepository,
)
from thoth_control_plane.infrastructure.workflow_run_store import WorkflowRunStore
from thoth_control_plane.operations.editor_migrations import apply_editor_migrations

MIGRATIONS = Path(__file__).resolve().parents[2] / "migrations" / "editor"
DATABASE_URL = os.environ.get("THOTH_TEST_EDITOR_DATABASE_URL", "")

pytestmark = pytest.mark.skipif(
    not DATABASE_URL, reason="THOTH_TEST_EDITOR_DATABASE_URL points at a disposable Postgres"
)


@pytest.fixture
def database() -> str:
    with psycopg.connect(DATABASE_URL, autocommit=True) as connection:
        connection.execute("DROP SCHEMA public CASCADE")
        connection.execute("CREATE SCHEMA public")
    apply_editor_migrations(DATABASE_URL, MIGRATIONS)
    return DATABASE_URL


async def test_a_workflow_opens_in_studio_on_the_real_tables(database: str, tmp_path: Path) -> None:
    project = ProjectStore.connect(database).create("Studio", "ws_bootstrap").project_id
    reports = ReportStore.connect(database)
    reports.put(content_set_location(WF), "content_set", content_set_bytes())
    runs = WorkflowRunStore.connect(database)
    runs.insert_missing(stored_run())
    media = LocalMediaStore(tmp_path / "store")
    seed_media(media, tmp_path)
    assets = PostgresEditorAssetRepository(database)
    imports = StudioImportService(PostgresStudioImportRepository(database))
    service = WorkflowStudioImportService(
        runs=runs, reports=reports, media=media, assets=assets, imports=imports, probe=Probe()
    )

    opened = await service.open(project, WF, ACTOR, "open-1")

    assert {(item.item_id, item.outcome) for item in opened.items} == {
        ("main_000", "copied"),
        ("footage_000", "copied"),
        ("footage_001", "copied"),
    }
    inventory = await imports.get_inventory(project, opened.draft.document_id)
    attached = {i.item_id: i.asset_id for i in inventory.items if i.disposition == "attached"}
    assert set(attached) == {"main_000", "footage_000", "footage_001"}
    record = await assets.get_ready_record(project_id=project, asset_id=attached["main_000"])
    assert record is not None and record.provenance == "workflow_import"
    assert record.artifact_location == f"uploads/{project}/{attached['main_000']}.mp4"
    assert runs.get(WF).project_id == project

    second = await service.open(project, WF, ACTOR, "open-2")

    assert {item.outcome for item in second.items} == {"reused"}
    with psycopg.connect(database) as connection:
        assert connection.execute("SELECT count(*) FROM editor_assets").fetchone() == (3,)

    # The orphan sweep sees every project's rows, and nothing else, as registered.
    lost = f"uploads/{project}/asset_lost.mp4"
    assert await assets.registered_locations([record.artifact_location, lost]) == {
        record.artifact_location
    }


BAND = {"x": 0.12, "y": 0.65, "w": 0.75, "h": 0.09, "start": 6.8, "end": 43.8}
SUBTITLED = OCR | {"outcome": "subtitle", "mute_audio": True, "subtitle_blur": [BAND]}
TEXTS = ["wah", "mantap betul", "keren", "lucu sekali"]


def card(name: str) -> dict:
    digest = hashlib.sha256(name.encode()).hexdigest()
    return {
        "location": f"reports/{WF}/cards/{name}.jpg",
        "media_type": "image/jpeg",
        "checksum": f"sha256:{digest}",
        "bytes": 700,
        "width": 1080,
        "height": 1350,
    }


def carded_set() -> dict:
    comments = [
        {
            "text": text,
            "author": f"viewer{i}",
            "likes": 100 - i,
            "source": "input",
            "card": card(f"c{i}"),
        }
        for i, text in enumerate(TEXTS)
    ]
    return content_set_data(profile_card=card("profile"), ocr=SUBTITLED) | {"comments": comments}


def open_carded(database: str, tmp_path: Path, probe: Probe):
    data = carded_set()
    project = ProjectStore.connect(database).create("Studio", "ws_bootstrap").project_id
    reports = ReportStore.connect(database)
    reports.put(content_set_location(WF), "content_set", content_set_bytes(data))
    runs = WorkflowRunStore.connect(database)
    runs.insert_missing(stored_run())
    media = LocalMediaStore(tmp_path / "store")
    seed_media(media, tmp_path, data)
    service = WorkflowStudioImportService(
        runs=runs,
        reports=reports,
        media=media,
        assets=PostgresEditorAssetRepository(database),
        imports=StudioImportService(PostgresStudioImportRepository(database)),
        probe=probe,
    )
    return project, service


def clips_of(database: str, project: str, document_id: str) -> tuple[dict, dict]:
    with psycopg.connect(database) as connection:
        [document] = connection.execute(
            "SELECT document_json FROM edit_document_revisions WHERE project_id = %s"
            " AND document_id = %s ORDER BY revision DESC LIMIT 1",
            (project, document_id),
        ).fetchone()
    clips = {clip["clip_id"]: clip for clip in document["clips"]}
    tracks = {track["track_id"]: track for track in document["tracks"]}
    return clips, tracks


async def test_cards_and_blur_land_where_the_layout_says(database: str, tmp_path: Path) -> None:
    project, service = open_carded(database, tmp_path, Probe())

    opened = await service.open(project, WF, ACTOR, "open-cards")

    outcomes = {item.item_id: (item.outcome, item.reason) for item in opened.items}
    assert outcomes["profile_card_000"][0] == "copied"
    assert [outcomes[f"comment_card_00{i}"][0] for i in range(3)] == ["copied"] * 3
    assert outcomes["comment_card_003"] == ("unresolved", "no_room_in_reaction_beat")
    clips, tracks = clips_of(database, project, opened.draft.document_id)
    fps = 30
    start, length = profile_slot(30.0)
    profile = clips["clip_profile_card_000"]
    assert (profile["track_id"], profile["from_frame"], profile["duration_in_frames"]) == (
        "track_b_roll",
        round(start * fps),
        round(length * fps),
    )
    assert profile["fit"] == "contain"
    assert profile["position"]["y"] == pytest.approx(CARD_CENTER_Y - 0.5)
    reading = [reading_seconds(text) for text in TEXTS]
    slots = reaction_beat(30.0, reading, not_before=start + length + CARD_GAP)
    for index in range(3):
        clip = clips[f"clip_comment_card_00{index}"]
        at, seconds = slots[index]
        assert (clip["track_id"], clip["from_frame"], clip["duration_in_frames"]) == (
            "track_b_roll",
            round(at * fps),
            round(seconds * fps),
        )
    main = clips["clip_main_000"]
    assert [(r["from_frame"], r["to_frame"]) for r in main["blur_regions"]] == [(204, 1314)]
    assert main["blur_enabled"] is False
    assert tracks["track_main_video"]["muted"] is False


async def test_overlay_items_wait_for_the_main(database: str, tmp_path: Path) -> None:
    probe = Probe(invalid={"tiktok-1"})
    project, service = open_carded(database, tmp_path, probe)

    first = await service.open(project, WF, ACTOR, "open-wait")

    outcomes = {item.item_id: (item.outcome, item.reason) for item in first.items}
    assert outcomes["main_000"][0] == "unresolved"
    assert outcomes["profile_card_000"] == ("unresolved", "main_not_attached")
    assert outcomes["comment_card_000"] == ("unresolved", "main_not_attached")

    probe.invalid = set()
    second = await service.open(project, WF, ACTOR, "open-wait")

    placed = {item.item_id: item.outcome for item in second.items}
    assert placed["main_000"] == "copied"
    assert placed["profile_card_000"] in {"copied", "reused"}
    clips, _ = clips_of(database, project, second.draft.document_id)
    assert clips["clip_profile_card_000"]["from_frame"] == 90


async def test_a_carousel_main_plays_its_slides_in_turn(database: str, tmp_path: Path) -> None:
    data = content_set_data(kind="images", video=None, ocr=None, images=[card("s1"), card("s2")])
    project = ProjectStore.connect(database).create("Studio", "ws_bootstrap").project_id
    reports = ReportStore.connect(database)
    reports.put(content_set_location(WF), "content_set", content_set_bytes(data))
    runs = WorkflowRunStore.connect(database)
    runs.insert_missing(stored_run())
    media = LocalMediaStore(tmp_path / "store")
    seed_media(media, tmp_path, data)
    service = WorkflowStudioImportService(
        runs=runs,
        reports=reports,
        media=media,
        assets=PostgresEditorAssetRepository(database),
        imports=StudioImportService(PostgresStudioImportRepository(database)),
        probe=Probe(),
    )

    opened = await service.open(project, WF, ACTOR, "open-slides")

    clips, _ = clips_of(database, project, opened.draft.document_id)
    first, second = clips["clip_main_000"], clips["clip_slide_000"]
    assert (first["track_id"], first["from_frame"], first["duration_in_frames"]) == (
        "track_main_video",
        0,
        90,
    )
    assert (second["track_id"], second["from_frame"], second["duration_in_frames"]) == (
        "track_main_video",
        90,
        90,
    )
    assert second["fit"] == "contain"
