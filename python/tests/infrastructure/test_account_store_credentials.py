"""Sessions, trusted browsers, email challenges, tokens and auth events (spec 3.1)."""

from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy import create_engine, select
from sqlalchemy.pool import StaticPool

from thoth_control_plane.auth.models import BOOTSTRAP_WORKSPACE_ID
from thoth_control_plane.infrastructure import account_models  # noqa: F401
from thoth_control_plane.infrastructure.account_models import AuthEventRow, WorkspaceRow
from thoth_control_plane.infrastructure.account_store import AccountStore, TokenRecord
from thoth_control_plane.infrastructure.source_account_models import Base

T0 = datetime(2026, 10, 19, tzinfo=UTC)


class Clock:
    def __init__(self) -> None:
        self.now = T0

    def __call__(self) -> datetime:
        return self.now


@pytest.fixture
def clock() -> Clock:
    return Clock()


@pytest.fixture
def store(clock) -> AccountStore:
    engine = create_engine(
        "sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool
    )
    Base.metadata.create_all(engine)
    with engine.begin() as connection:
        connection.execute(
            WorkspaceRow.__table__.insert().values(
                workspace_id=BOOTSTRAP_WORKSPACE_ID, name="Thoth", created_at=T0
            )
        )
    return AccountStore(engine, clock=clock)


def test_a_session_is_live_until_it_expires_or_is_revoked(store, clock) -> None:
    user = store.ensure_user("a@acme.test", "A")
    made = store.create_session(user.user_id, user.workspace_id, "h1", T0 + timedelta(hours=12))
    assert store.live_session("h1") == made
    store.extend_session(made.session_id, T0 + timedelta(hours=20), T0 + timedelta(hours=8))
    clock.now = T0 + timedelta(hours=13)
    assert store.live_session("h1").expires_at == T0 + timedelta(hours=20)
    store.revoke_session("h1")
    assert store.live_session("h1") is None
    store.create_session(user.user_id, user.workspace_id, "h2", T0 + timedelta(hours=1))
    assert store.live_session("h2") is None  # already past its expiry at 13 h


def test_a_trusted_browser_belongs_to_one_user_and_can_be_forgotten(store, clock) -> None:
    alice = store.ensure_user("a@acme.test", "A")
    bob = store.ensure_user("b@acme.test", "B")
    store.trust_device(alice.user_id, "d1", T0 + timedelta(days=30))
    assert store.is_trusted(alice.user_id, "d1")
    assert not store.is_trusted(bob.user_id, "d1")
    store.forget_device("d1")
    assert not store.is_trusted(alice.user_id, "d1")


def test_a_challenge_counts_attempts_and_is_used_once(store, clock) -> None:
    user = store.ensure_user("a@acme.test", "A")
    store.create_challenge("chl_1", user.user_id, "c1", "hmac", T0 + timedelta(minutes=10))
    assert store.live_challenge("c1").attempts == 0
    assert store.count_attempt("chl_1") == 1
    assert store.count_attempt("chl_1") == 2
    assert store.consume_challenge("chl_1")
    assert not store.consume_challenge("chl_1")  # only one caller ever wins
    assert store.live_challenge("c1") is None
    assert store.challenge_times(user.user_id, T0 - timedelta(days=1)) == [T0]


def test_tokens_are_listed_newest_first_counted_revoked_and_touched(store, clock) -> None:
    user = store.ensure_user("a@acme.test", "A")

    def record(token_id: str, created: datetime) -> TokenRecord:
        return TokenRecord(
            token_id,
            "user",
            user.user_id,
            user.workspace_id,
            token_id,
            "thoth_pat_ab",
            "write",
            created,
            created + timedelta(days=90),
            None,
        )

    store.create_token(record("tok_old", T0), "t1")
    store.create_token(record("tok_new", T0 + timedelta(minutes=1)), "t2")
    assert [t.token_id for t in store.list_tokens("user", user.user_id)] == ["tok_new", "tok_old"]
    assert store.active_token_count("user", user.user_id) == 2
    assert store.live_token("t1").token_id == "tok_old"
    store.touch_token("tok_old", T0 + timedelta(minutes=5))
    assert store.live_token("t1").last_used_at == T0 + timedelta(minutes=5)
    assert store.revoke_token("tok_old", "user", user.user_id)
    assert not store.revoke_token("tok_old", "user", "usr_other")
    assert store.live_token("t1") is None
    assert store.active_token_count("user", user.user_id) == 1
    clock.now = T0 + timedelta(days=91)
    assert store.live_token("t2") is None


def test_events_hold_codes_not_secrets(store) -> None:
    store.record_event("sign_in", "refused", detail_code="not_allowed")
    with store._sessions() as session:
        row = session.scalars(select(AuthEventRow)).one()
    assert (row.kind, row.outcome, row.detail_code) == ("sign_in", "refused", "not_allowed")
