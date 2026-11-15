-- Planner stage 1 (2026-11-13): a draft's plan (what each narration phrase shows), and the shots
-- found in a source video, kept by the video's checksum so another draft or a re-voice reuses them.
-- Rollback: images before 0032 never read the column or the table; both may stay.
ALTER TABLE narrations ADD COLUMN plan JSONB;
CREATE TABLE planner_shots (
    checksum TEXT PRIMARY KEY,
    shots JSONB NOT NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);
