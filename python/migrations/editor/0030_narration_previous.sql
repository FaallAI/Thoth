-- Style templates, final review (2026-11-10): a style restarts a finished narration, and its
-- undo brings that narration back, so the narration it replaced is kept here until then.
-- Rollback: images before 0030 never read the column; it may stay.
ALTER TABLE narrations ADD COLUMN previous JSONB;
