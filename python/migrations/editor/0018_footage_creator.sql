-- Stage 5c-2 (spec 2026-10-22): the creator's own videos and photos become footage candidates,
-- and a run keeps the TikTok profile page card its creator listing cropped.
ALTER TABLE footage_candidates
    DROP CONSTRAINT footage_candidates_source_check,
    ADD CONSTRAINT footage_candidates_source_check
        CHECK (source IN ('search', 'carousel', 'creator')),
    ADD COLUMN media_kind TEXT NOT NULL DEFAULT 'video'
        CHECK (media_kind IN ('video', 'image'));

ALTER TABLE footage_runs ADD COLUMN profile_page JSONB;
