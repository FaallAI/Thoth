# Source Accounts: Multi-Account Rotating Login Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Let acquisition use logged-in sessions. Each platform keeps a pool of accounts, imported as browser cookies, each with an optional dedicated proxy from a pool. The accounts rotate by least recent use with a cooldown ladder, and the dashboard manages them on a "Source Accounts" page.

**Architecture:**
- **Vault.** Cookie sets and proxy URLs are Fernet tokens (`THOTH_ACCOUNT_VAULT_KEY`) in three new tables of the editor Postgres (Alembic revision 0008, SQLAlchemy ORM).
- **Store.** `SourceAccountStore` leases one account with `SELECT … FOR UPDATE SKIP LOCKED` and applies the pure health rules in `accounts/policy.py`.
- **Runner.** `account_runner` wraps the acquisition activity's runner. It applies the platform's mode (`anonymous`, `fallback`, `always`), hands a `SessionAccess` to `acquirer_for`, and reports the outcome.
- **Acquirers.** `acquirer_for` injects the session into every access path: Scrapling browser sessions, request fetchers, and yt-dlp. A new attempt reason, `login_wall`, marks a sign-in page and still reports the failure code `request_blocked`.
- **Interfaces.** FastAPI routes under `/api/v1/source-accounts` and `/api/v1/source-proxies` serve the dashboard pages `SourceAccounts` and `SourceProxies`, which follow the `.pen` frames.

**Tech Stack:**
- Python 3.12, Pydantic v2, SQLAlchemy 2 ORM, Alembic, psycopg 3, `cryptography` (Fernet), FastAPI, pytest with pytest-asyncio (auto mode), Ruff.
- React 19 with base-ui and lucide, Bun test with happy-dom and Testing Library, oxlint, `openapi-typescript`.

**Spec:** `docs/superpowers/specs/2026-10-07-source-accounts-design.md` (operator-approved 2026-10-07).

**Design:** the `Source Accounts · …` frames in `design/thoth-dashboard.pen` (25 frames: the page per platform, the empty, unavailable, and no-healthy states, the add, re-import, and edit dialogs, the session toasts, the proxy pool, the import dialog, the proxy select, and the narrow layouts). Read them with the pencil MCP (`get_app_state`, then `execute` with `Get`/`Export`); never with `Read` or `Grep`.

**Where this plan departs from the spec's wording** (the behavior is the spec's):
- `cookie_names` is `JSONB` instead of `text[]`, so the ORM tests also run offline on SQLite.
- The migration is forward-only, like every editor revision (0001–0007 have no `downgrade`). Spec section 9's "upgrade and downgrade" becomes "upgrade".
- A `socks5://` proxy with credentials is refused at import, because Chromium cannot authenticate to a SOCKS5 proxy. A plain `socks5://host:port` is accepted.
- A sign-in page is `login_wall`, but a flagged-account page (Instagram `/challenge`, X `/account/access`) stays `request_blocked`, so the account cools down instead of expiring.
- TikTok has no reliable login-wall signal in its acquirer, so an expired TikTok session is found by "Test session" only.
- The `.pen` edit dialog has no Disable or Delete control. The dialog footer carries them as secondary actions, "Disable account" / "Enable account" and "Delete" with an inline confirmation.
- The yt-dlp cookie file lives in a private `tempfile.TemporaryDirectory`, removed after the acquisition, instead of the artifact work directory.

## Global Constraints

**Branch and stability**
- Branch `feat/source-accounts` from `master`. Do not push.
- With every platform in `anonymous` mode, or with `THOTH_ACCOUNT_VAULT_KEY` or `THOTH_EDITOR_DATABASE_URL` unset, acquisition behaves exactly as today.
- No new failure code: `AcquisitionFailure.code` stays within its `Literal`. `RETRYABLE_FAILURES` and `LEGACY_FALLBACK_ELIGIBLE_CODES` are unchanged.
- The Temporal workflows do not change. No account id, label, cookie, or proxy enters Temporal history; events carry enums and booleans only.

**Secrets**
- Cookie values and proxy credentials exist only in three places:
  - as ciphertext in the database;
  - in process memory while a session is built;
  - in the yt-dlp temporary cookie file (mode 0600), deleted after the acquisition.
- Logs, reports, events, API responses, and error messages never contain a cookie value, a proxy credential, or a URL. A request body from these routes is never echoed: their validation errors name the field and the error type only.
- The operator's real cookie exports and proxy lists live only under `D:/thoth-tmp/bu/accounts/`. Never commit, print, or describe them beyond counts, cookie names, and enums.

**Tests**
- No live test in the suite. Never change the conftest `_offline_unless_live` guard.
- Postgres tests skip unless `THOTH_TEST_EDITOR_DATABASE_URL` points at a disposable database. Task 1 creates a helper that starts one.

**Commands**
- Python tests (paths relative to `python/`; the script already passes `-q`, so never add `-q`):
  `MSYS_NO_PATHCONV=1 timeout 590 wsl -e bash /mnt/d/thoth-tmp/bu/pt.sh <paths> -p no:warnings`
- Python tests with a disposable Postgres (Task 1 creates the script):
  `MSYS_NO_PATHCONV=1 timeout 590 wsl -e bash /mnt/d/thoth-tmp/bu/pgtest.sh <paths> -p no:warnings`
- Ruff: `wsl -e bash -lc 'cd /mnt/c/Users/mfr/Documents/MyTools/CLIPPER/python && ~/.local/bin/uvx ruff check . && ~/.local/bin/uvx ruff format --check .'`
- Dashboard, from `dashboard/`:
  - `bun test`;
  - `bunx tsc -b` (expected: no output, exit 0);
  - `bunx oxlint src` (expected: no warning naming a file this plan adds);
  - `bun run build`.
- OpenAPI export with the locked versions (Task 8 creates the script):
  `MSYS_NO_PATHCONV=1 wsl -e bash /mnt/d/thoth-tmp/bu/export_openapi.sh /mnt/c/Users/mfr/Documents/MyTools/CLIPPER`

**Applying the plan's code**
- `D:/thoth-tmp/bu/sa/extract.py` (Task 1, Step 1) writes the plan's `Create` blocks and applies its `Apply` patches:
  - `python D:/thoth-tmp/bu/sa/extract.py create <repo path>...`
  - `python D:/thoth-tmp/bu/sa/extract.py apply <repo path>...`
  It reads the plan file, writes LF, and runs `git apply` for patches. A patch that does not apply cleanly stops the task: investigate, never force it.
- These working copies are CRLF and are edited only by the binary Python snippets the plan gives, which preserve CRLF:
  - `python/pyproject.toml`
  - `python/uv.lock` (changed by `uv lock` only)
  - `compose.stage1.local.yml`
  - `docs/python-control-plane.md`
  - `dashboard/src/App.tsx`
  - `dashboard/src/index.css`
  - `CHANGELOG.md`
  - the roadmap
  - the program checkpoint

  Never `sed -i` them.
- Any other ad hoc Python edit writes bytes (`write_bytes`, LF), never text mode: text mode on Windows writes CRLF.

**Commits and staging**
- Exactly one `git commit -m "<subject>"`, at most 72 characters, with no body, no trailer, and no AI attribution. `docs/superpowers/` needs `git add -f`.
- Never stage any of these:
  - `graphify-out/`
  - `build_log.txt`
  - `.superpowers`
  - `.understand-anything`
  - `.env.stage1.local.bak-*`
  - `dashboard/dist/`
  - the untracked `design/` files (`design/thoth-dashboard.pen` stays the operator's)

## Review Focus

1. **Two workers lease at the same moment.** Each gets a different account, or one gets none; never the same account twice.
   - Test: Task 4, `test_a_row_locked_by_another_lease_is_skipped_not_waited_for`.
   - It runs only with Postgres (`pgtest.sh`), so run it every time Task 4's tests run.
2. **A proxy password with `@` or `:`.** The credentials are percent-encoded exactly once, so the browser, curl, and yt-dlp read the same host.
   - Test: Task 2, `test_credentials_are_percent_encoded_once`.
3. **An account deleted while an acquisition holds it.** Releasing the lease is quiet, and nothing is re-created.
   - Test: Task 4, `test_releasing_a_lease_on_a_deleted_account_is_quiet`.
4. **A malformed request carrying a cookie export or a proxy password.** The 422 never echoes it.
   - Test: Task 8, `test_a_malformed_body_never_echoes_its_input`.
   - The sentinel sweep in Task 8: `test_secrets_never_leave_the_vault`.
5. **`fallback` after a slow anonymous failure.** Only `blocked` and `login_wall` trigger the one retry with an account; a timeout or a media failure never does, so the retry cannot double a slow run.
   - Test: Task 7, `test_fallback_does_not_retry_a_timeout`.

## File Structure

| File | Responsibility |
|---|---|
| `python/src/thoth_control_plane/acquisition/accounts/vault.py` (new) | Fernet seal and open, keyed fingerprint. |
| `python/src/thoth_control_plane/acquisition/accounts/cookies.py` (new) | Netscape and JSON cookie import, per-platform validation, the access-path shapes. |
| `python/src/thoth_control_plane/acquisition/accounts/proxies.py` (new) | Proxy list parsing and normalization. |
| `python/src/thoth_control_plane/acquisition/accounts/policy.py` (new) | Modes, outcomes, the cooldown ladder; pure. |
| `python/src/thoth_control_plane/acquisition/accounts/access.py` (new) | `SessionAccess`: cookies and proxy for the browser, the fetcher, and yt-dlp. |
| `python/src/thoth_control_plane/acquisition/accounts/runner.py` (new) | Mode logic around one acquisition, the outcome mapping. |
| `python/src/thoth_control_plane/acquisition/accounts/session_check.py` (new) | The manual session check. |
| `python/migrations/editor/0008_source_accounts.sql` (new), `alembic/versions/0008_source_accounts.py` (new) | The three tables. |
| `python/src/thoth_control_plane/infrastructure/source_account_models.py` (new) | ORM mapping, `UtcDateTime`. |
| `python/src/thoth_control_plane/infrastructure/source_account_store.py` (new) | Policies, accounts, proxies, lease and report. |
| `python/src/thoth_control_plane/domain/source_accounts.py` (new), `api/routes/source_accounts.py` (new) | API shapes and routes. |
| `python/src/thoth_control_plane/config.py`, `operations/editor_migrations.py`, `acquisition/models.py`, `domain/models.py`, `acquisition/registry.py`, the Threads, Instagram, X, and YouTube services, `activities/source_investigation.py`, `api/app.py` | Wiring. |
| `dashboard/src/api/source-accounts.ts`, `components/SourceAccounts.tsx`, `components/SourceAccountDialogs.tsx`, `components/SourceProxies.tsx`, `pen-source-accounts.css` (new) | The pages. |
| `dashboard/src/App.tsx`, `index.css`, `api/generated/control-plane.ts`, `python/openapi.json` | Wiring and the regenerated contract. |

---

### Task 1: Vault, setting, and the `cryptography` dependency

**Files:**
- Create: `python/src/thoth_control_plane/acquisition/accounts/__init__.py`, `accounts/vault.py`
- Create: `python/tests/acquisition/accounts/__init__.py`, `python/tests/acquisition/accounts/test_vault.py`
- Modify: `python/src/thoth_control_plane/config.py`, `python/tests/test_config.py`
- Modify (CRLF): `python/pyproject.toml`; `python/uv.lock` (through `uv lock`)

**Interfaces:**
- Consumes: nothing.
- Produces:
  - `Vault(key: str)` with `seal(plaintext: str) -> bytes`, `open(token: bytes) -> str` (raises `VaultError`, an empty-message exception), `fingerprint(text: str) -> str` (64 hex characters, keyed).
  - `Vault.from_key(key: str | None) -> Vault | None` (None for an absent or malformed key).
  - `Settings.THOTH_ACCOUNT_VAULT_KEY: SecretStr | None`; `Settings.account_vault_key -> str | None` (the stripped key, only when `THOTH_EDITOR_DATABASE_URL` is set too).

- [ ] **Step 1: Prepare the local tools (outside the repository)**

Write `D:/thoth-tmp/bu/sa/extract.py` with the Write tool, exactly as below:

```python
"""Write the plan's `Create` blocks and apply its patches, for one task.

Usage: python extract.py <create|apply> <task number> <repo path>...
Set SA_ROOT to run against another checkout (default: the main repository).
"""

import os
import re
import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path(os.environ.get("SA_ROOT", "C:/Users/mfr/Documents/MyTools/CLIPPER"))
PLAN = Path(
    os.environ.get(
        "SA_PLAN",
        "C:/Users/mfr/Documents/MyTools/CLIPPER/docs/superpowers/plans/2026-10-08-source-accounts.md",
    )
)
CREATE = re.compile(r"^Create `([^`]+)`:\n\n`{3}[a-z]*\n(.*?)^`{3}$", re.M | re.S)
APPLY = re.compile(r"^Apply this patch to `([^`]+)`:\n\n`{3}diff\n(.*?)^`{3}$", re.M | re.S)


def section(text: str, task: str) -> str:
    start = re.search(rf"^### Task {task}:", text, re.M)
    assert start, f"no Task {task}"
    end = re.search(r"^### Task \d+:", text[start.end():], re.M)
    return text[start.start(): start.end() + end.start()] if end else text[start.start():]


def main() -> None:
    action, task, *paths = sys.argv[1:]
    body = section(PLAN.read_text(encoding="utf-8"), task)
    pattern = CREATE if action == "create" else APPLY
    blocks = {}
    for match in pattern.finditer(body):
        assert match.group(1) not in blocks, f"two blocks for {match.group(1)}"
        blocks[match.group(1)] = match.group(2)
    for path in paths:
        assert path in blocks, f"Task {task} has no {action} block for {path}"
        if action == "create":
            target = ROOT / path
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_bytes(blocks[path].encode("utf-8"))
            print("created", path)
            continue
        with tempfile.NamedTemporaryFile("wb", suffix=".diff", delete=False) as handle:
            handle.write(blocks[path].encode("utf-8"))
        result = subprocess.run(
            ["git", "-C", str(ROOT), "apply", "--whitespace=nowarn", handle.name],
            capture_output=True,
            text=True,
        )
        os.unlink(handle.name)
        if result.returncode:
            sys.exit(f"patch for {path} did not apply:\n{result.stderr}")
        print("applied", path)


if __name__ == "__main__":
    main()
```

Add `--with cryptography` to `D:/thoth-tmp/bu/pt.sh`, right after `--with pyyaml`. The plan adds `cryptography` to the project, and `pt.sh` lists its packages by hand.

```bash
sed -i 's/--with pyyaml /--with pyyaml --with cryptography /' D:/thoth-tmp/bu/pt.sh && grep -c "with cryptography" D:/thoth-tmp/bu/pt.sh
```

Expected: `1`.

Write `D:/thoth-tmp/bu/pgtest.sh` (LF) with the Write tool. It starts a disposable Postgres in WSL Docker and runs `pt.sh` against it:

```bash
docker start thoth-pg-test >/dev/null 2>&1 || docker run -d --name thoth-pg-test -e POSTGRES_PASSWORD=test -e POSTGRES_DB=editor -p 127.0.0.1:55432:5432 postgres:16 >/dev/null
for i in $(seq 1 30); do docker exec thoth-pg-test pg_isready -U postgres >/dev/null 2>&1 && break; sleep 1; done
export THOTH_TEST_EDITOR_DATABASE_URL=postgresql://postgres:test@127.0.0.1:55432/editor
bash /mnt/d/thoth-tmp/bu/pt.sh "$@"
```

- [ ] **Step 2: Write the failing tests**

```bash
python D:/thoth-tmp/bu/sa/extract.py create 1 python/tests/acquisition/accounts/__init__.py python/tests/acquisition/accounts/test_vault.py
python D:/thoth-tmp/bu/sa/extract.py apply 1 python/tests/test_config.py
```

Create `python/tests/acquisition/accounts/__init__.py`:

```python
```

Create `python/tests/acquisition/accounts/test_vault.py`:

```python
"""The source-account vault: sealing, opening, keys, and fingerprints; no network."""

from __future__ import annotations

import pytest
from cryptography.fernet import Fernet

from thoth_control_plane.acquisition.accounts.vault import Vault, VaultError

KEY = Fernet.generate_key().decode()
SECRET = "sessionid=secret-cookie-value"


def test_a_sealed_value_opens_and_never_holds_the_plaintext() -> None:
    vault = Vault(KEY)
    token = vault.seal(SECRET)
    assert SECRET.encode() not in token
    assert vault.open(token) == SECRET


def test_another_key_or_a_damaged_token_is_a_vault_error() -> None:
    token = Vault(KEY).seal(SECRET)
    with pytest.raises(VaultError) as caught:
        Vault(Fernet.generate_key().decode()).open(token)
    assert str(caught.value) == ""
    with pytest.raises(VaultError):
        Vault(KEY).open(token[:-4] + b"AAAA")
    with pytest.raises(VaultError):
        Vault(KEY).open(b"not a token")


@pytest.mark.parametrize("key", [None, "", "not-a-fernet-key", "a" * 44])
def test_an_absent_or_malformed_key_gives_no_vault(key: str | None) -> None:
    assert Vault.from_key(key) is None


def test_fingerprints_are_stable_keyed_and_opaque() -> None:
    vault = Vault(KEY)
    assert vault.fingerprint(SECRET) == Vault(KEY).fingerprint(SECRET)
    assert vault.fingerprint(SECRET) != vault.fingerprint(SECRET + "x")
    assert vault.fingerprint(SECRET) != Vault(Fernet.generate_key().decode()).fingerprint(SECRET)
    assert "secret" not in vault.fingerprint(SECRET)
```

Apply this patch to `python/tests/test_config.py`:

```diff
diff --git a/python/tests/test_config.py b/python/tests/test_config.py
--- a/python/tests/test_config.py
+++ b/python/tests/test_config.py
@@ -123,3 +123,14 @@ def test_the_render_deadline_stays_inside_its_bounds(seconds: int) -> None:
 def test_the_render_preset_cannot_be_switched_to_another_value() -> None:
     with pytest.raises(ValueError):
         settings(THOTH_RENDER_PRESET_ID="wide_1080p_prores")
+
+
+def test_the_account_vault_key_needs_the_editor_database() -> None:
+    assert settings().account_vault_key is None
+    assert settings(THOTH_ACCOUNT_VAULT_KEY="k").account_vault_key is None
+    with_database = {"THOTH_EDITOR_DATABASE_URL": "postgresql://db/editor"}
+    assert settings(THOTH_ACCOUNT_VAULT_KEY=" k ", **with_database).account_vault_key == "k"
+    assert settings(THOTH_ACCOUNT_VAULT_KEY="  ", **with_database).account_vault_key is None
+    assert "vault-secret" not in repr(
+        settings(THOTH_ACCOUNT_VAULT_KEY="vault-secret", **with_database)
+    )
```

- [ ] **Step 3: Run the tests to verify they fail**

Run: `MSYS_NO_PATHCONV=1 timeout 590 wsl -e bash /mnt/d/thoth-tmp/bu/pt.sh tests/acquisition/accounts tests/test_config.py -p no:warnings`
Expected: FAIL: `ModuleNotFoundError: No module named 'thoth_control_plane.acquisition.accounts'` during collection, and `account_vault_key` missing.

- [ ] **Step 4: Implement**

```bash
python D:/thoth-tmp/bu/sa/extract.py create 1 python/src/thoth_control_plane/acquisition/accounts/__init__.py python/src/thoth_control_plane/acquisition/accounts/vault.py
python D:/thoth-tmp/bu/sa/extract.py apply 1 python/src/thoth_control_plane/config.py
```

Create `python/src/thoth_control_plane/acquisition/accounts/__init__.py`:

```python
"""Logged-in source accounts: the vault, cookie and proxy import, rotation, and access."""
```

Create `python/src/thoth_control_plane/acquisition/accounts/vault.py`:

```python
"""The source-account vault: Fernet encryption of cookie sets and proxy URLs.

The key is `THOTH_ACCOUNT_VAULT_KEY`, a Fernet key. Plaintext exists only in memory while a
session is built. A token this vault cannot open raises `VaultError`, which carries neither
the token nor the key.
"""

from __future__ import annotations

import hashlib
import hmac

from cryptography.fernet import Fernet, InvalidToken

_FINGERPRINT_CONTEXT = b"thoth-source-accounts/fingerprint/v1"


class VaultError(Exception):
    """A token this vault cannot open: another key, or a damaged value."""


class Vault:
    def __init__(self, key: str) -> None:
        self._fernet = Fernet(key)
        self._mac_key = hashlib.sha256(_FINGERPRINT_CONTEXT + key.encode("utf-8")).digest()

    @classmethod
    def from_key(cls, key: str | None) -> Vault | None:
        """A vault for a usable key; None when the key is absent or not a Fernet key."""
        if not key:
            return None
        try:
            return cls(key)
        except ValueError:
            return None

    def seal(self, plaintext: str) -> bytes:
        return self._fernet.encrypt(plaintext.encode("utf-8"))

    def open(self, token: bytes) -> str:
        try:
            return self._fernet.decrypt(bytes(token)).decode("utf-8")
        except (InvalidToken, UnicodeDecodeError, TypeError, ValueError):
            raise VaultError() from None

    def fingerprint(self, text: str) -> str:
        """A keyed digest that detects duplicates without keeping `text` in clear."""
        return hmac.new(self._mac_key, text.encode("utf-8"), hashlib.sha256).hexdigest()
```

Apply this patch to `python/src/thoth_control_plane/config.py`:

```diff
diff --git a/python/src/thoth_control_plane/config.py b/python/src/thoth_control_plane/config.py
--- a/python/src/thoth_control_plane/config.py
+++ b/python/src/thoth_control_plane/config.py
@@ -76,6 +76,8 @@ class Settings(BaseSettings):
     THOTH_RENDER_MAX_SECONDS: Annotated[int, Field(ge=60, le=7200)] = 900
     THOTH_RENDERER_VERSION: str = "remotion-4.0.523"
     THOTH_RENDER_PRESET_ID: Literal["standard_vertical_mp4_v1"] = "standard_vertical_mp4_v1"
+    # A Fernet key; source accounts need it and the editor database, else they stay off.
+    THOTH_ACCOUNT_VAULT_KEY: SecretStr | None = None
 
     def __init__(self, **values: object) -> None:
         """Load settings, then reject an incomplete gateway pair without retaining inputs."""
@@ -128,6 +130,13 @@ class Settings(BaseSettings):
         """Worker-only credential map keyed by catalog credential_id."""
         return dict(self.THOTH_PROMPT_PROVIDER_SECRETS)
 
+    @property
+    def account_vault_key(self) -> str | None:
+        """The source-account vault key, when the editor database is configured too."""
+        if self.THOTH_ACCOUNT_VAULT_KEY is None or self.THOTH_EDITOR_DATABASE_URL is None:
+            return None
+        return self.THOTH_ACCOUNT_VAULT_KEY.get_secret_value().strip() or None
+
     @property
     def legacy_bridge_enabled(self) -> bool:
         """Whether the validated legacy observation bridge can be constructed."""
```

Add `cryptography` to the base dependencies (CRLF preserved), then relock:

```bash
python - <<'PY'
from pathlib import Path

path = Path("C:/Users/mfr/Documents/MyTools/CLIPPER/python/pyproject.toml")
data = path.read_bytes()
nl = b"\r\n" if b"\r\n" in data else b"\n"
old = b'    "alembic>=1.13,<2",' + nl
assert data.count(old) == 1
path.write_bytes(data.replace(old, old + b'    "cryptography>=44,<48",' + nl))
PY
wsl -e bash -lc 'cd /mnt/c/Users/mfr/Documents/MyTools/CLIPPER && ~/.local/bin/uv lock --project python && ~/.local/bin/uv lock --project python --locked >/dev/null 2>&1; echo EXIT=$?'
git diff --stat -- python/uv.lock
```

Expected: `EXIT=0`, and `uv.lock` gains `cryptography` 47.0.0 (with `cffi` and `pycparser`) and nothing else changes.

- [ ] **Step 5: Run the tests to verify they pass**

Run: `MSYS_NO_PATHCONV=1 timeout 590 wsl -e bash /mnt/d/thoth-tmp/bu/pt.sh tests/acquisition/accounts tests/test_config.py -p no:warnings`
Expected: PASS.

- [ ] **Step 6: Commit**

```bash
git add python/src/thoth_control_plane/acquisition/accounts python/tests/acquisition/accounts python/src/thoth_control_plane/config.py python/tests/test_config.py python/pyproject.toml python/uv.lock
git commit -m "feat(accounts): add the source-account vault and its key setting"
```

---

### Task 2: Cookie and proxy import

**Files:**
- Create: `python/src/thoth_control_plane/acquisition/accounts/cookies.py`, `accounts/proxies.py`
- Test: `python/tests/acquisition/accounts/test_cookies.py`, `test_proxies.py`

**Interfaces:**
- Consumes: nothing.
- Produces:
  - `cookies.py`:
    - `Platform` literal and `PLATFORMS`;
    - `PLATFORM_DOMAINS`, `REQUIRED_COOKIES`, `MAX_IMPORT_BYTES = 262144`, `MAX_COOKIES = 500`;
    - `CookieImportError(code, missing)` with `code` in `invalid_cookie_file | all_cookies_expired | missing_required_cookie`;
    - `Cookie` (frozen; `value` hidden from `repr`);
    - `CookieSet(platform, cookies)` with `names()`, `earliest_expiry()`, `to_json()`, `from_json(platform, text)`, `to_playwright()`, `to_request()`, `to_netscape()`;
    - `CookieSummary(count, names, earliest_expiry, error, missing)`;
    - `parse_cookies(platform, text, *, now) -> CookieSet`;
    - `summarize(platform, text, *, now) -> CookieSummary` (never raises).
  - `proxies.py`:
    - `SCHEMES`, `MAX_PROXY_BYTES = 65536`, `MAX_PROXY_LINES = 500`;
    - `ProxyImportError` (`code = "invalid_proxy_file"`);
    - `ProxyEntry(url, scheme, display)`;
    - `ProxyImport(entries, invalid_lines)`;
    - `parse_proxy(line) -> ProxyEntry | None`;
    - `parse_proxy_list(text) -> ProxyImport`.

- [ ] **Step 1: Write the failing tests**

```bash
python D:/thoth-tmp/bu/sa/extract.py create 2 python/tests/acquisition/accounts/test_cookies.py python/tests/acquisition/accounts/test_proxies.py
```

Create `python/tests/acquisition/accounts/test_cookies.py`:

```python
"""Cookie export parsing and validation for each platform; no network."""

from __future__ import annotations

import json
from dataclasses import asdict
from datetime import UTC, datetime

import pytest

from thoth_control_plane.acquisition.accounts.cookies import (
    MAX_COOKIES,
    MAX_IMPORT_BYTES,
    CookieImportError,
    CookieSet,
    parse_cookies,
    summarize,
)

NOW = datetime(2026, 10, 7, tzinfo=UTC)
LATER = int(datetime(2026, 11, 2, tzinfo=UTC).timestamp())
LATEST = int(datetime(2027, 1, 1, tzinfo=UTC).timestamp())
PAST = int(datetime(2026, 1, 1, tzinfo=UTC).timestamp())
SECRET = "s3cr3t-session-value"


def _line(domain: str, name: str, value: str, expires: int = LATER, http_only: bool = False):
    prefix = "#HttpOnly_" if http_only else ""
    flag = "TRUE" if domain.startswith(".") else "FALSE"
    return "\t".join([prefix + domain, flag, "/", "TRUE", str(expires), name, value])


def _netscape(*lines: str) -> str:
    return "# Netscape HTTP Cookie File\n# a comment\n\n" + "\n".join(lines) + "\n"


def test_a_netscape_export_keeps_the_platforms_cookies_and_http_only() -> None:
    text = _netscape(
        _line(".instagram.com", "sessionid", SECRET, http_only=True),
        _line(".instagram.com", "csrftoken", "c", LATEST),
        _line(".google.com", "SID", "g"),
    )
    cookies = parse_cookies("instagram", text, now=NOW)
    assert cookies.names() == ["csrftoken", "sessionid"]
    session = next(c for c in cookies.cookies if c.name == "sessionid")
    assert (session.http_only, session.secure, session.domain) == (True, True, ".instagram.com")
    assert cookies.earliest_expiry() == datetime.fromtimestamp(LATER, UTC)


def test_a_cookie_editor_json_export_is_read() -> None:
    text = json.dumps(
        [
            {
                "name": "auth_token",
                "value": SECRET,
                "domain": ".x.com",
                "path": "/",
                "expirationDate": LATER + 0.5,
                "secure": True,
                "httpOnly": True,
                "sameSite": "no_restriction",
            },
            {"name": "ct0", "value": "csrf", "domain": "x.com", "session": True},
            {"name": "", "value": "dropped", "domain": "x.com"},
            "junk",
        ]
    )
    cookies = parse_cookies("x", text, now=NOW)
    assert cookies.names() == ["auth_token", "ct0"]
    auth = next(c for c in cookies.cookies if c.name == "auth_token")
    assert (auth.same_site, auth.expires) == ("None", LATER + 0.5)


def test_youtube_keeps_its_google_login_cookies() -> None:
    text = _netscape(
        _line(".youtube.com", "SAPISID", "a"),
        _line(".google.com", "__Secure-3PSID", "b"),
        _line(".tiktok.com", "sessionid", "c"),
    )
    assert parse_cookies("youtube", text, now=NOW).names() == ["SAPISID", "__Secure-3PSID"]


def test_threads_accepts_its_own_or_instagrams_session() -> None:
    for domain in (".threads.net", ".threads.com", ".instagram.com"):
        assert parse_cookies("threads", _netscape(_line(domain, "sessionid", "s")), now=NOW)


def test_a_lookalike_domain_is_not_the_platforms() -> None:
    text = _netscape(_line(".notinstagram.com", "sessionid", "s"))
    with pytest.raises(CookieImportError) as caught:
        parse_cookies("instagram", text, now=NOW)
    assert (caught.value.code, caught.value.missing) == ("missing_required_cookie", ("sessionid",))


def test_missing_login_cookies_are_named() -> None:
    text = _netscape(_line(".x.com", "ct0", "c"))
    with pytest.raises(CookieImportError) as caught:
        parse_cookies("x", text, now=NOW)
    assert (caught.value.code, caught.value.missing) == ("missing_required_cookie", ("auth_token",))


def test_expired_cookies_are_dropped_and_all_expired_is_refused() -> None:
    text = _netscape(_line(".tiktok.com", "sessionid", "s", PAST))
    with pytest.raises(CookieImportError) as caught:
        parse_cookies("tiktok", text, now=NOW)
    assert caught.value.code == "all_cookies_expired"
    mixed = _netscape(
        _line(".tiktok.com", "old", "o", PAST), _line(".tiktok.com", "sessionid", "s")
    )
    assert parse_cookies("tiktok", mixed, now=NOW).names() == ["sessionid"]


def test_a_session_only_login_cookie_has_no_expiry() -> None:
    text = _netscape(_line(".tiktok.com", "sessionid", "s", 0))
    cookies = parse_cookies("tiktok", text, now=NOW)
    assert cookies.earliest_expiry() is None


@pytest.mark.parametrize(
    "text",
    [
        "",
        "not a cookie file",
        "[1, 2",
        "{}",
        "x" * (MAX_IMPORT_BYTES + 1),
        _netscape(*[_line(".tiktok.com", f"c{i}", "v") for i in range(MAX_COOKIES + 1)]),
    ],
)
def test_broken_or_oversized_input_is_an_invalid_file(text: str) -> None:
    with pytest.raises(CookieImportError) as caught:
        parse_cookies("tiktok", text, now=NOW)
    assert caught.value.code == "invalid_cookie_file"


def test_a_repeated_cookie_keeps_the_last_copy() -> None:
    text = _netscape(
        _line(".tiktok.com", "sessionid", "old"), _line(".tiktok.com", "sessionid", "new")
    )
    (cookie,) = parse_cookies("tiktok", text, now=NOW).cookies
    assert cookie.value == "new"


def test_the_summary_names_cookies_and_never_holds_a_value() -> None:
    good = summarize("instagram", _netscape(_line(".instagram.com", "sessionid", SECRET)), now=NOW)
    assert (good.count, good.names, good.error) == (1, ("sessionid",), None)
    bad = summarize("x", _netscape(_line(".x.com", "auth_token", SECRET)), now=NOW)
    assert (bad.error, bad.missing, bad.count) == ("missing_required_cookie", ("ct0",), 0)
    assert SECRET not in repr(good) + repr(bad) + json.dumps(asdict(bad), default=str)
    with pytest.raises(CookieImportError) as caught:
        parse_cookies("x", _netscape(_line(".x.com", "auth_token", SECRET)), now=NOW)
    assert SECRET not in str(caught.value) + repr(caught.value)


def test_a_cookie_set_round_trips_and_feeds_every_access_path() -> None:
    text = _netscape(
        _line(".instagram.com", "sessionid", SECRET, http_only=True),
        _line("www.instagram.com", "csrftoken", "c", 0),
    )
    cookies = parse_cookies("instagram", text, now=NOW)
    assert CookieSet.from_json("instagram", cookies.to_json()) == cookies
    assert parse_cookies("instagram", cookies.to_netscape(), now=NOW) == cookies
    assert cookies.to_request() == {"sessionid": SECRET, "csrftoken": "c"}
    by_name = {c["name"]: c for c in cookies.to_playwright()}
    assert by_name["sessionid"] == {
        "name": "sessionid",
        "value": SECRET,
        "domain": ".instagram.com",
        "path": "/",
        "secure": True,
        "httpOnly": True,
        "expires": LATER,
    }
    assert "expires" not in by_name["csrftoken"]
```

Create `python/tests/acquisition/accounts/test_proxies.py`:

```python
"""Proxy list parsing for the pool; no network."""

from __future__ import annotations

import pytest

from thoth_control_plane.acquisition.accounts.proxies import (
    MAX_PROXY_BYTES,
    MAX_PROXY_LINES,
    ProxyImportError,
    parse_proxy,
    parse_proxy_list,
)

PASSWORD = "pr0xy-pa55"


@pytest.mark.parametrize(
    ("line", "url", "display"),
    [
        (
            f"http://user:{PASSWORD}@1.2.3.4:8080",
            f"http://user:{PASSWORD}@1.2.3.4:8080",
            "1.2.3.4:8080",
        ),
        (
            "HTTPS://Proxy.Example.Test:443/",
            "https://proxy.example.test:443",
            "proxy.example.test:443",
        ),
        ("socks5://10.0.0.1:1080", "socks5://10.0.0.1:1080", "10.0.0.1:1080"),
        ("http://[2001:db8::1]:3128", "http://[2001:db8::1]:3128", "[2001:db8::1]:3128"),
        (
            "  http://u:p@gw.example.test:7000  ",
            "http://u:p@gw.example.test:7000",
            "gw.example.test:7000",
        ),
    ],
)
def test_valid_proxies_normalize_and_display_host_and_port_only(
    line: str, url: str, display: str
) -> None:
    entry = parse_proxy(line)
    assert entry is not None
    assert (entry.url, entry.display) == (url, display)
    assert PASSWORD not in entry.display


@pytest.mark.parametrize(
    "line",
    [
        "1.2.3.4:8080",
        "ftp://1.2.3.4:21",
        "http://1.2.3.4",
        "http://1.2.3.4:0",
        "http://1.2.3.4:99999",
        "http://:8080",
        "http://1.2.3.4:8080/path",
        "http://1.2.3.4:8080?x=1",
        "http://user@1.2.3.4:8080",
        "socks5://user:pass@1.2.3.4:1080",
        "not a url",
    ],
)
def test_anything_else_is_invalid(line: str) -> None:
    assert parse_proxy(line) is None


def test_a_list_skips_comments_blanks_and_repeats_and_numbers_bad_lines() -> None:
    text = "\n".join(
        [
            "# my proxies",
            f"http://user:{PASSWORD}@1.2.3.4:8080",
            "",
            f"secret-garbage-{PASSWORD}",
            "socks5://10.0.0.1:1080",
            f"http://user:{PASSWORD}@1.2.3.4:8080",
        ]
    )
    result = parse_proxy_list(text)
    assert [entry.display for entry in result.entries] == ["1.2.3.4:8080", "10.0.0.1:1080"]
    assert result.invalid_lines == (4,)


@pytest.mark.parametrize(
    "text",
    ["x" * (MAX_PROXY_BYTES + 1), "\n".join(["http://1.2.3.4:8080"] * (MAX_PROXY_LINES + 1))],
)
def test_an_oversized_list_is_refused_whole(text: str) -> None:
    with pytest.raises(ProxyImportError) as caught:
        parse_proxy_list(text)
    assert caught.value.code == "invalid_proxy_file"


@pytest.mark.parametrize(
    ("line", "url"),
    [
        ("http://user:p@ss:w@1.2.3.4:8080", "http://user:p%40ss%3Aw@1.2.3.4:8080"),
        ("http://user:p%40ss@1.2.3.4:8080", "http://user:p%40ss@1.2.3.4:8080"),
        ("http://us%3Aer:pass@1.2.3.4:8080", "http://us%3Aer:pass@1.2.3.4:8080"),
    ],
)
def test_credentials_are_percent_encoded_once(line: str, url: str) -> None:
    entry = parse_proxy(line)
    assert entry is not None
    assert (entry.url, entry.display) == (url, "1.2.3.4:8080")
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `MSYS_NO_PATHCONV=1 timeout 590 wsl -e bash /mnt/d/thoth-tmp/bu/pt.sh tests/acquisition/accounts -p no:warnings`
Expected: FAIL with `ModuleNotFoundError` for `accounts.cookies` and `accounts.proxies`.

- [ ] **Step 3: Implement**

```bash
python D:/thoth-tmp/bu/sa/extract.py create 2 python/src/thoth_control_plane/acquisition/accounts/cookies.py python/src/thoth_control_plane/acquisition/accounts/proxies.py
```

Create `python/src/thoth_control_plane/acquisition/accounts/cookies.py`:

```python
"""Parse and validate a browser cookie export for one platform; holds no state.

Two formats are read: Netscape `cookies.txt` (yt-dlp, "Get cookies.txt" extensions; the
`#HttpOnly_` prefix is honored) and the JSON array Cookie-Editor and EditThisCookie export.
Only the platform's own cookies are kept; expired ones are dropped; the platform's login
cookies must be present. Errors carry a code and cookie names, never a cookie value.
"""

from __future__ import annotations

import json
from dataclasses import asdict, dataclass, field
from datetime import UTC, datetime
from typing import Any, Literal

Platform = Literal["tiktok", "threads", "instagram", "x", "youtube"]
PLATFORMS: tuple[Platform, ...] = ("tiktok", "threads", "instagram", "x", "youtube")
PLATFORM_DOMAINS: dict[str, tuple[str, ...]] = {
    "tiktok": ("tiktok.com",),
    "threads": ("threads.net", "threads.com", "instagram.com"),
    "instagram": ("instagram.com",),
    "x": ("x.com", "twitter.com"),
    "youtube": ("youtube.com", "google.com"),
}
REQUIRED_COOKIES: dict[str, tuple[str, ...]] = {
    "tiktok": ("sessionid",),
    "threads": ("sessionid",),
    "instagram": ("sessionid",),
    "x": ("auth_token", "ct0"),
    "youtube": ("SAPISID", "__Secure-3PSID"),
}
MAX_IMPORT_BYTES = 256 * 1024
MAX_COOKIES = 500
_SAME_SITE = {"lax": "Lax", "strict": "Strict", "none": "None", "no_restriction": "None"}
ErrorCode = Literal["invalid_cookie_file", "all_cookies_expired", "missing_required_cookie"]


class CookieImportError(ValueError):
    def __init__(self, code: ErrorCode, missing: tuple[str, ...] = ()) -> None:
        super().__init__(code)
        self.code: ErrorCode = code
        self.missing = missing


@dataclass(frozen=True)
class Cookie:
    name: str
    value: str = field(repr=False)
    domain: str
    path: str = "/"
    expires: float | None = None
    secure: bool = True
    http_only: bool = False
    same_site: str | None = None


@dataclass(frozen=True)
class CookieSet:
    platform: Platform
    cookies: tuple[Cookie, ...]

    def names(self) -> list[str]:
        return sorted({cookie.name for cookie in self.cookies})

    def earliest_expiry(self) -> datetime | None:
        """The earliest expiry among the login cookies; None when they are session-only."""
        required = REQUIRED_COOKIES[self.platform]
        times = [c.expires for c in self.cookies if c.name in required and c.expires]
        return datetime.fromtimestamp(min(times), UTC) if times else None

    def to_json(self) -> str:
        return json.dumps([asdict(cookie) for cookie in self.cookies], separators=(",", ":"))

    @classmethod
    def from_json(cls, platform: Platform, text: str) -> CookieSet:
        return cls(platform, tuple(Cookie(**item) for item in json.loads(text)))

    def to_playwright(self) -> list[dict[str, Any]]:
        out = []
        for c in self.cookies:
            cookie: dict[str, Any] = {
                "name": c.name,
                "value": c.value,
                "domain": c.domain,
                "path": c.path,
                "secure": c.secure,
                "httpOnly": c.http_only,
            }
            if c.expires:
                cookie["expires"] = c.expires
            if c.same_site:
                cookie["sameSite"] = c.same_site
            out.append(cookie)
        return out

    def to_request(self) -> dict[str, str]:
        return {cookie.name: cookie.value for cookie in self.cookies}

    def to_netscape(self) -> str:
        lines = ["# Netscape HTTP Cookie File"]
        for c in self.cookies:
            domain = ("#HttpOnly_" if c.http_only else "") + c.domain
            subdomains = "TRUE" if c.domain.startswith(".") else "FALSE"
            secure = "TRUE" if c.secure else "FALSE"
            expires = str(int(c.expires or 0))
            lines.append("\t".join([domain, subdomains, c.path, secure, expires, c.name, c.value]))
        return "\n".join(lines) + "\n"


@dataclass(frozen=True)
class CookieSummary:
    count: int = 0
    names: tuple[str, ...] = ()
    earliest_expiry: datetime | None = None
    error: ErrorCode | None = None
    missing: tuple[str, ...] = ()


def _belongs(domain: str, platform: str) -> bool:
    host = domain.lstrip(".").lower()
    return any(host == d or host.endswith("." + d) for d in PLATFORM_DOMAINS[platform])


def _expiry(value: object) -> float | None:
    if isinstance(value, bool) or not isinstance(value, int | float | str):
        return None
    try:
        seconds = float(value)
    except ValueError:
        return None
    return seconds if seconds > 0 else None


def _netscape(text: str) -> list[Cookie]:
    cookies = []
    for raw in text.splitlines():
        line = raw.strip("\r\n")
        http_only = line.startswith("#HttpOnly_")
        if http_only:
            line = line.removeprefix("#HttpOnly_")
        elif not line.strip() or line.startswith("#"):
            continue
        fields = line.split("\t")
        if len(fields) != 7 or not fields[5]:
            continue
        domain, _, path, secure, expires, name, value = fields
        cookies.append(
            Cookie(
                name=name,
                value=value,
                domain=domain,
                path=path or "/",
                expires=_expiry(expires),
                secure=secure.upper() == "TRUE",
                http_only=http_only,
            )
        )
    return cookies


def _json(text: str) -> list[Cookie]:
    try:
        items = json.loads(text)
    except ValueError:
        return []
    cookies = []
    for item in items if isinstance(items, list) else []:
        if not isinstance(item, dict):
            continue
        name, value, domain = item.get("name"), item.get("value"), item.get("domain")
        if not (isinstance(name, str) and name and isinstance(value, str)):
            continue
        if not (isinstance(domain, str) and domain):
            continue
        same_site = item.get("sameSite")
        path = item.get("path")
        cookies.append(
            Cookie(
                name=name,
                value=value,
                domain=domain,
                path=path if isinstance(path, str) and path else "/",
                expires=_expiry(item.get("expirationDate", item.get("expires"))),
                secure=item.get("secure") is not False,
                http_only=item.get("httpOnly") is True,
                same_site=_SAME_SITE.get(same_site.lower()) if isinstance(same_site, str) else None,
            )
        )
    return cookies


def parse_cookies(platform: Platform, text: str, *, now: datetime) -> CookieSet:
    """The platform's live cookies from an export, or `CookieImportError`."""
    if len(text.encode("utf-8")) > MAX_IMPORT_BYTES:
        raise CookieImportError("invalid_cookie_file")
    parsed = _json(text) if text.lstrip().startswith("[") else _netscape(text)
    if not parsed or len(parsed) > MAX_COOKIES:
        raise CookieImportError("invalid_cookie_file")
    mine = [cookie for cookie in parsed if _belongs(cookie.domain, platform)]
    stamp = now.timestamp()
    live = [c for c in mine if c.expires is None or c.expires > stamp]
    if mine and not live:
        raise CookieImportError("all_cookies_expired")
    unique = {(c.name, c.domain.lower(), c.path): c for c in live}
    names = {name for name, _, _ in unique}
    missing = tuple(name for name in REQUIRED_COOKIES[platform] if name not in names)
    if missing:
        raise CookieImportError("missing_required_cookie", missing)
    return CookieSet(platform, tuple(unique.values()))


def summarize(platform: Platform, text: str, *, now: datetime) -> CookieSummary:
    """The safe summary of an import; never raises and never holds a value."""
    try:
        cookie_set = parse_cookies(platform, text, now=now)
    except CookieImportError as error:
        return CookieSummary(error=error.code, missing=error.missing)
    return CookieSummary(
        count=len(cookie_set.cookies),
        names=tuple(cookie_set.names()),
        earliest_expiry=cookie_set.earliest_expiry(),
    )
```

Create `python/src/thoth_control_plane/acquisition/accounts/proxies.py`:

```python
"""Parse a pasted proxy list for the pool; holds no state.

One proxy per line, `scheme://[user:pass@]host:port`, with scheme `http`, `https`, or
`socks5`. Blank lines and `#` comments are skipped. A SOCKS5 proxy with credentials is
refused: Chromium cannot authenticate to one, so the card browser could never use it.
Invalid lines are reported by number only; a line is never echoed.
"""

from __future__ import annotations

from dataclasses import dataclass
from urllib.parse import quote, unquote, urlsplit

SCHEMES = ("http", "https", "socks5")
MAX_PROXY_BYTES = 64 * 1024
MAX_PROXY_LINES = 500


class ProxyImportError(ValueError):
    def __init__(self) -> None:
        super().__init__("invalid_proxy_file")
        self.code = "invalid_proxy_file"


@dataclass(frozen=True)
class ProxyEntry:
    url: str
    scheme: str
    display: str


@dataclass(frozen=True)
class ProxyImport:
    entries: tuple[ProxyEntry, ...]
    invalid_lines: tuple[int, ...]


def _encoded(value: str | None) -> str:
    """Percent-encoded exactly once, so an `@` or `:` in a password stays a credential."""
    return quote(unquote(value or ""), safe="")


def parse_proxy(line: str) -> ProxyEntry | None:
    """A normalized proxy, or None for anything outside the accepted shape."""
    try:
        parts = urlsplit(line.strip())
        port = parts.port
    except ValueError:
        return None
    scheme = parts.scheme.lower()
    host = (parts.hostname or "").lower()
    if scheme not in SCHEMES or not host or port is None or not 0 < port < 65536:
        return None
    if parts.path not in ("", "/") or parts.query or parts.fragment:
        return None
    has_user = parts.username is not None or parts.password is not None
    if scheme == "socks5" and has_user:
        return None
    if has_user and not (parts.username and parts.password):
        return None
    shown = f"[{host}]" if ":" in host else host
    display = f"{shown}:{port}"
    userinfo = f"{_encoded(parts.username)}:{_encoded(parts.password)}@" if has_user else ""
    return ProxyEntry(url=f"{scheme}://{userinfo}{display}", scheme=scheme, display=display)


def parse_proxy_list(text: str) -> ProxyImport:
    """Every valid proxy once, in order, and the numbers of the invalid lines."""
    if len(text.encode("utf-8")) > MAX_PROXY_BYTES:
        raise ProxyImportError()
    lines = text.splitlines()
    if len(lines) > MAX_PROXY_LINES:
        raise ProxyImportError()
    entries: dict[str, ProxyEntry] = {}
    invalid: list[int] = []
    for number, line in enumerate(lines, start=1):
        if not line.strip() or line.lstrip().startswith("#"):
            continue
        entry = parse_proxy(line)
        if entry is None:
            invalid.append(number)
        else:
            entries.setdefault(entry.url, entry)
    return ProxyImport(entries=tuple(entries.values()), invalid_lines=tuple(invalid))
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `MSYS_NO_PATHCONV=1 timeout 590 wsl -e bash /mnt/d/thoth-tmp/bu/pt.sh tests/acquisition/accounts -p no:warnings`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add python/src/thoth_control_plane/acquisition/accounts python/tests/acquisition/accounts
git commit -m "feat(accounts): parse cookie exports and proxy lists"
```

---

### Task 3: Editor migration 0008 and the ORM mapping

**Files:**
- Create: `python/migrations/editor/0008_source_accounts.sql`, `python/migrations/editor/alembic/versions/0008_source_accounts.py`
- Create: `python/src/thoth_control_plane/infrastructure/source_account_models.py`
- Modify: `python/src/thoth_control_plane/operations/editor_migrations.py` (the `0008` legacy marker)
- Test: `python/tests/operations/test_editor_migrations.py`, `test_editor_migrations_postgres.py`

**Interfaces:**
- Consumes: nothing.
- Produces:
  - Tables:
    - `source_account_policies(platform pk, mode, min_spacing_seconds, updated_at)`;
    - `source_proxies(id uuid pk, scheme, display, fingerprint unique, proxy_ciphertext, created_at)`;
    - `source_accounts(... proxy_id uuid unique → source_proxies ON DELETE RESTRICT, UNIQUE(platform, label))`.
  - The ORM classes `Base`, `SourceAccountPolicyRow`, `SourceProxyRow`, `SourceAccountRow`, with `UtcDateTime`, which is aware UTC in Python.

Every editor revision is a shipped SQL file run verbatim by a forward-only Alembic revision. `_LEGACY_MARKERS` needs a table for each revision; without the `0008` entry, `apply_editor_migrations` raises a `KeyError` on a pre-Alembic database.

- [ ] **Step 1: Write the failing tests**

```bash
python D:/thoth-tmp/bu/sa/extract.py apply 3 python/tests/operations/test_editor_migrations.py python/tests/operations/test_editor_migrations_postgres.py
```

Apply this patch to `python/tests/operations/test_editor_migrations.py`:

```diff
diff --git a/python/tests/operations/test_editor_migrations.py b/python/tests/operations/test_editor_migrations.py
--- a/python/tests/operations/test_editor_migrations.py
+++ b/python/tests/operations/test_editor_migrations.py
@@ -38,6 +38,7 @@ def test_editor_migrations_stay_explicit_forward_only_sql_files() -> None:
         "0005_revision_bound_render_jobs.sql",
         "0006_studio_review_events.sql",
         "0007_studio_import_sources.sql",
+        "0008_source_accounts.sql",
     ]
     for name in MIGRATION_FILES:
         sql = migration(name).lower()
@@ -400,3 +401,18 @@ def test_studio_review_migration_stores_no_secret_path_or_workflow_approval() ->
 
     for forbidden in ("secret", "token", "cookie", "http", "workflow", "approval_id", "path"):
         assert forbidden not in sql
+
+
+def test_source_accounts_keep_secrets_sealed_and_proxies_dedicated() -> None:
+    sql = " ".join(migration("0008_source_accounts.sql").split())
+
+    for table in ("source_account_policies", "source_proxies", "source_accounts"):
+        assert f"CREATE TABLE {table}" in sql
+    assert "cookies_ciphertext BYTEA NOT NULL" in sql
+    assert "proxy_ciphertext BYTEA NOT NULL" in sql
+    assert "proxy_id UUID UNIQUE REFERENCES source_proxies (id) ON DELETE RESTRICT" in sql
+    assert "fingerprint TEXT NOT NULL UNIQUE" in sql
+    assert "UNIQUE (platform, label)" in sql
+    assert "CHECK (mode IN ('anonymous', 'fallback', 'always'))" in sql
+    for clear in ("cookie_value", "password", "proxy_url"):
+        assert clear not in sql.lower()
```

Apply this patch to `python/tests/operations/test_editor_migrations_postgres.py`:

```diff
diff --git a/python/tests/operations/test_editor_migrations_postgres.py b/python/tests/operations/test_editor_migrations_postgres.py
--- a/python/tests/operations/test_editor_migrations_postgres.py
+++ b/python/tests/operations/test_editor_migrations_postgres.py
@@ -32,9 +32,10 @@ def _tables() -> set[str]:
 
 
 def test_fresh_database_applies_every_revision_and_a_rerun_applies_none() -> None:
-    assert apply_editor_migrations(DATABASE_URL, MIGRATIONS) == 7
+    assert apply_editor_migrations(DATABASE_URL, MIGRATIONS) == 8
     assert apply_editor_migrations(DATABASE_URL, MIGRATIONS) == 0
     assert {"alembic_version", "studio_import_drafts", "studio_import_decisions"} <= _tables()
+    assert {"source_account_policies", "source_proxies", "source_accounts"} <= _tables()
 
 
 def test_database_migrated_before_alembic_is_adopted_and_only_the_rest_applied() -> None:
@@ -42,7 +43,7 @@ def test_database_migrated_before_alembic_is_adopted_and_only_the_rest_applied()
         for migration in sorted(MIGRATIONS.glob("*.sql"))[:6]:
             connection.execute(migration.read_text(encoding="utf-8"))
 
-    assert apply_editor_migrations(DATABASE_URL, MIGRATIONS) == 1
+    assert apply_editor_migrations(DATABASE_URL, MIGRATIONS) == 2
     assert {"studio_import_drafts", "studio_import_decisions"} <= _tables()
 
 
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `MSYS_NO_PATHCONV=1 timeout 590 wsl -e bash /mnt/d/thoth-tmp/bu/pgtest.sh tests/operations/test_editor_migrations.py tests/operations/test_editor_migrations_postgres.py -p no:warnings`
Expected: FAIL. The migration list lacks `0008_source_accounts.sql`, `migration("0008_source_accounts.sql")` is missing, and the Postgres count is 7, not 8.

- [ ] **Step 3: Implement**

```bash
python D:/thoth-tmp/bu/sa/extract.py create 3 python/migrations/editor/0008_source_accounts.sql python/migrations/editor/alembic/versions/0008_source_accounts.py python/src/thoth_control_plane/infrastructure/source_account_models.py
python D:/thoth-tmp/bu/sa/extract.py apply 3 python/src/thoth_control_plane/operations/editor_migrations.py
```

Create `python/migrations/editor/0008_source_accounts.sql`:

```sql
-- Logged-in source accounts for acquisition, their per-platform policy, and the proxy pool.
-- Cookie sets and proxy URLs are Fernet tokens: only cookie names, their earliest expiry,
-- and a proxy's host:port are stored in clear. One proxy serves at most one account.

CREATE TABLE source_account_policies (
    platform TEXT PRIMARY KEY
        CHECK (platform IN ('tiktok', 'threads', 'instagram', 'x', 'youtube')),
    mode TEXT NOT NULL CHECK (mode IN ('anonymous', 'fallback', 'always')),
    min_spacing_seconds INTEGER NOT NULL DEFAULT 60
        CHECK (min_spacing_seconds BETWEEN 0 AND 86400),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE source_proxies (
    id UUID PRIMARY KEY,
    scheme TEXT NOT NULL CHECK (scheme IN ('http', 'https', 'socks5')),
    display TEXT NOT NULL CHECK (char_length(display) BETWEEN 3 AND 300),
    fingerprint TEXT NOT NULL UNIQUE CHECK (fingerprint ~ '^[0-9a-f]{64}$'),
    proxy_ciphertext BYTEA NOT NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE source_accounts (
    id UUID PRIMARY KEY,
    platform TEXT NOT NULL
        CHECK (platform IN ('tiktok', 'threads', 'instagram', 'x', 'youtube')),
    label TEXT NOT NULL CHECK (char_length(label) BETWEEN 1 AND 64),
    status TEXT NOT NULL CHECK (status IN ('healthy', 'cooldown', 'expired', 'disabled')),
    cooldown_level SMALLINT NOT NULL DEFAULT 0 CHECK (cooldown_level BETWEEN 0 AND 4),
    cooldown_until TIMESTAMPTZ,
    leased_until TIMESTAMPTZ,
    last_used_at TIMESTAMPTZ,
    last_outcome TEXT CHECK (last_outcome IN (
        'success', 'blocked', 'challenge', 'rate_limited', 'login_wall', 'undecryptable'
    )),
    success_count INTEGER NOT NULL DEFAULT 0 CHECK (success_count >= 0),
    failure_count INTEGER NOT NULL DEFAULT 0 CHECK (failure_count >= 0),
    cookies_ciphertext BYTEA NOT NULL,
    cookie_names JSONB NOT NULL CHECK (jsonb_typeof(cookie_names) = 'array'),
    cookies_earliest_expiry TIMESTAMPTZ,
    proxy_id UUID UNIQUE REFERENCES source_proxies (id) ON DELETE RESTRICT,
    created_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
    UNIQUE (platform, label)
);

-- Rotation picks the least recently used eligible account of one platform.
CREATE INDEX source_accounts_rotation_idx
    ON source_accounts (platform, status, last_used_at);
```

Create `python/migrations/editor/alembic/versions/0008_source_accounts.py`:

```python
"""Apply the shipped 0008_source_accounts.sql verbatim."""

from thoth_control_plane.operations.editor_migrations import execute_sql_file

revision = "0008"
down_revision = "0007"


def upgrade() -> None:
    execute_sql_file(__file__)
```

Create `python/src/thoth_control_plane/infrastructure/source_account_models.py`:

```python
"""SQLAlchemy ORM mapping of the source-account tables (editor migration 0008)."""

from __future__ import annotations

import uuid
from datetime import UTC, datetime
from typing import Any

from sqlalchemy import (
    JSON,
    DateTime,
    ForeignKey,
    Integer,
    LargeBinary,
    SmallInteger,
    String,
    TypeDecorator,
    Uuid,
)
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column


class UtcDateTime(TypeDecorator[datetime]):
    """Aware UTC in Python; `timestamptz` on Postgres, naive UTC on SQLite (tests)."""

    impl = DateTime(timezone=True)
    cache_ok = True

    def process_bind_param(self, value: datetime | None, dialect: Any) -> datetime | None:
        if value is None:
            return None
        value = value.astimezone(UTC)
        return value if dialect.name == "postgresql" else value.replace(tzinfo=None)

    def process_result_value(self, value: datetime | None, dialect: Any) -> datetime | None:
        if value is None:
            return None
        return value.replace(tzinfo=UTC) if value.tzinfo is None else value.astimezone(UTC)


class Base(DeclarativeBase):
    pass


class SourceAccountPolicyRow(Base):
    __tablename__ = "source_account_policies"

    platform: Mapped[str] = mapped_column(String, primary_key=True)
    mode: Mapped[str] = mapped_column(String)
    min_spacing_seconds: Mapped[int] = mapped_column(Integer, default=60)
    updated_at: Mapped[datetime] = mapped_column(UtcDateTime)


class SourceProxyRow(Base):
    __tablename__ = "source_proxies"

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    scheme: Mapped[str] = mapped_column(String)
    display: Mapped[str] = mapped_column(String)
    fingerprint: Mapped[str] = mapped_column(String, unique=True)
    proxy_ciphertext: Mapped[bytes] = mapped_column(LargeBinary)
    created_at: Mapped[datetime] = mapped_column(UtcDateTime)


class SourceAccountRow(Base):
    __tablename__ = "source_accounts"

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    platform: Mapped[str] = mapped_column(String)
    label: Mapped[str] = mapped_column(String)
    status: Mapped[str] = mapped_column(String)
    cooldown_level: Mapped[int] = mapped_column(SmallInteger, default=0)
    cooldown_until: Mapped[datetime | None] = mapped_column(UtcDateTime, nullable=True)
    leased_until: Mapped[datetime | None] = mapped_column(UtcDateTime, nullable=True)
    last_used_at: Mapped[datetime | None] = mapped_column(UtcDateTime, nullable=True)
    last_outcome: Mapped[str | None] = mapped_column(String, nullable=True)
    success_count: Mapped[int] = mapped_column(Integer, default=0)
    failure_count: Mapped[int] = mapped_column(Integer, default=0)
    cookies_ciphertext: Mapped[bytes] = mapped_column(LargeBinary)
    cookie_names: Mapped[list[str]] = mapped_column(JSON)
    cookies_earliest_expiry: Mapped[datetime | None] = mapped_column(UtcDateTime, nullable=True)
    proxy_id: Mapped[uuid.UUID | None] = mapped_column(
        Uuid, ForeignKey("source_proxies.id", ondelete="RESTRICT"), unique=True, nullable=True
    )
    created_at: Mapped[datetime] = mapped_column(UtcDateTime)
    updated_at: Mapped[datetime] = mapped_column(UtcDateTime)
```

Apply this patch to `python/src/thoth_control_plane/operations/editor_migrations.py`:

```diff
diff --git a/python/src/thoth_control_plane/operations/editor_migrations.py b/python/src/thoth_control_plane/operations/editor_migrations.py
--- a/python/src/thoth_control_plane/operations/editor_migrations.py
+++ b/python/src/thoth_control_plane/operations/editor_migrations.py
@@ -21,6 +21,7 @@ _LEGACY_MARKERS = {
     "0005": "render_jobs",
     "0006": "studio_review_events",
     "0007": "studio_import_drafts",
+    "0008": "source_accounts",
 }
 
 
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `MSYS_NO_PATHCONV=1 timeout 590 wsl -e bash /mnt/d/thoth-tmp/bu/pgtest.sh tests/operations/test_editor_migrations.py tests/operations/test_editor_migrations_postgres.py -p no:warnings`
Expected: PASS, with the three Postgres tests run, not skipped.

- [ ] **Step 5: Commit**

```bash
git add python/migrations/editor/0008_source_accounts.sql python/migrations/editor/alembic/versions/0008_source_accounts.py python/src/thoth_control_plane/infrastructure/source_account_models.py python/src/thoth_control_plane/operations/editor_migrations.py python/tests/operations/test_editor_migrations.py python/tests/operations/test_editor_migrations_postgres.py
git commit -m "feat(accounts): add the source-account tables to the editor schema"
```

---

### Task 4: Health rules, session access, and the store

**Files:**
- Create: `python/src/thoth_control_plane/acquisition/accounts/policy.py`, `accounts/access.py`
- Create: `python/src/thoth_control_plane/infrastructure/source_account_store.py`
- Test: `python/tests/acquisition/accounts/test_policy.py`, `test_access.py`
- Test: `python/tests/infrastructure/test_source_account_store.py`, `test_source_account_store_postgres.py`

**Interfaces:**
- Consumes: Task 1's `Vault`; Task 2's `CookieSet`, `PLATFORMS`, `ProxyImport`; Task 3's ORM rows.
- Produces:
  - `policy.py`:
    - `Mode`, `Status`, `Outcome`, `MODES`;
    - `DEFAULT_MODE = "fallback"`, `DEFAULT_SPACING_SECONDS = 60`, `MAX_SPACING_SECONDS = 86400`;
    - `LEASE = 10 min`, `COOLDOWN_STEPS = (15 min, 1 h, 6 h, 24 h)`;
    - `Health(status, cooldown_level, cooldown_until, success_count, failure_count)`;
    - `after(health, outcome, now) -> Health`.
  - `access.py`: `SessionAccess(cookies: CookieSet, proxy: str | None)`, whose `repr` hides the secrets, with these methods:
    - `browser_kwargs()`: `cookies` and `proxy` for `AsyncStealthySession`;
    - `request_kwargs()`: `cookies` and `proxy` for `AsyncFetcher.get`;
    - `yt_dlp_options(directory)`: writes `cookies.txt` with mode 0600, returns `cookiefile` and `proxy`.
  - `source_account_store.py`:
    - `SourceAccountStore(engine, vault, clock)` and `SourceAccountStore.connect(database_url, vault)`;
    - policies: `policies()`, `policy(platform)`, `set_policy(platform, mode, spacing)`;
    - accounts:
      - `accounts()`, `account(id)`;
      - `add_account(platform, label, cookies, proxy_id=None)`;
      - `replace_cookies(id, cookies)`;
      - `update_account(id, *, label=UNSET, proxy_id=UNSET, disabled=None)`;
      - `delete_account(id)`;
      - `record_check(id, valid)`, `access(id)`;
    - rotation: `lease(platform) -> AccountLease | None`, `report(account_id, outcome | None)`;
    - proxies: `proxies()`, `import_proxies(ProxyImport) -> ProxyImportResult`, `delete_proxy(id)`;
    - `SourceAccountError(code)` with `code` in `not_found | label_taken | proxy_in_use | proxy_not_found | platform_mismatch | undecryptable`;
    - the views `PolicyView`, `AccountView`, `ProxyView`, `ProxyImportResult`, `AccountLease(account_id, platform, access)`, and the sentinel `UNSET`.

The store is synchronous; async callers run it with `asyncio.to_thread`. Offline tests run it on SQLite (`StaticPool`), where `FOR UPDATE SKIP LOCKED` is ignored. The Postgres file proves the locking against the shipped schema. A row that fails to decrypt is marked `expired` with the outcome `undecryptable`, and the lease moves on, at most 5 times per call.

- [ ] **Step 1: Write the failing tests**

```bash
python D:/thoth-tmp/bu/sa/extract.py create 4 python/tests/acquisition/accounts/test_policy.py python/tests/acquisition/accounts/test_access.py python/tests/infrastructure/test_source_account_store.py python/tests/infrastructure/test_source_account_store_postgres.py
```

Create `python/tests/acquisition/accounts/test_policy.py`:

```python
"""Health rules for one reported outcome; pure."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest

from thoth_control_plane.acquisition.accounts.policy import COOLDOWN_STEPS, Health, after

NOW = datetime(2026, 10, 7, 12, 0, tzinfo=UTC)


def test_success_heals_and_counts() -> None:
    cooling = Health("cooldown", cooldown_level=3, cooldown_until=NOW, failure_count=2)
    assert after(cooling, "success", NOW) == Health(
        "healthy", cooldown_level=0, cooldown_until=None, success_count=1, failure_count=2
    )


@pytest.mark.parametrize("outcome", ["blocked", "challenge", "rate_limited"])
def test_blocks_climb_the_cooldown_ladder_and_stop_at_a_day(outcome: str) -> None:
    health = Health("healthy")
    seen = []
    for _ in range(6):
        health = after(health, outcome, NOW)  # type: ignore[arg-type]
        seen.append(health.cooldown_until - NOW)
    assert seen == [*COOLDOWN_STEPS, COOLDOWN_STEPS[-1], COOLDOWN_STEPS[-1]]
    assert (health.status, health.cooldown_level, health.failure_count) == ("cooldown", 4, 6)
    assert (
        timedelta(minutes=15),
        timedelta(hours=1),
        timedelta(hours=6),
        timedelta(hours=24),
    ) == COOLDOWN_STEPS


def test_a_login_wall_expires_the_account() -> None:
    assert after(Health("healthy"), "login_wall", NOW) == Health("expired", failure_count=1)


def test_an_undecryptable_account_expires_without_counting_a_failure() -> None:
    assert after(Health("healthy"), "undecryptable", NOW) == Health("expired")


def test_a_disabled_account_stays_disabled_whatever_happens() -> None:
    for outcome in ("success", "blocked", "login_wall"):
        assert after(Health("disabled"), outcome, NOW).status == "disabled"  # type: ignore[arg-type]
```

Create `python/tests/acquisition/accounts/test_access.py`:

```python
"""A leased session shaped for the browser, the request fetcher, and yt-dlp; no network."""

from __future__ import annotations

import stat
from datetime import UTC, datetime
from pathlib import Path

from thoth_control_plane.acquisition.accounts.access import SessionAccess
from thoth_control_plane.acquisition.accounts.cookies import parse_cookies

NOW = datetime(2026, 10, 7, tzinfo=UTC)
SECRET = "s3cr3t-session-value"
PROXY = "http://user:pr0xy-pa55@1.2.3.4:8080"
COOKIES = parse_cookies(
    "instagram",
    "\t".join([".instagram.com", "TRUE", "/", "TRUE", "1893456000", "sessionid", SECRET]) + "\n",
    now=NOW,
)


def test_each_access_path_gets_the_cookies_and_the_proxy() -> None:
    access = SessionAccess(COOKIES, PROXY)
    browser = access.browser_kwargs()
    assert browser["proxy"] == PROXY
    assert [c["value"] for c in browser["cookies"]] == [SECRET]
    assert access.request_kwargs() == {"cookies": {"sessionid": SECRET}, "proxy": PROXY}


def test_without_a_proxy_no_proxy_argument_is_passed() -> None:
    access = SessionAccess(COOKIES)
    assert "proxy" not in access.browser_kwargs()
    assert "proxy" not in access.request_kwargs()


def test_the_yt_dlp_cookie_file_is_private_and_readable_by_yt_dlp(tmp_path: Path) -> None:
    options = SessionAccess(COOKIES, PROXY).yt_dlp_options(tmp_path)
    path = Path(options["cookiefile"])
    assert options["proxy"] == PROXY
    assert parse_cookies("instagram", path.read_text(encoding="utf-8"), now=NOW) == COOKIES
    assert stat.S_IMODE(path.stat().st_mode) == 0o600


def test_a_session_never_prints_its_secrets() -> None:
    text = repr(SessionAccess(COOKIES, PROXY)) + str(SessionAccess(COOKIES, PROXY)) + repr(COOKIES)
    assert SECRET not in text and "pr0xy-pa55" not in text
```

Create `python/tests/infrastructure/test_source_account_store.py`:

```python
"""The source-account store on an in-memory SQLite database; Postgres locking is tested apart."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest
from cryptography.fernet import Fernet
from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session
from sqlalchemy.pool import StaticPool

from thoth_control_plane.acquisition.accounts.cookies import parse_cookies
from thoth_control_plane.acquisition.accounts.proxies import parse_proxy_list
from thoth_control_plane.acquisition.accounts.vault import Vault
from thoth_control_plane.infrastructure.source_account_models import Base, SourceAccountRow
from thoth_control_plane.infrastructure.source_account_store import (
    SourceAccountError,
    SourceAccountStore,
)

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
    engine = create_engine(
        "sqlite://", poolclass=StaticPool, connect_args={"check_same_thread": False}
    )
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
    assert {(p.platform, p.mode, p.min_spacing_seconds) for p in store.policies()} == {
        (platform, "fallback", 60)
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
```

Create `python/tests/infrastructure/test_source_account_store_postgres.py`:

```python
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
    store.report(store.lease("instagram").account_id, "blocked")
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
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `MSYS_NO_PATHCONV=1 timeout 590 wsl -e bash /mnt/d/thoth-tmp/bu/pgtest.sh tests/acquisition/accounts tests/infrastructure/test_source_account_store.py tests/infrastructure/test_source_account_store_postgres.py -p no:warnings`
Expected: FAIL with `ModuleNotFoundError` for `accounts.policy`, `accounts.access`, and `infrastructure.source_account_store`.

- [ ] **Step 3: Implement**

```bash
python D:/thoth-tmp/bu/sa/extract.py create 4 python/src/thoth_control_plane/acquisition/accounts/policy.py python/src/thoth_control_plane/acquisition/accounts/access.py python/src/thoth_control_plane/infrastructure/source_account_store.py
```

Create `python/src/thoth_control_plane/acquisition/accounts/policy.py`:

```python
"""Rotation and health rules for source accounts; pure, so every rule is testable alone."""

from __future__ import annotations

from dataclasses import dataclass, replace
from datetime import datetime, timedelta
from typing import Literal

Mode = Literal["anonymous", "fallback", "always"]
Status = Literal["healthy", "cooldown", "expired", "disabled"]
Outcome = Literal["success", "blocked", "challenge", "rate_limited", "login_wall", "undecryptable"]
MODES: tuple[Mode, ...] = ("anonymous", "fallback", "always")
DEFAULT_MODE: Mode = "fallback"
DEFAULT_SPACING_SECONDS = 60
MAX_SPACING_SECONDS = 86_400
# Longer than the 5-minute acquisition activity, so only a dead holder's lease ever expires.
LEASE = timedelta(minutes=10)
COOLDOWN_STEPS = (
    timedelta(minutes=15),
    timedelta(hours=1),
    timedelta(hours=6),
    timedelta(hours=24),
)
COOLING_OUTCOMES = ("blocked", "challenge", "rate_limited")


@dataclass(frozen=True)
class Health:
    status: Status
    cooldown_level: int = 0
    cooldown_until: datetime | None = None
    success_count: int = 0
    failure_count: int = 0


def after(health: Health, outcome: Outcome, now: datetime) -> Health:
    """The account's health once an acquisition reports `outcome`.

    A `disabled` account keeps its status: only the dashboard enables it again.
    """
    if outcome == "success":
        new = replace(
            health,
            status="healthy",
            cooldown_level=0,
            cooldown_until=None,
            success_count=health.success_count + 1,
        )
    elif outcome in COOLING_OUTCOMES:
        level = min(health.cooldown_level + 1, len(COOLDOWN_STEPS))
        new = replace(
            health,
            status="cooldown",
            cooldown_level=level,
            cooldown_until=now + COOLDOWN_STEPS[level - 1],
            failure_count=health.failure_count + 1,
        )
    elif outcome == "login_wall":
        new = replace(health, status="expired", failure_count=health.failure_count + 1)
    else:
        new = replace(health, status="expired")
    return replace(new, status="disabled") if health.status == "disabled" else new
```

Create `python/src/thoth_control_plane/acquisition/accounts/access.py`:

```python
"""One leased session: the decrypted cookies and proxy, shaped for each access path."""

from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from thoth_control_plane.acquisition.accounts.cookies import CookieSet

COOKIE_FILE_NAME = "cookies.txt"


@dataclass(frozen=True)
class SessionAccess:
    cookies: CookieSet
    proxy: str | None = None

    def __repr__(self) -> str:
        # The cookies and the proxy are secrets; a repr must never print them.
        return f"SessionAccess(platform={self.cookies.platform!r})"

    def browser_kwargs(self) -> dict[str, Any]:
        """Extra `AsyncStealthySession` arguments: the cookies, and the proxy if any."""
        kwargs: dict[str, Any] = {"cookies": self.cookies.to_playwright()}
        if self.proxy:
            kwargs["proxy"] = self.proxy
        return kwargs

    def request_kwargs(self) -> dict[str, Any]:
        """Extra `AsyncFetcher.get` arguments: the cookies, and the proxy if any."""
        kwargs: dict[str, Any] = {"cookies": self.cookies.to_request()}
        if self.proxy:
            kwargs["proxy"] = self.proxy
        return kwargs

    def yt_dlp_options(self, directory: Path) -> dict[str, Any]:
        """yt-dlp options; writes the cookie file (mode 0600) into `directory`.

        The caller owns `directory` and removes it once yt-dlp is done.
        """
        path = directory / COOKIE_FILE_NAME
        descriptor = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
        with os.fdopen(descriptor, "w", encoding="utf-8") as handle:
            handle.write(self.cookies.to_netscape())
        options: dict[str, Any] = {"cookiefile": str(path)}
        if self.proxy:
            options["proxy"] = self.proxy
        return options
```

Create `python/src/thoth_control_plane/infrastructure/source_account_store.py`:

```python
"""Source accounts, their per-platform policy, and the proxy pool, on SQLAlchemy ORM.

Synchronous: async callers run it in a worker thread. Cookie sets and proxy URLs are sealed
by the vault before they reach a row and opened only to build a `SessionAccess`. Errors are
`SourceAccountError` codes; none carries a secret.
"""

from __future__ import annotations

import uuid
from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Any, Final

from sqlalchemy import and_, create_engine, or_, select
from sqlalchemy.engine import Engine, make_url
from sqlalchemy.orm import Session, sessionmaker

from thoth_control_plane.acquisition.accounts.access import SessionAccess
from thoth_control_plane.acquisition.accounts.cookies import PLATFORMS, CookieSet, Platform
from thoth_control_plane.acquisition.accounts.policy import (
    DEFAULT_MODE,
    DEFAULT_SPACING_SECONDS,
    LEASE,
    Health,
    Mode,
    Outcome,
    after,
)
from thoth_control_plane.acquisition.accounts.proxies import ProxyImport
from thoth_control_plane.acquisition.accounts.vault import Vault, VaultError
from thoth_control_plane.infrastructure.source_account_models import (
    SourceAccountPolicyRow,
    SourceAccountRow,
    SourceProxyRow,
)

UNSET: Final = object()
# A lease skips at most this many undecryptable accounts before giving up for this call.
MAX_LEASE_ATTEMPTS = 5


class SourceAccountError(Exception):
    def __init__(self, code: str) -> None:
        super().__init__(code)
        self.code = code


@dataclass(frozen=True)
class PolicyView:
    platform: Platform
    mode: Mode
    min_spacing_seconds: int


@dataclass(frozen=True)
class AccountView:
    id: str
    platform: Platform
    label: str
    status: str
    cooldown_until: datetime | None
    last_used_at: datetime | None
    last_outcome: str | None
    success_count: int
    failure_count: int
    cookie_names: tuple[str, ...]
    cookies_earliest_expiry: datetime | None
    proxy_id: str | None
    proxy_display: str | None
    created_at: datetime
    updated_at: datetime


@dataclass(frozen=True)
class ProxyView:
    id: str
    scheme: str
    display: str
    account_platform: str | None
    account_label: str | None


@dataclass(frozen=True)
class ProxyImportResult:
    added: int
    duplicates: int
    invalid_lines: tuple[int, ...]


@dataclass(frozen=True)
class AccountLease:
    account_id: str
    platform: Platform
    access: SessionAccess


def _uuid(value: str) -> uuid.UUID:
    try:
        return uuid.UUID(value)
    except (TypeError, ValueError):
        raise SourceAccountError("not_found") from None


class SourceAccountStore:
    def __init__(
        self,
        engine: Engine,
        vault: Vault,
        clock: Callable[[], datetime] = lambda: datetime.now(UTC),
    ) -> None:
        self._sessions = sessionmaker(engine, expire_on_commit=False)
        self._vault = vault
        self._clock = clock

    @classmethod
    def connect(cls, database_url: str, vault: Vault) -> SourceAccountStore:
        url = make_url(database_url).set(drivername="postgresql+psycopg")
        return cls(create_engine(url, pool_pre_ping=True, pool_size=2, max_overflow=2), vault)

    # Policies

    def policies(self) -> list[PolicyView]:
        with self._sessions() as session:
            rows = {row.platform: row for row in session.scalars(select(SourceAccountPolicyRow))}
        return [self._policy_view(platform, rows.get(platform)) for platform in PLATFORMS]

    def policy(self, platform: Platform) -> PolicyView:
        with self._sessions() as session:
            return self._policy_view(platform, session.get(SourceAccountPolicyRow, platform))

    def set_policy(self, platform: Platform, mode: Mode, min_spacing_seconds: int) -> PolicyView:
        with self._sessions.begin() as session:
            row = session.get(SourceAccountPolicyRow, platform)
            if row is None:
                row = SourceAccountPolicyRow(platform=platform)
                session.add(row)
            row.mode, row.min_spacing_seconds = mode, min_spacing_seconds
            row.updated_at = self._clock()
        return self._policy_view(platform, row)

    @staticmethod
    def _policy_view(platform: Platform, row: SourceAccountPolicyRow | None) -> PolicyView:
        if row is None:
            return PolicyView(platform, DEFAULT_MODE, DEFAULT_SPACING_SECONDS)
        return PolicyView(platform, row.mode, row.min_spacing_seconds)  # type: ignore[arg-type]

    # Accounts

    def accounts(self) -> list[AccountView]:
        with self._sessions() as session:
            rows = session.scalars(
                select(SourceAccountRow).order_by(SourceAccountRow.platform, SourceAccountRow.label)
            ).all()
            return [self._account_view(session, row) for row in rows]

    def account(self, account_id: str) -> AccountView:
        with self._sessions() as session:
            return self._account_view(session, self._row(session, account_id))

    def add_account(
        self, platform: Platform, label: str, cookies: CookieSet, proxy_id: str | None = None
    ) -> AccountView:
        now = self._clock()
        with self._sessions.begin() as session:
            self._require_free_label(session, platform, label)
            row = SourceAccountRow(
                id=uuid.uuid4(),
                platform=platform,
                label=label,
                status="healthy",
                cooldown_level=0,
                success_count=0,
                failure_count=0,
                created_at=now,
                updated_at=now,
            )
            self._set_cookies(row, cookies)
            row.proxy_id = self._free_proxy(session, proxy_id, None)
            session.add(row)
            session.flush()
            return self._account_view(session, row)

    def replace_cookies(self, account_id: str, cookies: CookieSet) -> AccountView:
        with self._sessions.begin() as session:
            row = self._row(session, account_id)
            if cookies.platform != row.platform:
                raise SourceAccountError("platform_mismatch")
            self._set_cookies(row, cookies)
            if row.status != "disabled":
                row.status = "healthy"
            row.cooldown_level, row.cooldown_until = 0, None
            row.updated_at = self._clock()
            return self._account_view(session, row)

    def update_account(
        self,
        account_id: str,
        *,
        label: Any = UNSET,
        proxy_id: Any = UNSET,
        disabled: bool | None = None,
    ) -> AccountView:
        with self._sessions.begin() as session:
            row = self._row(session, account_id)
            if label is not UNSET and label != row.label:
                self._require_free_label(session, row.platform, label)
                row.label = label
            if proxy_id is not UNSET:
                row.proxy_id = self._free_proxy(session, proxy_id, row.id)
            if disabled is True:
                row.status = "disabled"
            elif disabled is False and row.status == "disabled":
                row.status, row.cooldown_level, row.cooldown_until = "healthy", 0, None
            row.updated_at = self._clock()
            session.flush()
            return self._account_view(session, row)

    def delete_account(self, account_id: str) -> None:
        with self._sessions.begin() as session:
            session.delete(self._row(session, account_id))

    def record_check(self, account_id: str, valid: bool) -> AccountView:
        """A manual session check: valid makes the account healthy, invalid expires it."""
        with self._sessions.begin() as session:
            row = self._row(session, account_id)
            if row.status != "disabled":
                row.status = "healthy" if valid else "expired"
                if valid:
                    row.cooldown_level, row.cooldown_until = 0, None
            row.last_outcome = "success" if valid else "login_wall"
            row.updated_at = self._clock()
            return self._account_view(session, row)

    def access(self, account_id: str) -> SessionAccess:
        """The account's session, for a manual check; an unreadable one is expired."""
        with self._sessions.begin() as session:
            row = self._row(session, account_id)
            try:
                return self._open(session, row)
            except VaultError:
                row.status, row.last_outcome = "expired", "undecryptable"
        raise SourceAccountError("undecryptable")

    # Rotation

    def lease(self, platform: Platform) -> AccountLease | None:
        """The least recently used eligible account, held for `LEASE`; None when none is."""
        for _ in range(MAX_LEASE_ATTEMPTS):
            now = self._clock()
            spacing = timedelta(seconds=self.policy(platform).min_spacing_seconds)
            with self._sessions.begin() as session:
                row = session.scalars(
                    select(SourceAccountRow)
                    .where(
                        SourceAccountRow.platform == platform,
                        or_(
                            SourceAccountRow.status == "healthy",
                            and_(
                                SourceAccountRow.status == "cooldown",
                                SourceAccountRow.cooldown_until <= now,
                            ),
                        ),
                        or_(
                            SourceAccountRow.leased_until.is_(None),
                            SourceAccountRow.leased_until <= now,
                        ),
                        or_(
                            SourceAccountRow.last_used_at.is_(None),
                            SourceAccountRow.last_used_at <= now - spacing,
                        ),
                    )
                    .order_by(SourceAccountRow.last_used_at.asc().nulls_first())
                    .limit(1)
                    .with_for_update(skip_locked=True)
                ).first()
                if row is None:
                    return None
                try:
                    access = self._open(session, row)
                except VaultError:
                    row.status, row.last_outcome, row.updated_at = "expired", "undecryptable", now
                    continue
                row.leased_until, row.last_used_at = now + LEASE, now
                return AccountLease(str(row.id), platform, access)
        return None

    def report(self, account_id: str, outcome: Outcome | None) -> None:
        """Release a lease; `outcome` None releases it without touching the account's health."""
        now = self._clock()
        with self._sessions.begin() as session:
            row = session.get(SourceAccountRow, _uuid(account_id))
            if row is None:
                return
            row.leased_until = None
            if outcome is not None:
                health = after(
                    Health(
                        status=row.status,  # type: ignore[arg-type]
                        cooldown_level=row.cooldown_level,
                        cooldown_until=row.cooldown_until,
                        success_count=row.success_count,
                        failure_count=row.failure_count,
                    ),
                    outcome,
                    now,
                )
                row.status, row.cooldown_level = health.status, health.cooldown_level
                row.cooldown_until = health.cooldown_until
                row.success_count, row.failure_count = health.success_count, health.failure_count
                row.last_outcome = outcome
            row.updated_at = now

    # Proxies

    def proxies(self) -> list[ProxyView]:
        with self._sessions() as session:
            holders = {
                row.proxy_id: row
                for row in session.scalars(
                    select(SourceAccountRow).where(SourceAccountRow.proxy_id.is_not(None))
                )
            }
            rows = session.scalars(select(SourceProxyRow).order_by(SourceProxyRow.created_at))
            return [
                ProxyView(
                    id=str(row.id),
                    scheme=row.scheme,
                    display=row.display,
                    account_platform=holders[row.id].platform if row.id in holders else None,
                    account_label=holders[row.id].label if row.id in holders else None,
                )
                for row in rows
            ]

    def import_proxies(self, parsed: ProxyImport) -> ProxyImportResult:
        added = duplicates = 0
        now = self._clock()
        with self._sessions.begin() as session:
            for entry in parsed.entries:
                fingerprint = self._vault.fingerprint(entry.url)
                exists = session.scalars(
                    select(SourceProxyRow.id).where(SourceProxyRow.fingerprint == fingerprint)
                ).first()
                if exists is not None:
                    duplicates += 1
                    continue
                session.add(
                    SourceProxyRow(
                        id=uuid.uuid4(),
                        scheme=entry.scheme,
                        display=entry.display,
                        fingerprint=fingerprint,
                        proxy_ciphertext=self._vault.seal(entry.url),
                        created_at=now,
                    )
                )
                added += 1
        return ProxyImportResult(added, duplicates, parsed.invalid_lines)

    def delete_proxy(self, proxy_id: str) -> None:
        with self._sessions.begin() as session:
            row = session.get(SourceProxyRow, _uuid(proxy_id))
            if row is None:
                raise SourceAccountError("not_found")
            if self._holder(session, row.id) is not None:
                raise SourceAccountError("proxy_in_use")
            session.delete(row)

    # Helpers

    def _row(self, session: Session, account_id: str) -> SourceAccountRow:
        row = session.get(SourceAccountRow, _uuid(account_id))
        if row is None:
            raise SourceAccountError("not_found")
        return row

    @staticmethod
    def _holder(session: Session, proxy_id: uuid.UUID) -> SourceAccountRow | None:
        return session.scalars(
            select(SourceAccountRow).where(SourceAccountRow.proxy_id == proxy_id)
        ).first()

    def _require_free_label(self, session: Session, platform: str, label: str) -> None:
        taken = session.scalars(
            select(SourceAccountRow.id).where(
                SourceAccountRow.platform == platform, SourceAccountRow.label == label
            )
        ).first()
        if taken is not None:
            raise SourceAccountError("label_taken")

    def _free_proxy(
        self, session: Session, proxy_id: str | None, owner: uuid.UUID | None
    ) -> uuid.UUID | None:
        if proxy_id is None:
            return None
        key = _uuid(proxy_id)
        if session.get(SourceProxyRow, key) is None:
            raise SourceAccountError("proxy_not_found")
        holder = self._holder(session, key)
        if holder is not None and holder.id != owner:
            raise SourceAccountError("proxy_in_use")
        return key

    def _set_cookies(self, row: SourceAccountRow, cookies: CookieSet) -> None:
        row.cookies_ciphertext = self._vault.seal(cookies.to_json())
        row.cookie_names = cookies.names()
        row.cookies_earliest_expiry = cookies.earliest_expiry()

    def _open(self, session: Session, row: SourceAccountRow) -> SessionAccess:
        cookies = CookieSet.from_json(
            row.platform,  # type: ignore[arg-type]
            self._vault.open(row.cookies_ciphertext),
        )
        proxy = None
        if row.proxy_id is not None:
            proxy_row = session.get(SourceProxyRow, row.proxy_id)
            proxy = self._vault.open(proxy_row.proxy_ciphertext) if proxy_row else None
        return SessionAccess(cookies, proxy)

    @staticmethod
    def _account_view(session: Session, row: SourceAccountRow) -> AccountView:
        proxy = session.get(SourceProxyRow, row.proxy_id) if row.proxy_id else None
        return AccountView(
            id=str(row.id),
            platform=row.platform,  # type: ignore[arg-type]
            label=row.label,
            status=row.status,
            cooldown_until=row.cooldown_until,
            last_used_at=row.last_used_at,
            last_outcome=row.last_outcome,
            success_count=row.success_count,
            failure_count=row.failure_count,
            cookie_names=tuple(row.cookie_names),
            cookies_earliest_expiry=row.cookies_earliest_expiry,
            proxy_id=str(row.proxy_id) if row.proxy_id else None,
            proxy_display=proxy.display if proxy else None,
            created_at=row.created_at,
            updated_at=row.updated_at,
        )
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `MSYS_NO_PATHCONV=1 timeout 590 wsl -e bash /mnt/d/thoth-tmp/bu/pgtest.sh tests/acquisition/accounts tests/infrastructure/test_source_account_store.py tests/infrastructure/test_source_account_store_postgres.py -p no:warnings`
Expected: PASS, with the three Postgres store tests run, not skipped.

- [ ] **Step 5: Commit**

```bash
git add python/src/thoth_control_plane/acquisition/accounts python/src/thoth_control_plane/infrastructure/source_account_store.py python/tests/acquisition/accounts python/tests/infrastructure/test_source_account_store.py python/tests/infrastructure/test_source_account_store_postgres.py
git commit -m "feat(accounts): rotate source accounts with leases and a cooldown ladder"
```

---

### Task 5: A session reaches every access path

**Files:**
- Modify: `python/src/thoth_control_plane/acquisition/registry.py`
- Test: `python/tests/acquisition/test_registry.py`

**Interfaces:**
- Consumes: Task 4's `SessionAccess`.
- Produces: `acquirer_for(source_url, *, client, materializer, access: SessionAccess | None = None, scratch: Path | None = None)`. With `access`, the session is wired into every access path:
  - every Scrapling session factory gets the `cookies` and `proxy` arguments;
  - every request fetcher's `get` is `partial(_scrapling_get, cookies=…, proxy=…)`;
  - yt-dlp's factory adds `cookiefile` (written into `scratch`) and `proxy`.

  A YouTube session without `scratch` raises `ValueError`. Without `access`, the acquirers get exactly today's defaults.

- [ ] **Step 1: Write the failing tests**

```bash
python D:/thoth-tmp/bu/sa/extract.py apply 5 python/tests/acquisition/test_registry.py
```

Apply this patch to `python/tests/acquisition/test_registry.py`:

```diff
diff --git a/python/tests/acquisition/test_registry.py b/python/tests/acquisition/test_registry.py
--- a/python/tests/acquisition/test_registry.py
+++ b/python/tests/acquisition/test_registry.py
@@ -2,9 +2,15 @@
 
 from __future__ import annotations
 
+from datetime import UTC, datetime
+from pathlib import Path
+
 import httpx
 import pytest
 
+from thoth_control_plane.acquisition import browser, registry, threads_service, youtube_service
+from thoth_control_plane.acquisition.accounts.access import SessionAccess
+from thoth_control_plane.acquisition.accounts.cookies import parse_cookies
 from thoth_control_plane.acquisition.instagram_service import InstagramAcquirer
 from thoth_control_plane.acquisition.materializer import (
     MediaMaterializer,
@@ -45,3 +51,85 @@ async def test_acquirer_for_routes_tiktok_and_refuses_legacy_hosts() -> None:
             "https://youtu.be/abcDEF123_-", client=client, materializer=materializer
         )
         assert isinstance(youtube, YouTubeAcquirer)
+
+
+COOKIES = parse_cookies(
+    "instagram",
+    "\t".join([".instagram.com", "TRUE", "/", "TRUE", "1893456000", "sessionid", "s"]) + "\n",
+    now=datetime(2026, 10, 7, tzinfo=UTC),
+)
+PROXY = "http://u:p@1.2.3.4:8080"
+
+
+@pytest.mark.asyncio
+async def test_a_session_reaches_every_access_path(
+    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
+) -> None:
+    seen: dict[str, dict] = {}
+    monkeypatch.setattr(
+        registry, "_default_session_factory", lambda **kw: seen.setdefault("browser", kw)
+    )
+    monkeypatch.setattr(
+        registry, "_default_factory", lambda options: seen.setdefault("yt", options)
+    )
+
+    async def fake_get(url: str, **kwargs: object) -> None:
+        seen["request"] = kwargs
+
+    monkeypatch.setattr(registry, "_scrapling_get", fake_get)
+    access = SessionAccess(COOKIES, PROXY)
+    async with httpx.AsyncClient() as client:
+        materializer = MediaMaterializer(client, resolve_host_via_getaddrinfo)
+        instagram = acquirer_for(
+            "https://www.instagram.com/p/abc/",
+            client=client,
+            materializer=materializer,
+            access=access,
+        )
+        await instagram._request._get("https://www.instagram.com/p/abc/", impersonate="chrome")
+        instagram._headless._session_factory(headless=True, max_pages=1)
+        youtube = acquirer_for(
+            "https://youtu.be/abcDEF123_-",
+            client=client,
+            materializer=materializer,
+            access=access,
+            scratch=tmp_path,
+        )
+        youtube._client._factory({"quiet": True})
+    assert seen["request"] == {
+        "impersonate": "chrome",
+        "cookies": {"sessionid": "s"},
+        "proxy": PROXY,
+    }
+    assert (seen["browser"]["headless"], seen["browser"]["proxy"]) == (True, PROXY)
+    assert [c["name"] for c in seen["browser"]["cookies"]] == ["sessionid"]
+    assert (seen["yt"]["quiet"], seen["yt"]["proxy"]) == (True, PROXY)
+    assert Path(seen["yt"]["cookiefile"]).parent == tmp_path
+
+
+@pytest.mark.asyncio
+async def test_without_a_session_the_default_access_is_untouched() -> None:
+    async with httpx.AsyncClient() as client:
+        materializer = MediaMaterializer(client, resolve_host_via_getaddrinfo)
+        instagram = acquirer_for(
+            "https://www.instagram.com/p/abc/", client=client, materializer=materializer
+        )
+        youtube = acquirer_for(
+            "https://youtu.be/abcDEF123_-", client=client, materializer=materializer
+        )
+    assert instagram._request._get is threads_service._scrapling_get
+    assert instagram._headless._session_factory is browser._default_session_factory
+    assert youtube._client._factory is youtube_service._default_factory
+
+
+@pytest.mark.asyncio
+async def test_a_yt_dlp_session_needs_a_scratch_directory() -> None:
+    async with httpx.AsyncClient() as client:
+        materializer = MediaMaterializer(client, resolve_host_via_getaddrinfo)
+        with pytest.raises(ValueError):
+            acquirer_for(
+                "https://youtu.be/abcDEF123_-",
+                client=client,
+                materializer=materializer,
+                access=SessionAccess(COOKIES),
+            )
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `MSYS_NO_PATHCONV=1 timeout 590 wsl -e bash /mnt/d/thoth-tmp/bu/pt.sh tests/acquisition/test_registry.py -p no:warnings`
Expected: 2 FAIL: `AttributeError` (`registry` has no `_default_session_factory` to patch) and `TypeError: acquirer_for() got an unexpected keyword argument 'access'`.

- [ ] **Step 3: Implement**

```bash
python D:/thoth-tmp/bu/sa/extract.py apply 5 python/src/thoth_control_plane/acquisition/registry.py
```

Apply this patch to `python/src/thoth_control_plane/acquisition/registry.py`:

```diff
diff --git a/python/src/thoth_control_plane/acquisition/registry.py b/python/src/thoth_control_plane/acquisition/registry.py
--- a/python/src/thoth_control_plane/acquisition/registry.py
+++ b/python/src/thoth_control_plane/acquisition/registry.py
@@ -2,13 +2,19 @@
 
 from __future__ import annotations
 
+from collections.abc import Awaitable, Callable
+from functools import partial
 from pathlib import Path
-from typing import Protocol
+from typing import Any, Protocol
 
 import httpx
 
+from thoth_control_plane.acquisition.accounts.access import SessionAccess
 from thoth_control_plane.acquisition.adapters.tikwm import TikWmResolver
-from thoth_control_plane.acquisition.browser import ScraplingHeadlessBrowser
+from thoth_control_plane.acquisition.browser import (
+    ScraplingHeadlessBrowser,
+    _default_session_factory,
+)
 from thoth_control_plane.acquisition.instagram_service import (
     InstagramAcquirer,
     InstagramHeadlessBrowser,
@@ -22,6 +28,7 @@ from thoth_control_plane.acquisition.threads_service import (
     ThreadsAcquirer,
     ThreadsHeadlessBrowser,
     ThreadsRequestFetcher,
+    _scrapling_get,
 )
 from thoth_control_plane.acquisition.x_service import (
     XAcquirer,
@@ -32,6 +39,7 @@ from thoth_control_plane.acquisition.youtube_service import (
     YouTubeAcquirer,
     YouTubeHeadlessBrowser,
     YtDlpClient,
+    _default_factory,
 )
 
 
@@ -43,22 +51,62 @@ class Acquirer(Protocol):
     ) -> AcquisitionResult: ...
 
 
+def _browser_factory(access: SessionAccess | None) -> Callable[..., Any]:
+    if access is None:
+        return _default_session_factory
+    extra = access.browser_kwargs()
+    return lambda **kwargs: _default_session_factory(**kwargs, **extra)
+
+
+def _request_get(access: SessionAccess | None) -> Callable[..., Awaitable[Any]] | None:
+    return None if access is None else partial(_scrapling_get, **access.request_kwargs())
+
+
+def _yt_dlp_factory(
+    access: SessionAccess | None, scratch: Path | None
+) -> Callable[[dict[str, Any]], Any] | None:
+    if access is None:
+        return None
+    if scratch is None:
+        raise ValueError("a yt-dlp session needs a scratch directory for its cookie file")
+    extra = access.yt_dlp_options(scratch)
+    return lambda options: _default_factory({**options, **extra})
+
+
 def acquirer_for(
-    source_url: str, *, client: httpx.AsyncClient, materializer: MediaMaterializer
+    source_url: str,
+    *,
+    client: httpx.AsyncClient,
+    materializer: MediaMaterializer,
+    access: SessionAccess | None = None,
+    scratch: Path | None = None,
 ) -> Acquirer:
+    """The platform's acquirer; with `access`, every request and browser carries the session.
+
+    `scratch` is a private directory the caller removes afterwards; yt-dlp reads its cookie
+    file from there.
+    """
     platform = platform_of(source_url)
+    browser = _browser_factory(access)
+    get = _request_get(access)
     if platform == "tiktok":
         return TikTokAcquisitionService(
-            ScraplingHeadlessBrowser(), TikWmResolver(client), materializer
+            ScraplingHeadlessBrowser(browser), TikWmResolver(client), materializer
         )
     if platform == "threads":
-        return ThreadsAcquirer(ThreadsRequestFetcher(), ThreadsHeadlessBrowser(), materializer)
+        return ThreadsAcquirer(
+            ThreadsRequestFetcher(get), ThreadsHeadlessBrowser(browser), materializer
+        )
     if platform == "instagram":
         return InstagramAcquirer(
-            InstagramRequestFetcher(), InstagramHeadlessBrowser(), materializer
+            InstagramRequestFetcher(get), InstagramHeadlessBrowser(browser), materializer
         )
     if platform == "x":
-        return XAcquirer(XRequestFetcher(), XHeadlessBrowser(), materializer)
+        return XAcquirer(XRequestFetcher(get), XHeadlessBrowser(browser), materializer)
     if platform == "youtube":
-        return YouTubeAcquirer(YtDlpClient(), YouTubeHeadlessBrowser(), materializer)
+        return YouTubeAcquirer(
+            YtDlpClient(_yt_dlp_factory(access, scratch)),
+            YouTubeHeadlessBrowser(browser),
+            materializer,
+        )
     raise LookupError("no python acquirer for this platform")
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `MSYS_NO_PATHCONV=1 timeout 590 wsl -e bash /mnt/d/thoth-tmp/bu/pt.sh tests/acquisition -p no:warnings`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add python/src/thoth_control_plane/acquisition/registry.py python/tests/acquisition/test_registry.py
git commit -m "feat(accounts): carry a leased session through every access path"
```

---

### Task 6: The `login_wall` attempt reason

**Files:**
- Modify: `python/src/thoth_control_plane/acquisition/models.py` (`AcquisitionReason.LOGIN_WALL`, `failure_code`)
- Modify: `python/src/thoth_control_plane/domain/models.py` (`login_wall` in `SOURCE_EVENT_REASONS`)
- Modify: `threads_service.py`, `instagram_service.py`, `x_service.py`, `youtube_service.py`, `registry.py` (in `acquisition/`)
- Test: `test_models.py`, `test_youtube_service.py`, `test_instagram_acquirer.py`, `test_instagram_service.py`, `test_threads_service.py`, `test_x_service.py` (in `python/tests/acquisition/`)
- Test: `python/tests/activities/test_source_investigation.py`, `python/tests/domain/test_models.py`

**Interfaces:**
- Consumes: Task 5's `acquirer_for(..., access=...)`.
- Produces:
  - `AcquisitionReason.LOGIN_WALL` (`"login_wall"`).
  - `failure_code(reason) -> str`, which gives `"request_blocked"` for `LOGIN_WALL` and `reason.value` otherwise. Every place that turns a reason into an `AcquisitionFailure.code` uses it.
  - Fetchers raise `RequestFetchError(LOGIN_WALL)` for a sign-in page:
    - Threads `/login`;
    - Instagram `/accounts/login`, `/login`, and the `require_login` payload;
    - X `/i/flow/login`, `/login`.
  - A flagged-account page (Instagram `/challenge`, X `/account/access`) stays `REQUEST_BLOCKED`.
  - `classify(error, *, signed_in=False)` turns a sign-in demand into `LOGIN_WALL` only when `signed_in`.
  - `YtDlpClient(factory, *, signed_in=False)`, which the registry builds with `signed_in=access is not None`.

`SOURCE_EVENT_REASONS` must admit `login_wall`. Otherwise the activity fails while building a progress event for any attempt with that reason; the activity test below reproduces that.

- [ ] **Step 1: Write the failing tests**

```bash
python D:/thoth-tmp/bu/sa/extract.py apply 6 python/tests/acquisition/test_models.py python/tests/acquisition/test_youtube_service.py python/tests/acquisition/test_instagram_acquirer.py python/tests/acquisition/test_instagram_service.py python/tests/acquisition/test_threads_service.py python/tests/acquisition/test_x_service.py python/tests/activities/test_source_investigation.py python/tests/domain/test_models.py
```

Apply this patch to `python/tests/acquisition/test_models.py`:

```diff
diff --git a/python/tests/acquisition/test_models.py b/python/tests/acquisition/test_models.py
--- a/python/tests/acquisition/test_models.py
+++ b/python/tests/acquisition/test_models.py
@@ -28,6 +28,7 @@ from thoth_control_plane.acquisition.models import (
     TikTokPost,
     TikTokSourceReport,
     TrendingDiscovery,
+    failure_code,
 )
 
 
@@ -547,3 +548,12 @@ def test_neutral_result_requires_exactly_one_outcome() -> None:
         AcquisitionResult(
             report=_v3(), failure=AcquisitionFailure(code="no_content", retryable=False)
         )
+
+
+def test_a_login_wall_is_reported_with_the_request_blocked_code() -> None:
+    assert failure_code(AcquisitionReason.LOGIN_WALL) == "request_blocked"
+    for reason in AcquisitionReason:
+        if reason is not AcquisitionReason.LOGIN_WALL:
+            assert failure_code(reason) == reason.value
+    failure = AcquisitionFailure(code=failure_code(AcquisitionReason.LOGIN_WALL), retryable=True)
+    assert failure.code == "request_blocked"
```

Apply this patch to `python/tests/acquisition/test_youtube_service.py`:

```diff
diff --git a/python/tests/acquisition/test_youtube_service.py b/python/tests/acquisition/test_youtube_service.py
--- a/python/tests/acquisition/test_youtube_service.py
+++ b/python/tests/acquisition/test_youtube_service.py
@@ -251,3 +251,23 @@ def test_extract_and_download_fit_inside_the_activity_budget() -> None:
     # the adoption need what is left, so yt-dlp's own timeouts must fire first.
     budget = youtube_service.EXTRACT_TIMEOUT_SECONDS + youtube_service.DOWNLOAD_TIMEOUT_SECONDS
     assert budget <= 240
+
+
+def test_a_sign_in_demand_with_cookies_is_a_login_wall() -> None:
+    error = RuntimeError("ERROR: Sign in to confirm you're not a bot")
+    assert classify(error) is AcquisitionReason.REQUEST_BLOCKED
+    assert classify(error, signed_in=True) is AcquisitionReason.LOGIN_WALL
+    assert classify(RuntimeError("Video unavailable"), signed_in=True) is (
+        AcquisitionReason.REQUEST_INCOMPLETE
+    )
+
+
+@pytest.mark.asyncio
+async def test_a_signed_in_client_reports_a_login_wall() -> None:
+    client = YtDlpClient(
+        lambda options: FakeYdl(options, RuntimeError("Sign in to confirm your age")),
+        signed_in=True,
+    )
+    with pytest.raises(YtDlpError) as caught:
+        await client.extract(URL, comments=True)
+    assert caught.value.reason is AcquisitionReason.LOGIN_WALL
```

Apply this patch to `python/tests/acquisition/test_instagram_acquirer.py`:

```diff
diff --git a/python/tests/acquisition/test_instagram_acquirer.py b/python/tests/acquisition/test_instagram_acquirer.py
--- a/python/tests/acquisition/test_instagram_acquirer.py
+++ b/python/tests/acquisition/test_instagram_acquirer.py
@@ -250,11 +250,12 @@ async def test_a_blocked_request_is_retryable_and_skips_cards(tmp_path: Path) ->
 
 
 @pytest.mark.asyncio
-async def test_require_login_is_request_blocked(tmp_path: Path) -> None:
+async def test_require_login_is_request_blocked_with_a_login_wall_attempt(tmp_path: Path) -> None:
     texts = [json.dumps({"message": "x", "require_login": True, "status": "fail"})]
     result = await _inspect(tmp_path, FakeRequest(texts), FakeHeadless())
     assert result.failure is not None
-    assert result.failure.code == "request_blocked"
+    assert (result.failure.code, result.failure.retryable) == ("request_blocked", True)
+    assert [a.reason for a in result.failure.attempts] == [AcquisitionReason.LOGIN_WALL]
 
 
 @pytest.mark.asyncio
```

Apply this patch to `python/tests/acquisition/test_instagram_service.py`:

```diff
diff --git a/python/tests/acquisition/test_instagram_service.py b/python/tests/acquisition/test_instagram_service.py
--- a/python/tests/acquisition/test_instagram_service.py
+++ b/python/tests/acquisition/test_instagram_service.py
@@ -70,7 +70,7 @@ async def test_request_fetcher_returns_script_texts() -> None:
         (_response(status=429), AcquisitionReason.REQUEST_BLOCKED),
         (
             _response(url="https://www.instagram.com/accounts/login/?next=%2Fp%2Fx%2F"),
-            AcquisitionReason.REQUEST_BLOCKED,
+            AcquisitionReason.LOGIN_WALL,
         ),
         (_response(url="https://www.instagram.com/challenge/"), AcquisitionReason.REQUEST_BLOCKED),
         (TimeoutError(), AcquisitionReason.REQUEST_TIMEOUT),
```

Apply this patch to `python/tests/acquisition/test_threads_service.py`:

```diff
diff --git a/python/tests/acquisition/test_threads_service.py b/python/tests/acquisition/test_threads_service.py
--- a/python/tests/acquisition/test_threads_service.py
+++ b/python/tests/acquisition/test_threads_service.py
@@ -329,7 +329,7 @@ async def test_request_fetcher_returns_script_texts() -> None:
     ("get_result", "reason"),
     [
         (_response(status=403), AcquisitionReason.REQUEST_BLOCKED),
-        (_response(url="https://www.threads.com/login?next=x"), AcquisitionReason.REQUEST_BLOCKED),
+        (_response(url="https://www.threads.com/login?next=x"), AcquisitionReason.LOGIN_WALL),
         (TimeoutError(), AcquisitionReason.REQUEST_TIMEOUT),
         (RuntimeError("boom"), AcquisitionReason.REQUEST_BLOCKED),
     ],
```

Apply this patch to `python/tests/acquisition/test_x_service.py`:

```diff
diff --git a/python/tests/acquisition/test_x_service.py b/python/tests/acquisition/test_x_service.py
--- a/python/tests/acquisition/test_x_service.py
+++ b/python/tests/acquisition/test_x_service.py
@@ -70,7 +70,10 @@ async def test_a_non_json_syndication_body_is_missing() -> None:
     [
         (_response(status=403), BLOCKED),
         (_response(status=429), BLOCKED),
-        (_response(url="https://x.com/i/flow/login?redirect_after_login=%2F"), BLOCKED),
+        (
+            _response(url="https://x.com/i/flow/login?redirect_after_login=%2F"),
+            AcquisitionReason.LOGIN_WALL,
+        ),
         (_response(url="https://x.com/account/access"), BLOCKED),
         (TimeoutError(), TIMEOUT),
         (RuntimeError("boom"), BLOCKED),
```

Apply this patch to `python/tests/activities/test_source_investigation.py`:

```diff
diff --git a/python/tests/activities/test_source_investigation.py b/python/tests/activities/test_source_investigation.py
--- a/python/tests/activities/test_source_investigation.py
+++ b/python/tests/activities/test_source_investigation.py
@@ -688,3 +688,31 @@ async def test_threads_attempts_use_platform_stage_names(tmp_path: Path) -> None
         "threads_cleanup",
     ]
     assert result.events[1].payload["reason"] == "request_blocked"
+
+
+@pytest.mark.asyncio
+async def test_a_login_wall_attempt_is_a_safe_event_and_a_request_blocked_failure(
+    tmp_path: Path,
+) -> None:
+    async def runner(workflow_id: str, source_url: str, artifact_root: Path):
+        del workflow_id, source_url, artifact_root
+        return AcquisitionResult(
+            failure=AcquisitionFailure(
+                code="request_blocked",
+                retryable=True,
+                attempts=[
+                    AcquisitionAttempt(
+                        strategy=AcquisitionStrategy.SCRAPLING_HEADLESS,
+                        status=AttemptStatus.FAILED,
+                        reason=AcquisitionReason.LOGIN_WALL,
+                        attempt_count=1,
+                        elapsed_ms=10,
+                    )
+                ],
+            )
+        )
+
+    result = await build_source_investigation_activity(_settings(tmp_path), runner=runner)(INPUT)
+
+    assert result.failure == SafeActivityError(code="request_blocked", retryable=True)
+    assert result.events[1].payload["reason"] == "login_wall"
```

Apply this patch to `python/tests/domain/test_models.py`:

```diff
diff --git a/python/tests/domain/test_models.py b/python/tests/domain/test_models.py
--- a/python/tests/domain/test_models.py
+++ b/python/tests/domain/test_models.py
@@ -261,6 +261,13 @@ def test_source_progress_event_rejects_out_of_set_reason(reason: str) -> None:
         SourceProgressEvent(kind="stage.failed", payload={"stage": "tiktok_cdn", "reason": reason})
 
 
+def test_a_login_wall_reason_is_a_safe_event_reason() -> None:
+    event = SourceProgressEvent(
+        kind="stage.failed", payload={"stage": "x_request", "reason": "login_wall"}
+    )
+    assert event.payload["reason"] == "login_wall"
+
+
 def test_unsupported_platform_is_not_legacy_fallback_eligible() -> None:
     """`unsupported_platform` is a pre-provider rejection, not a Python failure.
 
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `MSYS_NO_PATHCONV=1 timeout 590 wsl -e bash /mnt/d/thoth-tmp/bu/pt.sh tests/acquisition tests/activities/test_source_investigation.py tests/domain/test_models.py -p no:warnings`
Expected: FAIL during collection with `ImportError: cannot import name 'failure_code'` and `AttributeError: type object 'AcquisitionReason' has no attribute 'LOGIN_WALL'`.

- [ ] **Step 3: Implement**

```bash
python D:/thoth-tmp/bu/sa/extract.py apply 6 python/src/thoth_control_plane/acquisition/models.py python/src/thoth_control_plane/domain/models.py python/src/thoth_control_plane/acquisition/threads_service.py python/src/thoth_control_plane/acquisition/instagram_service.py python/src/thoth_control_plane/acquisition/x_service.py python/src/thoth_control_plane/acquisition/youtube_service.py python/src/thoth_control_plane/acquisition/registry.py
```

Apply this patch to `python/src/thoth_control_plane/acquisition/models.py`:

```diff
diff --git a/python/src/thoth_control_plane/acquisition/models.py b/python/src/thoth_control_plane/acquisition/models.py
--- a/python/src/thoth_control_plane/acquisition/models.py
+++ b/python/src/thoth_control_plane/acquisition/models.py
@@ -77,6 +77,16 @@ class AcquisitionReason(StrEnum):
     CDN_RATE_LIMITED = "cdn_rate_limited"
     CDN_UNAVAILABLE = "cdn_unavailable"
     MEDIA_VALIDATION_FAILED = "media_validation_failed"
+    # A login page instead of the content: reported as `request_blocked`; the reason
+    # tells source-account rotation that a session has expired.
+    LOGIN_WALL = "login_wall"
+
+
+def failure_code(reason: AcquisitionReason) -> str:
+    """The failure code for `reason`; a login wall adds no code of its own."""
+    if reason is AcquisitionReason.LOGIN_WALL:
+        return AcquisitionReason.REQUEST_BLOCKED.value
+    return reason.value
 
 
 class AcquisitionAttempt(StrictModel):
```

Apply this patch to `python/src/thoth_control_plane/domain/models.py`:

```diff
diff --git a/python/src/thoth_control_plane/domain/models.py b/python/src/thoth_control_plane/domain/models.py
--- a/python/src/thoth_control_plane/domain/models.py
+++ b/python/src/thoth_control_plane/domain/models.py
@@ -382,6 +382,7 @@ SOURCE_EVENT_REASONS = frozenset(
         "cdn_rate_limited",
         "cdn_unavailable",
         "media_validation_failed",
+        "login_wall",
     }
 )
 
```

Apply this patch to `python/src/thoth_control_plane/acquisition/threads_service.py`:

```diff
diff --git a/python/src/thoth_control_plane/acquisition/threads_service.py b/python/src/thoth_control_plane/acquisition/threads_service.py
--- a/python/src/thoth_control_plane/acquisition/threads_service.py
+++ b/python/src/thoth_control_plane/acquisition/threads_service.py
@@ -55,6 +55,7 @@ from thoth_control_plane.acquisition.models import (
     ReportSource,
     ResolvedMedia,
     SourceReport,
+    failure_code,
 )
 from thoth_control_plane.acquisition.service import (
     RETRYABLE_FAILURES,
@@ -113,7 +114,9 @@ class ThreadsRequestFetcher:
                 else AcquisitionReason.REQUEST_BLOCKED
             )
             raise RequestFetchError(reason) from None
-        if getattr(response, "status", None) != 200 or _blocked(response.url):
+        if _blocked(response.url):
+            raise RequestFetchError(AcquisitionReason.LOGIN_WALL)
+        if getattr(response, "status", None) != 200:
             raise RequestFetchError(AcquisitionReason.REQUEST_BLOCKED)
         return [text for text in response.css(SCRIPT_SELECTOR).getall() if text]
 
@@ -345,8 +348,8 @@ class ThreadsAcquirer:
             except HeadlessBrowserError as error:
                 return AcquisitionResult(
                     failure=AcquisitionFailure(
-                        code=error.reason.value,
-                        retryable=error.reason.value in RETRYABLE_FAILURES,
+                        code=failure_code(error.reason),
+                        retryable=failure_code(error.reason) in RETRYABLE_FAILURES,
                     )
                 )
             start = time.monotonic()
@@ -375,8 +378,8 @@ class ThreadsAcquirer:
             if reason is not None:
                 return AcquisitionResult(
                     failure=AcquisitionFailure(
-                        code=reason.value,
-                        retryable=reason.value in RETRYABLE_FAILURES,
+                        code=failure_code(reason),
+                        retryable=failure_code(reason) in RETRYABLE_FAILURES,
                         attempts=[attempt],
                     )
                 )
```

Apply this patch to `python/src/thoth_control_plane/acquisition/instagram_service.py`:

```diff
diff --git a/python/src/thoth_control_plane/acquisition/instagram_service.py b/python/src/thoth_control_plane/acquisition/instagram_service.py
--- a/python/src/thoth_control_plane/acquisition/instagram_service.py
+++ b/python/src/thoth_control_plane/acquisition/instagram_service.py
@@ -61,6 +61,7 @@ from thoth_control_plane.acquisition.models import (
     MaterializedMedia,
     ReportSource,
     SourceReport,
+    failure_code,
 )
 from thoth_control_plane.acquisition.service import (
     RETRYABLE_FAILURES,
@@ -86,6 +87,8 @@ DIALOG_CLOSE_SELECTOR = 'div[role=dialog] svg[aria-label="Close"]'
 POST_CARD_SELECTOR = "main > div > div"
 PROFILE_CARD_SELECTOR = "header"
 LOGIN_PATHS = ("/accounts/login", "/login", "/challenge")
+# A sign-in page means no usable session; a challenge means the session was flagged.
+SIGN_IN_PATHS = ("/accounts/login", "/login")
 # Tags each matched comment row; targets arrive as the evaluate argument, never interpolated.
 TAG_COMMENTS_JS = """
 (targets) => {
@@ -145,6 +148,8 @@ class InstagramRequestFetcher:
                 else AcquisitionReason.REQUEST_BLOCKED
             )
             raise RequestFetchError(reason) from None
+        if is_login_path(response.url, SIGN_IN_PATHS):
+            raise RequestFetchError(AcquisitionReason.LOGIN_WALL)
         if getattr(response, "status", None) != 200 or _blocked(response.url):
             raise RequestFetchError(AcquisitionReason.REQUEST_BLOCKED)
         return response
@@ -213,12 +218,11 @@ class InstagramAcquirer:
         self, identity: InstagramPostIdentity
     ) -> tuple[InstagramParse | None, AcquisitionReason | None]:
         url = str(identity.canonical_url)
-        if CONTENT_METHOD == "request":
-            blocked = AcquisitionReason.REQUEST_BLOCKED
-            incomplete = AcquisitionReason.REQUEST_INCOMPLETE
-        else:
-            blocked = AcquisitionReason.HEADLESS_BLOCKED
-            incomplete = AcquisitionReason.HEADLESS_INCOMPLETE
+        incomplete = (
+            AcquisitionReason.REQUEST_INCOMPLETE
+            if CONTENT_METHOD == "request"
+            else AcquisitionReason.HEADLESS_INCOMPLETE
+        )
         try:
             if CONTENT_METHOD == "request":
                 texts = await self._request.fetch(url)
@@ -228,7 +232,7 @@ class InstagramAcquirer:
             return None, error.reason
         roots = json_roots(texts)
         if login_required(roots):
-            return None, blocked
+            return None, AcquisitionReason.LOGIN_WALL
         parsed = parse_post(roots, identity)
         return parsed, None if parsed else incomplete
 
@@ -248,8 +252,8 @@ class InstagramAcquirer:
             except (RequestFetchError, HeadlessBrowserError) as error:
                 return AcquisitionResult(
                     failure=AcquisitionFailure(
-                        code=error.reason.value,
-                        retryable=error.reason.value in RETRYABLE_FAILURES,
+                        code=failure_code(error.reason),
+                        retryable=failure_code(error.reason) in RETRYABLE_FAILURES,
                     )
                 )
             start = time.monotonic()
@@ -278,8 +282,8 @@ class InstagramAcquirer:
             if reason is not None:
                 return AcquisitionResult(
                     failure=AcquisitionFailure(
-                        code=reason.value,
-                        retryable=reason.value in RETRYABLE_FAILURES,
+                        code=failure_code(reason),
+                        retryable=failure_code(reason) in RETRYABLE_FAILURES,
                         attempts=[attempt],
                     )
                 )
```

Apply this patch to `python/src/thoth_control_plane/acquisition/x_service.py`:

```diff
diff --git a/python/src/thoth_control_plane/acquisition/x_service.py b/python/src/thoth_control_plane/acquisition/x_service.py
--- a/python/src/thoth_control_plane/acquisition/x_service.py
+++ b/python/src/thoth_control_plane/acquisition/x_service.py
@@ -55,6 +55,7 @@ from thoth_control_plane.acquisition.models import (
     MaterializedMedia,
     ReportSource,
     SourceReport,
+    failure_code,
 )
 from thoth_control_plane.acquisition.service import (
     RETRYABLE_FAILURES,
@@ -75,6 +76,8 @@ CONTENT_METHOD: Literal["request"] = "request"
 # Any token is accepted (Stage 3c probe); the id names the tweet.
 SYNDICATION_URL = "https://cdn.syndication.twimg.com/tweet-result?id={post_id}&token=0&lang=en"
 LOGIN_PATHS = ("/i/flow/login", "/login", "/account/access")
+# A sign-in page means no usable session; `/account/access` means the account was flagged.
+SIGN_IN_PATHS = ("/i/flow/login", "/login")
 # From the Stage 3c capture survey. The post's own article links to its status; on a reply's
 # page the parent tweet's article comes first. The profile card is the block holding the
 # avatar, name, and bio, directly under the banner.
@@ -161,6 +164,8 @@ class XRequestFetcher:
         status = getattr(response, "status", None)
         if missing_ok and status == 404:
             return None
+        if is_login_path(response.url, SIGN_IN_PATHS):
+            raise RequestFetchError(AcquisitionReason.LOGIN_WALL)
         if status != 200 or is_login_path(response.url, LOGIN_PATHS):
             raise RequestFetchError(AcquisitionReason.REQUEST_BLOCKED)
         return response
@@ -291,7 +296,7 @@ class XAcquirer:
                     reason = AcquisitionReason.MEDIA_VALIDATION_FAILED
             attempt = _make_attempt(strategy, reason, _elapsed_ms(start))
             if reason is not None or parsed is None:
-                code = (reason or AcquisitionReason.REQUEST_INCOMPLETE).value
+                code = failure_code(reason or AcquisitionReason.REQUEST_INCOMPLETE)
                 return AcquisitionResult(
                     failure=AcquisitionFailure(
                         code=code, retryable=code in RETRYABLE_FAILURES, attempts=[attempt]
```

Apply this patch to `python/src/thoth_control_plane/acquisition/youtube_service.py`:

```diff
diff --git a/python/src/thoth_control_plane/acquisition/youtube_service.py b/python/src/thoth_control_plane/acquisition/youtube_service.py
--- a/python/src/thoth_control_plane/acquisition/youtube_service.py
+++ b/python/src/thoth_control_plane/acquisition/youtube_service.py
@@ -50,6 +50,7 @@ from thoth_control_plane.acquisition.models import (
     MaterializedMedia,
     ReportSource,
     SourceReport,
+    failure_code,
 )
 from thoth_control_plane.acquisition.service import (
     RETRYABLE_FAILURES,
@@ -156,13 +157,14 @@ class YtDlpError(Exception):
         self.reason = reason
 
 
-def classify(error: BaseException) -> AcquisitionReason:
+def classify(error: BaseException, *, signed_in: bool = False) -> AcquisitionReason:
     """Map a yt-dlp failure to a reason by message class; the message never leaves here."""
     text = str(error).lower()
     if isinstance(error, TimeoutError) or "timed out" in text:
         return AcquisitionReason.REQUEST_TIMEOUT
     if any(phrase in text for phrase in BOT_CHECK):
-        return AcquisitionReason.REQUEST_BLOCKED
+        # With a session's cookies, a sign-in demand means the session no longer works.
+        return AcquisitionReason.LOGIN_WALL if signed_in else AcquisitionReason.REQUEST_BLOCKED
     if any(phrase in text for phrase in STALE):
         logger.warning("youtube extraction failed in a way that suggests yt-dlp needs an update")
         return AcquisitionReason.REQUEST_BLOCKED
@@ -196,8 +198,14 @@ def _default_factory(options: dict[str, Any]) -> Any:
 class YtDlpClient:
     """yt-dlp as a library, run in a worker thread under a timeout."""
 
-    def __init__(self, factory: Callable[[dict[str, Any]], Any] | None = None) -> None:
+    def __init__(
+        self,
+        factory: Callable[[dict[str, Any]], Any] | None = None,
+        *,
+        signed_in: bool = False,
+    ) -> None:
         self._factory = factory or _default_factory
+        self._signed_in = signed_in
 
     def _call(self, options: dict[str, Any], call: Callable[[Any], Any]) -> Any:
         with self._factory({**YTDLP_OPTIONS, "logger": _Silent(), **options}) as ydl:
@@ -233,7 +241,7 @@ class YtDlpClient:
                 options, lambda ydl: ydl.extract_info(url, download=False), EXTRACT_TIMEOUT_SECONDS
             )
         except Exception as error:
-            raise YtDlpError(classify(error)) from None
+            raise YtDlpError(classify(error, signed_in=self._signed_in)) from None
         if not isinstance(info, dict):
             raise YtDlpError(AcquisitionReason.REQUEST_INCOMPLETE)
         return info
@@ -369,7 +377,7 @@ class YouTubeAcquirer:
                         reason = AcquisitionReason.MEDIA_VALIDATION_FAILED
             attempt = _make_attempt(strategy, reason, _elapsed_ms(start))
             if reason is not None or parsed is None:
-                code = (reason or AcquisitionReason.REQUEST_INCOMPLETE).value
+                code = failure_code(reason or AcquisitionReason.REQUEST_INCOMPLETE)
                 return AcquisitionResult(
                     failure=AcquisitionFailure(
                         code=code, retryable=code in RETRYABLE_FAILURES, attempts=[attempt]
```

Apply this patch to `python/src/thoth_control_plane/acquisition/registry.py`:

```diff
diff --git a/python/src/thoth_control_plane/acquisition/registry.py b/python/src/thoth_control_plane/acquisition/registry.py
--- a/python/src/thoth_control_plane/acquisition/registry.py
+++ b/python/src/thoth_control_plane/acquisition/registry.py
@@ -105,7 +105,7 @@ def acquirer_for(
         return XAcquirer(XRequestFetcher(get), XHeadlessBrowser(browser), materializer)
     if platform == "youtube":
         return YouTubeAcquirer(
-            YtDlpClient(_yt_dlp_factory(access, scratch)),
+            YtDlpClient(_yt_dlp_factory(access, scratch), signed_in=access is not None),
             YouTubeHeadlessBrowser(browser),
             materializer,
         )
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `MSYS_NO_PATHCONV=1 timeout 590 wsl -e bash /mnt/d/thoth-tmp/bu/pt.sh tests/acquisition tests/activities tests/workflows tests/domain -p no:warnings`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add python/src/thoth_control_plane/acquisition python/src/thoth_control_plane/domain/models.py python/tests/acquisition python/tests/activities/test_source_investigation.py python/tests/domain/test_models.py
git commit -m "feat(acquisition): report a sign-in page as a login wall attempt"
```

---

### Task 7: The account runner and its event

**Files:**
- Create: `python/src/thoth_control_plane/acquisition/accounts/runner.py`
- Modify: `python/src/thoth_control_plane/acquisition/models.py` (`AccountUse`, `AcquisitionResult.account`)
- Modify: `python/src/thoth_control_plane/domain/models.py` (account event keys and outcomes)
- Modify: `python/src/thoth_control_plane/activities/source_investigation.py`
- Test: `python/tests/acquisition/accounts/test_runner.py`, `python/tests/activities/test_source_investigation.py`, `python/tests/domain/test_models.py`

**Interfaces:**
- Consumes: Task 4's store and `SessionAccess`; Task 5's `acquirer_for(access, scratch)`; Task 6's `LOGIN_WALL`.
- Produces:
  - `AccountUse(used: bool, outcome: success|blocked|challenge|rate_limited|login_wall | None, no_account_available: bool)` and `AcquisitionResult.account: AccountUse | None`.
  - `account_outcome(result) -> Outcome | None`:
    - `success` on no failure;
    - `login_wall` when any attempt's reason is `LOGIN_WALL`;
    - `rate_limited` on `cdn_rate_limited`;
    - `blocked` on `request_blocked` or `headless_blocked`;
    - otherwise None.
  - `account_runner(store | None, acquire) -> runner`, where `acquire(workflow_id, source_url, artifact_root, access)`.
  - `build_production_acquisition_runner(settings)` wraps the production acquisition with the store when `account_vault_key` yields a vault; otherwise it logs one `warn`, "source accounts unavailable; acquisition runs anonymously".
  - The activity adds one `stage.progress` event, `<platform>_account`, with `account_used`, `no_account_available`, and, when set, `account_outcome`, before the cleanup event, when `result.account` is set.
  - The domain validator admits only booleans for the two flags and only the five outcomes.

- [ ] **Step 1: Write the failing tests**

```bash
python D:/thoth-tmp/bu/sa/extract.py create 7 python/tests/acquisition/accounts/test_runner.py
python D:/thoth-tmp/bu/sa/extract.py apply 7 python/tests/activities/test_source_investigation.py python/tests/domain/test_models.py
```

Create `python/tests/acquisition/accounts/test_runner.py`:

```python
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
```

Apply this patch to `python/tests/activities/test_source_investigation.py`:

```diff
diff --git a/python/tests/activities/test_source_investigation.py b/python/tests/activities/test_source_investigation.py
--- a/python/tests/activities/test_source_investigation.py
+++ b/python/tests/activities/test_source_investigation.py
@@ -2,6 +2,7 @@
 
 import asyncio
 import json
+import logging
 import os
 from pathlib import Path, PurePosixPath
 
@@ -9,6 +10,7 @@ import pytest
 from pydantic import ValidationError
 
 from thoth_control_plane.acquisition.models import (
+    AccountUse,
     AcquisitionAttempt,
     AcquisitionFailure,
     AcquisitionOutcome,
@@ -22,6 +24,7 @@ from thoth_control_plane.acquisition.models import (
 )
 from thoth_control_plane.activities.source_investigation import (
     SourceInvestigationActivityInput,
+    build_production_acquisition_runner,
     build_source_investigation_activity,
 )
 from thoth_control_plane.config import Settings
@@ -716,3 +719,34 @@ async def test_a_login_wall_attempt_is_a_safe_event_and_a_request_blocked_failur
 
     assert result.failure == SafeActivityError(code="request_blocked", retryable=True)
     assert result.events[1].payload["reason"] == "login_wall"
+
+
+@pytest.mark.asyncio
+async def test_account_use_becomes_one_enum_only_event_before_cleanup(tmp_path: Path) -> None:
+    async def runner(workflow_id: str, source_url: str, artifact_root: Path):
+        del workflow_id, source_url, artifact_root
+        return AcquisitionResult(
+            failure=AcquisitionFailure(code="request_timeout", retryable=True),
+            account=AccountUse(used=False, no_account_available=True),
+        )
+
+    result = await build_source_investigation_activity(_settings(tmp_path), runner=runner)(INPUT)
+
+    assert [event.payload["stage"] for event in result.events] == [
+        "tiktok_account",
+        "tiktok_cleanup",
+    ]
+    assert result.events[0].kind == "stage.progress"
+    assert result.events[0].payload == {
+        "stage": "tiktok_account",
+        "account_used": False,
+        "no_account_available": True,
+    }
+
+
+def test_without_a_vault_the_production_runner_warns_once_and_stays_anonymous(
+    tmp_path: Path, caplog: pytest.LogCaptureFixture
+) -> None:
+    with caplog.at_level(logging.WARNING):
+        build_production_acquisition_runner(_settings(tmp_path))
+    assert caplog.text.count("source accounts unavailable") == 1
```

Apply this patch to `python/tests/domain/test_models.py`:

```diff
diff --git a/python/tests/domain/test_models.py b/python/tests/domain/test_models.py
--- a/python/tests/domain/test_models.py
+++ b/python/tests/domain/test_models.py
@@ -261,6 +261,25 @@ def test_source_progress_event_rejects_out_of_set_reason(reason: str) -> None:
         SourceProgressEvent(kind="stage.failed", payload={"stage": "tiktok_cdn", "reason": reason})
 
 
+@pytest.mark.parametrize(
+    "payload",
+    [
+        {"stage": "x_account", "account_used": "yes"},
+        {"stage": "x_account", "no_account_available": 1},
+        {"stage": "x_account", "account_outcome": "account 42 expired"},
+        {"stage": "x_account", "account_label": "main"},
+    ],
+)
+def test_account_events_carry_booleans_and_fixed_outcomes_only(payload: dict) -> None:
+    with pytest.raises(ValidationError):
+        SourceProgressEvent(kind="stage.progress", payload=payload)
+
+
+def test_an_account_event_with_enums_only_is_accepted() -> None:
+    payload = {"stage": "x_account", "account_used": True, "account_outcome": "login_wall"}
+    assert SourceProgressEvent(kind="stage.progress", payload=payload).payload == payload
+
+
 def test_a_login_wall_reason_is_a_safe_event_reason() -> None:
     event = SourceProgressEvent(
         kind="stage.failed", payload={"stage": "x_request", "reason": "login_wall"}
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `MSYS_NO_PATHCONV=1 timeout 590 wsl -e bash /mnt/d/thoth-tmp/bu/pt.sh tests/acquisition/accounts tests/activities/test_source_investigation.py tests/domain/test_models.py -p no:warnings`
Expected: FAIL during collection with `ImportError: cannot import name 'AccountUse'`.

- [ ] **Step 3: Implement**

```bash
python D:/thoth-tmp/bu/sa/extract.py create 7 python/src/thoth_control_plane/acquisition/accounts/runner.py
python D:/thoth-tmp/bu/sa/extract.py apply 7 python/src/thoth_control_plane/acquisition/models.py python/src/thoth_control_plane/domain/models.py python/src/thoth_control_plane/activities/source_investigation.py
```

Create `python/src/thoth_control_plane/acquisition/accounts/runner.py`:

```python
"""Acquisition with source accounts: the platform's mode decides when a session is used.

- `anonymous`: never.
- `always`: lease an account; run anonymously and say so when none is available.
- `fallback`: run anonymously; when that is blocked or meets a login wall, lease one account
  and run once more with it.

The leased account is always released, with the outcome its acquisition earned. An account
store that fails never fails acquisition: it runs anonymously and a `warn` says why. Logs and
results carry enums only, never an account, a label, or a proxy.
"""

from __future__ import annotations

import asyncio
import logging
from collections.abc import Awaitable, Callable
from pathlib import Path

from thoth_control_plane.acquisition.accounts.access import SessionAccess
from thoth_control_plane.acquisition.accounts.policy import Outcome
from thoth_control_plane.acquisition.models import AccountUse, AcquisitionReason, AcquisitionResult
from thoth_control_plane.acquisition.platforms import platform_of
from thoth_control_plane.infrastructure.source_account_store import (
    AccountLease,
    SourceAccountStore,
)

logger = logging.getLogger(__name__)

Acquire = Callable[[str, str, Path, SessionAccess | None], Awaitable[AcquisitionResult]]
Runner = Callable[[str, str, Path], Awaitable[AcquisitionResult]]
BLOCKED_CODES = frozenset({"request_blocked", "headless_blocked"})


def account_outcome(result: AcquisitionResult) -> Outcome | None:
    """What `result` says about the session; None leaves the account's health alone."""
    if result.failure is None:
        return "success"
    if AcquisitionReason.LOGIN_WALL in {attempt.reason for attempt in result.failure.attempts}:
        return "login_wall"
    if result.failure.code == "cdn_rate_limited":
        return "rate_limited"
    if result.failure.code in BLOCKED_CODES:
        return "blocked"
    return None


async def _lease(store: SourceAccountStore, platform: str) -> AccountLease | None:
    try:
        return await asyncio.to_thread(store.lease, platform)  # type: ignore[arg-type]
    except Exception:
        logger.warning("source account lease unavailable; acquisition runs anonymously")
        return None


async def _release(store: SourceAccountStore, lease: AccountLease, outcome: Outcome | None) -> None:
    try:
        await asyncio.to_thread(store.report, lease.account_id, outcome)
    except Exception:
        logger.warning("source account release failed; its lease expires on its own")


def account_runner(store: SourceAccountStore | None, acquire: Acquire) -> Runner:
    async def run(workflow_id: str, source_url: str, artifact_root: Path) -> AcquisitionResult:
        async def attempt(access: SessionAccess | None) -> AcquisitionResult:
            return await acquire(workflow_id, source_url, artifact_root, access)

        platform = platform_of(source_url)
        if store is None or platform is None:
            return await attempt(None)
        try:
            mode = (await asyncio.to_thread(store.policy, platform)).mode  # type: ignore[arg-type]
        except Exception:
            logger.warning("source account policy unavailable; acquisition runs anonymously")
            return await attempt(None)
        if mode == "anonymous":
            return await attempt(None)
        anonymous: AcquisitionResult | None = None
        if mode == "fallback":
            anonymous = await attempt(None)
            if account_outcome(anonymous) not in ("blocked", "login_wall"):
                return anonymous
        lease = await _lease(store, platform)
        if lease is None:
            result = anonymous if anonymous is not None else await attempt(None)
            logger.info("no source account available platform=%s mode=%s", platform, mode)
            return result.model_copy(
                update={"account": AccountUse(used=False, no_account_available=True)}
            )
        outcome: Outcome | None = None
        try:
            result = await attempt(lease.access)
            outcome = account_outcome(result)
        finally:
            await _release(store, lease, outcome)
        logger.info("source account used platform=%s outcome=%s", platform, outcome or "none")
        return result.model_copy(update={"account": AccountUse(used=True, outcome=outcome)})

    return run
```

Apply this patch to `python/src/thoth_control_plane/acquisition/models.py`:

```diff
diff --git a/python/src/thoth_control_plane/acquisition/models.py b/python/src/thoth_control_plane/acquisition/models.py
--- a/python/src/thoth_control_plane/acquisition/models.py
+++ b/python/src/thoth_control_plane/acquisition/models.py
@@ -267,9 +267,18 @@ class AcquisitionFailure(StrictModel):
     attempts: Annotated[list[AcquisitionAttempt], Field(max_length=3)] = Field(default_factory=list)
 
 
+class AccountUse(StrictModel):
+    """Whether a source account served this acquisition; enums only, never an account."""
+
+    used: bool
+    outcome: Literal["success", "blocked", "challenge", "rate_limited", "login_wall"] | None = None
+    no_account_available: bool = False
+
+
 class AcquisitionResult(StrictModel):
     report: SourceReport | None = None
     failure: AcquisitionFailure | None = None
+    account: AccountUse | None = None
 
     @model_validator(mode="after")
     def require_exactly_one_outcome(self) -> AcquisitionResult:
```

Apply this patch to `python/src/thoth_control_plane/domain/models.py`:

```diff
diff --git a/python/src/thoth_control_plane/domain/models.py b/python/src/thoth_control_plane/domain/models.py
--- a/python/src/thoth_control_plane/domain/models.py
+++ b/python/src/thoth_control_plane/domain/models.py
@@ -367,10 +367,16 @@ SOURCE_EVENT_PAYLOAD_KEYS = frozenset(
         "partial_cleanup_passed",
         "browser_cleanup_passed",
         "fallback_from",
+        "account_used",
+        "account_outcome",
+        "no_account_available",
     }
 )
 SOURCE_EVENT_STAGE_PATTERN = re.compile(r"^[a-z][a-z0-9_]{0,63}$")
 SOURCE_EVENT_STATUSES = frozenset({"succeeded", "failed", "incomplete"})
+SOURCE_ACCOUNT_OUTCOMES = frozenset(
+    {"success", "blocked", "challenge", "rate_limited", "login_wall"}
+)
 SOURCE_EVENT_REASONS = frozenset(
     {
         "headless_timeout",
@@ -405,6 +411,12 @@ class SourceProgressEvent(StrictModel):
         stage = payload.get("stage")
         if not isinstance(stage, str) or not SOURCE_EVENT_STAGE_PATTERN.fullmatch(stage):
             raise ValueError("source event stage must be a safe code")
+        for flag in ("account_used", "no_account_available"):
+            if flag in payload and not isinstance(payload[flag], bool):
+                raise ValueError("source event account flags must be booleans")
+        outcome = payload.get("account_outcome")
+        if outcome is not None and outcome not in SOURCE_ACCOUNT_OUTCOMES:
+            raise ValueError("source event account outcome is unsupported")
         if "status" in payload and payload["status"] not in SOURCE_EVENT_STATUSES:
             raise ValueError("source event status is unsupported")
         if "reason" in payload and payload["reason"] not in SOURCE_EVENT_REASONS:
```

Apply this patch to `python/src/thoth_control_plane/activities/source_investigation.py`:

```diff
diff --git a/python/src/thoth_control_plane/activities/source_investigation.py b/python/src/thoth_control_plane/activities/source_investigation.py
--- a/python/src/thoth_control_plane/activities/source_investigation.py
+++ b/python/src/thoth_control_plane/activities/source_investigation.py
@@ -4,7 +4,9 @@ from __future__ import annotations
 
 import asyncio
 import contextlib
+import logging
 import os
+import tempfile
 from collections.abc import Awaitable, Callable, Mapping
 from hashlib import sha256
 from pathlib import Path, PurePosixPath
@@ -13,6 +15,9 @@ import httpx
 from pydantic import HttpUrl, TypeAdapter
 from temporalio import activity
 
+from thoth_control_plane.acquisition.accounts.access import SessionAccess
+from thoth_control_plane.acquisition.accounts.runner import account_runner
+from thoth_control_plane.acquisition.accounts.vault import Vault
 from thoth_control_plane.acquisition.browser import (
     ScraplingCapability,
     active_scrapling_session_count,
@@ -22,6 +27,7 @@ from thoth_control_plane.acquisition.materializer import (
     resolve_host_via_getaddrinfo,
 )
 from thoth_control_plane.acquisition.models import (
+    AccountUse,
     AcquisitionAttempt,
     AcquisitionResult,
     AcquisitionStrategy,
@@ -41,10 +47,12 @@ from thoth_control_plane.domain.models import (
     SourceProgressEvent,
     StrictModel,
 )
+from thoth_control_plane.infrastructure.source_account_store import SourceAccountStore
 
 AcquisitionRunner = Callable[[str, str, Path], Awaitable[AcquisitionResult]]
 
 _CAPABILITY_ADAPTER = TypeAdapter(ScraplingCapability)
+logger = logging.getLogger(__name__)
 
 _STAGE_SUFFIXES: dict[AcquisitionStrategy, str] = {
     AcquisitionStrategy.SCRAPLING_HEADLESS: "headless",
@@ -70,23 +78,45 @@ def _coerce_capability(
     return _CAPABILITY_ADAPTER.validate_python(capability)
 
 
+def _account_store(settings: Settings) -> SourceAccountStore | None:
+    vault = Vault.from_key(settings.account_vault_key)
+    if vault is None or settings.THOTH_EDITOR_DATABASE_URL is None:
+        logger.warning("source accounts unavailable; acquisition runs anonymously")
+        return None
+    return SourceAccountStore.connect(settings.THOTH_EDITOR_DATABASE_URL.get_secret_value(), vault)
+
+
 def build_production_acquisition_runner(settings: Settings) -> AcquisitionRunner:
-    """Build a fresh HTTP client and materializer per activity call; the acquirer owns its browser.
+    """Build a fresh HTTP client and materializer per acquisition; the acquirer owns its browser.
 
-    `settings` is accepted for interface symmetry with `build_source_investigation_activity`
-    and future acquisition-stack configuration; the stack itself needs no settings today.
+    Source accounts wrap the acquisition when the vault key and the editor database are
+    configured; otherwise every acquisition runs anonymously.
     """
-    del settings
-
-    async def run(workflow_id: str, source_url: str, artifact_root: Path) -> AcquisitionResult:
-        async with httpx.AsyncClient(follow_redirects=False) as client:
-            materializer = MediaMaterializer(client, resolve_host_via_getaddrinfo)
-            acquirer = acquirer_for(source_url, client=client, materializer=materializer)
-            return await acquirer.inspect(
-                workflow_id=workflow_id, source_url=source_url, artifact_root=artifact_root
-            )
 
-    return run
+    async def acquire(
+        workflow_id: str, source_url: str, artifact_root: Path, access: SessionAccess | None
+    ) -> AcquisitionResult:
+        with contextlib.ExitStack() as stack:
+            # A private directory for yt-dlp's cookie file, removed with everything in it.
+            scratch = (
+                Path(stack.enter_context(tempfile.TemporaryDirectory(prefix="thoth-session-")))
+                if access is not None
+                else None
+            )
+            async with httpx.AsyncClient(follow_redirects=False) as client:
+                materializer = MediaMaterializer(client, resolve_host_via_getaddrinfo)
+                acquirer = acquirer_for(
+                    source_url,
+                    client=client,
+                    materializer=materializer,
+                    access=access,
+                    scratch=scratch,
+                )
+                return await acquirer.inspect(
+                    workflow_id=workflow_id, source_url=source_url, artifact_root=artifact_root
+                )
+
+    return account_runner(_account_store(settings), acquire)
 
 
 def _attempt_events(attempts: list[AcquisitionAttempt], platform: str) -> list[SourceProgressEvent]:
@@ -142,8 +172,26 @@ def _cleanup_event(artifact_root: Path, workflow_id: str, platform: str) -> Sour
     )
 
 
+def _account_events(account: AccountUse | None, platform: str) -> list[SourceProgressEvent]:
+    """One enum-only event when source accounts took part; never an account or a label."""
+    if account is None:
+        return []
+    payload: dict[str, str | int | float | bool | None] = {
+        "stage": f"{platform}_account",
+        "account_used": account.used,
+        "no_account_available": account.no_account_available,
+    }
+    if account.outcome is not None:
+        payload["account_outcome"] = account.outcome
+    return [SourceProgressEvent(kind="stage.progress", payload=payload)]
+
+
 def _terminal_events(
-    attempts: list[AcquisitionAttempt], artifact_root: Path, workflow_id: str, platform: str
+    attempts: list[AcquisitionAttempt],
+    artifact_root: Path,
+    workflow_id: str,
+    platform: str,
+    account: AccountUse | None = None,
 ) -> list[SourceProgressEvent]:
     """Compose the full history-safe event trail for a terminal activity result.
 
@@ -152,6 +200,7 @@ def _terminal_events(
     """
     return [
         *_attempt_events(attempts, platform),
+        *_account_events(account, platform),
         _cleanup_event(artifact_root, workflow_id, platform),
     ]
 
@@ -243,7 +292,11 @@ async def _run(
                 retryable=acquisition_result.failure.retryable,
             ),
             events=_terminal_events(
-                acquisition_result.failure.attempts, artifact_root, input_.workflow_id, platform
+                acquisition_result.failure.attempts,
+                artifact_root,
+                input_.workflow_id,
+                platform,
+                acquisition_result.account,
             ),
         )
 
@@ -276,7 +329,11 @@ async def _run(
         return SourceInvestigationActivityResult(
             failure=SafeActivityError(code="artifact_persistence_failed", retryable=True),
             events=_terminal_events(
-                report.outcome.attempts, artifact_root, input_.workflow_id, platform
+                report.outcome.attempts,
+                artifact_root,
+                input_.workflow_id,
+                platform,
+                acquisition_result.account,
             ),
         )
 
@@ -290,7 +347,13 @@ async def _run(
         checksum=f"sha256:{digest}",
         size_bytes=len(content),
     )
-    events = _terminal_events(report.outcome.attempts, artifact_root, input_.workflow_id, platform)
+    events = _terminal_events(
+        report.outcome.attempts,
+        artifact_root,
+        input_.workflow_id,
+        platform,
+        acquisition_result.account,
+    )
     return SourceInvestigationActivityResult(report=artifact, events=events)
 
 
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `MSYS_NO_PATHCONV=1 timeout 590 wsl -e bash /mnt/d/thoth-tmp/bu/pt.sh tests/acquisition tests/activities tests/workflows tests/domain tests/test_worker.py -p no:warnings`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add python/src/thoth_control_plane/acquisition python/src/thoth_control_plane/domain/models.py python/src/thoth_control_plane/activities/source_investigation.py python/tests/acquisition/accounts python/tests/activities/test_source_investigation.py python/tests/domain/test_models.py
git commit -m "feat(accounts): apply the access mode around each acquisition"
```

---

### Task 8: API, session check, and the secret sweep

**Files:**
- Create: `python/src/thoth_control_plane/domain/source_accounts.py`
- Create: `python/src/thoth_control_plane/api/routes/source_accounts.py`
- Create: `python/src/thoth_control_plane/acquisition/accounts/session_check.py`
- Modify: `python/src/thoth_control_plane/api/app.py`
- Regenerate: `python/openapi.json`
- Modify (CRLF): `compose.stage1.local.yml`, `docs/python-control-plane.md`
- Test: `python/tests/api/test_source_accounts.py`, `python/tests/acquisition/accounts/test_session_check.py`, `python/tests/acquisition/accounts/test_secret_leaks.py`
- Test: `python/tests/api/test_workflows.py`, `python/tests/activities/test_legacy_scout.py`

**Interfaces:**
- Consumes: Tasks 2, 4, and 7.
- Produces:
  - Routes under `/api/v1`:

    | Method | Path |
    |---|---|
    | GET | `/source-accounts` |
    | PUT | `/source-accounts/policies/{platform}` |
    | POST | `/source-accounts/validate` |
    | POST | `/source-accounts` |
    | PUT | `/source-accounts/{account_id}/cookies` |
    | PATCH | `/source-accounts/{account_id}` |
    | DELETE | `/source-accounts/{account_id}` |
    | POST | `/source-accounts/{account_id}/test` |
    | GET | `/source-proxies` |
    | POST | `/source-proxies/import` |
    | DELETE | `/source-proxies/{proxy_id}` |

  - Errors are `{"detail": {"code": …}}`:
    - `503 source_accounts_unavailable`;
    - `404 not_found` and `404 proxy_not_found`;
    - `409 label_taken`, `409 proxy_in_use`, `409 undecryptable`;
    - `422` with a cookie error code plus `missing`, `invalid_proxy_file`, `platform_mismatch`, or `invalid_request` with `errors[{field, code}]`.
  - `create_app(..., source_account_store=None)`. Without a store, the app builds one from `settings.account_vault_key`. `app.state.session_checker` is injectable.
  - `check_session(platform, access, get=None) -> "valid" | "expired" | "inconclusive"` and `judge(check, response)`, over `CHECKS` per platform.

The session check runs in the API process, only when the operator presses "Test session". Its endpoints are best known values. Task 10 confirms them live before this feature is called done.

- [ ] **Step 1: Write the failing tests**

```bash
python D:/thoth-tmp/bu/sa/extract.py create 8 python/tests/api/test_source_accounts.py python/tests/acquisition/accounts/test_session_check.py python/tests/acquisition/accounts/test_secret_leaks.py
python D:/thoth-tmp/bu/sa/extract.py apply 8 python/tests/api/test_workflows.py python/tests/activities/test_legacy_scout.py
```

Create `python/tests/api/test_source_accounts.py`:

```python
"""Contract tests for source accounts, their policy, and the proxy pool; secrets never return."""

from __future__ import annotations

from datetime import UTC, datetime

import httpx
import pytest
from cryptography.fernet import Fernet
from sqlalchemy import create_engine
from sqlalchemy.pool import StaticPool

from thoth_control_plane.acquisition.accounts.cookies import parse_cookies
from thoth_control_plane.acquisition.accounts.vault import Vault
from thoth_control_plane.api import create_app
from thoth_control_plane.config import Settings
from thoth_control_plane.infrastructure.source_account_models import Base
from thoth_control_plane.infrastructure.source_account_store import SourceAccountStore

AUTH = {"Authorization": "Bearer test-key"}
SECRET = "s3cr3t-session-value"
PROXY_PASSWORD = "pr0xy-pa55"
COOKIES = "\t".join([".instagram.com", "TRUE", "/", "TRUE", "1893456000", "sessionid", SECRET])


def _store() -> SourceAccountStore:
    engine = create_engine(
        "sqlite://", poolclass=StaticPool, connect_args={"check_same_thread": False}
    )
    Base.metadata.create_all(engine)
    return SourceAccountStore(engine, Vault(Fernet.generate_key().decode()))


def client(store: SourceAccountStore | None = None) -> httpx.AsyncClient:
    app = create_app(Settings(THOTH_CONTROL_PLANE_API_KEY="test-key"), source_account_store=store)
    return httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test/api/v1")


def _clean(response: httpx.Response) -> httpx.Response:
    assert SECRET not in response.text and PROXY_PASSWORD not in response.text
    return response


@pytest.mark.asyncio
async def test_every_route_needs_the_api_key() -> None:
    async with client(_store()) as api:
        assert (await api.get("/source-accounts")).status_code == 403
        assert (await api.get("/source-proxies")).status_code == 403


@pytest.mark.asyncio
async def test_unavailable_lists_defaults_refuses_writes_and_still_validates() -> None:
    async with client(None) as api:
        overview = (await api.get("/source-accounts", headers=AUTH)).json()
        assert overview["available"] is False
        assert [p["platform"] for p in overview["platforms"]] == [
            "tiktok",
            "threads",
            "instagram",
            "x",
            "youtube",
        ]
        created = await api.post(
            "/source-accounts",
            headers=AUTH,
            json={"platform": "instagram", "label": "a", "cookies": COOKIES},
        )
        assert (created.status_code, created.json()["detail"]["code"]) == (
            503,
            "source_accounts_unavailable",
        )
        _clean(created)
        validated = await api.post(
            "/source-accounts/validate",
            headers=AUTH,
            json={"platform": "instagram", "cookies": COOKIES},
        )
        assert _clean(validated).json()["valid"] is True


@pytest.mark.asyncio
async def test_validation_summarizes_without_echoing_a_value() -> None:
    async with client(_store()) as api:
        good = await api.post(
            "/source-accounts/validate",
            headers=AUTH,
            json={"platform": "instagram", "cookies": COOKIES},
        )
        assert _clean(good).json() == {
            "valid": True,
            "count": 1,
            "names": ["sessionid"],
            "earliest_expiry": "2030-01-01T00:00:00Z",
            "error": None,
            "missing": [],
        }
        bad = await api.post(
            "/source-accounts/validate", headers=AUTH, json={"platform": "x", "cookies": COOKIES}
        )
        body = _clean(bad).json()
        assert (body["valid"], body["error"], body["missing"]) == (
            False,
            "missing_required_cookie",
            ["auth_token", "ct0"],
        )


@pytest.mark.asyncio
async def test_an_account_round_trips_with_safe_fields_only() -> None:
    async with client(_store()) as api:
        created = await api.post(
            "/source-accounts",
            headers=AUTH,
            json={"platform": "instagram", "label": " main ", "cookies": COOKIES},
        )
        assert created.status_code == 201
        account = _clean(created).json()
        assert (account["label"], account["status"], account["cookie_names"]) == (
            "main",
            "healthy",
            ["sessionid"],
        )
        overview = _clean(await api.get("/source-accounts", headers=AUTH)).json()
        instagram = next(p for p in overview["platforms"] if p["platform"] == "instagram")
        assert instagram["counts"] == {"healthy": 1, "cooldown": 0, "expired": 0, "disabled": 0}
        assert [a["id"] for a in instagram["accounts"]] == [account["id"]]
        again = await api.post(
            "/source-accounts",
            headers=AUTH,
            json={"platform": "instagram", "label": "main", "cookies": COOKIES},
        )
        assert (again.status_code, again.json()["detail"]["code"]) == (409, "label_taken")


@pytest.mark.asyncio
async def test_a_refused_import_names_the_missing_cookie_only() -> None:
    async with client(_store()) as api:
        refused = await api.post(
            "/source-accounts",
            headers=AUTH,
            json={"platform": "x", "label": "a", "cookies": COOKIES},
        )
        assert refused.status_code == 422
        assert _clean(refused).json()["detail"] == {
            "code": "missing_required_cookie",
            "missing": ["auth_token", "ct0"],
        }


@pytest.mark.asyncio
async def test_a_malformed_body_never_echoes_its_input() -> None:
    async with client(_store()) as api:
        for body in (
            {"platform": "instagram", "label": "x" * 65, "cookies": COOKIES},
            {"platform": "nope", "label": "a", "cookies": COOKIES},
            {"platform": "instagram", "label": "a", "cookies": COOKIES, "extra": SECRET},
        ):
            response = await api.post("/source-accounts", headers=AUTH, json=body)
            assert response.status_code == 422
            assert _clean(response).json()["detail"]["code"] == "invalid_request"
        proxies = await api.post("/source-proxies/import", headers=AUTH, json={"text": 5})
        assert _clean(proxies).json()["detail"]["code"] == "invalid_request"


@pytest.mark.asyncio
async def test_the_policy_is_set_per_platform() -> None:
    async with client(_store()) as api:
        updated = await api.put(
            "/source-accounts/policies/instagram",
            headers=AUTH,
            json={"mode": "always", "min_spacing_seconds": 120},
        )
        assert updated.json() == {"mode": "always", "min_spacing_seconds": 120}
        overview = (await api.get("/source-accounts", headers=AUTH)).json()
        modes = {p["platform"]: p["mode"] for p in overview["platforms"]}
        assert (modes["instagram"], modes["x"]) == ("always", "fallback")
        refused = await api.put(
            "/source-accounts/policies/instagram",
            headers=AUTH,
            json={"mode": "always", "min_spacing_seconds": 86_401},
        )
        assert refused.status_code == 422


@pytest.mark.asyncio
async def test_the_proxy_pool_assigns_one_proxy_per_account() -> None:
    async with client(_store()) as api:
        summary = await api.post(
            "/source-proxies/import",
            headers=AUTH,
            json={
                "text": f"http://u:{PROXY_PASSWORD}@1.2.3.4:8080\nnot a proxy\nhttp://5.6.7.8:80"
            },
        )
        assert _clean(summary).json() == {"added": 2, "duplicates": 0, "invalid_lines": [2]}
        pool = _clean(await api.get("/source-proxies", headers=AUTH)).json()
        assert [(p["display"], p["account_label"]) for p in pool] == [
            ("1.2.3.4:8080", None),
            ("5.6.7.8:80", None),
        ]
        first, second = (p["id"] for p in pool)
        account = (
            await api.post(
                "/source-accounts",
                headers=AUTH,
                json={"platform": "instagram", "label": "a", "cookies": COOKIES, "proxy_id": first},
            )
        ).json()
        assert (account["proxy_id"], account["proxy_display"]) == (first, "1.2.3.4:8080")
        taken = await api.post(
            "/source-accounts",
            headers=AUTH,
            json={"platform": "instagram", "label": "b", "cookies": COOKIES, "proxy_id": first},
        )
        assert (taken.status_code, taken.json()["detail"]["code"]) == (409, "proxy_in_use")
        held = await api.delete(f"/source-proxies/{first}", headers=AUTH)
        assert (held.status_code, held.json()["detail"]["code"]) == (409, "proxy_in_use")
        moved = await api.patch(
            f"/source-accounts/{account['id']}", headers=AUTH, json={"proxy_id": second}
        )
        assert moved.json()["proxy_display"] == "5.6.7.8:80"
        cleared = await api.patch(
            f"/source-accounts/{account['id']}", headers=AUTH, json={"proxy_id": None}
        )
        assert cleared.json()["proxy_id"] is None
        assert (await api.delete(f"/source-proxies/{first}", headers=AUTH)).status_code == 204


@pytest.mark.asyncio
async def test_accounts_are_relabelled_disabled_reimported_and_deleted() -> None:
    async with client(_store()) as api:
        account = (
            await api.post(
                "/source-accounts",
                headers=AUTH,
                json={"platform": "instagram", "label": "a", "cookies": COOKIES},
            )
        ).json()
        path = f"/source-accounts/{account['id']}"
        renamed = await api.patch(path, headers=AUTH, json={"label": "renamed", "disabled": True})
        assert (renamed.json()["label"], renamed.json()["status"]) == ("renamed", "disabled")
        reimported = await api.put(f"{path}/cookies", headers=AUTH, json={"cookies": COOKIES})
        assert _clean(reimported).json()["status"] == "disabled"
        enabled = await api.patch(path, headers=AUTH, json={"disabled": False})
        assert enabled.json()["status"] == "healthy"
        wrong = await api.put(f"{path}/cookies", headers=AUTH, json={"cookies": "garbage"})
        assert (wrong.status_code, wrong.json()["detail"]["code"]) == (422, "invalid_cookie_file")
        assert (await api.delete(path, headers=AUTH)).status_code == 204
        gone = await api.patch(path, headers=AUTH, json={"label": "x"})
        assert (gone.status_code, gone.json()["detail"]["code"]) == (404, "not_found")


def _client_with_checker(store: SourceAccountStore, verdict: str) -> httpx.AsyncClient:
    app = create_app(Settings(THOTH_CONTROL_PLANE_API_KEY="test-key"), source_account_store=store)
    seen: list[tuple[str, object]] = []

    async def checker(platform: str, access: object) -> str:
        seen.append((platform, access))
        return verdict

    app.state.session_checker = checker
    app.state.seen_checks = seen
    return httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test/api/v1")


@pytest.mark.parametrize(
    ("verdict", "status"),
    [("valid", "healthy"), ("expired", "expired"), ("inconclusive", "disabled")],
)
@pytest.mark.asyncio
async def test_a_session_check_records_only_a_clear_verdict(verdict: str, status: str) -> None:
    store = _store()
    cookies = parse_cookies("instagram", COOKIES + "\n", now=datetime.now(UTC))
    account = store.add_account("instagram", "a", cookies)
    store.update_account(account.id, disabled=True)
    if verdict != "inconclusive":
        store.update_account(account.id, disabled=False)
    async with _client_with_checker(store, verdict) as api:
        checked = await api.post(f"/source-accounts/{account.id}/test", headers=AUTH)
    body = _clean(checked).json()
    assert (body["result"], body["account"]["status"]) == (verdict, status)


@pytest.mark.asyncio
async def test_a_session_check_of_an_unknown_account_is_not_found() -> None:
    async with _client_with_checker(_store(), "valid") as api:
        missing = await api.post(
            "/source-accounts/00000000-0000-0000-0000-000000000000/test", headers=AUTH
        )
    assert (missing.status_code, missing.json()["detail"]["code"]) == (404, "not_found")
```

Create `python/tests/acquisition/accounts/test_session_check.py`:

```python
"""The manual session check over synthetic responses; no network."""

from __future__ import annotations

import asyncio
import json
from datetime import UTC, datetime
from types import SimpleNamespace
from typing import Any

import pytest

from thoth_control_plane.acquisition.accounts import session_check
from thoth_control_plane.acquisition.accounts.access import SessionAccess
from thoth_control_plane.acquisition.accounts.cookies import parse_cookies
from thoth_control_plane.acquisition.accounts.session_check import CHECKS, check_session, judge

ACCESS = SessionAccess(
    parse_cookies(
        "instagram",
        "\t".join([".instagram.com", "TRUE", "/", "TRUE", "1893456000", "sessionid", "s"]) + "\n",
        now=datetime(2026, 10, 8, tzinfo=UTC),
    ),
    "http://u:p@1.2.3.4:8080",
)


def _response(url: str, status: int = 200, body: object = b"", location: str | None = None):
    headers = {"location": location} if location else {}
    data = json.dumps(body).encode() if isinstance(body, dict) else body
    return SimpleNamespace(url=url, status=status, body=data, headers=headers)


@pytest.mark.parametrize(
    ("platform", "response", "verdict"),
    [
        ("instagram", _response("https://www.instagram.com/accounts/edit/"), "valid"),
        (
            "instagram",
            _response("https://www.instagram.com/accounts/login/?next=/accounts/edit/"),
            "expired",
        ),
        ("instagram", _response("https://www.instagram.com/accounts/edit/", 429), "inconclusive"),
        ("threads", _response("https://www.threads.com/settings/account"), "valid"),
        ("threads", _response("https://www.threads.com/login?next=x"), "expired"),
        ("x", _response("https://x.com/settings/account"), "valid"),
        ("x", _response("https://x.com/i/flow/login?redirect_after_login=x"), "expired"),
        (
            "tiktok",
            _response(
                "https://www.tiktok.com/passport/web/account/info/",
                body={"data": {"username": "u"}},
            ),
            "valid",
        ),
        (
            "tiktok",
            _response(
                "https://www.tiktok.com/passport/web/account/info/", body={"data": {"captcha": ""}}
            ),
            "expired",
        ),
        (
            "tiktok",
            _response("https://www.tiktok.com/passport/web/account/info/", body=b"<html>"),
            "inconclusive",
        ),
        ("youtube", _response("https://www.youtube.com/account"), "valid"),
        (
            "youtube",
            _response(
                "https://www.youtube.com/account",
                status=303,
                location="https://accounts.google.com/ServiceLogin?service=youtube",
            ),
            "expired",
        ),
    ],
)
def test_each_platform_reads_its_signed_in_page(platform: str, response: Any, verdict: str) -> None:
    assert judge(CHECKS[platform], response) == verdict


@pytest.mark.asyncio
async def test_the_check_sends_the_sessions_cookies_and_proxy() -> None:
    seen: dict[str, Any] = {}

    async def get(url: str, **kwargs: Any):
        seen.update(url=url, **kwargs)
        return _response("https://www.instagram.com/accounts/edit/")

    assert await check_session("instagram", ACCESS, get) == "valid"
    assert seen["url"] == "https://www.instagram.com/accounts/edit/"
    assert (seen["cookies"], seen["proxy"]) == ({"sessionid": "s"}, "http://u:p@1.2.3.4:8080")
    assert seen["impersonate"] == "chrome"


@pytest.mark.asyncio
async def test_a_failure_or_a_slow_answer_is_inconclusive(monkeypatch: pytest.MonkeyPatch) -> None:
    async def broken(url: str, **kwargs: Any):
        raise RuntimeError("proxy refused")

    assert await check_session("instagram", ACCESS, broken) == "inconclusive"
    monkeypatch.setattr(session_check, "TIMEOUT_SECONDS", 0.01)

    async def slow(url: str, **kwargs: Any):
        await asyncio.sleep(1)

    assert await check_session("instagram", ACCESS, slow) == "inconclusive"


def test_every_platform_has_a_check() -> None:
    assert set(CHECKS) == {"tiktok", "threads", "instagram", "x", "youtube"}
```

Create `python/tests/acquisition/accounts/test_secret_leaks.py`:

```python
"""Sentinel cookie and proxy secrets never reach a log, a response, a result, or an event."""

from __future__ import annotations

import logging
from pathlib import Path

import httpx
import pytest
from cryptography.fernet import Fernet
from sqlalchemy import create_engine
from sqlalchemy.pool import StaticPool

from tests.activities.test_source_investigation import INPUT, _load_fixture_report, _settings
from thoth_control_plane.acquisition.accounts.runner import account_runner
from thoth_control_plane.acquisition.accounts.vault import Vault
from thoth_control_plane.acquisition.models import (
    AcquisitionAttempt,
    AcquisitionFailure,
    AcquisitionReason,
    AcquisitionResult,
    AcquisitionStrategy,
    AttemptStatus,
)
from thoth_control_plane.activities.source_investigation import (
    build_source_investigation_activity,
)
from thoth_control_plane.api import create_app
from thoth_control_plane.config import Settings
from thoth_control_plane.infrastructure.source_account_models import Base
from thoth_control_plane.infrastructure.source_account_store import SourceAccountStore

COOKIE_SENTINEL = "cookie-sentinel-7f3a"
PROXY_SENTINEL = "proxy-sentinel-9b1c"
SENTINELS = (COOKIE_SENTINEL, PROXY_SENTINEL)
AUTH = {"Authorization": "Bearer test-key"}


def _cookies(platform: str, domain: str, name: str) -> str:
    return "\t".join([domain, "TRUE", "/", "TRUE", "1893456000", name, COOKIE_SENTINEL]) + "\n"


def _store() -> SourceAccountStore:
    engine = create_engine(
        "sqlite://", poolclass=StaticPool, connect_args={"check_same_thread": False}
    )
    Base.metadata.create_all(engine)
    return SourceAccountStore(engine, Vault(Fernet.generate_key().decode()))


def _assert_clean(*texts: str) -> None:
    for text in texts:
        for sentinel in SENTINELS:
            assert sentinel not in text


@pytest.mark.asyncio
async def test_secrets_never_leave_the_vault(
    tmp_path: Path, caplog: pytest.LogCaptureFixture
) -> None:
    store = _store()
    app = create_app(Settings(THOTH_CONTROL_PLANE_API_KEY="test-key"), source_account_store=store)

    async def checker(platform: str, access: object) -> str:
        logging.getLogger("test").info("checking %r", access)
        return "valid"

    app.state.session_checker = checker
    responses: list[str] = []
    caplog.set_level(logging.DEBUG)
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://test/api/v1"
    ) as api:
        cookies = _cookies("tiktok", ".tiktok.com", "sessionid")
        imported = await api.post(
            "/source-proxies/import",
            headers=AUTH,
            json={"text": f"http://user:{PROXY_SENTINEL}@1.2.3.4:8080\n{PROXY_SENTINEL}"},
        )
        proxy_id = (await api.get("/source-proxies", headers=AUTH)).json()[0]["id"]
        validated = await api.post(
            "/source-accounts/validate",
            headers=AUTH,
            json={"platform": "tiktok", "cookies": cookies},
        )
        created = await api.post(
            "/source-accounts",
            headers=AUTH,
            json={"platform": "tiktok", "label": "a", "cookies": cookies, "proxy_id": proxy_id},
        )
        account_id = created.json()["id"]
        refused = await api.post(
            "/source-accounts",
            headers=AUTH,
            json={"platform": "x", "label": "b", "cookies": cookies},
        )
        malformed = await api.post(
            "/source-accounts",
            headers=AUTH,
            json={"platform": "tiktok", "label": "c", "cookies": cookies, "x": COOKIE_SENTINEL},
        )
        reimported = await api.put(
            f"/source-accounts/{account_id}/cookies", headers=AUTH, json={"cookies": cookies}
        )
        checked = await api.post(f"/source-accounts/{account_id}/test", headers=AUTH)
        listed = await api.get("/source-accounts", headers=AUTH)
        pool = await api.get("/source-proxies", headers=AUTH)
        responses += [
            r.text
            for r in (
                imported,
                validated,
                created,
                refused,
                malformed,
                reimported,
                checked,
                listed,
                pool,
            )
        ]

    store.set_policy("tiktok", "always", 0)

    async def acquire(workflow_id, source_url, artifact_root, access):
        logging.getLogger("test").info("acquiring with %s", access)
        if access is None:
            return AcquisitionResult(report=_load_fixture_report())
        return AcquisitionResult(
            failure=AcquisitionFailure(
                code="request_blocked",
                retryable=True,
                attempts=[
                    AcquisitionAttempt(
                        strategy=AcquisitionStrategy.SCRAPLING_HEADLESS,
                        status=AttemptStatus.FAILED,
                        reason=AcquisitionReason.LOGIN_WALL,
                        attempt_count=1,
                        elapsed_ms=3,
                    )
                ],
            )
        )

    activity = build_source_investigation_activity(
        _settings(tmp_path), runner=account_runner(store, acquire)
    )
    result = await activity(INPUT)

    assert created.status_code == 201 and checked.json()["result"] == "valid"
    assert [event.payload["stage"] for event in result.events][-2:] == [
        "tiktok_account",
        "tiktok_cleanup",
    ]
    _assert_clean(caplog.text, *responses, result.model_dump_json())
```

Apply this patch to `python/tests/api/test_workflows.py`:

```diff
diff --git a/python/tests/api/test_workflows.py b/python/tests/api/test_workflows.py
--- a/python/tests/api/test_workflows.py
+++ b/python/tests/api/test_workflows.py
@@ -479,6 +479,17 @@ def test_openapi_exposes_exact_required_path_method_pairs(gateway) -> None:
             "/resolve",
             "post",
         ),
+        ("/api/v1/source-accounts", "get"),
+        ("/api/v1/source-accounts", "post"),
+        ("/api/v1/source-accounts/policies/{platform}", "put"),
+        ("/api/v1/source-accounts/validate", "post"),
+        ("/api/v1/source-accounts/{account_id}/cookies", "put"),
+        ("/api/v1/source-accounts/{account_id}", "patch"),
+        ("/api/v1/source-accounts/{account_id}", "delete"),
+        ("/api/v1/source-accounts/{account_id}/test", "post"),
+        ("/api/v1/source-proxies", "get"),
+        ("/api/v1/source-proxies/import", "post"),
+        ("/api/v1/source-proxies/{proxy_id}", "delete"),
         ("/api/v1/projects/{project_id}/editor-assets", "get"),
         ("/api/v1/projects/{project_id}/editor-assets", "post"),
         ("/api/v1/projects/{project_id}/editor-assets/{asset_id}/preview", "get"),
```

Apply this patch to `python/tests/activities/test_legacy_scout.py`:

```diff
diff --git a/python/tests/activities/test_legacy_scout.py b/python/tests/activities/test_legacy_scout.py
--- a/python/tests/activities/test_legacy_scout.py
+++ b/python/tests/activities/test_legacy_scout.py
@@ -391,21 +391,27 @@ def test_no_fastapi_request_model_exposes_activity_mode() -> None:
         if media_type != "application/json"
     )
     assert request_schema_names == {
+        "AccessPolicyUpdate",
         "ApplyPromptProposalRequest",
         "ApprovalSubmission",
         "ContentSetImportRequest",
+        "CookieReimport",
+        "CookieValidationRequest",
         "CreateComment",
         "CreateDecision",
         "CreatePromptProposalRequest",
         "CreateRenderJobRequest",
         "CreateStudioImport",
         "EditDocumentPatch",
+        "ProxyImportRequest",
         "ResolveStudioImportItem",
         "RetryRequest",
         "SaveProjectPromptBindingRequest",
         "SavePromptLayerLockRequest",
         "SavePromptModelPreferenceRequest",
         "SavePromptTemplateRequest",
+        "SourceAccountCreate",
+        "SourceAccountUpdate",
         "StudioSourceProjection",
         "UpgradeTimelineRequest",
         "WorkflowRequest",
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `MSYS_NO_PATHCONV=1 timeout 590 wsl -e bash /mnt/d/thoth-tmp/bu/pt.sh tests/api tests/acquisition/accounts tests/activities/test_legacy_scout.py -p no:warnings`
Expected: FAIL during collection with `ImportError: cannot import name 'session_check'`. Pytest stops at the first collection error; the API and allowlist tests fail once it is fixed, until Step 3.

- [ ] **Step 3: Implement**

```bash
python D:/thoth-tmp/bu/sa/extract.py create 8 python/src/thoth_control_plane/domain/source_accounts.py python/src/thoth_control_plane/api/routes/source_accounts.py python/src/thoth_control_plane/acquisition/accounts/session_check.py
python D:/thoth-tmp/bu/sa/extract.py apply 8 python/src/thoth_control_plane/api/app.py
```

Create `python/src/thoth_control_plane/domain/source_accounts.py`:

```python
"""Public shapes of the source-account API: safe fields only, never a cookie or a proxy URL."""

from __future__ import annotations

from datetime import datetime
from typing import Annotated, Literal

from pydantic import Field, StringConstraints

from thoth_control_plane.acquisition.accounts.cookies import MAX_IMPORT_BYTES
from thoth_control_plane.acquisition.accounts.policy import MAX_SPACING_SECONDS
from thoth_control_plane.acquisition.accounts.proxies import MAX_PROXY_BYTES
from thoth_control_plane.domain.models import StrictModel

SourcePlatform = Literal["tiktok", "threads", "instagram", "x", "youtube"]
AccessMode = Literal["anonymous", "fallback", "always"]
AccountStatus = Literal["healthy", "cooldown", "expired", "disabled"]
AccountOutcome = Literal[
    "success", "blocked", "challenge", "rate_limited", "login_wall", "undecryptable"
]
AccountLabel = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=64)]
CookieText = Annotated[str, Field(min_length=1, max_length=MAX_IMPORT_BYTES)]
ProxyText = Annotated[str, Field(min_length=1, max_length=MAX_PROXY_BYTES)]
OpaqueUuid = Annotated[str, Field(pattern=r"^[0-9a-f-]{36}$")]


class SourceAccount(StrictModel):
    id: str
    platform: SourcePlatform
    label: str
    status: AccountStatus
    cooldown_until: datetime | None
    last_used_at: datetime | None
    last_outcome: AccountOutcome | None
    success_count: int
    failure_count: int
    cookie_names: list[str]
    cookies_earliest_expiry: datetime | None
    proxy_id: str | None
    proxy_display: str | None
    created_at: datetime
    updated_at: datetime


class StatusCounts(StrictModel):
    healthy: int = 0
    cooldown: int = 0
    expired: int = 0
    disabled: int = 0


class PlatformAccounts(StrictModel):
    platform: SourcePlatform
    mode: AccessMode
    min_spacing_seconds: int
    counts: StatusCounts
    accounts: list[SourceAccount]


class SourceAccountsOverview(StrictModel):
    available: bool
    platforms: list[PlatformAccounts]


class AccessPolicyUpdate(StrictModel):
    mode: AccessMode
    min_spacing_seconds: Annotated[int, Field(ge=0, le=MAX_SPACING_SECONDS)]


class CookieValidationRequest(StrictModel):
    platform: SourcePlatform
    cookies: CookieText


class CookieValidation(StrictModel):
    valid: bool
    count: int
    names: list[str]
    earliest_expiry: datetime | None
    error: Literal["invalid_cookie_file", "all_cookies_expired", "missing_required_cookie"] | None
    missing: list[str]


class SourceAccountCreate(StrictModel):
    platform: SourcePlatform
    label: AccountLabel
    cookies: CookieText
    proxy_id: OpaqueUuid | None = None


class CookieReimport(StrictModel):
    cookies: CookieText


class SourceAccountUpdate(StrictModel):
    """Omit a field to keep it; `proxy_id: null` removes the proxy."""

    label: AccountLabel | None = None
    proxy_id: OpaqueUuid | None = None
    disabled: bool | None = None


class SourceProxy(StrictModel):
    id: str
    scheme: Literal["http", "https", "socks5"]
    display: str
    account_platform: SourcePlatform | None
    account_label: str | None


class ProxyImportRequest(StrictModel):
    text: ProxyText


class ProxyImportSummary(StrictModel):
    added: int
    duplicates: int
    invalid_lines: list[int]


class SessionCheckResult(StrictModel):
    result: Literal["valid", "expired", "inconclusive"]
    account: SourceAccount
```

Create `python/src/thoth_control_plane/api/routes/source_accounts.py`:

```python
"""Authenticated routes for source accounts, their access policy, and the proxy pool.

The store is synchronous, so every call runs in a worker thread. Responses carry safe fields
only; a request body (cookies, proxy credentials) is never logged or echoed.
"""

from __future__ import annotations

import asyncio
import logging
from collections.abc import Callable
from datetime import UTC, datetime
from typing import Annotated, Any, TypeVar

from fastapi import APIRouter, Depends, HTTPException, Request, Response, status

from thoth_control_plane.acquisition.accounts.cookies import (
    PLATFORMS,
    CookieImportError,
    parse_cookies,
    summarize,
)
from thoth_control_plane.acquisition.accounts.proxies import ProxyImportError, parse_proxy_list
from thoth_control_plane.acquisition.accounts.session_check import check_session
from thoth_control_plane.api.dependencies import current_actor
from thoth_control_plane.domain import Actor
from thoth_control_plane.domain.source_accounts import (
    AccessPolicyUpdate,
    CookieReimport,
    CookieValidation,
    CookieValidationRequest,
    PlatformAccounts,
    ProxyImportRequest,
    ProxyImportSummary,
    SessionCheckResult,
    SourceAccount,
    SourceAccountCreate,
    SourceAccountsOverview,
    SourceAccountUpdate,
    SourcePlatform,
    SourceProxy,
    StatusCounts,
)
from thoth_control_plane.infrastructure.source_account_store import (
    UNSET,
    AccountView,
    SourceAccountError,
    SourceAccountStore,
)

router = APIRouter()
logger = logging.getLogger(__name__)
T = TypeVar("T")
_ERROR_STATUS = {
    "not_found": status.HTTP_404_NOT_FOUND,
    "proxy_not_found": status.HTTP_404_NOT_FOUND,
    "label_taken": status.HTTP_409_CONFLICT,
    "proxy_in_use": status.HTTP_409_CONFLICT,
    "undecryptable": status.HTTP_409_CONFLICT,
    "platform_mismatch": status.HTTP_422_UNPROCESSABLE_CONTENT,
}


def get_source_account_store(request: Request) -> SourceAccountStore | None:
    return request.app.state.source_account_store


def get_session_checker(request: Request) -> Callable[..., Any]:
    return getattr(request.app.state, "session_checker", check_session)


Store = Annotated[SourceAccountStore | None, Depends(get_source_account_store)]
Authorized = Annotated[Actor, Depends(current_actor)]


def _error(status_code: int, code: str, **extra: Any) -> HTTPException:
    return HTTPException(status_code=status_code, detail={"code": code, **extra})


def _require(store: SourceAccountStore | None) -> SourceAccountStore:
    if store is None:
        raise _error(status.HTTP_503_SERVICE_UNAVAILABLE, "source_accounts_unavailable")
    return store


async def _call(function: Callable[..., T], *args: Any, **kwargs: Any) -> T:
    try:
        return await asyncio.to_thread(function, *args, **kwargs)
    except SourceAccountError as error:
        raise _error(_ERROR_STATUS.get(error.code, status.HTTP_409_CONFLICT), error.code) from None


def _account(view: AccountView) -> SourceAccount:
    return SourceAccount(
        id=view.id,
        platform=view.platform,
        label=view.label,
        status=view.status,  # type: ignore[arg-type]
        cooldown_until=view.cooldown_until,
        last_used_at=view.last_used_at,
        last_outcome=view.last_outcome,  # type: ignore[arg-type]
        success_count=view.success_count,
        failure_count=view.failure_count,
        cookie_names=list(view.cookie_names),
        cookies_earliest_expiry=view.cookies_earliest_expiry,
        proxy_id=view.proxy_id,
        proxy_display=view.proxy_display,
        created_at=view.created_at,
        updated_at=view.updated_at,
    )


def _cookies(platform: SourcePlatform, text: str):
    try:
        return parse_cookies(platform, text, now=datetime.now(UTC))
    except CookieImportError as error:
        raise _error(
            status.HTTP_422_UNPROCESSABLE_CONTENT, error.code, missing=list(error.missing)
        ) from None


@router.get("/source-accounts", response_model=SourceAccountsOverview)
async def list_source_accounts(_: Authorized, store: Store) -> SourceAccountsOverview:
    if store is None:
        return SourceAccountsOverview(
            available=False,
            platforms=[
                PlatformAccounts(
                    platform=platform,
                    mode="fallback",
                    min_spacing_seconds=60,
                    counts=StatusCounts(),
                    accounts=[],
                )
                for platform in PLATFORMS
            ],
        )
    policies = await _call(store.policies)
    accounts = [_account(view) for view in await _call(store.accounts)]
    platforms = []
    for policy in policies:
        mine = [account for account in accounts if account.platform == policy.platform]
        counts = StatusCounts()
        for account in mine:
            setattr(counts, account.status, getattr(counts, account.status) + 1)
        platforms.append(
            PlatformAccounts(
                platform=policy.platform,
                mode=policy.mode,
                min_spacing_seconds=policy.min_spacing_seconds,
                counts=counts,
                accounts=mine,
            )
        )
    return SourceAccountsOverview(available=True, platforms=platforms)


@router.put("/source-accounts/policies/{platform}", response_model=AccessPolicyUpdate)
async def update_access_policy(
    platform: SourcePlatform, payload: AccessPolicyUpdate, _: Authorized, store: Store
) -> AccessPolicyUpdate:
    view = await _call(
        _require(store).set_policy, platform, payload.mode, payload.min_spacing_seconds
    )
    return AccessPolicyUpdate(mode=view.mode, min_spacing_seconds=view.min_spacing_seconds)


@router.post("/source-accounts/validate", response_model=CookieValidation)
async def validate_cookies(payload: CookieValidationRequest, _: Authorized) -> CookieValidation:
    """A dry run of an import: the safe summary; nothing is stored."""
    summary = summarize(payload.platform, payload.cookies, now=datetime.now(UTC))
    return CookieValidation(
        valid=summary.error is None,
        count=summary.count,
        names=list(summary.names),
        earliest_expiry=summary.earliest_expiry,
        error=summary.error,
        missing=list(summary.missing),
    )


@router.post("/source-accounts", response_model=SourceAccount, status_code=status.HTTP_201_CREATED)
async def create_source_account(
    payload: SourceAccountCreate, _: Authorized, store: Store
) -> SourceAccount:
    store = _require(store)
    cookies = _cookies(payload.platform, payload.cookies)
    view = await _call(
        store.add_account, payload.platform, payload.label, cookies, payload.proxy_id
    )
    return _account(view)


@router.put("/source-accounts/{account_id}/cookies", response_model=SourceAccount)
async def reimport_cookies(
    account_id: str, payload: CookieReimport, _: Authorized, store: Store
) -> SourceAccount:
    store = _require(store)
    current = await _call(store.account, account_id)
    cookies = _cookies(current.platform, payload.cookies)
    return _account(await _call(store.replace_cookies, account_id, cookies))


@router.patch("/source-accounts/{account_id}", response_model=SourceAccount)
async def update_source_account(
    account_id: str, payload: SourceAccountUpdate, _: Authorized, store: Store
) -> SourceAccount:
    store = _require(store)
    given = payload.model_fields_set
    view = await _call(
        store.update_account,
        account_id,
        label=payload.label if "label" in given and payload.label is not None else UNSET,
        proxy_id=payload.proxy_id if "proxy_id" in given else UNSET,
        disabled=payload.disabled,
    )
    return _account(view)


@router.delete("/source-accounts/{account_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_source_account(account_id: str, _: Authorized, store: Store) -> Response:
    await _call(_require(store).delete_account, account_id)
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.get("/source-proxies", response_model=list[SourceProxy])
async def list_source_proxies(_: Authorized, store: Store) -> list[SourceProxy]:
    views = await _call(_require(store).proxies)
    return [
        SourceProxy(
            id=view.id,
            scheme=view.scheme,  # type: ignore[arg-type]
            display=view.display,
            account_platform=view.account_platform,  # type: ignore[arg-type]
            account_label=view.account_label,
        )
        for view in views
    ]


@router.post("/source-proxies/import", response_model=ProxyImportSummary)
async def import_source_proxies(
    payload: ProxyImportRequest, _: Authorized, store: Store
) -> ProxyImportSummary:
    store = _require(store)
    try:
        parsed = parse_proxy_list(payload.text)
    except ProxyImportError as error:
        raise _error(status.HTTP_422_UNPROCESSABLE_CONTENT, error.code) from None
    result = await _call(store.import_proxies, parsed)
    return ProxyImportSummary(
        added=result.added, duplicates=result.duplicates, invalid_lines=list(result.invalid_lines)
    )


@router.delete("/source-proxies/{proxy_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_source_proxy(proxy_id: str, _: Authorized, store: Store) -> Response:
    await _call(_require(store).delete_proxy, proxy_id)
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.post("/source-accounts/{account_id}/test", response_model=SessionCheckResult)
async def test_source_account(
    account_id: str,
    _: Authorized,
    store: Store,
    checker: Annotated[Callable[..., Any], Depends(get_session_checker)],
) -> SessionCheckResult:
    """One live request with the account's session; only an operator's press sends it."""
    store = _require(store)
    view = await _call(store.account, account_id)
    access = await _call(store.access, account_id)
    verdict = await checker(view.platform, access)
    if verdict != "inconclusive":
        view = await _call(store.record_check, account_id, verdict == "valid")
    logger.info("source account session check platform=%s result=%s", view.platform, verdict)
    return SessionCheckResult(result=verdict, account=_account(view))
```

Create `python/src/thoth_control_plane/acquisition/accounts/session_check.py`:

```python
"""A manual session check: one request to a page only a signed-in session can open.

Run only when the operator presses "Test session"; never by acquisition and never by the
suite. The verdict is `valid`, `expired`, or `inconclusive` (timeout, block, or an answer the
check cannot read). Nothing about the response leaves this module but the verdict.
"""

from __future__ import annotations

import asyncio
import json
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from typing import Any, Literal
from urllib.parse import urlsplit

from thoth_control_plane.acquisition.accounts.access import SessionAccess
from thoth_control_plane.acquisition.card_browser import is_login_path

Verdict = Literal["valid", "expired", "inconclusive"]
TIMEOUT_SECONDS = 20.0
CHECK_OPTIONS: dict[str, Any] = {
    "impersonate": "chrome",
    "stealthy_headers": True,
    "follow_redirects": "safe",
    "timeout": 15,
    "retries": 0,
}


@dataclass(frozen=True)
class SessionCheck:
    url: str
    # Where a signed-out request ends up, or is redirected to.
    signed_out_paths: tuple[str, ...] = ()
    signed_out_hosts: tuple[str, ...] = ()
    # For a JSON check: the keys whose value is present only for a signed-in session.
    signed_in_json: tuple[str, ...] = ()


CHECKS: dict[str, SessionCheck] = {
    "tiktok": SessionCheck(
        url="https://www.tiktok.com/passport/web/account/info/",
        signed_in_json=("data", "username"),
    ),
    "threads": SessionCheck(
        url="https://www.threads.com/settings/account",
        signed_out_paths=("/login",),
    ),
    "instagram": SessionCheck(
        url="https://www.instagram.com/accounts/edit/",
        signed_out_paths=("/accounts/login", "/login"),
    ),
    "x": SessionCheck(
        url="https://x.com/settings/account",
        signed_out_paths=("/i/flow/login", "/login"),
    ),
    "youtube": SessionCheck(
        url="https://www.youtube.com/account",
        signed_out_paths=("/signin", "/ServiceLogin"),
        signed_out_hosts=("accounts.google.com",),
    ),
}


def _signed_out(check: SessionCheck, url: object) -> bool:
    if not url:
        return False
    host = (urlsplit(str(url)).hostname or "").lower()
    return host in check.signed_out_hosts or is_login_path(url, check.signed_out_paths)


def judge(check: SessionCheck, response: Any) -> Verdict:
    """The verdict for one response; reads its status, URL, redirect, and body only."""
    status = getattr(response, "status", None)
    headers = getattr(response, "headers", None) or {}
    location = headers.get("location") or headers.get("Location")
    if _signed_out(check, getattr(response, "url", None)) or _signed_out(check, location):
        return "expired"
    if status != 200:
        return "inconclusive"
    if not check.signed_in_json:
        return "valid"
    body = getattr(response, "body", b"")
    try:
        node: Any = json.loads(body.decode("utf-8") if isinstance(body, bytes) else str(body))
    except (ValueError, UnicodeDecodeError):
        return "inconclusive"
    for key in check.signed_in_json:
        node = node.get(key) if isinstance(node, dict) else None
    return "valid" if node else "expired"


async def _scrapling_get(url: str, **kwargs: Any) -> Any:
    from scrapling.fetchers import AsyncFetcher

    return await AsyncFetcher.get(url, **kwargs)


async def check_session(
    platform: str,
    access: SessionAccess,
    get: Callable[..., Awaitable[Any]] | None = None,
) -> Verdict:
    check = CHECKS[platform]
    try:
        response = await asyncio.wait_for(
            (get or _scrapling_get)(check.url, **CHECK_OPTIONS, **access.request_kwargs()),
            TIMEOUT_SECONDS,
        )
    except Exception:
        return "inconclusive"
    return judge(check, response)
```

Apply this patch to `python/src/thoth_control_plane/api/app.py`:

```diff
diff --git a/python/src/thoth_control_plane/api/app.py b/python/src/thoth_control_plane/api/app.py
--- a/python/src/thoth_control_plane/api/app.py
+++ b/python/src/thoth_control_plane/api/app.py
@@ -15,6 +15,7 @@ from fastapi.middleware.cors import CORSMiddleware
 from fastapi.responses import JSONResponse
 from temporalio.service import RPCError
 
+from thoth_control_plane.acquisition.accounts.vault import Vault
 from thoth_control_plane.api.routes.edit_documents import router as edit_document_router
 from thoth_control_plane.api.routes.editor_assets import router as editor_asset_router
 from thoth_control_plane.api.routes.health import router as health_router
@@ -22,6 +23,7 @@ from thoth_control_plane.api.routes.internal_render_jobs import router as intern
 from thoth_control_plane.api.routes.prompt_lab import router as prompt_lab_router
 from thoth_control_plane.api.routes.prompt_proposals import router as prompt_proposal_router
 from thoth_control_plane.api.routes.render_jobs import router as render_job_router
+from thoth_control_plane.api.routes.source_accounts import router as source_account_router
 from thoth_control_plane.api.routes.studio_imports import router as studio_import_router
 from thoth_control_plane.api.routes.studio_review import router as studio_review_router
 from thoth_control_plane.api.routes.workflows import router as workflow_router
@@ -82,6 +84,7 @@ from thoth_control_plane.infrastructure.renderer_gateway import (
     HttpRendererGateway,
     UnavailableRendererGateway,
 )
+from thoth_control_plane.infrastructure.source_account_store import SourceAccountStore
 from thoth_control_plane.infrastructure.studio_import_repository import (
     PostgresStudioImportRepository,
 )
@@ -156,6 +159,14 @@ async def _reconcile_render_deadlines(service: RenderJobService, interval: float
             await service.reconcile_expired(datetime.now(UTC))
 
 
+def _source_account_store(settings: Settings) -> SourceAccountStore | None:
+    """The source-account store, when the vault key and the editor database are configured."""
+    vault = Vault.from_key(settings.account_vault_key)
+    if vault is None or settings.THOTH_EDITOR_DATABASE_URL is None:
+        return None
+    return SourceAccountStore.connect(settings.THOTH_EDITOR_DATABASE_URL.get_secret_value(), vault)
+
+
 def create_app(
     settings: Settings | None = None,
     gateway: WorkflowGateway | None = None,
@@ -168,6 +179,7 @@ def create_app(
     render_job_service: RenderJobService | None = None,
     studio_review_repository: StudioReviewRepository | None = None,
     studio_import_repository: StudioImportRepository | None = None,
+    source_account_store: SourceAccountStore | None = None,
 ) -> FastAPI:
     """Create an isolated v1 API application for the supplied workflow gateway."""
     settings = settings or Settings()  # type: ignore[call-arg]
@@ -273,6 +285,7 @@ def create_app(
     app.state.render_job_service = render_service
     app.state.studio_review_service = StudioReviewService(studio_review_repository)
     app.state.studio_import_service = StudioImportService(studio_import_repository)
+    app.state.source_account_store = source_account_store or _source_account_store(settings)
 
     app.add_middleware(
         CORSMiddleware,
@@ -339,6 +352,15 @@ def create_app(
                     return JSONResponse(
                         status_code=422, content={"detail": {"code": "missing_idempotency_key"}}
                     )
+        if "/source-accounts" in path or "/source-proxies" in path:
+            # These bodies hold cookies and proxy credentials: name the field, never echo it.
+            errors = [
+                {"field": str(error.get("loc", ("",))[-1]), "code": str(error.get("type", ""))}
+                for error in exc.errors()
+            ]
+            return JSONResponse(
+                status_code=422, content={"detail": {"code": "invalid_request", "errors": errors}}
+            )
         if request.method == "GET" and path.endswith("/editor-assets"):
             return JSONResponse(
                 status_code=422, content={"detail": {"code": "invalid_asset_query"}}
@@ -360,6 +382,7 @@ def create_app(
     app.include_router(render_job_router, prefix="/api/v1")
     app.include_router(studio_review_router, prefix="/api/v1")
     app.include_router(studio_import_router, prefix="/api/v1")
+    app.include_router(source_account_router, prefix="/api/v1")
     # Unversioned and unpublished: only the private renderer ever calls these.
     app.include_router(internal_render_router)
     return app
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `MSYS_NO_PATHCONV=1 timeout 590 wsl -e bash /mnt/d/thoth-tmp/bu/pt.sh tests/api tests/acquisition/accounts tests/activities -p no:warnings`
Expected: PASS.

- [ ] **Step 5: Regenerate the OpenAPI contract**

Write `D:/thoth-tmp/bu/export_openapi.sh` (LF) with the Write tool. It pins the versions `python/uv.lock` resolves, so the export matches the committed contract's generator:

```bash
cd "$1/python" && PYTHONPATH=src ~/.local/bin/uv run --no-project --python 3.12 --with fastapi==0.141.1 --with pydantic==2.13.5 --with pydantic-core==2.46.5 --with starlette==1.6.0 --with pydantic-settings==2.15.0 --with temporalio --with httpx --with typer --with psycopg[binary] --with sqlalchemy --with alembic --with boto3 --with python-multipart --with pyjwt --with agno --with pillow --with pyyaml --with cryptography python scripts/export_openapi.py
```

If `grep -n -A1 'name = "fastapi"' python/uv.lock` names another version, use the locked versions instead and ledger a ruling. Then:

```bash
MSYS_NO_PATHCONV=1 wsl -e bash /mnt/d/thoth-tmp/bu/export_openapi.sh /mnt/c/Users/mfr/Documents/MyTools/CLIPPER
python - <<'PY'
import json, subprocess
old = json.loads(subprocess.run(["git", "show", "HEAD:python/openapi.json"], capture_output=True, check=True, cwd="C:/Users/mfr/Documents/MyTools/CLIPPER").stdout)
new = json.load(open("C:/Users/mfr/Documents/MyTools/CLIPPER/python/openapi.json", encoding="utf-8"))
def walk(a, b, path=""):
    if isinstance(a, dict) and isinstance(b, dict):
        for k in a:
            if k not in b: print("REMOVED", path + "/" + k)
            else: walk(a[k], b[k], path + "/" + k)
        for k in b:
            if k not in a: print("ADDED", path + "/" + k)
    elif a != b:
        print("CHANGED", path)
walk(old, new)
PY
```

Expected: only `ADDED` lines, for 14 schemas and the 9 `source-…` paths. Any `REMOVED` or `CHANGED` line means the generator differs from the one that produced the committed contract: stop and investigate. The textual `git diff` is large, because `sort_keys` interleaves the new entries; the semantic check above is the gate.

- [ ] **Step 6: Document the key and pass it to the services**

```bash
python - <<'PY'
from pathlib import Path

ROOT = Path("C:/Users/mfr/Documents/MyTools/CLIPPER")


def edit(rel, fn):
    path = ROOT / rel
    data = path.read_bytes().decode("utf-8")
    crlf = "\r\n" in data
    text = fn(data.replace("\r\n", "\n"))
    path.write_bytes((text.replace("\n", "\r\n") if crlf else text).encode("utf-8"))


line = '      THOTH_EDITOR_DATABASE_URL: "postgresql://thoth_editor:${THOTH_EDITOR_POSTGRES_PASSWORD:?set THOTH_EDITOR_POSTGRES_PASSWORD}@editor-postgresql:5432/thoth_editor"\n'


def compose(text):
    assert text.count(line) == 2
    return text.replace(line, line + '      # Optional Fernet key; empty keeps source accounts off and acquisition anonymous.\n      THOTH_ACCOUNT_VAULT_KEY: "${THOTH_ACCOUNT_VAULT_KEY:-}"\n')


row = "| `THOTH_EDITOR_DATABASE_URL` | FastAPI, `thoth-control editor migrate` | Secret PostgreSQL URL for immutable Creator Studio revisions. Stage 1 Compose derives it from the isolated editor database password. |\n"


def docs(text):
    assert text.count(row) == 1
    return text.replace(row, row + '| `THOTH_ACCOUNT_VAULT_KEY` | FastAPI, Python worker | Optional secret Fernet key that seals source-account cookies and proxies in the editor database. Without it (or without `THOTH_EDITOR_DATABASE_URL`) source accounts are off and acquisition runs anonymously. Generate one with `python -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())"`. |\n')


edit("compose.stage1.local.yml", compose)
edit("docs/python-control-plane.md", docs)
PY
MSYS_NO_PATHCONV=1 timeout 590 wsl -e bash /mnt/d/thoth-tmp/bu/pt.sh tests/deployment -p no:warnings
```

Expected: the deployment contract tests PASS.

- [ ] **Step 7: Run Ruff and commit**

Run the Ruff command from Global Constraints (expected: clean).

```bash
git add python/src/thoth_control_plane/domain/source_accounts.py python/src/thoth_control_plane/api python/src/thoth_control_plane/acquisition/accounts/session_check.py python/openapi.json python/tests/api python/tests/acquisition/accounts python/tests/activities/test_legacy_scout.py compose.stage1.local.yml docs/python-control-plane.md
git commit -m "feat(accounts): manage source accounts and proxies over the api"
```

---

### Task 9: Dashboard pages

**Files:**
- Regenerate: `dashboard/src/api/generated/control-plane.ts`
- Create: `dashboard/src/api/source-accounts.ts`, `dashboard/src/components/SourceAccounts.tsx`, `SourceAccountDialogs.tsx`, `SourceProxies.tsx`, `dashboard/src/pen-source-accounts.css`
- Modify (CRLF): `dashboard/src/App.tsx`, `dashboard/src/index.css`
- Test: `dashboard/src/components/SourceAccounts.test.tsx`, `SourceProxies.test.tsx`

**Interfaces:**
- Consumes: Task 8's routes, through the regenerated `components["schemas"]` types.
- Produces:
  - In `source-accounts.ts`:
    - `createSourceAccountsClient(options)` and the module-level `sourceAccountsClient`;
    - `SourceAccountsRequestError(status, code, missing)`;
    - `errorText(error)`, which gives fixed copy and never the server's words;
    - `PLATFORMS`, `REQUIRED_COOKIES`, `platformLabel`.
  - Components:
    - `SourceAccounts({ client, onManageProxies })`;
    - `SourceProxies({ client, onBack })`;
    - the dialogs `AddAccountDialog`, `ReimportDialog`, `EditAccountDialog`.
  - `App` views `accounts` ("Source Accounts", "Access / 07") and `proxies` ("Proxies"). The sidebar's Tools group gains "Source Accounts", highlighted on both views.

The frames are the authority for layout and copy; open `Source Accounts · TikTok mixed statuses` (`Sl5Lg`) and `Source Accounts · Proxies pool` (`UL7Rh`) side by side with the running page. The palette:
- text `#f5f3ee` and `#c5c6c7`;
- cards `#242628`, rows `#2a2c2e`, inputs `#101113`, borders `#47494a`;
- accent `#d49a79`;
- status green `#78c69b` on `#244135`, gold `#d7af5f` on `#493b27`, red `#e8918f` on `#4a3030`.

A pasted cookie export or proxy list is masked on screen (`-webkit-text-security: disc`) and never echoed. Cookie values never reach the page: the server returns names only.

- [ ] **Step 1: Regenerate the API types**

```bash
cd dashboard && bun install --frozen-lockfile && bun run generate:control-plane-types && cd .. && git diff --stat -- dashboard/src/api/generated/control-plane.ts
```

Expected: one file with insertions only (about 730 lines).

- [ ] **Step 2: Write the failing tests**

```bash
python D:/thoth-tmp/bu/sa/extract.py create 9 dashboard/src/components/SourceAccounts.test.tsx dashboard/src/components/SourceProxies.test.tsx
```

Create `dashboard/src/components/SourceAccounts.test.tsx`:

```tsx
/// <reference types="bun-types" />

import { afterEach, expect, mock, test } from "bun:test";
import { cleanup, render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { SourceAccounts } from "./SourceAccounts";
import {
  SourceAccountsRequestError,
  type SourceAccount,
  type SourceAccountsClient,
  type SourceAccountsOverview,
} from "@/api/source-accounts";

const DAY = 86_400_000;
const NOW = Date.now();

function account(overrides: Partial<SourceAccount>): SourceAccount {
  return {
    id: "00000000-0000-0000-0000-000000000001",
    platform: "tiktok",
    label: "Cedar · primary",
    status: "healthy",
    cooldown_until: null,
    last_used_at: null,
    last_outcome: null,
    success_count: 0,
    failure_count: 0,
    cookie_names: ["sessionid", "tt_csrf_token"],
    cookies_earliest_expiry: new Date(NOW + 12 * DAY).toISOString(),
    proxy_id: null,
    proxy_display: null,
    created_at: new Date(NOW).toISOString(),
    updated_at: new Date(NOW).toISOString(),
    ...overrides,
  };
}

const ROWS = [
  account({}),
  account({ id: "00000000-0000-0000-0000-000000000002", label: "Cedar · backup", status: "cooldown",
    cooldown_until: new Date(NOW + 3_600_000).toISOString(), proxy_id: "p1", proxy_display: "proxy.thoth.local:8080" }),
  account({ id: "00000000-0000-0000-0000-000000000003", label: "Archive login", status: "expired" }),
];

function overview(available = true, accounts = ROWS, mode: "anonymous" | "fallback" | "always" = "fallback"): SourceAccountsOverview {
  return {
    available,
    platforms: ["tiktok", "threads", "instagram", "x", "youtube"].map((platform) => {
      const mine = accounts.filter((row) => row.platform === platform);
      const count = (status: string) => mine.filter((row) => row.status === status).length;
      return {
        platform: platform as SourceAccount["platform"],
        mode,
        min_spacing_seconds: 60,
        counts: { healthy: count("healthy"), cooldown: count("cooldown"), expired: count("expired"), disabled: count("disabled") },
        accounts: mine,
      };
    }),
  };
}

function fakeClient(state: SourceAccountsOverview = overview()): SourceAccountsClient & Record<string, ReturnType<typeof mock>> {
  return {
    overview: mock(async () => state),
    setPolicy: mock(async (_platform, policy) => policy),
    validate: mock(async (_platform, cookies: string) => cookies.includes("sessionid")
      ? { valid: true, count: 1, names: ["sessionid"], earliest_expiry: "2030-01-01T00:00:00Z", error: null, missing: [] }
      : { valid: false, count: 0, names: [], earliest_expiry: null, error: "missing_required_cookie", missing: ["sessionid"] }),
    create: mock(async (request) => account({ label: request.label })),
    reimport: mock(async (id: string) => account({ id })),
    update: mock(async (id: string, update) => account({ id, ...(update.label ? { label: update.label } : {}),
      ...(update.disabled ? { status: "disabled" } : {}) })),
    remove: mock(async () => undefined),
    test: mock(async (id: string) => ({ result: "valid", account: account({ id }) })),
    proxies: mock(async () => []),
    importProxies: mock(async () => ({ added: 0, duplicates: 0, invalid_lines: [] })),
    removeProxy: mock(async () => undefined),
  } as never;
}

afterEach(cleanup);

test("shows the platform's access, counts, and accounts without any cookie value", async () => {
  render(<SourceAccounts client={fakeClient()} onManageProxies={() => {}} />);
  expect(await screen.findByText("Cedar · primary")).toBeDefined();
  expect(screen.getByRole("tab", { name: "TikTok", selected: true })).toBeDefined();
  expect(screen.getByRole("radio", { name: "fallback", checked: true })).toBeDefined();
  const table = screen.getByRole("table");
  expect(within(table).getByText("cooldown")).toBeDefined();
  expect(within(table).getByText("re-import needed")).toBeDefined();
  expect(within(table).getByText("proxy.thoth.local:8080")).toBeDefined();
  expect(within(table).getAllByText("Direct").length).toBe(2);
  expect(within(table).getAllByText("in 12 days").length).toBe(3);
  expect(screen.getByText("03 accounts")).toBeDefined();
});

test("changing the access mode saves the platform's policy", async () => {
  const client = fakeClient();
  render(<SourceAccounts client={client} onManageProxies={() => {}} />);
  await userEvent.click(await screen.findByRole("radio", { name: "always" }));
  expect(client.setPolicy).toHaveBeenCalledWith("tiktok", { mode: "always", min_spacing_seconds: 60 });
});

test("an unavailable server explains itself and disables adding", async () => {
  render(<SourceAccounts client={fakeClient(overview(false, []))} onManageProxies={() => {}} />);
  expect(await screen.findByText(/not configured on this server/)).toBeDefined();
  expect((screen.getAllByRole("button", { name: /add account/i })[0] as HTMLButtonElement).disabled).toBe(true);
});

test("an empty platform invites an import, and no healthy account warns", async () => {
  render(<SourceAccounts client={fakeClient()} onManageProxies={() => {}} />);
  await userEvent.click(await screen.findByRole("tab", { name: "Threads" }));
  expect(screen.getByText("No Threads accounts yet")).toBeDefined();
  expect(screen.getByText(/No healthy account. Acquisition on Threads runs anonymously/)).toBeDefined();
});

test("testing a session reports the verdict", async () => {
  const client = fakeClient();
  render(<SourceAccounts client={client} onManageProxies={() => {}} />);
  await screen.findByText("Cedar · primary");
  await userEvent.click(screen.getAllByRole("button", { name: "Test" })[0]);
  expect(await screen.findByText("Cedar · primary: Session valid")).toBeDefined();
  expect(client.test).toHaveBeenCalledWith(ROWS[0].id);
});

test("adding an account validates the export before it can be imported", async () => {
  const client = fakeClient();
  render(<SourceAccounts client={client} onManageProxies={() => {}} />);
  await screen.findByText("Cedar · primary");
  await userEvent.click(screen.getAllByRole("button", { name: /add account/i })[0]);
  const dialog = await screen.findByRole("dialog");
  await userEvent.type(within(dialog).getByLabelText("Account label"), "Cedar · new");
  await userEvent.click(within(dialog).getByRole("button", { name: "Paste" }));
  const importButton = within(dialog).getByRole("button", { name: "Import account" }) as HTMLButtonElement;
  await userEvent.type(within(dialog).getByLabelText("Cookie export"), "no login here");
  expect(await within(dialog).findByText(/Missing sessionid/)).toBeDefined();
  expect(importButton.disabled).toBe(true);
  await userEvent.clear(within(dialog).getByLabelText("Cookie export"));
  await userEvent.type(within(dialog).getByLabelText("Cookie export"), ".tiktok.com sessionid secret");
  expect(await within(dialog).findByText(/Found 1 cookies; sessionid/)).toBeDefined();
  await waitFor(() => expect(importButton.disabled).toBe(false));
  await userEvent.click(importButton);
  expect(client.create).toHaveBeenCalledWith({
    platform: "tiktok", label: "Cedar · new", cookies: ".tiktok.com sessionid secret", proxy_id: null,
  });
});

test("a refused import names what is missing, never the server's words", async () => {
  const client = fakeClient();
  (client.create as unknown as ReturnType<typeof mock>).mockImplementation(async () => {
    throw new SourceAccountsRequestError(409, "label_taken");
  });
  render(<SourceAccounts client={client} onManageProxies={() => {}} />);
  await screen.findByText("Cedar · primary");
  await userEvent.click(screen.getAllByRole("button", { name: /add account/i })[0]);
  const dialog = await screen.findByRole("dialog");
  await userEvent.type(within(dialog).getByLabelText("Account label"), "Cedar · primary");
  await userEvent.click(within(dialog).getByRole("button", { name: "Paste" }));
  await userEvent.type(within(dialog).getByLabelText("Cookie export"), "sessionid");
  await waitFor(() => expect((within(dialog).getByRole("button", { name: "Import account" }) as HTMLButtonElement).disabled).toBe(false));
  await userEvent.click(within(dialog).getByRole("button", { name: "Import account" }));
  expect(await within(dialog).findByText("Another account on this platform already uses that label.")).toBeDefined();
});

test("editing renames, disables, and deletes with a confirmation", async () => {
  const client = fakeClient();
  render(<SourceAccounts client={client} onManageProxies={() => {}} />);
  await screen.findByText("Cedar · primary");
  await userEvent.click(screen.getAllByRole("button", { name: "Edit" })[0]);
  let dialog = await screen.findByRole("dialog");
  const label = within(dialog).getByLabelText("Account label");
  await userEvent.clear(label);
  await userEvent.type(label, "Renamed");
  await userEvent.click(within(dialog).getByRole("button", { name: "Save changes" }));
  expect(client.update).toHaveBeenCalledWith(ROWS[0].id, { label: "Renamed", proxy_id: null });

  await userEvent.click(screen.getAllByRole("button", { name: "Edit" })[0]);
  dialog = await screen.findByRole("dialog");
  await userEvent.click(within(dialog).getByRole("button", { name: "Disable account" }));
  expect(client.update).toHaveBeenCalledWith(ROWS[0].id, { disabled: true });

  await userEvent.click(screen.getAllByRole("button", { name: "Edit" })[0]);
  dialog = await screen.findByRole("dialog");
  await userEvent.click(within(dialog).getByRole("button", { name: "Delete" }));
  expect(client.remove).not.toHaveBeenCalled();
  await userEvent.click(within(dialog).getByRole("button", { name: "Delete account" }));
  expect(client.remove).toHaveBeenCalledWith(ROWS[0].id);
});

test("manage proxies hands over to the proxy view", async () => {
  const onManage = mock(() => {});
  render(<SourceAccounts client={fakeClient()} onManageProxies={onManage} />);
  await userEvent.click(await screen.findByRole("button", { name: /manage proxies/i }));
  expect(onManage).toHaveBeenCalled();
});
```

Create `dashboard/src/components/SourceProxies.test.tsx`:

```tsx
/// <reference types="bun-types" />

import { afterEach, expect, mock, test } from "bun:test";
import { cleanup, render, screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { SourceProxies } from "./SourceProxies";
import type { SourceAccountsClient, SourceProxy } from "@/api/source-accounts";

const POOL: SourceProxy[] = [
  { id: "p1", scheme: "http", display: "proxy.thoth.local:8080", account_platform: "tiktok", account_label: "Cedar · backup" },
  { id: "p2", scheme: "https", display: "eu-west.proxy.local:3128", account_platform: null, account_label: null },
];

function fakeClient(pool: SourceProxy[] = POOL) {
  return {
    proxies: mock(async () => pool),
    importProxies: mock(async () => ({ added: 12, duplicates: 2, invalid_lines: [7] })),
    removeProxy: mock(async () => undefined),
  } as unknown as SourceAccountsClient & Record<string, ReturnType<typeof mock>>;
}

afterEach(cleanup);

test("lists the pool by host and port and blocks deleting an assigned proxy", async () => {
  const client = fakeClient();
  render(<SourceProxies client={client} onBack={() => {}} />);
  const table = await screen.findByRole("table");
  expect(within(table).getByText("TikTok · Cedar · backup")).toBeDefined();
  expect(within(table).getByText("Unassigned")).toBeDefined();
  const held = within(table).getByRole("button", { name: "Delete proxy.thoth.local:8080" }) as HTMLButtonElement;
  expect(held.title).toBe("Assigned to an account");
  expect(held.disabled).toBe(true);
  await userEvent.click(within(table).getByRole("button", { name: "Delete eu-west.proxy.local:3128" }));
  expect(client.removeProxy).toHaveBeenCalledWith("p2");
  expect(screen.getByText("02 proxies")).toBeDefined();
});

test("importing shows the summary by line number only", async () => {
  const client = fakeClient();
  render(<SourceProxies client={client} onBack={() => {}} />);
  await screen.findByRole("table");
  await userEvent.click(screen.getAllByRole("button", { name: /import proxies/i })[0]);
  const dialog = await screen.findByRole("dialog");
  await userEvent.type(within(dialog).getByLabelText("Proxy lines"), "http://u:secret@1.2.3.4:8080");
  await userEvent.click(within(dialog).getByRole("button", { name: "Import proxies" }));
  expect(await within(dialog).findByText("12 added, 2 duplicates skipped, 1 invalid line (line 7)")).toBeDefined();
  expect(client.importProxies).toHaveBeenCalledWith("http://u:secret@1.2.3.4:8080");
  expect(within(dialog).getByRole("button", { name: "Done" })).toBeDefined();
});

test("an empty pool invites an import", async () => {
  render(<SourceProxies client={fakeClient([])} onBack={() => {}} />);
  expect(await screen.findByText("No proxies yet")).toBeDefined();
});
```

- [ ] **Step 3: Run the tests to verify they fail**

Run: `cd dashboard && bun test src/components/SourceAccounts.test.tsx src/components/SourceProxies.test.tsx`
Expected: FAIL. The module `./SourceAccounts` cannot be found.

- [ ] **Step 4: Implement**

```bash
python D:/thoth-tmp/bu/sa/extract.py create 9 dashboard/src/api/source-accounts.ts dashboard/src/components/SourceAccountDialogs.tsx dashboard/src/components/SourceAccounts.tsx dashboard/src/components/SourceProxies.tsx dashboard/src/pen-source-accounts.css
```

Create `dashboard/src/api/source-accounts.ts`:

```ts
import type { components } from "@/api/generated/control-plane";

export type SourcePlatform = components["schemas"]["SourceAccountCreate"]["platform"];
export type AccessMode = components["schemas"]["AccessPolicyUpdate"]["mode"];
export type SourceAccount = components["schemas"]["SourceAccount"];
export type PlatformAccounts = components["schemas"]["PlatformAccounts"];
export type SourceAccountsOverview = components["schemas"]["SourceAccountsOverview"];
export type AccessPolicyUpdate = components["schemas"]["AccessPolicyUpdate"];
export type CookieValidation = components["schemas"]["CookieValidation"];
export type SourceProxy = components["schemas"]["SourceProxy"];
export type ProxyImportSummary = components["schemas"]["ProxyImportSummary"];
export type SessionCheckResult = components["schemas"]["SessionCheckResult"];
export type SourceAccountUpdate = components["schemas"]["SourceAccountUpdate"];

export const PLATFORMS: { id: SourcePlatform; label: string }[] = [
  { id: "tiktok", label: "TikTok" },
  { id: "threads", label: "Threads" },
  { id: "instagram", label: "Instagram" },
  { id: "x", label: "X" },
  { id: "youtube", label: "YouTube" },
];

export function platformLabel(platform: string): string {
  return PLATFORMS.find((entry) => entry.id === platform)?.label ?? platform;
}

export const REQUIRED_COOKIES: Record<SourcePlatform, string[]> = {
  tiktok: ["sessionid"],
  threads: ["sessionid"],
  instagram: ["sessionid"],
  x: ["auth_token", "ct0"],
  youtube: ["SAPISID", "__Secure-3PSID"],
};

/** A failed source-account call: only the status and the server's code survive. */
export class SourceAccountsRequestError extends Error {
  readonly status: number | null;
  readonly code: string | null;
  readonly missing: string[];

  constructor(status: number | null, code: string | null, missing: string[] = []) {
    super(code ?? "source_accounts_request_failed");
    this.status = status;
    this.code = code;
    this.missing = missing;
  }
}

export type SourceAccountsClient = {
  overview: () => Promise<SourceAccountsOverview>;
  setPolicy: (platform: SourcePlatform, policy: AccessPolicyUpdate) => Promise<AccessPolicyUpdate>;
  validate: (platform: SourcePlatform, cookies: string) => Promise<CookieValidation>;
  create: (request: {
    platform: SourcePlatform;
    label: string;
    cookies: string;
    proxy_id: string | null;
  }) => Promise<SourceAccount>;
  reimport: (accountId: string, cookies: string) => Promise<SourceAccount>;
  update: (accountId: string, update: SourceAccountUpdate) => Promise<SourceAccount>;
  remove: (accountId: string) => Promise<void>;
  test: (accountId: string) => Promise<SessionCheckResult>;
  proxies: () => Promise<SourceProxy[]>;
  importProxies: (text: string) => Promise<ProxyImportSummary>;
  removeProxy: (proxyId: string) => Promise<void>;
};

type ClientOptions = { baseUrl?: string; apiKey?: string; fetch?: typeof fetch };

export function createSourceAccountsClient(options: ClientOptions = {}): SourceAccountsClient {
  const baseUrl = (options.baseUrl ?? import.meta.env.VITE_CONTROL_PLANE_URL ?? "").replace(/\/$/, "");
  const apiKey = options.apiKey ?? import.meta.env.VITE_CONTROL_PLANE_API_KEY ?? "";
  const doFetch = options.fetch ?? fetch;

  async function call<T>(path: string, method = "GET", body?: unknown): Promise<T> {
    let response: Response;
    try {
      response = await doFetch(`${baseUrl}/api/v1${path}`, {
        method,
        headers: {
          Authorization: `Bearer ${apiKey}`,
          ...(body === undefined ? {} : { "Content-Type": "application/json" }),
        },
        body: body === undefined ? undefined : JSON.stringify(body),
      });
    } catch {
      throw new SourceAccountsRequestError(null, null);
    }
    if (!response.ok) {
      const payload = (await response.json().catch(() => null)) as
        | { detail?: { code?: unknown; missing?: unknown } }
        | null;
      const code = payload?.detail?.code;
      const missing = payload?.detail?.missing;
      throw new SourceAccountsRequestError(
        response.status,
        typeof code === "string" ? code : null,
        Array.isArray(missing) ? missing.filter((name): name is string => typeof name === "string") : [],
      );
    }
    return (response.status === 204 ? undefined : await response.json()) as T;
  }

  const id = encodeURIComponent;
  return {
    overview: () => call("/source-accounts"),
    setPolicy: (platform, policy) => call(`/source-accounts/policies/${id(platform)}`, "PUT", policy),
    validate: (platform, cookies) => call("/source-accounts/validate", "POST", { platform, cookies }),
    create: (request) => call("/source-accounts", "POST", request),
    reimport: (accountId, cookies) => call(`/source-accounts/${id(accountId)}/cookies`, "PUT", { cookies }),
    update: (accountId, update) => call(`/source-accounts/${id(accountId)}`, "PATCH", update),
    remove: (accountId) => call(`/source-accounts/${id(accountId)}`, "DELETE"),
    test: (accountId) => call(`/source-accounts/${id(accountId)}/test`, "POST"),
    proxies: () => call("/source-proxies"),
    importProxies: (text) => call("/source-proxies/import", "POST", { text }),
    removeProxy: (proxyId) => call(`/source-proxies/${id(proxyId)}`, "DELETE"),
  };
}

export const sourceAccountsClient = createSourceAccountsClient();

const ERROR_TEXT: Record<string, string> = {
  source_accounts_unavailable: "Source accounts are not configured on this server.",
  label_taken: "Another account on this platform already uses that label.",
  proxy_in_use: "That proxy already serves another account.",
  proxy_not_found: "That proxy is no longer in the pool.",
  not_found: "That account no longer exists.",
  invalid_cookie_file: "The file is not a cookie export this page can read.",
  all_cookies_expired: "Every cookie in the export has expired. Sign in again and export.",
  missing_required_cookie: "The export is missing a required login cookie.",
  invalid_proxy_file: "The proxy list is too large. Import at most 500 lines.",
  undecryptable: "This account can no longer be read. Re-import its cookies.",
  invalid_request: "Some fields are not valid.",
};

/** Fixed, safe copy for an error; never the server's own words. */
export function errorText(error: unknown): string {
  const code = error instanceof SourceAccountsRequestError ? error.code : null;
  return (code && ERROR_TEXT[code]) || "The request did not complete. Try again.";
}
```

Create `dashboard/src/components/SourceAccountDialogs.tsx`:

```tsx
import { useEffect, useRef, useState, type ReactNode } from "react";
import { LockKeyhole, Upload } from "lucide-react";
import { PenDialog } from "@/components/PenDialog";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Textarea } from "@/components/ui/textarea";
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "@/components/ui/select";
import {
  PLATFORMS,
  REQUIRED_COOKIES,
  SourceAccountsRequestError,
  errorText,
  platformLabel,
  type CookieValidation,
  type SourceAccount,
  type SourceAccountsClient,
  type SourcePlatform,
  type SourceProxy,
} from "@/api/source-accounts";

const DIRECT = "direct";
const VALIDATE_DELAY_MS = 250;

function requiredCopy(platform: SourcePlatform): string {
  return `${platformLabel(platform)} requires ${REQUIRED_COOKIES[platform].join(" and ")}.`;
}

function failureText(error: unknown): string {
  if (error instanceof SourceAccountsRequestError && error.missing.length) {
    return `Missing ${error.missing.join(", ")}. Export cookies from a signed-in session.`;
  }
  return errorText(error);
}

function validationText(platform: SourcePlatform, result: CookieValidation): string {
  if (result.error === "missing_required_cookie") {
    return `Missing ${result.missing.join(", ")}. Export cookies from a signed-in ${platformLabel(platform)} session.`;
  }
  if (result.error === "all_cookies_expired") return "Every cookie in the export has expired.";
  if (result.error) return "The file is not a cookie export this page can read.";
  const expiry = result.earliest_expiry ? `; earliest expiry ${result.earliest_expiry.slice(0, 10)}` : "";
  return `Found ${result.count} cookies; ${result.names.join(", ")}${expiry}.`;
}

/** A cookie export from a file or a paste, validated by the server; values are never shown. */
function CookieInput({ platform, client, onChange }: {
  platform: SourcePlatform;
  client: SourceAccountsClient;
  onChange: (text: string, valid: boolean) => void;
}) {
  const [mode, setMode] = useState<"file" | "paste">("file");
  const [text, setText] = useState("");
  const [fileName, setFileName] = useState("");
  const [result, setResult] = useState<CookieValidation | null>(null);
  const [failed, setFailed] = useState(false);
  // The parent passes a fresh closure each render; only the export and platform revalidate.
  const report = useRef(onChange);
  report.current = onChange;

  useEffect(() => {
    if (!text) {
      setResult(null);
      report.current("", false);
      return;
    }
    let live = true;
    const timer = setTimeout(() => {
      client.validate(platform, text).then(
        (validation) => {
          if (!live) return;
          setResult(validation);
          setFailed(false);
          report.current(text, validation.valid);
        },
        () => {
          if (!live) return;
          setResult(null);
          setFailed(true);
          report.current(text, false);
        },
      );
    }, VALIDATE_DELAY_MS);
    return () => {
      live = false;
      clearTimeout(timer);
    };
  }, [text, platform, client]);

  return <div className="sa-cookie-input">
    <div className="sa-segmented" role="group" aria-label="Cookie source">
      {(["file", "paste"] as const).map((option) => <button key={option} type="button"
        aria-pressed={mode === option} onClick={() => setMode(option)}>
        {option === "file" ? "File" : "Paste"}</button>)}
    </div>
    {mode === "file" ? <label className="sa-dropzone">
      <Upload aria-hidden="true" />
      <strong>{fileName || "Choose cookie export file"}</strong>
      <small>JSON or Netscape format · cookie values stay hidden</small>
      <input type="file" accept=".txt,.json,text/plain,application/json" aria-label="Cookie export file"
        onChange={async (event) => {
          const file = event.target.files?.[0];
          if (!file) return;
          setFileName(file.name);
          setText(await file.text());
        }} />
    </label> : <Textarea aria-label="Cookie export" className="sa-secret-text" placeholder="Paste the cookie export"
      value={text} onChange={(event) => { setFileName(""); setText(event.target.value); }} />}
    <p className="sa-field-hint">{requiredCopy(platform)}</p>
    {result && <p role="status" className={result.valid ? "sa-validation sa-validation--ok" : "sa-validation sa-validation--error"}>
      {validationText(platform, result)}</p>}
    {failed && <p role="alert" className="sa-validation sa-validation--error">The export could not be checked. Try again.</p>}
    <p className="sa-lock-note"><LockKeyhole aria-hidden="true" />Only cookie names and expiry are shown after import.</p>
  </div>;
}

/** Direct, or one pool proxy; a proxy another account holds is shown but cannot be chosen. */
function ProxySelect({ proxies, value, onChange, currentProxyId, onImportProxies }: {
  proxies: SourceProxy[];
  value: string | null;
  onChange: (proxyId: string | null) => void;
  currentProxyId?: string | null;
  onImportProxies: () => void;
}) {
  const selected = proxies.find((proxy) => proxy.id === value);
  return <div className="sa-field">
    <label htmlFor="sa-proxy">Proxy</label>
    <Select value={value ?? DIRECT} onValueChange={(next) => onChange(next === DIRECT ? null : String(next))}>
      <SelectTrigger id="sa-proxy" aria-label="Proxy" className="sa-select"><SelectValue>{selected?.display ?? "Direct"}</SelectValue></SelectTrigger>
      <SelectContent>
        <SelectItem value={DIRECT}><span className="sa-option"><strong>Direct</strong><small>No proxy</small></span></SelectItem>
        {proxies.map((proxy) => {
          const held = proxy.account_label !== null && proxy.id !== currentProxyId;
          return <SelectItem key={proxy.id} value={proxy.id} disabled={held}>
            <span className="sa-option"><strong>{proxy.display}</strong>
              <small>{held ? `in use by ${platformLabel(proxy.account_platform ?? "")} · ${proxy.account_label}` : "Available"}</small></span>
          </SelectItem>;
        })}
      </SelectContent>
    </Select>
    {proxies.length ? <p className="sa-field-hint">Choose from the pool. One proxy per account.</p>
      : <p className="sa-field-hint">No proxies yet. <button type="button" className="sa-link" onClick={onImportProxies}>Import proxies first.</button></p>}
  </div>;
}

function Footer({ children }: { children: ReactNode }) {
  return <footer className="sa-dialog-footer">{children}</footer>;
}

export function AddAccountDialog({ open, onOpenChange, client, platform: initialPlatform, proxies, onSaved, onImportProxies }: {
  open: boolean;
  onOpenChange: (open: boolean) => void;
  client: SourceAccountsClient;
  platform: SourcePlatform;
  proxies: SourceProxy[];
  onSaved: (account: SourceAccount) => void;
  onImportProxies: () => void;
}) {
  const [platform, setPlatform] = useState<SourcePlatform>(initialPlatform);
  const [label, setLabel] = useState("");
  const [proxyId, setProxyId] = useState<string | null>(null);
  const [cookies, setCookies] = useState({ text: "", valid: false });
  const [error, setError] = useState("");
  const [saving, setSaving] = useState(false);

  useEffect(() => {
    if (open) {
      setPlatform(initialPlatform);
      setLabel("");
      setProxyId(null);
      setCookies({ text: "", valid: false });
      setError("");
    }
  }, [open, initialPlatform]);

  async function save() {
    setSaving(true);
    setError("");
    try {
      onSaved(await client.create({ platform, label: label.trim(), cookies: cookies.text, proxy_id: proxyId }));
      onOpenChange(false);
    } catch (failure) {
      setError(failureText(failure));
    } finally {
      setSaving(false);
    }
  }

  return <PenDialog open={open} onOpenChange={onOpenChange} eyebrow="Source access" title="Add account"
    description="Import browser cookies from a session you signed in to." className="sa-dialog">
    <div className="sa-dialog-body">
      <div className="sa-field">
        <label htmlFor="sa-platform">Platform</label>
        <Select value={platform} onValueChange={(next) => setPlatform(next as SourcePlatform)}>
          <SelectTrigger id="sa-platform" aria-label="Platform" className="sa-select"><SelectValue>{platformLabel(platform)}</SelectValue></SelectTrigger>
          <SelectContent>{PLATFORMS.map((entry) => <SelectItem key={entry.id} value={entry.id}>{entry.label}</SelectItem>)}</SelectContent>
        </Select>
      </div>
      <div className="sa-field">
        <label htmlFor="sa-label">Account label</label>
        <Input id="sa-label" maxLength={64} placeholder="e.g. Cedar · primary" value={label} onChange={(event) => setLabel(event.target.value)} />
      </div>
      <ProxySelect proxies={proxies} value={proxyId} onChange={setProxyId} onImportProxies={onImportProxies} />
      <div className="sa-field">
        <span className="sa-field-label">Browser cookie export</span>
        <CookieInput key={`${open}`} platform={platform} client={client} onChange={(text, valid) => setCookies({ text, valid })} />
      </div>
      {error && <p role="alert" className="sa-validation sa-validation--error">{error}</p>}
    </div>
    <Footer>
      <Button variant="ghost" onClick={() => onOpenChange(false)}>Cancel</Button>
      <Button disabled={saving || !label.trim() || !cookies.valid} onClick={save}>Import account</Button>
    </Footer>
  </PenDialog>;
}

export function ReimportDialog({ account, onOpenChange, client, onSaved }: {
  account: SourceAccount | null;
  onOpenChange: (open: boolean) => void;
  client: SourceAccountsClient;
  onSaved: (account: SourceAccount) => void;
}) {
  const [cookies, setCookies] = useState({ text: "", valid: false });
  const [error, setError] = useState("");
  const [saving, setSaving] = useState(false);
  if (!account) return null;

  async function save() {
    if (!account) return;
    setSaving(true);
    setError("");
    try {
      onSaved(await client.reimport(account.id, cookies.text));
      onOpenChange(false);
    } catch (failure) {
      setError(failureText(failure));
    } finally {
      setSaving(false);
    }
  }

  return <PenDialog open onOpenChange={onOpenChange} eyebrow="Source access" title="Re-import cookies"
    description="Replace cookies for this account after signing in again." className="sa-dialog">
    <div className="sa-dialog-body">
      <div className="sa-field"><span className="sa-field-label">Account</span>
        <p className="sa-readonly">{platformLabel(account.platform)} · {account.label}</p></div>
      <div className="sa-field">
        <span className="sa-field-label">Browser cookie export</span>
        <CookieInput platform={account.platform} client={client} onChange={(text, valid) => setCookies({ text, valid })} />
      </div>
      {cookies.valid && <p className="sa-field-hint">Validation passed. Existing session is replaced on save.</p>}
      {error && <p role="alert" className="sa-validation sa-validation--error">{error}</p>}
    </div>
    <Footer>
      <Button variant="ghost" onClick={() => onOpenChange(false)}>Cancel</Button>
      <Button disabled={saving || !cookies.valid} onClick={save}>Replace cookies</Button>
    </Footer>
  </PenDialog>;
}

export function EditAccountDialog({ account, onOpenChange, client, proxies, onSaved, onDeleted, onImportProxies }: {
  account: SourceAccount | null;
  onOpenChange: (open: boolean) => void;
  client: SourceAccountsClient;
  proxies: SourceProxy[];
  onSaved: (account: SourceAccount) => void;
  onDeleted: (accountId: string) => void;
  onImportProxies: () => void;
}) {
  const [label, setLabel] = useState(account?.label ?? "");
  const [proxyId, setProxyId] = useState<string | null>(account?.proxy_id ?? null);
  const [confirming, setConfirming] = useState(false);
  const [error, setError] = useState("");
  const [saving, setSaving] = useState(false);

  useEffect(() => {
    setLabel(account?.label ?? "");
    setProxyId(account?.proxy_id ?? null);
    setConfirming(false);
    setError("");
  }, [account]);

  if (!account) return null;
  const disabled = account.status === "disabled";

  async function run(action: () => Promise<void>) {
    setSaving(true);
    setError("");
    try {
      await action();
    } catch (failure) {
      setError(failureText(failure));
    } finally {
      setSaving(false);
    }
  }

  const save = () => run(async () => {
    if (!account) return;
    onSaved(await client.update(account.id, { label: label.trim(), proxy_id: proxyId }));
    onOpenChange(false);
  });
  const toggle = () => run(async () => {
    if (!account) return;
    onSaved(await client.update(account.id, { disabled: !disabled }));
    onOpenChange(false);
  });
  const remove = () => run(async () => {
    if (!account) return;
    await client.remove(account.id);
    onDeleted(account.id);
    onOpenChange(false);
  });

  return <PenDialog open onOpenChange={onOpenChange} eyebrow="Account settings" title="Edit account"
    description="Update the label or choose a dedicated proxy." className="sa-dialog">
    <div className="sa-dialog-body">
      <div className="sa-field"><span className="sa-field-label">Platform</span>
        <p className="sa-readonly">{platformLabel(account.platform)}</p></div>
      <div className="sa-field">
        <label htmlFor="sa-edit-label">Account label</label>
        <Input id="sa-edit-label" maxLength={64} value={label} onChange={(event) => setLabel(event.target.value)} />
      </div>
      <ProxySelect proxies={proxies} value={proxyId} onChange={setProxyId} currentProxyId={account.proxy_id}
        onImportProxies={onImportProxies} />
      <p className="sa-field-hint">A proxy can serve one account at a time.</p>
      {confirming && <p role="alert" className="sa-validation sa-validation--error">Delete {account.label}? Its cookies are removed and its proxy returns to the pool.</p>}
      {error && <p role="alert" className="sa-validation sa-validation--error">{error}</p>}
    </div>
    <Footer>
      <div className="sa-footer-secondary">
        <Button variant="ghost" disabled={saving} onClick={toggle}>{disabled ? "Enable account" : "Disable account"}</Button>
        {confirming
          ? <Button variant="destructive" disabled={saving} onClick={remove}>Delete account</Button>
          : <Button variant="ghost" disabled={saving} onClick={() => setConfirming(true)}>Delete</Button>}
      </div>
      <Button variant="ghost" onClick={() => onOpenChange(false)}>Cancel</Button>
      <Button disabled={saving || !label.trim()} onClick={save}>Save changes</Button>
    </Footer>
  </PenDialog>;
}
```

Create `dashboard/src/components/SourceAccounts.tsx`:

```tsx
import { useCallback, useEffect, useState } from "react";
import { CircleAlert, Info, KeyRound, Network, Plus } from "lucide-react";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { PageActions } from "@/components/PageActions";
import { AddAccountDialog, EditAccountDialog, ReimportDialog } from "@/components/SourceAccountDialogs";
import {
  PLATFORMS,
  errorText,
  platformLabel,
  type AccessMode,
  type PlatformAccounts,
  type SourceAccount,
  type SourceAccountsClient,
  type SourceAccountsOverview,
  type SourcePlatform,
  type SourceProxy,
} from "@/api/source-accounts";

const MODES: { id: AccessMode; hint: string }[] = [
  { id: "anonymous", hint: "never use accounts" },
  { id: "fallback", hint: "when anonymous access is blocked" },
  { id: "always", hint: "whenever a healthy account exists" },
];
const STATUS_LABEL = { healthy: "healthy", cooldown: "cooling down", expired: "expired", disabled: "disabled" };
const DAY_MS = 86_400_000;

function expiryText(value: string | null, now: number): string {
  if (!value) return "session only";
  const days = Math.ceil((Date.parse(value) - now) / DAY_MS);
  return days <= 0 ? "expired" : `in ${days} day${days === 1 ? "" : "s"}`;
}

function clock(value: string): string {
  return new Date(value).toLocaleTimeString([], { hour: "2-digit", minute: "2-digit", hour12: false });
}

function StatusCell({ account }: { account: SourceAccount }) {
  return <div className="sa-status">
    <span className={`sa-badge sa-badge--${account.status}`}>{account.status}</span>
    {account.status === "cooldown" && account.cooldown_until && <small>until {clock(account.cooldown_until)}</small>}
    {account.status === "expired" && <small>re-import needed</small>}
  </div>;
}

function AccessCard({ group, available, onSave }: {
  group: PlatformAccounts;
  available: boolean;
  onSave: (mode: AccessMode, spacing: number) => Promise<void>;
}) {
  const [spacing, setSpacing] = useState(String(group.min_spacing_seconds));
  useEffect(() => setSpacing(String(group.min_spacing_seconds)), [group.min_spacing_seconds]);
  const parsed = Number(spacing);
  const spacingValid = spacing !== "" && Number.isInteger(parsed) && parsed >= 0 && parsed <= 86_400;
  const commitSpacing = () => {
    if (spacingValid && parsed !== group.min_spacing_seconds) void onSave(group.mode, parsed);
  };
  return <section className="sa-card sa-access" aria-label={`${platformLabel(group.platform)} access`}>
    <header><h2><KeyRound aria-hidden="true" />{platformLabel(group.platform)} access</h2><span>Accounts rotate when used</span></header>
    <div className="sa-access-grid">
      <div>
        <p className="sa-field-label" id="sa-mode-label">Access mode</p>
        <div className="sa-segmented" role="radiogroup" aria-labelledby="sa-mode-label">
          {MODES.map((mode) => <button key={mode.id} type="button" role="radio" aria-checked={group.mode === mode.id}
            disabled={!available} onClick={() => mode.id !== group.mode && void onSave(mode.id, group.min_spacing_seconds)}>
            {mode.id}</button>)}
        </div>
        <p className="sa-mode-hints">{MODES.map((mode) => `${mode.id}: ${mode.hint}`).join("   ·   ")}</p>
      </div>
      <div>
        <label className="sa-field-label" htmlFor="sa-spacing">Minimum spacing</label>
        <div className="sa-spacing">
          <Input id="sa-spacing" inputMode="numeric" value={spacing} disabled={!available} aria-invalid={!spacingValid}
            onChange={(event) => setSpacing(event.target.value.trim())} onBlur={commitSpacing}
            onKeyDown={(event) => event.key === "Enter" && commitSpacing()} />
          <span>seconds</span>
        </div>
      </div>
    </div>
  </section>;
}

export function SourceAccounts({ client, onManageProxies }: {
  client: SourceAccountsClient;
  onManageProxies: () => void;
}) {
  const [overview, setOverview] = useState<SourceAccountsOverview | null>(null);
  const [proxies, setProxies] = useState<SourceProxy[]>([]);
  const [platform, setPlatform] = useState<SourcePlatform>("tiktok");
  const [adding, setAdding] = useState(false);
  const [reimporting, setReimporting] = useState<SourceAccount | null>(null);
  const [editing, setEditing] = useState<SourceAccount | null>(null);
  const [testing, setTesting] = useState<string | null>(null);
  const [notice, setNotice] = useState<{ tone: "ok" | "error"; text: string } | null>(null);
  const [loadError, setLoadError] = useState("");

  const load = useCallback(async () => {
    try {
      const next = await client.overview();
      setOverview(next);
      setProxies(next.available ? await client.proxies().catch(() => []) : []);
      setLoadError("");
    } catch (failure) {
      setLoadError(errorText(failure));
    }
  }, [client]);

  useEffect(() => { void load(); }, [load]);

  const available = overview?.available ?? false;
  const group = overview?.platforms.find((entry) => entry.platform === platform);
  const now = Date.now();

  async function savePolicy(mode: AccessMode, spacing: number) {
    try {
      await client.setPolicy(platform, { mode, min_spacing_seconds: spacing });
      await load();
    } catch (failure) {
      setNotice({ tone: "error", text: errorText(failure) });
    }
  }

  async function test(account: SourceAccount) {
    setTesting(account.id);
    try {
      const checked = await client.test(account.id);
      const text = { valid: "Session valid", expired: "Session expired", inconclusive: "Check inconclusive. Try again later." }[checked.result];
      setNotice({ tone: checked.result === "expired" ? "error" : "ok", text: `${account.label}: ${text}` });
      await load();
    } catch (failure) {
      setNotice({ tone: "error", text: errorText(failure) });
    } finally {
      setTesting(null);
    }
  }

  const changed = () => { void load(); };

  return <div className="sa-page">
    <PageActions>
      <Button variant="secondary" onClick={onManageProxies}><Network aria-hidden="true" />Manage proxies</Button>
      <Button disabled={!available} onClick={() => setAdding(true)}>Add account<Plus aria-hidden="true" /></Button>
    </PageActions>
    {loadError && <p role="alert" className="sa-banner sa-banner--error"><CircleAlert aria-hidden="true" />{loadError}</p>}
    {overview && !available && <p role="status" className="sa-banner"><Info aria-hidden="true" />
      Source accounts are not configured on this server. Acquisition runs anonymously, and accounts cannot be added.</p>}
    <div className="sa-tabs" role="tablist" aria-label="Platforms">
      {PLATFORMS.map((entry) => <button key={entry.id} type="button" role="tab" aria-selected={platform === entry.id}
        onClick={() => setPlatform(entry.id)}>{entry.label}</button>)}
    </div>
    {notice && <p role="status" className={`sa-toast sa-toast--${notice.tone}`}>{notice.text}
      <button type="button" aria-label="Dismiss" onClick={() => setNotice(null)}>×</button></p>}
    {group && <>
      <AccessCard group={group} available={available} onSave={savePolicy} />
      {available && group.mode !== "anonymous" && group.counts.healthy === 0 && <p role="status" className="sa-banner sa-banner--warning">
        <CircleAlert aria-hidden="true" />No healthy account. Acquisition on {platformLabel(platform)} runs anonymously.</p>}
      <section className="sa-card sa-counts" aria-label="Account status counts">
        {(Object.keys(STATUS_LABEL) as (keyof typeof STATUS_LABEL)[]).map((status) => <div key={status}>
          <i className={`sa-dot sa-dot--${status}`} aria-hidden="true" />
          <strong>{String(group.counts[status]).padStart(2, "0")}</strong><span>{STATUS_LABEL[status]}</span></div>)}
      </section>
      <section className="sa-card sa-table" aria-label="Accounts in rotation">
        <header><h2>Accounts in rotation</h2><span>{String(group.accounts.length).padStart(2, "0")} accounts</span></header>
        {group.accounts.length ? <table>
          <thead><tr>{["Label", "Status", "Proxy", "Cookies", "Earliest expiry", "Actions"].map((name) => <th key={name}>{name}</th>)}</tr></thead>
          <tbody>{group.accounts.map((account) => <tr key={account.id}>
            <td className="sa-label">{account.label}</td>
            <td><StatusCell account={account} /></td>
            <td>{account.proxy_display ?? "Direct"}</td>
            <td><div className="sa-chips">{account.cookie_names.map((name) => <span key={name}>{name}</span>)}</div></td>
            <td>{expiryText(account.cookies_earliest_expiry, now)}</td>
            <td><div className="sa-row-actions">
              <button type="button" disabled={testing !== null} onClick={() => test(account)}>{testing === account.id ? "Testing…" : "Test"}</button>
              <button type="button" onClick={() => setReimporting(account)}>Re-import</button>
              <button type="button" onClick={() => setEditing(account)}>Edit</button>
            </div></td>
          </tr>)}</tbody>
        </table> : <div className="sa-empty">
          <strong>No {platformLabel(platform)} accounts yet</strong>
          <p>Sign in with a normal browser, export its cookies with an extension such as Cookie-Editor, then import the file here.</p>
          <Button disabled={!available} onClick={() => setAdding(true)}>Add account<Plus aria-hidden="true" /></Button>
        </div>}
        <p className="sa-footnote"><Info aria-hidden="true" />Test session sends one live request to the platform.</p>
      </section>
    </>}
    <AddAccountDialog open={adding} onOpenChange={setAdding} client={client} platform={platform} proxies={proxies}
      onSaved={changed} onImportProxies={() => { setAdding(false); onManageProxies(); }} />
    <ReimportDialog account={reimporting} onOpenChange={(open) => !open && setReimporting(null)} client={client} onSaved={changed} />
    <EditAccountDialog account={editing} onOpenChange={(open) => !open && setEditing(null)} client={client} proxies={proxies}
      onSaved={changed} onDeleted={changed} onImportProxies={() => { setEditing(null); onManageProxies(); }} />
  </div>;
}
```

Create `dashboard/src/components/SourceProxies.tsx`:

```tsx
import { useCallback, useEffect, useState } from "react";
import { ArrowLeft, CircleAlert, CircleCheck, Info, LockKeyhole, Plus, Upload } from "lucide-react";
import { Button } from "@/components/ui/button";
import { Textarea } from "@/components/ui/textarea";
import { PageActions } from "@/components/PageActions";
import { PenDialog } from "@/components/PenDialog";
import { errorText, platformLabel, type ProxyImportSummary, type SourceAccountsClient, type SourceProxy } from "@/api/source-accounts";

function summaryText(summary: ProxyImportSummary): string {
  const parts = [`${summary.added} added`];
  if (summary.duplicates) parts.push(`${summary.duplicates} duplicate${summary.duplicates === 1 ? "" : "s"} skipped`);
  if (summary.invalid_lines.length) {
    const count = summary.invalid_lines.length;
    parts.push(`${count} invalid line${count === 1 ? "" : "s"} (line${count === 1 ? "" : "s"} ${summary.invalid_lines.join(", ")})`);
  }
  return parts.join(", ");
}

function ImportProxiesDialog({ open, onOpenChange, client, onImported }: {
  open: boolean;
  onOpenChange: (open: boolean) => void;
  client: SourceAccountsClient;
  onImported: () => void;
}) {
  const [text, setText] = useState("");
  const [summary, setSummary] = useState<ProxyImportSummary | null>(null);
  const [error, setError] = useState("");
  const [saving, setSaving] = useState(false);
  const reset = () => { setText(""); setSummary(null); setError(""); };
  useEffect(() => { if (open) reset(); }, [open]);
  const lines = text.split(/\r?\n/).filter((line) => line.trim() && !line.trim().startsWith("#")).length;

  async function submit() {
    setSaving(true);
    setError("");
    try {
      setSummary(await client.importProxies(text));
      setText("");
      onImported();
    } catch (failure) {
      setError(errorText(failure));
    } finally {
      setSaving(false);
    }
  }

  return <PenDialog open={open} onOpenChange={onOpenChange} eyebrow="Proxy pool" title="Import proxies"
    description="Paste one proxy per line or upload a .txt file." className="sa-dialog">
    <div className="sa-dialog-body">
      <div className="sa-field">
        <label htmlFor="sa-proxy-lines">Proxy lines</label>
        <Textarea id="sa-proxy-lines" className="sa-secret-text" placeholder="http://user:pass@host:port"
          value={text} onChange={(event) => setText(event.target.value)} />
        <p className="sa-field-hint">{lines ? `${lines} lines ready` : "One per line"} · http, https, or socks5 · credentials optional</p>
      </div>
      {summary && <p role="status" className="sa-validation sa-validation--ok"><CircleCheck aria-hidden="true" />{summaryText(summary)}</p>}
      {error && <p role="alert" className="sa-validation sa-validation--error">{error}</p>}
      <label className="sa-upload-row"><Upload aria-hidden="true" />Upload .txt instead
        <input type="file" accept=".txt,text/plain" aria-label="Proxy list file"
          onChange={async (event) => { const file = event.target.files?.[0]; if (file) setText(await file.text()); }} />
      </label>
      <p className="sa-lock-note"><LockKeyhole aria-hidden="true" />Credentials are never shown after import.</p>
    </div>
    <footer className="sa-dialog-footer">
      {summary ? <>
        <Button variant="ghost" onClick={reset}>Import another file</Button>
        <Button onClick={() => onOpenChange(false)}>Done</Button>
      </> : <>
        <Button variant="ghost" onClick={() => onOpenChange(false)}>Cancel</Button>
        <Button disabled={saving || !lines} onClick={submit}>Import proxies</Button>
      </>}
    </footer>
  </PenDialog>;
}

export function SourceProxies({ client, onBack }: { client: SourceAccountsClient; onBack: () => void }) {
  const [proxies, setProxies] = useState<SourceProxy[] | null>(null);
  const [importing, setImporting] = useState(false);
  const [error, setError] = useState("");

  const load = useCallback(async () => {
    try {
      setProxies(await client.proxies());
      setError("");
    } catch (failure) {
      setProxies([]);
      setError(errorText(failure));
    }
  }, [client]);
  useEffect(() => { void load(); }, [load]);

  async function remove(proxy: SourceProxy) {
    try {
      await client.removeProxy(proxy.id);
      await load();
    } catch (failure) {
      setError(errorText(failure));
    }
  }

  const assigned = proxies?.filter((proxy) => proxy.account_label !== null).length ?? 0;
  const total = proxies?.length ?? 0;
  const pad = (value: number) => String(value).padStart(2, "0");

  return <div className="sa-page">
    <PageActions>
      <Button variant="secondary" onClick={onBack}><ArrowLeft aria-hidden="true" />Back to accounts</Button>
      <Button onClick={() => setImporting(true)}>Import proxies<Plus aria-hidden="true" /></Button>
    </PageActions>
    <p className="sa-banner"><Info aria-hidden="true" />Each proxy can serve one account. Assign it while adding or editing an account.</p>
    {error && <p role="alert" className="sa-banner sa-banner--error"><CircleAlert aria-hidden="true" />{error}</p>}
    <section className="sa-card sa-counts" aria-label="Proxy counts">
      {([["total", total], ["assigned", assigned], ["unassigned", total - assigned]] as const).map(([name, value]) =>
        <div key={name}><strong>{pad(value)}</strong><span>{name}</span></div>)}
    </section>
    <section className="sa-card sa-table" aria-label="Proxy pool">
      <header><h2>Proxy pool</h2><span>{pad(total)} proxies</span></header>
      {total ? <table>
        <thead><tr>{["Proxy", "Scheme", "Assigned to", "Actions"].map((name) => <th key={name}>{name}</th>)}</tr></thead>
        <tbody>{proxies!.map((proxy) => {
          const held = proxy.account_label !== null;
          return <tr key={proxy.id}>
            <td className="sa-label">{proxy.display}</td>
            <td><span className="sa-chip">{proxy.scheme}</span></td>
            <td>{held ? `${platformLabel(proxy.account_platform ?? "")} · ${proxy.account_label}` : "Unassigned"}</td>
            <td><div className="sa-row-actions"><button type="button" disabled={held}
              title={held ? "Assigned to an account" : undefined} aria-label={`Delete ${proxy.display}`}
              onClick={() => remove(proxy)}>Delete</button></div></td>
          </tr>;
        })}</tbody>
      </table> : proxies && <div className="sa-empty">
        <strong>No proxies yet</strong>
        <p>Import a list of dedicated proxies, one per line. Each account can then use its own.</p>
        <Button onClick={() => setImporting(true)}>Import proxies<Plus aria-hidden="true" /></Button>
      </div>}
      <p className="sa-footnote">Only host and port are displayed. Credentials are stored privately.</p>
    </section>
    <ImportProxiesDialog open={importing} onOpenChange={setImporting} client={client} onImported={() => void load()} />
  </div>;
}
```

Create `dashboard/src/pen-source-accounts.css`:

```css
/* Source Accounts and Proxies, measured from the "Source Accounts" frames in thoth-dashboard.pen. */

.sa-page { display: flex; flex-direction: column; gap: 18px; color: #f5f3ee; font-family: Inter, system-ui, sans-serif; }
.sa-card { background: #242628; border-radius: 8px; }
.sa-field-label, .sa-field > label, .sa-table th, .sa-table header > span {
  font: 600 10px/1.2 Inter, sans-serif; letter-spacing: 1.6px; text-transform: uppercase; color: #c5c6c7;
}

.sa-tabs { display: flex; gap: 6px; }
.sa-tabs button { height: 37px; padding: 0 18px; border-radius: 6px; font-size: 13px; color: #c5c6c7; }
.sa-tabs button[aria-selected="true"] { background: #2a2c2e; color: #f5f3ee; font-weight: 600; }

.sa-access { padding: 18px; }
.sa-access header { display: flex; justify-content: space-between; align-items: center; margin-bottom: 12px; }
.sa-access h2 { display: flex; align-items: center; gap: 8px; font-size: 16px; font-weight: 600; margin: 0; }
.sa-access h2 svg { width: 17px; height: 17px; color: #d49a79; }
.sa-access header > span { font-size: 11px; color: #c5c6c7; }
.sa-access-grid { display: grid; grid-template-columns: 1fr 220px; gap: 24px; align-items: start; }
.sa-access-grid .sa-field-label { margin: 0 0 6px; display: block; }

.sa-segmented { display: inline-flex; gap: 2px; padding: 4px; background: #101113; border-radius: 6px; }
.sa-segmented button { height: 28px; padding: 0 12px; border-radius: 4px; font-size: 11px; color: #c5c6c7; }
.sa-segmented button[aria-checked="true"], .sa-segmented button[aria-pressed="true"] { background: #2a2c2e; color: #f5f3ee; font-weight: 600; }
.sa-segmented button:disabled { opacity: 0.5; }
.sa-mode-hints { margin: 10px 0 0; font-size: 10px; color: #c5c6c7; white-space: pre; }

.sa-spacing { display: flex; align-items: center; height: 35px; padding: 0 12px; background: #101113; border: 1px solid #47494a; border-radius: 6px; }
.sa-spacing input { border: 0; background: transparent; padding: 0; height: 100%; font-size: 12px; color: #f5f3ee; }
.sa-spacing input[aria-invalid="true"] { color: #e8918f; }
.sa-spacing span { font-size: 11px; color: #c5c6c7; }

.sa-counts { display: flex; gap: 28px; align-items: center; padding: 20px 18px; }
.sa-counts div { display: flex; align-items: baseline; gap: 8px; }
.sa-counts strong { font-size: 19px; font-weight: 600; }
.sa-counts span { font-size: 11px; color: #c5c6c7; }
.sa-dot { width: 6px; height: 6px; border-radius: 50%; align-self: center; }
.sa-dot--healthy { background: #78c69b; }
.sa-dot--cooldown { background: #d7af5f; }
.sa-dot--expired { background: #e8918f; }
.sa-dot--disabled { background: #c5c6c7; }

.sa-table { overflow: hidden; }
.sa-table header { display: flex; justify-content: space-between; align-items: center; padding: 14px 18px; border-bottom: 1px solid #47494a; }
.sa-table h2 { margin: 0; font-size: 15px; font-weight: 600; }
.sa-table table { width: 100%; border-collapse: collapse; table-layout: fixed; }
.sa-table th { height: 34px; padding: 0 18px; text-align: left; background: #2a2c2e; }
.sa-table td { height: 58px; padding: 0 18px; font-size: 11px; color: #c5c6c7; }
.sa-table tbody tr:nth-child(even) { background: #2a2c2e; }
.sa-table td.sa-label { font-size: 12px; font-weight: 600; color: #f5f3ee; }
.sa-status { display: flex; flex-direction: column; align-items: flex-start; gap: 3px; }
.sa-status small { font-size: 9px; color: #c5c6c7; }
.sa-badge, .sa-chip, .sa-chips span { display: inline-flex; align-items: center; height: 21px; padding: 0 8px; border-radius: 4px; font-size: 10px; }
.sa-badge--healthy { background: #244135; color: #78c69b; }
.sa-badge--cooldown { background: #493b27; color: #d7af5f; }
.sa-badge--expired { background: #4a3030; color: #e8918f; }
.sa-badge--disabled, .sa-chip, .sa-chips span { background: #2a2c2e; color: #c5c6c7; border: 1px solid #47494a; }
.sa-chips { display: flex; flex-wrap: wrap; gap: 6px; }
.sa-row-actions { display: flex; gap: 5px; }
.sa-row-actions button { height: 26px; padding: 0 8px; border-radius: 4px; background: #2a2c2e; font-size: 10px; color: #f5f3ee; }
.sa-table tbody tr:nth-child(even) .sa-row-actions button { background: #242628; }
.sa-row-actions button:disabled { opacity: 0.4; cursor: not-allowed; }
.sa-footnote { display: flex; align-items: center; gap: 8px; margin: 0; padding: 14px 18px; font-size: 10px; color: #c5c6c7; }
.sa-footnote svg { width: 13px; height: 13px; }
.sa-empty { display: flex; flex-direction: column; align-items: flex-start; gap: 10px; padding: 28px 18px; }
.sa-empty strong { font-size: 14px; }
.sa-empty p { margin: 0; max-width: 520px; font-size: 12px; color: #c5c6c7; }

.sa-banner { display: flex; align-items: center; gap: 10px; margin: 0; padding: 16px; border-radius: 8px; background: #242628; font-size: 11px; color: #f5f3ee; }
.sa-banner svg { width: 15px; height: 15px; color: #5fb6c9; flex: none; }
.sa-banner--warning svg { color: #d7af5f; }
.sa-banner--error svg { color: #e8918f; }
.sa-toast { position: fixed; right: 28px; bottom: 28px; z-index: 50; display: flex; align-items: center; gap: 12px; margin: 0;
  padding: 12px 16px; border-radius: 8px; background: #244135; color: #f5f3ee; font-size: 12px; }
.sa-toast--error { background: #4a3030; }
.sa-toast button { color: #c5c6c7; font-size: 14px; }

.sa-dialog { width: min(670px, calc(100vw - 32px)); }
.sa-dialog-body { display: flex; flex-direction: column; gap: 16px; padding: 22px 30px; border-top: 1px solid #47494a; border-bottom: 1px solid #47494a; }
.sa-field { display: flex; flex-direction: column; gap: 8px; }
.sa-select, .sa-readonly, .sa-field input:not([type="file"]) { height: 41px; border-radius: 6px; background: #101113; border: 1px solid #47494a; font-size: 13px; }
.sa-readonly { display: flex; align-items: center; margin: 0; padding: 0 13px; background: #2a2c2e; }
.sa-option { display: flex; flex-direction: column; }
.sa-option small { font-size: 9px; color: #c5c6c7; }
.sa-field-hint { margin: 0; font-size: 10px; color: #c5c6c7; }
.sa-link { color: #d49a79; text-decoration: underline; }
.sa-dropzone { position: relative; display: flex; flex-direction: column; align-items: center; gap: 4px; padding: 14px;
  border: 1px solid #47494a; border-radius: 6px; background: #101113; cursor: pointer; }
.sa-dropzone svg { width: 15px; height: 15px; color: #d49a79; }
.sa-dropzone strong { font-size: 12px; }
.sa-dropzone small { font-size: 10px; color: #c5c6c7; }
.sa-dropzone input, .sa-upload-row input { position: absolute; inset: 0; opacity: 0; cursor: pointer; }
.sa-cookie-input { display: flex; flex-direction: column; gap: 10px; }
.sa-secret-text { min-height: 150px; background: #101113; border-color: #47494a; font: 12px/1.5 ui-monospace, monospace; -webkit-text-security: disc; }
.sa-validation { display: flex; align-items: center; gap: 8px; margin: 0; padding: 12px 14px; border-radius: 6px; font-size: 11px; font-weight: 600; }
.sa-validation svg { width: 15px; height: 15px; }
.sa-validation--ok { background: #244135; }
.sa-validation--error { background: #4a3030; }
.sa-lock-note, .sa-upload-row { position: relative; display: flex; align-items: center; gap: 10px; margin: 0; padding: 12px 14px;
  border-radius: 6px; background: #2a2c2e; font-size: 10px; }
.sa-upload-row { font-size: 12px; font-weight: 600; cursor: pointer; }
.sa-lock-note svg, .sa-upload-row svg { width: 14px; height: 14px; color: #5fb6c9; }
.sa-dialog-footer { display: flex; align-items: center; justify-content: flex-end; gap: 12px; padding: 18px 30px; }
.sa-footer-secondary { display: flex; gap: 8px; margin-right: auto; }

@media (max-width: 720px) {
  .sa-tabs { overflow-x: auto; }
  .sa-access-grid { grid-template-columns: 1fr; }
  .sa-mode-hints { white-space: normal; }
  .sa-counts { flex-wrap: wrap; gap: 16px; }
  .sa-table thead { display: none; }
  .sa-table table, .sa-table tbody, .sa-table tr, .sa-table td { display: block; width: 100%; }
  .sa-table tr { padding: 14px 18px; border-bottom: 1px solid #47494a; }
  .sa-table td { height: auto; padding: 4px 0; }
  .sa-dialog-body, .sa-dialog-footer { padding-left: 18px; padding-right: 18px; }
  .sa-dialog-footer { flex-wrap: wrap; }
}
```

Wire the views and the stylesheet (CRLF preserved):

```bash
python - <<'PY'
from pathlib import Path

ROOT = Path("C:/Users/mfr/Documents/MyTools/CLIPPER/dashboard/src")


def edit(rel, pairs):
    path = ROOT / rel
    data = path.read_bytes().decode("utf-8")
    crlf = "\r\n" in data
    text = data.replace("\r\n", "\n")
    for old, new in pairs:
        assert text.count(old) == 1, (rel, old[:70])
        text = text.replace(old, new)
    path.write_bytes((text.replace("\n", "\r\n") if crlf else text).encode("utf-8"))


edit("App.tsx", [
    ('import { WorkflowWizard } from "@/components/WorkflowWizard";\n',
     'import { WorkflowWizard } from "@/components/WorkflowWizard";\n'
     'import { SourceAccounts } from "@/components/SourceAccounts";\n'
     'import { SourceProxies } from "@/components/SourceProxies";\n'
     'import { sourceAccountsClient } from "@/api/source-accounts";\n'),
    ('import { ArrowRight, CircleHelp, Clapperboard, Compass, Feather, Layers, Plus, Terminal, UserRound, Workflow } from "lucide-react";',
     'import { ArrowRight, CircleHelp, Clapperboard, Compass, Feather, KeyRound, Layers, Plus, Terminal, UserRound, Workflow } from "lucide-react";'),
    ('  studio: { label: "Creator Studio", eyebrow: "Create / 06", description: "Shape your story, one scene at a time.", icon: Clapperboard },\n};',
     '  studio: { label: "Creator Studio", eyebrow: "Create / 06", description: "Shape your story, one scene at a time.", icon: Clapperboard },\n'
     '  accounts: { label: "Source Accounts", eyebrow: "Access / 07", description: "Logged-in sessions that acquisition rotates through, per platform.", icon: KeyRound },\n'
     '  proxies: { label: "Proxies", eyebrow: "Access / 07", description: "Dedicated proxies for source accounts. Each proxy serves one account.", icon: KeyRound },\n};'),
    ('useState<"workflows" | "runs" | "profiles" | "discovery" | "contentset" | "studio">("workflows");',
     'useState<keyof typeof pages>("workflows");'),
    ('            ["runs", "Legacy console"], ["studio", "Creator Studio"],\n',
     '            ["runs", "Legacy console"], ["studio", "Creator Studio"], ["accounts", "Source Accounts"],\n'),
    ('<Button className="dashboard-nav-item" variant="ghost" aria-current={view === id ? "page" : undefined}',
     '<Button className="dashboard-nav-item" variant="ghost" aria-current={view === id || (id === "accounts" && view === "proxies") ? "page" : undefined}'),
    ('      ) : view === "studio" && studioDocument ? (\n',
     '      ) : view === "accounts" ? (\n'
     '        <SourceAccounts client={sourceAccountsClient} onManageProxies={() => setView("proxies")} />\n'
     '      ) : view === "proxies" ? (\n'
     '        <SourceProxies client={sourceAccountsClient} onBack={() => setView("accounts")} />\n'
     '      ) : view === "studio" && studioDocument ? (\n'),
])
edit("index.css", [('@import "./pen-studio.css";\n', '@import "./pen-studio.css";\n@import "./pen-source-accounts.css";\n')])
PY
```

- [ ] **Step 5: Run the dashboard checks**

```bash
cd dashboard && bun test src/components/SourceAccounts.test.tsx src/components/SourceProxies.test.tsx && bunx tsc -b && bunx oxlint src && bun test && bun run build
```

Expected:
- the 12 new tests PASS, and then the whole dashboard suite passes;
- `tsc` prints nothing;
- oxlint reports no warning naming a file this task adds;
- the build succeeds. Its chunk-size warning was there before this task.

- [ ] **Step 6: Compare with the frames**

Run the stack locally if it is up, or `bun run dev` against a local API, and open "Source Accounts". Compare it with `Sl5Lg`, `ZribQ` (the add dialog, valid), `l7u15u` (the edit dialog), `UL7Rh` (the proxy pool), `jWZTg` (the import result), and `N2hC2` (the narrow layout). Use the pencil MCP `TakeScreenshot` for the frames and the built-in browser for the page.

Ledger every visible difference you keep, as a ruling with its reason. The Disable and Delete controls in the edit dialog are an expected difference (see "Where this plan departs").

- [ ] **Step 7: Commit**

```bash
git add dashboard/src/api/source-accounts.ts dashboard/src/api/generated/control-plane.ts dashboard/src/components/SourceAccounts.tsx dashboard/src/components/SourceAccountDialogs.tsx dashboard/src/components/SourceProxies.tsx dashboard/src/components/SourceAccounts.test.tsx dashboard/src/components/SourceProxies.test.tsx dashboard/src/pen-source-accounts.css dashboard/src/App.tsx dashboard/src/index.css
git status --short
git commit -m "feat(dashboard): add the source accounts and proxies pages"
```

---

### Task 10: Live session-check probe (HARD STOP)

**Files:**
- Modify (only if the probe requires it): `python/src/thoth_control_plane/acquisition/accounts/session_check.py` (`CHECKS`), `python/tests/acquisition/accounts/test_session_check.py`

**Interfaces:**
- Consumes: Task 8's `check_session`, `judge`, `CHECKS`; Task 2's `parse_cookies`; Task 4's `SessionAccess`.
- Produces: `CHECKS` confirmed live for every platform the operator holds an account on. Each confirmation is a ledger line.

- [ ] **Step 1: HARD STOP: ask for the probe and the cookie exports**

Ask the operator, in Indonesian, to authorize a live, read-only probe. It sends one request per platform with the operator's own account and one without cookies. The operator places one cookie export per platform they hold an account on at `D:/thoth-tmp/bu/accounts/<platform>.txt` (`tiktok`, `threads`, `instagram`, `x`, `youtube`) and, optionally, one proxy URL at `D:/thoth-tmp/bu/accounts/proxy.txt`.

Never open, print, or inspect those files. Wait for the explicit authorization. Never record it as an approval in any repository document.

- [ ] **Step 2: Write the probe (not committed)**

Write `D:/thoth-tmp/bu/accounts/probe.py` with the Write tool:

```python
import asyncio
import json
from datetime import UTC, datetime
from pathlib import Path
from urllib.parse import urlsplit

from thoth_control_plane.acquisition.accounts.access import SessionAccess
from thoth_control_plane.acquisition.accounts.cookies import CookieImportError, parse_cookies
from thoth_control_plane.acquisition.accounts.session_check import (
    CHECK_OPTIONS,
    CHECKS,
    _scrapling_get,
    check_session,
    judge,
)

ROOT = Path("/work")


async def anonymous(platform: str) -> dict:
    check = CHECKS[platform]
    try:
        response = await _scrapling_get(check.url, **CHECK_OPTIONS)
    except Exception as error:
        return {"verdict": "inconclusive", "error": type(error).__name__}
    return {
        "verdict": judge(check, response),
        "status": getattr(response, "status", None),
        "final_path_changed": urlsplit(str(response.url)).path != urlsplit(check.url).path,
    }


async def main() -> None:
    proxy_file = ROOT / "proxy.txt"
    proxy = proxy_file.read_text(encoding="utf-8").strip() if proxy_file.exists() else None
    for platform in CHECKS:
        path = ROOT / f"{platform}.txt"
        if not path.exists():
            continue
        try:
            cookies = parse_cookies(platform, path.read_text(encoding="utf-8"), now=datetime.now(UTC))
        except CookieImportError as error:
            print(json.dumps({"platform": platform, "import_error": error.code, "missing": list(error.missing)}))
            continue
        signed_in = await check_session(platform, SessionAccess(cookies, proxy))
        print(json.dumps({
            "platform": platform,
            "cookie_names": cookies.names(),
            "signed_in": signed_in,
            "anonymous": await anonymous(platform),
        }))
        await asyncio.sleep(5)


asyncio.run(main())
```

- [ ] **Step 3: Run the probe in the capture image**

```bash
wsl -e bash -lc 'docker run --rm -v /mnt/c/Users/mfr/Documents/MyTools/CLIPPER/python/src:/src:ro -v /mnt/d/thoth-tmp/bu/accounts:/work -e PYTHONPATH=/src ghcr.io/muhfalihr/thoth@sha256:56fa84e6f99fe1d59c94ed0389236866c0b82fd0d5a0119e1d996bd5c9e5adf9 python /work/probe.py 2>/dev/null' | sed -E 's#https?://[^ "]+#<url>#g'
```

The capture image predates this feature, but it carries Scrapling. The probe imports only the mounted source, and `cryptography` is not needed by these modules.

Expected, per platform with an export: `"signed_in": "valid"` and `"anonymous": {"verdict": "expired"}`.

- [ ] **Step 4: Rule on each platform**

For each platform:
- **Confirmed:** the signed-in check is `valid` and the anonymous one `expired`. Ledger `Task 10: Ruling: <platform> session check confirmed live`.
- **Anything else:** the check cannot tell the two apart.
  1. Find a page or endpoint that does. Use only the verdict, the status, and `final_path_changed`; never print a body.
  2. Change that platform's `SessionCheck` in `CHECKS`.
  3. Change its two `judge` cases in `test_session_check.py` to the new shape, and watch the old test fail first.
  4. Rerun Steps 3 and 4.
- **No account for the platform:** ledger `Task 10: Ruling: <platform> session check unconfirmed (no account)`. It stays a live-smoke item.

- [ ] **Step 5: Commit (only if `CHECKS` changed)**

```bash
MSYS_NO_PATHCONV=1 timeout 590 wsl -e bash /mnt/d/thoth-tmp/bu/pt.sh tests/acquisition/accounts -p no:warnings
git add python/src/thoth_control_plane/acquisition/accounts/session_check.py python/tests/acquisition/accounts/test_session_check.py
git commit -m "fix(accounts): pin the session checks the live probe confirmed"
```

---

### Task 11: Verification and documentation

**Files:**
- Modify: `docs/superpowers/specs/2026-10-07-source-accounts-design.md` (status line)
- Modify: `CHANGELOG.md` (CRLF, newest first)
- Modify: `docs/python-scout-migration-roadmap.md` (CRLF, append)
- Modify: `.superpowers/sdd/2026-09-23-python-scout-migration-program/progress.md` (CRLF, append; gitignored)

**Interfaces:**
- Consumes: every earlier task's commits and the Task 10 rulings.
- Produces: the verification record and the next operator gates.

- [ ] **Step 1: Run every suite**

```bash
MSYS_NO_PATHCONV=1 timeout 590 wsl -e bash /mnt/d/thoth-tmp/bu/pgtest.sh tests -rA -p no:warnings > D:/thoth-tmp/source-accounts-suite.txt 2>&1; echo EXIT=$?
for s in PASSED FAILED SKIPPED ERROR; do echo "$s $(grep -c "^$s" D:/thoth-tmp/source-accounts-suite.txt)"; done
cd dashboard && bun test 2>&1 | tail -n 4 && bunx tsc -b && bun run build 2>&1 | tail -n 1
```

Expected: 0 failed and 0 errors; the Postgres tests ran. A transient Temporal test-server start error is re-run alone before it is believed.

- [ ] **Step 2: Run Ruff and refresh the graph**

Run the Ruff command from Global Constraints (expected: clean). Then run `graphify update .` from the repository root; never stage `graphify-out/`.

- [ ] **Step 3: Update the spec status line**

Replace the spec's `Status:` lines with:

```markdown
Status: written spec approved by the operator on 2026-10-07; implemented on branch
`feat/source-accounts` (see `docs/superpowers/plans/2026-10-08-source-accounts.md`).
```

- [ ] **Step 4: Write the CHANGELOG section and the status notes**

Write the section to `D:/thoth-tmp/bu/sa/changelog-section.md` (LF):
- The heading is `## <today> - Source accounts: rotating logged-in sessions with a proxy pool`.
- What shipped, each item with its commit hash from `git log --oneline master..HEAD`:
  - the vault, the cookie and proxy import, the tables;
  - the store and the runner;
  - `login_wall`;
  - the API and the session check;
  - the dashboard pages.
- Verification: the suite counts, Ruff, and the dashboard checks.
- The Task 10 rulings, as platform names and verdict enums only.
- The deliberate departures listed at the top of this plan.
- `Next steps`, as AGENTS.md requires:
  - The operator reviews the branch. Push, merge, and deploy each need their own authorization.
  - The deploy needs these steps:
    - set `THOTH_ACCOUNT_VAULT_KEY` in the API and worker environment;
    - run `thoth-control editor migrate` (revision 0008);
    - import accounts and proxies in the dashboard;
    - choose each platform's mode.
  - The live smoke with real accounts joins the final acceptance (ADR 0001).
  - Follow-ups from spec section 10:
    - interactive login through a worker-run browser;
    - the login-only platform capabilities;
    - vault key rotation.

Insert it into `CHANGELOG.md` before the first `## ` heading, keeping CRLF:

```bash
python - <<'PY'
from pathlib import Path

path = Path("C:/Users/mfr/Documents/MyTools/CLIPPER/CHANGELOG.md")
data = path.read_bytes()
assert data.endswith(b"\r\n")
text = data.decode("utf-8").replace("\r\n", "\n")
section = Path("D:/thoth-tmp/bu/sa/changelog-section.md").read_text(encoding="utf-8")
at = text.index("\n## ") + 1
text = text[:at] + section.rstrip("\n") + "\n\n" + text[at:]
path.write_bytes(text.replace("\n", "\r\n").encode("utf-8"))
PY
```

Append a short "Source accounts status" entry to `docs/python-scout-migration-roadmap.md` and to the checkpoint `progress.md`. It covers what shipped, a pointer to the CHANGELOG section, and the same next steps. Use the same script shape, replacing the insertion with `text = text.rstrip("\n") + "\n\n" + entry.rstrip("\n") + "\n"`.

- [ ] **Step 5: Commit and stop**

```bash
git add -f docs/superpowers/specs/2026-10-07-source-accounts-design.md
git add CHANGELOG.md docs/python-scout-migration-roadmap.md
git status --short
git commit -m "docs: record the source accounts feature"
```

Before committing, check that `git status --short` shows nothing from the never-stage list. Then stop and report to the operator in Indonesian. The report covers:
- the commits;
- the suites;
- the Task 10 rulings;
- the departures from the design frames;
- a **Next steps** section.
