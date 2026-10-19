-- Projects belong to a workspace (spec 2026-10-19 workspace isolation, section 1.2). Every
-- existing project is the operator's, so it moves to the bootstrap workspace.
ALTER TABLE projects ADD COLUMN workspace_id TEXT REFERENCES workspaces (workspace_id);
UPDATE projects SET workspace_id = 'ws_bootstrap' WHERE workspace_id IS NULL;
ALTER TABLE projects ALTER COLUMN workspace_id SET NOT NULL;
CREATE INDEX projects_workspace ON projects (workspace_id, updated_at DESC);
