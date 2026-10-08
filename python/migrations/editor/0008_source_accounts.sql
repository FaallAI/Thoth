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
