"""The source-account store on a disposable Postgres migrated by the shipped revisions."""

from __future__ import annotations

import os
from datetime import UTC, datetime
from pathlib import Path

import psycopg
import pytest
from cryptography.fernet import Fernet

from thoth_control_plane.acquisition.accounts.cookies import parse_cookies
from thoth_control_plane.acquisition.accounts.proxies import parse_proxy_list
from thoth_control_plane.acquisition.accounts.vault import Vault
from thoth_control_plane.infrastructure.source_account_store import (
    SourceAccountError,
    SourceAccountStore,
)
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
