"""Opening a workflow in Studio: reuse, probe in place, copy, attach, and resumable replay."""

from __future__ import annotations

import asyncio
import dataclasses
import hashlib
import json
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import pytest

from tests.application.test_studio_imports import MemoryStudioImports
from tests.assembly.test_models import OCR, content_set
from tests.test_metering import Sink
from thoth_control_plane import metering
from thoth_control_plane.application.editor_asset_ports import (
    EditorAssetMediaInvalid,
    EditorAssetPersistenceError,
)
from thoth_control_plane.application.ports import (
    EditDocumentRevisionConflict,
    StudioImportDecisionRejected,
    StudioImportItemResolved,
)
from thoth_control_plane.application.studio_imports import StudioImportService
from thoth_control_plane.application.workflow_studio_imports import (
    ContentSetInvalid,
    ContentSetUnavailable,
    WorkflowInOtherProject,
    WorkflowStudioImportService,
    WorkflowStudioUnavailable,
)
from thoth_control_plane.application.workflows import WorkflowNotFound
from thoth_control_plane.assembly.studio import workflow_source_key
from thoth_control_plane.domain.editor_assets import EditorAssetRecord
from thoth_control_plane.domain.models import Actor
from thoth_control_plane.domain.studio_imports import (
    AttachImportAsset,
    ExcludeImportItem,
    ResolveStudioImportItem,
)
from thoth_control_plane.domain.workflow_runs import StoredRun
from thoth_control_plane.infrastructure.media_store import LocalMediaStore, MeteredMediaStore
from thoth_control_plane.metering import MeterScope

PROJECT = "project_001"
WF = "wf_a"
ACTOR = Actor(actor_id="owner", actor_type="user")
COVER = OCR | {"outcome": "cover", "trim_start": 1.0}
VIDEO_REPORT = {
    "streams": [
        {"codec_type": "video", "width": 1080, "height": 1920, "avg_frame_rate": "30/1"},
        {"codec_type": "audio"},
    ],
    "format": {"duration": "30.0"},
}
IMAGE_REPORT = {"streams": [{"codec_type": "video", "width": 1080, "height": 1350}], "format": {}}
ALL_COPIED = [("main_000", "copied"), ("footage_000", "copied"), ("footage_001", "copied")]


def footage(index: int, **changes: Any) -> dict[str, Any]:
    item: dict[str, Any] = {
        "source": "search",
        "url": f"https://www.tiktok.com/@kreator/video/740000000000000000{index}",
        "platform": "tiktok",
        "owner_handle": "kreator",
        "query": "banjir jakarta",
        "description": f"Footage {index}",
        "video": {
            "location": f"reports/{WF}/footage/clip-{index}.mp4",
            "media_type": "video/mp4",
            "checksum": "sha256:" + "cd"[index] * 64,
            "bytes": 2048,
            "duration_seconds": 20.0,
        },
        "clip_start": 0.0,
        "ocr": OCR,
        "story_score": 0.61,
        "shows_object": "yes",
    }
    item.update(changes)
    return item


def content_set_data(**main: Any) -> dict[str, Any]:
    return content_set(**main) | {
        "footage": [footage(0, ocr=COVER), footage(1)],
        "footage_status": "ok",
    }


def content_set_bytes(data: dict[str, Any] | None = None) -> bytes:
    return json.dumps(data or content_set_data()).encode()


def seed_media(media: Any, tmp_path: Path, data: dict[str, Any] | None = None) -> None:
    """Store one object per MediaRef, exactly as many bytes as it declares."""
    data = data or content_set_data()
    main = data["main"]
    refs = [ref for ref in (main.get("video"), main.get("card"), main.get("profile_card")) if ref]
    refs += [*main.get("images", []), *(item["video"] for item in data.get("footage", []))]
    refs += [comment["card"] for comment in data.get("comments", []) if comment.get("card")]
    for index, ref in enumerate(refs):
        source = tmp_path / f"seed-{index}.bin"
        source.write_bytes(b"m" * ref["bytes"])
        media.put_file(ref["location"], source)


def stored_run(
    project_id: str | None = None, actor_id: str = "owner", status: str = "succeeded"
) -> StoredRun:
    now = datetime(2026, 10, 20, tzinfo=UTC)
    return StoredRun(
        workflow_id=WF,
        project_id=project_id,
        actor_type="user",
        actor_id=actor_id,
        display_url="https://x.test/v",
        platform="tiktok",
        status=status,
        history_expired=False,
        summary=None,
        created_at=now,
        updated_at=now,
    )


class MemoryRuns:
    def __init__(self, *runs: StoredRun) -> None:
        self.runs = {run.workflow_id: run for run in runs}

    def get(self, workflow_id: str) -> StoredRun | None:
        return self.runs.get(workflow_id)

    def claim(self, workflow_id: str, project_id: str) -> StoredRun | None:
        run = self.runs.get(workflow_id)
        if run is None:
            return None
        if run.project_id is None:
            self.runs[workflow_id] = dataclasses.replace(run, project_id=project_id)
        return self.runs[workflow_id]


class MemoryReports:
    def __init__(self, content: bytes | None) -> None:
        self.rows = {} if content is None else {f"reports/{WF}/content-set.json": content}

    def get(self, location: str) -> bytes | None:
        return self.rows.get(location)


class MemoryAssets:
    def __init__(self, *, fail_register: bool = False) -> None:
        self.records: list[EditorAssetRecord] = []
        self.fail_register = fail_register

    async def find_ready_by_checksum(
        self, *, project_id: str, checksum: str
    ) -> EditorAssetRecord | None:
        return next(
            (
                record
                for record in self.records
                if (record.asset.project_id, record.asset.checksum) == (project_id, checksum)
            ),
            None,
        )

    async def register_ready(self, record: EditorAssetRecord) -> None:
        if self.fail_register:
            raise EditorAssetPersistenceError()
        self.records.append(record)


class AttachingImports(MemoryStudioImports):
    """MemoryStudioImports plus the decision path, with the refusals Postgres gives."""

    def __init__(
        self,
        refuse: dict[str, str] | None = None,
        conflict: set[str] | None = None,
        conflict_once: set[str] | None = None,
        decide_first: set[str] | None = None,
    ) -> None:
        super().__init__()
        self.refuse = refuse or {}
        self.conflict = conflict or set()
        self.conflict_once = conflict_once or set()  # an unrelated edit bumps the revision once
        self.decide_first = decide_first or set()  # a person excludes the item in the gate first

    async def resolve_item(
        self,
        *,
        project_id: str,
        document_id: str,
        item_id: str,
        base_revision: int,
        decision: Any,
    ) -> Any:
        row = next(
            row
            for row in self.rows
            if (row["project_id"], row["draft"].document_id) == (project_id, document_id)
        )
        if item_id in self.decide_first:
            self.decide_first.discard(item_id)
            row["inventory"] = [
                item.model_copy(update={"disposition": "excluded"})
                if item.item_id == item_id
                else item
                for item in row["inventory"]
            ]
            raise StudioImportItemResolved()
        if item_id in self.conflict_once:
            self.conflict_once.discard(item_id)
            raise EditDocumentRevisionConflict(row["document"])
        if item_id in self.conflict or base_revision != row["draft"].revision:
            raise EditDocumentRevisionConflict(row["document"])
        entry = next(item for item in row["inventory"] if item.item_id == item_id)
        if entry.disposition != "unresolved":
            raise StudioImportItemResolved()
        if item_id in self.refuse:
            raise StudioImportDecisionRejected(self.refuse[item_id])
        attached = isinstance(decision, AttachImportAsset)
        row["inventory"] = [
            item.model_copy(
                update={
                    "disposition": "attached" if attached else "excluded",
                    "asset_id": decision.asset_id if attached else None,
                }
            )
            if item.item_id == item_id
            else item
            for item in row["inventory"]
        ]
        row["draft"] = row["draft"].model_copy(update={"revision": row["draft"].revision + 1})
        return await self.get_inventory(project_id=project_id, document_id=document_id)


class Probe:
    def __init__(self, invalid: set[str] | None = None) -> None:
        self.sources: list[str] = []
        self.invalid = invalid or set()

    async def __call__(self, source: Path | str) -> dict[str, Any]:
        self.sources.append(str(source))
        if any(name in str(source) for name in self.invalid):
            raise EditorAssetMediaInvalid("invalid_media")
        return IMAGE_REPORT if str(source).endswith(".jpg") else VIDEO_REPORT


@dataclasses.dataclass
class World:
    service: WorkflowStudioImportService
    runs: MemoryRuns
    media: LocalMediaStore
    assets: MemoryAssets
    imports: AttachingImports
    probe: Probe


def world(
    tmp_path: Path,
    *,
    data: dict[str, Any] | None = None,
    reports: Any = None,
    run: StoredRun | None = None,
    assets: MemoryAssets | None = None,
    imports: AttachingImports | None = None,
    probe: Probe | None = None,
) -> World:
    media = LocalMediaStore(tmp_path / "store")
    seed_media(media, tmp_path, data)
    runs = MemoryRuns(run or stored_run())
    assets, imports, probe = (
        assets or MemoryAssets(),
        imports or AttachingImports(),
        probe or Probe(),
    )
    service = WorkflowStudioImportService(
        runs=runs,
        reports=reports or MemoryReports(content_set_bytes(data)),
        media=MeteredMediaStore(media),
        assets=assets,
        imports=StudioImportService(imports),
        probe=probe,
    )
    return World(service, runs, media, assets, imports, probe)


def outcomes(opened: Any) -> list[tuple[str, str]]:
    return [(item.item_id, item.outcome) for item in opened.items]


async def test_inspect_is_read_only_and_keyed_by_the_workflow(tmp_path: Path) -> None:
    w = world(tmp_path)
    found = await w.service.inspect(PROJECT, WF, ACTOR)
    digest = hashlib.sha256(content_set_bytes()).hexdigest()
    assert found.source_key == workflow_source_key(WF, digest)
    media = {item.item_id for item in found.items if item.media_kind != "none"}
    assert media == {"main_000", "footage_000", "footage_001"}
    assert found.drafts == []
    assert (w.runs.get(WF).project_id, w.assets.records, w.imports.rows) == (None, [], [])


async def test_open_probes_in_place_copies_registers_and_attaches(tmp_path: Path) -> None:
    w = world(tmp_path)
    opened = await w.service.open(PROJECT, WF, ACTOR, "open-1")

    assert outcomes(opened) == ALL_COPIED
    assert w.runs.get(WF).project_id == PROJECT
    assert len(w.probe.sources) == 3
    assert all(source.startswith(str(w.media.root)) for source in w.probe.sources)
    for record in w.assets.records:
        assert record.provenance == "workflow_import"
        assert record.artifact_location == f"uploads/{PROJECT}/{record.asset.asset_id}.mp4"
    assert sorted(w.media.size(r.artifact_location) for r in w.assets.records) == [
        2048,
        2048,
        20000,
    ]
    inventory = await StudioImportService(w.imports).get_inventory(
        PROJECT, opened.draft.document_id
    )
    attached = {i.item_id: i.disposition for i in inventory.items if i.media_kind != "none"}
    assert set(attached.values()) == {"attached"}
    assert opened.draft.revision == inventory.revision == 4


async def test_a_project_asset_with_the_same_bytes_is_reused(tmp_path: Path) -> None:
    w = world(tmp_path)
    await w.service.open(PROJECT, WF, ACTOR, "open-1")
    copies = w.media.list(f"uploads/{PROJECT}/")

    second = await w.service.open(PROJECT, WF, ACTOR, "open-2")

    assert {outcome for _, outcome in outcomes(second)} == {"reused"}
    assert w.media.list(f"uploads/{PROJECT}/") == copies
    assert len(w.probe.sources) == 3


async def test_replaying_the_key_finishes_what_a_cut_off_attempt_left(tmp_path: Path) -> None:
    w = world(tmp_path, assets=MemoryAssets(fail_register=True))
    first = await w.service.open(PROJECT, WF, ACTOR, "open-1")
    assert {(item.outcome, item.reason) for item in first.items} == {
        ("unresolved", "asset_unavailable")
    }
    assert w.media.list(f"uploads/{PROJECT}/") == []  # every orphan copy was removed

    w.assets.fail_register = False
    again = await w.service.open(PROJECT, WF, ACTOR, "open-1")
    third = await w.service.open(PROJECT, WF, ACTOR, "open-1")

    assert again.draft.document_id == first.draft.document_id
    assert outcomes(again) == ALL_COPIED
    assert {outcome for _, outcome in outcomes(third)} == {"decided"}
    assert len(w.imports.rows) == 1


async def test_an_excluded_item_is_not_retried(tmp_path: Path) -> None:
    w = world(tmp_path, probe=Probe(invalid={"clip-1"}))
    first = await w.service.open(PROJECT, WF, ACTOR, "open-1")
    assert ("footage_001", "unresolved") in outcomes(first)
    imports = StudioImportService(w.imports)
    inventory = await imports.get_inventory(PROJECT, first.draft.document_id)
    exclude = ResolveStudioImportItem(
        base_revision=inventory.revision, decision=ExcludeImportItem(kind="exclude")
    )
    await imports.resolve(PROJECT, first.draft.document_id, "footage_001", exclude)

    again = await w.service.open(PROJECT, WF, ACTOR, "open-1")

    assert {outcome for _, outcome in outcomes(again)} == {"decided"}
    assert sum("clip-1" in source for source in w.probe.sources) == 1


@pytest.mark.parametrize(
    ("damage", "reason"), [("delete", "media_missing"), ("grow", "media_mismatch")]
)
async def test_a_missing_or_changed_object_leaves_only_its_item(
    tmp_path: Path, damage: str, reason: str
) -> None:
    w = world(tmp_path)
    location = f"reports/{WF}/footage/clip-0.mp4"
    if damage == "delete":
        w.media.delete(location)
    else:
        bigger = tmp_path / "bigger.bin"
        bigger.write_bytes(b"m" * 4096)
        w.media.put_file(location, bigger)

    opened = await w.service.open(PROJECT, WF, ACTOR, "open-1")

    found = {item.item_id: (item.outcome, item.reason) for item in opened.items}
    assert found["footage_000"] == ("unresolved", reason)
    assert found["main_000"] == ("copied", None)


async def test_invalid_media_is_never_copied(tmp_path: Path) -> None:
    w = world(tmp_path, probe=Probe(invalid={"clip-0"}))
    opened = await w.service.open(PROJECT, WF, ACTOR, "open-1")
    found = {item.item_id: (item.outcome, item.reason) for item in opened.items}
    assert found["footage_000"] == ("unresolved", "media_invalid")
    assert len(w.media.list(f"uploads/{PROJECT}/")) == 2


async def test_a_refused_attach_keeps_the_registered_asset(tmp_path: Path) -> None:
    w = world(tmp_path, imports=AttachingImports(refuse={"footage_000": "trim_exceeds_asset"}))
    opened = await w.service.open(PROJECT, WF, ACTOR, "open-1")
    found = {item.item_id: (item.outcome, item.reason) for item in opened.items}
    assert found["footage_000"] == ("unresolved", "trim_exceeds_asset")
    assert len(w.assets.records) == 3


async def test_a_decision_made_meanwhile_in_the_gate_stands(tmp_path: Path) -> None:
    w = world(tmp_path, imports=AttachingImports(conflict={"footage_000"}))
    opened = await w.service.open(PROJECT, WF, ACTOR, "open-1")
    found = {item.item_id: (item.outcome, item.reason) for item in opened.items}
    assert found["footage_000"] == ("unresolved", "draft_changed")
    assert found["footage_001"] == ("copied", None)


async def test_an_upper_case_checksum_is_stored_lower_case(tmp_path: Path) -> None:
    data = content_set_data()
    # A copy: `content_set()` shares the module-level VIDEO dict with every other test.
    data["main"]["video"] = data["main"]["video"] | {"checksum": "sha256:" + "A" * 64}
    w = world(tmp_path, data=data)
    opened = await w.service.open(PROJECT, WF, ACTOR, "open-1")
    assert outcomes(opened) == ALL_COPIED
    assert "sha256:" + "a" * 64 in {record.asset.checksum for record in w.assets.records}


async def test_an_images_main_imports_its_first_slide_as_a_still(tmp_path: Path) -> None:
    slide = {
        "location": f"reports/{WF}/media/slide-1.jpg",
        "media_type": "image/jpeg",
        "checksum": "sha256:" + "b" * 64,
        "bytes": 900,
        "width": 1080,
        "height": 1350,
    }
    data = content_set_data(kind="images", video=None, ocr=None, images=[slide])
    w = world(tmp_path, data=data)
    opened = await w.service.open(PROJECT, WF, ACTOR, "open-1")
    assert outcomes(opened)[0] == ("main_000", "copied")
    [still] = [r for r in w.assets.records if r.asset.kind == "image"]
    assert still.artifact_location.endswith(".jpg")


async def test_a_lagging_run_status_does_not_block_the_import(tmp_path: Path) -> None:
    w = world(tmp_path, run=stored_run(status="running"))
    assert outcomes(await w.service.open(PROJECT, WF, ACTOR, "open-1")) == ALL_COPIED


async def test_copies_count_as_stored_media_for_the_workspace(tmp_path: Path) -> None:
    sink = Sink()
    metering.install(sink)
    w = world(tmp_path)
    with metering.scoped(MeterScope("ws_a", project_id=PROJECT)):
        await w.service.open(PROJECT, WF, ACTOR, "open-1")
    stored = sorted(event.quantity for event in sink.events if event.key == "uploads")
    assert stored == [2048.0, 2048.0, 20000.0]


async def test_an_unknown_or_foreign_run_is_not_found(tmp_path: Path) -> None:
    w = world(tmp_path, run=stored_run(actor_id="ws_other"))
    with pytest.raises(WorkflowNotFound):
        await w.service.inspect(PROJECT, WF, ACTOR)
    with pytest.raises(WorkflowNotFound):
        await w.service.open(PROJECT, "wf_unknown", ACTOR, "open-1")


async def test_a_run_of_another_project_is_refused_before_any_write(tmp_path: Path) -> None:
    w = world(tmp_path, run=stored_run(project_id="project_002"))
    with pytest.raises(WorkflowInOtherProject):
        await w.service.open(PROJECT, WF, ACTOR, "open-1")
    assert w.imports.rows == []


@pytest.mark.parametrize(
    ("content", "error"),
    [
        (None, ContentSetUnavailable),
        (b"{}", ContentSetInvalid),
        (content_set_bytes(content_set_data() | {"workflow_id": "wf_b"}), ContentSetInvalid),
    ],
)
async def test_a_missing_or_invalid_content_set_creates_nothing(
    tmp_path: Path, content: bytes | None, error: type[Exception]
) -> None:
    w = world(tmp_path, reports=MemoryReports(content))
    with pytest.raises(error):
        await w.service.open(PROJECT, WF, ACTOR, "open-1")
    assert (w.imports.rows, w.runs.get(WF).project_id) == ([], None)


async def test_an_unreachable_report_store_is_unavailable(tmp_path: Path) -> None:
    class Down:
        def get(self, location: str) -> bytes | None:
            raise RuntimeError("database down")

    w = world(tmp_path, reports=Down())
    with pytest.raises(WorkflowStudioUnavailable):
        await w.service.inspect(PROJECT, WF, ACTOR)


async def test_a_missing_ffprobe_fails_loud(tmp_path: Path) -> None:
    class NoFfprobe(Probe):
        async def __call__(self, source: Path | str) -> dict[str, Any]:
            raise FileNotFoundError("ffprobe")

    w = world(tmp_path, probe=NoFfprobe())
    with pytest.raises(WorkflowStudioUnavailable):
        await w.service.open(PROJECT, WF, ACTOR, "open-1")


async def test_an_unreachable_media_store_creates_no_draft(tmp_path: Path) -> None:
    class DownStore(LocalMediaStore):
        def check(self) -> None:
            raise RuntimeError("media store down")

    w = world(tmp_path)
    w.service._media = MeteredMediaStore(DownStore(tmp_path / "store"))
    with pytest.raises(WorkflowStudioUnavailable):
        await w.service.open(PROJECT, WF, ACTOR, "open-1")
    assert (w.imports.rows, w.runs.get(WF).project_id) == ([], None)


async def test_an_unrelated_edit_during_an_attach_is_retried_once(tmp_path: Path) -> None:
    w = world(tmp_path, imports=AttachingImports(conflict_once={"footage_000"}))
    assert outcomes(await w.service.open(PROJECT, WF, ACTOR, "open-1")) == ALL_COPIED


async def test_an_item_decided_meanwhile_is_reported_decided(tmp_path: Path) -> None:
    w = world(tmp_path, imports=AttachingImports(decide_first={"footage_000"}))
    opened = await w.service.open(PROJECT, WF, ACTOR, "open-1")
    found = {item.item_id: (item.outcome, item.reason) for item in opened.items}
    assert found["footage_000"] == ("decided", None)
    assert found["footage_001"] == ("copied", None)


async def test_another_tab_claiming_the_run_first_wins(tmp_path: Path) -> None:
    class ClaimedElsewhere(MemoryRuns):
        def claim(self, workflow_id: str, project_id: str) -> StoredRun | None:
            self.runs[workflow_id] = stored_run(project_id="project_002")
            return super().claim(workflow_id, project_id)

    w = world(tmp_path)
    w.service._runs = ClaimedElsewhere(stored_run())
    with pytest.raises(WorkflowInOtherProject):
        await w.service.open(PROJECT, WF, ACTOR, "open-1")
    assert w.imports.rows == []
    assert w.service._runs.get(WF).project_id == "project_002"


async def test_a_cancelled_registration_leaves_no_copy(tmp_path: Path) -> None:
    class Cancelled(MemoryAssets):
        async def register_ready(self, record: EditorAssetRecord) -> None:
            raise asyncio.CancelledError

    w = world(tmp_path, assets=Cancelled())
    with pytest.raises(asyncio.CancelledError):
        await w.service.open(PROJECT, WF, ACTOR, "open-1")
    assert w.media.list(f"uploads/{PROJECT}/") == []


async def test_a_copy_rolled_back_is_never_counted(tmp_path: Path) -> None:
    sink = Sink()
    metering.install(sink)
    w = world(tmp_path, assets=MemoryAssets(fail_register=True))
    with metering.scoped(MeterScope("ws_a", project_id=PROJECT)):
        await w.service.open(PROJECT, WF, ACTOR, "open-1")
    assert [event for event in sink.events if event.key == "uploads"] == []
