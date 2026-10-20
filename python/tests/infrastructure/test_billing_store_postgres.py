"""The allowance lock and the lazy free row on a disposable PostgreSQL."""

from __future__ import annotations

import os
import threading
from pathlib import Path

import psycopg
import pytest

from thoth_control_plane.billing import PlanLimitReached
from thoth_control_plane.infrastructure.billing_store import BillingStore
from thoth_control_plane.operations.editor_migrations import apply_editor_migrations

MIGRATIONS = Path(__file__).resolve().parents[2] / "migrations" / "editor"
DATABASE_URL = os.environ.get("THOTH_TEST_EDITOR_DATABASE_URL", "")

pytestmark = pytest.mark.skipif(
    not DATABASE_URL, reason="THOTH_TEST_EDITOR_DATABASE_URL points at a disposable Postgres"
)


@pytest.fixture
def store() -> BillingStore:
    with psycopg.connect(DATABASE_URL, autocommit=True) as connection:
        connection.execute("DROP SCHEMA public CASCADE")
        connection.execute("CREATE SCHEMA public")
    apply_editor_migrations(DATABASE_URL, MIGRATIONS)
    with psycopg.connect(DATABASE_URL) as connection:
        for workspace in ("ws_a", "ws_b"):
            connection.execute(
                "INSERT INTO workspaces (workspace_id, name, created_at) VALUES (%s, %s, now())",
                (workspace, workspace),
            )
    return BillingStore.connect(DATABASE_URL)


def _race(calls) -> list[object]:
    barrier = threading.Barrier(len(calls))
    results: list[object] = []

    def run(call) -> None:
        barrier.wait()
        try:
            results.append(call())
        except PlanLimitReached as refused:
            results.append(refused.kind)
        except BaseException as error:  # a thread's exception would otherwise vanish
            results.append(error)

    threads = [threading.Thread(target=run, args=(call,)) for call in calls]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join()
    return results


def test_two_starts_at_the_last_unit_admit_exactly_one(store: BillingStore) -> None:
    store.consume("ws_a", "workflow", "r1")
    store.consume("ws_a", "workflow", "r2")
    results = _race(
        [
            lambda: store.consume("ws_a", "workflow", "x"),
            lambda: store.consume("ws_a", "workflow", "y"),
        ]
    )
    assert sorted(map(str, results)) == ["True", "workflow"]


def test_racing_first_starts_create_one_free_row(store: BillingStore) -> None:
    results = _race(
        [
            lambda: store.consume("ws_b", "video", "a"),
            lambda: store.consume("ws_b", "video", "b"),
        ]
    )
    assert sorted(map(str, results)) == ["True", "video"]  # free allows one video
    with psycopg.connect(DATABASE_URL) as connection:
        assert connection.execute(
            "SELECT count(*) FROM subscriptions WHERE workspace_id = 'ws_b'"
        ).fetchone() == (1,)
