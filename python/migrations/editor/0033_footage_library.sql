-- Footage library (2026-11-15): a run's context card (who and what the main post is about), and
-- every clip a run kept, per workspace, so a later run on the same story reuses it.
-- Rollback: images before 0033 never read the column or the table; both may stay.
ALTER TABLE footage_runs ADD COLUMN context JSONB;
CREATE TABLE footage_library (
    id TEXT PRIMARY KEY,
    workspace_id TEXT NOT NULL REFERENCES workspaces(workspace_id),
    url TEXT NOT NULL,
    platform TEXT NOT NULL,
    owner_handle TEXT NOT NULL DEFAULT '',
    published_at TEXT,
    section_start DOUBLE PRECISION NOT NULL DEFAULT 0,
    section_end DOUBLE PRECISION,
    media_location TEXT NOT NULL,
    media_checksum TEXT NOT NULL,
    hashes JSONB NOT NULL DEFAULT '[]',
    names JSONB NOT NULL DEFAULT '[]',
    event TEXT NOT NULL DEFAULT '',
    first_workflow_id TEXT NOT NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    UNIQUE (workspace_id, url, section_start)
);
CREATE INDEX footage_library_workspace ON footage_library (workspace_id);
