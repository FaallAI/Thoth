"""The source-account store on an in-memory SQLite database; Postgres locking is tested apart."""

from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta

import pytest
from cryptography.fernet import Fernet
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from tests.sqlite_support import sqlite_engine
from thoth_control_plane import metering
from thoth_control_plane.acquisition.accounts import fingerprints
from thoth_control_plane.acquisition.accounts.cookies import parse_cookies
from thoth_control_plane.acquisition.accounts.proxies import parse_proxy_list
from thoth_control_plane.acquisition.accounts.vault import Vault
from thoth_control_plane.infrastructure.source_account_models import Base, SourceAccountRow
from thoth_control_plane.infrastructure.source_account_store import (
    QuotaReached,
    SourceAccountError,
    SourceAccountStore,
)
from thoth_control_plane.infrastructure.usage_models import UsageEventRow, WorkspaceQuotaRow
from thoth_control_plane.metering import MeterScope

NOW = datetime(2026, 10, 7, 12, 0, tzinfo=UTC)
SECRET = "s3cr3t-session-value"
PROXY_PASSWORD = "pr0xy-pa55"


class Clock:
    def __init__(self) -> None:
        self.now = NOW

    def __call__(self) -> datetime:
        return self.now


def _cookies(platform: str = "instagram", value: str = SECRET):
    name = {"x": "auth_token"}.get(platform, "sessionid")
    domain = {"x": ".x.com", "tiktok": ".tiktok.com"}.get(platform, ".instagram.com")
    lines = ["\t".join([domain, "TRUE", "/", "TRUE", "1893456000", name, value])]
    if platform == "x":
        lines.append("\t".join([domain, "TRUE", "/", "TRUE", "1893456000", "ct0", "c"]))
    return parse_cookies(platform, "\n".join(lines) + "\n", now=NOW)  # type: ignore[arg-type]


@pytest.fixture
def engine():
    engine = sqlite_engine()
    Base.metadata.create_all(engine)
    return engine


@pytest.fixture
def clock() -> Clock:
    return Clock()


@pytest.fixture
def store(engine, clock: Clock) -> SourceAccountStore:
    return SourceAccountStore(engine, Vault(Fernet.generate_key().decode()), clock)


def _proxies(store: SourceAccountStore, *lines: str) -> list[str]:
    store.import_proxies(parse_proxy_list("\n".join(lines)))
    return [proxy.id for proxy in store.proxies()]


def test_policies_default_to_fallback_and_can_be_set(store: SourceAccountStore) -> None:
    # Instagram spaces leases at least 10 minutes (spec 2026-10-13, account safety).
    assert {(p.platform, p.mode, p.min_spacing_seconds) for p in store.policies()} == {
        (platform, "fallback", 600 if platform == "instagram" else 60)
        for platform in ("tiktok", "threads", "instagram", "x", "youtube")
    }
    store.set_policy("instagram", "always", 120)
    store.set_policy("instagram", "anonymous", 30)
    assert store.policy("instagram").mode == "anonymous"
    assert store.policy("instagram").min_spacing_seconds == 30


def test_an_account_stores_names_and_expiry_but_never_the_cookie_in_clear(
    store: SourceAccountStore, engine
) -> None:
    view = store.add_account("instagram", "main", _cookies())
    assert (view.status, view.cookie_names, view.proxy_id) == ("healthy", ("sessionid",), None)
    assert view.cookies_earliest_expiry == datetime(2030, 1, 1, tzinfo=UTC)
    with Session(engine) as session:
        row = session.scalars(select(SourceAccountRow)).one()
        assert SECRET.encode() not in row.cookies_ciphertext
    assert SECRET not in repr(view)


def test_labels_are_unique_per_platform(store: SourceAccountStore) -> None:
    store.add_account("instagram", "main", _cookies())
    store.add_account("x", "main", _cookies("x"))
    with pytest.raises(SourceAccountError) as caught:
        store.add_account("instagram", "main", _cookies())
    assert caught.value.code == "label_taken"


def test_one_proxy_serves_one_account_and_returns_to_the_pool(store: SourceAccountStore) -> None:
    (proxy,) = _proxies(store, f"http://u:{PROXY_PASSWORD}@1.2.3.4:8080")
    first = store.add_account("instagram", "a", _cookies(), proxy)
    assert (first.proxy_id, first.proxy_display) == (proxy, "1.2.3.4:8080")
    with pytest.raises(SourceAccountError) as caught:
        store.add_account("instagram", "b", _cookies(), proxy)
    assert caught.value.code == "proxy_in_use"
    with pytest.raises(SourceAccountError) as caught:
        store.delete_proxy(proxy)
    assert caught.value.code == "proxy_in_use"
    (view,) = store.proxies()
    assert (view.account_platform, view.account_label) == ("instagram", "a")
    store.update_account(first.id, proxy_id=proxy)
    store.delete_account(first.id)
    assert store.proxies()[0].account_label is None
    store.delete_proxy(proxy)
    assert store.proxies() == []


def test_an_unknown_proxy_or_account_is_refused(store: SourceAccountStore) -> None:
    with pytest.raises(SourceAccountError) as caught:
        store.add_account("instagram", "a", _cookies(), "00000000-0000-0000-0000-000000000000")
    assert caught.value.code == "proxy_not_found"
    for bad in ("not-a-uuid", "00000000-0000-0000-0000-000000000000"):
        with pytest.raises(SourceAccountError) as caught:
            store.account(bad)
        assert caught.value.code == "not_found"


def test_proxy_imports_count_duplicates_by_fingerprint(store: SourceAccountStore) -> None:
    line = f"http://u:{PROXY_PASSWORD}@1.2.3.4:8080"
    first = store.import_proxies(parse_proxy_list(f"{line}\nbad line"))
    again = store.import_proxies(parse_proxy_list(f"{line}\nhttp://u:other@1.2.3.4:8080"))
    assert (first.added, first.duplicates, first.invalid_lines) == (1, 0, (2,))
    assert (again.added, again.duplicates) == (1, 1)
    assert [p.display for p in store.proxies()] == ["1.2.3.4:8080", "1.2.3.4:8080"]


def test_update_relabels_reassigns_and_toggles(store: SourceAccountStore) -> None:
    proxy_a, proxy_b = _proxies(store, "http://1.1.1.1:80", "http://2.2.2.2:80")
    account = store.add_account("instagram", "a", _cookies(), proxy_a)
    view = store.update_account(account.id, label="renamed", proxy_id=proxy_b)
    assert (view.label, view.proxy_id) == ("renamed", proxy_b)
    assert store.update_account(account.id, proxy_id=None).proxy_id is None
    assert store.update_account(account.id, disabled=True).status == "disabled"
    assert store.update_account(account.id).status == "disabled"
    assert store.update_account(account.id, disabled=False).status == "healthy"


def test_lease_takes_the_least_recently_used_and_respects_spacing(
    store: SourceAccountStore, clock: Clock
) -> None:
    store.set_policy("instagram", "always", 60)
    a = store.add_account("instagram", "a", _cookies(value="a-cookie"))
    b = store.add_account("instagram", "b", _cookies(value="b-cookie"))
    first = store.lease("instagram")
    second = store.lease("instagram")
    assert {first.account_id, second.account_id} == {a.id, b.id}
    assert store.lease("instagram") is None
    store.report(first.account_id, "success")
    store.report(second.account_id, "success")
    clock.now += timedelta(seconds=30)
    assert store.lease("instagram") is None
    clock.now += timedelta(seconds=31)
    third = store.lease("instagram")
    assert third.account_id == first.account_id
    assert third.access.cookies.to_request()["sessionid"] in ("a-cookie", "b-cookie")


def test_a_lease_carries_the_accounts_proxy(store: SourceAccountStore) -> None:
    (proxy,) = _proxies(store, f"http://u:{PROXY_PASSWORD}@1.2.3.4:8080")
    store.add_account("instagram", "a", _cookies(), proxy)
    lease = store.lease("instagram")
    assert lease.access.proxy == f"http://u:{PROXY_PASSWORD}@1.2.3.4:8080"
    assert lease.access.cookies.to_request() == {"sessionid": SECRET}


def test_a_dead_holders_lease_expires(store: SourceAccountStore, clock: Clock) -> None:
    store.set_policy("instagram", "always", 0)
    store.add_account("instagram", "a", _cookies())
    assert store.lease("instagram") is not None
    clock.now += timedelta(minutes=9)
    assert store.lease("instagram") is None
    clock.now += timedelta(minutes=2)
    assert store.lease("instagram") is not None


def test_cooldown_expired_and_disabled_accounts_are_skipped(
    store: SourceAccountStore, clock: Clock
) -> None:
    store.set_policy("instagram", "always", 0)
    a = store.add_account("instagram", "a", _cookies())
    store.report(store.lease("instagram").account_id, "blocked")
    assert store.account(a.id).status == "cooldown"
    assert store.lease("instagram") is None
    clock.now += timedelta(minutes=15)
    lease = store.lease("instagram")
    assert lease.account_id == a.id
    store.report(lease.account_id, "login_wall")
    assert (store.account(a.id).status, store.account(a.id).last_outcome) == (
        "expired",
        "login_wall",
    )
    assert store.lease("instagram") is None
    store.replace_cookies(a.id, _cookies())
    assert store.account(a.id).status == "healthy"
    store.update_account(a.id, disabled=True)
    assert store.lease("instagram") is None


def test_a_release_without_outcome_leaves_health_alone(store: SourceAccountStore) -> None:
    store.set_policy("instagram", "always", 0)
    a = store.add_account("instagram", "a", _cookies())
    store.report(store.lease("instagram").account_id, None)
    view = store.account(a.id)
    assert (view.status, view.success_count, view.failure_count) == ("healthy", 0, 0)
    assert store.lease("instagram") is not None


def test_an_account_sealed_with_another_key_expires_and_is_skipped(engine, clock: Clock) -> None:
    old = SourceAccountStore(engine, Vault(Fernet.generate_key().decode()), clock)
    old.set_policy("instagram", "always", 0)
    stale = old.add_account("instagram", "stale", _cookies())
    new = SourceAccountStore(engine, Vault(Fernet.generate_key().decode()), clock)
    assert new.lease("instagram") is None
    assert (new.account(stale.id).status, new.account(stale.id).last_outcome) == (
        "expired",
        "undecryptable",
    )
    with pytest.raises(SourceAccountError) as caught:
        new.access(stale.id)
    assert caught.value.code == "undecryptable"


def test_re_importing_another_platforms_cookies_is_refused(store: SourceAccountStore) -> None:
    a = store.add_account("instagram", "a", _cookies())
    with pytest.raises(SourceAccountError) as caught:
        store.replace_cookies(a.id, _cookies("x"))
    assert caught.value.code == "platform_mismatch"


def test_a_manual_check_heals_or_expires(store: SourceAccountStore) -> None:
    a = store.add_account("instagram", "a", _cookies())
    assert store.record_check(a.id, valid=False).status == "expired"
    assert store.record_check(a.id, valid=True).status == "healthy"
    assert store.access(a.id).cookies.to_request() == {"sessionid": SECRET}


def test_releasing_a_lease_on_a_deleted_account_is_quiet(store: SourceAccountStore) -> None:
    store.set_policy("instagram", "always", 0)
    account = store.add_account("instagram", "a", _cookies())
    lease = store.lease("instagram")
    store.delete_account(account.id)
    store.report(lease.account_id, "success")
    assert store.accounts() == []


def test_a_stale_report_after_a_re_import_leaves_the_fresh_session_alone(
    store: SourceAccountStore,
) -> None:
    store.set_policy("instagram", "always", 0)
    account = store.add_account("instagram", "a", _cookies())
    lease = store.lease("instagram")
    store.replace_cookies(account.id, _cookies(value="fresh"))
    store.report(lease.account_id, "login_wall", leased_until=lease.leased_until)
    assert store.account(account.id).status == "healthy"
    assert store.lease("instagram") is not None


def test_policies_default_to_the_platform_budgets_and_patchright(
    store: SourceAccountStore,
) -> None:
    views = {view.platform: view for view in store.policies()}

    assert (views["instagram"].daily_budget, views["instagram"].min_spacing_seconds) == (20, 600)
    assert (views["tiktok"].daily_budget, views["x"].daily_budget) == (40, 30)
    assert (views["youtube"].daily_budget, views["threads"].daily_budget) == (60, 30)
    assert {view.engine for view in views.values()} == {"patchright"}


def test_a_policy_stores_budget_and_engine(store: SourceAccountStore) -> None:
    view = store.set_policy("instagram", "fallback", 900, daily_budget=5, engine="camoufox")

    assert (view.daily_budget, view.engine, view.min_spacing_seconds) == (5, "camoufox", 900)
    assert store.policy("instagram").engine == "camoufox"
    assert store.set_policy("instagram", "fallback", 900, daily_budget=None).daily_budget == 20
    with pytest.raises(ValueError):
        store.set_policy("instagram", "fallback", 900, engine="chromium")


def test_an_account_over_its_daily_budget_is_not_leased(store: SourceAccountStore) -> None:
    # Spec 2026-10-13, 3.3: a busy day must not turn into a burst on one account.
    store.set_policy("instagram", "fallback", 0, daily_budget=2)
    account = store.add_account("instagram", "a", _cookies())

    for _ in range(2):
        lease = store.lease("instagram")
        assert lease is not None
        store.report(lease.account_id, "success", lease.leased_until)

    assert store.lease("instagram") is None
    assert store.account(account.id).uses_today == 2


def test_the_budget_resets_on_the_next_utc_day(store: SourceAccountStore, clock: Clock) -> None:
    store.set_policy("instagram", "fallback", 0, daily_budget=1)
    store.add_account("instagram", "a", _cookies())
    first = store.lease("instagram")
    store.report(first.account_id, "success", first.leased_until)
    assert store.lease("instagram") is None

    clock.now += timedelta(days=1)

    assert store.lease("instagram") is not None


def test_a_zero_budget_is_unlimited(store: SourceAccountStore) -> None:
    store.set_policy("instagram", "fallback", 0, daily_budget=0)
    store.add_account("instagram", "a", _cookies())

    for _ in range(30):
        lease = store.lease("instagram")
        assert lease is not None
        store.report(lease.account_id, "success", lease.leased_until)


def test_the_budget_counts_in_the_lease_transaction(store: SourceAccountStore) -> None:
    # Review focus 2: two leases in the same instant each take one account's last slot.
    store.set_policy("instagram", "fallback", 0, daily_budget=1)
    store.add_account("instagram", "a", _cookies(value="a-cookie"))
    store.add_account("instagram", "b", _cookies(value="b-cookie"))

    first, second = store.lease("instagram"), store.lease("instagram")

    assert first is not None and second is not None
    assert first.account_id != second.account_id
    store.report(first.account_id, "success", first.leased_until)
    store.report(second.account_id, "success", second.leased_until)
    assert store.lease("instagram") is None


def test_an_account_view_shows_locale_timezone_and_no_fingerprint_yet(
    store: SourceAccountStore,
) -> None:
    view = store.add_account("instagram", "a", _cookies())

    assert (view.locale, view.timezone, view.fingerprint_set, view.uses_today) == (
        "id-ID",
        "Asia/Jakarta",
        False,
        0,
    )


def test_a_camoufox_account_gets_one_lasting_firefox_fingerprint(
    store: SourceAccountStore, clock: Clock, monkeypatch: pytest.MonkeyPatch
) -> None:
    # The real generator installs fpgen's model; the store test pins only the lifecycle.
    made = iter([{"navigator": {"userAgent": "Firefox/150.0"}, "n": 1}, {"n": 2}])
    monkeypatch.setattr(fingerprints, "new_fingerprint", lambda: next(made))
    store.set_policy("instagram", "fallback", 0, engine="camoufox")
    account = store.add_account("instagram", "a", _cookies())
    first = store.lease("instagram")
    assert first is not None
    store.report(first.account_id, "success", first.leased_until)
    clock.now += timedelta(minutes=1)
    second = store.lease("instagram")
    assert second is not None

    assert first.access.fingerprint and first.access.fingerprint == second.access.fingerprint
    assert first.access.engine == "camoufox" and store.account(account.id).fingerprint_set


def test_a_patchright_lease_never_makes_a_fingerprint(
    store: SourceAccountStore, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(fingerprints, "new_fingerprint", lambda: pytest.fail("generated"))
    account = store.add_account("instagram", "a", _cookies())

    lease = store.lease("instagram")

    assert lease is not None
    assert lease.access.fingerprint is None and lease.access.engine == "patchright"
    assert not store.account(account.id).fingerprint_set


def test_a_lease_carries_the_accounts_locale_and_timezone(store: SourceAccountStore) -> None:
    account = store.add_account("instagram", "a", _cookies())
    store.update_account(account.id, locale="en-US", timezone="Asia/Makassar")

    lease = store.lease("instagram")

    assert lease is not None
    assert (lease.access.locale, lease.access.timezone) == ("en-US", "Asia/Makassar")
    view = store.account(account.id)
    assert (view.locale, view.timezone) == ("en-US", "Asia/Makassar")


def test_a_fingerprint_reset_clears_it(
    store: SourceAccountStore, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(fingerprints, "new_fingerprint", lambda: {"n": 1})
    store.set_policy("instagram", "fallback", 0, engine="camoufox")
    account = store.add_account("instagram", "a", _cookies())
    assert store.lease("instagram") is not None

    assert not store.update_account(account.id, reset_fingerprint=True).fingerprint_set


def test_a_lease_for_another_engine_skips_the_fingerprint(
    store: SourceAccountStore, monkeypatch: pytest.MonkeyPatch
) -> None:
    # Acquisition leases for Patchright even where discovery runs Camoufox (spec 3.4).
    monkeypatch.setattr(fingerprints, "new_fingerprint", lambda: pytest.fail("generated"))
    store.set_policy("instagram", "fallback", 0, engine="camoufox")
    store.add_account("instagram", "a", _cookies())

    lease = store.lease("instagram", engine="patchright")

    assert lease is not None
    assert (lease.access.engine, lease.access.fingerprint) == ("patchright", None)


def test_camoufox_is_refused_where_no_session_runs_it(store: SourceAccountStore) -> None:
    # Only Instagram's signed-in reels discovery runs Camoufox (spec 3.4); elsewhere a Firefox
    # profile would reach Chromium.
    for platform in ("tiktok", "x", "youtube", "threads"):
        with pytest.raises(SourceAccountError) as raised:
            store.set_policy(platform, "fallback", 0, engine="camoufox")  # type: ignore[arg-type]
        assert raised.value.code == "engine_unsupported"


def test_a_stray_camoufox_policy_still_leases_patchright(
    store: SourceAccountStore, engine, monkeypatch: pytest.MonkeyPatch
) -> None:
    from thoth_control_plane.infrastructure.source_account_models import SourceAccountPolicyRow

    monkeypatch.setattr(fingerprints, "new_fingerprint", lambda: pytest.fail("generated"))
    with Session(engine) as session, session.begin():
        session.add(
            SourceAccountPolicyRow(
                platform="tiktok",
                mode="fallback",
                min_spacing_seconds=0,
                engine="camoufox",
                updated_at=NOW,
            )
        )
    store.add_account("tiktok", "a", _cookies("tiktok"))

    lease = store.lease("tiktok")

    assert lease is not None and lease.access.engine == "patchright"


def test_a_policy_update_keeps_the_budget_and_engine_it_omits(store: SourceAccountStore) -> None:
    store.set_policy("instagram", "fallback", 900, daily_budget=5, engine="camoufox")

    view = store.set_policy("instagram", "always", 600)

    assert (view.mode, view.daily_budget, view.engine) == ("always", 5, "camoufox")


def test_a_lease_prunes_usage_older_than_a_month(
    store: SourceAccountStore, engine, clock: Clock
) -> None:
    import uuid

    from thoth_control_plane.infrastructure.source_account_models import SourceAccountUsageRow

    account = store.add_account("instagram", "a", _cookies())
    with Session(engine) as session, session.begin():
        for days in (31, 30):
            session.add(
                SourceAccountUsageRow(
                    account_id=uuid.UUID(account.id),
                    day=(NOW - timedelta(days=days)).date(),
                    uses=3,
                )
            )
    store.set_policy("instagram", "fallback", 0)

    assert store.lease("instagram") is not None

    with Session(engine) as session:
        days = sorted(row.day for row in session.scalars(select(SourceAccountUsageRow)))
    assert days == [(NOW - timedelta(days=30)).date(), NOW.date()]


A = MeterScope("ws_a", workflow_id="wf_a")


def _quota(engine, workspace: str, platform: str, n: int) -> None:
    with Session(engine) as session, session.begin():
        session.add(
            WorkspaceQuotaRow(
                workspace_id=workspace, platform=platform, daily_leases=n, updated_at=NOW
            )
        )


def _lease_and_release(store: SourceAccountStore, platform: str):
    lease = store.lease(platform)
    if lease is not None:
        store.report(lease.account_id, None, leased_until=lease.leased_until)
    return lease


def test_a_workspace_stops_at_its_daily_quota_and_the_bootstrap_does_not(store, engine, clock):
    store.set_policy("tiktok", "always", 0, daily_budget=0)
    store.add_account("tiktok", "t1", _cookies("tiktok"))
    _quota(engine, "ws_a", "tiktok", 2)
    with metering.scoped(A):
        assert _lease_and_release(store, "tiktok") is not None
        assert _lease_and_release(store, "tiktok") is not None
        with pytest.raises(QuotaReached) as refused:
            store.lease("tiktok")
        assert refused.value.code == "workspace_quota"
    assert _lease_and_release(store, "tiktok") is not None  # no scope: the bootstrap
    clock.now = NOW + timedelta(days=1)
    with metering.scoped(A):
        assert _lease_and_release(store, "tiktok") is not None


def test_a_zero_quota_turns_source_accounts_off_for_the_workspace(store, engine) -> None:
    store.set_policy("tiktok", "always", 0, daily_budget=0)
    store.add_account("tiktok", "t1", _cookies("tiktok"))
    _quota(engine, "ws_a", "tiktok", 0)
    with metering.scoped(A), pytest.raises(QuotaReached):
        store.lease("tiktok")


def test_the_reserve_keeps_half_the_capacity_for_the_operator(store, engine) -> None:
    store.set_policy("instagram", "always", 0, daily_budget=20)
    store.add_account("instagram", "i1", _cookies("instagram"))
    _quota(engine, "ws_a", "instagram", 100)
    with metering.scoped(A):
        for _ in range(10):
            assert _lease_and_release(store, "instagram") is not None
        with pytest.raises(QuotaReached) as refused:
            store.lease("instagram")
        assert refused.value.code == "operator_reserve"
    assert _lease_and_release(store, "instagram") is not None  # the bootstrap still leases


def test_capacity_skips_a_cooldown_that_lasts_past_today(store, engine) -> None:
    store.set_policy("instagram", "always", 0, daily_budget=20)
    store.add_account("instagram", "i1", _cookies("instagram"))
    resting = store.add_account("instagram", "i2", _cookies("instagram", "other"))
    with Session(engine) as session, session.begin():
        row = session.get(SourceAccountRow, uuid.UUID(resting.id))
        row.status, row.cooldown_until = "cooldown", NOW + timedelta(days=2)
    _quota(engine, "ws_a", "instagram", 100)
    with metering.scoped(A):
        for _ in range(10):
            assert _lease_and_release(store, "instagram") is not None
        with pytest.raises(QuotaReached):
            store.lease("instagram")


def test_an_unlimited_budget_has_no_reserve(store, engine) -> None:
    store.set_policy("tiktok", "always", 0, daily_budget=0)
    store.add_account("tiktok", "t1", _cookies("tiktok"))
    _quota(engine, "ws_a", "tiktok", 30)
    with metering.scoped(A):
        for _ in range(30):
            assert _lease_and_release(store, "tiktok") is not None


def test_the_reserve_percentage_can_be_changed_per_platform(store, engine) -> None:
    store.set_policy("instagram", "always", 0, daily_budget=20, operator_reserve_percent=0)
    assert store.policy("instagram").operator_reserve_percent == 0
    store.add_account("instagram", "i1", _cookies("instagram"))
    _quota(engine, "ws_a", "instagram", 100)
    with metering.scoped(A):
        for _ in range(20):
            assert _lease_and_release(store, "instagram") is not None


def test_every_lease_records_one_event_for_its_workspace(store, engine) -> None:
    store.set_policy("tiktok", "always", 0, daily_budget=0)
    store.add_account("tiktok", "t1", _cookies("tiktok"))
    with metering.scoped(A):
        _lease_and_release(store, "tiktok")
    _lease_and_release(store, "tiktok")
    with Session(engine) as session:
        rows = session.execute(
            select(
                UsageEventRow.workspace_id,
                UsageEventRow.workflow_id,
                UsageEventRow.kind,
                UsageEventRow.key,
                UsageEventRow.unit,
            )
        ).all()
    assert sorted(rows, key=str) == sorted(
        [
            ("ws_a", "wf_a", "account_lease", "tiktok", "session"),
            ("ws_bootstrap", None, "account_lease", "tiktok", "session"),
        ],
        key=str,
    )


def test_no_account_writes_no_event(store, engine) -> None:
    store.set_policy("tiktok", "always", 0, daily_budget=0)
    with metering.scoped(A):
        assert store.lease("tiktok") is None
    with Session(engine) as session:
        assert session.scalar(select(func.count()).select_from(UsageEventRow)) == 0


def test_an_empty_pool_is_no_account_not_a_reached_quota(store, engine) -> None:
    store.set_policy("instagram", "always", 0, daily_budget=20)
    _quota(engine, "ws_a", "instagram", 100)
    with metering.scoped(A):
        assert store.lease("instagram") is None  # no account at all: not the workspace's limit
