"""The activity reads persisted reports, writes the content set atomically, and redacts."""

from __future__ import annotations

import asyncio
import json
from hashlib import sha256
from pathlib import Path

import pytest

from tests.assembly.support import comment, report
from thoth_control_plane.activities.content_assembly import (
    ContentAssemblyActivityInput,
    _run,
)
from thoth_control_plane.assembly.models import ContentSet
from thoth_control_plane.assembly.ports import AssemblyError
from thoth_control_plane.assembly.service import AssemblyInputs


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


def persist(root: Path, workflow_id: str = "wf_a", **kwargs) -> None:
    folder = root / "reports" / workflow_id
    folder.mkdir(parents=True, exist_ok=True)
    (folder / "source-report.json").write_text(
        report(workflow_id=workflow_id, **kwargs).model_dump_json(), encoding="utf-8"
    )


def run(root: Path, assembler: FakeAssembler, **kwargs):
    return asyncio.run(
        _run(ContentAssemblyActivityInput(workflow_id="wf_a", **kwargs), root, assembler)
    )


def test_writes_the_content_set_with_a_matching_checksum(tmp_path: Path) -> None:
    persist(tmp_path)

    result = run(tmp_path, FakeAssembler())

    written = (tmp_path / "reports" / "wf_a" / "content-set.json").read_bytes()
    assert result.content_set is not None and result.failure is None
    assert result.content_set.location == "reports/wf_a/content-set.json"
    assert result.content_set.checksum == "sha256:" + sha256(written).hexdigest()
    assert result.content_set.kind == "content_set"
    assert not list((tmp_path / "reports" / "wf_a").glob("*.part"))
    payload = result.events[0].payload
    assert payload["stage"] == "assembly" and payload["status"] == "succeeded"
    assert payload["comment_count"] == 1 and payload["ocr_outcome"] == "none"


def test_a_second_run_replaces_the_content_set(tmp_path: Path) -> None:
    persist(tmp_path, comments=[comment("a", "satu", 1)])
    run(tmp_path, FakeAssembler())
    second = run(tmp_path, FakeAssembler())

    stored = ContentSet.model_validate_json(
        (tmp_path / "reports" / "wf_a" / "content-set.json").read_bytes()
    )
    assert len(stored.comments) == 1
    assert second.content_set is not None


def test_no_report_is_a_failure(tmp_path: Path) -> None:
    result = run(tmp_path, FakeAssembler())

    assert result.failure == "source_report_missing" and result.content_set is None
    assert result.events[0].payload["reason"] == "source_report_missing"


def test_replaced_reads_the_original_report_it_is_given(tmp_path: Path) -> None:
    persist(tmp_path)
    persist(tmp_path, workflow_id="wf_a-c1", owner="source")
    (tmp_path / "reports" / "wf_a" / "source-attribution.json").write_text(
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
        ),
        encoding="utf-8",
    )
    assembler = FakeAssembler()

    run(
        tmp_path,
        assembler,
        attribution="reports/wf_a/source-attribution.json",
        original_report="reports/wf_a-c1/source-report.json",
    )

    assert assembler.inputs[0].original is not None
    assert assembler.inputs[0].original.post.owner_handle == "source"


@pytest.mark.parametrize(
    "location", ["../etc/passwd", "/abs/source-report.json", "reports/x/other.json"]
)
def test_an_unsafe_original_location_is_ignored(tmp_path: Path, location: str) -> None:
    persist(tmp_path)
    assembler = FakeAssembler()

    run(tmp_path, assembler, original_report=location)

    assert assembler.inputs[0].original is None


def test_assembly_failures_keep_their_code_and_write_nothing(tmp_path: Path) -> None:
    persist(tmp_path)

    result = run(tmp_path, FakeAssembler(error="incomplete_frame_coverage"))

    assert result.failure == "incomplete_frame_coverage"
    assert not (tmp_path / "reports" / "wf_a" / "content-set.json").exists()


def test_results_carry_no_text(tmp_path: Path) -> None:
    persist(tmp_path)

    result = run(tmp_path, FakeAssembler())

    assert "rahasia" not in result.model_dump_json()


def test_a_stale_attribution_on_disk_is_not_read(tmp_path: Path) -> None:
    # Review 2026-10-12: a crashed first attempt can leave `replaced` on disk while the
    # workflow received `unresolved`; assembly must follow what the workflow received.
    persist(tmp_path)
    (tmp_path / "reports" / "wf_a" / "source-attribution.json").write_text(
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
        ),
        encoding="utf-8",
    )
    assembler = FakeAssembler()

    run(tmp_path, assembler)

    assert assembler.inputs[0].attribution is None


def test_a_retry_with_the_real_assembler_never_duplicates_comments(tmp_path: Path) -> None:
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
        tmp_path,
        media="none",
        post_card=True,
        comments=[comment("a", "satu", 3), comment("b", "dua", 2)],
    )
    real = ContentAssembler(AssemblyPorts(frames=Unused(), probe=Unused(), text=Unused()))

    first = run(tmp_path, real)
    second = run(tmp_path, real)

    stored = ContentSet.model_validate_json(
        (tmp_path / "reports" / "wf_a" / "content-set.json").read_bytes()
    )
    assert [c.text for c in stored.comments] == ["satu", "dua"]
    assert first.content_set == second.content_set
