"""The activity reads persisted reports, writes the content set atomically, and redacts."""

from __future__ import annotations

import asyncio
import json
from hashlib import sha256
from pathlib import Path

import pytest

from tests.assembly.support import comment, report
from tests.conftest import DownReports
from thoth_control_plane.activities.content_assembly import (
    ContentAssemblyActivityInput,
    _run,
    build_content_assembly_activity,
)
from thoth_control_plane.assembly.models import ContentSet
from thoth_control_plane.assembly.ports import AssemblyError
from thoth_control_plane.assembly.service import AssemblyInputs
from thoth_control_plane.config import Settings
from thoth_control_plane.infrastructure.report_store import ReportStoreUnavailable


def _settings(tmp_path: Path) -> Settings:
    return Settings(  # type: ignore[arg-type]
        THOTH_CONTROL_PLANE_API_KEY="k", THOTH_CONTROL_PLANE_ARTIFACT_ROOT=tmp_path
    )


class FakeAssembler:
    def __init__(self, error: str | None = None) -> None:
        self.error, self.inputs = error, []

    async def build(self, inputs: AssemblyInputs) -> ContentSet:
        self.inputs.append(inputs)
        if self.error:
            raise AssemblyError(self.error)
        return ContentSet.model_validate_json(
            json.dumps(
                {
                    "workflow_id": inputs.workflow_id,
                    "attribution_verdict": "none",
                    "main": {
                        "source": "input",
                        "url": "https://www.tiktok.com/@creator/video/1234567890",
                        "platform": "tiktok",
                        "owner_handle": "creator",
                        "kind": "card",
                        "card": {
                            "location": "reports/wf_a/cards/post.png",
                            "media_type": "image/png",
                            "checksum": "sha256:" + "c" * 64,
                            "bytes": 2048,
                        },
                    },
                    "comments": [{"text": "rahasia komentar", "author": "a", "source": "input"}],
                    "figures_status": "none",
                }
            )
        )


def persist(store, workflow_id: str = "wf_a", **kwargs) -> None:
    store.put(
        f"reports/{workflow_id}/source-report.json",
        "source_report",
        report(workflow_id=workflow_id, **kwargs).model_dump_json().encode("utf-8"),
    )


def run(root: Path, store, assembler: FakeAssembler, **kwargs):
    return asyncio.run(
        _run(ContentAssemblyActivityInput(workflow_id="wf_a", **kwargs), root, assembler, store)
    )


def stored_content_set(store) -> bytes:
    stored = store.get("reports/wf_a/content-set.json")
    assert stored is not None
    return stored


def test_writes_the_content_set_with_a_matching_checksum(tmp_path: Path, report_store) -> None:
    persist(report_store)

    result = run(tmp_path, report_store, FakeAssembler())

    written = stored_content_set(report_store)
    assert result.content_set is not None and result.failure is None
    assert result.content_set.location == "reports/wf_a/content-set.json"
    assert result.content_set.checksum == "sha256:" + sha256(written).hexdigest()
    assert result.content_set.kind == "content_set"
    assert not (tmp_path / "reports").exists()
    payload = result.events[0].payload
    assert payload["stage"] == "assembly" and payload["status"] == "succeeded"
    assert payload["comment_count"] == 1 and payload["ocr_outcome"] == "none"


def test_a_second_run_replaces_the_content_set(tmp_path: Path, report_store) -> None:
    persist(report_store, comments=[comment("a", "satu", 1)])
    run(tmp_path, report_store, FakeAssembler())
    second = run(tmp_path, report_store, FakeAssembler())

    stored = ContentSet.model_validate_json(stored_content_set(report_store))
    assert len(stored.comments) == 1
    assert second.content_set is not None


def test_no_report_is_a_failure(tmp_path: Path, report_store) -> None:
    result = run(tmp_path, report_store, FakeAssembler())

    assert result.failure == "source_report_missing" and result.content_set is None
    assert result.events[0].payload["reason"] == "source_report_missing"


def test_replaced_reads_the_original_report_it_is_given(tmp_path: Path, report_store) -> None:
    persist(report_store)
    persist(report_store, workflow_id="wf_a-c1", owner="source")
    report_store.put(
        "reports/wf_a/source-attribution.json",
        "source_attribution",
        json.dumps(
            {
                "schema_version": 1,
                "workflow_id": "wf_a",
                "input": {
                    "platform": "tiktok",
                    "canonical_url": "https://www.tiktok.com/@creator/video/1234567890",
                    "owner_handle": "creator",
                },
                "verdict": "replaced",
                "source": {
                    "platform": "tiktok",
                    "canonical_url": "https://www.tiktok.com/@source/video/1",
                    "owner_handle": "source",
                },
            }
        ).encode("utf-8"),
    )
    assembler = FakeAssembler()

    run(
        tmp_path,
        report_store,
        assembler,
        attribution="reports/wf_a/source-attribution.json",
        original_report="reports/wf_a-c1/source-report.json",
    )

    assert assembler.inputs[0].original is not None
    assert assembler.inputs[0].original.post.owner_handle == "source"


@pytest.mark.parametrize(
    "location", ["../etc/passwd", "/abs/source-report.json", "reports/x/other.json"]
)
def test_an_unsafe_original_location_is_ignored(
    tmp_path: Path, report_store, location: str
) -> None:
    persist(report_store)
    assembler = FakeAssembler()

    run(tmp_path, report_store, assembler, original_report=location)

    assert assembler.inputs[0].original is None


def test_assembly_failures_keep_their_code_and_write_nothing(tmp_path: Path, report_store) -> None:
    persist(report_store)

    result = run(tmp_path, report_store, FakeAssembler(error="incomplete_frame_coverage"))

    assert result.failure == "incomplete_frame_coverage"
    assert report_store.get("reports/wf_a/content-set.json") is None


def test_results_carry_no_text(tmp_path: Path, report_store) -> None:
    persist(report_store)

    result = run(tmp_path, report_store, FakeAssembler())

    assert "rahasia" not in result.model_dump_json()


def test_a_stale_attribution_on_disk_is_not_read(tmp_path: Path, report_store) -> None:
    # Review 2026-10-12: a crashed first attempt can leave `replaced` on disk while the
    # workflow received `unresolved`; assembly must follow what the workflow received.
    persist(report_store)
    report_store.put(
        "reports/wf_a/source-attribution.json",
        "source_attribution",
        json.dumps(
            {
                "schema_version": 1,
                "workflow_id": "wf_a",
                "input": {
                    "platform": "tiktok",
                    "canonical_url": "https://www.tiktok.com/@creator/video/1234567890",
                    "owner_handle": "creator",
                },
                "verdict": "replaced",
                "source": {
                    "platform": "tiktok",
                    "canonical_url": "https://www.tiktok.com/@source/video/1",
                    "owner_handle": "source",
                },
            }
        ).encode("utf-8"),
    )
    assembler = FakeAssembler()

    run(tmp_path, report_store, assembler)

    assert assembler.inputs[0].attribution is None


def test_a_retry_with_the_real_assembler_never_duplicates_comments(
    tmp_path: Path, report_store
) -> None:
    # Review 2026-10-12: the FakeAssembler returns a fixed set, so it cannot catch an append.
    from thoth_control_plane.assembly.service import AssemblyPorts, ContentAssembler

    class Unused:
        async def frame_at(self, *args, **kwargs):  # pragma: no cover - a card main has no OCR
            raise AssertionError("no frames for a card main")

        async def duration(self, *args, **kwargs):  # pragma: no cover
            raise AssertionError("no probe for a card main")

        async def read(self, *args, **kwargs):  # pragma: no cover
            raise AssertionError("no OCR for a card main")

    persist(
        report_store,
        media="none",
        post_card=True,
        comments=[
            comment("a", "komentar pertama yang berisi", 3),
            comment("b", "komentar kedua yang berisi", 2),
        ],
    )
    real = ContentAssembler(AssemblyPorts(frames=Unused(), probe=Unused(), text=Unused()))

    first = run(tmp_path, report_store, real)
    second = run(tmp_path, report_store, real)

    stored = ContentSet.model_validate_json(stored_content_set(report_store))
    assert [c.text for c in stored.comments] == [
        "komentar pertama yang berisi",
        "komentar kedua yang berisi",
    ]
    assert first.content_set == second.content_set


def test_assembly_reads_the_stored_report_and_stores_the_content_set(
    tmp_path: Path, report_store
) -> None:
    persist(report_store)
    activity = build_content_assembly_activity(
        _settings(tmp_path), assembler=FakeAssembler(), reports=report_store
    )
    result = asyncio.run(activity(ContentAssemblyActivityInput(workflow_id="wf_a")))

    stored = report_store.get("reports/wf_a/content-set.json")
    assert stored is not None
    assert result.content_set is not None
    assert result.content_set.checksum == f"sha256:{sha256(stored).hexdigest()}"
    assert not (tmp_path / "reports" / "wf_a" / "content-set.json").exists()


def test_assembly_without_a_stored_report_is_source_report_missing(
    tmp_path: Path, report_store
) -> None:
    activity = build_content_assembly_activity(
        _settings(tmp_path), assembler=FakeAssembler(), reports=report_store
    )
    result = asyncio.run(activity(ContentAssemblyActivityInput(workflow_id="wf_none")))
    assert result.failure == "source_report_missing"


def test_assembly_raises_when_the_database_is_down(tmp_path: Path) -> None:
    activity = build_content_assembly_activity(
        _settings(tmp_path), assembler=FakeAssembler(), reports=DownReports()
    )
    with pytest.raises(ReportStoreUnavailable):
        asyncio.run(activity(ContentAssemblyActivityInput(workflow_id="wf_down")))


def test_a_down_store_while_writing_the_content_set_raises(tmp_path: Path, report_store) -> None:
    persist(report_store)

    class ReadOnly(DownReports):
        def get(self, location: str) -> bytes | None:
            return report_store.get(location)

    activity = build_content_assembly_activity(
        _settings(tmp_path), assembler=FakeAssembler(), reports=ReadOnly()
    )
    with pytest.raises(ReportStoreUnavailable):
        asyncio.run(activity(ContentAssemblyActivityInput(workflow_id="wf_a")))


def test_assembly_reads_the_main_video_from_the_store(tmp_path: Path, report_store) -> None:
    from thoth_control_plane.infrastructure.media_store import LocalMediaStore

    store_root = tmp_path / "store"
    store_root.mkdir()
    media = LocalMediaStore(store_root)
    persist(report_store)
    video = str(report(workflow_id="wf_a").media[0].location)
    (tmp_path / "main.mp4").write_bytes(b"main-video")
    media.put_file(video, tmp_path / "main.mp4")
    roots: list[Path] = []

    class Reading(FakeAssembler):
        async def build(self, inputs: AssemblyInputs) -> ContentSet:
            roots.append(inputs.artifact_root)
            assert (inputs.artifact_root / video).read_bytes() == b"main-video"
            return await super().build(inputs)

    result = asyncio.run(
        _run(
            ContentAssemblyActivityInput(workflow_id="wf_a"),
            tmp_path / "unused-root",
            Reading(),
            report_store,
            media=media,
        )
    )
    assert result.content_set is not None
    assert roots and not roots[0].exists()


def test_the_heartbeat_covers_the_assembly_pull(
    tmp_path: Path, report_store, monkeypatch: pytest.MonkeyPatch
) -> None:
    from tests.activities.heartbeat_support import WatchedHeartbeat, WatchingStore
    from thoth_control_plane.activities import content_assembly
    from thoth_control_plane.infrastructure.media_store import LocalMediaStore

    heartbeat = WatchedHeartbeat()
    monkeypatch.setattr(content_assembly, "_heartbeat", heartbeat)
    store_root = tmp_path / "store"
    store_root.mkdir()
    store = WatchingStore(store_root, heartbeat)
    persist(report_store)
    video = str(report(workflow_id="wf_a").media[0].location)
    (tmp_path / "main.mp4").write_bytes(b"main-video")
    LocalMediaStore(store_root).put_file(video, tmp_path / "main.mp4")

    asyncio.run(
        _run(
            ContentAssemblyActivityInput(workflow_id="wf_a"),
            tmp_path / "unused-root",
            FakeAssembler(),
            report_store,
            media=store,
        )
    )
    assert store.calls == [("fetch", True)]
