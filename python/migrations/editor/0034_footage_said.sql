-- Footage revision (2026-11-16): what a footage section's video says around it (caption lines in
-- source-video seconds), kept on the candidate and the library clip for the narration and the
-- planner. Rollback: images before 0034 never read the column; it may stay.
ALTER TABLE footage_candidates ADD COLUMN said JSONB NOT NULL DEFAULT '[]'::jsonb;
ALTER TABLE footage_library ADD COLUMN said JSONB NOT NULL DEFAULT '[]'::jsonb;
