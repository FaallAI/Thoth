"""The usage store on in-memory SQLite."""

from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session
from sqlalchemy.pool import StaticPool

from thoth_control_plane.infrastructure import usage_models  # noqa: F401
from thoth_control_plane.infrastructure.run_models import ProjectRow, WorkflowRunRow
from thoth_control_plane.infrastructure.source_account_models import Base
from thoth_control_plane.infrastructure.usage_store import UsageStore
from thoth_control_plane.metering import UsageRecord

NOW = datetime(2026, 10, 20, 12, 0, tzinfo=UTC)
DAY = (NOW - timedelta(days=1), NOW + timedelta(days=1))


@pytest.fixture
def engine():
    engine = create_engine(
        "sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool
    )
    Base.metadata.create_all(engine)
    return engine


@pytest.fixture
def store(engine) -> UsageStore:
    return UsageStore(engine, lambda: NOW)


def _run(workflow_id: str, actor_id: str) -> WorkflowRunRow:
    return WorkflowRunRow(
        workflow_id=workflow_id,
        project_id=None,
        actor_type="user",
        actor_id=actor_id,
        display_url="https://x.test",
        platform="x",
        status="running",
        history_expired=False,
        summary=None,
        created_at=NOW,
        updated_at=NOW,
    )


def test_totals_sum_and_count_per_kind_key_and_unit(store: UsageStore) -> None:
    for seconds in (10, 20):
        store.record(UsageRecord("ws_a", "video_rendered", "p", seconds, "second"))
    store.record(UsageRecord("ws_b", "video_rendered", "p", 99, "second"))
    (total,) = store.totals("ws_a", *DAY)
    assert (total.kind, total.key, total.unit, total.quantity, total.events) == (
        "video_rendered",
        "p",
        "second",
        30.0,
        2,
    )
    assert set(store.totals_by_workspace(*DAY)) == {"ws_a", "ws_b"}


def test_leases_today_count_per_platform(store: UsageStore) -> None:
    store.record(UsageRecord("ws_a", "account_lease", "instagram", 1, "session"))
    store.record(UsageRecord("ws_a", "account_lease", "instagram", 1, "session"))
    assert store.leases_today("ws_a") == {"instagram": 2}


def test_quotas_default_per_platform_and_take_an_override(store: UsageStore) -> None:
    assert store.quotas("ws_a")["instagram"] == 3
    store.set_quota("ws_a", "instagram", 7)
    assert store.quotas("ws_a")["instagram"] == 7
    store.clear_quota("ws_a", "instagram")
    assert store.quotas("ws_a")["instagram"] == 3
    with pytest.raises(ValueError):
        store.set_quota("ws_a", "myspace", 1)
    with pytest.raises(ValueError):
        store.set_quota("ws_a", "instagram", -1)


def test_prices_round_trip_and_refuse_unknown_kinds(store: UsageStore) -> None:
    store.set_price("provider_call", "*", "token_in", 0.000001)
    assert [(p.kind, p.key, p.unit, p.usd_per_unit) for p in store.prices()] == [
        ("provider_call", "*", "token_in", 0.000001)
    ]
    with pytest.raises(ValueError):
        store.set_price("teleport", "*", "call", 1)


def test_a_workflow_and_a_project_map_to_their_workspace(store: UsageStore, engine) -> None:
    with Session(engine) as session, session.begin():
        session.add(
            ProjectRow(
                project_id="p1", name="P", workspace_id="ws_p", created_at=NOW, updated_at=NOW
            )
        )
        session.add(_run("wf_1", "ws_w"))
        session.add(_run("wf_2", "owner"))
    assert store.workspace_of_project("p1") == "ws_p"
    assert store.workspace_of_workflow("wf_1") == "ws_w"
    assert store.workspace_of_workflow("wf_2") == "ws_bootstrap"
    assert store.workspace_of_workflow("wf_none") is None


def test_totals_tell_workflow_usage_apart(store: UsageStore) -> None:
    store.record(UsageRecord("ws_a", "account_lease", "x", 1, "session", "wf_1"))
    store.record(UsageRecord("ws_a", "account_lease", "x", 1, "session"))
    rows = sorted((t.in_workflow, t.events) for t in store.totals("ws_a", *DAY))
    assert rows == [(False, 1), (True, 1)]
