-- Restyle spec §7, B9 (2026-10-27): the run a Studio draft was opened from, so the documents
-- list can show its source. NULL for drafts made before this, or not opened from a run.
ALTER TABLE studio_import_drafts
    ADD COLUMN source_workflow_id TEXT;
