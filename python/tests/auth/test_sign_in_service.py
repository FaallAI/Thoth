"""Sign-in rules end to end against SQLite (spec sections 2 and 3)."""

import re
from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy import create_engine, text
from sqlalchemy.pool import StaticPool

from thoth_control_plane.auth.mailer import MailNotSent
from thoth_control_plane.auth.models import (
    BOOTSTRAP_WORKSPACE_ID,
    SCOPE_SETS,
    CreateToken,
    Principal,
    SignInRefused,
    VerifiedIdentity,
    is_platform_admin,
)
from thoth_control_plane.auth.service import (
    CodeLimited,
    CodeNotSent,
    CodeRejected,
    CodeSent,
    ScopeTooBroad,
    SignedIn,
    SignInService,
    TokenLimitReached,
    UserRequired,
)
from thoth_control_plane.infrastructure import account_models  # noqa: F401
from thoth_control_plane.infrastructure.account_models import WorkspaceRow
from thoth_control_plane.infrastructure.account_store import AccountStore
from thoth_control_plane.infrastructure.source_account_models import Base

T0 = datetime(2026, 10, 19, tzinfo=UTC)
ALICE = VerifiedIdentity("google", "g1", "alice@acme.test", "Alice")


class Clock:
    def __init__(self) -> None:
        self.now = T0

    def __call__(self) -> datetime:
        return self.now


class FakeMailer:
    def __init__(self) -> None:
        self.sent: list[tuple[str, str, str]] = []
        self.fail = False

    async def send(self, to: str, subject: str, body: str) -> None:
        if self.fail:
            raise MailNotSent()
        self.sent.append((to, subject, body))

    @property
    def last_code(self) -> str:
        return re.search(r"\b(\d{6})\b", self.sent[-1][2]).group(1)


@pytest.fixture
def clock() -> Clock:
    return Clock()


@pytest.fixture
def mailer() -> FakeMailer:
    return FakeMailer()


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


@pytest.fixture
def service(store, mailer, clock) -> SignInService:
    return SignInService(store, mailer, "s" * 32, clock=clock)


async def signed_in(service, mailer, *, trust=True) -> SignedIn:
    step = await service.begin(ALICE, None)
    assert isinstance(step, CodeSent)
    return await service.verify(
        step.challenge_token, mailer.last_code, trust_device=trust, previous_session=None
    )


async def test_a_first_sign_in_emails_a_code_and_the_code_opens_a_session(service, mailer) -> None:
    step = await service.begin(ALICE, None)
    assert isinstance(step, CodeSent)
    assert mailer.sent[0][0] == "alice@acme.test"
    done = await service.verify(
        step.challenge_token, mailer.last_code, trust_device=True, previous_session=None
    )
    assert done.device_token is not None
    principal = await service.authenticate_session(done.session_token)
    assert principal == Principal(
        principal.user_id,
        BOOTSTRAP_WORKSPACE_ID,
        SCOPE_SETS["admin"],
        "session",
        "alice@acme.test",
        role="owner",
    )


async def test_a_trusted_browser_skips_the_code(service, mailer) -> None:
    first = await signed_in(service, mailer)
    mailer.sent.clear()
    again = await service.begin(ALICE, first.device_token)
    assert isinstance(again, SignedIn) and again.device_token is None
    assert mailer.sent == []


async def test_a_code_dies_after_five_misses_and_a_used_code_never_works_again(
    service, mailer, clock
) -> None:
    step = await service.begin(ALICE, None)
    good = mailer.last_code
    bad = "000000" if good != "000000" else "111111"
    for _ in range(4):
        with pytest.raises(CodeRejected, match="wrong_code"):
            await service.verify(
                step.challenge_token, bad, trust_device=False, previous_session=None
            )
    with pytest.raises(CodeRejected, match="too_many_attempts"):
        await service.verify(step.challenge_token, bad, trust_device=False, previous_session=None)
    with pytest.raises(CodeRejected, match="expired"):
        await service.verify(step.challenge_token, good, trust_device=False, previous_session=None)
    clock.now = T0 + timedelta(seconds=61)  # a new sign-in waits out the code cooldown
    fresh = await service.begin(ALICE, None)
    code = mailer.last_code
    await service.verify(fresh.challenge_token, code, trust_device=False, previous_session=None)
    with pytest.raises(CodeRejected, match="expired"):
        await service.verify(fresh.challenge_token, code, trust_device=False, previous_session=None)


async def test_a_code_expires_after_ten_minutes(service, mailer, clock) -> None:
    step = await service.begin(ALICE, None)
    clock.now = T0 + timedelta(minutes=10, seconds=1)
    with pytest.raises(CodeRejected, match="expired"):
        await service.verify(
            step.challenge_token, mailer.last_code, trust_device=False, previous_session=None
        )


async def test_resend_waits_sixty_seconds_and_replaces_the_code(service, mailer, clock) -> None:
    step = await service.begin(ALICE, None)
    with pytest.raises(CodeLimited, match="resend_too_soon"):
        await service.resend(step.challenge_token)
    clock.now = T0 + timedelta(seconds=61)
    again = await service.resend(step.challenge_token)
    with pytest.raises(CodeRejected, match="expired"):
        await service.verify(
            step.challenge_token, mailer.last_code, trust_device=False, previous_session=None
        )
    await service.verify(
        again.challenge_token, mailer.last_code, trust_device=False, previous_session=None
    )


async def test_ten_codes_a_day_at_most(service, mailer, clock) -> None:
    for minute in range(10):
        clock.now = T0 + timedelta(minutes=minute)
        await service.begin(ALICE, None)
    with pytest.raises(SignInRefused) as caught:
        await service.begin(ALICE, None)
    assert caught.value.code == "too_many_codes"


async def test_an_unsent_code_cannot_be_used(service, mailer, clock) -> None:
    mailer.fail = True
    with pytest.raises(CodeNotSent):
        await service.begin(ALICE, None)


async def test_a_failed_send_does_not_start_the_cooldown(service, mailer) -> None:
    mailer.fail = True
    with pytest.raises(CodeNotSent):
        await service.begin(ALICE, None)
    mailer.fail = False
    await service.begin(ALICE, None)  # same instant: nothing was sent, so nothing to wait for
    assert len(mailer.sent) == 1


async def test_a_session_slides_but_never_outlives_seven_days(service, mailer, clock) -> None:
    done = await signed_in(service, mailer)
    for hours in range(11, 24 * 7, 11):
        clock.now = T0 + timedelta(hours=hours)
        assert await service.authenticate_session(done.session_token) is not None
    clock.now = T0 + timedelta(days=7, minutes=1)
    assert await service.authenticate_session(done.session_token) is None


async def test_signing_in_again_rotates_the_session_and_logout_ends_it(
    service, mailer, clock
) -> None:
    first = await signed_in(service, mailer, trust=False)
    clock.now = T0 + timedelta(minutes=2)
    step = await service.begin(ALICE, None)
    second = await service.verify(
        step.challenge_token,
        mailer.last_code,
        trust_device=False,
        previous_session=first.session_token,
    )
    assert await service.authenticate_session(first.session_token) is None
    await service.logout(second.session_token, None, forget_device=False)
    assert await service.authenticate_session(second.session_token) is None


async def test_a_disabled_user_cannot_sign_in_or_keep_a_session(service, mailer, store) -> None:
    done = await signed_in(service, mailer)
    with store._engine.begin() as connection:
        connection.execute(text("UPDATE users SET disabled_at = CURRENT_TIMESTAMP"))
    assert await service.authenticate_session(done.session_token) is None
    with pytest.raises(SignInRefused, match="not_allowed"):
        await service.begin(ALICE, done.device_token)


async def test_tokens_are_scoped_limited_listed_and_revoked(service, mailer, clock) -> None:
    done = await signed_in(service, mailer)
    owner = await service.authenticate_session(done.session_token)
    created = await service.create_token(owner, CreateToken(name="ci", scope="read", days=1))
    assert created.secret.startswith("thoth_pat_") and created.token.prefix == created.secret[:16]
    by_token = await service.authenticate_token(created.secret)
    assert by_token.scopes == SCOPE_SETS["read"] and by_token.via == "token"
    with pytest.raises(ScopeTooBroad):
        await service.create_token(by_token, CreateToken(name="wider", scope="write"))
    assert [t.name for t in await service.list_tokens(owner)] == ["ci"]
    assert await service.revoke_token(owner, created.token.token_id)
    assert await service.authenticate_token(created.secret) is None
    for index in range(20):
        await service.create_token(owner, CreateToken(name=f"t{index}"))
    with pytest.raises(TokenLimitReached):
        await service.create_token(owner, CreateToken(name="one too many"))
    clock.now = T0 + timedelta(days=91)
    assert await service.authenticate_token(created.secret) is None


async def test_the_service_key_principal_has_no_user_for_personal_tokens(service) -> None:
    service_principal = Principal(None, BOOTSTRAP_WORKSPACE_ID, SCOPE_SETS["admin"], "service")
    with pytest.raises(UserRequired):
        await service.create_token(service_principal, CreateToken(name="x"))


async def test_without_a_secret_or_mailer_sign_in_is_not_configured(store) -> None:
    with pytest.raises(SignInRefused, match="not_configured"):
        await SignInService(store, None, "s" * 32).begin(ALICE, None)
    with pytest.raises(SignInRefused, match="not_configured"):
        await SignInService(store, FakeMailer(), None).begin(ALICE, None)


async def test_an_unknown_token_or_session_is_simply_absent(service) -> None:
    assert await service.authenticate_token("not-a-thoth-token") is None
    assert await service.authenticate_token("thoth_pat_nope") is None
    assert await service.authenticate_session("nope") is None


async def test_racing_guesses_get_at_most_five_evaluations(
    service, mailer, store, monkeypatch
) -> None:
    """Six wrong guesses are in flight (each has read the challenge, none counted yet)."""
    import asyncio
    import threading

    step = await service.begin(ALICE, None)
    good = mailer.last_code
    bad = "000000" if good != "000000" else "111111"
    gate = threading.Event()
    real = store.claim_attempt

    lock = threading.Lock()  # the test database is one shared SQLite connection

    def held(token_hash):
        with lock:
            claimed = real(token_hash)  # the guess is counted, then held before it is checked
        gate.wait(5)
        return claimed

    monkeypatch.setattr(store, "claim_attempt", held)
    racing = [
        asyncio.create_task(
            service.verify(step.challenge_token, bad, trust_device=False, previous_session=None)
        )
        for _ in range(6)
    ]
    await asyncio.sleep(0.3)
    monkeypatch.setattr(store, "claim_attempt", real)  # the good guess is not held
    try:
        with pytest.raises(CodeRejected):
            await service.verify(
                step.challenge_token, good, trust_device=False, previous_session=None
            )
    finally:
        gate.set()
        await asyncio.gather(*racing, return_exceptions=True)


async def test_a_token_minted_by_a_token_never_outlives_its_parent(service, mailer) -> None:
    done = await signed_in(service, mailer)
    owner = await service.authenticate_session(done.session_token)
    parent = await service.create_token(owner, CreateToken(name="leaked", scope="admin", days=1))
    by_parent = await service.authenticate_token(parent.secret)
    child = await service.create_token(
        by_parent, CreateToken(name="successor", scope="admin", days=365)
    )
    assert child.token.expires_at <= parent.token.expires_at
    assert await service.authenticate_token(child.secret) is not None
    assert await service.revoke_token(owner, parent.token.token_id)
    assert (
        await service.authenticate_token(child.secret) is None
    )  # revoking the leak cuts its heirs


async def test_a_trusted_browser_sign_in_rotates_the_previous_session(
    service, mailer, clock
) -> None:
    first = await signed_in(service, mailer)
    clock.now = T0 + timedelta(minutes=2)
    again = await service.begin(ALICE, first.device_token, previous_session=first.session_token)
    assert isinstance(again, SignedIn)
    assert await service.authenticate_session(first.session_token) is None
    assert await service.authenticate_session(again.session_token) is not None


async def test_sign_ins_within_a_minute_send_one_code(service, mailer, clock) -> None:
    await service.begin(ALICE, None)
    with pytest.raises(SignInRefused) as caught:
        await service.begin(ALICE, None)
    assert caught.value.code == "too_soon"
    assert len(mailer.sent) == 1
    clock.now = T0 + timedelta(seconds=61)
    await service.begin(ALICE, None)
    assert len(mailer.sent) == 2


async def test_the_principal_carries_the_membership_role(service, mailer) -> None:
    first = await signed_in(service, mailer)
    principal = await service.authenticate_session(first.session_token)
    assert principal.workspace_id == BOOTSTRAP_WORKSPACE_ID
    assert principal.role == "owner"
    assert is_platform_admin(principal)


async def test_a_session_without_membership_is_signed_out(service, mailer, store) -> None:
    first = await signed_in(service, mailer)
    with store._engine.begin() as connection:
        connection.execute(text("DELETE FROM workspace_members"))
    assert await service.authenticate_session(first.session_token) is None


async def test_a_personal_token_without_membership_is_refused(service, mailer, store) -> None:
    first = await signed_in(service, mailer)
    principal = await service.authenticate_session(first.session_token)
    created = await service.create_token(principal, CreateToken(name="cli", scope="write", days=30))
    assert await service.authenticate_token(created.secret) is not None
    with store._engine.begin() as connection:
        connection.execute(text("DELETE FROM workspace_members"))
    assert await service.authenticate_token(created.secret) is None


def test_who_is_a_platform_admin() -> None:
    def principal(workspace, role, via="session", user="usr_1"):
        return Principal(user, workspace, SCOPE_SETS["admin"], via, role=role)

    service_key = Principal(None, BOOTSTRAP_WORKSPACE_ID, SCOPE_SETS["admin"], "service")
    assert is_platform_admin(service_key)
    assert is_platform_admin(principal(BOOTSTRAP_WORKSPACE_ID, "owner"))
    assert is_platform_admin(principal(BOOTSTRAP_WORKSPACE_ID, "admin", via="token"))
    assert not is_platform_admin(principal(BOOTSTRAP_WORKSPACE_ID, "member"))
    assert not is_platform_admin(principal("ws_other", "owner"))
    assert not is_platform_admin(principal(BOOTSTRAP_WORKSPACE_ID, None, via="token", user=None))


async def test_describe_names_the_workspace_and_the_admin_flag(service, mailer, store) -> None:
    first = await signed_in(service, mailer)
    principal = await service.authenticate_session(first.session_token)
    view = await service.describe(principal)
    assert view.workspace.workspace_id == BOOTSTRAP_WORKSPACE_ID
    assert view.workspace.name == "Thoth"
    assert view.workspace.role == "owner"
    assert view.platform_admin is True
    bob = store.ensure_user("bob@acme.test", "Bob")
    assert bob.workspace_id != BOOTSTRAP_WORKSPACE_ID
    bob_view = await service.describe(
        Principal(bob.user_id, bob.workspace_id, SCOPE_SETS["admin"], "session", role="owner")
    )
    assert bob_view.workspace.name == "Bob's workspace"
    assert bob_view.platform_admin is False
