"""The step recorder and its catalogue (run-progress spec 2026-10-25, G2, D2 and D3)."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest

from thoth_control_plane import progress
from thoth_control_plane.progress import StepRecord, StepScope

SCOPE = StepScope(workflow_id="wf_1", stage="source", attempt=1)
FOOTAGE = StepScope(workflow_id="wf_1", stage="footage", attempt=1)


class Sink:
    def __init__(self, fail: bool = False) -> None:
        self.records: list[tuple[StepScope, StepRecord]] = []
        self.fail = fail

    def append(self, scope: StepScope, record: StepRecord) -> None:
        if self.fail:
            raise RuntimeError("sink down")
        self.records.append((scope, record))


@pytest.fixture(autouse=True)
def no_sink():
    progress.install(None)
    yield
    progress.install(None)


@pytest.fixture
def sink() -> Sink:
    installed = Sink()
    progress.install(installed)
    return installed


@pytest.fixture
def clock(monkeypatch: pytest.MonkeyPatch) -> list[float]:
    """A patchable monotonic clock: tests advance it by appending seconds."""
    ticks = [0.0]
    monkeypatch.setattr(progress, "_monotonic", lambda: ticks[-1])
    return ticks


def recorded(sink: Sink, code: str) -> list[StepRecord]:
    return [record for _, record in sink.records if record.code == code]


async def test_the_kind_follows_the_catalogue_and_arguments(sink: Sink) -> None:
    with progress.scoped(SCOPE):
        await progress.step("source.read_link")
        await progress.step("source.download_media", n=2, total=10)
        await progress.step("source.page_gap", wait_until=datetime.now(UTC) + timedelta(seconds=30))
        await progress.step("source.login_wall")
        await progress.step("source.gate_covered", n=1, total=2)
    kinds = {record.code: record.kind for _, record in sink.records}
    assert kinds == {
        "source.read_link": "info",
        "source.download_media": "progress",
        "source.page_gap": "wait",
        "source.login_wall": "warning",
        "source.gate_covered": "warning",
    }


async def test_the_catalogue_holds_exactly_the_spec_codes() -> None:
    assert set(progress.CATALOGUE) == {
        "source.read_link",
        "source.fetch_post",
        "source.download_media",
        "source.capture_post_card",
        "source.capture_comment_cards",
        "source.gate_covered",
        "source.page_gap",
        "source.capture_embed_cards",
        "source.capture_profile",
        "source.login_wall",
        "source.save_report",
        "attribution.read_text",
        "attribution.ask_vision",
        "attribution.search_candidates",
        "attribution.compare_frames",
        "attribution.verdict",
        "footage.plan_queries",
        "footage.search_platforms",
        "footage.screen_clips",
        "footage.creator_listing",
        "footage.keep_clips",
        "assembly.read_subtitles",
        "assembly.judge_comments",
        "assembly.find_figures",
        "assembly.save_content_set",
    }
    assert progress.CATALOGUE["source.page_gap"] == "wait"
    assert progress.CATALOGUE["source.gate_covered"] == "warning"
    assert progress.CATALOGUE["source.login_wall"] == "warning"


async def test_an_unknown_code_is_dropped(sink: Sink) -> None:
    with progress.scoped(SCOPE):
        await progress.step("source.teleport")
        await progress.step("download_media")  # not stage-qualified
    assert sink.records == []


async def test_a_code_outside_the_scope_stage_is_dropped(sink: Sink) -> None:
    with progress.scoped(FOOTAGE):
        await progress.step("source.read_link")
    assert sink.records == []


async def test_whitelisted_params_survive_and_anything_else_drops_them_all(sink: Sink) -> None:
    with progress.scoped(SCOPE):
        await progress.step("source.fetch_post")
        await progress.step("source.fetch_post", params={"count": 3})
        await progress.step("source.fetch_post", params={"platform": "tiktok"})
        await progress.step("source.fetch_post", params={"platform": "https://x.test/video"})
        await progress.step("source.fetch_post", params={"url": "https://x.test/video"})
        await progress.step("source.fetch_post", params={"verdict": "Not-Original!"})
    params = [record.params for _, record in sink.records]
    assert params[0] is None
    assert params[1] == {"count": 3}
    assert params[2] == {"platform": "tiktok"}
    assert params[3:] == [None, None, None]  # the step itself is still recorded


async def test_progress_updates_coalesce_but_completions_never_drop(sink: Sink, clock) -> None:
    with progress.scoped(SCOPE):
        await progress.step("source.download_media", n=1, total=3)  # t=0.0, written
        clock.append(0.5)
        await progress.step("source.download_media", n=2, total=3)  # coalesced
        clock.append(0.6)
        await progress.step("source.download_media", n=3, total=3)  # n == total: written
        clock.append(0.7)
        await progress.step("source.fetch_post")  # another code: written, resets the pairing
        clock.append(0.8)
        await progress.step("source.download_media", n=4, total=9)  # last write was another code
    assert [record.n for record in recorded(sink, "source.download_media")] == [1, 3, 4]
    assert len(recorded(sink, "source.fetch_post")) == 1


async def test_a_written_step_is_coalesced_again_within_a_second(sink: Sink, clock) -> None:
    with progress.scoped(SCOPE):
        await progress.step("source.capture_embed_cards", n=1, total=9)
        clock.append(0.99)
        await progress.step("source.capture_embed_cards", n=2, total=9)  # dropped
        clock.append(1.0)
        await progress.step("source.capture_embed_cards", n=3, total=9)  # written: a second passed
    assert [record.n for _, record in sink.records] == [1, 3]


async def test_without_a_sink_or_a_scope_nothing_is_recorded(sink: Sink) -> None:
    with progress.scoped(SCOPE):  # no sink installed for this scope
        was = Sink()
        progress.install(was)
        progress.install(None)
        await progress.step("source.read_link")
    progress.install(sink)
    await progress.step("source.read_link")  # a sink, but no scope
    assert sink.records == []


async def test_a_sink_error_never_fails_the_work(sink: Sink, clock) -> None:
    broken = Sink(fail=True)
    progress.install(broken)
    with progress.scoped(SCOPE):
        await progress.step("source.read_link")  # warns, returns normally
    progress.install(sink)
    with progress.scoped(SCOPE):
        await progress.step("source.read_link")  # the failed write left no coalesce state
    assert [record.code for _, record in sink.records] == ["source.read_link"]


async def test_two_scopes_do_not_share_coalescing_state(sink: Sink, clock) -> None:
    other = StepScope(workflow_id="wf_2", stage="source", attempt=1)
    with progress.scoped(SCOPE):
        await progress.step("source.download_media", n=1, total=5)
    with progress.scoped(other):
        clock.append(0.1)
        await progress.step("source.download_media", n=1, total=5)  # fresh scope: written
    assert [(scope.workflow_id, record.n) for scope, record in sink.records] == [
        ("wf_1", 1),
        ("wf_2", 1),
    ]
    # The coalescing state never leaks into equality.
    assert StepScope(workflow_id="wf_1", stage="source", attempt=1) == SCOPE


async def test_the_recorder_stamps_the_time_and_carries_the_scope(sink: Sink) -> None:
    before = datetime.now(UTC)
    with progress.scoped(SCOPE):
        await progress.step("source.read_link", n=None, total=None)
    (scope, record) = sink.records[0]
    assert scope is not None and scope.workflow_id == "wf_1"
    assert record.at.tzinfo is not None and record.at >= before
