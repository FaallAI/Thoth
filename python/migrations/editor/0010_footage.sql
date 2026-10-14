-- Stage 5b footage (spec 2026-10-14): a 24-hour search cache, one run per workflow, and one
-- row per candidate with its decision. Media stay files; rows hold locations and checksums.

CREATE TABLE footage_searches (
    id UUID PRIMARY KEY,
    platform TEXT NOT NULL CHECK (platform IN ('tiktok', 'youtube', 'x')),
    query TEXT NOT NULL CHECK (char_length(query) BETWEEN 1 AND 200),
    results JSONB NOT NULL,
    fetched_at TIMESTAMPTZ NOT NULL,
    expires_at TIMESTAMPTZ NOT NULL,
    UNIQUE (platform, query)
);
CREATE INDEX footage_searches_expires_at ON footage_searches (expires_at);

CREATE TABLE footage_runs (
    workflow_id TEXT PRIMARY KEY CHECK (char_length(workflow_id) BETWEEN 1 AND 128),
    status TEXT NOT NULL CHECK (status IN ('running', 'done')),
    footage_status TEXT CHECK (footage_status IN ('ok', 'none', 'disabled', 'unavailable')),
    objects JSONB NOT NULL,
    started_at TIMESTAMPTZ NOT NULL,
    finished_at TIMESTAMPTZ
);

CREATE TABLE footage_candidates (
    id UUID PRIMARY KEY,
    workflow_id TEXT NOT NULL REFERENCES footage_runs (workflow_id) ON DELETE CASCADE,
    url TEXT NOT NULL CHECK (char_length(url) BETWEEN 1 AND 2048),
    platform TEXT NOT NULL CHECK (platform IN ('tiktok', 'youtube', 'x', 'instagram')),
    source TEXT NOT NULL CHECK (source IN ('search', 'carousel')),
    query TEXT NOT NULL,
    visual TEXT NOT NULL,
    owner_handle TEXT NOT NULL,
    caption TEXT NOT NULL DEFAULT '',
    published_at TEXT,
    engagement JSONB NOT NULL,
    source_duration DOUBLE PRECISION,
    status TEXT NOT NULL CHECK (status IN ('pending', 'admitted', 'rejected')),
    reason TEXT CHECK (reason IN (
        'main', 'aggregator', 'spam', 'reaction_text', 'duration', 'story', 'subtitle',
        'commentary', 'object_absent', 'duplicate', 'media_failed', 'vision_unavailable'
    )),
    story_score DOUBLE PRECISION,
    kind TEXT CHECK (kind IN ('footage', 'commentary')),
    shows_object TEXT CHECK (shows_object IN ('yes', 'partly', 'no')),
    description TEXT,
    media_location TEXT,
    media_checksum TEXT,
    media_bytes BIGINT,
    clip_duration DOUBLE PRECISION,
    clip_start DOUBLE PRECISION,
    ocr JSONB,
    position INTEGER,
    created_at TIMESTAMPTZ NOT NULL,
    updated_at TIMESTAMPTZ NOT NULL,
    UNIQUE (workflow_id, url),
    CHECK ((status = 'rejected') = (reason IS NOT NULL)),
    CHECK (status <> 'admitted' OR (media_location IS NOT NULL AND position IS NOT NULL))
);
