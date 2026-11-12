-- Style templates (spec 2026-11-10): a workspace's own style templates, one row per revision.
-- The built-in Style A and Style B are read from code (domain/style_templates.py), not stored.
-- Rollback: images before 0028 never read this table, so it may stay; drop it to undo fully.
CREATE TABLE style_templates (
    workspace_id TEXT NOT NULL,
    template_id TEXT NOT NULL,
    revision INTEGER NOT NULL CHECK (revision > 0),
    body JSONB NOT NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
    -- A template id is the workspace's own; the key leads with the workspace, as reads do.
    PRIMARY KEY (workspace_id, template_id, revision)
);
