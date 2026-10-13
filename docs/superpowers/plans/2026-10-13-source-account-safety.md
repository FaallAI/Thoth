# Source Account Safety Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Signed-in sessions stop getting accounts flagged. Concretely:
- platform warnings cool the account;
- each account keeps one encrypted browser profile and one fingerprint;
- each account has a daily budget per platform;
- Camoufox is available as a second engine, chosen per platform.

**Architecture:**
- **Data.** Migration 0009 adds the policy fields (`daily_budget`, `engine`), the account fields (`locale`, `timezone`, `fingerprint_ciphertext`), and a usage table.
  - The store's `lease()` enforces the budget and fills `SessionAccess` with the account's locale, timezone, fingerprint, and engine.
- **Profiles.** A shared async context, `leased_access`, opens the account's encrypted profile into a private directory for the lease and seals it back on release. It is used by the acquisition runner and by discovery's `StoreLeases`.
- **Warnings.** Instagram's warnings map to `DiscoveryReason.CHALLENGE`, then to the `challenge` outcome, then to the existing cooldown ladder.
- **Camoufox.** `CamoufoxSession` serves the sessions that need only `url`, `status`, and `body` (the Instagram reels discovery).

**Tech Stack:**
- Python 3.12, SQLAlchemy ORM over SQLite (tests) and Postgres, editor SQL migrations through Alembic.
- Fernet (the existing vault), Scrapling/Patchright, `camoufox` 0.5.8 (MIT; browser MPL-2.0), `browserforge` 1.2.4 (Apache-2.0).
- FastAPI; React and TypeScript dashboard (bun test).

**Spec:** `docs/superpowers/specs/2026-10-13-source-account-safety-design.md`. Research: `docs/research/2026-10-13-account-safety-research.md`.

## Global Constraints

**Values from the spec:**
- Default daily budgets per account: Instagram 20, TikTok 40, X 30, YouTube 60, Threads 30; `daily_budget = 0` means unlimited; `NULL` means the platform default.
- Instagram `min_spacing_seconds` is at least 600; other platforms keep 60.
- Engine: `patchright` (default) or `camoufox`, per platform.
- Account `locale` defaults to `id-ID`, `timezone` to `Asia/Jakarta`.
- Profiles:
  - stored at `THOTH_ACCOUNT_PROFILE_DIR/<account_id>.profile` (default `/var/lib/thoth/account-profiles`), Fernet-encrypted with the vault key;
  - unpacked into a private mode-0700 temporary directory only during a lease, and removed on release, including on failure;
  - the cache directories `Cache`, `Code Cache`, `GPUCache`, and `Service Worker/CacheStorage` are never archived;
  - an archive over 64 MB drops the remaining large files first.

**Rules:**
- Cookies are injected from the vault on every use; the vault stays the source of truth. An undecryptable profile is discarded with a warning, and a fresh one starts.
- A missing `camoufox` package or browser is an explicit error, `camoufox_missing`, never a skip or a silent fallback (operator rule, 2026-10-11).
- Budget or cooldown exhaustion is "no account", never an error.
- The fingerprint ciphertext never reaches logs, events, artifacts, or the dashboard; the dashboard shows only `fingerprint_set` and a reset. A reset also deletes the profile.
- Logs carry enums only: never an account label, a cookie, a proxy, or a fingerprint value.

**Repository rules:**
- Commits: one `git commit -m "<subject>"` of at most 72 characters, no body, no trailer, no AI attribution.
- Never stage `graphify-out/`, `.superpowers`, `.understand-anything`, `.env.stage1.local*`, `dashboard/dist/`, or `design/`.
- Files with CRLF endings are edited through bytes-level scripts: `compose.stage1.local.yml`, `.env.stage1.local.example`, `Dockerfile`, `CHANGELOG.md`, `python/pyproject.toml`, and the roadmap.
- **Never chain a test run and a commit with `;`.** Run the tests, read the result, then commit.

**Commands:**
- Python tests (run from `python/`):
  `env MSYS_NO_PATHCONV=1 timeout 590 wsl -e bash /mnt/d/thoth-tmp/bu/pt.sh <paths> -p no:warnings`
- Ruff:
  `wsl -e bash -lc 'cd /mnt/c/Users/mfr/Documents/MyTools/CLIPPER/python && ~/.local/bin/uvx ruff check --fix src tests; ~/.local/bin/uvx ruff format src tests; ~/.local/bin/uvx ruff check . -q && echo RUFF_OK'`
- Dashboard tests (run from `dashboard/`): `bun test src/components/SourceAccounts.test.tsx`
- Dashboard build check: `bun run build`
- OpenAPI export, then types: `python scripts/export_openapi.py` (from `python/`), then `bun run generate:control-plane-types` (from `dashboard/`).

## Review Focus

1. **A lease that raises mid-acquisition** must still seal and remove the temporary profile directory, and still release the lease. Pinned in Task 5 (`test_a_failing_attempt_still_seals_and_removes_the_profile`).
2. **Two workers leasing the last budget slot at the same time** must give it to only one. The `uses` increment happens in the same row-locked transaction as the lease. Pinned in Task 2 (`test_the_budget_counts_in_the_lease_transaction`).
3. **A profile archive written by an older or partial run** (truncated, wrong key) must start fresh with a warning, never crash. Pinned in Task 4 (`test_a_truncated_or_foreign_profile_starts_fresh`).
4. **An account deleted while its profile is unpacked** must not leave the archive behind, and must not resurrect it on release. Pinned in Task 5 (`test_a_deleted_account_does_not_get_its_profile_back`).
5. **The UTC day boundary**: uses counted on day N do not count on day N+1. Pinned in Task 2 (`test_the_budget_resets_on_the_next_utc_day`).

---

## File structure

| File | Change | Responsibility |
|---|---|---|
| `python/migrations/editor/0009_source_account_safety.sql`, `python/migrations/editor/alembic/versions/0009_source_account_safety.py` | create | schema |
| `python/src/thoth_control_plane/infrastructure/source_account_models.py` | modify | ORM columns, `SourceAccountUsageRow` |
| `python/src/thoth_control_plane/infrastructure/source_account_store.py` | modify | policy defaults, budget in `lease()`, fingerprint, locale/timezone/engine in `_open`, account updates |
| `python/src/thoth_control_plane/acquisition/accounts/policy.py` | modify | `DEFAULT_DAILY_BUDGETS`, `DEFAULT_SPACING`, `ENGINES` |
| `python/src/thoth_control_plane/acquisition/accounts/access.py` | modify | `SessionAccess` gains `profile_dir`, `locale`, `timezone`, `fingerprint`, `engine`; `browser_kwargs()` |
| `python/src/thoth_control_plane/acquisition/accounts/profiles.py` | create | `AccountProfiles` (seal/unseal/delete), `leased_access` |
| `python/src/thoth_control_plane/acquisition/accounts/fingerprints.py` | create | `new_fingerprint(locale)` via BrowserForge |
| `python/src/thoth_control_plane/acquisition/camoufox_session.py` | create | `CamoufoxSession` |
| `python/src/thoth_control_plane/acquisition/instagram_reels.py` | modify | warnings → `CHALLENGE`; engine-aware session factory |
| `python/src/thoth_control_plane/acquisition/models.py` | modify | `DiscoveryReason.CHALLENGE` |
| `python/src/thoth_control_plane/attribution/adapters/discovery.py` | modify | reason → outcome; `StoreLeases` uses `leased_access` |
| `python/src/thoth_control_plane/acquisition/accounts/runner.py` | modify | uses `leased_access` |
| `python/src/thoth_control_plane/domain/source_accounts.py`, `api/routes/source_accounts.py` | modify | API fields |
| `python/src/thoth_control_plane/config.py`, `worker.py`, `domain/models.py` | modify | `THOTH_ACCOUNT_PROFILE_DIR`, `camoufox_missing` |
| `python/pyproject.toml`, `uv.lock`, `Dockerfile`, `compose.stage1.local.yml`, `.env.stage1.local.example` | modify | packages, browser fetch, volume |
| `dashboard/src/api/source-accounts.ts`, `dashboard/src/components/SourceAccounts.tsx`, `SourceAccountDialogs.tsx`, tests, `src/api/generated/control-plane.ts` | modify | UI |

---

### Task 1: Migration 0009 and the policy defaults

**Files:**
- Create: `python/migrations/editor/0009_source_account_safety.sql`, `python/migrations/editor/alembic/versions/0009_source_account_safety.py`
- Modify: `source_account_models.py`, `acquisition/accounts/policy.py`, `source_account_store.py` (`PolicyView`, `_policy_view`, `set_policy`)
- Test: `tests/operations/test_editor_migrations.py`, `tests/infrastructure/test_source_account_store.py` (locate the store tests with `grep -rl "SourceAccountStore" python/tests`)

**Interfaces:**
- Produces:
  - `policy.DEFAULT_DAILY_BUDGETS: dict[str, int]`;
  - `policy.DEFAULT_SPACING_SECONDS_BY_PLATFORM: dict[str, int]` (Instagram 600);
  - `policy.ENGINES = ("patchright", "camoufox")`;
  - `PolicyView(platform, mode, min_spacing_seconds, daily_budget: int, engine: str)`, where `daily_budget` is effective, never `None`;
  - `store.set_policy(platform, mode, min_spacing_seconds, daily_budget: int | None = None, engine: str = "patchright") -> PolicyView`;
  - ORM `SourceAccountUsageRow(account_id, day, uses)`.

- [ ] **Step 1: Write the failing tests**

In the migration test, append `"0009_source_account_safety.sql"` to the expected `MIGRATION_FILES`, and add:

```python
def test_source_account_safety_adds_budget_engine_profile_fields() -> None:
    sql = " ".join(migration("0009_source_account_safety.sql").split())

    assert "ADD COLUMN daily_budget INTEGER" in sql
    assert "CHECK (engine IN ('patchright', 'camoufox'))" in sql
    assert "ADD COLUMN locale TEXT NOT NULL DEFAULT 'id-ID'" in sql
    assert "ADD COLUMN timezone TEXT NOT NULL DEFAULT 'Asia/Jakarta'" in sql
    assert "fingerprint_ciphertext BYTEA" in sql
    assert "CREATE TABLE source_account_usage" in sql
    assert "REFERENCES source_accounts (id) ON DELETE CASCADE" in sql
    assert "GREATEST(min_spacing_seconds, 600)" in sql
    for clear in ("fingerprint_json", "user_agent", "cookie_value"):
        assert clear not in sql.lower()
```

In the store tests:

```python
def test_policies_default_to_the_platform_budgets_and_patchright(store) -> None:
    views = {view.platform: view for view in store.policies()}

    assert (views["instagram"].daily_budget, views["instagram"].min_spacing_seconds) == (20, 600)
    assert (views["tiktok"].daily_budget, views["x"].daily_budget) == (40, 30)
    assert {view.engine for view in views.values()} == {"patchright"}


def test_a_policy_stores_budget_and_engine(store) -> None:
    view = store.set_policy("instagram", "fallback", 900, daily_budget=5, engine="camoufox")

    assert (view.daily_budget, view.engine, view.min_spacing_seconds) == (5, "camoufox", 900)
    assert store.set_policy("instagram", "fallback", 900, daily_budget=None).daily_budget == 20
```

- [ ] **Step 2: Run them; expect failures** (missing file; `PolicyView` has no `daily_budget`).

- [ ] **Step 3: Implement**

`0009_source_account_safety.sql`:

```sql
-- Source account safety (spec 2026-10-13): a daily budget and a browser engine per platform,
-- and per account a locale, a timezone, a sealed fingerprint, and a daily usage count.
-- NULL daily_budget means the platform default; 0 means unlimited.

ALTER TABLE source_account_policies ADD COLUMN daily_budget INTEGER
    CHECK (daily_budget IS NULL OR daily_budget BETWEEN 0 AND 100000);
ALTER TABLE source_account_policies ADD COLUMN engine TEXT NOT NULL DEFAULT 'patchright'
    CHECK (engine IN ('patchright', 'camoufox'));
UPDATE source_account_policies
    SET min_spacing_seconds = GREATEST(min_spacing_seconds, 600)
    WHERE platform = 'instagram';

ALTER TABLE source_accounts ADD COLUMN locale TEXT NOT NULL DEFAULT 'id-ID'
    CHECK (locale ~ '^[a-z]{2,3}-[A-Z]{2}$');
ALTER TABLE source_accounts ADD COLUMN timezone TEXT NOT NULL DEFAULT 'Asia/Jakarta'
    CHECK (char_length(timezone) BETWEEN 3 AND 64);
ALTER TABLE source_accounts ADD COLUMN fingerprint_ciphertext BYTEA;

CREATE TABLE source_account_usage (
    account_id UUID NOT NULL REFERENCES source_accounts (id) ON DELETE CASCADE,
    day DATE NOT NULL,
    uses INTEGER NOT NULL DEFAULT 0 CHECK (uses >= 0),
    PRIMARY KEY (account_id, day)
);
```

The Alembic revision follows the 0008 pattern: `revision = "0009"`, `down_revision = "0008"`, and `upgrade()` calls `execute_sql_file(__file__)`.

ORM:
- `SourceAccountPolicyRow` gains `daily_budget: Mapped[int | None]` (nullable) and `engine: Mapped[str] = mapped_column(String, default="patchright")`.
- `SourceAccountRow` gains `locale: Mapped[str]` (default `"id-ID"`), `timezone: Mapped[str]` (default `"Asia/Jakarta"`), and `fingerprint_ciphertext: Mapped[bytes | None]`.
- New `SourceAccountUsageRow` with `__tablename__ = "source_account_usage"`, `account_id` (`Uuid`, `ForeignKey("source_accounts.id", ondelete="CASCADE")`, primary key), `day` (`Date`, primary key), `uses` (`Integer`, default 0).

`policy.py`:

```python
DEFAULT_DAILY_BUDGETS = {"instagram": 20, "tiktok": 40, "x": 30, "youtube": 60, "threads": 30}
DEFAULT_SPACING_SECONDS_BY_PLATFORM = {"instagram": 600}
ENGINES = ("patchright", "camoufox")
```

Store:
- `_policy_view` resolves `daily_budget = row.daily_budget if row and row.daily_budget is not None else DEFAULT_DAILY_BUDGETS.get(platform, 0)`.
- Spacing comes from the row, else `DEFAULT_SPACING_SECONDS_BY_PLATFORM.get(platform, DEFAULT_SPACING_SECONDS)`.
- `engine = row.engine if row else "patchright"`.
- `set_policy` stores all four values, and rejects an engine not in `ENGINES` with `ValueError`.

- [ ] **Step 4: Run the store and migration tests; expect them to pass.** Also run `tests/operations/test_editor_migrations_postgres.py` with the disposable Postgres if it is available locally; it skips today when none is. Record the run in the ledger.

- [ ] **Step 5: Commit** — `feat(accounts): budget, engine, and profile fields (migration 0009)`

---

### Task 2: The daily budget in `lease()`

**Files:** Modify `source_account_store.py` (`lease`, `AccountView`); Test the store tests.

**Interfaces:**
- Produces:
  - `lease()` returns `None` when every eligible account reached `policy.daily_budget` (unless the budget is 0, meaning unlimited) for the current UTC day;
  - a returned lease increments `SourceAccountUsageRow.uses` for that day in the same transaction;
  - `AccountView` gains `uses_today: int`, `locale: str`, `timezone: str`, `fingerprint_set: bool`.

- [ ] **Step 1: Write the failing tests**

```python
def test_an_account_over_its_daily_budget_is_not_leased(store, clock) -> None:
    store.set_policy("instagram", "fallback", 0, daily_budget=2)
    account = _add(store, "instagram")  # the file's existing helper that adds an account

    for _ in range(2):
        lease = store.lease("instagram")
        assert lease is not None
        store.report(lease.account_id, "success", lease.leased_until)
    assert store.lease("instagram") is None
    assert store.account(account.id).uses_today == 2


def test_the_budget_resets_on_the_next_utc_day(store, clock) -> None:
    store.set_policy("instagram", "fallback", 0, daily_budget=1)
    _add(store, "instagram")
    first = store.lease("instagram")
    store.report(first.account_id, "success", first.leased_until)
    clock.advance(timedelta(days=1))  # the file's clock fixture

    assert store.lease("instagram") is not None


def test_a_zero_budget_is_unlimited(store, clock) -> None:
    store.set_policy("instagram", "fallback", 0, daily_budget=0)
    _add(store, "instagram")
    for _ in range(30):
        lease = store.lease("instagram")
        assert lease is not None
        store.report(lease.account_id, "success", lease.leased_until)


def test_the_budget_counts_in_the_lease_transaction(store, clock) -> None:
    # Review focus 2: the increment rides the row-locked lease, so a second lease in the same
    # instant sees it.
    store.set_policy("instagram", "fallback", 0, daily_budget=1)
    _add(store, "instagram")
    _add(store, "instagram", label="second")

    first, second = store.lease("instagram"), store.lease("instagram")

    assert first is not None and second is not None and first.account_id != second.account_id
    assert store.lease("instagram") is None
```

Read the existing store tests first, and adapt `_add` and `clock` to their real helper names.

- [ ] **Step 2: Run; expect failures.**

- [ ] **Step 3: Implement**

In `lease()`, compute `today = now.date()` (UTC) and `budget = self.policy(platform).daily_budget`. When `budget > 0`, add to the `where` clause:

```python
~SourceAccountRow.id.in_(
    select(SourceAccountUsageRow.account_id).where(
        SourceAccountUsageRow.day == today, SourceAccountUsageRow.uses >= budget
    )
),
```

After `row` is chosen and `access` opened, increment usage in the same session:

```python
usage = session.get(SourceAccountUsageRow, (row.id, today))
if usage is None:
    session.add(SourceAccountUsageRow(account_id=row.id, day=today, uses=1))
else:
    usage.uses += 1
```

`_account_view` fills `uses_today`, read with the view's session for today's row (0 when absent), plus `locale`, `timezone`, and `fingerprint_set = row.fingerprint_ciphertext is not None`.

- [ ] **Step 4: Run; expect them to pass, and the existing store tests to stay green.** Commit — `feat(accounts): a daily lease budget per account`

---

### Task 3: Platform warnings cool the account

**Files:**
- Modify: `acquisition/models.py` (`DiscoveryReason.CHALLENGE = "challenge"`), `acquisition/instagram_reels.py`, `attribution/adapters/discovery.py`
- Test: `tests/acquisition/test_instagram_reels.py`, `tests/attribution/test_discovery.py`

**Interfaces:**
- Produces:
  - `instagram_reels.WARNING_PATHS = ("/challenge/", "/accounts/suspended/")` and `WARNING_MARKERS = (b"feedback_required", b"checkpoint_required", b'"spam":true')`;
  - `discover()` returns `_empty("profile", DiscoveryReason.CHALLENGE)` on a warning;
  - `ProfileDiscoverer` reports outcome `"challenge"` for `CHALLENGE` or `CAPTCHA`, `"blocked"` for `BLOCKED`, `"success"` for videos.

- [ ] **Step 1: Write the failing tests**

```python
@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("final_url", "body"),
    [
        (f"https://www.instagram.com/challenge/?next=/{HANDLE}/reels/", None),
        (f"https://www.instagram.com/accounts/suspended/", None),
        (None, b'{"message":"feedback_required","spam":true,"status":"fail"}'),
        (None, b'{"message":"checkpoint_required"}'),
    ],
)
async def test_an_instagram_warning_is_a_challenge(final_url, body) -> None:
    bodies = [body] if body is not None else BODIES
    session = _Session(bodies, final_url=final_url or f"https://www.instagram.com/{HANDLE}/reels/")

    result = await _discovery(session).discover(ProfileDiscovery(handle=HANDLE, limit=30))

    assert (result.videos, result.reason) == ([], DiscoveryReason.CHALLENGE)
```

In `tests/attribution/test_discovery.py`, use the existing `FakeDiscovery` and `FakeLeases`:

```python
@pytest.mark.asyncio
async def test_a_challenge_cools_the_account() -> None:
    fake = FakeDiscovery(CAPTCHA, _result([], DiscoveryReason.CHALLENGE))
    leases = FakeLeases("fallback")

    with pytest.raises(DiscoveryBlocked):
        await _discover(fake, leases)
    assert leases.released == ["challenge"]
```

A challenge with no videos must surface as blocked to the caller. If today's code raises `DiscoveryBlocked` only for the anonymous captcha path, add `CHALLENGE` to the reasons `_videos` raises for, and record that in the ledger.

- [ ] **Step 2: Run; expect failures.**

- [ ] **Step 3: Implement**

In `InstagramReelsDiscovery.discover()`, after `fetch`, before the login check:

```python
path = urlsplit(str(getattr(page, "url", ""))).path
if any(path.startswith(marker) for marker in WARNING_PATHS) or any(
    marker in body for body in bodies for marker in WARNING_MARKERS
):
    logger.warning("instagram warned the session; the account cools down")
    return _empty("profile", DiscoveryReason.CHALLENGE)
```

Only GraphQL bodies are collected today. Also collect any response whose URL contains `/api/` or `/graphql`, so a `feedback_required` JSON is seen, and keep `parse_reels` reading only the `clips_connection` ones.

In `ProfileDiscoverer.discover()`, the outcome is chosen as:

```python
if result.videos:
    outcome = "success"
elif result.reason in (DiscoveryReason.CHALLENGE, DiscoveryReason.CAPTCHA):
    outcome = "challenge"
elif result.reason in RETRY_REASONS:
    outcome = "blocked"
```

`RETRY_REASONS` gains `DiscoveryReason.CHALLENGE`.

- [ ] **Step 4: Run; expect them to pass.** Commit — `feat(accounts): Instagram warnings cool the account down`

---

### Task 4: Encrypted browser profiles

**Files:** Create `acquisition/accounts/profiles.py`; Test `tests/acquisition/accounts/test_profiles.py`.

**Interfaces:**
- Produces:
  - `AccountProfiles(vault: Vault, root: Path, *, max_bytes: int = 64 * 2**20)`;
  - `.unseal(account_id: str) -> Path`: a new private temporary directory, filled from the archive when one exists and opens;
  - `.seal(account_id: str, directory: Path) -> None`: archives the directory without caches, encrypts it, writes it atomically, then removes the directory;
  - `.discard(directory: Path) -> None`: removes a directory without saving;
  - `.delete(account_id: str) -> None`: removes the archive;
  - `PRUNED = ("Cache", "Code Cache", "GPUCache", "Service Worker/CacheStorage")`.

- [ ] **Step 1: Write the failing tests**

```python
"""Encrypted per-account browser profiles (spec 3.2)."""

from __future__ import annotations

import stat
from pathlib import Path

import pytest
from cryptography.fernet import Fernet

from thoth_control_plane.acquisition.accounts.profiles import AccountProfiles
from thoth_control_plane.infrastructure.vault import Vault  # adjust to the vault's module

ACCOUNT = "4f6c7d1e-0000-4000-8000-000000000001"


def _profiles(tmp_path: Path, **kwargs) -> AccountProfiles:
    return AccountProfiles(Vault(Fernet.generate_key()), tmp_path / "profiles", **kwargs)


def test_a_profile_round_trips_without_its_caches(tmp_path: Path) -> None:
    profiles = _profiles(tmp_path)
    directory = profiles.unseal(ACCOUNT)
    assert stat.S_IMODE(directory.stat().st_mode) == 0o700
    (directory / "Default").mkdir()
    (directory / "Default" / "Local Storage").write_text("device-id")
    (directory / "Default" / "Cache").mkdir()
    (directory / "Default" / "Cache" / "blob").write_bytes(b"x" * 1000)

    profiles.seal(ACCOUNT, directory)
    assert not directory.exists()
    archive = tmp_path / "profiles" / f"{ACCOUNT}.profile"
    assert b"device-id" not in archive.read_bytes()  # encrypted at rest

    again = profiles.unseal(ACCOUNT)
    assert (again / "Default" / "Local Storage").read_text() == "device-id"
    assert not (again / "Default" / "Cache").exists()


def test_a_truncated_or_foreign_profile_starts_fresh(tmp_path: Path, caplog) -> None:
    profiles = _profiles(tmp_path)
    (tmp_path / "profiles").mkdir()
    (tmp_path / "profiles" / f"{ACCOUNT}.profile").write_bytes(b"not a profile")

    with caplog.at_level("WARNING"):
        directory = profiles.unseal(ACCOUNT)

    assert list(directory.iterdir()) == []
    assert "profile" in caplog.text


def test_an_oversized_profile_is_cut_to_the_cap(tmp_path: Path) -> None:
    profiles = _profiles(tmp_path, max_bytes=10_000)
    directory = profiles.unseal(ACCOUNT)
    (directory / "keep").write_text("small")
    (directory / "huge.bin").write_bytes(b"x" * 50_000)

    profiles.seal(ACCOUNT, directory)

    again = profiles.unseal(ACCOUNT)
    assert (again / "keep").exists() and not (again / "huge.bin").exists()


def test_delete_removes_the_archive(tmp_path: Path) -> None:
    profiles = _profiles(tmp_path)
    profiles.seal(ACCOUNT, profiles.unseal(ACCOUNT))
    profiles.delete(ACCOUNT)

    assert not (tmp_path / "profiles" / f"{ACCOUNT}.profile").exists()
```

- [ ] **Step 2: Run; expect `ModuleNotFoundError`.**

- [ ] **Step 3: Implement**

```python
"""Encrypted per-account browser profiles (spec 2026-10-13, section 3.2).

A profile keeps an account looking like one returning device: local storage and device ids
survive between leases. At rest it is a tar archive sealed with the vault key; it is unpacked
into a private directory only while the account is leased. Cookies still come from the vault.
"""

from __future__ import annotations

import io
import logging
import os
import shutil
import tarfile
import tempfile
from pathlib import Path

from thoth_control_plane.infrastructure.vault import Vault, VaultError  # adjust to the real module

logger = logging.getLogger(__name__)
PRUNED = ("Cache", "Code Cache", "GPUCache", "Service Worker/CacheStorage")
MAX_BYTES = 64 * 2**20


class AccountProfiles:
    def __init__(self, vault: Vault, root: Path, *, max_bytes: int = MAX_BYTES) -> None:
        self._vault, self._root, self._max = vault, root, max_bytes

    def _archive(self, account_id: str) -> Path:
        return self._root / f"{account_id}.profile"

    def unseal(self, account_id: str) -> Path:
        directory = Path(tempfile.mkdtemp(prefix="thoth-profile-"))
        os.chmod(directory, 0o700)
        archive = self._archive(account_id)
        if archive.is_file():
            try:
                data = self._vault.open_bytes(archive.read_bytes())
                with tarfile.open(fileobj=io.BytesIO(data), mode="r:gz") as tar:
                    tar.extractall(directory, filter="data")
            except (VaultError, tarfile.TarError, OSError, ValueError):
                logger.warning("account profile unreadable; a fresh profile starts")
                shutil.rmtree(directory, ignore_errors=True)
                directory.mkdir(mode=0o700)
        return directory

    def seal(self, account_id: str, directory: Path) -> None:
        try:
            files = sorted(
                (path for path in directory.rglob("*") if path.is_file() and not _pruned(path, directory)),
                key=lambda path: path.stat().st_size,
            )
            total, kept = 0, []
            for path in files:  # smallest first, so the cap drops the largest files
                size = path.stat().st_size
                if total + size > self._max:
                    continue
                total += size
                kept.append(path)
            buffer = io.BytesIO()
            with tarfile.open(fileobj=buffer, mode="w:gz") as tar:
                for path in kept:
                    tar.add(path, arcname=str(path.relative_to(directory)))
            self._root.mkdir(parents=True, exist_ok=True)
            target = self._archive(account_id)
            partial = target.with_suffix(".part")
            partial.write_bytes(self._vault.seal_bytes(buffer.getvalue()))
            os.replace(partial, target)
        except OSError:
            logger.warning("account profile could not be saved; the next lease starts fresh")
        finally:
            self.discard(directory)

    @staticmethod
    def discard(directory: Path) -> None:
        shutil.rmtree(directory, ignore_errors=True)

    def delete(self, account_id: str) -> None:
        self._archive(account_id).unlink(missing_ok=True)


def _pruned(path: Path, root: Path) -> bool:
    relative = path.relative_to(root).as_posix()
    return any(f"/{name}/" in f"/{relative}" for name in PRUNED)
```

Read `infrastructure/vault.py` first: if it exposes only `seal(str)` and `open(bytes) -> str`, add `seal_bytes` and `open_bytes` beside them with the same Fernet, and record that in the ledger.

- [ ] **Step 4: Run; expect them to pass.** Commit — `feat(accounts): encrypted per-account browser profiles`

---

### Task 5: Leased access carries the profile, locale, timezone, fingerprint, and engine

**Files:**
- Create: `acquisition/accounts/fingerprints.py`
- Modify: `acquisition/accounts/access.py`, `source_account_store.py` (`_open`, fingerprint generation, `update_account`), `acquisition/accounts/profiles.py` (`leased_access`), `acquisition/accounts/runner.py`, `attribution/adapters/discovery.py` (`StoreLeases`)
- Test: `tests/acquisition/accounts/test_profiles.py`, the store tests, `tests/acquisition/accounts/test_runner.py` (locate with grep), `tests/attribution/test_discovery.py`

**Interfaces:**
- Produces:
  - `SessionAccess(cookies, proxy=None, *, profile_dir: Path | None = None, locale: str = "id-ID", timezone: str = "Asia/Jakarta", fingerprint: dict | None = None, engine: str = "patchright")`, still frozen; `__repr__` unchanged (no secrets);
  - `SessionAccess.browser_kwargs()` adds:
    - `user_data_dir=str(profile_dir)` when set;
    - `locale=locale`, `timezone_id=timezone`;
    - `useragent=fingerprint["navigator"]["userAgent"]` when a fingerprint exists;
  - `fingerprints.new_fingerprint(locale: str) -> dict`: BrowserForge `FingerprintGenerator(browser="chrome", os=("windows", "macos"), locale=locale)`, serialized to plain JSON-safe types;
  - the store's `_open()` builds `SessionAccess` with the row's locale and timezone, the platform policy's engine, and the fingerprint. When `fingerprint_ciphertext` is NULL, it generates one with `new_fingerprint(row.locale)` and stores it sealed in the same transaction;
  - `store.update_account(..., locale=None, timezone=None, reset_fingerprint=False)`. A reset sets `fingerprint_ciphertext = None`, and the route also deletes the profile;
  - `profiles.leased_access(profiles: AccountProfiles | None, lease: AccountLease)`: an async context manager yielding the lease's `SessionAccess` with `profile_dir` set. It unseals before and seals after, including on exceptions. With `profiles is None` it yields `lease.access` unchanged;
  - `account_runner(store, acquire, profiles: AccountProfiles | None = None)` and `StoreLeases(store, profiles: AccountProfiles | None = None)`: both lease through `leased_access`. `StoreLeases.lease()` returns an `AccountLease` whose `access` already has `profile_dir`; `release()` seals it.

- [ ] **Step 1: Write the failing tests**

```python
def test_browser_kwargs_carry_profile_locale_timezone_and_agent(tmp_path: Path) -> None:
    access = SessionAccess(
        COOKIES,  # the access tests' cookie fixture
        None,
        profile_dir=tmp_path,
        locale="id-ID",
        timezone="Asia/Jakarta",
        fingerprint={"navigator": {"userAgent": "Mozilla/5.0 test"}},
    )

    kwargs = access.browser_kwargs()

    assert kwargs["user_data_dir"] == str(tmp_path)
    assert (kwargs["locale"], kwargs["timezone_id"]) == ("id-ID", "Asia/Jakarta")
    assert kwargs["useragent"] == "Mozilla/5.0 test"
    assert "Mozilla" not in repr(access) and str(tmp_path) not in repr(access)


@pytest.mark.asyncio
async def test_a_failing_attempt_still_seals_and_removes_the_profile(tmp_path: Path) -> None:
    profiles = _profiles(tmp_path)
    lease = AccountLease(ACCOUNT, "instagram", SessionAccess(COOKIES), NOW)
    seen: list[Path] = []

    with pytest.raises(RuntimeError):
        async with leased_access(profiles, lease) as access:
            seen.append(access.profile_dir)
            (access.profile_dir / "state").write_text("kept")
            raise RuntimeError("acquisition crashed")

    assert not seen[0].exists()
    async with leased_access(profiles, lease) as again:
        assert (again.profile_dir / "state").read_text() == "kept"


@pytest.mark.asyncio
async def test_a_deleted_account_does_not_get_its_profile_back(tmp_path: Path) -> None:
    profiles = _profiles(tmp_path)
    lease = AccountLease(ACCOUNT, "instagram", SessionAccess(COOKIES), NOW)

    async with leased_access(profiles, lease) as access:
        (access.profile_dir / "state").write_text("x")
        profiles.delete(ACCOUNT)
        profiles.mark_deleted(ACCOUNT)  # the route calls this beside delete()

    assert not (tmp_path / "profiles" / f"{ACCOUNT}.profile").exists()


def test_a_leased_account_gets_one_lasting_fingerprint(store) -> None:
    account = _add(store, "instagram")
    first = store.lease("instagram")
    store.report(first.account_id, "success", first.leased_until)
    second = store.lease("instagram")

    assert first.access.fingerprint and first.access.fingerprint == second.access.fingerprint
    assert store.account(account.id).fingerprint_set
```

The deleted-account test requires `AccountProfiles.mark_deleted(account_id)`. It records the id in a small in-process set, and `seal()` then discards the directory instead of writing the archive. Add it to the Task 4 class in this task, and record a ruling: the spec's "deleting an account deletes its profile" needs it whenever the delete happens while a lease is open.

- [ ] **Step 2: Run; expect failures.**

- [ ] **Step 3: Implement**

`leased_access`:

```python
@contextlib.asynccontextmanager
async def leased_access(
    profiles: AccountProfiles | None, lease: AccountLease
) -> AsyncIterator[SessionAccess]:
    if profiles is None:
        yield lease.access
        return
    directory = await asyncio.to_thread(profiles.unseal, lease.account_id)
    try:
        yield dataclasses.replace(lease.access, profile_dir=directory)
    finally:
        await asyncio.to_thread(profiles.seal, lease.account_id, directory)
```

The runner wraps `attempt(lease.access)` as `async with leased_access(profiles, lease) as access: result = await attempt(access)`. `StoreLeases` keeps a dict from account id to the open directory: `lease()` unseals and returns the lease with the profile set, and `release()` seals.

`fingerprints.py` serializes BrowserForge's `Fingerprint` with `dataclasses.asdict`, keeping JSON-safe values only. The store seals it with the vault as JSON text.

`worker.py`, `activities/source_investigation.py`, and `activities/source_attribution.py` build `AccountProfiles(vault, settings.THOTH_ACCOUNT_PROFILE_DIR)` wherever they build the store (`_account_store`), and pass it to `account_runner` and `StoreLeases`.

- [ ] **Step 4: Run the accounts, store, runner, discovery, and activities tests; expect them to pass.** Commit — `feat(accounts): leased sessions keep a profile and a fingerprint`

---

### Task 6: Camoufox as a second engine

**Files:**
- Create: `acquisition/camoufox_session.py`
- Modify: `acquisition/instagram_reels.py` (engine-aware default factory), `worker.py` (start check), `domain/models.py` (`camoufox_missing` in `ATTRIBUTION_REASONS`), `python/pyproject.toml` and `uv.lock` (`camoufox==0.5.8`, `browserforge>=1.2,<2`), `Dockerfile`, `D:/thoth-tmp/bu/pt.sh` (adds `--with camoufox==0.5.8 --with browserforge`)
- Test: `tests/acquisition/test_camoufox_session.py`, `tests/acquisition/test_instagram_reels.py`, `tests/test_worker.py`, `tests/domain/test_attribution_events.py`

**Interfaces:**
- Produces:
  - `CamoufoxSession(**kwargs)`: an async context manager. `fetch(url, *, page_setup=None, page_action=None, timeout=90_000) -> SimpleNamespace(url, status, body)`;
  - the kwargs it reads: `headless`, `proxy`, `cookies` (Playwright form), `user_data_dir`, `locale`, `timezone_id`, `fingerprint`;
  - a missing package raises `ToolMissing("camoufox_missing")`;
  - `InstagramReelsDiscovery` picks `CamoufoxSession` when `access.engine == "camoufox"` and no `session_factory` is injected.

- [ ] **Step 1: Write the failing tests**

```python
"""Camoufox as a Scrapling-shaped session for signed-in discovery (spec 3.4)."""

from __future__ import annotations

import sys
from types import SimpleNamespace
from typing import Any

import pytest

from thoth_control_plane.acquisition.camoufox_session import CamoufoxSession


class _Page:
    def __init__(self) -> None:
        self.url = "https://www.instagram.com/x/reels/"
        self.handlers: list[Any] = []

    def on(self, event: str, handler: Any) -> None:
        self.handlers.append(handler)

    async def goto(self, url: str, timeout: int) -> SimpleNamespace:
        self.url = url
        return SimpleNamespace(status=200)

    async def content(self) -> str:
        return "<html></html>"


class _Context:
    def __init__(self) -> None:
        self.cookies: list[dict] = []
        self.page = _Page()

    async def add_cookies(self, cookies: list[dict]) -> None:
        self.cookies += cookies

    async def new_page(self) -> _Page:
        return self.page

    async def close(self) -> None:
        return None


class _Camoufox:
    seen: dict[str, Any] = {}

    def __init__(self, **kwargs: Any) -> None:
        _Camoufox.seen = kwargs
        self.context = _Context()

    async def __aenter__(self) -> _Context:
        return self.context

    async def __aexit__(self, *exc: object) -> None:
        return None


@pytest.mark.asyncio
async def test_a_page_runs_setup_and_action_in_a_persistent_profile(
    monkeypatch: pytest.MonkeyPatch, tmp_path
) -> None:
    import thoth_control_plane.acquisition.camoufox_session as module

    monkeypatch.setattr(module, "_camoufox", lambda: _Camoufox)
    steps: list[str] = []

    async def setup(page: Any) -> None:
        steps.append("setup")

    async def action(page: Any) -> Any:
        steps.append("action")
        return page

    async with CamoufoxSession(
        headless=True,
        cookies=[{"name": "sessionid", "value": "s", "domain": ".instagram.com", "path": "/"}],
        user_data_dir=str(tmp_path),
        locale="id-ID",
        timezone_id="Asia/Jakarta",
        fingerprint={"navigator": {"userAgent": "UA"}},
    ) as session:
        result = await session.fetch(
            "https://www.instagram.com/x/reels/", page_setup=setup, page_action=action
        )

    assert steps == ["setup", "action"]
    assert (result.status, result.url) == (200, "https://www.instagram.com/x/reels/")
    assert _Camoufox.seen["persistent_context"] is True
    assert _Camoufox.seen["user_data_dir"] == str(tmp_path)
    assert _Camoufox.seen["locale"] == "id-ID"


@pytest.mark.asyncio
async def test_without_camoufox_the_session_is_tool_missing(monkeypatch: pytest.MonkeyPatch) -> None:
    from thoth_control_plane.attribution.adapters.frames import ToolMissing

    monkeypatch.setitem(sys.modules, "camoufox", None)
    monkeypatch.setitem(sys.modules, "camoufox.async_api", None)

    with pytest.raises(ToolMissing) as raised:
        async with CamoufoxSession(headless=True):
            pass
    assert raised.value.code == "camoufox_missing"
```

Also:
- `test_worker.py`: `("camoufox", "camoufox_missing")` joins the `find_spec` parametrization.
- `test_attribution_events.py`: `"camoufox_missing"` joins `CODES`.
- `test_instagram_reels.py`: an access with `engine="camoufox"` makes `InstagramReelsDiscovery(access)._session_factory is CamoufoxSession`.

- [ ] **Step 2: Run; expect failures.**

- [ ] **Step 3: Implement**

```python
"""Camoufox (Firefox patched at the C level) shaped like the Scrapling sessions we use.

Spec 2026-10-13, section 3.4: only the sessions that need `url`, `status`, and `body` use
it (signed-in Instagram reels discovery). The account's BrowserForge fingerprint, profile,
locale, and timezone stay the same on every visit.
"""

from __future__ import annotations

from types import SimpleNamespace
from typing import Any

from thoth_control_plane.attribution.adapters.frames import ToolMissing


def _camoufox() -> Any:
    try:
        from camoufox.async_api import AsyncCamoufox
    except ImportError:
        raise ToolMissing("camoufox_missing") from None
    return AsyncCamoufox


class CamoufoxSession:
    def __init__(self, **kwargs: Any) -> None:
        self._kwargs = kwargs
        self._manager: Any = None
        self._context: Any = None

    async def __aenter__(self) -> CamoufoxSession:
        options: dict[str, Any] = {
            "headless": self._kwargs.get("headless", True),
            "persistent_context": True,
            "user_data_dir": self._kwargs.get("user_data_dir"),
            "locale": self._kwargs.get("locale"),
            "geoip": False,
        }
        if self._kwargs.get("proxy"):
            options["proxy"] = self._kwargs["proxy"]
        if self._kwargs.get("fingerprint"):
            options["fingerprint"] = self._kwargs["fingerprint"]
        if self._kwargs.get("timezone_id"):
            options["config"] = {"timezone": self._kwargs["timezone_id"]}
        self._manager = _camoufox()(**{k: v for k, v in options.items() if v is not None})
        self._context = await self._manager.__aenter__()
        if self._kwargs.get("cookies"):
            await self._context.add_cookies(self._kwargs["cookies"])
        return self

    async def __aexit__(self, *exc: object) -> None:
        await self._manager.__aexit__(*exc)

    async def fetch(
        self, url: str, *, page_setup: Any = None, page_action: Any = None, timeout: int = 90_000
    ) -> SimpleNamespace:
        page = await self._context.new_page()
        if page_setup is not None:
            await page_setup(page)
        response = await page.goto(url, timeout=timeout)
        if page_action is not None:
            await page_action(page)
        return SimpleNamespace(
            url=page.url,
            status=getattr(response, "status", None),
            body=(await page.content()).encode(),
        )
```

Read the installed `camoufox` 0.5.8 API (`AsyncCamoufox` keyword names: `persistent_context`, `user_data_dir`, `fingerprint`, `locale`, `proxy`, `config`) from its package source before coding, and adjust the option names to it. Record the actual names in the ledger.

Dockerfile, after the speech models:

```dockerfile
RUN /opt/thoth/python/.venv/bin/python -m camoufox fetch \
    && chown -R thoth:thoth /home/thoth
```

Run it as the `thoth` user (or set `HOME` so the browser lands in `/home/thoth/.cache/camoufox`). Add `camoufox, browserforge` to the import check, and `test -d /home/thoth/.cache/camoufox` to the `USER thoth` block.

The worker start check: with attribution on, `find_spec("camoufox") is None` → `SettingsValidationError("camoufox_missing")`.

- [ ] **Step 4: Run the tests; then run actionlint and the deployment contract tests.** Commit — `feat(acquisition): Camoufox as a second signed-in engine`

---

### Task 7: API fields and the profile lifecycle in routes

**Files:**
- Modify: `domain/source_accounts.py`, `api/routes/source_accounts.py`, `config.py` (`THOTH_ACCOUNT_PROFILE_DIR: Path = Path("/var/lib/thoth/account-profiles")`)
- Regenerate: `python/openapi.json` (`python scripts/export_openapi.py`)
- Test: `tests/api/test_source_accounts.py` (locate with grep)

**Interfaces:**
- Produces:
  - `PlatformAccounts` gains `daily_budget: int` and `engine: Literal["patchright", "camoufox"]`;
  - `AccessPolicyUpdate` gains `daily_budget: int | None = None` (0–100000) and `engine: Literal["patchright", "camoufox"] = "patchright"`;
  - `SourceAccount` gains `locale: str`, `timezone: str`, `fingerprint_set: bool`, `uses_today: int`;
  - `SourceAccountUpdate` gains `locale: str | None` (pattern `^[a-z]{2,3}-[A-Z]{2}$`), `timezone: str | None` (3–64 characters, validated with `zoneinfo.ZoneInfo`), and `reset_fingerprint: bool = False`;
  - `DELETE /source-accounts/{id}` and a reset call `profiles.mark_deleted(id)` and `profiles.delete(id)`. The routes build `AccountProfiles` from the app's vault and `THOTH_ACCOUNT_PROFILE_DIR`.

- [ ] **Step 1: Write the failing tests** in the routes' existing style:
  - PUT a policy with `daily_budget=5, engine="camoufox"`, and the overview shows them;
  - an invalid engine answers 422;
  - PATCH an account's `locale` and `timezone`; an invalid timezone answers 422;
  - `reset_fingerprint` gives `fingerprint_set` false and removes the profile archive;
  - DELETE removes the profile archive;
  - no response contains the fingerprint JSON (assert `"userAgent" not in response.text`).
- [ ] **Step 2: Run; expect failures. Step 3: Implement. Step 4: Run; then export the OpenAPI document and commit** — `feat(api): budget, engine, locale, and fingerprint reset for accounts`

---

### Task 8: Dashboard

**Files:**
- Modify: `dashboard/src/api/source-accounts.ts` (types and `setPolicy` payload), `dashboard/src/components/SourceAccounts.tsx` (the access card gains "Daily budget" and "Engine"; the table gains "Today"), `dashboard/src/components/SourceAccountDialogs.tsx` (the edit dialog gains locale, timezone, and "Reset device fingerprint"), `src/api/generated/control-plane.ts` (`bun run generate:control-plane-types`)
- Test: `dashboard/src/components/SourceAccounts.test.tsx`

**Interfaces:** `client.setPolicy(platform, { mode, min_spacing_seconds, daily_budget, engine })` and `client.update(id, { locale?, timezone?, reset_fingerprint? })`.

- [ ] **Step 1: Write failing tests** in the file's existing style:
  - the access card shows the budget and the engine, and saving the budget sends `daily_budget`;
  - choosing Camoufox sends `engine: "camoufox"`;
  - the table shows `uses_today` against the budget (for example "3 / 20");
  - the edit dialog sends `locale` and `timezone`;
  - "Reset device fingerprint" asks for confirmation, then sends `reset_fingerprint: true`.
- [ ] **Step 2: Run `bun test src/components/SourceAccounts.test.tsx`; expect failures.**
- [ ] **Step 3: Implement.** Follow `AccessCard`'s spacing input for the budget: a numeric input committed on blur or Enter, valid from 0 to 100000, where 0 means unlimited and the hint says so. Use a two-option segmented radio group for the engine, with arrow keys, like the mode group.
- [ ] **Step 4: Run the tests and `bun run build`; expect both green.** Commit — `feat(dashboard): account budgets, engines, and device fingerprints`

---

### Task 9: Deployment wiring

**Files:**
- Modify: `compose.stage1.local.yml` (CRLF): a named volume `account-profiles`, mounted at `/var/lib/thoth/account-profiles` in `api` and `worker`;
- Modify: `Dockerfile` (CRLF): `mkdir -p /var/lib/thoth/account-profiles`, owned by `thoth`, and `test -w` in the `USER thoth` block;
- Modify: `.env.stage1.local.example` (CRLF): a commented `# THOTH_ACCOUNT_PROFILE_DIR=/var/lib/thoth/account-profiles`.
- Test: `tests/deployment/test_container_contract.py` (volume mounted in both services; directory writable).

- [ ] **Step 1: Write the failing contract test. Step 2: Run; expect it to fail. Step 3: Edit with bytes-level scripts. Step 4: Run the deployment tests and actionlint (container). Commit** — `build: an account-profiles volume for api and worker`

---

### Task 10: Live gates and documentation

- [ ] **Step 1: HARD STOP — the operator's gate for the fingerprint comparison.**
  1. With one Instagram account, open CreepJS and BrowserScan through the capture container, once with Patchright and once with Camoufox, each with the account's profile, fingerprint, and proxy.
  2. Record the trust and lie scores in the CHANGELOG.
  3. The operator decides whether Instagram's policy moves to Camoufox.
- [ ] **Step 2: HARD STOP — the operator's gate for the recapture.** Recapture `instagram_deWlWJmyKxP`, `instagram_deOUJ60SHeI`, and `instagram_deHz54GT4ea`, 10 minutes apart, with the reels listing (plan `2026-10-13-stage4-reaction-attribution.md`, Task 16). Install cases that now meet their expectation into the suite, and keep the others pending with updated notes.
- [ ] **Step 3: Documentation.** CHANGELOG (CRLF) and the roadmap status get the defenses, the comparison, the recapture, and the suite count. Close with **Next steps**: push, merge, deploy (migration 0009, the new volume); then Stage 5b.
