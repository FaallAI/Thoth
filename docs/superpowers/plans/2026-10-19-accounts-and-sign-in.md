# Accounts, Sign-in and Developer Access Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** The stack serves the dashboard from a `web` container. People sign in with Google (one
email domain) or GitHub (one organization), then enter a code sent by email. Developers use scoped,
expiring tokens, and no API key reaches the browser.

**Architecture:**
- New tables in the editor database (migration 0013), mapped with SQLAlchemy, behind one
  synchronous `AccountStore` that callers wrap in `asyncio.to_thread`.
- A `SignInService` owns the sign-in rules: email codes, sessions, trusted browsers and tokens.
- Thin `/auth` routes drive the OAuth round trip with Authlib.
- `current_principal` resolves the session cookie, a developer token or the legacy service key.
  `current_actor` keeps returning the data actor `owner`, so the 48 existing routes are untouched.
- Caddy serves the built SPA and forwards `/api/v1` and `/auth` to the API.

**Tech Stack:** Python 3.12, FastAPI/Starlette, SQLAlchemy 2, Alembic SQL-file migrations,
Authlib (Starlette client, httpx), `itsdangerous`, `smtplib`, React 19 + React Router 7 + Bun,
Caddy 2, Docker Compose, GitHub Actions.

**Spec:** `docs/superpowers/specs/2026-10-19-accounts-and-sign-in-design.md`. Read it first; it is
the authority this plan argues from.

## Global Constraints

**Repository conventions:**
- Repository artifacts are in English. Chat with the operator is in Indonesian.
- Commits use exactly one `git commit -m "<subject>"`: no body, no trailer, no `Co-Authored-By`,
  no AI attribution.
- Never stage `.superpowers/`, `graphify-out/`, `.serena/`, the `.codegraph` database or `design/`.
  `docs/superpowers/**` needs `git add -f`.
- Working-copy files may be CRLF. A scripted edit must keep each file's line endings.
- No test may reach the network. Live OAuth, SMTP and Google/GitHub waits for the final live
  acceptance.

**Running the checks** (from WSL):
- Python tests: `wsl -e bash -lc 'cd /mnt/d/thoth-tmp/wt-accounts && make test T="<paths relative to python/>"'`
- Postgres tests: `make test-postgres`. Lint: `make lint`, and `make format` before it.
- Dashboard (from `dashboard/`): `bun test`, `bunx tsc --noEmit -p tsconfig.app.json`,
  `bun run build`.
- OpenAPI export: `PYTHONPATH=$PWD/src uv run --no-project --python 3.12 --with <deps> python scripts/export_openapi.py`
  from `python/` under WSL, then `bun run generate:control-plane-types` in `dashboard/`.

**Durations and limits** (exact values, from the spec):

| What | Value |
|---|---|
| Session | 12 h, renewed on use, at most 7 d in all |
| Trusted browser | 30 d |
| Email code | 6 digits, valid 10 min, at most 5 attempts |
| Resend | no sooner than 60 s after the last code |
| Codes per user | at most 10 in 24 h |
| Developer tokens | at most 20 active per user; 90 d by default, 365 d at most |
| `last_used_at` and `last_seen_at` | written at most once a minute |

**Names:**
- Cookies: `thoth_session` (path `/`), `thoth_device` (path `/auth`), `thoth_challenge` (path
  `/auth`), and Authlib's state cookie `thoth_oauth` (path `/auth`, 600 s).
- Developer tokens start with `thoth_pat_`.
- The bootstrap workspace ID is `ws_bootstrap`.

**Behaviour that must not change:**
- The API still answers **403 `{"detail": "Not authorized"}`** to a request without valid
  credentials. 19 existing tests pin it.
- `current_actor` still returns `Actor(actor_id="owner", actor_type="user")` for every principal;
  only `display_name` now carries the user's email.

**Failure codes:**
- Sign-in errors (`/login?error=`): `unverified_email`, `not_allowed`, `provider_error`,
  `not_configured`, `too_many_codes`, `code_not_sent`, `unavailable`. `/auth/me` answers 401 `signed_out`.
- Code errors: `wrong_code`, `expired`, `too_many_attempts`, `resend_too_soon`, `daily_limit`,
  `code_not_sent`.
- Authorization errors: `insufficient_scope`, `cross_site_request`, `user_required`,
  `token_limit`, `workspace_tokens_disabled`.

**Dependencies:** add only `authlib>=1.6,<2` and `itsdangerous>=2.2,<3` to the control-plane
package. Email uses `smtplib` from the standard library.

## Review Focus

1. **An OAuth callback opened twice, or in another tab, so that the state cookie is missing or
   already used:** the person lands on `/login?error=provider_error`, never on a 500. Task 5 pins
   it through a real Authlib round trip.
2. **Email look-alikes:**
   - `alice@sub.acme.test`, `alice@acme.test.evil.test` and `ALICE@ACME.TEST` against the domain
     `acme.test`;
   - a GitHub organization whose login only differs in case.

   Only the exact domain is accepted, and the stored email is lower-case. Task 5 pins it.
3. **The same person signs in with Google, then with GitHub, using the same email:** they become
   one user with one workspace and get no second personal workspace. Task 3 pins it.
4. **A code reused after it succeeded, or tried a sixth time:** it is rejected with `expired` or
   `too_many_attempts`, and a correct code after five misses does not sign in. Task 7 pins it.
5. **The Content-Security-Policy on the real dashboard:**
   - Studio previews (`/api/v1/.../preview`, a `<video>` from self);
   - blob downloads (`URL.createObjectURL`);
   - React inline styles.

   All of them keep working under the CSP. Task 14 checks it with an Edge headless walk of the
   built image.

---

### Task 1: Accounts schema (migration 0013) and its ORM mapping

**Files:**
- Create: `python/migrations/editor/0013_accounts.sql`
- Create: `python/migrations/editor/alembic/versions/0013_accounts.py`
- Create: `python/src/thoth_control_plane/infrastructure/account_models.py`
- Modify: `python/tests/operations/test_editor_migrations_postgres.py`, which pins 12 revisions at
  line 42.

**Interfaces:**
- Produces:
  - the tables `workspaces` (with the row `ws_bootstrap`), `users`, `user_identities`,
    `workspace_members`, `sessions`, `trusted_devices`, `email_challenges`, `access_tokens` and
    `auth_events`;
  - the ORM classes `WorkspaceRow`, `UserRow`, `UserIdentityRow`, `MemberRow`, `SessionRow`,
    `DeviceRow`, `ChallengeRow`, `TokenRow` and `AuthEventRow` on the shared `Base`.

- [ ] **Step 1: Write the failing Postgres test**

In `test_editor_migrations_postgres.py`:
- change `== 12` to `== 13` in `test_fresh_database_applies_every_revision_and_a_rerun_applies_none`;
- append:

```python
def test_accounts_tables_exist_with_the_bootstrap_workspace() -> None:
    apply_editor_migrations(DATABASE_URL, MIGRATIONS)
    assert {
        "workspaces", "users", "user_identities", "workspace_members", "sessions",
        "trusted_devices", "email_challenges", "access_tokens", "auth_events",
    } <= _tables()
    with psycopg.connect(DATABASE_URL) as connection:
        rows = connection.execute("SELECT workspace_id, name FROM workspaces").fetchall()
        assert rows == [("ws_bootstrap", "Thoth")]
        with pytest.raises(psycopg.errors.CheckViolation):
            connection.execute(
                "INSERT INTO users (user_id, email, display_name, created_at)"
                " VALUES ('usr_1', 'Mixed@Case.test', 'A', now())"
            )
```

- [ ] **Step 2: Run it to verify it fails**

Run: `make test-postgres`
Expected: FAIL. The fresh-database count is `12 != 13`, and the accounts tables are missing.

- [ ] **Step 3: Write the migration**

`python/migrations/editor/0013_accounts.sql`:

```sql
-- Accounts, sign-in and developer access (spec 2026-10-19, SaaS sub-project 1).
-- Only hashes of tokens and an HMAC of each email code are stored, never the secrets.

CREATE TABLE workspaces (
    workspace_id TEXT PRIMARY KEY CHECK (char_length(workspace_id) BETWEEN 1 AND 64),
    name TEXT NOT NULL CHECK (char_length(btrim(name)) BETWEEN 1 AND 120),
    created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);
-- The workspace the legacy service key maps to; its first member becomes its owner.
INSERT INTO workspaces (workspace_id, name) VALUES ('ws_bootstrap', 'Thoth');

CREATE TABLE users (
    user_id TEXT PRIMARY KEY CHECK (char_length(user_id) BETWEEN 1 AND 64),
    email TEXT NOT NULL UNIQUE
        CHECK (email = lower(email) AND char_length(email) BETWEEN 3 AND 320),
    display_name TEXT NOT NULL CHECK (char_length(display_name) BETWEEN 1 AND 200),
    created_at TIMESTAMPTZ NOT NULL,
    disabled_at TIMESTAMPTZ
);

CREATE TABLE user_identities (
    provider TEXT NOT NULL CHECK (provider IN ('google', 'github')),
    subject TEXT NOT NULL CHECK (char_length(subject) BETWEEN 1 AND 255),
    user_id TEXT NOT NULL REFERENCES users (user_id),
    email_at_sign_in TEXT NOT NULL,
    last_sign_in_at TIMESTAMPTZ NOT NULL,
    PRIMARY KEY (provider, subject)
);

CREATE TABLE workspace_members (
    workspace_id TEXT NOT NULL REFERENCES workspaces (workspace_id),
    user_id TEXT NOT NULL REFERENCES users (user_id),
    role TEXT NOT NULL CHECK (role IN ('owner', 'admin', 'member')),
    created_at TIMESTAMPTZ NOT NULL,
    PRIMARY KEY (workspace_id, user_id)
);

CREATE TABLE sessions (
    session_id TEXT PRIMARY KEY,
    user_id TEXT NOT NULL REFERENCES users (user_id),
    workspace_id TEXT NOT NULL REFERENCES workspaces (workspace_id),
    token_hash TEXT NOT NULL UNIQUE,
    created_at TIMESTAMPTZ NOT NULL,
    last_seen_at TIMESTAMPTZ NOT NULL,
    expires_at TIMESTAMPTZ NOT NULL,
    revoked_at TIMESTAMPTZ
);

CREATE TABLE trusted_devices (
    device_id TEXT PRIMARY KEY,
    user_id TEXT NOT NULL REFERENCES users (user_id),
    token_hash TEXT NOT NULL UNIQUE,
    created_at TIMESTAMPTZ NOT NULL,
    expires_at TIMESTAMPTZ NOT NULL,
    revoked_at TIMESTAMPTZ
);

CREATE TABLE email_challenges (
    challenge_id TEXT PRIMARY KEY,
    user_id TEXT NOT NULL REFERENCES users (user_id),
    token_hash TEXT NOT NULL UNIQUE,
    code_hmac TEXT NOT NULL,
    attempts SMALLINT NOT NULL DEFAULT 0 CHECK (attempts BETWEEN 0 AND 5),
    created_at TIMESTAMPTZ NOT NULL,
    expires_at TIMESTAMPTZ NOT NULL,
    consumed_at TIMESTAMPTZ
);
CREATE INDEX email_challenges_user ON email_challenges (user_id, created_at DESC);

CREATE TABLE access_tokens (
    token_id TEXT PRIMARY KEY,
    owner_kind TEXT NOT NULL CHECK (owner_kind IN ('user', 'workspace')),
    owner_id TEXT NOT NULL,
    workspace_id TEXT NOT NULL REFERENCES workspaces (workspace_id),
    name TEXT NOT NULL CHECK (char_length(btrim(name)) BETWEEN 1 AND 100),
    prefix TEXT NOT NULL,
    token_hash TEXT NOT NULL UNIQUE,
    scope TEXT NOT NULL CHECK (scope IN ('read', 'write', 'admin')),
    created_at TIMESTAMPTZ NOT NULL,
    expires_at TIMESTAMPTZ NOT NULL,
    last_used_at TIMESTAMPTZ,
    revoked_at TIMESTAMPTZ
);
CREATE INDEX access_tokens_owner ON access_tokens (owner_kind, owner_id, created_at DESC);

CREATE TABLE auth_events (
    event_id BIGSERIAL PRIMARY KEY,
    at TIMESTAMPTZ NOT NULL DEFAULT now(),
    kind TEXT NOT NULL CHECK (char_length(kind) BETWEEN 1 AND 64),
    outcome TEXT NOT NULL CHECK (outcome IN ('ok', 'refused', 'failed')),
    user_id TEXT,
    token_id TEXT,
    detail_code TEXT
);
```

`python/migrations/editor/alembic/versions/0013_accounts.py`:

```python
"""Apply the shipped 0013_accounts.sql verbatim."""

from thoth_control_plane.operations.editor_migrations import execute_sql_file

revision = "0013"
down_revision = "0012"


def upgrade() -> None:
    execute_sql_file(__file__)
```

`python/src/thoth_control_plane/infrastructure/account_models.py`:

```python
"""SQLAlchemy ORM mapping of the accounts tables (editor migration 0013)."""

from __future__ import annotations

from datetime import datetime

from sqlalchemy import BigInteger, ForeignKey, Integer, SmallInteger, String
from sqlalchemy.orm import Mapped, mapped_column

from thoth_control_plane.infrastructure.source_account_models import Base, UtcDateTime


class WorkspaceRow(Base):
    __tablename__ = "workspaces"

    workspace_id: Mapped[str] = mapped_column(String, primary_key=True)
    name: Mapped[str] = mapped_column(String)
    created_at: Mapped[datetime] = mapped_column(UtcDateTime)


class UserRow(Base):
    __tablename__ = "users"

    user_id: Mapped[str] = mapped_column(String, primary_key=True)
    email: Mapped[str] = mapped_column(String, unique=True)
    display_name: Mapped[str] = mapped_column(String)
    created_at: Mapped[datetime] = mapped_column(UtcDateTime)
    disabled_at: Mapped[datetime | None] = mapped_column(UtcDateTime, nullable=True)


class UserIdentityRow(Base):
    __tablename__ = "user_identities"

    provider: Mapped[str] = mapped_column(String, primary_key=True)
    subject: Mapped[str] = mapped_column(String, primary_key=True)
    user_id: Mapped[str] = mapped_column(String, ForeignKey("users.user_id"))
    email_at_sign_in: Mapped[str] = mapped_column(String)
    last_sign_in_at: Mapped[datetime] = mapped_column(UtcDateTime)


class MemberRow(Base):
    __tablename__ = "workspace_members"

    workspace_id: Mapped[str] = mapped_column(
        String, ForeignKey("workspaces.workspace_id"), primary_key=True
    )
    user_id: Mapped[str] = mapped_column(String, ForeignKey("users.user_id"), primary_key=True)
    role: Mapped[str] = mapped_column(String)
    created_at: Mapped[datetime] = mapped_column(UtcDateTime)


class SessionRow(Base):
    __tablename__ = "sessions"

    session_id: Mapped[str] = mapped_column(String, primary_key=True)
    user_id: Mapped[str] = mapped_column(String, ForeignKey("users.user_id"))
    workspace_id: Mapped[str] = mapped_column(String, ForeignKey("workspaces.workspace_id"))
    token_hash: Mapped[str] = mapped_column(String, unique=True)
    created_at: Mapped[datetime] = mapped_column(UtcDateTime)
    last_seen_at: Mapped[datetime] = mapped_column(UtcDateTime)
    expires_at: Mapped[datetime] = mapped_column(UtcDateTime)
    revoked_at: Mapped[datetime | None] = mapped_column(UtcDateTime, nullable=True)


class DeviceRow(Base):
    __tablename__ = "trusted_devices"

    device_id: Mapped[str] = mapped_column(String, primary_key=True)
    user_id: Mapped[str] = mapped_column(String, ForeignKey("users.user_id"))
    token_hash: Mapped[str] = mapped_column(String, unique=True)
    created_at: Mapped[datetime] = mapped_column(UtcDateTime)
    expires_at: Mapped[datetime] = mapped_column(UtcDateTime)
    revoked_at: Mapped[datetime | None] = mapped_column(UtcDateTime, nullable=True)


class ChallengeRow(Base):
    __tablename__ = "email_challenges"

    challenge_id: Mapped[str] = mapped_column(String, primary_key=True)
    user_id: Mapped[str] = mapped_column(String, ForeignKey("users.user_id"))
    token_hash: Mapped[str] = mapped_column(String, unique=True)
    code_hmac: Mapped[str] = mapped_column(String)
    attempts: Mapped[int] = mapped_column(SmallInteger, default=0)
    created_at: Mapped[datetime] = mapped_column(UtcDateTime)
    expires_at: Mapped[datetime] = mapped_column(UtcDateTime)
    consumed_at: Mapped[datetime | None] = mapped_column(UtcDateTime, nullable=True)


class TokenRow(Base):
    __tablename__ = "access_tokens"

    token_id: Mapped[str] = mapped_column(String, primary_key=True)
    owner_kind: Mapped[str] = mapped_column(String)
    owner_id: Mapped[str] = mapped_column(String)
    workspace_id: Mapped[str] = mapped_column(String, ForeignKey("workspaces.workspace_id"))
    name: Mapped[str] = mapped_column(String)
    prefix: Mapped[str] = mapped_column(String)
    token_hash: Mapped[str] = mapped_column(String, unique=True)
    scope: Mapped[str] = mapped_column(String)
    created_at: Mapped[datetime] = mapped_column(UtcDateTime)
    expires_at: Mapped[datetime] = mapped_column(UtcDateTime)
    last_used_at: Mapped[datetime | None] = mapped_column(UtcDateTime, nullable=True)
    revoked_at: Mapped[datetime | None] = mapped_column(UtcDateTime, nullable=True)


class AuthEventRow(Base):
    __tablename__ = "auth_events"

    # BIGSERIAL on Postgres; SQLite only autoincrements an INTEGER primary key.
    event_id: Mapped[int] = mapped_column(
        BigInteger().with_variant(Integer, "sqlite"), primary_key=True, autoincrement=True
    )
    at: Mapped[datetime] = mapped_column(UtcDateTime)
    kind: Mapped[str] = mapped_column(String)
    outcome: Mapped[str] = mapped_column(String)
    user_id: Mapped[str | None] = mapped_column(String, nullable=True)
    token_id: Mapped[str | None] = mapped_column(String, nullable=True)
    detail_code: Mapped[str | None] = mapped_column(String, nullable=True)
```

- [ ] **Step 4: Run the Postgres tests to verify they pass**

Run: `make test-postgres`
Expected: PASS, every Postgres test including the new one; previously 14.

- [ ] **Step 5: Commit**

```bash
git add python/migrations/editor/0013_accounts.sql python/migrations/editor/alembic/versions/0013_accounts.py python/src/thoth_control_plane/infrastructure/account_models.py python/tests/operations/test_editor_migrations_postgres.py
git commit -m "feat(accounts): add the accounts schema (editor migration 0013)"
```

---

### Task 2: Auth settings, secrets helpers, auth models and the new dependencies

**Files:**
- Modify: `python/pyproject.toml` (`dependencies`) and `python/uv.lock`.
- Modify: `python/src/thoth_control_plane/config.py`, adding the settings, a blank-to-None
  validator and the derived properties.
- Create: `python/src/thoth_control_plane/auth/__init__.py`, which is empty apart from its
  docstring.
- Create: `python/src/thoth_control_plane/auth/secrets.py`
- Create: `python/src/thoth_control_plane/auth/models.py`
- Test: `python/tests/auth/__init__.py` (empty), `python/tests/auth/test_secrets_and_settings.py`

**Interfaces:**
- Produces:
  - **`auth/secrets.py`:**
    - `TOKEN_PREFIX = "thoth_pat_"`;
    - `random_token(prefix: str = "") -> str`;
    - `token_hash(text: str) -> str`;
    - `new_code() -> str`;
    - `code_hmac(secret: str, challenge_id: str, code: str) -> str`;
    - `same(a: str, b: str) -> bool`.
  - **`auth/models.py`:**
    - `Scope`, `SCOPE_SETS: dict[Scope, frozenset[str]]`, `ALL_SCOPES`;
    - `BOOTSTRAP_WORKSPACE_ID = "ws_bootstrap"`;
    - the dataclasses `Principal(user_id, workspace_id, scopes, via, email=None)` and
      `VerifiedIdentity(provider, subject, email, display_name)`;
    - `class SignInRefused(Exception)` with `.code`;
    - the API models `MeView`, `TokenView`, `CreateToken` and `CreatedToken`.
  - **`Settings`:**
    - the fields `THOTH_SITE_ORIGIN`, `THOTH_AUTH_SECRET`, `THOTH_AUTH_GOOGLE_CLIENT_ID`,
      `THOTH_AUTH_GOOGLE_CLIENT_SECRET`, `THOTH_AUTH_GOOGLE_DOMAIN`, `THOTH_AUTH_GITHUB_CLIENT_ID`,
      `THOTH_AUTH_GITHUB_CLIENT_SECRET`, `THOTH_AUTH_GITHUB_ORG`, `THOTH_SMTP_HOST`,
      `THOTH_SMTP_PORT`, `THOTH_SMTP_USERNAME`, `THOTH_SMTP_PASSWORD`, `THOTH_SMTP_FROM` and
      `THOTH_AUTH_WORKSPACE_TOKENS`;
    - the properties `cookie_secure`, `email_codes_enabled`, `sign_in_ready`,
      `google_sign_in_enabled` and `github_sign_in_enabled`.

- [ ] **Step 1: Add the dependencies**

In `python/pyproject.toml` `dependencies`, add `"authlib>=1.6,<2"` and `"itsdangerous>=2.2,<3"`
after `"minio>=7.2.20,<8"`. Then, in WSL, run `cd python && uv lock`. Expected: `uv.lock` gains
`authlib` and its JOSE dependency, plus `itsdangerous`.

- [ ] **Step 2: Write the failing tests**

`python/tests/auth/test_secrets_and_settings.py`:

```python
"""Secret helpers and the sign-in settings (spec 2026-10-19, sections 3 and 5)."""

from thoth_control_plane.auth.models import SCOPE_SETS, Principal
from thoth_control_plane.auth.secrets import (
    TOKEN_PREFIX,
    code_hmac,
    new_code,
    random_token,
    same,
    token_hash,
)
from thoth_control_plane.config import Settings


def test_tokens_are_random_prefixed_and_only_their_hash_is_stable() -> None:
    first, second = random_token(TOKEN_PREFIX), random_token(TOKEN_PREFIX)
    assert first.startswith("thoth_pat_") and first != second
    assert len(first) > len(TOKEN_PREFIX) + 40
    assert token_hash(first) == token_hash(first) != token_hash(second)
    assert len(token_hash(first)) == 64


def test_codes_are_six_digits_and_their_hmac_binds_the_challenge() -> None:
    code = new_code()
    assert len(code) == 6 and code.isdigit()
    assert code_hmac("s", "chl_1", "123456") != code_hmac("s", "chl_2", "123456")
    assert code_hmac("s", "chl_1", "123456") != code_hmac("t", "chl_1", "123456")
    assert same("abc", "abc") and not same("abc", "abd")
    assert not same("é", "e")  # non-ASCII input compares as bytes instead of raising


def test_scope_levels_imply_the_lower_ones() -> None:
    assert SCOPE_SETS["read"] == {"read"}
    assert SCOPE_SETS["write"] == {"read", "write"}
    assert SCOPE_SETS["admin"] == {"read", "write", "admin"}
    principal = Principal(None, "ws_bootstrap", SCOPE_SETS["admin"], "service")
    assert principal.email is None


def test_blank_auth_settings_are_unset_and_sign_in_needs_every_part() -> None:
    blank = Settings(
        THOTH_CONTROL_PLANE_API_KEY="k",
        THOTH_AUTH_GOOGLE_CLIENT_ID="",
        THOTH_AUTH_GOOGLE_CLIENT_SECRET="",
        THOTH_SMTP_HOST="  ",
    )
    assert blank.THOTH_AUTH_GOOGLE_CLIENT_ID is None
    assert blank.THOTH_AUTH_GOOGLE_CLIENT_SECRET is None
    assert blank.THOTH_SMTP_HOST is None
    assert not blank.google_sign_in_enabled and not blank.cookie_secure
    ready = Settings(
        THOTH_CONTROL_PLANE_API_KEY="k",
        THOTH_EDITOR_DATABASE_URL="postgresql://u:p@db/x",
        THOTH_SITE_ORIGIN="https://thoth.example",
        THOTH_AUTH_SECRET="s" * 32,
        THOTH_SMTP_HOST="smtp.example",
        THOTH_SMTP_FROM="Thoth <no-reply@thoth.example>",
        THOTH_AUTH_GOOGLE_CLIENT_ID="gid",
        THOTH_AUTH_GOOGLE_CLIENT_SECRET="gsecret",
        THOTH_AUTH_GOOGLE_DOMAIN="acme.test",
    )
    assert ready.sign_in_ready and ready.google_sign_in_enabled and ready.cookie_secure
    assert not ready.github_sign_in_enabled
```

- [ ] **Step 3: Run them to verify they fail**

Run: `make test T="tests/auth/test_secrets_and_settings.py"`
Expected: FAIL with `ModuleNotFoundError: No module named 'thoth_control_plane.auth'`.

- [ ] **Step 4: Implement**

`python/src/thoth_control_plane/auth/__init__.py`:

```python
"""Accounts, sign-in and developer access (spec 2026-10-19, SaaS sub-project 1)."""
```

`python/src/thoth_control_plane/auth/secrets.py`:

```python
"""Random tokens, their hashes, and email codes. Only hashes and HMACs are ever stored."""

from __future__ import annotations

import hashlib
import hmac
import secrets

#: Lets secret scanners recognise a leaked developer token.
TOKEN_PREFIX = "thoth_pat_"


def random_token(prefix: str = "") -> str:
    return prefix + secrets.token_urlsafe(32)


def token_hash(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def new_code() -> str:
    return f"{secrets.randbelow(1_000_000):06d}"


def code_hmac(secret: str, challenge_id: str, code: str) -> str:
    message = f"{challenge_id}:{code}".encode()
    return hmac.new(secret.encode("utf-8"), message, hashlib.sha256).hexdigest()


def same(a: str, b: str) -> bool:
    """Constant-time comparison that also accepts non-ASCII text."""
    return hmac.compare_digest(a.encode("utf-8"), b.encode("utf-8"))
```

`python/src/thoth_control_plane/auth/models.py`:

```python
"""Who is calling, what a provider vouched for, and the account API models."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Annotated, Literal

from pydantic import Field

from thoth_control_plane.domain.models import StrictModel

Scope = Literal["read", "write", "admin"]
SCOPE_SETS: dict[str, frozenset[str]] = {
    "read": frozenset({"read"}),
    "write": frozenset({"read", "write"}),
    "admin": frozenset({"read", "write", "admin"}),
}
ALL_SCOPES = SCOPE_SETS["admin"]
BOOTSTRAP_WORKSPACE_ID = "ws_bootstrap"
SignInErrorCode = Literal[
    "unverified_email", "not_allowed", "provider_error", "not_configured", "too_many_codes"
]


@dataclass(frozen=True)
class Principal:
    """An authenticated caller. `user_id` is None for the legacy service key and workspace tokens."""

    user_id: str | None
    workspace_id: str
    scopes: frozenset[str]
    via: Literal["session", "token", "service"]
    email: str | None = None


@dataclass(frozen=True)
class VerifiedIdentity:
    provider: Literal["google", "github"]
    subject: str
    email: str  # lower-case and verified by the provider
    display_name: str


class SignInRefused(Exception):
    def __init__(self, code: SignInErrorCode) -> None:
        super().__init__(code)
        self.code = code


class MeView(StrictModel):
    user_id: str | None
    email: str | None
    display_name: str | None
    workspace_id: str
    scopes: list[Scope]


class TokenView(StrictModel):
    token_id: str
    owner_kind: Literal["user", "workspace"]
    name: str
    prefix: str
    scope: Scope
    created_at: datetime
    expires_at: datetime
    last_used_at: datetime | None


class CreateToken(StrictModel):
    name: Annotated[str, Field(min_length=1, max_length=100)]
    scope: Scope = "write"
    days: Annotated[int, Field(ge=1, le=365)] = 90


class CreatedToken(StrictModel):
    token: TokenView
    secret: str  # shown once; never stored
```

In `config.py`, add these fields after `THOTH_EDITOR_PREVIEW_BASE_URL`. Add `field_validator` to
the pydantic import if it is missing.

```python
    THOTH_SITE_ORIGIN: str = "http://localhost:8088"
    THOTH_AUTH_SECRET: SecretStr | None = None
    THOTH_AUTH_GOOGLE_CLIENT_ID: str | None = None
    THOTH_AUTH_GOOGLE_CLIENT_SECRET: SecretStr | None = None
    THOTH_AUTH_GOOGLE_DOMAIN: str | None = None
    THOTH_AUTH_GITHUB_CLIENT_ID: str | None = None
    THOTH_AUTH_GITHUB_CLIENT_SECRET: SecretStr | None = None
    THOTH_AUTH_GITHUB_ORG: str | None = None
    THOTH_SMTP_HOST: str | None = None
    THOTH_SMTP_PORT: Annotated[int, Field(ge=1, le=65535)] = 587
    THOTH_SMTP_USERNAME: str | None = None
    THOTH_SMTP_PASSWORD: SecretStr | None = None
    THOTH_SMTP_FROM: str | None = None
    THOTH_AUTH_WORKSPACE_TOKENS: bool = False
```

and, inside the class:

```python
    @field_validator(
        "THOTH_AUTH_SECRET",
        "THOTH_AUTH_GOOGLE_CLIENT_ID",
        "THOTH_AUTH_GOOGLE_CLIENT_SECRET",
        "THOTH_AUTH_GOOGLE_DOMAIN",
        "THOTH_AUTH_GITHUB_CLIENT_ID",
        "THOTH_AUTH_GITHUB_CLIENT_SECRET",
        "THOTH_AUTH_GITHUB_ORG",
        "THOTH_SMTP_HOST",
        "THOTH_SMTP_USERNAME",
        "THOTH_SMTP_PASSWORD",
        "THOTH_SMTP_FROM",
        mode="before",
    )
    @classmethod
    def _blank_is_unset(cls, value: object) -> object:
        """Compose passes `${VAR:-}` as an empty string; empty means not configured."""
        return None if isinstance(value, str) and not value.strip() else value

    @property
    def cookie_secure(self) -> bool:
        return self.THOTH_SITE_ORIGIN.startswith("https://")

    @property
    def email_codes_enabled(self) -> bool:
        return self.THOTH_SMTP_HOST is not None and self.THOTH_SMTP_FROM is not None

    @property
    def sign_in_ready(self) -> bool:
        """Everything a provider needs besides its own client: a secret, the DB, and mail."""
        return (
            self.THOTH_AUTH_SECRET is not None
            and self.THOTH_EDITOR_DATABASE_URL is not None
            and self.email_codes_enabled
        )

    @property
    def google_sign_in_enabled(self) -> bool:
        return self.sign_in_ready and None not in (
            self.THOTH_AUTH_GOOGLE_CLIENT_ID,
            self.THOTH_AUTH_GOOGLE_CLIENT_SECRET,
            self.THOTH_AUTH_GOOGLE_DOMAIN,
        )

    @property
    def github_sign_in_enabled(self) -> bool:
        return self.sign_in_ready and None not in (
            self.THOTH_AUTH_GITHUB_CLIENT_ID,
            self.THOTH_AUTH_GITHUB_CLIENT_SECRET,
            self.THOTH_AUTH_GITHUB_ORG,
        )
```

- [ ] **Step 5: Run the tests to verify they pass**

Run: `make test T="tests/auth/test_secrets_and_settings.py tests/test_package.py"`
Expected: PASS.

- [ ] **Step 6: Commit**

```bash
git add python/pyproject.toml python/uv.lock python/src/thoth_control_plane/config.py python/src/thoth_control_plane/auth python/tests/auth
git commit -m "feat(auth): add sign-in settings, token secrets and auth models"
```

---

### Task 3: AccountStore: users, identities and workspaces

**Files:**
- Create: `python/src/thoth_control_plane/infrastructure/account_store.py`
- Test: `python/tests/infrastructure/test_account_store_identities.py`

**Interfaces:**
- Consumes: the Task 1 ORM rows; `VerifiedIdentity` and `BOOTSTRAP_WORKSPACE_ID` (Task 2).
- Produces:
  - `class AccountStoreUnavailable(RuntimeError)`;
  - the dataclass `AccountUser(user_id: str, email: str, display_name: str, workspace_id: str,
    role: str, disabled: bool)`;
  - `class AccountStore`:
    - `__init__(engine, clock=utcnow)` and the classmethod `connect(database_url)`;
    - `upsert_identity(identity: VerifiedIdentity) -> AccountUser`;
    - `ensure_user(email: str, display_name: str) -> AccountUser`;
    - `account(user_id: str) -> AccountUser | None`.

  Task 4 adds the credential methods to the same class.

- [ ] **Step 1: Write the failing tests**

`python/tests/infrastructure/test_account_store_identities.py`:

```python
"""Users, linked identities and the bootstrap workspace (spec 2026-10-19, section 2.4)."""

from datetime import UTC, datetime

import pytest
from sqlalchemy import create_engine, text
from sqlalchemy.pool import StaticPool

from thoth_control_plane.auth.models import BOOTSTRAP_WORKSPACE_ID, VerifiedIdentity
from thoth_control_plane.infrastructure import account_models  # noqa: F401
from thoth_control_plane.infrastructure.account_models import WorkspaceRow
from thoth_control_plane.infrastructure.account_store import AccountStore
from thoth_control_plane.infrastructure.source_account_models import Base

T0 = datetime(2026, 10, 19, tzinfo=UTC)


@pytest.fixture
def store() -> AccountStore:
    engine = create_engine(
        "sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool
    )
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


def test_the_first_user_owns_the_bootstrap_workspace_and_later_users_get_their_own(store) -> None:
    first = store.upsert_identity(google("g1", "alice@acme.test"))
    assert (first.workspace_id, first.role) == (BOOTSTRAP_WORKSPACE_ID, "owner")
    second = store.upsert_identity(google("g2", "bob@acme.test"))
    assert second.workspace_id != BOOTSTRAP_WORKSPACE_ID
    assert second.workspace_id.startswith("ws_") and second.role == "owner"


def test_one_email_across_google_and_github_is_one_user_with_one_workspace(store) -> None:
    by_google = store.upsert_identity(google("g1", "alice@acme.test"))
    store.upsert_identity(google("g9", "someone@acme.test"))  # the bootstrap is taken now
    by_github = store.upsert_identity(
        VerifiedIdentity("github", "42", "alice@acme.test", "alice")
    )
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
```

- [ ] **Step 2: Run them to verify they fail**

Run: `make test T="tests/infrastructure/test_account_store_identities.py"`
Expected: FAIL with `ModuleNotFoundError: ... account_store`.

- [ ] **Step 3: Implement**

`python/src/thoth_control_plane/infrastructure/account_store.py`:

```python
"""Accounts in PostgreSQL (editor migration 0013).

Synchronous like the project store; callers wrap calls in `asyncio.to_thread`. A database error is
`AccountStoreUnavailable`, never an absent account.
"""

from __future__ import annotations

import logging
from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime
from uuid import uuid4

from sqlalchemy import create_engine, func, select
from sqlalchemy.engine import Engine, make_url
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session, sessionmaker

from thoth_control_plane.auth.models import BOOTSTRAP_WORKSPACE_ID, VerifiedIdentity
from thoth_control_plane.infrastructure.account_models import (
    MemberRow,
    UserIdentityRow,
    UserRow,
    WorkspaceRow,
)

logger = logging.getLogger(__name__)


class AccountStoreUnavailable(RuntimeError):
    """The database could not be reached or refused the statement."""


@dataclass(frozen=True)
class AccountUser:
    user_id: str
    email: str
    display_name: str
    workspace_id: str
    role: str
    disabled: bool


def _unavailable(error: Exception) -> AccountStoreUnavailable:
    logger.warning("account store failed: %s", type(error).__name__)
    return AccountStoreUnavailable("account_store_unavailable")


class AccountStore:
    def __init__(
        self, engine: Engine, clock: Callable[[], datetime] = lambda: datetime.now(UTC)
    ) -> None:
        self._engine = engine
        self._sessions = sessionmaker(engine, expire_on_commit=False)
        self._clock = clock

    @classmethod
    def connect(cls, database_url: str) -> AccountStore:
        url = make_url(database_url).set(drivername="postgresql+psycopg")
        return cls(
            create_engine(
                url,
                pool_pre_ping=True,
                pool_size=2,
                max_overflow=4,
                hide_parameters=True,
                connect_args={"connect_timeout": 10},
            )
        )

    # --- users, identities, workspaces ----------------------------------------------------

    def upsert_identity(self, identity: VerifiedIdentity) -> AccountUser:
        """The user behind a verified identity: linked by (provider, subject), else by email."""
        now = self._clock()
        try:
            with self._sessions.begin() as session:
                link = session.get(UserIdentityRow, (identity.provider, identity.subject))
                user = (
                    session.get(UserRow, link.user_id)
                    if link is not None
                    else session.scalar(select(UserRow).where(UserRow.email == identity.email))
                )
                if user is None:
                    user = self._new_user(session, identity.email, identity.display_name, now)
                if link is None:
                    session.add(
                        UserIdentityRow(
                            provider=identity.provider,
                            subject=identity.subject,
                            user_id=user.user_id,
                            email_at_sign_in=identity.email,
                            last_sign_in_at=now,
                        )
                    )
                else:
                    link.email_at_sign_in = identity.email
                    link.last_sign_in_at = now
                return self._account(session, user)
        except SQLAlchemyError as error:
            raise _unavailable(error) from None

    def ensure_user(self, email: str, display_name: str) -> AccountUser:
        """The user with this email, created when missing (the bootstrap CLI)."""
        now = self._clock()
        try:
            with self._sessions.begin() as session:
                user = session.scalar(select(UserRow).where(UserRow.email == email))
                if user is None:
                    user = self._new_user(session, email, display_name, now)
                return self._account(session, user)
        except SQLAlchemyError as error:
            raise _unavailable(error) from None

    def account(self, user_id: str) -> AccountUser | None:
        try:
            with self._sessions() as session:
                user = session.get(UserRow, user_id)
                return None if user is None else self._account(session, user)
        except SQLAlchemyError as error:
            raise _unavailable(error) from None

    def _new_user(self, session: Session, email: str, name: str, now: datetime) -> UserRow:
        user = UserRow(
            user_id=f"usr_{uuid4().hex}",
            email=email,
            display_name=(name or email)[:200],
            created_at=now,
        )
        session.add(user)
        session.flush()
        # ponytail: two first sign-ins racing may both own the bootstrap; harmless until
        # sub-project 2 scopes data by workspace.
        taken = session.scalar(
            select(func.count())
            .select_from(MemberRow)
            .where(MemberRow.workspace_id == BOOTSTRAP_WORKSPACE_ID)
        )
        workspace_id = BOOTSTRAP_WORKSPACE_ID
        if taken:
            workspace_id = f"ws_{uuid4().hex}"
            session.add(
                WorkspaceRow(
                    workspace_id=workspace_id,
                    name=f"{user.display_name}'s workspace"[:120],
                    created_at=now,
                )
            )
        session.add(
            MemberRow(workspace_id=workspace_id, user_id=user.user_id, role="owner", created_at=now)
        )
        session.flush()
        return user

    @staticmethod
    def _account(session: Session, user: UserRow) -> AccountUser:
        member = session.scalars(
            select(MemberRow)
            .where(MemberRow.user_id == user.user_id)
            .order_by(MemberRow.created_at, MemberRow.workspace_id)
        ).first()
        return AccountUser(
            user_id=user.user_id,
            email=user.email,
            display_name=user.display_name,
            workspace_id=member.workspace_id if member else BOOTSTRAP_WORKSPACE_ID,
            role=member.role if member else "member",
            disabled=user.disabled_at is not None,
        )
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `make test T="tests/infrastructure/test_account_store_identities.py"`
Expected: PASS (4 tests).

- [ ] **Step 5: Commit**

```bash
git add python/src/thoth_control_plane/infrastructure/account_store.py python/tests/infrastructure/test_account_store_identities.py
git commit -m "feat(accounts): store users, linked identities and workspaces"
```

---

### Task 4: AccountStore: sessions, trusted browsers, email codes, tokens and events

**Files:**
- Modify: `python/src/thoth_control_plane/infrastructure/account_store.py`
- Test: `python/tests/infrastructure/test_account_store_credentials.py`

**Interfaces:**
- Consumes: `AccountStore` (Task 3).
- Produces, on `AccountStore`:
  - the dataclasses `SessionRecord(session_id, user_id, workspace_id, created_at, last_seen_at,
    expires_at)`, `ChallengeRecord(challenge_id, user_id, code_hmac, attempts, created_at,
    expires_at)` and `TokenRecord(token_id, owner_kind, owner_id, workspace_id, name, prefix, scope,
    created_at, expires_at, last_used_at)`;
  - **sessions:** `create_session(user_id, workspace_id, token_hash, expires_at) -> SessionRecord`,
    `live_session(token_hash) -> SessionRecord | None`,
    `extend_session(session_id, expires_at, seen_at) -> None`, `revoke_session(token_hash) -> None`;
  - **trusted browsers:** `trust_device(user_id, token_hash, expires_at) -> None`,
    `is_trusted(user_id, token_hash) -> bool`, `forget_device(token_hash) -> None`;
  - **email codes:** `create_challenge(challenge_id, user_id, token_hash, code_hmac, expires_at) ->
    None`, `live_challenge(token_hash) -> ChallengeRecord | None`,
    `count_attempt(challenge_id) -> int`, `consume_challenge(challenge_id) -> bool` (True only for
    the call that consumed it, so two racing verifications cannot both sign in),
    `challenge_times(user_id, since) -> list[datetime]`;
  - **tokens:** `create_token(record: TokenRecord, token_hash: str) -> None`,
    `live_token(token_hash) -> TokenRecord | None`,
    `list_tokens(owner_kind, owner_id) -> list[TokenRecord]`,
    `active_token_count(owner_kind, owner_id) -> int`,
    `revoke_token(token_id, owner_kind, owner_id) -> bool`, `touch_token(token_id, at) -> None`;
  - **events:** `record_event(kind, outcome, *, user_id=None, token_id=None, detail_code=None) ->
    None`.

  "Live" means not revoked, not consumed, and not expired at `clock()`.

- [ ] **Step 1: Write the failing tests**

`python/tests/infrastructure/test_account_store_credentials.py`:

```python
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
            token_id, "user", user.user_id, user.workspace_id, token_id, "thoth_pat_ab",
            "write", created, created + timedelta(days=90), None,
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
```

- [ ] **Step 2: Run them to verify they fail**

Run: `make test T="tests/infrastructure/test_account_store_credentials.py"`
Expected: FAIL with `ImportError: cannot import name 'TokenRecord'`.

- [ ] **Step 3: Implement**

In `account_store.py`:
- add `update` to the `sqlalchemy` import;
- add `AuthEventRow, ChallengeRow, DeviceRow, SessionRow, TokenRow` to the `account_models`
  import;
- add these dataclasses after `AccountUser`.

```python
@dataclass(frozen=True)
class SessionRecord:
    session_id: str
    user_id: str
    workspace_id: str
    created_at: datetime
    last_seen_at: datetime
    expires_at: datetime


@dataclass(frozen=True)
class ChallengeRecord:
    challenge_id: str
    user_id: str
    code_hmac: str
    attempts: int
    created_at: datetime
    expires_at: datetime


@dataclass(frozen=True)
class TokenRecord:
    token_id: str
    owner_kind: str
    owner_id: str
    workspace_id: str
    name: str
    prefix: str
    scope: str
    created_at: datetime
    expires_at: datetime
    last_used_at: datetime | None
```

Add these methods to `AccountStore`:

```python
    # --- sessions --------------------------------------------------------------------------

    def create_session(
        self, user_id: str, workspace_id: str, token_hash: str, expires_at: datetime
    ) -> SessionRecord:
        now = self._clock()
        row = SessionRow(
            session_id=f"ses_{uuid4().hex}",
            user_id=user_id,
            workspace_id=workspace_id,
            token_hash=token_hash,
            created_at=now,
            last_seen_at=now,
            expires_at=expires_at,
        )
        self._write(lambda session: session.add(row))
        return _session(row)

    def live_session(self, token_hash: str) -> SessionRecord | None:
        row = self._one(
            select(SessionRow).where(
                SessionRow.token_hash == token_hash,
                SessionRow.revoked_at.is_(None),
                SessionRow.expires_at > self._clock(),
            )
        )
        return None if row is None else _session(row)

    def extend_session(self, session_id: str, expires_at: datetime, seen_at: datetime) -> None:
        self._execute(
            update(SessionRow)
            .where(SessionRow.session_id == session_id)
            .values(expires_at=expires_at, last_seen_at=seen_at)
        )

    def revoke_session(self, token_hash: str) -> None:
        self._execute(
            update(SessionRow)
            .where(SessionRow.token_hash == token_hash, SessionRow.revoked_at.is_(None))
            .values(revoked_at=self._clock())
        )

    # --- trusted browsers ------------------------------------------------------------------

    def trust_device(self, user_id: str, token_hash: str, expires_at: datetime) -> None:
        row = DeviceRow(
            device_id=f"dev_{uuid4().hex}",
            user_id=user_id,
            token_hash=token_hash,
            created_at=self._clock(),
            expires_at=expires_at,
        )
        self._write(lambda session: session.add(row))

    def is_trusted(self, user_id: str, token_hash: str) -> bool:
        return (
            self._one(
                select(DeviceRow).where(
                    DeviceRow.token_hash == token_hash,
                    DeviceRow.user_id == user_id,
                    DeviceRow.revoked_at.is_(None),
                    DeviceRow.expires_at > self._clock(),
                )
            )
            is not None
        )

    def forget_device(self, token_hash: str) -> None:
        self._execute(
            update(DeviceRow)
            .where(DeviceRow.token_hash == token_hash, DeviceRow.revoked_at.is_(None))
            .values(revoked_at=self._clock())
        )

    # --- email challenges ------------------------------------------------------------------

    def create_challenge(
        self,
        challenge_id: str,
        user_id: str,
        token_hash: str,
        code_hmac: str,
        expires_at: datetime,
    ) -> None:
        row = ChallengeRow(
            challenge_id=challenge_id,
            user_id=user_id,
            token_hash=token_hash,
            code_hmac=code_hmac,
            attempts=0,
            created_at=self._clock(),
            expires_at=expires_at,
        )
        self._write(lambda session: session.add(row))

    def live_challenge(self, token_hash: str) -> ChallengeRecord | None:
        row = self._one(
            select(ChallengeRow).where(
                ChallengeRow.token_hash == token_hash,
                ChallengeRow.consumed_at.is_(None),
                ChallengeRow.expires_at > self._clock(),
            )
        )
        if row is None:
            return None
        return ChallengeRecord(
            row.challenge_id, row.user_id, row.code_hmac, row.attempts, row.created_at,
            row.expires_at,
        )

    def count_attempt(self, challenge_id: str) -> int:
        try:
            with self._sessions.begin() as session:
                row = session.get(ChallengeRow, challenge_id, with_for_update=True)
                if row is None:
                    return 0
                row.attempts = min(row.attempts + 1, 5)
                return row.attempts
        except SQLAlchemyError as error:
            raise _unavailable(error) from None

    def consume_challenge(self, challenge_id: str) -> bool:
        try:
            with self._sessions.begin() as session:
                result = session.execute(
                    update(ChallengeRow)
                    .where(
                        ChallengeRow.challenge_id == challenge_id,
                        ChallengeRow.consumed_at.is_(None),
                    )
                    .values(consumed_at=self._clock())
                )
                return result.rowcount == 1
        except SQLAlchemyError as error:
            raise _unavailable(error) from None

    def challenge_times(self, user_id: str, since: datetime) -> list[datetime]:
        try:
            with self._sessions() as session:
                return list(
                    session.scalars(
                        select(ChallengeRow.created_at)
                        .where(ChallengeRow.user_id == user_id, ChallengeRow.created_at >= since)
                        .order_by(ChallengeRow.created_at)
                    )
                )
        except SQLAlchemyError as error:
            raise _unavailable(error) from None

    # --- developer tokens ------------------------------------------------------------------

    def create_token(self, record: TokenRecord, token_hash: str) -> None:
        row = TokenRow(
            token_id=record.token_id,
            owner_kind=record.owner_kind,
            owner_id=record.owner_id,
            workspace_id=record.workspace_id,
            name=record.name,
            prefix=record.prefix,
            token_hash=token_hash,
            scope=record.scope,
            created_at=record.created_at,
            expires_at=record.expires_at,
        )
        self._write(lambda session: session.add(row))

    def live_token(self, token_hash: str) -> TokenRecord | None:
        row = self._one(
            select(TokenRow).where(
                TokenRow.token_hash == token_hash,
                TokenRow.revoked_at.is_(None),
                TokenRow.expires_at > self._clock(),
            )
        )
        return None if row is None else _token(row)

    def list_tokens(self, owner_kind: str, owner_id: str) -> list[TokenRecord]:
        """Tokens that are not revoked, newest first; expired ones stay listed until revoked."""
        try:
            with self._sessions() as session:
                rows = session.scalars(
                    select(TokenRow)
                    .where(
                        TokenRow.owner_kind == owner_kind,
                        TokenRow.owner_id == owner_id,
                        TokenRow.revoked_at.is_(None),
                    )
                    .order_by(TokenRow.created_at.desc(), TokenRow.token_id.desc())
                ).all()
        except SQLAlchemyError as error:
            raise _unavailable(error) from None
        return [_token(row) for row in rows]

    def active_token_count(self, owner_kind: str, owner_id: str) -> int:
        try:
            with self._sessions() as session:
                return int(
                    session.scalar(
                        select(func.count())
                        .select_from(TokenRow)
                        .where(
                            TokenRow.owner_kind == owner_kind,
                            TokenRow.owner_id == owner_id,
                            TokenRow.revoked_at.is_(None),
                            TokenRow.expires_at > self._clock(),
                        )
                    )
                    or 0
                )
        except SQLAlchemyError as error:
            raise _unavailable(error) from None

    def revoke_token(self, token_id: str, owner_kind: str, owner_id: str) -> bool:
        try:
            with self._sessions.begin() as session:
                result = session.execute(
                    update(TokenRow)
                    .where(
                        TokenRow.token_id == token_id,
                        TokenRow.owner_kind == owner_kind,
                        TokenRow.owner_id == owner_id,
                        TokenRow.revoked_at.is_(None),
                    )
                    .values(revoked_at=self._clock())
                )
                return result.rowcount == 1
        except SQLAlchemyError as error:
            raise _unavailable(error) from None

    def touch_token(self, token_id: str, at: datetime) -> None:
        self._execute(update(TokenRow).where(TokenRow.token_id == token_id).values(last_used_at=at))

    # --- events ----------------------------------------------------------------------------

    def record_event(
        self,
        kind: str,
        outcome: str,
        *,
        user_id: str | None = None,
        token_id: str | None = None,
        detail_code: str | None = None,
    ) -> None:
        row = AuthEventRow(
            at=self._clock(),
            kind=kind,
            outcome=outcome,
            user_id=user_id,
            token_id=token_id,
            detail_code=detail_code,
        )
        self._write(lambda session: session.add(row))

    # --- plumbing --------------------------------------------------------------------------

    def _write(self, action: Callable[[Session], object]) -> None:
        try:
            with self._sessions.begin() as session:
                action(session)
        except SQLAlchemyError as error:
            raise _unavailable(error) from None

    def _execute(self, statement: object) -> None:
        self._write(lambda session: session.execute(statement))

    def _one(self, statement: object):  # noqa: ANN202 - an ORM row or None
        try:
            with self._sessions() as session:
                return session.scalars(statement).first()
        except SQLAlchemyError as error:
            raise _unavailable(error) from None
```

Add these module-level helpers after `_unavailable`:

```python
def _session(row: SessionRow) -> SessionRecord:
    return SessionRecord(
        row.session_id, row.user_id, row.workspace_id, row.created_at, row.last_seen_at,
        row.expires_at,
    )


def _token(row: TokenRow) -> TokenRecord:
    return TokenRecord(
        row.token_id, row.owner_kind, row.owner_id, row.workspace_id, row.name, row.prefix,
        row.scope, row.created_at, row.expires_at, row.last_used_at,
    )
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `make test T="tests/infrastructure/test_account_store_credentials.py tests/infrastructure/test_account_store_identities.py"`
Expected: PASS (9 tests).

- [ ] **Step 5: Add one Postgres round trip, run it, and commit**

Append to `python/tests/operations/test_editor_migrations_postgres.py`:

```python
def test_account_store_round_trips_on_postgres() -> None:
    from datetime import UTC, datetime, timedelta

    from thoth_control_plane.infrastructure.account_store import AccountStore

    apply_editor_migrations(DATABASE_URL, MIGRATIONS)
    store = AccountStore.connect(DATABASE_URL)
    user = store.ensure_user("a@acme.test", "A")
    assert user.workspace_id == "ws_bootstrap"
    later = datetime.now(UTC) + timedelta(hours=1)
    store.create_session(user.user_id, user.workspace_id, "h", later)
    assert store.live_session("h").user_id == user.user_id
    store.record_event("sign_in", "ok", user_id=user.user_id)
```

Run: `make test-postgres`
Expected: PASS.

```bash
git add python/src/thoth_control_plane/infrastructure/account_store.py python/tests/infrastructure/test_account_store_credentials.py python/tests/operations/test_editor_migrations_postgres.py
git commit -m "feat(accounts): store sessions, trusted browsers, codes, tokens and events"
```

---

### Task 5: Identity rules and the Google and GitHub providers

**Files:**
- Create: `python/src/thoth_control_plane/auth/rules.py`
- Create: `python/src/thoth_control_plane/auth/providers.py`
- Test: `python/tests/auth/test_rules.py`, `python/tests/auth/test_providers.py`

**Interfaces:**
- Consumes: `VerifiedIdentity` and `SignInRefused` (Task 2); `Settings` and its
  `*_sign_in_enabled` properties (Task 2).
- Produces:
  - **`rules.py`:**
    - `google_identity(userinfo: Mapping[str, object], domain: str) -> VerifiedIdentity`;
    - `github_identity(user: Mapping, emails: Sequence[Mapping], membership: Mapping | None, org:
      str) -> VerifiedIdentity`.
  - **`providers.py`:**
    - the protocol `IdentityProvider` with `name: str`, `async redirect(request, redirect_uri) ->
      Response` and `async identity(request) -> VerifiedIdentity`;
    - `GoogleProvider(client_id, client_secret, domain, *, metadata_url=GOOGLE_METADATA,
      transport=None)`;
    - `GitHubProvider(client_id, client_secret, org, *, transport=None)`;
    - `build_providers(settings, transport=None) -> dict[str, IdentityProvider]`.

- [ ] **Step 1: Write the failing rule tests**

`python/tests/auth/test_rules.py`:

```python
"""Who a provider may sign in (spec section 2, step 3). Pure functions, no network."""

import pytest

from thoth_control_plane.auth.models import SignInRefused
from thoth_control_plane.auth.rules import github_identity, google_identity


def refused(call) -> str:
    with pytest.raises(SignInRefused) as caught:
        call()
    return caught.value.code


def userinfo(**extra):
    return {"sub": "g-1", "email": "alice@acme.test", "email_verified": True, "name": "Alice"} | extra


def test_google_accepts_a_verified_address_in_the_exact_domain_lowercased() -> None:
    identity = google_identity(userinfo(email="ALICE@Acme.Test", hd="acme.test"), "acme.test")
    assert (identity.provider, identity.subject, identity.email) == (
        "google", "g-1", "alice@acme.test",
    )


@pytest.mark.parametrize(
    "email", ["alice@sub.acme.test", "alice@acme.test.evil.test", "alice@evil.test", "acme.test"]
)
def test_google_refuses_any_other_domain(email) -> None:
    assert refused(lambda: google_identity(userinfo(email=email), "acme.test")) == "not_allowed"


@pytest.mark.parametrize("verified", [False, None, "true"])
def test_google_requires_a_provider_verified_email(verified) -> None:
    claims = userinfo(email_verified=verified)
    assert refused(lambda: google_identity(claims, "acme.test")) == "unverified_email"


def test_google_refuses_a_workspace_claim_for_another_domain() -> None:
    claims = userinfo(hd="other.test")
    assert refused(lambda: google_identity(claims, "acme.test")) == "not_allowed"


GITHUB_USER = {"id": 42, "login": "alice", "name": "Alice"}
VERIFIED = [{"email": "Alice@Acme.test", "primary": True, "verified": True}]


def membership(state="active", org="Acme"):
    return {"state": state, "organization": {"login": org}}


def test_github_accepts_an_active_member_with_a_verified_primary_email() -> None:
    identity = github_identity(GITHUB_USER, VERIFIED, membership(), "acme")
    assert (identity.provider, identity.subject, identity.email, identity.display_name) == (
        "github", "42", "alice@acme.test", "Alice",
    )


@pytest.mark.parametrize("member", [None, membership(state="pending"), membership(org="Other")])
def test_github_refuses_anyone_not_an_active_member_of_the_org(member) -> None:
    assert refused(lambda: github_identity(GITHUB_USER, VERIFIED, member, "acme")) == "not_allowed"


@pytest.mark.parametrize(
    "emails",
    [
        [],
        [{"email": "a@acme.test", "primary": True, "verified": False}],
        [{"email": "a@acme.test", "primary": False, "verified": True}],
    ],
)
def test_github_requires_a_verified_primary_email(emails) -> None:
    call = lambda: github_identity(GITHUB_USER, emails, membership(), "acme")  # noqa: E731
    assert refused(call) == "unverified_email"
```

- [ ] **Step 2: Run them to verify they fail**

Run: `make test T="tests/auth/test_rules.py"`
Expected: FAIL with `ModuleNotFoundError: ... auth.rules`.

- [ ] **Step 3: Implement the rules**

`python/src/thoth_control_plane/auth/rules.py`:

```python
"""Turn a provider's answer into a verified identity, or refuse it with a fixed code."""

from __future__ import annotations

from collections.abc import Mapping, Sequence

from thoth_control_plane.auth.models import SignInRefused, VerifiedIdentity


def _domain(email: str) -> str:
    return email.rpartition("@")[2] if "@" in email else ""


def google_identity(userinfo: Mapping[str, object], domain: str) -> VerifiedIdentity:
    if userinfo.get("email_verified") is not True:
        raise SignInRefused("unverified_email")
    email = str(userinfo.get("email") or "").strip().lower()
    wanted = domain.strip().lower()
    if not email or _domain(email) != wanted:
        raise SignInRefused("not_allowed")
    hosted = userinfo.get("hd")
    if hosted is not None and str(hosted).strip().lower() != wanted:
        raise SignInRefused("not_allowed")
    subject = str(userinfo.get("sub") or "")
    if not subject:
        raise SignInRefused("provider_error")
    return VerifiedIdentity("google", subject, email, str(userinfo.get("name") or email)[:200])


def github_identity(
    user: Mapping[str, object],
    emails: Sequence[Mapping[str, object]],
    membership: Mapping[str, object] | None,
    org: str,
) -> VerifiedIdentity:
    subject = str(user.get("id") or "")
    if not subject:
        raise SignInRefused("provider_error")
    primary = next((e for e in emails if isinstance(e, Mapping) and e.get("primary")), None)
    email = str((primary or {}).get("email") or "").strip().lower()
    if primary is None or primary.get("verified") is not True or "@" not in email:
        raise SignInRefused("unverified_email")
    organization = (membership or {}).get("organization") or {}
    login = str(organization.get("login") or "") if isinstance(organization, Mapping) else ""
    if (
        membership is None
        or membership.get("state") != "active"
        or login.lower() != org.strip().lower()
    ):
        raise SignInRefused("not_allowed")
    name = str(user.get("name") or user.get("login") or email)[:200]
    return VerifiedIdentity("github", subject, email, name)
```

- [ ] **Step 4: Run the rule tests to verify they pass**

Run: `make test T="tests/auth/test_rules.py"`
Expected: PASS.

- [ ] **Step 5: Write the failing provider tests**

These drive Authlib through a real redirect and callback, with every provider endpoint faked by
`httpx.MockTransport`.

`python/tests/auth/test_providers.py`:

```python
"""Google and GitHub through Authlib with faked endpoints (spec section 5, testing)."""

import time
from urllib.parse import parse_qs, urlsplit

import httpx
import pytest
from authlib.jose import JsonWebKey, jwt
from starlette.applications import Starlette
from starlette.middleware.sessions import SessionMiddleware
from starlette.responses import JSONResponse
from starlette.routing import Route

from thoth_control_plane.auth.models import SignInRefused
from thoth_control_plane.auth.providers import GitHubProvider, GoogleProvider, build_providers
from thoth_control_plane.config import Settings

CALLBACK = "http://testserver/callback"


def harness(provider) -> Starlette:
    async def login(request):
        return await provider.redirect(request, CALLBACK)

    async def callback(request):
        try:
            identity = await provider.identity(request)
        except SignInRefused as refused:
            return JSONResponse({"refused": refused.code})
        return JSONResponse({"subject": identity.subject, "email": identity.email})

    app = Starlette(routes=[Route("/login", login), Route("/callback", callback)])
    app.add_middleware(SessionMiddleware, secret_key="test-secret")
    return app


def client(app) -> httpx.AsyncClient:
    return httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://testserver")


def query(response: httpx.Response) -> dict[str, str]:
    return {k: v[0] for k, v in parse_qs(urlsplit(response.headers["location"]).query).items()}


def github_api(*, state: str | None = "active") -> httpx.MockTransport:
    def handler(request: httpx.Request) -> httpx.Response:
        url = str(request.url)
        if url == "https://github.com/login/oauth/access_token":
            return httpx.Response(200, json={"access_token": "t", "token_type": "bearer"})
        if url == "https://api.github.com/user":
            return httpx.Response(200, json={"id": 42, "login": "alice", "name": "Alice"})
        if url == "https://api.github.com/user/emails":
            return httpx.Response(
                200, json=[{"email": "Alice@Acme.test", "primary": True, "verified": True}]
            )
        if url == "https://api.github.com/user/memberships/orgs/acme" and state:
            return httpx.Response(200, json={"state": state, "organization": {"login": "acme"}})
        return httpx.Response(404, json={"message": "Not Found"})

    return httpx.MockTransport(handler)


async def test_github_signs_in_an_active_member_through_a_real_redirect() -> None:
    app = harness(GitHubProvider("gh-id", "gh-secret", "acme", transport=github_api()))
    async with client(app) as http:
        login = await http.get("/login")
        assert login.headers["location"].startswith("https://github.com/login/oauth/authorize")
        params = query(login)
        assert params["code_challenge_method"] == "S256"
        assert "read:org" in params["scope"]
        result = (await http.get(f"/callback?code=c&state={params['state']}")).json()
    assert result == {"subject": "42", "email": "alice@acme.test"}


async def test_github_refuses_a_pending_member() -> None:
    app = harness(GitHubProvider("gh-id", "gh-secret", "acme", transport=github_api(state="pending")))
    async with client(app) as http:
        state = query(await http.get("/login"))["state"]
        assert (await http.get(f"/callback?code=c&state={state}")).json() == {"refused": "not_allowed"}


async def test_a_replayed_or_foreign_callback_is_a_provider_error_not_a_crash() -> None:
    app = harness(GitHubProvider("gh-id", "gh-secret", "acme", transport=github_api()))
    async with client(app) as http:
        state = query(await http.get("/login"))["state"]
        await http.get(f"/callback?code=c&state={state}")
        replay = await http.get(f"/callback?code=c&state={state}")
    assert replay.json() == {"refused": "provider_error"}
    async with client(app) as stranger:  # no state cookie at all: another tab or browser
        foreign = await stranger.get("/callback?code=c&state=forged")
    assert foreign.json() == {"refused": "provider_error"}


KEY = JsonWebKey.generate_key("RSA", 2048, is_private=True, options={"kid": "k1"})
ISSUER = "https://accounts.test"


def google_api(nonce: dict[str, str], **claims) -> httpx.MockTransport:
    def handler(request: httpx.Request) -> httpx.Response:
        url = str(request.url)
        if url == f"{ISSUER}/.well-known/openid-configuration":
            return httpx.Response(200, json={
                "issuer": ISSUER,
                "authorization_endpoint": f"{ISSUER}/auth",
                "token_endpoint": f"{ISSUER}/token",
                "jwks_uri": f"{ISSUER}/jwks",
                "id_token_signing_alg_values_supported": ["RS256"],
            })
        if url == f"{ISSUER}/jwks":
            return httpx.Response(200, json={"keys": [KEY.as_dict(is_private=False)]})
        if url == f"{ISSUER}/token":
            now = int(time.time())
            body = {
                "iss": ISSUER, "aud": "g-id", "sub": "g-123", "iat": now, "exp": now + 600,
                "nonce": nonce["value"], "email": "alice@acme.test", "email_verified": True,
                "hd": "acme.test", "name": "Alice",
            } | claims
            token = jwt.encode({"alg": "RS256", "kid": "k1"}, body, KEY).decode()
            return httpx.Response(200, json={
                "access_token": "a", "token_type": "Bearer", "expires_in": 600, "id_token": token,
            })
        return httpx.Response(404)

    return httpx.MockTransport(handler)


async def google_sign_in(**claims) -> dict:
    nonce: dict[str, str] = {}
    provider = GoogleProvider(
        "g-id", "g-secret", "acme.test",
        metadata_url=f"{ISSUER}/.well-known/openid-configuration",
        transport=google_api(nonce, **claims),
    )
    async with client(harness(provider)) as http:
        params = query(await http.get("/login"))
        nonce["value"] = params["nonce"]
        return (await http.get(f"/callback?code=c&state={params['state']}")).json()


async def test_google_signs_in_a_verified_domain_account_from_a_signed_id_token() -> None:
    assert await google_sign_in() == {"subject": "g-123", "email": "alice@acme.test"}


async def test_google_refuses_an_unverified_or_foreign_account() -> None:
    assert await google_sign_in(email_verified=False) == {"refused": "unverified_email"}
    assert await google_sign_in(email="eve@evil.test", hd=None) == {"refused": "not_allowed"}


async def test_google_refuses_a_token_for_another_audience() -> None:
    assert await google_sign_in(aud="someone-else") == {"refused": "provider_error"}


def test_only_fully_configured_providers_are_built() -> None:
    base = dict(
        THOTH_CONTROL_PLANE_API_KEY="k",
        THOTH_EDITOR_DATABASE_URL="postgresql://u:p@db/x",
        THOTH_AUTH_SECRET="s" * 32,
        THOTH_SMTP_HOST="smtp.test",
        THOTH_SMTP_FROM="no-reply@acme.test",
    )
    assert build_providers(Settings(**base)) == {}
    both = build_providers(Settings(
        **base,
        THOTH_AUTH_GOOGLE_CLIENT_ID="g", THOTH_AUTH_GOOGLE_CLIENT_SECRET="s",
        THOTH_AUTH_GOOGLE_DOMAIN="acme.test",
        THOTH_AUTH_GITHUB_CLIENT_ID="h", THOTH_AUTH_GITHUB_CLIENT_SECRET="s",
        THOTH_AUTH_GITHUB_ORG="acme",
    ))
    assert sorted(both) == ["github", "google"]
```

If the installed Authlib turns `authlib.jose` into an error rather than a warning, sign with
`joserfc`, which Authlib depends on. Record that in the ledger as a ruling. The pytest
configuration has no `filterwarnings`, so a deprecation warning alone needs no change.

- [ ] **Step 6: Run them to verify they fail**

Run: `make test T="tests/auth/test_providers.py"`
Expected: FAIL with `ModuleNotFoundError: ... auth.providers`.

- [ ] **Step 7: Implement the providers**

`python/src/thoth_control_plane/auth/providers.py`:

```python
"""Google (OpenID Connect) and GitHub (OAuth 2) through Authlib's Starlette client.

Every provider failure, including a missing or replayed state, becomes `provider_error`; the
provider's own text never reaches the caller.
"""

from __future__ import annotations

from typing import Protocol
from urllib.parse import quote

import httpx
from authlib.common.errors import AuthlibBaseError
from authlib.integrations.starlette_client import OAuth
from starlette.requests import Request
from starlette.responses import Response

from thoth_control_plane.auth.models import SignInRefused, VerifiedIdentity
from thoth_control_plane.auth.rules import github_identity, google_identity
from thoth_control_plane.config import Settings

GOOGLE_METADATA = "https://accounts.google.com/.well-known/openid-configuration"
#: Failures a provider round trip can raise; all of them mean `provider_error`.
PROVIDER_FAILURES = (AuthlibBaseError, httpx.HTTPError, KeyError, TypeError, ValueError)


class IdentityProvider(Protocol):
    name: str

    async def redirect(self, request: Request, redirect_uri: str) -> Response: ...

    async def identity(self, request: Request) -> VerifiedIdentity: ...


def _client_kwargs(scope: str, transport: httpx.AsyncBaseTransport | None) -> dict[str, object]:
    kwargs: dict[str, object] = {"scope": scope, "code_challenge_method": "S256"}
    if transport is not None:
        kwargs["transport"] = transport
    return kwargs


class GoogleProvider:
    name = "google"

    def __init__(
        self,
        client_id: str,
        client_secret: str,
        domain: str,
        *,
        metadata_url: str = GOOGLE_METADATA,
        transport: httpx.AsyncBaseTransport | None = None,
    ) -> None:
        self._domain = domain
        self._client = OAuth().register(
            "google",
            client_id=client_id,
            client_secret=client_secret,
            server_metadata_url=metadata_url,
            client_kwargs=_client_kwargs("openid email profile", transport),
        )

    async def redirect(self, request: Request, redirect_uri: str) -> Response:
        return await self._client.authorize_redirect(request, redirect_uri)

    async def identity(self, request: Request) -> VerifiedIdentity:
        try:
            token = await self._client.authorize_access_token(request)
        except PROVIDER_FAILURES:
            raise SignInRefused("provider_error") from None
        return google_identity(token.get("userinfo") or {}, self._domain)


class GitHubProvider:
    name = "github"

    def __init__(
        self,
        client_id: str,
        client_secret: str,
        org: str,
        *,
        transport: httpx.AsyncBaseTransport | None = None,
    ) -> None:
        self._org = org
        self._client = OAuth().register(
            "github",
            client_id=client_id,
            client_secret=client_secret,
            access_token_url="https://github.com/login/oauth/access_token",
            authorize_url="https://github.com/login/oauth/authorize",
            api_base_url="https://api.github.com/",
            client_kwargs=_client_kwargs("read:user user:email read:org", transport),
        )

    async def redirect(self, request: Request, redirect_uri: str) -> Response:
        return await self._client.authorize_redirect(request, redirect_uri)

    async def identity(self, request: Request) -> VerifiedIdentity:
        try:
            token = await self._client.authorize_access_token(request)
            user = await self._client.get("user", token=token)
            user.raise_for_status()
            emails = await self._client.get("user/emails", token=token)
            emails.raise_for_status()
            membership = await self._client.get(
                f"user/memberships/orgs/{quote(self._org, safe='')}", token=token
            )
            found = membership.json() if membership.status_code == 200 else None
            listed = emails.json()
            return github_identity(
                user.json(), listed if isinstance(listed, list) else [], found, self._org
            )
        except PROVIDER_FAILURES:
            raise SignInRefused("provider_error") from None


def build_providers(
    settings: Settings, transport: httpx.AsyncBaseTransport | None = None
) -> dict[str, IdentityProvider]:
    """Only providers whose client, rule, secret, database and mail are all configured."""
    providers: dict[str, IdentityProvider] = {}
    if settings.google_sign_in_enabled:
        providers["google"] = GoogleProvider(
            settings.THOTH_AUTH_GOOGLE_CLIENT_ID or "",
            settings.THOTH_AUTH_GOOGLE_CLIENT_SECRET.get_secret_value(),  # type: ignore[union-attr]
            settings.THOTH_AUTH_GOOGLE_DOMAIN or "",
            transport=transport,
        )
    if settings.github_sign_in_enabled:
        providers["github"] = GitHubProvider(
            settings.THOTH_AUTH_GITHUB_CLIENT_ID or "",
            settings.THOTH_AUTH_GITHUB_CLIENT_SECRET.get_secret_value(),  # type: ignore[union-attr]
            settings.THOTH_AUTH_GITHUB_ORG or "",
            transport=transport,
        )
    return providers
```

`github_identity` raises `SignInRefused` itself. That exception is not in `PROVIDER_FAILURES`, so
it passes through unchanged.

- [ ] **Step 8: Run the tests to verify they pass**

Run: `make test T="tests/auth/test_rules.py tests/auth/test_providers.py"`
Expected: PASS.

- [ ] **Step 9: Commit**

```bash
git add python/src/thoth_control_plane/auth/rules.py python/src/thoth_control_plane/auth/providers.py python/tests/auth/test_rules.py python/tests/auth/test_providers.py
git commit -m "feat(auth): verify Google domain and GitHub org identities via Authlib"
```

---

### Task 6: The email code mailer

**Files:**
- Create: `python/src/thoth_control_plane/auth/mailer.py`
- Test: `python/tests/auth/test_mailer.py`

**Interfaces:**
- Produces:
  - `class MailNotSent(Exception)`;
  - the protocol `Mailer` with `async send(to: str, subject: str, body: str) -> None`;
  - `SmtpMailer(host, port, username, password, sender, *, smtp=smtplib)`;
  - `mailer_from(settings) -> Mailer | None`.

- [ ] **Step 1: Write the failing tests**

`python/tests/auth/test_mailer.py`:

```python
"""Email codes over SMTP; the library is faked so no socket opens (spec section 5)."""

import smtplib
import types

import pytest

from thoth_control_plane.auth.mailer import MailNotSent, SmtpMailer, mailer_from
from thoth_control_plane.config import Settings


class FakeSmtp:
    sent: list = []
    calls: list = []
    fail = False

    def __init__(self, host, port, timeout, **_):
        FakeSmtp.calls.append(("connect", type(self).__name__, host, port, timeout))

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False

    def starttls(self, context=None):
        FakeSmtp.calls.append(("starttls",))

    def login(self, user, password):
        FakeSmtp.calls.append(("login", user))

    def send_message(self, message):
        if FakeSmtp.fail:
            raise smtplib.SMTPException("relay refused")
        FakeSmtp.sent.append(message)


class FakeSmtpSsl(FakeSmtp):
    pass


@pytest.fixture(autouse=True)
def reset():
    FakeSmtp.sent, FakeSmtp.calls, FakeSmtp.fail = [], [], False


FAKE = types.SimpleNamespace(SMTP=FakeSmtp, SMTP_SSL=FakeSmtpSsl, SMTPException=smtplib.SMTPException)


async def test_a_code_is_sent_over_starttls_with_login() -> None:
    mailer = SmtpMailer("smtp.test", 587, "user", "pw", "Thoth <no-reply@acme.test>", smtp=FAKE)
    await mailer.send("alice@acme.test", "Your code", "123456")
    (message,) = FakeSmtp.sent
    assert (message["To"], message["From"], message["Subject"]) == (
        "alice@acme.test", "Thoth <no-reply@acme.test>", "Your code",
    )
    assert [call[0] for call in FakeSmtp.calls] == ["connect", "starttls", "login"]


async def test_port_465_uses_implicit_tls() -> None:
    await SmtpMailer("smtp.test", 465, None, None, "a@acme.test", smtp=FAKE).send("b@acme.test", "s", "b")
    assert FakeSmtp.calls[0][1] == "FakeSmtpSsl"
    assert ("starttls",) not in FakeSmtp.calls


async def test_a_relay_failure_is_mail_not_sent_without_the_server_text() -> None:
    FakeSmtp.fail = True
    with pytest.raises(MailNotSent) as caught:
        await SmtpMailer("smtp.test", 587, None, None, "a@acme.test", smtp=FAKE).send("b@acme.test", "s", "b")
    assert "relay refused" not in str(caught.value)


def test_no_mailer_without_host_and_sender() -> None:
    assert mailer_from(Settings(THOTH_CONTROL_PLANE_API_KEY="k")) is None
    configured = Settings(
        THOTH_CONTROL_PLANE_API_KEY="k", THOTH_SMTP_HOST="smtp.test", THOTH_SMTP_FROM="a@acme.test"
    )
    assert isinstance(mailer_from(configured), SmtpMailer)
```

- [ ] **Step 2: Run them to verify they fail**

Run: `make test T="tests/auth/test_mailer.py"`
Expected: FAIL with `ModuleNotFoundError: ... auth.mailer`.

- [ ] **Step 3: Implement**

`python/src/thoth_control_plane/auth/mailer.py`:

```python
"""Send sign-in codes over SMTP (standard library), off the event loop."""

from __future__ import annotations

import asyncio
import smtplib
import ssl
from email.message import EmailMessage
from types import ModuleType
from typing import Any, Protocol

from thoth_control_plane.config import Settings

IMPLICIT_TLS_PORT = 465


class MailNotSent(Exception):
    """The relay refused or could not be reached. The server's text is never kept."""


class Mailer(Protocol):
    async def send(self, to: str, subject: str, body: str) -> None: ...


class SmtpMailer:
    def __init__(
        self,
        host: str,
        port: int,
        username: str | None,
        password: str | None,
        sender: str,
        *,
        smtp: ModuleType | Any = smtplib,
    ) -> None:
        self._host, self._port = host, port
        self._username, self._password = username, password
        self._sender = sender
        self._smtp = smtp

    def __repr__(self) -> str:
        return "SmtpMailer()"

    async def send(self, to: str, subject: str, body: str) -> None:
        await asyncio.to_thread(self._send, to, subject, body)

    def _send(self, to: str, subject: str, body: str) -> None:
        message = EmailMessage()
        message["From"] = self._sender
        message["To"] = to
        message["Subject"] = subject
        message.set_content(body)
        context = ssl.create_default_context()
        try:
            if self._port == IMPLICIT_TLS_PORT:
                client = self._smtp.SMTP_SSL(self._host, self._port, timeout=15, context=context)
            else:
                client = self._smtp.SMTP(self._host, self._port, timeout=15)
            with client:
                if self._port != IMPLICIT_TLS_PORT:
                    client.starttls(context=context)
                if self._username:
                    client.login(self._username, self._password or "")
                client.send_message(message)
        except (OSError, smtplib.SMTPException):
            raise MailNotSent() from None


def mailer_from(settings: Settings) -> Mailer | None:
    if not settings.email_codes_enabled:
        return None
    password = settings.THOTH_SMTP_PASSWORD
    return SmtpMailer(
        settings.THOTH_SMTP_HOST or "",
        settings.THOTH_SMTP_PORT,
        settings.THOTH_SMTP_USERNAME,
        password.get_secret_value() if password is not None else None,
        settings.THOTH_SMTP_FROM or "",
    )
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `make test T="tests/auth/test_mailer.py"`
Expected: PASS (4 tests).

- [ ] **Step 5: Commit**

```bash
git add python/src/thoth_control_plane/auth/mailer.py python/tests/auth/test_mailer.py
git commit -m "feat(auth): send sign-in codes over SMTP"
```

---

### Task 7: SignInService: codes, sessions, trusted browsers and tokens

**Files:**
- Create: `python/src/thoth_control_plane/auth/service.py`
- Test: `python/tests/auth/test_sign_in_service.py`

**Interfaces:**
- Consumes:
  - `AccountStore`, `AccountUser`, `TokenRecord` and `AccountStoreUnavailable` (Tasks 3-4);
  - `Mailer` and `MailNotSent` (Task 6);
  - the secrets helpers and models (Task 2).
- Produces:
  - **constants:** `SESSION_IDLE`, `SESSION_MAX`, `DEVICE_TTL`, `CODE_TTL`, `CODE_ATTEMPTS`,
    `RESEND_AFTER`, `DAILY_CODES`, `TOKEN_LIMIT`, `TOUCH_EVERY`;
  - **dataclasses:** `SignedIn(session_token, session_expires_at, device_token | None)` and
    `CodeSent(challenge_token)`;
  - **errors:** `CodeRejected(code)`, `CodeLimited(code)`, `CodeNotSent`, `AuthUnavailable`,
    `UserRequired`, `TokenLimitReached`, `ScopeTooBroad`;
  - **`class SignInService(store, mailer, secret, clock=utcnow)`:**
    - `async begin(identity, device_token) -> SignedIn | CodeSent`;
    - `async verify(challenge_token, code, *, trust_device, previous_session) -> SignedIn`;
    - `async resend(challenge_token) -> CodeSent`;
    - `async logout(session_token, device_token, *, forget_device) -> None`;
    - `async authenticate_session(token) -> Principal | None`;
    - `async authenticate_token(text) -> Principal | None`;
    - `async create_token(principal, request: CreateToken) -> CreatedToken`;
    - `async create_workspace_token(principal, request) -> CreatedToken`;
    - `async list_tokens(principal) -> list[TokenView]`;
    - `async revoke_token(principal, token_id) -> bool`;
    - `async note_service_key() -> None`;
  - `token_view(record: TokenRecord) -> TokenView`.

- [ ] **Step 1: Write the failing tests**

`python/tests/auth/test_sign_in_service.py`:

```python
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
    done = await service.verify(step.challenge_token, mailer.last_code, trust_device=True, previous_session=None)
    assert done.device_token is not None
    principal = await service.authenticate_session(done.session_token)
    assert principal == Principal(
        principal.user_id, BOOTSTRAP_WORKSPACE_ID, SCOPE_SETS["admin"], "session", "alice@acme.test"
    )


async def test_a_trusted_browser_skips_the_code(service, mailer) -> None:
    first = await signed_in(service, mailer)
    mailer.sent.clear()
    again = await service.begin(ALICE, first.device_token)
    assert isinstance(again, SignedIn) and again.device_token is None
    assert mailer.sent == []


async def test_a_code_dies_after_five_misses_and_a_used_code_never_works_again(service, mailer) -> None:
    step = await service.begin(ALICE, None)
    good = mailer.last_code
    bad = "000000" if good != "000000" else "111111"
    for _ in range(4):
        with pytest.raises(CodeRejected, match="wrong_code"):
            await service.verify(step.challenge_token, bad, trust_device=False, previous_session=None)
    with pytest.raises(CodeRejected, match="too_many_attempts"):
        await service.verify(step.challenge_token, bad, trust_device=False, previous_session=None)
    with pytest.raises(CodeRejected, match="expired"):
        await service.verify(step.challenge_token, good, trust_device=False, previous_session=None)
    fresh = await service.begin(ALICE, None)  # begin has no cooldown
    code = mailer.last_code
    await service.verify(fresh.challenge_token, code, trust_device=False, previous_session=None)
    with pytest.raises(CodeRejected, match="expired"):
        await service.verify(fresh.challenge_token, code, trust_device=False, previous_session=None)


async def test_a_code_expires_after_ten_minutes(service, mailer, clock) -> None:
    step = await service.begin(ALICE, None)
    clock.now = T0 + timedelta(minutes=10, seconds=1)
    with pytest.raises(CodeRejected, match="expired"):
        await service.verify(step.challenge_token, mailer.last_code, trust_device=False, previous_session=None)


async def test_resend_waits_sixty_seconds_and_replaces_the_code(service, mailer, clock) -> None:
    step = await service.begin(ALICE, None)
    with pytest.raises(CodeLimited, match="resend_too_soon"):
        await service.resend(step.challenge_token)
    clock.now = T0 + timedelta(seconds=61)
    again = await service.resend(step.challenge_token)
    with pytest.raises(CodeRejected, match="expired"):
        await service.verify(step.challenge_token, mailer.last_code, trust_device=False, previous_session=None)
    await service.verify(again.challenge_token, mailer.last_code, trust_device=False, previous_session=None)


async def test_ten_codes_a_day_at_most(service, mailer, clock) -> None:
    for minute in range(10):
        clock.now = T0 + timedelta(minutes=minute)
        await service.begin(ALICE, None)
    with pytest.raises(SignInRefused) as caught:
        await service.begin(ALICE, None)
    assert caught.value.code == "too_many_codes"


async def test_an_unsent_code_cannot_be_used(service, mailer) -> None:
    mailer.fail = True
    with pytest.raises(CodeNotSent):
        await service.begin(ALICE, None)


async def test_a_session_slides_but_never_outlives_seven_days(service, mailer, clock) -> None:
    done = await signed_in(service, mailer)
    for hours in range(11, 24 * 7, 11):
        clock.now = T0 + timedelta(hours=hours)
        assert await service.authenticate_session(done.session_token) is not None
    clock.now = T0 + timedelta(days=7, minutes=1)
    assert await service.authenticate_session(done.session_token) is None


async def test_signing_in_again_rotates_the_session_and_logout_ends_it(service, mailer, clock) -> None:
    first = await signed_in(service, mailer, trust=False)
    clock.now = T0 + timedelta(minutes=2)
    step = await service.begin(ALICE, None)
    second = await service.verify(step.challenge_token, mailer.last_code, trust_device=False, previous_session=first.session_token)
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
```

`SignInRefused` has no `match` text by itself. Give it one by calling
`super().__init__(code)`, which Task 2 already does, so `pytest.raises(..., match="not_allowed")`
works. Make `CodeRejected` and `CodeLimited` do the same.

- [ ] **Step 2: Run them to verify they fail**

Run: `make test T="tests/auth/test_sign_in_service.py"`
Expected: FAIL with `ModuleNotFoundError: ... auth.service`.

- [ ] **Step 3: Implement**

`python/src/thoth_control_plane/auth/service.py`:

```python
"""Sign-in rules: email codes, sessions, trusted browsers and developer tokens (spec 2-3).

Every store call runs off the event loop. A store failure is `AuthUnavailable`; an audit row
that cannot be written is logged and never blocks a sign-in.
"""

from __future__ import annotations

import asyncio
import logging
from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Any
from uuid import uuid4

from thoth_control_plane.auth.mailer import Mailer, MailNotSent
from thoth_control_plane.auth.models import (
    ALL_SCOPES,
    SCOPE_SETS,
    CreatedToken,
    CreateToken,
    Principal,
    SignInRefused,
    TokenView,
    VerifiedIdentity,
)
from thoth_control_plane.auth.secrets import (
    TOKEN_PREFIX,
    code_hmac,
    new_code,
    random_token,
    same,
    token_hash,
)
from thoth_control_plane.infrastructure.account_store import (
    AccountStore,
    AccountStoreUnavailable,
    AccountUser,
    TokenRecord,
)

logger = logging.getLogger(__name__)

SESSION_IDLE = timedelta(hours=12)
SESSION_MAX = timedelta(days=7)
DEVICE_TTL = timedelta(days=30)
CODE_TTL = timedelta(minutes=10)
CODE_ATTEMPTS = 5
RESEND_AFTER = timedelta(seconds=60)
DAILY_CODES = 10
TOKEN_LIMIT = 20
TOUCH_EVERY = timedelta(minutes=1)
CODE_SUBJECT = "Your Thoth sign-in code"


@dataclass(frozen=True)
class SignedIn:
    session_token: str
    session_expires_at: datetime
    device_token: str | None


@dataclass(frozen=True)
class CodeSent:
    challenge_token: str


class _Coded(Exception):
    def __init__(self, code: str) -> None:
        super().__init__(code)
        self.code = code


class CodeRejected(_Coded):
    """`wrong_code`, `expired` or `too_many_attempts`."""


class CodeLimited(_Coded):
    """`resend_too_soon` or `daily_limit`."""


class CodeNotSent(Exception):
    pass


class AuthUnavailable(Exception):
    pass


class UserRequired(Exception):
    pass


class TokenLimitReached(Exception):
    pass


class ScopeTooBroad(Exception):
    pass


def token_view(record: TokenRecord) -> TokenView:
    return TokenView(
        token_id=record.token_id,
        owner_kind=record.owner_kind,  # type: ignore[arg-type]
        name=record.name,
        prefix=record.prefix,
        scope=record.scope,  # type: ignore[arg-type]
        created_at=record.created_at,
        expires_at=record.expires_at,
        last_used_at=record.last_used_at,
    )


class SignInService:
    def __init__(
        self,
        store: AccountStore,
        mailer: Mailer | None,
        secret: str | None,
        clock: Callable[[], datetime] = lambda: datetime.now(UTC),
    ) -> None:
        self._store = store
        self._mailer = mailer
        self._secret = secret
        self._clock = clock

    async def _run(self, function: Callable[..., Any], *args: Any) -> Any:
        try:
            return await asyncio.to_thread(function, *args)
        except AccountStoreUnavailable as error:
            raise AuthUnavailable() from error

    async def _event(self, kind: str, outcome: str, **fields: str | None) -> None:
        try:
            await asyncio.to_thread(self._store.record_event, kind, outcome, **fields)
        except AccountStoreUnavailable:
            logger.warning("auth event %s was not recorded", kind)

    # --- signing in ------------------------------------------------------------------------

    async def begin(self, identity: VerifiedIdentity, device_token: str | None) -> SignedIn | CodeSent:
        if self._secret is None or self._mailer is None:
            raise SignInRefused("not_configured")
        account: AccountUser = await self._run(self._store.upsert_identity, identity)
        if account.disabled:
            await self._event("sign_in", "refused", user_id=account.user_id, detail_code="not_allowed")
            raise SignInRefused("not_allowed")
        if device_token and await self._run(
            self._store.is_trusted, account.user_id, token_hash(device_token)
        ):
            return await self._start(account, trust_device=False)
        try:
            return await self._send_code(account, enforce_cooldown=False)
        except CodeLimited:
            raise SignInRefused("too_many_codes") from None

    async def verify(
        self,
        challenge_token: str,
        code: str,
        *,
        trust_device: bool,
        previous_session: str | None,
    ) -> SignedIn:
        record = await self._run(self._store.live_challenge, token_hash(challenge_token))
        if record is None:
            raise CodeRejected("expired")
        if record.attempts >= CODE_ATTEMPTS:
            raise CodeRejected("too_many_attempts")
        expected = code_hmac(self._secret or "", record.challenge_id, code.strip())
        if not same(record.code_hmac, expected):
            attempts = await self._run(self._store.count_attempt, record.challenge_id)
            if attempts >= CODE_ATTEMPTS:
                await self._run(self._store.consume_challenge, record.challenge_id)
                await self._event("email_code", "refused", user_id=record.user_id, detail_code="too_many_attempts")
                raise CodeRejected("too_many_attempts")
            raise CodeRejected("wrong_code")
        if not await self._run(self._store.consume_challenge, record.challenge_id):
            raise CodeRejected("expired")  # a concurrent verification won
        account = await self._run(self._store.account, record.user_id)
        if account is None or account.disabled:
            raise SignInRefused("not_allowed")
        if previous_session:
            await self._run(self._store.revoke_session, token_hash(previous_session))
        return await self._start(account, trust_device=trust_device)

    async def resend(self, challenge_token: str) -> CodeSent:
        record = await self._run(self._store.live_challenge, token_hash(challenge_token))
        if record is None:
            raise CodeRejected("expired")
        account = await self._run(self._store.account, record.user_id)
        if account is None or account.disabled:
            raise SignInRefused("not_allowed")
        sent = await self._send_code(account, enforce_cooldown=True)
        await self._run(self._store.consume_challenge, record.challenge_id)
        return sent

    async def logout(
        self, session_token: str | None, device_token: str | None, *, forget_device: bool
    ) -> None:
        if session_token:
            await self._run(self._store.revoke_session, token_hash(session_token))
        if forget_device and device_token:
            await self._run(self._store.forget_device, token_hash(device_token))

    # --- who is calling --------------------------------------------------------------------

    async def authenticate_session(self, session_token: str) -> Principal | None:
        record = await self._run(self._store.live_session, token_hash(session_token))
        if record is None:
            return None
        account = await self._run(self._store.account, record.user_id)
        if account is None or account.disabled:
            return None
        now = self._clock()
        if now - record.last_seen_at >= TOUCH_EVERY:
            expires = min(now + SESSION_IDLE, record.created_at + SESSION_MAX)
            await self._run(self._store.extend_session, record.session_id, expires, now)
        return Principal(account.user_id, record.workspace_id, ALL_SCOPES, "session", account.email)

    async def authenticate_token(self, text: str) -> Principal | None:
        if not text.startswith(TOKEN_PREFIX):
            return None
        record = await self._run(self._store.live_token, token_hash(text))
        if record is None:
            return None
        user_id = email = None
        if record.owner_kind == "user":
            account = await self._run(self._store.account, record.owner_id)
            if account is None or account.disabled:
                return None
            user_id, email = account.user_id, account.email
        now = self._clock()
        if record.last_used_at is None or now - record.last_used_at >= TOUCH_EVERY:
            await self._run(self._store.touch_token, record.token_id, now)
        return Principal(user_id, record.workspace_id, SCOPE_SETS[record.scope], "token", email)

    async def note_service_key(self) -> None:
        await self._event("service_key", "ok")

    # --- developer tokens ------------------------------------------------------------------

    async def create_token(self, principal: Principal, request: CreateToken) -> CreatedToken:
        if principal.user_id is None:
            raise UserRequired()
        if not SCOPE_SETS[request.scope] <= principal.scopes:
            raise ScopeTooBroad()
        count = await self._run(self._store.active_token_count, "user", principal.user_id)
        if count >= TOKEN_LIMIT:
            raise TokenLimitReached()
        return await self._issue("user", principal.user_id, principal.workspace_id, request, principal.user_id)

    async def create_workspace_token(self, principal: Principal, request: CreateToken) -> CreatedToken:
        """External developer tokens. The route refuses this until the operator enables them."""
        if principal.user_id is None:
            raise UserRequired()
        account = await self._run(self._store.account, principal.user_id)
        if account is None or account.role not in ("owner", "admin") or not SCOPE_SETS[request.scope] <= principal.scopes:
            raise ScopeTooBroad()
        count = await self._run(self._store.active_token_count, "workspace", principal.workspace_id)
        if count >= TOKEN_LIMIT:
            raise TokenLimitReached()
        return await self._issue("workspace", principal.workspace_id, principal.workspace_id, request, principal.user_id)

    async def list_tokens(self, principal: Principal) -> list[TokenView]:
        if principal.user_id is None:
            raise UserRequired()
        records = await self._run(self._store.list_tokens, "user", principal.user_id)
        return [token_view(record) for record in records]

    async def revoke_token(self, principal: Principal, token_id: str) -> bool:
        if principal.user_id is None:
            raise UserRequired()
        revoked = await self._run(self._store.revoke_token, token_id, "user", principal.user_id)
        if revoked:
            await self._event("token_revoked", "ok", user_id=principal.user_id, token_id=token_id)
        return revoked

    # --- internals -------------------------------------------------------------------------

    async def _issue(
        self,
        owner_kind: str,
        owner_id: str,
        workspace_id: str,
        request: CreateToken,
        actor_user_id: str,
    ) -> CreatedToken:
        secret = random_token(TOKEN_PREFIX)
        now = self._clock()
        record = TokenRecord(
            token_id=f"tok_{uuid4().hex}",
            owner_kind=owner_kind,
            owner_id=owner_id,
            workspace_id=workspace_id,
            name=request.name.strip(),
            prefix=secret[: len(TOKEN_PREFIX) + 6],
            scope=request.scope,
            created_at=now,
            expires_at=now + timedelta(days=request.days),
            last_used_at=None,
        )
        await self._run(self._store.create_token, record, token_hash(secret))
        await self._event("token_created", "ok", user_id=actor_user_id, token_id=record.token_id)
        return CreatedToken(token=token_view(record), secret=secret)

    async def _start(self, account: AccountUser, *, trust_device: bool) -> SignedIn:
        now = self._clock()
        session_token = random_token()
        expires = now + SESSION_IDLE
        await self._run(
            self._store.create_session,
            account.user_id,
            account.workspace_id,
            token_hash(session_token),
            expires,
        )
        device = None
        if trust_device:
            device = random_token()
            await self._run(self._store.trust_device, account.user_id, token_hash(device), now + DEVICE_TTL)
        await self._event("sign_in", "ok", user_id=account.user_id)
        return SignedIn(session_token, expires, device)

    async def _send_code(self, account: AccountUser, *, enforce_cooldown: bool) -> CodeSent:
        assert self._mailer is not None and self._secret is not None  # begin() checked both
        now = self._clock()
        times = await self._run(self._store.challenge_times, account.user_id, now - timedelta(days=1))
        if len(times) >= DAILY_CODES:
            raise CodeLimited("daily_limit")
        if enforce_cooldown and times and now - times[-1] < RESEND_AFTER:
            raise CodeLimited("resend_too_soon")
        challenge_id = f"chl_{uuid4().hex}"
        code = new_code()
        challenge = random_token()
        await self._run(
            self._store.create_challenge,
            challenge_id,
            account.user_id,
            token_hash(challenge),
            code_hmac(self._secret, challenge_id, code),
            now + CODE_TTL,
        )
        body = (
            f"Your Thoth sign-in code is {code}.\n\n"
            "It expires in 10 minutes. If you did not try to sign in, ignore this email.\n"
        )
        try:
            await self._mailer.send(account.email, CODE_SUBJECT, body)
        except MailNotSent:
            await self._run(self._store.consume_challenge, challenge_id)
            await self._event("email_code", "failed", user_id=account.user_id, detail_code="code_not_sent")
            raise CodeNotSent() from None
        await self._event("email_code", "ok", user_id=account.user_id)
        return CodeSent(challenge)
```

`resend` runs `_send_code` with a mailer and secret only after `begin` succeeded once. Still,
`resend` must refuse with `SignInRefused("not_configured")` when either is missing: add the same
two-line guard at its top.

- [ ] **Step 4: Run the tests to verify they pass**

Run: `make test T="tests/auth"`
Expected: PASS (every `tests/auth` file so far).

- [ ] **Step 5: Lint and commit**

Run `make format` and then `make lint`. Expected: `All checks passed!`.

```bash
git add python/src/thoth_control_plane/auth/service.py python/tests/auth/test_sign_in_service.py
git commit -m "feat(auth): sign-in service for codes, sessions, devices and tokens"
```

---

### Task 8: Principals: sessions and tokens in the API, the data actor kept, and the wiring

**Files:**
- Modify: `python/src/thoth_control_plane/api/dependencies.py`, which replaces `current_actor`.
- Modify: `python/src/thoth_control_plane/api/app.py`: `create_app` gains `account_store`, `mailer`
  and `identity_providers`, plus `SessionMiddleware`.
- Test: `python/tests/api/test_auth_principal.py`

**Interfaces:**
- Consumes: `SignInService`, `AuthUnavailable` (Task 7); `AccountStore` (Tasks 3-4);
  `mailer_from` (Task 6); `build_providers` (Task 5); `Principal`, `ALL_SCOPES`,
  `BOOTSTRAP_WORKSPACE_ID` (Task 2).
- Produces:
  - **constants:** `SESSION_COOKIE = "thoth_session"`, `SAFE_METHODS`;
  - **functions:** `async resolve_principal(request, authorization) -> Principal | None`,
    `async current_principal(...) -> Principal` (403 `Not authorized` when absent),
    `require_write(request, principal) -> None`, and `async current_actor(...) -> Actor`;
  - **app state:** `app.state.sign_in: SignInService | None` and
    `app.state.auth_providers: dict[str, IdentityProvider]`;
  - **middleware:** Starlette `SessionMiddleware`, with cookie `thoth_oauth`, path `/auth` and
    600 s, installed only when `THOTH_AUTH_SECRET` is set.

- [ ] **Step 1: Write the failing tests**

`python/tests/api/test_auth_principal.py`:

```python
"""Sessions and developer tokens on the existing API; data stays the shared `owner`'s (spec 3.6)."""

from datetime import UTC, datetime, timedelta

import httpx
import pytest
from sqlalchemy import create_engine, func, select, text
from sqlalchemy.pool import StaticPool

from thoth_control_plane.api import create_app
from thoth_control_plane.auth.models import BOOTSTRAP_WORKSPACE_ID
from thoth_control_plane.auth.secrets import token_hash
from thoth_control_plane.config import Settings
from thoth_control_plane.infrastructure import account_models, run_models  # noqa: F401
from thoth_control_plane.infrastructure.account_models import AuthEventRow, WorkspaceRow
from thoth_control_plane.infrastructure.account_store import AccountStore, TokenRecord
from thoth_control_plane.infrastructure.project_store import ProjectStore
from thoth_control_plane.infrastructure.report_store import ReportStore
from thoth_control_plane.infrastructure.source_account_models import Base
from thoth_control_plane.infrastructure.workflow_run_store import WorkflowRunStore

ORIGIN = "http://localhost:8088"
SERVICE = {"Authorization": "Bearer test-key"}
REQUEST = {
    "source": {"url": "https://www.tiktok.com/@a/video/1", "intent": "identify_original"},
    "style": {"preset_id": "news-vertical"},
    "output": {"format": "vertical_video", "language": "id"},
    "review": {"require_publish_approval": True},
}


@pytest.fixture
def engine():
    engine = create_engine(
        "sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool
    )
    Base.metadata.create_all(engine)
    with engine.begin() as connection:
        connection.execute(
            WorkspaceRow.__table__.insert().values(
                workspace_id=BOOTSTRAP_WORKSPACE_ID, name="Thoth", created_at=datetime.now(UTC)
            )
        )
    return engine


@pytest.fixture
def accounts(engine) -> AccountStore:
    return AccountStore(engine)


@pytest.fixture
async def api(gateway, engine, accounts):
    app = create_app(
        Settings(THOTH_CONTROL_PLANE_API_KEY="test-key", THOTH_SITE_ORIGIN=ORIGIN),
        gateway,
        project_store=ProjectStore(engine),
        workflow_run_store=WorkflowRunStore(engine),
        report_store=ReportStore(engine),
        account_store=accounts,
    )
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        yield client


def session_for(accounts: AccountStore, email: str = "alice@acme.test") -> dict[str, str]:
    user = accounts.ensure_user(email, "Alice")
    accounts.create_session(
        user.user_id, user.workspace_id, token_hash("ses-" + email), datetime.now(UTC) + timedelta(hours=1)
    )
    return {"thoth_session": "ses-" + email}


def token_for(accounts: AccountStore, scope: str, *, days: int = 1, secret: str = "") -> dict[str, str]:
    user = accounts.ensure_user("alice@acme.test", "Alice")
    secret = secret or f"thoth_pat_{scope}"
    now = datetime.now(UTC)
    accounts.create_token(
        TokenRecord(
            f"tok_{scope}{days}", "user", user.user_id, user.workspace_id, scope,
            secret[:16], scope, now - timedelta(days=2), now + timedelta(days=days), None,
        ),
        token_hash(secret),
    )
    return {"Authorization": f"Bearer {secret}"}


async def test_a_session_reads_and_writes_only_from_its_own_origin(api, accounts) -> None:
    cookies = session_for(accounts)
    assert (await api.get("/api/v1/projects", cookies=cookies)).status_code == 200
    cross = await api.post("/api/v1/projects", json={"name": "News"}, cookies=cookies)
    assert (cross.status_code, cross.json()) == (403, {"detail": "cross_site_request"})
    foreign = await api.post(
        "/api/v1/projects", json={"name": "News"}, cookies=cookies,
        headers={"Origin": "https://evil.test"},
    )
    assert foreign.status_code == 403
    made = await api.post(
        "/api/v1/projects", json={"name": "News"}, cookies=cookies, headers={"Origin": ORIGIN}
    )
    assert made.status_code == 201


async def test_a_token_needs_write_to_mutate_and_no_origin(api, accounts) -> None:
    read = token_for(accounts, "read")
    assert (await api.get("/api/v1/projects", headers=read)).status_code == 200
    refused = await api.post("/api/v1/projects", json={"name": "News"}, headers=read)
    assert (refused.status_code, refused.json()) == (403, {"detail": "insufficient_scope"})
    write = token_for(accounts, "write")
    assert (await api.post("/api/v1/projects", json={"name": "News"}, headers=write)).status_code == 201


@pytest.mark.parametrize("case", ["unknown", "expired", "revoked"])
async def test_a_dead_token_is_not_authorized(api, accounts, case) -> None:
    if case == "unknown":
        headers = {"Authorization": "Bearer thoth_pat_unknown"}
    elif case == "expired":
        headers = token_for(accounts, "write", days=-1, secret="thoth_pat_expired")
    else:
        headers = token_for(accounts, "write", secret="thoth_pat_revoked")
        user = accounts.ensure_user("alice@acme.test", "Alice")
        assert accounts.revoke_token("tok_write1", "user", user.user_id)
    response = await api.get("/api/v1/projects", headers=headers)
    assert (response.status_code, response.json()) == (403, {"detail": "Not authorized"})


async def test_a_disabled_users_session_stops_working(api, accounts, engine) -> None:
    cookies = session_for(accounts)
    with engine.begin() as connection:
        connection.execute(text("UPDATE users SET disabled_at = CURRENT_TIMESTAMP"))
    assert (await api.get("/api/v1/projects", cookies=cookies)).status_code == 403


async def test_the_service_key_still_works_and_is_noted_at_most_once_a_minute(api, engine) -> None:
    for _ in range(3):
        assert (await api.get("/api/v1/projects", headers=SERVICE)).status_code == 200
    with engine.connect() as connection:
        noted = connection.scalar(
            select(func.count()).select_from(AuthEventRow).where(AuthEventRow.kind == "service_key")
        )
    assert noted == 1


async def test_everyone_signed_in_acts_on_the_same_owner_data(api, accounts) -> None:
    cookies = session_for(accounts)
    origin = {"Origin": ORIGIN}
    project = (await api.post("/api/v1/projects", json={"name": "News"}, cookies=cookies, headers=origin)).json()
    started = await api.post(
        f"/api/v1/projects/{project['project_id']}/workflows",
        json=REQUEST, cookies=cookies, headers={**origin, "Idempotency-Key": "k1"},
    )
    assert started.status_code in (200, 201, 202)
    workflow_id = started.json()["workflow_id"]
    by_service = await api.get(f"/api/v1/workflows/{workflow_id}", headers=SERVICE)
    assert by_service.status_code == 200
    by_other = await api.get(f"/api/v1/workflows/{workflow_id}", cookies=session_for(accounts, "bob@acme.test"))
    assert by_other.status_code == 200
```

`gateway` is the shared fixture in `tests/conftest.py`. If `POST .../workflows` needs another
header in this codebase, copy it from `tests/api/test_workflow_runs.py::start`.

- [ ] **Step 2: Run them to verify they fail**

Run: `make test T="tests/api/test_auth_principal.py"`
Expected: FAIL with `TypeError: create_app() got an unexpected keyword argument 'account_store'`.

- [ ] **Step 3: Rewrite `dependencies.py`**

Replace `current_actor` with the code below. Leave `internal_renderer` as it is.

```python
"""Shared authenticated API dependencies.

A caller is a session cookie, a developer token, or the legacy service key (spec 3.5-3.6). Every
principal still acts on the shared `owner` data until sub-project 2 scopes data by workspace.
"""

from __future__ import annotations

import time
from hmac import compare_digest
from typing import Annotated

from fastapi import Depends, Header, HTTPException, Request, status

from thoth_control_plane.auth.models import ALL_SCOPES, BOOTSTRAP_WORKSPACE_ID, Principal
from thoth_control_plane.auth.service import AuthUnavailable
from thoth_control_plane.domain import Actor

SESSION_COOKIE = "thoth_session"
SAFE_METHODS = frozenset({"GET", "HEAD", "OPTIONS"})
#: The legacy service key's use is recorded at most this often per API process.
SERVICE_KEY_NOTE_SECONDS = 60.0


def _forbidden(detail: str = "Not authorized") -> HTTPException:
    return HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail=detail)


async def _note_service_key(request: Request) -> None:
    state = request.app.state
    now = time.monotonic()
    last = getattr(state, "service_key_noted_at", None)
    if last is not None and now - last < SERVICE_KEY_NOTE_SECONDS:
        return
    state.service_key_noted_at = now
    sign_in = getattr(state, "sign_in", None)
    if sign_in is not None:
        await sign_in.note_service_key()


async def resolve_principal(request: Request, authorization: str | None) -> Principal | None:
    """The caller, or None. A present Authorization header never falls back to the cookie."""
    settings = request.app.state.settings
    sign_in = getattr(request.app.state, "sign_in", None)
    try:
        if authorization is not None:
            scheme, _, credential = authorization.partition(" ")
            if scheme.lower() != "bearer" or not credential:
                return None
            expected = settings.THOTH_CONTROL_PLANE_API_KEY.get_secret_value()
            if compare_digest(credential.encode("utf-8"), expected.encode("utf-8")):
                await _note_service_key(request)
                return Principal(None, BOOTSTRAP_WORKSPACE_ID, ALL_SCOPES, "service")
            return None if sign_in is None else await sign_in.authenticate_token(credential)
        cookie = request.cookies.get(SESSION_COOKIE)
        if cookie and sign_in is not None:
            return await sign_in.authenticate_session(cookie)
    except AuthUnavailable:
        raise HTTPException(status.HTTP_503_SERVICE_UNAVAILABLE, "auth_unavailable") from None
    return None


async def current_principal(
    request: Request,
    authorization: Annotated[str | None, Header(alias="Authorization")] = None,
) -> Principal:
    principal = await resolve_principal(request, authorization)
    if principal is None:
        raise _forbidden()
    return principal


def require_write(request: Request, principal: Principal) -> None:
    """Unsafe methods need the write scope; a cookie also needs the site's own Origin."""
    if request.method in SAFE_METHODS:
        return
    if "write" not in principal.scopes:
        raise _forbidden("insufficient_scope")
    site = request.app.state.settings.THOTH_SITE_ORIGIN
    if principal.via == "session" and request.headers.get("origin") != site:
        raise _forbidden("cross_site_request")


async def current_actor(
    request: Request, principal: Annotated[Principal, Depends(current_principal)]
) -> Actor:
    """The data actor: still the single `owner` (spec 3.6); the email is kept for audit."""
    require_write(request, principal)
    display = principal.email[:200] if principal.email else None
    return Actor(actor_id="owner", actor_type="user", display_name=display)
```

- [ ] **Step 4: Wire `create_app`**

In `api/app.py`:
- **Imports:** `from starlette.middleware.sessions import SessionMiddleware`, plus `AccountStore`,
  `SignInService`, `Mailer`, `mailer_from`, `IdentityProvider` and `build_providers`.
- **Parameters:** add `account_store: AccountStore | None = None`, `mailer: Mailer | None = None`
  and `identity_providers: dict[str, IdentityProvider] | None = None` after `workflow_run_store`.
- **Body:** add the block below next to the `workflow_run_store` construction.

```python
    if account_store is None and settings.THOTH_EDITOR_DATABASE_URL is not None:
        account_store = AccountStore.connect(settings.THOTH_EDITOR_DATABASE_URL.get_secret_value())
    auth_secret = (
        settings.THOTH_AUTH_SECRET.get_secret_value() if settings.THOTH_AUTH_SECRET else None
    )
    app.state.sign_in = (
        None
        if account_store is None
        else SignInService(account_store, mailer or mailer_from(settings), auth_secret)
    )
    app.state.auth_providers = (
        identity_providers if identity_providers is not None else build_providers(settings)
    )
    if auth_secret is not None:
        # Authlib keeps the OAuth state and PKCE verifier here, only on /auth, for 10 minutes.
        app.add_middleware(
            SessionMiddleware,
            secret_key=auth_secret,
            session_cookie="thoth_oauth",
            max_age=600,
            path="/auth",
            same_site="lax",
            https_only=settings.cookie_secure,
        )
```

- [ ] **Step 5: Run the new tests and the whole API suite**

Run: `make test T="tests/api tests/auth"`
Expected: PASS. All the existing 403 tests stay green, because the contract is unchanged.

- [ ] **Step 6: Commit**

```bash
git add python/src/thoth_control_plane/api/dependencies.py python/src/thoth_control_plane/api/app.py python/tests/api/test_auth_principal.py
git commit -m "feat(auth): accept sessions and developer tokens, keep the owner data actor"
```

---

### Task 9: The `/auth` routes (login, callback, verify, resend, logout, me)

**Files:**
- Create: `python/src/thoth_control_plane/api/routes/auth.py`
- Modify: `python/src/thoth_control_plane/auth/service.py`, adding `describe(principal) -> MeView`.
- Modify: `python/src/thoth_control_plane/api/app.py`, adding `app.include_router(auth_router)`
  without a prefix; the router carries `/auth`.
- Test: `python/tests/api/test_auth_routes.py`

**Interfaces:**
- Consumes: `resolve_principal`, `SESSION_COOKIE` and `require_write` (Task 8); `SignInService`,
  `SignedIn`, `CodeSent` and the errors (Task 7); `IdentityProvider` (Task 5).
- Produces:
  - **cookies:** `DEVICE_COOKIE = "thoth_device"`, `CHALLENGE_COOKIE = "thoth_challenge"`;
  - **`safe_next(value: str | None) -> str`**, which falls back to `/workflows`;
  - **routes, all outside OpenAPI:**
    - `GET /auth/providers` returns `{"providers": [...]}`;
    - `GET /auth/login/{provider}?next=`;
    - `GET /auth/callback/{provider}`;
    - `POST /auth/verify` takes `{code, trust_device=true, next}` and returns `{"next": path}`;
    - `POST /auth/resend` returns 204;
    - `POST /auth/logout` takes `{forget_device=false}` and returns 204;
    - `GET /auth/me` returns `MeView` or 401.

- [ ] **Step 1: Write the failing tests**

`python/tests/api/test_auth_routes.py`:

```python
"""The sign-in round trip with a fake provider and a fake mailer (spec section 2)."""

import re
from datetime import UTC, datetime

import httpx
import pytest
from sqlalchemy import create_engine
from sqlalchemy.pool import StaticPool
from starlette.responses import RedirectResponse

from thoth_control_plane.api import create_app
from thoth_control_plane.auth.models import BOOTSTRAP_WORKSPACE_ID, SignInRefused, VerifiedIdentity
from thoth_control_plane.config import Settings
from thoth_control_plane.infrastructure import account_models  # noqa: F401
from thoth_control_plane.infrastructure.account_models import WorkspaceRow
from thoth_control_plane.infrastructure.account_store import AccountStore
from thoth_control_plane.infrastructure.source_account_models import Base

ORIGIN = "http://localhost:8088"
SAME_SITE = {"Origin": ORIGIN}
ALICE = VerifiedIdentity("google", "g1", "alice@acme.test", "Alice")


class FakeProvider:
    name = "google"

    def __init__(self) -> None:
        self.identity_or_error: VerifiedIdentity | str = ALICE

    async def redirect(self, request, redirect_uri):
        request.session["started"] = True
        return RedirectResponse(f"https://idp.test/authorize?redirect_uri={redirect_uri}", 302)

    async def identity(self, request):
        if isinstance(self.identity_or_error, str):
            raise SignInRefused(self.identity_or_error)
        return self.identity_or_error


class FakeMailer:
    def __init__(self) -> None:
        self.bodies: list[str] = []

    async def send(self, to, subject, body):
        self.bodies.append(body)

    @property
    def code(self) -> str:
        return re.search(r"\b(\d{6})\b", self.bodies[-1]).group(1)


@pytest.fixture
def provider() -> FakeProvider:
    return FakeProvider()


@pytest.fixture
def mailer() -> FakeMailer:
    return FakeMailer()


@pytest.fixture
async def api(gateway, provider, mailer):
    engine = create_engine(
        "sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool
    )
    Base.metadata.create_all(engine)
    with engine.begin() as connection:
        connection.execute(
            WorkspaceRow.__table__.insert().values(
                workspace_id=BOOTSTRAP_WORKSPACE_ID, name="Thoth", created_at=datetime.now(UTC)
            )
        )
    settings = Settings(
        THOTH_CONTROL_PLANE_API_KEY="test-key", THOTH_SITE_ORIGIN=ORIGIN, THOTH_AUTH_SECRET="s" * 32
    )
    app = create_app(
        settings, gateway, account_store=AccountStore(engine), mailer=mailer,
        identity_providers={"google": provider},
    )
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url=ORIGIN) as client:
        yield client


async def callback(api) -> httpx.Response:
    await api.get("/auth/login/google?next=/studio")
    return await api.get("/auth/callback/google?code=c&state=s")


async def sign_in(api, mailer, *, trust=True) -> None:
    await callback(api)
    done = await api.post(
        "/auth/verify", json={"code": mailer.code, "trust_device": trust, "next": "/studio"},
        headers=SAME_SITE,
    )
    assert done.status_code == 200 and done.json() == {"next": "/studio"}


async def test_providers_lists_only_the_configured_ones(api) -> None:
    assert (await api.get("/auth/providers")).json() == {"providers": ["google"]}


async def test_an_unknown_provider_is_not_configured(api) -> None:
    response = await api.get("/auth/login/okta")
    assert (response.status_code, response.headers["location"]) == (303, "/login?error=not_configured")


async def test_a_refused_identity_returns_to_login_with_its_code(api, provider) -> None:
    provider.identity_or_error = "not_allowed"
    response = await callback(api)
    assert response.headers["location"] == "/login?error=not_allowed"
    assert "thoth_session" not in response.cookies


async def test_the_first_sign_in_asks_for_the_emailed_code(api, mailer) -> None:
    response = await callback(api)
    assert response.headers["location"] == "/login/verify?next=/studio"
    assert "thoth_challenge" in response.cookies and len(mailer.bodies) == 1
    assert (await api.get("/auth/me")).status_code == 401


async def test_the_code_signs_in_and_the_browser_is_then_trusted(api, mailer) -> None:
    await sign_in(api, mailer)
    me = (await api.get("/auth/me")).json()
    assert (me["email"], me["display_name"], me["workspace_id"]) == (
        "alice@acme.test", "Alice", BOOTSTRAP_WORKSPACE_ID,
    )
    api.cookies.delete("thoth_session")
    again = await callback(api)
    assert again.headers["location"] == "/studio" and len(mailer.bodies) == 1


async def test_a_wrong_code_a_cross_site_verify_and_a_missing_challenge_are_refused(api, mailer) -> None:
    await callback(api)
    wrong = "000000" if mailer.code != "000000" else "111111"
    bad = await api.post("/auth/verify", json={"code": wrong}, headers=SAME_SITE)
    assert (bad.status_code, bad.json()) == (400, {"detail": "wrong_code"})
    cross = await api.post("/auth/verify", json={"code": mailer.code})
    assert (cross.status_code, cross.json()) == (403, {"detail": "cross_site_request"})
    api.cookies.delete("thoth_challenge", path="/auth")
    gone = await api.post("/auth/verify", json={"code": mailer.code}, headers=SAME_SITE)
    assert (gone.status_code, gone.json()) == (400, {"detail": "expired"})


async def test_resend_is_throttled(api, mailer) -> None:
    await callback(api)
    response = await api.post("/auth/resend", headers=SAME_SITE)
    assert (response.status_code, response.json()) == (429, {"detail": "resend_too_soon"})


@pytest.mark.parametrize("target", ["//evil.test/x", "https://evil.test", "evil", "/\\evil.test"])
async def test_next_never_leaves_the_site(api, mailer, target) -> None:
    await api.get("/auth/login/google", params={"next": target})
    response = await api.get("/auth/callback/google?code=c&state=s")
    assert response.headers["location"] == "/login/verify?next=/workflows"


async def test_logout_ends_the_session_and_can_forget_the_browser(api, mailer) -> None:
    await sign_in(api, mailer)
    out = await api.post("/auth/logout", json={"forget_device": True}, headers=SAME_SITE)
    assert out.status_code == 204
    assert (await api.get("/auth/me")).status_code == 401
    await callback(api)
    assert len(mailer.bodies) == 2  # the browser is no longer trusted


async def test_me_accepts_a_developer_token_for_the_local_dashboard(api, mailer) -> None:
    response = await api.get("/auth/me", headers={"Authorization": "Bearer test-key"})
    assert response.status_code == 200 and response.json()["user_id"] is None
```

- [ ] **Step 2: Run them to verify they fail**

Run: `make test T="tests/api/test_auth_routes.py"`
Expected: FAIL. Every request to `/auth/...` answers 404.

- [ ] **Step 3: Add `describe` to the service**

In `auth/service.py`, add `MeView` to the models import and add this method under "who is
calling":

```python
    async def describe(self, principal: Principal) -> MeView:
        name = None
        if principal.user_id is not None:
            account = await self._run(self._store.account, principal.user_id)
            name = account.display_name if account else None
        return MeView(
            user_id=principal.user_id,
            email=principal.email,
            display_name=name,
            workspace_id=principal.workspace_id,
            scopes=sorted(principal.scopes),  # type: ignore[arg-type]
        )
```

- [ ] **Step 4: Implement the routes**

`python/src/thoth_control_plane/api/routes/auth.py`:

```python
"""Sign-in with Google or GitHub, then an emailed code (spec section 2). Not in OpenAPI.

Every refusal returns to /login with a fixed code; no provider or server text reaches the page.
"""

from __future__ import annotations

from typing import Annotated
from urllib.parse import quote

from fastapi import APIRouter, Header, Request, Response, status
from fastapi.responses import JSONResponse, RedirectResponse
from pydantic import Field

from thoth_control_plane.api.dependencies import SESSION_COOKIE, resolve_principal
from thoth_control_plane.auth.models import MeView, SignInRefused
from thoth_control_plane.auth.service import (
    DEVICE_TTL,
    SESSION_MAX,
    AuthUnavailable,
    CodeLimited,
    CodeNotSent,
    CodeRejected,
    SignedIn,
)
from thoth_control_plane.domain.models import StrictModel

router = APIRouter(prefix="/auth", include_in_schema=False)

DEVICE_COOKIE = "thoth_device"
CHALLENGE_COOKIE = "thoth_challenge"
NEXT_KEY = "thoth_next"
DEFAULT_NEXT = "/workflows"


class VerifyBody(StrictModel):
    code: Annotated[str, Field(min_length=6, max_length=12)]
    trust_device: bool = True
    next: Annotated[str, Field(max_length=2048)] | None = None


class LogoutBody(StrictModel):
    forget_device: bool = False


def safe_next(value: str | None) -> str:
    """Only a same-site absolute path; anything else becomes the Workflows page."""
    if not value or not value.startswith("/") or value.startswith("//") or "\\" in value:
        return DEFAULT_NEXT
    return value


def _to_login(code: str) -> RedirectResponse:
    return RedirectResponse(f"/login?error={code}", status_code=status.HTTP_303_SEE_OTHER)


def _same_site(request: Request) -> bool:
    return request.headers.get("origin") == request.app.state.settings.THOTH_SITE_ORIGIN


def _detail(code: str, status_code: int) -> JSONResponse:
    return JSONResponse({"detail": code}, status_code=status_code)


def _set_cookie(response: Response, request: Request, name: str, value: str, *, max_age: int, path: str) -> None:
    response.set_cookie(
        name, value, max_age=max_age, path=path, httponly=True, samesite="lax",
        secure=request.app.state.settings.cookie_secure,
    )


def _signed_in(response: Response, request: Request, done: SignedIn) -> None:
    _set_cookie(response, request, SESSION_COOKIE, done.session_token,
                max_age=int(SESSION_MAX.total_seconds()), path="/")
    if done.device_token is not None:
        _set_cookie(response, request, DEVICE_COOKIE, done.device_token,
                    max_age=int(DEVICE_TTL.total_seconds()), path="/auth")


@router.get("/providers")
async def providers(request: Request) -> dict[str, list[str]]:
    return {"providers": sorted(request.app.state.auth_providers)}


@router.get("/login/{provider}")
async def login(provider: str, request: Request, next: str | None = None) -> Response:
    found = request.app.state.auth_providers.get(provider)
    if found is None or request.app.state.sign_in is None:
        return _to_login("not_configured")
    request.session[NEXT_KEY] = safe_next(next)
    origin = request.app.state.settings.THOTH_SITE_ORIGIN.rstrip("/")
    return await found.redirect(request, f"{origin}/auth/callback/{provider}")


@router.get("/callback/{provider}")
async def callback(provider: str, request: Request) -> Response:
    found = request.app.state.auth_providers.get(provider)
    sign_in = request.app.state.sign_in
    target = safe_next(request.session.pop(NEXT_KEY, None) if "session" in request.scope else None)
    if found is None or sign_in is None:
        return _to_login("not_configured")
    try:
        identity = await found.identity(request)
        step = await sign_in.begin(identity, request.cookies.get(DEVICE_COOKIE))
    except SignInRefused as refused:
        return _to_login(refused.code)
    except CodeNotSent:
        return _to_login("code_not_sent")
    except AuthUnavailable:
        return _to_login("unavailable")
    if isinstance(step, SignedIn):
        response = RedirectResponse(target, status_code=status.HTTP_303_SEE_OTHER)
        _signed_in(response, request, step)
        return response
    response = RedirectResponse(
        f"/login/verify?next={quote(target, safe='/')}", status_code=status.HTTP_303_SEE_OTHER
    )
    _set_cookie(response, request, CHALLENGE_COOKIE, step.challenge_token, max_age=600, path="/auth")
    return response


@router.post("/verify")
async def verify(body: VerifyBody, request: Request) -> Response:
    if not _same_site(request):
        return _detail("cross_site_request", 403)
    sign_in = request.app.state.sign_in
    challenge = request.cookies.get(CHALLENGE_COOKIE)
    if sign_in is None:
        return _detail("not_configured", 503)
    if not challenge:
        return _detail("expired", 400)
    try:
        done = await sign_in.verify(
            challenge, body.code, trust_device=body.trust_device,
            previous_session=request.cookies.get(SESSION_COOKIE),
        )
    except CodeRejected as rejected:
        return _detail(rejected.code, 400)
    except SignInRefused as refused:
        return _detail(refused.code, 403)
    except AuthUnavailable:
        return _detail("unavailable", 503)
    response = JSONResponse({"next": safe_next(body.next)})
    _signed_in(response, request, done)
    response.delete_cookie(CHALLENGE_COOKIE, path="/auth")
    return response


@router.post("/resend")
async def resend(request: Request) -> Response:
    if not _same_site(request):
        return _detail("cross_site_request", 403)
    sign_in = request.app.state.sign_in
    challenge = request.cookies.get(CHALLENGE_COOKIE)
    if sign_in is None or not challenge:
        return _detail("expired", 400)
    try:
        sent = await sign_in.resend(challenge)
    except CodeRejected as rejected:
        return _detail(rejected.code, 400)
    except CodeLimited as limited:
        return _detail(limited.code, 429)
    except CodeNotSent:
        return _detail("code_not_sent", 503)
    except SignInRefused as refused:
        return _detail(refused.code, 403)
    except AuthUnavailable:
        return _detail("unavailable", 503)
    response = Response(status_code=status.HTTP_204_NO_CONTENT)
    _set_cookie(response, request, CHALLENGE_COOKIE, sent.challenge_token, max_age=600, path="/auth")
    return response


@router.post("/logout")
async def logout(body: LogoutBody, request: Request) -> Response:
    if not _same_site(request):
        return _detail("cross_site_request", 403)
    sign_in = request.app.state.sign_in
    if sign_in is not None:
        try:
            await sign_in.logout(
                request.cookies.get(SESSION_COOKIE), request.cookies.get(DEVICE_COOKIE),
                forget_device=body.forget_device,
            )
        except AuthUnavailable:
            return _detail("unavailable", 503)
    response = Response(status_code=status.HTTP_204_NO_CONTENT)
    response.delete_cookie(SESSION_COOKIE, path="/")
    if body.forget_device:
        response.delete_cookie(DEVICE_COOKIE, path="/auth")
    return response


@router.get("/me", response_model=MeView)
async def me(
    request: Request,
    authorization: Annotated[str | None, Header(alias="Authorization")] = None,
) -> Response | MeView:
    principal = await resolve_principal(request, authorization)
    if principal is None:
        return _detail("signed_out", 401)
    sign_in = request.app.state.sign_in
    if sign_in is None:
        return MeView(user_id=None, email=None, display_name=None,
                      workspace_id=principal.workspace_id, scopes=sorted(principal.scopes))  # type: ignore[arg-type]
    return await sign_in.describe(principal)
```

The failure codes `unavailable` (the account store is down) and `signed_out` (`/auth/me` only)
complete the Global Constraints lists. Add both to `docs/python-control-plane.md` in Task 15.

- [ ] **Step 5: Include the router, then run the tests to verify they pass**

In `app.py`, add `from thoth_control_plane.api.routes.auth import router as auth_router` and
`app.include_router(auth_router)` before `health_router`.

Run: `make test T="tests/api/test_auth_routes.py tests/api/test_auth_principal.py tests/auth"`
Expected: PASS.

- [ ] **Step 6: Commit**

```bash
git add python/src/thoth_control_plane/api/routes/auth.py python/src/thoth_control_plane/auth/service.py python/src/thoth_control_plane/api/app.py python/tests/api/test_auth_routes.py
git commit -m "feat(auth): sign-in routes with an emailed code and trusted browsers"
```

---

### Task 10: The account API, the bootstrap CLI, the contract pins and the generated types

**Files:**
- Create: `python/src/thoth_control_plane/api/routes/me.py`
- Modify: `python/src/thoth_control_plane/api/app.py`, adding `app.include_router(me_router,
  prefix="/api/v1")`.
- Modify: `python/src/thoth_control_plane/cli.py`, adding the `tokens create` command.
- Modify: `python/tests/api/test_workflows.py`
  (`test_openapi_exposes_exact_required_path_method_pairs`) and
  `python/tests/activities/test_legacy_scout.py` (the request schema names).
- Regenerate: `python/openapi.json` and `dashboard/src/api/generated/control-plane.ts`.
- Test: `python/tests/api/test_me_routes.py`, plus a new test in `python/tests/test_cli.py`.

**Interfaces:**
- Consumes: `current_principal`, `require_write` (Task 8); `SignInService.create_token`,
  `create_workspace_token`, `list_tokens`, `revoke_token` and `describe` (Tasks 7 and 9).
- Produces:
  - **routes:** `GET /api/v1/me`; `GET` and `POST /api/v1/me/tokens`;
    `DELETE /api/v1/me/tokens/{token_id}`; `POST /api/v1/workspace/tokens`;
  - **CLI:** `thoth-control tokens create --email --name [--scope write] [--days 90]`, which prints
    only the token.

- [ ] **Step 1: Write the failing tests**

`python/tests/api/test_me_routes.py`:

```python
"""The caller's account and personal developer tokens (spec 3.3)."""

from datetime import UTC, datetime, timedelta

import httpx
import pytest
from sqlalchemy import create_engine
from sqlalchemy.pool import StaticPool

from thoth_control_plane.api import create_app
from thoth_control_plane.auth.models import BOOTSTRAP_WORKSPACE_ID
from thoth_control_plane.auth.secrets import token_hash
from thoth_control_plane.config import Settings
from thoth_control_plane.infrastructure import account_models  # noqa: F401
from thoth_control_plane.infrastructure.account_models import WorkspaceRow
from thoth_control_plane.infrastructure.account_store import AccountStore
from thoth_control_plane.infrastructure.source_account_models import Base

ORIGIN = "http://localhost:8088"
SAME_SITE = {"Origin": ORIGIN}


def build(gateway, **settings):
    engine = create_engine(
        "sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool
    )
    Base.metadata.create_all(engine)
    with engine.begin() as connection:
        connection.execute(
            WorkspaceRow.__table__.insert().values(
                workspace_id=BOOTSTRAP_WORKSPACE_ID, name="Thoth", created_at=datetime.now(UTC)
            )
        )
    accounts = AccountStore(engine)
    user = accounts.ensure_user("alice@acme.test", "Alice")
    accounts.create_session(user.user_id, user.workspace_id, token_hash("ses"), datetime.now(UTC) + timedelta(hours=1))
    app = create_app(
        Settings(THOTH_CONTROL_PLANE_API_KEY="test-key", THOTH_SITE_ORIGIN=ORIGIN, **settings),
        gateway, account_store=accounts,
    )
    client = httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url=ORIGIN)
    client.cookies.set("thoth_session", "ses")
    return client


@pytest.fixture
async def api(gateway):
    async with build(gateway) as client:
        yield client


async def test_me_names_the_signed_in_user(api) -> None:
    me = (await api.get("/api/v1/me")).json()
    assert (me["email"], me["workspace_id"], me["scopes"]) == (
        "alice@acme.test", BOOTSTRAP_WORKSPACE_ID, ["admin", "read", "write"],
    )


async def test_a_token_is_shown_once_listed_without_secret_and_revoked(api) -> None:
    made = await api.post("/api/v1/me/tokens", json={"name": "laptop", "scope": "write", "days": 30}, headers=SAME_SITE)
    assert made.status_code == 201
    secret = made.json()["secret"]
    listed = (await api.get("/api/v1/me/tokens")).json()
    assert [t["name"] for t in listed] == ["laptop"] and "secret" not in listed[0]
    bearer = {"Authorization": f"Bearer {secret}"}
    assert (await api.get("/api/v1/projects", headers=bearer)).status_code == 200
    token_id = made.json()["token"]["token_id"]
    assert (await api.delete(f"/api/v1/me/tokens/{token_id}", headers=SAME_SITE)).status_code == 204
    assert (await api.get("/api/v1/projects", headers=bearer)).status_code == 403
    assert (await api.delete(f"/api/v1/me/tokens/{token_id}", headers=SAME_SITE)).status_code == 404


async def test_a_write_token_cannot_manage_tokens_and_the_service_key_has_no_user(api) -> None:
    made = (await api.post("/api/v1/me/tokens", json={"name": "ci"}, headers=SAME_SITE)).json()
    bearer = {"Authorization": f"Bearer {made['secret']}"}
    refused = await api.get("/api/v1/me/tokens", headers=bearer)
    assert (refused.status_code, refused.json()) == (403, {"detail": "insufficient_scope"})
    service = await api.get("/api/v1/me/tokens", headers={"Authorization": "Bearer test-key"})
    assert (service.status_code, service.json()) == (403, {"detail": "user_required"})


async def test_the_twenty_first_token_is_refused(api) -> None:
    for index in range(20):
        await api.post("/api/v1/me/tokens", json={"name": f"t{index}"}, headers=SAME_SITE)
    over = await api.post("/api/v1/me/tokens", json={"name": "more"}, headers=SAME_SITE)
    assert (over.status_code, over.json()) == (409, {"detail": "token_limit"})


async def test_workspace_tokens_are_refused_until_the_operator_enables_them(gateway) -> None:
    async with build(gateway) as off:
        refused = await off.post("/api/v1/workspace/tokens", json={"name": "partner"}, headers=SAME_SITE)
        assert (refused.status_code, refused.json()) == (403, {"detail": "workspace_tokens_disabled"})
    async with build(gateway, THOTH_AUTH_WORKSPACE_TOKENS=True) as on:
        made = await on.post("/api/v1/workspace/tokens", json={"name": "partner"}, headers=SAME_SITE)
        assert made.status_code == 201 and made.json()["token"]["owner_kind"] == "workspace"
```

Append to `python/tests/test_cli.py`:

```python
def test_tokens_create_prints_one_working_token_and_creates_the_user(monkeypatch) -> None:
    import asyncio
    from datetime import UTC, datetime

    from sqlalchemy import create_engine
    from sqlalchemy.pool import StaticPool
    from typer.testing import CliRunner

    from thoth_control_plane import cli
    from thoth_control_plane.auth.service import SignInService
    from thoth_control_plane.infrastructure import account_models  # noqa: F401
    from thoth_control_plane.infrastructure.account_models import WorkspaceRow
    from thoth_control_plane.infrastructure.account_store import AccountStore
    from thoth_control_plane.infrastructure.source_account_models import Base

    engine = create_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool)
    Base.metadata.create_all(engine)
    with engine.begin() as connection:
        connection.execute(WorkspaceRow.__table__.insert().values(
            workspace_id="ws_bootstrap", name="Thoth", created_at=datetime.now(UTC)))
    store = AccountStore(engine)
    monkeypatch.setenv("THOTH_CONTROL_PLANE_API_KEY", "k")
    monkeypatch.setenv("THOTH_EDITOR_DATABASE_URL", "postgresql://unused/db")
    monkeypatch.setattr(cli.AccountStore, "connect", classmethod(lambda cls, url: store))
    result = CliRunner().invoke(cli.app, ["tokens", "create", "--email", "Dev@Acme.test", "--name", "vite"])
    assert result.exit_code == 0, result.output
    secret = result.output.strip()
    assert secret.startswith("thoth_pat_") and "\n" not in secret
    principal = asyncio.run(SignInService(store, None, None).authenticate_token(secret))
    assert principal.email == "dev@acme.test" and principal.workspace_id == "ws_bootstrap"
    bad = CliRunner().invoke(cli.app, ["tokens", "create", "--email", "x@y", "--name", "n", "--scope", "root"])
    assert bad.exit_code == 1 and bad.output.strip() == "invalid_request"
```

Update the pins:
- **`test_openapi_exposes_exact_required_path_method_pairs`:** add `("/api/v1/me", "get")`,
  `("/api/v1/me/tokens", "get")`, `("/api/v1/me/tokens", "post")`,
  `("/api/v1/me/tokens/{token_id}", "delete")` and `("/api/v1/workspace/tokens", "post")`.
- **`test_no_fastapi_request_model_exposes_activity_mode`:** add `"CreateToken"` to the expected
  names. The `/auth` bodies are outside OpenAPI, so they do not appear.

- [ ] **Step 2: Run them to verify they fail**

Run: `make test T="tests/api/test_me_routes.py tests/test_cli.py tests/api/test_workflows.py tests/activities/test_legacy_scout.py"`
Expected: FAIL. The `/api/v1/me` routes answer 404, `cli.AccountStore` is missing, and the pins
differ.

- [ ] **Step 3: Implement the routes**

`python/src/thoth_control_plane/api/routes/me.py`:

```python
"""The caller's account and developer tokens (spec 3.3)."""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Request, Response, status

from thoth_control_plane.api.dependencies import current_principal, require_write
from thoth_control_plane.auth.models import CreatedToken, CreateToken, MeView, Principal, TokenView
from thoth_control_plane.auth.service import (
    AuthUnavailable,
    ScopeTooBroad,
    SignInService,
    TokenLimitReached,
    UserRequired,
)

router = APIRouter(tags=["account"])
Caller = Annotated[Principal, Depends(current_principal)]


def _service(request: Request) -> SignInService:
    service = request.app.state.sign_in
    if service is None:
        raise HTTPException(status.HTTP_503_SERVICE_UNAVAILABLE, "accounts_unavailable")
    return service


def _account_caller(request: Request, principal: Principal) -> SignInService:
    """Token management needs a user: a session, or a personal token with the admin scope."""
    require_write(request, principal)
    if principal.user_id is None:
        raise HTTPException(status.HTTP_403_FORBIDDEN, "user_required")
    if principal.via == "token" and "admin" not in principal.scopes:
        raise HTTPException(status.HTTP_403_FORBIDDEN, "insufficient_scope")
    return _service(request)


async def _issue(call) -> CreatedToken:  # noqa: ANN001 - an awaitable from the service
    try:
        return await call
    except UserRequired:
        raise HTTPException(status.HTTP_403_FORBIDDEN, "user_required") from None
    except ScopeTooBroad:
        raise HTTPException(status.HTTP_403_FORBIDDEN, "insufficient_scope") from None
    except TokenLimitReached:
        raise HTTPException(status.HTTP_409_CONFLICT, "token_limit") from None
    except AuthUnavailable:
        raise HTTPException(status.HTTP_503_SERVICE_UNAVAILABLE, "auth_unavailable") from None


@router.get("/me", response_model=MeView)
async def me(request: Request, principal: Caller) -> MeView:
    service = request.app.state.sign_in
    if service is None:
        return MeView(user_id=None, email=None, display_name=None,
                      workspace_id=principal.workspace_id, scopes=sorted(principal.scopes))  # type: ignore[arg-type]
    return await service.describe(principal)


@router.get("/me/tokens", response_model=list[TokenView])
async def list_tokens(request: Request, principal: Caller) -> list[TokenView]:
    return await _account_caller(request, principal).list_tokens(principal)


@router.post("/me/tokens", response_model=CreatedToken, status_code=status.HTTP_201_CREATED)
async def create_token(body: CreateToken, request: Request, principal: Caller) -> CreatedToken:
    return await _issue(_account_caller(request, principal).create_token(principal, body))


@router.delete("/me/tokens/{token_id}", status_code=status.HTTP_204_NO_CONTENT)
async def revoke_token(token_id: str, request: Request, principal: Caller) -> Response:
    if not await _account_caller(request, principal).revoke_token(principal, token_id):
        raise HTTPException(status.HTTP_404_NOT_FOUND, "token_not_found")
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.post("/workspace/tokens", response_model=CreatedToken, status_code=status.HTTP_201_CREATED)
async def create_workspace_token(body: CreateToken, request: Request, principal: Caller) -> CreatedToken:
    if not request.app.state.settings.THOTH_AUTH_WORKSPACE_TOKENS:
        raise HTTPException(status.HTTP_403_FORBIDDEN, "workspace_tokens_disabled")
    return await _issue(_account_caller(request, principal).create_workspace_token(principal, body))
```

In `app.py`, add `from thoth_control_plane.api.routes.me import router as me_router` and
`app.include_router(me_router, prefix="/api/v1")` after `project_router`.

- [ ] **Step 4: Implement the CLI command**

In `cli.py`:
- add the imports `from thoth_control_plane.infrastructure.account_store import AccountStore`,
  `from thoth_control_plane.auth.models import ALL_SCOPES, CreateToken, Principal` and
  `from thoth_control_plane.auth.service import SignInService`. Keep any heavier import inside the
  command, as `projects import` does.
- add, after the `projects` commands:

```python
tokens_app = typer.Typer(no_args_is_help=True)
app.add_typer(tokens_app, name="tokens")


@tokens_app.command("create")
def tokens_create(
    email: Annotated[str, typer.Option(help="The developer's email; the user is created if missing")],
    name: Annotated[str, typer.Option(help="What the token is for, e.g. vite or ci")],
    scope: Annotated[str, typer.Option(help="read, write or admin")] = "write",
    days: Annotated[int, typer.Option(help="Lifetime in days, 1 to 365")] = 90,
) -> None:
    """Create a personal developer token (spec 3.3). Prints the token once and nothing else."""
    from pydantic import ValidationError

    database_url = Settings().THOTH_EDITOR_DATABASE_URL
    if database_url is None:
        raise typer.BadParameter("THOTH_EDITOR_DATABASE_URL must be configured")
    address = email.strip().lower()
    try:
        request = CreateToken.model_validate({"name": name, "scope": scope, "days": days})
        if "@" not in address:
            raise ValueError("email")
    except (ValidationError, ValueError):
        typer.echo("invalid_request")
        raise typer.Exit(1) from None
    store = AccountStore.connect(database_url.get_secret_value())
    account = store.ensure_user(address, address.partition("@")[0])
    principal = Principal(account.user_id, account.workspace_id, ALL_SCOPES, "session", account.email)
    created = asyncio.run(SignInService(store, None, None).create_token(principal, request))
    typer.echo(created.secret)
```

- [ ] **Step 5: Run the tests, regenerate the contract, and check the drift**

Run: `make test T="tests/api tests/auth tests/test_cli.py tests/activities/test_legacy_scout.py"`
Expected: PASS.

Regenerate the contract:
1. In WSL from `python/`, run the export:
   `PYTHONPATH=$PWD/src $HOME/.local/bin/uv run --no-project --python 3.12 --with pydantic --with pydantic-settings --with typer --with httpx --with temporalio --with fastapi --with python-multipart --with "psycopg[binary]" --with sqlalchemy --with alembic --with "minio>=7.2.20,<8" --with agno --with "openai<3" --with cryptography --with "authlib>=1.6,<2" --with itsdangerous -- python scripts/export_openapi.py`
2. In `dashboard/`, run `bun run generate:control-plane-types`.

Expected:
- `git diff --stat` shows only additions: `/api/v1/me...` and the schemas `MeView`, `TokenView`,
  `CreateToken` and `CreatedToken`;
- no `/auth` path appears in `openapi.json`.

- [ ] **Step 6: Commit**

```bash
git add python/src/thoth_control_plane/api/routes/me.py python/src/thoth_control_plane/api/app.py python/src/thoth_control_plane/cli.py python/tests/api/test_me_routes.py python/tests/test_cli.py python/tests/api/test_workflows.py python/tests/activities/test_legacy_scout.py python/openapi.json dashboard/src/api/generated/control-plane.ts
git commit -m "feat(auth): account API, developer tokens and the bootstrap token CLI"
```

---

### Task 11: Dashboard sign-in: the auth client, the gate, and the login and verify pages

**Files:**
- Create: `dashboard/src/lib/auth-events.ts`
- Create: `dashboard/src/api/auth.ts`
- Create: `dashboard/src/features/auth/AuthGate.tsx`, `LoginPage.tsx` and `VerifyPage.tsx`
- Modify:
  - `dashboard/src/api/control-plane.ts` and `dashboard/src/api/source-accounts.ts`: no default
    key, and a 403 fires `forbidden`;
  - `dashboard/src/App.tsx`: the login routes sit outside the gate;
  - `dashboard/src/vite-env.d.ts`: drop `VITE_CONTROL_PLANE_API_KEY`.
- Test: `dashboard/src/features/auth/auth.test.tsx`; add one case to
  `dashboard/src/api/control-plane.test.ts`; update `dashboard/src/App.test.tsx`.

**Interfaces:**
- Consumes: `GET /auth/me`, `GET /auth/providers`, `POST /auth/verify`, `POST /auth/resend`
  (Task 9); the generated types `MeView`, `TokenView`, `CreateToken` and `CreatedToken` (Task 10).
- Produces:
  - **`lib/auth-events.ts`:** `authEvents: EventTarget` and `notifyForbidden(): void`;
  - **`api/auth.ts`:**
    - the types `Me`, `TokenView`, `CreateToken` and `CreatedToken`;
    - `class AuthRequestError(status, code)`;
    - `createAuthClient(fetch?)`, returning `{ me, providers, verify, resend, logout, listTokens,
      createToken, revokeToken }`;
    - the type `AuthClient` and the instance `authClient`;
  - **`AuthGate`:** `<AuthGate client?>{children}</AuthGate>`, plus `useAuth(): { me: Me;
    refresh(): Promise<void> }`;
  - **pages:** `LoginPage({ client? })` and `VerifyPage({ client?, onSignedIn? })`.

- [ ] **Step 1: Write the failing tests**

`dashboard/src/features/auth/auth.test.tsx`:

```tsx
/// <reference types="bun-types" />

import { afterEach, expect, mock, test } from "bun:test";
import { cleanup, render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { MemoryRouter, Route, Routes } from "react-router";

import { AuthRequestError } from "@/api/auth";
import { notifyForbidden } from "@/lib/auth-events";

import { AuthGate, useAuth } from "./AuthGate";
import { LoginPage } from "./LoginPage";
import { VerifyPage } from "./VerifyPage";

afterEach(cleanup);

const ME = { user_id: "usr_1", email: "alice@acme.test", display_name: "Alice", workspace_id: "ws_bootstrap", scopes: ["admin", "read", "write"] };

function Who() {
  return <p>{`signed in as ${useAuth().me.email}`}</p>;
}

function gate(me: () => Promise<typeof ME | null>, path = "/studio") {
  return render(
    <MemoryRouter initialEntries={[path]}>
      <Routes>
        <Route path="/login" element={<p>login page</p>} />
        <Route path="*" element={<AuthGate client={{ me: mock(me) }}><Who /></AuthGate>} />
      </Routes>
    </MemoryRouter>,
  );
}

test("a signed-in person sees the app", async () => {
  gate(async () => ME);
  expect(await screen.findByText("signed in as alice@acme.test")).toBeDefined();
});

test("nobody signed in goes to the login page", async () => {
  gate(async () => null);
  expect(await screen.findByText("login page")).toBeDefined();
});

test("a 403 from any API call re-checks the session and signs out when it ended", async () => {
  let current: typeof ME | null = ME;
  gate(async () => current);
  await screen.findByText("signed in as alice@acme.test");
  current = null;
  notifyForbidden();
  expect(await screen.findByText("login page")).toBeDefined();
});

test("an unreachable control plane offers a retry instead of the login page", async () => {
  let calls = 0;
  gate(async () => {
    calls += 1;
    if (calls === 1) throw new AuthRequestError(503, null);
    return ME;
  });
  await userEvent.setup().click(await screen.findByRole("button", { name: "Try again" }));
  expect(await screen.findByText("signed in as alice@acme.test")).toBeDefined();
});

test("the login page offers the configured providers and carries next", async () => {
  render(
    <MemoryRouter initialEntries={["/login?next=%2Fstudio%2Fp%2Fd&error=not_allowed"]}>
      <LoginPage client={{ providers: mock(async () => ["github", "google"]) }} />
    </MemoryRouter>,
  );
  expect(await screen.findByText("This account is not allowed to sign in to this workspace.")).toBeDefined();
  const google = await screen.findByRole("link", { name: "Continue with Google" });
  expect(google.getAttribute("href")).toBe("/auth/login/google?next=%2Fstudio%2Fp%2Fd");
  expect(screen.getByRole("link", { name: "Continue with GitHub" })).toBeDefined();
});

test("with no provider configured the login page says so", async () => {
  render(<MemoryRouter initialEntries={["/login"]}><LoginPage client={{ providers: mock(async () => []) }} /></MemoryRouter>);
  expect(await screen.findByText("Sign-in is not configured on this server.")).toBeDefined();
});

test("the verify page signs in with the code and reports a wrong one", async () => {
  const verify = mock(async (code: string) => {
    if (code === "000000") throw new AuthRequestError(400, "wrong_code");
    return "/studio";
  });
  const onSignedIn = mock((_target: string) => {});
  render(
    <MemoryRouter initialEntries={["/login/verify?next=%2Fstudio"]}>
      <VerifyPage client={{ verify, resend: mock(async () => {}) }} onSignedIn={onSignedIn} />
    </MemoryRouter>,
  );
  const user = userEvent.setup();
  const input = screen.getByLabelText("Code from your email");
  expect(input.getAttribute("autocomplete")).toBe("one-time-code");
  await user.type(input, "000000");
  await user.click(screen.getByRole("button", { name: "Continue" }));
  expect(await screen.findByText("That code is not right. Check the email and try again.")).toBeDefined();
  await user.clear(input);
  await user.type(input, "123456");
  await user.click(screen.getByRole("button", { name: "Continue" }));
  await waitFor(() => expect(onSignedIn).toHaveBeenCalledWith("/studio"));
  expect(verify).toHaveBeenLastCalledWith("123456", true, "/studio");
  expect((screen.getByRole("button", { name: /Resend in/ }) as HTMLButtonElement).disabled).toBe(true);
});
```

Append to `dashboard/src/api/control-plane.test.ts`:

```ts
test("the default client sends no API key and a 403 raises the forbidden event", async () => {
  const { authEvents } = await import("@/lib/auth-events");
  let forbidden = 0;
  const onForbidden = () => { forbidden += 1; };
  authEvents.addEventListener("forbidden", onForbidden);
  const fetchMock = mock(async () => new Response(JSON.stringify({ detail: "Not authorized" }), { status: 403 }));
  const client = createControlPlaneClient({ baseUrl: "", fetch: fetchMock as unknown as typeof fetch });
  await expect(client.listProjects()).rejects.toThrow();
  const init = (fetchMock.mock.calls[0] as unknown as [string, RequestInit])[1];
  expect(new Headers(init.headers).has("Authorization")).toBe(false);
  expect(forbidden).toBe(1);
  authEvents.removeEventListener("forbidden", onForbidden);
});
```

In `dashboard/src/App.test.tsx`:
- add `if (path === "/auth/me") return response({ user_id: "usr_1", email: "alice@acme.test", display_name: "Alice", workspace_id: "ws_bootstrap", scopes: ["admin", "read", "write"] });`
  as the first line inside `stubFetch`'s mock;
- in the test "no page reaches the retired Rust server", replace the filter with
  `requested.filter((path) => !path.startsWith("/api/v1/") && path !== "/auth/me")`;
- append:

```tsx
test("signed out, every page goes to the login page with next", async () => {
  stubFetch();
  const signedOut = globalThis.fetch;
  globalThis.fetch = mock(async (input: RequestInfo | URL, init?: RequestInit) =>
    String(input) === "/auth/me" ? new Response("{}", { status: 401 })
      : String(input) === "/auth/providers" ? response({ providers: ["google"] })
      : (signedOut as typeof fetch)(input, init),
  ) as unknown as typeof fetch;
  window.history.replaceState(null, "", "/studio");
  const { default: App } = await import("./App");
  render(<App />);
  expect(await screen.findByRole("link", { name: "Continue with Google" })).toBeDefined();
  expect(window.location.pathname + window.location.search).toBe("/login?next=%2Fstudio");
});
```

- [ ] **Step 2: Run them to verify they fail**

Run: `cd dashboard && bun test src/features/auth src/api/control-plane.test.ts src/App.test.tsx`
Expected: FAIL. The module `@/api/auth` is missing, and the default client still sends
`Authorization: Bearer `.

- [ ] **Step 3: Implement the events, the client changes and the auth client**

`dashboard/src/lib/auth-events.ts`:

```ts
/** API clients raise `forbidden` on a 403 so the auth gate re-checks whether anyone is signed in. */
export const authEvents = new EventTarget();

export function notifyForbidden(): void {
  authEvents.dispatchEvent(new Event("forbidden"));
}
```

In `dashboard/src/api/control-plane.ts`:
- delete `const defaultApiKey = import.meta.env.VITE_CONTROL_PLANE_API_KEY ?? "";`;
- in `createControlPlaneClient` replace the `apiKey`, `doFetch` and `headers` lines with the block
  below;
- import `notifyForbidden` from `@/lib/auth-events`.

The `apiKey` option stays for non-browser callers and the existing tests.

```ts
  // The browser authenticates with its same-site session cookie; it never holds a key (spec 3.6).
  const apiKey = options.apiKey ?? "";
  const rawFetch = options.fetch ?? fetch;
  const doFetch: typeof fetch = async (input, init) => {
    const response = await rawFetch(input, init);
    if (response.status === 403) notifyForbidden();
    return response;
  };
  const headers = (extra: HeadersInit = {}) =>
    apiKey ? { Authorization: `Bearer ${apiKey}`, ...extra } : { ...extra };
```

In `dashboard/src/api/source-accounts.ts`:
- replace the `apiKey` line with `const apiKey = options.apiKey ?? "";`;
- spread `...(apiKey ? { Authorization: \`Bearer ${apiKey}\` } : {})` in place of the fixed
  `Authorization` entry;
- right after `response = await doFetch(...)` succeeds, add
  `if (response.status === 403) notifyForbidden();`.

In `dashboard/src/vite-env.d.ts`, delete the line
`readonly VITE_CONTROL_PLANE_API_KEY?: string;`.

`dashboard/src/api/auth.ts`:

```ts
// Sign-in and developer tokens (spec 2026-10-19). /auth is not in OpenAPI; /api/v1/me is.
import type { components } from "@/api/generated/control-plane";

export type Me = components["schemas"]["MeView"];
export type TokenView = components["schemas"]["TokenView"];
export type CreateToken = components["schemas"]["CreateToken"];
export type CreatedToken = components["schemas"]["CreatedToken"];

export class AuthRequestError extends Error {
  constructor(
    readonly status: number,
    readonly code: string | null,
  ) {
    super(code ?? `auth_request_failed_${status}`);
  }
}

async function failure(response: Response): Promise<AuthRequestError> {
  const body = (await response.json().catch(() => null)) as { detail?: unknown } | null;
  return new AuthRequestError(response.status, typeof body?.detail === "string" ? body.detail : null);
}

const JSON_BODY = { "Content-Type": "application/json" };

export function createAuthClient(doFetch: typeof fetch = (input, init) => fetch(input, init)) {
  async function send(path: string, init: RequestInit = {}): Promise<Response> {
    const response = await doFetch(path, init);
    if (!response.ok) throw await failure(response);
    return response;
  }
  return {
    async me(): Promise<Me | null> {
      const response = await doFetch("/auth/me");
      if (response.status === 401) return null;
      if (!response.ok) throw await failure(response);
      return (await response.json()) as Me;
    },
    async providers(): Promise<string[]> {
      const response = await doFetch("/auth/providers");
      if (!response.ok) return [];
      return ((await response.json()) as { providers: string[] }).providers;
    },
    async verify(code: string, trustDevice: boolean, next: string): Promise<string> {
      const response = await send("/auth/verify", {
        method: "POST", headers: JSON_BODY, body: JSON.stringify({ code, trust_device: trustDevice, next }),
      });
      return ((await response.json()) as { next: string }).next;
    },
    async resend(): Promise<void> {
      await send("/auth/resend", { method: "POST" });
    },
    async logout(forgetDevice: boolean): Promise<void> {
      await send("/auth/logout", { method: "POST", headers: JSON_BODY, body: JSON.stringify({ forget_device: forgetDevice }) });
    },
    async listTokens(): Promise<TokenView[]> {
      return (await (await send("/api/v1/me/tokens")).json()) as TokenView[];
    },
    async createToken(request: CreateToken): Promise<CreatedToken> {
      const response = await send("/api/v1/me/tokens", { method: "POST", headers: JSON_BODY, body: JSON.stringify(request) });
      return (await response.json()) as CreatedToken;
    },
    async revokeToken(tokenId: string): Promise<void> {
      await send(`/api/v1/me/tokens/${encodeURIComponent(tokenId)}`, { method: "DELETE" });
    },
  };
}

export type AuthClient = ReturnType<typeof createAuthClient>;
export const authClient = createAuthClient();
```

- [ ] **Step 4: Implement the gate and the pages**

`dashboard/src/features/auth/AuthGate.tsx`:

```tsx
import { createContext, useCallback, useContext, useEffect, useState, type ReactNode } from "react";
import { Navigate, useLocation } from "react-router";

import { authClient, type AuthClient, type Me } from "@/api/auth";
import { authEvents } from "@/lib/auth-events";

type AuthState = { me: Me; refresh: () => Promise<void> };
const AuthContext = createContext<AuthState | null>(null);

export function useAuth(): AuthState {
  const state = useContext(AuthContext);
  if (!state) throw new Error("useAuth must be used inside <AuthGate>");
  return state;
}

/** Renders its children only for a signed-in caller; a session that ends sends them to /login. */
export function AuthGate({ client = authClient, children }: { client?: Pick<AuthClient, "me">; children: ReactNode }) {
  const location = useLocation();
  const [state, setState] = useState<"loading" | "signed_out" | "unreachable" | Me>("loading");
  const check = useCallback(async () => {
    try {
      setState((await client.me()) ?? "signed_out");
    } catch {
      setState("unreachable");
    }
  }, [client]);

  useEffect(() => {
    void check();
  }, [check]);
  useEffect(() => {
    const recheck = () => void check();
    authEvents.addEventListener("forbidden", recheck);
    return () => authEvents.removeEventListener("forbidden", recheck);
  }, [check]);

  if (state === "loading") return <p role="status" className="dashboard-auth-status">Checking your session…</p>;
  if (state === "unreachable") {
    return (
      <div role="alert" className="dashboard-auth-status">
        <p>The control plane could not be reached.</p>
        <button type="button" onClick={() => void check()}>Try again</button>
      </div>
    );
  }
  if (state === "signed_out") {
    return <Navigate to={`/login?next=${encodeURIComponent(location.pathname + location.search)}`} replace />;
  }
  return <AuthContext.Provider value={{ me: state, refresh: check }}>{children}</AuthContext.Provider>;
}
```

`dashboard/src/features/auth/LoginPage.tsx`:

```tsx
import { useEffect, useState } from "react";
import { useSearchParams } from "react-router";
import { Feather } from "lucide-react";

import { authClient, type AuthClient } from "@/api/auth";
import { buttonVariants } from "@/components/ui/button";

export const SIGN_IN_ERRORS: Record<string, string> = {
  unverified_email: "Your provider has not verified this email address.",
  not_allowed: "This account is not allowed to sign in to this workspace.",
  provider_error: "Sign-in did not complete. Try again.",
  not_configured: "Sign-in is not configured on this server.",
  too_many_codes: "Too many codes were sent today. Try again tomorrow.",
  code_not_sent: "The sign-in code could not be sent. Try again.",
  unavailable: "Sign-in is unavailable right now. Try again shortly.",
};
const LABELS: Record<string, string> = { google: "Continue with Google", github: "Continue with GitHub" };

export function LoginPage({ client = authClient }: { client?: Pick<AuthClient, "providers"> }) {
  const [params] = useSearchParams();
  const next = params.get("next") ?? "/workflows";
  const error = params.get("error");
  const [providers, setProviders] = useState<string[] | null>(null);
  useEffect(() => {
    client.providers().then(setProviders, () => setProviders([]));
  }, [client]);
  return (
    <main className="dashboard-login">
      <div className="dashboard-login-card">
        <p className="dashboard-brand"><Feather aria-hidden="true" /><span>Thoth</span></p>
        <h1>Sign in</h1>
        {error && <p role="alert">{SIGN_IN_ERRORS[error] ?? SIGN_IN_ERRORS.provider_error}</p>}
        {providers === null ? (
          <p role="status">Loading…</p>
        ) : providers.length === 0 ? (
          <p>{SIGN_IN_ERRORS.not_configured}</p>
        ) : (
          providers.map((provider) => (
            <a key={provider} className={buttonVariants({ variant: "outline" })} href={`/auth/login/${provider}?next=${encodeURIComponent(next)}`}>
              {LABELS[provider] ?? provider}
            </a>
          ))
        )}
        <p className="dashboard-login-note">After signing in we email you a one-time code.</p>
      </div>
    </main>
  );
}
```

`dashboard/src/features/auth/VerifyPage.tsx`:

```tsx
import { useEffect, useState, type FormEvent } from "react";
import { Link, useSearchParams } from "react-router";

import { authClient, AuthRequestError, type AuthClient } from "@/api/auth";
import { Button } from "@/components/ui/button";

import { SIGN_IN_ERRORS } from "./LoginPage";

const CODE_ERRORS: Record<string, string> = {
  wrong_code: "That code is not right. Check the email and try again.",
  expired: "This code has expired. Sign in again to get a new one.",
  too_many_attempts: "Too many wrong codes. Sign in again to get a new one.",
  resend_too_soon: "Wait a minute before asking for another code.",
  daily_limit: SIGN_IN_ERRORS.too_many_codes,
  code_not_sent: SIGN_IN_ERRORS.code_not_sent,
  cross_site_request: "Open this page from the Thoth site to continue.",
  unavailable: SIGN_IN_ERRORS.unavailable,
};
const RESEND_SECONDS = 60;

export function VerifyPage({
  client = authClient,
  onSignedIn = (target: string) => window.location.assign(target),
}: {
  client?: Pick<AuthClient, "verify" | "resend">;
  onSignedIn?: (target: string) => void;
}) {
  const [params] = useSearchParams();
  const next = params.get("next") ?? "/workflows";
  const [code, setCode] = useState("");
  const [trust, setTrust] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [notice, setNotice] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const [wait, setWait] = useState(RESEND_SECONDS);

  useEffect(() => {
    if (wait <= 0) return;
    const timer = setTimeout(() => setWait((seconds) => seconds - 1), 1000);
    return () => clearTimeout(timer);
  }, [wait]);

  const codeOf = (failure: unknown) => (failure instanceof AuthRequestError && failure.code ? failure.code : "unavailable");

  async function submit(event: FormEvent) {
    event.preventDefault();
    setBusy(true);
    setError(null);
    try {
      onSignedIn(await client.verify(code, trust, next));
    } catch (failure) {
      setError(codeOf(failure));
    } finally {
      setBusy(false);
    }
  }

  async function resend() {
    setError(null);
    try {
      await client.resend();
      setWait(RESEND_SECONDS);
      setNotice("A new code is on its way.");
    } catch (failure) {
      setError(codeOf(failure));
    }
  }

  const dead = error === "expired" || error === "too_many_attempts";
  return (
    <main className="dashboard-login">
      <form className="dashboard-login-card" onSubmit={(event) => void submit(event)}>
        <h1>Check your email</h1>
        <p>We sent a 6-digit code to the address your provider verified.</p>
        <label htmlFor="sign-in-code">Code from your email</label>
        <input
          id="sign-in-code"
          inputMode="numeric"
          autoComplete="one-time-code"
          pattern="[0-9]{6}"
          maxLength={6}
          value={code}
          onChange={(event) => setCode(event.target.value.replace(/\D/g, ""))}
          aria-describedby={error ? "sign-in-error" : undefined}
        />
        <label className="dashboard-login-trust">
          <input type="checkbox" checked={trust} onChange={(event) => setTrust(event.target.checked)} />
          Trust this browser for 30 days
        </label>
        {error && <p id="sign-in-error" role="alert">{CODE_ERRORS[error] ?? CODE_ERRORS.unavailable}</p>}
        {notice && !error && <p role="status">{notice}</p>}
        {dead ? (
          <Link to={`/login?next=${encodeURIComponent(next)}`}>Back to sign in</Link>
        ) : (
          <Button type="submit" disabled={busy || code.length !== 6}>Continue</Button>
        )}
        <Button type="button" variant="outline" disabled={wait > 0 || dead} onClick={() => void resend()}>
          {wait > 0 ? `Resend in ${wait}s` : "Resend code"}
        </Button>
      </form>
    </main>
  );
}
```

In `dashboard/src/App.tsx`:
- import `AuthGate`, `LoginPage` and `VerifyPage`;
- replace the `App` body with:

```tsx
export default function App() {
  return (
    <BrowserRouter>
      <Routes>
        <Route path="/login" element={<LoginPage />} />
        <Route path="/login/verify" element={<VerifyPage />} />
        <Route path="*" element={<AuthGate><Shell /></AuthGate>} />
      </Routes>
    </BrowserRouter>
  );
}
```

Add these styles to `dashboard/src/dashboard.css`:

```css
.dashboard-login { min-height: 100dvh; display: grid; place-items: center; padding: 16px; background: var(--background); }
.dashboard-login-card { width: min(100%, 380px); display: grid; gap: 14px; padding: 28px; border-radius: 8px; background: var(--card); }
.dashboard-login-card h1 { font-size: 22px; font-weight: 600; }
.dashboard-login-card input#sign-in-code { height: 44px; font: 600 22px var(--font-mono); letter-spacing: .3em; text-align: center; border-radius: 6px; background: var(--background); }
.dashboard-login-trust { display: flex; align-items: center; gap: 8px; font-size: 13px; }
.dashboard-login-note, .dashboard-auth-status { font-size: 12px; color: var(--muted-foreground); }
.dashboard-auth-status { padding: 24px; }
```

- [ ] **Step 5: Run the tests and the type check**

Run: `cd dashboard && bun test && bunx tsc --noEmit -p tsconfig.app.json`
Expected: every test passes; `tsc` prints nothing.

- [ ] **Step 6: Commit**

```bash
git add dashboard/src/lib/auth-events.ts dashboard/src/api/auth.ts dashboard/src/features/auth dashboard/src/api/control-plane.ts dashboard/src/api/source-accounts.ts dashboard/src/api/control-plane.test.ts dashboard/src/App.tsx dashboard/src/App.test.tsx dashboard/src/vite-env.d.ts dashboard/src/dashboard.css
git commit -m "feat(dashboard): sign in with a provider and an emailed code; no bundled key"
```

---

### Task 12: Dashboard: the user menu and the Developer tokens page

**Files:**
- Create: `dashboard/src/features/settings/TokensPage.tsx` and `TokensPage.test.tsx`
- Create: `dashboard/src/lib/initials.ts`
- Modify:
  - `dashboard/src/components/WorkspaceMenu.tsx`;
  - `dashboard/src/App.tsx`: the `/settings/tokens` page and the menu wiring.
- Test: `dashboard/src/components/WorkspaceMenu.test.tsx` (new).

**Interfaces:**
- Consumes: `useAuth` (Task 11); `AuthClient.listTokens`, `createToken`, `revokeToken` and
  `logout` (Task 11).
- Produces:
  - `TokensPage({ client? })`;
  - `WorkspaceMenu({ me, onHelp, onTokens, onSignOut(forget: boolean) })`;
  - `initials(me: Pick<Me, "display_name" | "email">): string`.

- [ ] **Step 1: Write the failing tests**

`dashboard/src/features/settings/TokensPage.test.tsx`:

```tsx
/// <reference types="bun-types" />

import { afterEach, expect, mock, test } from "bun:test";
import { cleanup, render, screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";

import { AuthRequestError, type TokenView } from "@/api/auth";

import { TokensPage } from "./TokensPage";

afterEach(cleanup);

const token = (name: string): TokenView => ({
  token_id: `tok_${name}`, owner_kind: "user", name, prefix: "thoth_pat_ab12cd", scope: "write",
  created_at: "2026-10-19T00:00:00Z", expires_at: "2027-01-17T00:00:00Z", last_used_at: null,
});

function client(listed: TokenView[] = [token("laptop")]) {
  return {
    listTokens: mock(async () => listed),
    createToken: mock(async () => ({ token: token("ci"), secret: "thoth_pat_secretvalue" })),
    revokeToken: mock(async () => {}),
  };
}

test("lists tokens without secrets", async () => {
  render(<TokensPage client={client()} />);
  const row = (await screen.findByText("laptop")).closest("tr")!;
  expect(within(row).getByText("thoth_pat_ab12cd…")).toBeDefined();
  expect(within(row).getByText("Never")).toBeDefined();
});

test("a new token is shown once with what it can do", async () => {
  const c = client([]);
  render(<TokensPage client={c} />);
  const user = userEvent.setup();
  await user.type(await screen.findByLabelText("Token name"), "ci");
  await user.selectOptions(screen.getByLabelText("Access"), "read");
  await user.click(screen.getByRole("button", { name: "Create token" }));
  expect(c.createToken).toHaveBeenCalledWith({ name: "ci", scope: "read", days: 90 });
  expect(((await screen.findByLabelText("New token")) as HTMLInputElement).value).toBe("thoth_pat_secretvalue");
  expect(screen.getByText("Copy it now. It is not shown again.")).toBeDefined();
});

test("revoking asks first", async () => {
  const c = client();
  render(<TokensPage client={c} />);
  const user = userEvent.setup();
  await user.click(await screen.findByRole("button", { name: "Revoke laptop" }));
  expect(c.revokeToken).not.toHaveBeenCalled();
  await user.click(screen.getByRole("button", { name: "Confirm revoke laptop" }));
  expect(c.revokeToken).toHaveBeenCalledWith("tok_laptop");
});

test("the limit and a missing account are explained", async () => {
  const c = client([]);
  c.createToken.mockImplementation(async () => { throw new AuthRequestError(409, "token_limit"); });
  render(<TokensPage client={c} />);
  const user = userEvent.setup();
  await user.type(await screen.findByLabelText("Token name"), "x");
  await user.click(screen.getByRole("button", { name: "Create token" }));
  expect(await screen.findByText("You have 20 active tokens. Revoke one to create another.")).toBeDefined();
  cleanup();
  const service = client();
  service.listTokens.mockImplementation(async () => { throw new AuthRequestError(403, "user_required"); });
  render(<TokensPage client={service} />);
  expect(await screen.findByText("Developer tokens belong to a signed-in account.")).toBeDefined();
});
```

`dashboard/src/components/WorkspaceMenu.test.tsx`:

```tsx
/// <reference types="bun-types" />

import { afterEach, expect, mock, test } from "bun:test";
import { cleanup, render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";

import { WorkspaceMenu } from "./WorkspaceMenu";

afterEach(cleanup);

const ME = { user_id: "usr_1", email: "alice.walker@acme.test", display_name: "Alice Walker", workspace_id: "ws_bootstrap", scopes: ["admin", "read", "write"] };

test("the menu names the signed-in person and signs out", async () => {
  const onSignOut = mock((_forget: boolean) => {});
  const onTokens = mock(() => {});
  render(<WorkspaceMenu me={ME} onHelp={() => {}} onTokens={onTokens} onSignOut={onSignOut} />);
  const user = userEvent.setup();
  await user.click(screen.getByRole("button", { name: "Workspace menu" }));
  expect(screen.getAllByText("AW").length).toBeGreaterThan(0);
  expect(screen.getByText("alice.walker@acme.test")).toBeDefined();
  await user.click(screen.getByRole("button", { name: /Developer tokens/ }));
  expect(onTokens).toHaveBeenCalled();
  await user.click(screen.getByRole("button", { name: "Workspace menu" }));
  await user.click(screen.getByRole("button", { name: "Sign out and forget this browser" }));
  expect(onSignOut).toHaveBeenCalledWith(true);
});
```

- [ ] **Step 2: Run them to verify they fail**

Run: `cd dashboard && bun test src/features/settings src/components/WorkspaceMenu.test.tsx`
Expected: FAIL. `./TokensPage` is missing, and `WorkspaceMenu` has no `me` prop.

- [ ] **Step 3: Implement**

`dashboard/src/lib/initials.ts`:

```ts
import type { Me } from "@/api/auth";

/** Up to two capitals from the name, else the email's first letter. */
export function initials(me: Pick<Me, "display_name" | "email">): string {
  const words = (me.display_name ?? "").trim().split(/\s+/).filter(Boolean);
  const fromName = words.slice(0, 2).map((word) => word[0]!.toUpperCase()).join("");
  return fromName || (me.email?.[0]?.toUpperCase() ?? "?");
}
```

`dashboard/src/components/WorkspaceMenu.tsx`:

```tsx
import { useState } from "react";
import { CircleHelp, KeyRound, LogOut } from "lucide-react";

import type { Me } from "@/api/auth";
import { initials } from "@/lib/initials";

import { PenDialog } from "./PenDialog";

export function WorkspaceMenu({
  me,
  onHelp,
  onTokens,
  onSignOut,
}: {
  me: Me;
  onHelp: () => void;
  onTokens: () => void;
  onSignOut: (forgetBrowser: boolean) => void;
}) {
  const [open, setOpen] = useState(false);
  const mark = initials(me);
  const run = (action: () => void) => () => {
    setOpen(false);
    action();
  };
  return <>
    <button type="button" aria-label="Workspace menu" className="pen-avatar" onClick={() => setOpen(true)}>{mark}</button>
    <PenDialog open={open} onOpenChange={setOpen} title="Workspace menu" className="pen-workspace-menu">
      <div className="pen-workspace-identity"><span className="pen-avatar">{mark}</span><div><strong>{me.display_name ?? me.email ?? "Service access"}</strong><small>{me.email ?? "No personal account"}</small></div></div>
      <button type="button" onClick={run(onTokens)}><KeyRound aria-hidden="true" /><span>Developer tokens<small>API and CLI access</small></span></button>
      <button type="button" onClick={run(onHelp)}><CircleHelp aria-hidden="true" /><span>Help & shortcuts<small>Guides and key commands</small></span></button>
      <button type="button" className="pen-sign-out" onClick={run(() => onSignOut(false))}><LogOut aria-hidden="true" />Sign out</button>
      <button type="button" className="pen-sign-out" onClick={run(() => onSignOut(true))}>Sign out and forget this browser</button>
    </PenDialog>
  </>;
}
```

`dashboard/src/features/settings/TokensPage.tsx`:

```tsx
import { useEffect, useState, type FormEvent } from "react";

import { authClient, AuthRequestError, type AuthClient, type CreatedToken, type TokenView } from "@/api/auth";
import { Button } from "@/components/ui/button";
import { formatWhen } from "@/lib/format-time";

type TokensClient = Pick<AuthClient, "listTokens" | "createToken" | "revokeToken">;
const ERRORS: Record<string, string> = {
  token_limit: "You have 20 active tokens. Revoke one to create another.",
  user_required: "Developer tokens belong to a signed-in account.",
  insufficient_scope: "Managing tokens needs a signed-in session or an admin token.",
};
const message = (failure: unknown) =>
  (failure instanceof AuthRequestError && failure.code && ERRORS[failure.code]) || "Tokens could not be loaded. Try again.";

export function TokensPage({ client = authClient }: { client?: TokensClient }) {
  const [tokens, setTokens] = useState<TokenView[]>([]);
  const [error, setError] = useState<string | null>(null);
  const [name, setName] = useState("");
  const [scope, setScope] = useState<"read" | "write" | "admin">("write");
  const [days, setDays] = useState(90);
  const [created, setCreated] = useState<CreatedToken | null>(null);
  const [confirming, setConfirming] = useState<string | null>(null);

  const load = () => client.listTokens().then(setTokens, (failure) => setError(message(failure)));
  useEffect(() => {
    void load();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [client]);

  async function create(event: FormEvent) {
    event.preventDefault();
    setError(null);
    try {
      setCreated(await client.createToken({ name: name.trim(), scope, days }));
      setName("");
      await load();
    } catch (failure) {
      setError(message(failure));
    }
  }

  async function revoke(token: TokenView) {
    setConfirming(null);
    try {
      await client.revokeToken(token.token_id);
      await load();
    } catch (failure) {
      setError(message(failure));
    }
  }

  return (
    <div className="dashboard-tokens">
      <form className="pen-recent-runs dashboard-token-form" onSubmit={(event) => void create(event)}>
        <label htmlFor="token-name">Token name</label>
        <input id="token-name" value={name} maxLength={100} onChange={(event) => setName(event.target.value)} />
        <label htmlFor="token-scope">Access</label>
        <select id="token-scope" value={scope} onChange={(event) => setScope(event.target.value as typeof scope)}>
          <option value="read">Read only</option>
          <option value="write">Read and write</option>
          <option value="admin">Admin (can manage tokens)</option>
        </select>
        <label htmlFor="token-days">Expires after</label>
        <select id="token-days" value={days} onChange={(event) => setDays(Number(event.target.value))}>
          {[30, 90, 180, 365].map((value) => <option key={value} value={value}>{`${value} days`}</option>)}
        </select>
        <Button type="submit" disabled={!name.trim()}>Create token</Button>
      </form>
      {created && (
        <section className="pen-recent-runs dashboard-token-created" aria-live="polite">
          <label htmlFor="new-token">New token</label>
          <input id="new-token" readOnly value={created.secret} onFocus={(event) => event.target.select()} />
          <Button type="button" variant="outline" onClick={() => void navigator.clipboard?.writeText(created.secret)}>Copy</Button>
          <p>Copy it now. It is not shown again.</p>
        </section>
      )}
      {error && <p role="alert" className="text-sm text-destructive">{error}</p>}
      <section className="pen-recent-runs">
        <header><h2>Your tokens</h2></header>
        <div className="pen-runs-table">
          <table>
            <thead><tr>{["Name", "Token", "Access", "Last used", "Expires", ""].map((heading) => <th key={heading}>{heading}</th>)}</tr></thead>
            <tbody>
              {tokens.map((token) => (
                <tr key={token.token_id}>
                  <td>{token.name}</td>
                  <td>{`${token.prefix}…`}</td>
                  <td>{token.scope}</td>
                  <td>{token.last_used_at ? formatWhen(token.last_used_at) : "Never"}</td>
                  <td>{formatWhen(token.expires_at)}</td>
                  <td>
                    {confirming === token.token_id ? (
                      <Button type="button" variant="destructive" aria-label={`Confirm revoke ${token.name}`} onClick={() => void revoke(token)}>Confirm</Button>
                    ) : (
                      <Button type="button" variant="outline" aria-label={`Revoke ${token.name}`} onClick={() => setConfirming(token.token_id)}>Revoke</Button>
                    )}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
          {!tokens.length && !error && <p className="pen-empty-runs">No developer tokens yet.</p>}
        </div>
      </section>
    </div>
  );
}
```

If `Button` has no `destructive` variant in `components/ui/button.tsx`, use `outline`.

In `dashboard/src/App.tsx`:
- add `tokens: { path: "/settings/tokens", label: "Developer tokens", eyebrow: "Access / 03", description: "Personal tokens for the API and the CLI. Each token is shown once.", icon: KeyRound },`
  to `pages`. It is not in `NAV`. Make `pageFor` check `/settings/tokens` before the generic lookup;
- add `<Route path="/settings/tokens" element={<TokensPage />} />`;
- in `Shell`:
  - read `const { me } = useAuth();`;
  - render `<WorkspaceMenu me={me} onHelp={() => setHelpOpen(true)} onTokens={() => navigate("/settings/tokens")} onSignOut={(forget) => void authClient.logout(forget).finally(() => window.location.assign("/login"))} />`.

Add to `dashboard.css`:

```css
.dashboard-tokens { display: grid; gap: 16px; }
.dashboard-token-form, .dashboard-token-created { display: grid; grid-template-columns: max-content minmax(0, 1fr); gap: 10px 14px; align-items: center; padding: 20px 22px; height: auto; }
.dashboard-token-created p { grid-column: 1 / -1; font-size: 12px; color: var(--muted-foreground); }
```

- [ ] **Step 4: Run all dashboard tests and the type check**

Run: `cd dashboard && bun test && bunx tsc --noEmit -p tsconfig.app.json`
Expected: PASS; `tsc` prints nothing.

- [ ] **Step 5: Commit**

```bash
git add dashboard/src/features/settings dashboard/src/lib/initials.ts dashboard/src/components/WorkspaceMenu.tsx dashboard/src/components/WorkspaceMenu.test.tsx dashboard/src/App.tsx dashboard/src/dashboard.css
git commit -m "feat(dashboard): user menu and developer tokens page"
```

---

### Task 13: Vite: proxy `/auth`, inject a local developer token, refuse a bundled key

**Files:**
- Create: `dashboard/vite.auth.ts`
- Modify: `dashboard/vite.config.ts` and `dashboard/vite.config.test.ts`

**Interfaces:**
- Produces:
  - `devProxy(target = "http://127.0.0.1:8000")`, which returns the `server.proxy` map;
  - `refuseBundledKey()`, a Vite plugin that throws on `build` when `VITE_CONTROL_PLANE_API_KEY`
    is set;
  - `injectDevToken(proxyRequest, env = process.env)`.

- [ ] **Step 1: Write the failing test**

Replace `dashboard/vite.config.test.ts` with:

```ts
import { expect, test } from "bun:test";

import config from "./vite.config";
import { injectDevToken, refuseBundledKey } from "./vite.auth";

test("proxies the control plane and the sign-in routes", () => {
  const proxy = config.server?.proxy as Record<string, { target: string }>;
  expect(proxy["/api/v1"].target).toBe("http://127.0.0.1:8000");
  expect(proxy["/auth"].target).toBe("http://127.0.0.1:8000");
});

test("a local developer token is added on the dev server only when set", () => {
  const headers = new Map<string, string>();
  const request = { setHeader: (name: string, value: string) => headers.set(name, value) };
  injectDevToken(request, {});
  expect(headers.size).toBe(0);
  injectDevToken(request, { THOTH_DEV_TOKEN: "thoth_pat_local" });
  expect(headers.get("Authorization")).toBe("Bearer thoth_pat_local");
});

test("a build refuses a control-plane key in the bundle environment", () => {
  const plugin = refuseBundledKey() as { config: (c: object, e: { command: string }) => void };
  const saved = process.env.VITE_CONTROL_PLANE_API_KEY;
  process.env.VITE_CONTROL_PLANE_API_KEY = "leak";
  try {
    expect(() => plugin.config({}, { command: "build" })).toThrow(/VITE_CONTROL_PLANE_API_KEY/);
    expect(() => plugin.config({}, { command: "serve" })).not.toThrow();
  } finally {
    if (saved === undefined) delete process.env.VITE_CONTROL_PLANE_API_KEY;
    else process.env.VITE_CONTROL_PLANE_API_KEY = saved;
  }
});
```

- [ ] **Step 2: Run it to verify it fails**

Run: `cd dashboard && bun test vite.config.test.ts`
Expected: FAIL with `Cannot find module './vite.auth'`.

- [ ] **Step 3: Implement**

`dashboard/vite.auth.ts`:

```ts
// Local development auth (spec 2026-10-19, 3.4): the server never bypasses authentication.
// The dev server adds a personal developer token from the developer's own environment; it is
// read by Node at request time and never becomes a VITE_ variable, so no bundle can contain it.
import type { Plugin, ProxyOptions } from "vite";

type HeaderTarget = { setHeader(name: string, value: string): void };

export function injectDevToken(request: HeaderTarget, env: Record<string, string | undefined> = process.env): void {
  const token = env.THOTH_DEV_TOKEN?.trim();
  if (token) request.setHeader("Authorization", `Bearer ${token}`);
}

export function devProxy(target = "http://127.0.0.1:8000"): Record<string, ProxyOptions> {
  const withToken: ProxyOptions = {
    target,
    configure: (proxy) => proxy.on("proxyReq", (request) => injectDevToken(request)),
  };
  return { "/api/v1": withToken, "/auth": { ...withToken } };
}

export function refuseBundledKey(): Plugin {
  return {
    name: "thoth-refuse-bundled-key",
    config(_config, { command }) {
      if (command === "build" && process.env.VITE_CONTROL_PLANE_API_KEY) {
        throw new Error("VITE_CONTROL_PLANE_API_KEY is set: the dashboard must not bundle a control-plane key. Unset it; the browser signs in instead.");
      }
    },
  };
}
```

In `dashboard/vite.config.ts`:
- import `{ devProxy, refuseBundledKey } from "./vite.auth"`;
- set `plugins: [react(), tailwindcss(), refuseBundledKey()]`;
- replace the `server.proxy` object with `proxy: devProxy(),`;
- if `tsconfig.node.json` lists `vite.config.ts` in `include`, add `vite.auth.ts` next to it.

- [ ] **Step 4: Run the tests and the build**

Run: `cd dashboard && bun test && VITE_CONTROL_PLANE_API_KEY= bun run build`
Expected: tests pass and the build succeeds. Then `VITE_CONTROL_PLANE_API_KEY=x bun run build`
must fail with the message above.

- [ ] **Step 5: Commit**

```bash
git add dashboard/vite.auth.ts dashboard/vite.config.ts dashboard/vite.config.test.ts dashboard/tsconfig.node.json
git commit -m "feat(dashboard): proxy sign-in, inject a local dev token, refuse a bundled key"
```

---

### Task 14: The `web` container: Caddy, compose, deploy, CI and the smoke

**Files:**
- Create: `Dockerfile.web`, `Dockerfile.web.dockerignore`, `deploy/web/Caddyfile` and
  `compose.stage1.web.yml`.
- Modify:
  - `compose.stage1.local.yml`: auth and SMTP settings on `api`;
  - `.env.stage1.local.example`: `THOTH_WEB_IMAGE` and the auth settings;
  - `scripts/ops/deploy-stage1.sh`: add the web overlay;
  - `.github/workflows/container-image.yml`: build, publish, validate and smoke;
  - `docker/test-renderer-offline.sh`: a third argument, the web service and the web checks.

**Interfaces:**
- Consumes: the dashboard build (Tasks 11-13); `thoth-control tokens create` and the
  `/api/v1/me/tokens` routes (Task 10).
- Produces:
  - **the image** `ghcr.io/muhfalihr/thoth-web`, pinned as `THOTH_WEB_IMAGE`;
  - **the `web` service** on `127.0.0.1:${THOTH_WEB_PORT:-8088}`;
  - **smoke lines:** `web_serves_the_spa_on_deep_paths`, `web_requires_a_session`,
    `developer_token_accepted`, `developer_token_revoked`.

- [ ] **Step 1: Write the smoke checks first**

These are the tests: they fail until the image and the service exist.

`docker/test-renderer-offline.sh`:
- **Arguments:** require three arguments, `IMAGE RENDERER_IMAGE WEB_IMAGE`, so `$# -ne 3`, and
  update the usage text. Set `web_image="$3"`, and write `SMOKE_WEB_IMAGE=$web_image` into
  `harness.env` next to `SMOKE_IMAGE`.
- **Stack:** add this service to the `stack.yml` heredoc, after `api`:

```yaml
  web:
    image: ${SMOKE_WEB_IMAGE:?}
    user: "10001:10001"
    depends_on:
      api:
        condition: service_healthy
    environment:
      THOTH_SITE_ADDRESS: ":8088"
    read_only: true
    tmpfs:
      - /data:uid=10001,gid=10001,mode=0700
      - /config:uid=10001,gid=10001,mode=0700
    cap_drop: [ALL]
    healthcheck:
      test: ["CMD", "wget", "-q", "-O", "/dev/null", "http://127.0.0.1:8088/"]
      interval: 5s
      timeout: 5s
      retries: 20
```

- **Checks:** after the "projects, their workflow lists, and Studio documents" block, add:

```bash
# --- the web container: SPA fallback, API behind sign-in, developer tokens (spec 2026-10-19) ---
#: Status (and, with BODY=1, body) of one request to the web container, from the api container.
web() {
    compose exec -T --env BODY="${BODY:-0}" api /opt/thoth/python/.venv/bin/python -c '
import os, sys, urllib.error, urllib.request
request = urllib.request.Request("http://web:8088" + sys.argv[1], method=sys.argv[2] if len(sys.argv) > 2 else "GET")
if len(sys.argv) > 3:
    request.add_header("Authorization", "Bearer " + sys.argv[3])
try:
    with urllib.request.urlopen(request, timeout=10) as response:
        status, body = response.status, response.read().decode()
except urllib.error.HTTPError as error:
    status, body = error.code, ""
print(body if os.environ.get("BODY") == "1" else status)
' "$@"
}
BODY=1 web /studio/p/d | grep -q '<div id="root">' || fail web_serves_the_spa_on_deep_paths
echo web_serves_the_spa_on_deep_paths=true
[ "$(web /api/v1/projects)" = "403" ] || fail web_requires_a_session
echo web_requires_a_session=true
dev_token=$(compose exec -T api thoth-control tokens create --email smoke@thoth.test --name smoke --scope admin | tr -d '\r') \
    || fail developer_token_accepted
[ "$(web /api/v1/projects GET "$dev_token")" = "200" ] || fail developer_token_accepted
echo developer_token_accepted=true
token_id=$(BODY=1 web /api/v1/me/tokens GET "$dev_token" | python3 -c 'import json,sys; print(json.load(sys.stdin)[0]["token_id"])') \
    || fail developer_token_revoked
[ "$(web "/api/v1/me/tokens/$token_id" DELETE "$dev_token")" = "204" ] || fail developer_token_revoked
[ "$(web /api/v1/projects GET "$dev_token")" = "403" ] || fail developer_token_revoked
echo developer_token_revoked=true
```

  The token never reaches the job log: `$dev_token` is only passed as an argument. Leave
  `set -x` off.

- **Teardown and logs:** add `web` to the failure log dump, next to `remotion-renderer`.

- [ ] **Step 2: Write the image and the Caddy config**

`Dockerfile.web.dockerignore`, which BuildKit uses for `Dockerfile.web` in place of the root
`.dockerignore` that excludes `dashboard`:

```
*
!dashboard
!packages/remotion-composition
**/node_modules
dashboard/dist
**/.env*
```

`Dockerfile.web`:

```dockerfile
# syntax=docker/dockerfile:1
# The dashboard SPA behind Caddy (spec 2026-10-19, section 1). No credential is baked in.
FROM oven/bun:1.3.14 AS build
WORKDIR /src
COPY packages/remotion-composition packages/remotion-composition
COPY dashboard/package.json dashboard/bun.lock dashboard/
RUN cd dashboard && bun install --frozen-lockfile
COPY dashboard dashboard
RUN cd dashboard && bun run build

FROM caddy:2.11.4-alpine@sha256:6aeddd44c3078b0f9a35206472a11420648a79c184603ef95957d0a20044cb2b
COPY deploy/web/Caddyfile /etc/caddy/Caddyfile
COPY --from=build /src/dashboard/dist /srv/dashboard
USER 10001:10001
EXPOSE 8088
```

The Caddy base was resolved on 2026-10-19 with `docker buildx imagetools inspect caddy:2.11.4-alpine` (the newest published 2.x alpine release); keep the digest pin.

`deploy/web/Caddyfile`:

```caddyfile
{
	admin off
	# Local by default; a real domain in THOTH_SITE_ADDRESS turns on automatic HTTPS.
	auto_https disable_redirects
}

{$THOTH_SITE_ADDRESS::8088} {
	encode zstd gzip
	header {
		Content-Security-Policy "default-src 'self'; script-src 'self'; style-src 'self' 'unsafe-inline'; img-src 'self' data: blob:; media-src 'self' blob:; connect-src 'self'; font-src 'self' data:; frame-ancestors 'none'; base-uri 'self'; form-action 'self'"
		X-Frame-Options "DENY"
		Referrer-Policy "strict-origin-when-cross-origin"
		X-Content-Type-Options "nosniff"
		-Server
	}

	@backend path /api/v1/* /auth/*
	handle @backend {
		reverse_proxy {$THOTH_API_UPSTREAM:api:8000}
	}

	handle {
		root * /srv/dashboard
		@hashed path /assets/*
		header @hashed Cache-Control "public, max-age=31536000, immutable"
		@page not path /assets/*
		header @page Cache-Control "no-store"
		try_files {path} /index.html
		file_server
	}
}
```

`compose.stage1.web.yml`:

```yaml
# The dashboard behind Caddy (spec 2026-10-19). An overlay like the renderer: the base stack
# still parses without it.
services:
  web:
    image: ${THOTH_WEB_IMAGE:?set digest-qualified THOTH_WEB_IMAGE}
    user: "10001:10001"
    depends_on:
      api:
        condition: service_healthy
    environment:
      THOTH_SITE_ADDRESS: ${THOTH_SITE_ADDRESS:-:8088}
    read_only: true
    tmpfs:
      - /data:uid=10001,gid=10001,mode=0700
      - /config:uid=10001,gid=10001,mode=0700
    cap_drop: [ALL]
    ports:
      - "127.0.0.1:${THOTH_WEB_PORT:-8088}:8088"
    healthcheck:
      test: ["CMD", "wget", "-q", "-O", "/dev/null", "http://127.0.0.1:8088/"]
      interval: 10s
      timeout: 5s
      retries: 12
    restart: unless-stopped
    networks: [stage1-private]
```

In `compose.stage1.local.yml`, add to the `api` `environment`. Every value is optional; empty means
not configured.

```yaml
      # Sign-in (spec 2026-10-19). Empty values leave sign-in off; tokens and the service key work.
      THOTH_SITE_ORIGIN: ${THOTH_SITE_ORIGIN:-http://localhost:8088}
      THOTH_AUTH_SECRET: "${THOTH_AUTH_SECRET:-}"
      THOTH_AUTH_GOOGLE_CLIENT_ID: "${THOTH_AUTH_GOOGLE_CLIENT_ID:-}"
      THOTH_AUTH_GOOGLE_CLIENT_SECRET: "${THOTH_AUTH_GOOGLE_CLIENT_SECRET:-}"
      THOTH_AUTH_GOOGLE_DOMAIN: "${THOTH_AUTH_GOOGLE_DOMAIN:-}"
      THOTH_AUTH_GITHUB_CLIENT_ID: "${THOTH_AUTH_GITHUB_CLIENT_ID:-}"
      THOTH_AUTH_GITHUB_CLIENT_SECRET: "${THOTH_AUTH_GITHUB_CLIENT_SECRET:-}"
      THOTH_AUTH_GITHUB_ORG: "${THOTH_AUTH_GITHUB_ORG:-}"
      THOTH_SMTP_HOST: "${THOTH_SMTP_HOST:-}"
      THOTH_SMTP_PORT: "${THOTH_SMTP_PORT:-587}"
      THOTH_SMTP_USERNAME: "${THOTH_SMTP_USERNAME:-}"
      THOTH_SMTP_PASSWORD: "${THOTH_SMTP_PASSWORD:-}"
      THOTH_SMTP_FROM: "${THOTH_SMTP_FROM:-}"
```

In `.env.stage1.local.example`:
- after `THOTH_RENDERER_IMAGE`, add
  `THOTH_WEB_IMAGE=ghcr.io/muhfalihr/thoth-web@sha256:0000000000000000000000000000000000000000000000000000000000000000`;
- add a commented block listing every auth and SMTP variable above, with empty values.

In `scripts/ops/deploy-stage1.sh`:
- add `-f compose.stage1.web.yml` to the `compose=(...)` array;
- in `step preflight`, add `[ -n "$(value THOTH_WEB_IMAGE)" ] || { echo "THOTH_WEB_IMAGE is not pinned" >&2; exit 1; }`.

- [ ] **Step 3: Wire CI**

In `.github/workflows/container-image.yml`:
- **`env`:** add `WEB_REGISTRY_IMAGE: ghcr.io/muhfalihr/thoth-web`.
- **`validate-image`:**
  - add `WEB_CANDIDATE_IMAGE: thoth-web:pr-${{ github.sha }}`;
  - add a step "Build the web image without publishing", the same as the renderer step but with
    `file: Dockerfile.web`, `tags: ${{ env.WEB_CANDIDATE_IMAGE }}` and cache scope `thoth-web`;
  - pass `"${WEB_CANDIDATE_IMAGE}"` as the third argument to `docker/test-renderer-offline.sh`.
- **`publish-image`:**
  - add the `web_digest: ${{ steps.web-build.outputs.digest }}` output;
  - add a metadata step `web-meta` (title "Thoth dashboard web", description "The dashboard
    SPA behind Caddy") and a build-and-publish step `web-build` with `file: Dockerfile.web`,
    mirroring the renderer pair;
  - add a "Published web image" block to the release summary.
- **`stack-smoke`:**
  - add `THOTH_WEB_IMAGE_REF: ghcr.io/muhfalihr/thoth-web@${{ needs.publish-image.outputs.web_digest }}`;
  - pass it as the third argument in "Verify the isolated render stack on the published digests".
- **`quality`, step "Validate local Stage 1 Compose":** add
  `docker compose --env-file .env.stage1.local.example -f compose.stage1.local.yml -f compose.stage1.web.yml config --quiet`.

Lint the workflow locally before pushing, as the repository's memory advises: run
`actionlint .github/workflows/container-image.yml` in WSL if it is installed. Otherwise use
`docker run --rm -v "$PWD:/repo" -w /repo rhysd/actionlint:1.7.7`.

- [ ] **Step 4: Build the image locally and run the smoke**

In WSL from the worktree:
1. Build the three images:
   `docker build -f Dockerfile.web -t thoth-web:local .`,
   `docker build -t thoth:local .` and
   `docker build -f Dockerfile.renderer -t thoth-remotion-renderer:local .`.
2. Run `bash docker/test-renderer-offline.sh thoth:local thoth-remotion-renderer:local thoth-web:local`.

Expected: the script prints every existing `...=true` line plus `web_serves_the_spa_on_deep_paths`,
`web_requires_a_session`, `developer_token_accepted` and `developer_token_revoked`, and exits 0.

- [ ] **Step 5: Walk the built dashboard under its CSP (Review Focus 5)**

The checks run against a local stack with the web image:
1. Start the stack with `compose.stage1.web.yml`. Keep a background `wsl -e sleep 1800` open, so
   Windows reaches the WSL ports.
2. Create a dev token: `docker compose ... exec -T api thoth-control tokens create --email you@... --name walk --scope admin`.
3. Because the built SPA signs in with a cookie, walk it through `vite dev` with that token in
   `THOTH_DEV_TOKEN`. For the CSP itself, run Edge headless against `http://localhost:8088` with
   `--enable-logging=stderr --v=0` and fetch `/login`, `/workflows` and a Studio document. Check
   stderr for `Content Security Policy` violations.

Expected: no CSP violation on `/login`, `/workflows` or `/studio/...`. If one appears, widen only
that directive. Record each change as a ledger ruling.

- [ ] **Step 6: Commit**

```bash
git add Dockerfile.web Dockerfile.web.dockerignore deploy/web/Caddyfile compose.stage1.web.yml compose.stage1.local.yml .env.stage1.local.example scripts/ops/deploy-stage1.sh .github/workflows/container-image.yml docker/test-renderer-offline.sh
git commit -m "feat(web): serve the dashboard from a Caddy container with a CSP"
```

---

### Task 15: Documentation, records and the full verification

**Files:**
- Modify: `docs/python-control-plane.md`. Add a "Sign-in and developer access" section with:
  - every new setting (the table from spec section 5);
  - the cookies and the failure codes from the Global Constraints, including `unavailable` and
    `signed_out`;
  - the operator steps to create the Google and GitHub OAuth apps, with their callback URLs;
  - the bootstrap command `thoth-control tokens create`;
  - local development with `THOTH_DEV_TOKEN`.
- Modify: `README.md` ("Running the dashboard") and `dashboard/README.md`, describing the `web`
  container at `http://localhost:8088`, sign-in, and `vite dev` with `THOTH_DEV_TOKEN`.
- Modify: `CHANGELOG.md`, with a new top entry "2026-10-19 - Accounts, sign-in and developer access
  (SaaS sub-project 1)". It holds the rulings, the verification numbers and **Next steps**.

- [ ] **Step 1: Run every gate**

In WSL from the worktree, run `make format`, `make lint`, `make test` and `make test-postgres`.
Then, from `dashboard/`, run `bun test`, `bunx tsc --noEmit -p tsconfig.app.json` and
`bun run build`. Expected:
- lint is clean;
- the Python suite, Postgres and the dashboard all pass;
- the build succeeds;
- `git diff origin/master -- crates` is empty.

- [ ] **Step 2: Write the docs and the CHANGELOG entry**

The entry's **Next steps** list:
- **operator gates:**
  - push, PR, CI, merge;
  - pin `THOTH_WEB_IMAGE` and the new `THOTH_IMAGE`, then deploy;
  - create the OAuth apps and the SMTP account, and set the env values;
  - optionally set WSL `networkingMode=mirrored`;
- **the first real sign-in,** at the final live acceptance;
- **next:** SaaS sub-project 2 (multi-tenancy: every user's own isolated workspace), then
  metering and billing; roadmap priority 2 resumes from its checkpoint;
- **follow-ups:** per-IP rate limiting at Caddy, and removing the legacy service key.

- [ ] **Step 3: Commit**

```bash
git add docs/python-control-plane.md README.md dashboard/README.md CHANGELOG.md
git commit -m "docs: record accounts, sign-in and developer access"
```
