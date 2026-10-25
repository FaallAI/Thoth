-- Run progress phase 4 (spec 2026-10-25, section 4): a failed run leaves the inbox only
-- through an explicit acknowledge, so the inbox can list unacknowledged failures.
ALTER TABLE workflow_runs ADD COLUMN acknowledged_at TIMESTAMPTZ;

-- The inbox failure list: failed runs not yet acknowledged, newest first per caller.
CREATE INDEX workflow_runs_unacknowledged_failures ON workflow_runs (actor_type, actor_id, updated_at DESC) WHERE status = 'failed' AND acknowledged_at IS NULL;
