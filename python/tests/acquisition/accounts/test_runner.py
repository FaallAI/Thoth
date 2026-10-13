"""The account runner over a real SQLite store and a scripted acquisition; no network."""

from __future__ import annotations

import logging
from datetime import UTC, datetime
from pathlib import Path

import pytest
from cryptography.fernet import Fernet
from sqlalchemy import create_engine
from sqlalchemy.pool import StaticPool

from tests.activities.test_source_investigation import _load_fixture_report
from thoth_control_plane.acquisition.accounts.access import SessionAccess
from thoth_control_plane.acquisition.accounts.cookies import parse_cookies
from thoth_control_plane.acquisition.accounts.runner import account_outcome, account_runner
from thoth_control_plane.acquisition.accounts.vault import Vault
from thoth_control_plane.acquisition.models import (
    AccountUse,
    AcquisitionAttempt,
    AcquisitionFailure,
    AcquisitionReason,
    AcquisitionResult,
    AcquisitionStrategy,
    AttemptStatus,
)
from thoth_control_plane.infrastructure.source_account_models import Base
from thoth_control_plane.infrastructure.source_account_store import SourceAccountStore

URL = "https://www.instagram.com/p/abc/"
NOW = datetime(2026, 10, 7, 12, 0, tzinfo=UTC)
SECRET = "s3cr3t-session-value"
COOKIES = parse_cookies(
    "instagram",
    "\t".join([".instagram.com", "TRUE", "/", "TRUE", "1893456000", "sessionid", SECRET]) + "\n",
    now=NOW,
)
SUCCESS = AcquisitionResult(report=_load_fixture_report())


def _failure(code: str, reason: AcquisitionReason | None = None) -> AcquisitionResult:
    attempts = []
    if reason is not None:
        attempts.append(
            AcquisitionAttempt(
                strategy=AcquisitionStrategy.SCRAPLING_REQUEST,
                status=AttemptStatus.FAILED,
                reason=reason,
                attempt_count=1,
                elapsed_ms=5,
            )
        )
    return AcquisitionResult(
        failure=AcquisitionFailure(code=code, retryable=True, attempts=attempts)  # type: ignore[arg-type]
    )


BLOCKED = _failure("request_blocked", AcquisitionReason.REQUEST_BLOCKED)
LOGIN_WALL = _failure("request_blocked", AcquisitionReason.LOGIN_WALL)
TIMEOUT = _failure("request_timeout", AcquisitionReason.REQUEST_TIMEOUT)


class Script:
    """Answers each acquisition in turn and records whether a session was supplied."""

    def __init__(self, *results: AcquisitionResult | Exception) -> None:
        self.results = list(results)
        self.sessions: list[SessionAccess | None] = []

    async def __call__(self, workflow_id, source_url, artifact_root, access):
        self.sessions.append(access)
        result = self.results.pop(0)
        if isinstance(result, Exception):
            raise result
        return result


@pytest.fixture
def store() -> SourceAccountStore:
    engine = create_engine(
        "sqlite://", poolclass=StaticPool, connect_args={"check_same_thread": False}
    )
    Base.metadata.create_all(engine)
    store = SourceAccountStore(engine, Vault(Fernet.generate_key().decode()))
    store.set_policy("instagram", "fallback", 0)
    return store


async def _run(store: SourceAccountStore | None, script: Script) -> AcquisitionResult:
    return await account_runner(store, script)("wf_1", URL, Path("."))


@pytest.mark.parametrize(
    ("result", "outcome"),
    [
        (SUCCESS, "success"),
        (BLOCKED, "blocked"),
        (_failure("headless_blocked", AcquisitionReason.HEADLESS_BLOCKED), "blocked"),
        (LOGIN_WALL, "login_wall"),
        (_failure("cdn_rate_limited", AcquisitionReason.CDN_RATE_LIMITED), "rate_limited"),
        (TIMEOUT, None),
        (_failure("media_validation_failed"), None),
        (_failure("invalid_source_url"), None),
    ],
)
def test_outcomes_map_from_the_result(result: AcquisitionResult, outcome: str | None) -> None:
    assert account_outcome(result) == outcome


@pytest.mark.asyncio
async def test_without_a_store_or_in_anonymous_mode_no_session_is_used(
    store: SourceAccountStore,
) -> None:
    store.add_account("instagram", "a", COOKIES)
    script = Script(SUCCESS)
    assert (await _run(None, script)).account is None
    store.set_policy("instagram", "anonymous", 0)
    script = Script(BLOCKED)
    result = await _run(store, script)
    assert (script.sessions, result.account) == ([None], None)


@pytest.mark.asyncio
async def test_always_mode_uses_an_account_and_records_success(store: SourceAccountStore) -> None:
    store.set_policy("instagram", "always", 0)
    account = store.add_account("instagram", "a", COOKIES)
    script = Script(SUCCESS)
    result = await _run(store, script)
    (session,) = script.sessions
    assert session is not None and session.cookies.to_request() == {"sessionid": SECRET}
    assert result.account == AccountUse(used=True, outcome="success")
    view = store.account(account.id)
    assert (view.success_count, view.last_outcome) == (1, "success")
    assert store.lease("instagram") is not None


@pytest.mark.asyncio
async def test_always_mode_without_an_account_runs_anonymously_and_says_so(
    store: SourceAccountStore,
) -> None:
    store.set_policy("instagram", "always", 0)
    script = Script(SUCCESS)
    result = await _run(store, script)
    assert script.sessions == [None]
    assert result.report is not None
    assert result.account == AccountUse(used=False, no_account_available=True)


@pytest.mark.asyncio
async def test_fallback_keeps_an_anonymous_success_and_leaves_accounts_alone(
    store: SourceAccountStore,
) -> None:
    account = store.add_account("instagram", "a", COOKIES)
    script = Script(SUCCESS)
    result = await _run(store, script)
    assert (script.sessions, result.account) == ([None], None)
    assert store.account(account.id).last_used_at is None


@pytest.mark.parametrize("anonymous", [BLOCKED, LOGIN_WALL])
@pytest.mark.asyncio
async def test_fallback_retries_once_with_an_account_when_anonymous_is_refused(
    store: SourceAccountStore, anonymous: AcquisitionResult
) -> None:
    store.add_account("instagram", "a", COOKIES)
    script = Script(anonymous, SUCCESS)
    result = await _run(store, script)
    assert script.sessions[0] is None and script.sessions[1] is not None
    assert result.report is not None
    assert result.account == AccountUse(used=True, outcome="success")


@pytest.mark.asyncio
async def test_fallback_without_an_account_keeps_the_anonymous_failure(
    store: SourceAccountStore,
) -> None:
    script = Script(BLOCKED)
    result = await _run(store, script)
    assert script.sessions == [None]
    assert result.failure == BLOCKED.failure
    assert result.account == AccountUse(used=False, no_account_available=True)


@pytest.mark.asyncio
async def test_fallback_does_not_retry_a_timeout(store: SourceAccountStore) -> None:
    store.add_account("instagram", "a", COOKIES)
    script = Script(TIMEOUT)
    assert (await _run(store, script)).account is None
    assert script.sessions == [None]


@pytest.mark.asyncio
async def test_a_login_wall_with_an_account_expires_it(store: SourceAccountStore) -> None:
    store.set_policy("instagram", "always", 0)
    account = store.add_account("instagram", "a", COOKIES)
    result = await _run(store, Script(LOGIN_WALL))
    assert result.account == AccountUse(used=True, outcome="login_wall")
    assert store.account(account.id).status == "expired"


@pytest.mark.asyncio
async def test_a_timeout_with_an_account_releases_it_unharmed(store: SourceAccountStore) -> None:
    store.set_policy("instagram", "always", 0)
    account = store.add_account("instagram", "a", COOKIES)
    result = await _run(store, Script(TIMEOUT))
    assert result.account == AccountUse(used=True, outcome=None)
    view = store.account(account.id)
    assert (view.status, view.success_count, view.failure_count) == ("healthy", 0, 0)
    assert store.lease("instagram") is not None


@pytest.mark.asyncio
async def test_an_acquisition_that_raises_still_releases_the_account(
    store: SourceAccountStore,
) -> None:
    store.set_policy("instagram", "always", 0)
    store.add_account("instagram", "a", COOKIES)
    with pytest.raises(RuntimeError):
        await _run(store, Script(RuntimeError("boom")))
    assert store.lease("instagram") is not None


@pytest.mark.asyncio
async def test_a_failing_store_never_fails_acquisition(
    store: SourceAccountStore, monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
) -> None:
    def broken(*args: object) -> None:
        raise RuntimeError(f"database said {SECRET}")

    monkeypatch.setattr(store, "policy", broken)
    script = Script(SUCCESS)
    with caplog.at_level(logging.WARNING):
        result = await _run(store, script)
    assert (script.sessions, result.report is not None) == ([None], True)
    assert "acquisition runs anonymously" in caplog.text
    assert SECRET not in caplog.text


@pytest.mark.asyncio
async def test_a_leased_acquisition_runs_in_the_accounts_patchright_profile(
    store: SourceAccountStore, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from thoth_control_plane.acquisition.accounts import fingerprints
    from thoth_control_plane.acquisition.accounts.profiles import AccountProfiles

    monkeypatch.setattr(fingerprints, "new_fingerprint", lambda: {"n": 1})
    store.set_policy("instagram", "always", 0, engine="camoufox")
    store.add_account("instagram", "a", COOKIES)
    profiles = AccountProfiles(Vault(Fernet.generate_key().decode()), tmp_path / "profiles")
    script = Script(SUCCESS)

    await account_runner(store, script, profiles)("wf_1", URL, Path("."))

    (session,) = script.sessions
    assert session is not None and session.profile_dir is not None
    assert session.engine == "patchright"  # card crops stay on Scrapling (spec 3.4)
    assert not session.profile_dir.exists()
    assert [path.name.split(".")[1] for path in (tmp_path / "profiles").iterdir()] == ["patchright"]
