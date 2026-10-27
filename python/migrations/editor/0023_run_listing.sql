-- Restyle spec §6, B1-B2 (2026-10-26): what a run row shows, read once from its source report,
-- and the index behind the caller's list across every project. NULL until the report is read;
-- an empty title means the report was read and the post has no text.
ALTER TABLE workflow_runs
    ADD COLUMN title TEXT,
    ADD COLUMN owner_handle TEXT,
    ADD COLUMN post_card_location TEXT;
CREATE INDEX workflow_runs_actor ON workflow_runs (actor_type, actor_id, created_at DESC, workflow_id DESC);
