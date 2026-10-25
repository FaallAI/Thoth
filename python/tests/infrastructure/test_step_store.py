"""The step store on a private SQLite database (editor migration 0019)."""

from datetime import UTC, datetime, timedelta

import pytest

from tests.sqlite_support import sqlite_engine
from thoth_control_plane.infrastructure import step_models  # noqa: F401  (registers the table)
from thoth_control_plane.infrastructure.source_account_models import Base
from thoth_control_plane.infrastructure.step_store import StepStore
from thoth_control_plane.progress import StepRecord, StepScope

NOW = datetime(2026, 10, 25, 12, 0, tzinfo=UTC)


@pytest.fixture
def store() -> StepStore:
    engine = sqlite_engine()
    Base.metadata.create_all(engine)
    return StepStore(engine)


def scope(stage: str = "source", workflow_id: str = "wf_1", attempt: int = 1) -> StepScope:
    return StepScope(workflow_id=workflow_id, stage=stage, attempt=attempt)


def record(
    code: str,
    *,
    kind: str = "info",
    n: int | None = None,
    total: int | None = None,
    params: dict | None = None,
    wait_until: datetime | None = None,
    at: datetime = NOW,
) -> StepRecord:
    return StepRecord(
        at=at, kind=kind, code=code, n=n, total=total, wait_until=wait_until, params=params
    )


def test_append_then_page_in_seq_order_with_after_and_limit(store: StepStore) -> None:
    for n in range(1, 6):
        store.append(scope(), record("source.download_media", kind="progress", n=n, total=5))

    page = store.page("wf_1", after=0, limit=200)
    assert [step.n for step in page] == [1, 2, 3, 4, 5]
    assert [step.seq for step in page] == sorted(step.seq for step in page)
    assert page[0].stage == "source" and page[0].attempt == 1

    from_second = store.page("wf_1", after=page[0].seq, limit=200)
    assert [step.n for step in from_second] == [2, 3, 4, 5]
    assert [step.seq for step in store.page("wf_1", after=0, limit=2)] == [
        page[0].seq,
        page[1].seq,
    ]
    assert store.page("wf_other", after=0, limit=200) == []


def test_current_steps_picks_the_highest_attempt_then_the_latest_seq(store: StepStore) -> None:
    store.append(scope(attempt=1), record("source.read_link"))
    store.append(scope(attempt=1), record("source.fetch_post"))
    store.append(scope(attempt=2), record("source.read_link"))
    store.append(scope(attempt=2), record("source.fetch_post"))
    # A timed-out attempt 1 can still be running and write after attempt 2 started.
    store.append(scope(attempt=1), record("source.save_report"))
    store.append(scope(stage="footage", attempt=1), record("footage.plan_queries"))

    current = store.current_steps("wf_1")
    assert set(current) == {"source", "footage"}
    assert current["source"].attempt == 2
    assert current["source"].code == "source.fetch_post"  # the latest of attempt 2
    assert current["footage"].code == "footage.plan_queries"
    assert store.current_steps("wf_none") == {}


def test_params_and_wait_until_round_trip(store: StepStore) -> None:
    wait_until = NOW + timedelta(seconds=30)
    store.append(
        scope(),
        record(
            "source.page_gap",
            kind="wait",
            wait_until=wait_until,
            params={"count": 3, "verdict": "original"},
        ),
    )

    (step,) = store.page("wf_1", after=0, limit=200)
    assert step.kind == "wait"
    assert step.wait_until == wait_until
    assert step.params == {"count": 3, "verdict": "original"}
