-- Projects and workflow runs (spec 2026-10-18, UI foundation). Projects move into the control
-- plane; a run row is written when a workflow starts and settled when it is read.

CREATE TABLE projects (
    project_id TEXT PRIMARY KEY CHECK (char_length(project_id) BETWEEN 1 AND 128),
    name TEXT NOT NULL CHECK (char_length(btrim(name)) BETWEEN 1 AND 120),
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE workflow_runs (
    workflow_id TEXT PRIMARY KEY CHECK (char_length(workflow_id) BETWEEN 1 AND 128),
    project_id TEXT REFERENCES projects (project_id),
    actor_type TEXT NOT NULL,
    actor_id TEXT NOT NULL,
    display_url TEXT NOT NULL CHECK (char_length(display_url) BETWEEN 1 AND 2048),
    platform TEXT NOT NULL,
    status TEXT NOT NULL CHECK (status IN (
        'queued', 'running', 'awaiting_approval', 'succeeded', 'failed', 'cancelled', 'unknown')),
    history_expired BOOLEAN NOT NULL DEFAULT false,
    summary JSONB,
    created_at TIMESTAMPTZ NOT NULL,
    updated_at TIMESTAMPTZ NOT NULL
);
CREATE INDEX workflow_runs_project ON workflow_runs (project_id, created_at DESC, workflow_id DESC);
CREATE INDEX workflow_runs_unsettled ON workflow_runs (status)
    WHERE status IN ('queued', 'running', 'awaiting_approval', 'unknown');
