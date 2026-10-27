"""Assembly step emissions over the service and activity fakes (phase 3, D3)."""

from __future__ import annotations

from pathlib import Path

import pytest

from tests.activities.test_content_assembly import FakeAssembler, persist, run
from tests.assembly.support import comment, report
from tests.assembly.test_comment_judge import Judge
from tests.assembly.test_service import Figures, build
from thoth_control_plane import progress
from thoth_control_plane.assembly.figures import FigureAnswer
from thoth_control_plane.progress import StepRecord, StepScope

ASSEMBLY_SCOPE = StepScope(workflow_id="wf_a", stage="assembly", attempt=1)


class StepSink:
    def __init__(self) -> None:
        self.records: list[StepRecord] = []

    def append(self, scope: StepScope, record: StepRecord) -> None:
        self.records.append(record)


@pytest.fixture
def sink() -> StepSink:
    installed = StepSink()
    progress.install(installed)
    return installed


def sequence(sink: StepSink) -> list[tuple[str, int | None, int | None, dict | None]]:
    return [(r.code, r.n, r.total, r.params) for r in sink.records]


def test_a_build_reads_subtitles_finds_figures_then_judges_comments(
    sink: StepSink, tmp_path: Path
) -> None:
    figures = Figures(
        FigureAnswer.model_validate({"figures": [{"name": "Pramono Anung", "type": "person"}]})
    )
    main = report(
        comments=[comment("a", "ini video aslinya ternyata", 9), comment("b", "promo", 1)]
    )

    with progress.scoped(ASSEMBLY_SCOPE):
        content = build(
            tmp_path,
            main,
            verdict="original",
            figures=figures,
            headline="BANJIR LAGI",
            comments=Judge([0.9, 0.1]),
        )

    assert content.figures_status == "ok"
    steps = sequence(sink)
    # The subtitles read and the figures task run concurrently; their writes may land in
    # either order, but the comment judge always follows both.
    assert sorted(code for code, *_ in steps[:-1]) == [
        "assembly.find_figures",
        "assembly.read_subtitles",
    ]
    assert steps[-1] == ("assembly.judge_comments", None, len(main.comments), {"count": 1})


def test_the_activity_records_the_stored_content_set(
    sink: StepSink, tmp_path: Path, report_store
) -> None:
    persist(report_store)

    with progress.scoped(ASSEMBLY_SCOPE):
        result = run(tmp_path, report_store, FakeAssembler())

    assert result.content_set is not None
    assert sequence(sink) == [("assembly.save_content_set", None, None, None)]
