"""Every mapped activity runs in its workflow's step scope (spec 2026-10-25, G2, D4)."""

from types import SimpleNamespace

import pytest

from thoth_control_plane import progress, worker
from thoth_control_plane.activities import progress_scope
from thoth_control_plane.config import Settings
from thoth_control_plane.progress import StepScope


class Next:
    def __init__(self, code: str | None = None) -> None:
        self.code = code
        self.scope: StepScope | None = None
        self.records: list[tuple[StepScope, object]] = []

    async def execute_activity(self, input):
        self.scope = progress.current_scope()
        if self.code is not None:
            await progress.step(self.code)
        return "done"


@pytest.fixture
def sink():
    class Sink:
        def __init__(self) -> None:
            self.records: list[tuple[StepScope, object]] = []

        def append(self, scope, record) -> None:
            self.records.append((scope, record))

    installed = Sink()
    progress.install(installed)
    return installed


@pytest.fixture
def info(monkeypatch: pytest.MonkeyPatch):
    def with_type(activity_type: str, *, attempt: int = 1, workflow_id: str = "wf_1"):
        monkeypatch.setattr(
            progress_scope.activity,
            "info",
            lambda: SimpleNamespace(
                activity_type=activity_type, attempt=attempt, workflow_id=workflow_id
            ),
        )

    return with_type


@pytest.mark.parametrize(
    ("activity_type", "stage"),
    [
        ("inspect_source_candidates", "source"),
        ("attribute_source", "attribution"),
        ("build_footage", "footage"),
        ("assemble_content", "assembly"),
    ],
)
async def test_each_mapped_activity_runs_in_its_stage_scope(info, activity_type: str, stage: str) -> None:
    info(activity_type, attempt=3)
    following = Next()
    interceptor = progress_scope.ProgressScopeInterceptor()
    assert await interceptor.intercept_activity(following).execute_activity(object()) == "done"
    assert following.scope == StepScope(workflow_id="wf_1", stage=stage, attempt=3)
    assert progress.current_scope() is None  # the scope ends with the activity


@pytest.mark.parametrize(
    "activity_type", ["inspect_legacy_scout", "record_workflow_completed", "run_prompt_proposal"]
)
async def test_an_unmapped_activity_runs_without_a_scope(info, activity_type: str) -> None:
    info(activity_type, attempt=2)
    following = Next()
    await progress_scope.ProgressScopeInterceptor().intercept_activity(following).execute_activity(
        object()
    )
    assert following.scope is None


async def test_a_step_inside_the_activity_reaches_the_sink_with_that_scope(info, sink) -> None:
    info("inspect_source_candidates", attempt=1, workflow_id="wf_steps")
    following = Next("source.read_link")
    await progress_scope.ProgressScopeInterceptor().intercept_activity(
        following
    ).execute_activity(object())
    ((scope, record),) = sink.records
    assert scope.workflow_id == "wf_steps" and scope.stage == "source"
    assert record.code == "source.read_link" and record.kind == "info"


def test_the_source_worker_carries_both_scope_interceptors(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    recorded: dict = {}

    def fake_worker(client, **kwargs):
        recorded.update(kwargs)
        return object()

    monkeypatch.setattr(worker, "Worker", fake_worker)
    for name in (
        "build_source_investigation_activity",
        "build_source_attribution_activity",
        "build_content_assembly_activity",
        "build_footage_activity",
    ):
        monkeypatch.setattr(worker, name, lambda *args, **kwargs: object())
    settings = Settings(THOTH_CONTROL_PLANE_API_KEY="k")
    worker.build_source_investigation_worker(
        object(), settings, reports=object(), media=object()
    )
    names = [type(interceptor).__name__ for interceptor in recorded["interceptors"]]
    assert names == ["MeterScopeInterceptor", "ProgressScopeInterceptor"]
