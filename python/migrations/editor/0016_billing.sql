-- Billing: plans, subscriptions, invoices and the allowance ledger (spec 2026-10-20 billing).
CREATE TABLE plans (
    plan_id TEXT PRIMARY KEY CHECK (plan_id ~ '^[a-z0-9-]{1,32}$'),
    name TEXT NOT NULL CHECK (length(name) BETWEEN 1 AND 60),
    price_idr BIGINT NOT NULL CHECK (price_idr >= 0),
    workflows_per_period INTEGER NOT NULL CHECK (workflows_per_period >= 0),
    videos_per_period INTEGER NOT NULL CHECK (videos_per_period >= 0),
    period_days INTEGER NOT NULL DEFAULT 30 CHECK (period_days BETWEEN 1 AND 366),
    active BOOLEAN NOT NULL DEFAULT true,
    updated_at TIMESTAMPTZ NOT NULL DEFAULT now()
);
INSERT INTO plans (plan_id, name, price_idr, workflows_per_period, videos_per_period, period_days)
VALUES ('free', 'Free', 0, 3, 1, 30);

CREATE TABLE subscriptions (
    workspace_id TEXT PRIMARY KEY REFERENCES workspaces (workspace_id),
    plan_id TEXT NOT NULL REFERENCES plans (plan_id),
    period_start TIMESTAMPTZ NOT NULL,
    period_end TIMESTAMPTZ NOT NULL,
    updated_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE invoices (
    invoice_id TEXT PRIMARY KEY,
    workspace_id TEXT NOT NULL REFERENCES workspaces (workspace_id),
    plan_id TEXT NOT NULL REFERENCES plans (plan_id),
    amount_idr BIGINT NOT NULL CHECK (amount_idr >= 0),
    status TEXT NOT NULL CHECK (status IN ('pending', 'paid', 'expired', 'failed')),
    provider_invoice_id TEXT,
    invoice_url TEXT,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    paid_at TIMESTAMPTZ
);
CREATE INDEX invoices_workspace ON invoices (workspace_id, created_at DESC);

CREATE TABLE allowance_uses (
    use_id TEXT PRIMARY KEY,
    workspace_id TEXT NOT NULL REFERENCES workspaces (workspace_id),
    kind TEXT NOT NULL CHECK (kind IN ('workflow', 'video')),
    ref TEXT NOT NULL,
    created_at TIMESTAMPTZ NOT NULL,
    released_at TIMESTAMPTZ,
    UNIQUE (workspace_id, kind, ref)
);
CREATE INDEX allowance_uses_period ON allowance_uses (workspace_id, kind, created_at);
