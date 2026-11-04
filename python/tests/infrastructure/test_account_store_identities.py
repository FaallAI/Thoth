"""Users, linked identities and the bootstrap workspace (spec 2026-10-19, section 2.4)."""

from datetime import UTC, datetime

import pytest
from sqlalchemy import text

from tests.sqlite_support import sqlite_engine
from thoth_control_plane.auth.models import BOOTSTRAP_WORKSPACE_ID, VerifiedIdentity
from thoth_control_plane.infrastructure import account_models  # noqa: F401
from thoth_control_plane.infrastructure.account_models import WorkspaceRow
from thoth_control_plane.infrastructure.account_store import AccountStore
from thoth_control_plane.infrastructure.source_account_models import Base

T0 = datetime(2026, 10, 19, tzinfo=UTC)


@pytest.fixture
def store() -> AccountStore:
    engine = sqlite_engine()
    Base.metadata.create_all(engine)
    with engine.begin() as connection:  # migration 0013 inserts this row on Postgres
        connection.execute(
            WorkspaceRow.__table__.insert().values(
                workspace_id=BOOTSTRAP_WORKSPACE_ID, name="Thoth", created_at=T0
            )
        )
    return AccountStore(engine, clock=lambda: T0)


def google(subject: str, email: str) -> VerifiedIdentity:
    return VerifiedIdentity("google", subject, email, "Alice")


def test_a_sign_in_never_claims_the_bootstrap_workspace(store) -> None:
    # Owning the bootstrap makes a platform admin, so a stranger who signs in first on a fresh
    # install must not get it (audit A2): every sign-in gets a workspace of its own.
    first = store.upsert_identity(google("g1", "alice@acme.test"))
    assert first.workspace_id != BOOTSTRAP_WORKSPACE_ID
    assert first.workspace_id.startswith("ws_") and first.role == "owner"


def test_the_bootstrap_cli_claims_the_bootstrap_workspace_once(store) -> None:
    store.upsert_identity(google("g1", "stranger@acme.test"))
    operator = store.ensure_user("operator@acme.test", "Operator")
    assert (operator.workspace_id, operator.role) == (BOOTSTRAP_WORKSPACE_ID, "owner")
    later = store.ensure_user("dev@acme.test", "Dev")
    assert later.workspace_id != BOOTSTRAP_WORKSPACE_ID


def test_one_email_across_google_and_github_is_one_user_with_one_workspace(store) -> None:
    by_google = store.upsert_identity(google("g1", "alice@acme.test"))
    store.upsert_identity(google("g9", "someone@acme.test"))  # the bootstrap is taken now
    by_github = store.upsert_identity(VerifiedIdentity("github", "42", "alice@acme.test", "alice"))
    assert by_github.user_id == by_google.user_id
    assert by_github.workspace_id == by_google.workspace_id
    again = store.upsert_identity(google("g1", "alice@acme.test"))
    assert again.user_id == by_google.user_id


def test_ensure_user_is_idempotent_and_account_reads_back(store) -> None:
    made = store.ensure_user("dev@acme.test", "Dev")
    assert store.ensure_user("dev@acme.test", "Dev").user_id == made.user_id
    assert store.account(made.user_id) == made
    assert store.account("usr_missing") is None


def test_a_disabled_user_is_reported_disabled(store) -> None:
    user = store.ensure_user("gone@acme.test", "Gone")
    with store._engine.begin() as connection:
        connection.execute(
            text("UPDATE users SET disabled_at = :at WHERE user_id = :id"),
            {"at": T0, "id": user.user_id},
        )
    assert store.account(user.user_id).disabled
