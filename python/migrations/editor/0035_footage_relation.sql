-- Footage related events (2026-11-16, spec 10.3, 10.7 and 10.12): how a kept clip relates to the
-- main's incident, and the reasons a clip is now rejected (a second same-event clip, a clip without
-- the story's subject, a third old clip). Rollback: images before 0035 never read the column nor
-- write the reasons; both may stay.
ALTER TABLE footage_candidates ADD COLUMN relation TEXT NOT NULL DEFAULT 'unknown'
    CHECK (relation IN ('related', 'same_event', 'discusses', 'unknown'));
ALTER TABLE footage_library ADD COLUMN relation TEXT NOT NULL DEFAULT 'unknown'
    CHECK (relation IN ('related', 'same_event', 'discusses', 'unknown'));
ALTER TABLE footage_candidates
    DROP CONSTRAINT footage_candidates_reason_check,
    ADD CONSTRAINT footage_candidates_reason_check CHECK (reason IN (
        'main', 'aggregator', 'spam', 'reaction_text', 'duration', 'story', 'subtitle',
        'commentary', 'object_absent', 'duplicate', 'media_failed', 'vision_unavailable', 'repost',
        'same_event', 'subject_absent', 'too_old'
    ));
