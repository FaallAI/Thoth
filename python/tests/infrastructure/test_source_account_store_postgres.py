"""The source-account store on a disposable Postgres migrated by the shipped revisions."""

from __future__ import annotations

import os
import threading
from datetime import UTC, datetime
from pathlib import Path

import psycopg
import pytest
from cryptography.fernet import Fernet

from thoth_control_plane import metering
from thoth_control_plane.acquisition.accounts.cookies import parse_cookies
from thoth_control_plane.acquisition.accounts.proxies import parse_proxy_list
from thoth_control_plane.acquisition.accounts.vault import Vault
from thoth_control_plane.infrastructure.source_account_store import (
    QuotaReached,
    SourceAccountError,
    SourceAccountStore,
)
from thoth_control_plane.metering import MeterScope
from thoth_control_plane.operations.editor_migrations import apply_editor_migrations

MIGRATIONS = Path(__file__).resolve().parents[2] / "migrations" / "editor"
DATABASE_URL = os.environ.get("THOTH_TEST_EDITOR_DATABASE_URL", "")
NOW = datetime(2026, 10, 7, 12, 0, tzinfo=UTC)

pytestmark = pytest.mark.skipif(
    not DATABASE_URL, reason="THOTH_TEST_EDITOR_DATABASE_URL points at a disposable Postgres"
)


def _cookies(value: str):
    line = "\t".join([".instagram.com", "TRUE", "/", "TRUE", "1893456000", "sessionid", value])
    return parse_cookies("instagram", line + "\n", now=NOW)


@pytest.fixture
def store() -> SourceAccountStore:
    with psycopg.connect(DATABASE_URL, autocommit=True) as connection:
        connection.execute("DROP SCHEMA public CASCADE")
        connection.execute("CREATE SCHEMA public")
    apply_editor_migrations(DATABASE_URL, MIGRATIONS)
    store = SourceAccountStore.connect(DATABASE_URL, Vault(Fernet.generate_key().decode()))
    store.set_policy("instagram", "always", 0)
    return store


def test_the_orm_round_trips_through_the_shipped_schema(store: SourceAccountStore) -> None:
    store.import_proxies(parse_proxy_list("http://u:p@1.2.3.4:8080"))
    (proxy,) = store.proxies()
    account = store.add_account("instagram", "main", _cookies("secret"), proxy.id)
    assert store.account(account.id) == account
    assert account.cookie_names == ("sessionid",)
    assert account.cookies_earliest_expiry == datetime(2030, 1, 1, tzinfo=UTC)
    lease = store.lease("instagram")
    # The lease identity survives the timestamptz round trip, so its own report applies.
    store.report(lease.account_id, "blocked", leased_until=lease.leased_until)
    assert store.account(account.id).cooldown_until is not None
    with pytest.raises(SourceAccountError):
        store.delete_proxy(proxy.id)


def test_a_row_locked_by_another_lease_is_skipped_not_waited_for(
    store: SourceAccountStore,
) -> None:
    first = store.add_account("instagram", "first", _cookies("a"))
    second = store.add_account("instagram", "second", _cookies("b"))
    with psycopg.connect(DATABASE_URL) as holder:
        holder.execute("SELECT id FROM source_accounts WHERE id = %s FOR UPDATE", (first.id,))
        lease = store.lease("instagram")
        assert lease is not None and lease.account_id == second.id
        assert store.lease("instagram") is None
    assert store.lease("instagram").account_id == first.id


def test_the_database_refuses_a_second_holder_of_one_proxy(store: SourceAccountStore) -> None:
    store.import_proxies(parse_proxy_list("http://1.2.3.4:8080"))
    (proxy,) = store.proxies()
    a = store.add_account("instagram", "a", _cookies("a"), proxy.id)
    b = store.add_account("instagram", "b", _cookies("b"))
    with psycopg.connect(DATABASE_URL) as connection, pytest.raises(psycopg.errors.UniqueViolation):
        connection.execute(
            "UPDATE source_accounts SET proxy_id = %s WHERE id = %s", (proxy.id, b.id)
        )
    assert store.account(a.id).proxy_id == proxy.id


def _workspaces(*ids: str) -> None:
    with psycopg.connect(DATABASE_URL) as connection:
        for workspace in ids:
            connection.execute(
                "INSERT INTO workspaces (workspace_id, name, created_at) VALUES (%s, %s, now())",
                (workspace, workspace),
            )


def _race(store: SourceAccountStore, scopes: list[MeterScope]) -> list[object]:
    barrier = threading.Barrier(len(scopes))
    results: list[object] = []

    def lease(scope: MeterScope) -> None:
        barrier.wait()
        with metering.scoped(scope):
            try:
                results.append(store.lease("instagram"))
            except QuotaReached as refused:
                results.append(refused.code)
            except BaseException as error:  # a thread's exception would otherwise vanish
                results.append(error)

    threads = [threading.Thread(target=lease, args=(scope,)) for scope in scopes]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join()
    return results


def test_one_unit_of_quota_left_gives_exactly_one_lease(store: SourceAccountStore) -> None:
    _workspaces("ws_a")
    store.set_policy("instagram", "always", 0, daily_budget=0)
    for label in ("a", "b"):
        store.add_account("instagram", label, _cookies(label))
    with psycopg.connect(DATABASE_URL) as connection:
        connection.execute(
            "INSERT INTO workspace_quotas (workspace_id, platform, daily_leases)"
            " VALUES ('ws_a', 'instagram', 1)"
        )
    results = _race(store, [MeterScope("ws_a"), MeterScope("ws_a")])
    assert sorted(type(r).__name__ for r in results) == ["AccountLease", "str"]
    assert "workspace_quota" in results


def test_two_workspaces_at_the_reserve_line_get_one_lease(store: SourceAccountStore) -> None:
    _workspaces("ws_a", "ws_b")
    # Three accounts with a budget of one: capacity 3, reserve 2, so one lease is left.
    store.set_policy("instagram", "always", 0, daily_budget=1)
    for label in ("a", "b", "c"):
        store.add_account("instagram", label, _cookies(label))
    results = _race(store, [MeterScope("ws_a"), MeterScope("ws_b")])
    assert sorted(type(r).__name__ for r in results) == ["AccountLease", "str"]
    assert "operator_reserve" in results
    assert store.lease("instagram") is not None  # the bootstrap still leases


def test_the_quota_lock_never_blocks_foreign_key_inserts(store: SourceAccountStore) -> None:
    from sqlalchemy import event

    _workspaces("ws_a")
    store.set_policy("instagram", "always", 0, daily_budget=0)
    store.add_account("instagram", "a", _cookies("a"))
    statements: list[str] = []
    engine = store._sessions.kw["bind"]
    event.listen(engine, "before_cursor_execute", lambda *a: statements.append(a[2]))
    with metering.scoped(MeterScope("ws_a")):
        assert store.lease("instagram") is not None
    locks = [s for s in statements if "FROM workspaces" in s and "FOR " in s]
    # FOR UPDATE would conflict with the FOR KEY SHARE every insert referencing ws_bootstrap takes.
    assert locks and all("FOR NO KEY UPDATE" in s for s in locks)
