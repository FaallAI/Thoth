-- Workflow reports (spec 2026-10-16): the single store of the control plane's JSON reports,
-- keyed by the artifact location the ArtifactRef already carries. `content` is the exact JSON
-- text (checksums match); `body` is a queryable copy. jsonb refuses the \u0000 escape that
-- scraped text can contain, so `body` drops it; `content` is never altered.

CREATE TABLE workflow_reports (
    location TEXT PRIMARY KEY CHECK (char_length(location) BETWEEN 1 AND 1024),
    workflow_id TEXT NOT NULL CHECK (char_length(workflow_id) BETWEEN 1 AND 128),
    kind TEXT NOT NULL CHECK (
        kind IN ('source_report', 'original_source_report', 'source_attribution', 'content_set')
    ),
    content TEXT NOT NULL,
    body JSONB GENERATED ALWAYS AS (replace(content, '\u0000', '')::jsonb) STORED,
    sha256 CHAR(64) NOT NULL,
    size_bytes INTEGER NOT NULL CHECK (size_bytes >= 0),
    created_at TIMESTAMPTZ NOT NULL,
    updated_at TIMESTAMPTZ NOT NULL
);
CREATE INDEX workflow_reports_workflow ON workflow_reports (workflow_id, kind);
