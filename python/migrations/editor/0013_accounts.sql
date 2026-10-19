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
    revoked_at TIMESTAMPTZ,
    -- The token that minted this one: revoking a token revokes everything it minted.
    parent_token_id TEXT REFERENCES access_tokens (token_id)
);
CREATE INDEX access_tokens_owner ON access_tokens (owner_kind, owner_id, created_at DESC);
CREATE INDEX access_tokens_parent ON access_tokens (parent_token_id) WHERE parent_token_id IS NOT NULL;

CREATE TABLE auth_events (
    event_id BIGSERIAL PRIMARY KEY,
    at TIMESTAMPTZ NOT NULL DEFAULT now(),
    kind TEXT NOT NULL CHECK (char_length(kind) BETWEEN 1 AND 64),
    outcome TEXT NOT NULL CHECK (outcome IN ('ok', 'refused', 'failed')),
    user_id TEXT,
    token_id TEXT,
    detail_code TEXT
);
