-- Metering, the cost model and the shared-pool quota (spec 2026-10-20 metering).
CREATE TABLE usage_events (
    event_id TEXT PRIMARY KEY,
    workspace_id TEXT NOT NULL REFERENCES workspaces (workspace_id),
    workflow_id TEXT,
    project_id TEXT,
    kind TEXT NOT NULL CHECK (kind IN (
        'account_lease', 'workflow_completed', 'video_rendered', 'media_stored', 'provider_call'
    )),
    key TEXT NOT NULL,
    quantity DOUBLE PRECISION NOT NULL CHECK (quantity >= 0),
    unit TEXT NOT NULL CHECK (unit IN (
        'session', 'workflow', 'second', 'byte', 'call', 'token_in', 'token_out', 'character'
    )),
    occurred_at TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE INDEX usage_events_workspace ON usage_events (workspace_id, occurred_at);
CREATE INDEX usage_events_workspace_kind ON usage_events (workspace_id, kind, key, occurred_at);

CREATE TABLE workspace_quotas (
    workspace_id TEXT NOT NULL REFERENCES workspaces (workspace_id),
    platform TEXT NOT NULL,
    daily_leases INTEGER NOT NULL CHECK (daily_leases >= 0),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    PRIMARY KEY (workspace_id, platform)
);

CREATE TABLE unit_prices (
    kind TEXT NOT NULL,
    key TEXT NOT NULL,
    unit TEXT NOT NULL,
    usd_per_unit DOUBLE PRECISION NOT NULL CHECK (usd_per_unit >= 0),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    PRIMARY KEY (kind, key, unit)
);

ALTER TABLE source_account_policies ADD COLUMN operator_reserve_percent INTEGER
    CHECK (operator_reserve_percent BETWEEN 0 AND 100);
