-- Run progress phase 2 (spec 2026-10-25, section 4): activities record steps straight to
-- Postgres, coalesced to at most one row per second per code, kept as long as the run row.
CREATE TABLE workflow_steps (
    workflow_id TEXT NOT NULL,
    seq BIGSERIAL PRIMARY KEY,
    attempt INTEGER NOT NULL CHECK (attempt >= 1),
    stage TEXT NOT NULL CHECK (stage IN ('source', 'attribution', 'footage', 'assembly')),
    at TIMESTAMPTZ NOT NULL,
    kind TEXT NOT NULL CHECK (kind IN ('info', 'progress', 'wait', 'done', 'warning', 'error')),
    code TEXT NOT NULL,
    n INTEGER CHECK (n IS NULL OR n >= 0),
    total INTEGER CHECK (total IS NULL OR total >= 0),
    wait_until TIMESTAMPTZ,
    params JSONB CHECK (params IS NULL OR length(params::text) <= 1024)
);

-- No foreign key to workflow_runs on purpose: the run row is written only after Temporal
-- accepted the start, so a foreign key would drop the first activity's step.
CREATE INDEX workflow_steps_workflow ON workflow_steps (workflow_id, seq);
