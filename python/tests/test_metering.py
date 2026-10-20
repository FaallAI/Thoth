"""The meter scope, the sink and the cost estimate (spec 2026-10-20 metering, section 2)."""

import asyncio
from types import SimpleNamespace

from thoth_control_plane import metering
from thoth_control_plane.metering import MeterScope, UsageRecord


class Sink:
    def __init__(self, *, workflows=None, projects=None, fail=False) -> None:
        self.events: list[UsageRecord] = []
        self.workflows = workflows or {}
        self.projects = projects or {}
        self.fail = fail

    def record(self, event: UsageRecord) -> None:
        if self.fail:
            raise RuntimeError("database down")
        self.events.append(event)

    def workspace_of_workflow(self, workflow_id: str) -> str | None:
        return self.workflows.get(workflow_id)

    def workspace_of_project(self, project_id: str) -> str | None:
        return self.projects.get(project_id)


def test_a_record_carries_the_scope() -> None:
    sink = Sink()
    metering.install(sink)
    with metering.scoped(MeterScope("ws_a", workflow_id="wf_1", project_id="p1")):
        metering.record_sync("provider_call", "m", 1, "call")
    assert sink.events == [UsageRecord("ws_a", "provider_call", "m", 1.0, "call", "wf_1", "p1")]


def test_outside_any_scope_a_provider_call_goes_to_the_bootstrap() -> None:
    sink = Sink()
    metering.install(sink)
    metering.record_sync("provider_call", "m", 1, "call")
    assert sink.events[0].workspace_id == "ws_bootstrap"


def test_in_scope_only_records_nothing_outside_a_scope() -> None:
    sink = Sink()
    metering.install(sink)
    metering.record_sync("media_stored", "renders", 10, "byte", in_scope_only=True)
    assert sink.events == []


def test_a_failing_sink_never_fails_the_work() -> None:
    metering.install(Sink(fail=True))
    metering.record_sync("provider_call", "m", 1, "call")  # no exception


def test_no_sink_records_nothing() -> None:
    metering.install(None)
    metering.record_sync("provider_call", "m", 1, "call")


def test_a_model_run_records_the_call_and_its_tokens() -> None:
    sink = Sink()
    metering.install(sink)
    run = SimpleNamespace(metrics=SimpleNamespace(input_tokens=120, output_tokens=0))

    async def main() -> None:
        with metering.scoped(MeterScope("ws_a")):
            await metering.record_model_run("qwen", run)

    asyncio.run(main())
    assert [(e.quantity, e.unit) for e in sink.events] == [(1.0, "call"), (120.0, "token_in")]


def test_the_scope_reaches_a_worker_thread() -> None:
    sink = Sink()
    metering.install(sink)

    async def main() -> None:
        with metering.scoped(MeterScope("ws_t")):
            await metering.record("provider_call", "m", 1, "call")

    asyncio.run(main())
    assert sink.events[0].workspace_id == "ws_t"


def test_a_workflow_scope_prefers_the_memo_then_the_run_row_then_the_bootstrap() -> None:
    metering.install(Sink(workflows={"wf_row": "ws_row"}))
    assert metering.workflow_scope("wf_x", "ws_memo") == MeterScope("ws_memo", workflow_id="wf_x")
    assert metering.workflow_scope("wf_row").workspace_id == "ws_row"
    assert metering.workflow_scope("wf_none").workspace_id == "ws_bootstrap"


def test_a_project_scope_names_the_projects_workspace() -> None:
    metering.install(Sink(projects={"p1": "ws_p"}))
    assert metering.project_scope("p1") == MeterScope("ws_p", project_id="p1")


def test_the_estimate_prices_known_items_and_reports_the_rest_unpriced() -> None:
    totals = [
        SimpleNamespace(kind="account_lease", key="instagram", unit="session", quantity=4.0),
        SimpleNamespace(kind="provider_call", key="qwen", unit="token_in", quantity=1000.0),
        SimpleNamespace(kind="video_rendered", key="p", unit="second", quantity=30.0),
    ]
    prices = {
        ("account_lease", "instagram", "session"): 0.05,
        ("provider_call", "*", "token_in"): 0.000001,
    }
    result = metering.estimate(totals, prices)
    assert round(result.usd, 6) == 0.201
    assert [(line.key, line.usd) for line in result.unpriced] == [("p", None)]
