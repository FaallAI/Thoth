-- Workspace asset library (spec 2026-11-13): a workspace's own SFX, clips, backsound and images.
-- Media lives under library/<workspace_id>/; a draft that uses an item holds its own copy.
-- Rollback: images before 0031 never read this table, so it may stay; drop it to undo fully.
CREATE TABLE workspace_assets (
    workspace_id TEXT NOT NULL,
    asset_id TEXT NOT NULL,
    kind TEXT NOT NULL CHECK (kind IN ('sfx', 'clip', 'backsound', 'image')),
    name TEXT NOT NULL,
    labels JSONB NOT NULL DEFAULT '{}',
    media_type TEXT NOT NULL,
    location TEXT NOT NULL,
    checksum TEXT NOT NULL,
    duration_seconds DOUBLE PRECISION,
    width INTEGER,
    height INTEGER,
    has_audio BOOLEAN NOT NULL DEFAULT FALSE,
    created_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
    PRIMARY KEY (workspace_id, asset_id),
    -- The same file uploaded twice to one workspace is one item.
    UNIQUE (workspace_id, checksum)
);
