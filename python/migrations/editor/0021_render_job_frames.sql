-- Run progress phase 5 (spec 2026-10-25, G6): the renderer reports what it is doing and
-- how far, in frames, so the Render screen can show "862 of 1440 frames" and a rate.
ALTER TABLE render_jobs
    ADD COLUMN rendered_frames INTEGER CHECK (rendered_frames IS NULL OR rendered_frames >= 0),
    ADD COLUMN encoded_frames INTEGER CHECK (encoded_frames IS NULL OR encoded_frames >= 0),
    ADD COLUMN total_frames INTEGER CHECK (total_frames IS NULL OR total_frames > 0),
    ADD COLUMN render_stage TEXT
        CHECK (render_stage IS NULL
               OR render_stage IN ('preparing', 'rendering', 'encoding', 'uploading'));
