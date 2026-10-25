"""Attribution step emissions over the replay harness (phase 3, D3).

Two representative verdicts — an uncredited original and a credited replacement — run the
real `identify` inside `progress.scoped` with a fake sink and assert the ordered sequence.
"""

from __future__ import annotations

import threading

import pytest

from tests.attribution.replay import parse_report, replay_ports
from tests.attribution.test_service import VIDEO, _case, _identify, _report
from thoth_control_plane import progress
from thoth_control_plane.attribution.service import SourceAttributor
from thoth_control_plane.progress import StepRecord, StepScope

ATTRIBUTION_SCOPE = StepScope(workflow_id="wf_steps", stage="attribution", attempt=1)


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


@pytest.mark.asyncio
async def test_the_verdict_write_leaves_the_event_loop_thread(sink: StepSink) -> None:
    threads: dict[str, int] = {}
    plain_append = sink.append

    def recording_append(scope: StepScope, record: StepRecord) -> None:
        threads[record.code] = threading.get_ident()
        plain_append(scope, record)

    sink.append = recording_append
    with progress.scoped(ATTRIBUTION_SCOPE):
        await _identify(_case())

    # The verdict write is a database insert; on the activity's loop thread it would
    # block heartbeats and every other activity, so it must run on a worker thread.
    assert threads["attribution.verdict"] != threading.get_ident()


@pytest.mark.asyncio
async def test_an_uncredited_original_reads_asks_and_verdicts(sink: StepSink) -> None:
    quiet = _case()
    quiet["frames"]["repost"][0]["boxes"] = []
    quiet["decisions"] = {**quiet["decisions"], "handle": None, "handle_probability": 0.0}
    quiet["decisions"]["is_repost"] = 0.1

    with progress.scoped(ATTRIBUTION_SCOPE):
        outcome, _ = await _identify(quiet)

    assert outcome.attribution.verdict == "original"
    assert sequence(sink) == [
        ("attribution.read_text", None, None, None),
        ("attribution.ask_vision", None, None, None),
        ("attribution.ask_vision", None, None, None),
        ("attribution.verdict", None, None, {"verdict": "original"}),
    ]


@pytest.mark.asyncio
async def test_a_credited_replacement_searches_and_compares_before_the_verdict(
    sink: StepSink,
) -> None:
    with progress.scoped(ATTRIBUTION_SCOPE):
        outcome, _ = await _identify(_case())

    assert outcome.attribution.verdict == "replaced"
    assert sequence(sink) == [
        ("attribution.read_text", None, None, None),
        ("attribution.ask_vision", None, None, None),
        ("attribution.ask_vision", None, None, None),
        ("attribution.search_candidates", None, None, {"count": 3}),
        # Both finalists fit the default concurrency, so one batch reports one step.
        ("attribution.compare_frames", 2, 2, None),
        ("attribution.verdict", None, None, {"verdict": "replaced"}),
    ]


@pytest.mark.asyncio
async def test_a_batch_reports_its_compared_frames_after_its_checks(sink: StepSink) -> None:
    case = _case()
    ports = replay_ports(case)
    acquired_when_recorded: list[int] = []
    plain_append = sink.append

    def recording_append(scope: StepScope, record: StepRecord) -> None:
        if record.code == "attribution.compare_frames":
            acquired_when_recorded.append(len(ports.acquirer.acquired))
        plain_append(scope, record)

    sink.append = recording_append
    with progress.scoped(ATTRIBUTION_SCOPE):
        outcome = await SourceAttributor(ports).identify("wf_ref", parse_report(_report()), VIDEO)

    assert outcome.attribution.verdict == "replaced"
    # One step per batch — both finalists fit the default concurrency — and it lands
    # once the batch is compared, not before its acquisitions start.
    comparisons = [record for record in sink.records if record.code == "attribution.compare_frames"]
    assert [(record.n, record.total) for record in comparisons] == [(2, 2)]
    assert acquired_when_recorded == [2]
