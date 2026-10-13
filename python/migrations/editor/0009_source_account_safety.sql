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
