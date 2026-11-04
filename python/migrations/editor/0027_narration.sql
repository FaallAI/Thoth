-- Auto-draft, the narrated draft (spec 2026-10-31): the narration_script prompt stage, one
-- narration per Studio draft, each project's narration preset, and the shared SFX library.
ALTER TABLE prompt_template_revisions DROP CONSTRAINT prompt_template_revisions_stage_id_check,
    ADD CONSTRAINT prompt_template_revisions_stage_id_check
    CHECK (stage_id IN ('narrative_plan', 'visual_plan', 'caption_copy', 'story_assist', 'narration_script'));
ALTER TABLE project_prompt_bindings DROP CONSTRAINT project_prompt_bindings_stage_id_check,
    ADD CONSTRAINT project_prompt_bindings_stage_id_check
    CHECK (stage_id IN ('narrative_plan', 'visual_plan', 'caption_copy', 'story_assist', 'narration_script'));
ALTER TABLE prompt_provider_preferences DROP CONSTRAINT prompt_provider_preferences_stage_id_check,
    ADD CONSTRAINT prompt_provider_preferences_stage_id_check
    CHECK (stage_id IN ('narrative_plan', 'visual_plan', 'caption_copy', 'story_assist', 'narration_script'));
ALTER TABLE prompt_layer_locks DROP CONSTRAINT prompt_layer_locks_stage_id_check,
    ADD CONSTRAINT prompt_layer_locks_stage_id_check
    CHECK (stage_id IN ('narrative_plan', 'visual_plan', 'caption_copy', 'story_assist', 'narration_script'));
ALTER TABLE prompt_proposals DROP CONSTRAINT prompt_proposals_stage_id_check,
    ADD CONSTRAINT prompt_proposals_stage_id_check
    CHECK (stage_id IN ('narrative_plan', 'visual_plan', 'caption_copy', 'story_assist', 'narration_script'));
ALTER TABLE prompt_proposal_applications DROP CONSTRAINT prompt_proposal_applications_stage_id_check,
    ADD CONSTRAINT prompt_proposal_applications_stage_id_check
    CHECK (stage_id IN ('narrative_plan', 'visual_plan', 'caption_copy', 'story_assist', 'narration_script'));

CREATE TABLE narrations (
    document_id TEXT PRIMARY KEY,
    project_id TEXT NOT NULL,
    workflow_id TEXT NOT NULL,
    status TEXT NOT NULL CHECK (status IN (
        'transcribing', 'scripting', 'awaiting_approval', 'voicing', 'writing',
        'completed', 'failed', 'cancelled')),
    preset JSONB NOT NULL,
    transcript JSONB,
    script JSONB,
    estimate JSONB,
    unsupported JSONB NOT NULL DEFAULT '{}'::jsonb,
    voices JSONB,
    stale_beats JSONB NOT NULL DEFAULT '[]'::jsonb,
    failure_code TEXT,
    created_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP
);
CREATE INDEX narrations_project ON narrations (project_id);

CREATE TABLE narration_presets (
    project_id TEXT PRIMARY KEY,
    preset JSONB NOT NULL,
    revision INTEGER NOT NULL CHECK (revision > 0),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE sfx_library (
    sfx_id TEXT PRIMARY KEY,
    file_name TEXT NOT NULL,
    location TEXT NOT NULL,
    checksum TEXT NOT NULL UNIQUE,
    duration_seconds DOUBLE PRECISION NOT NULL CHECK (duration_seconds > 0),
    labels JSONB NOT NULL DEFAULT '{}'::jsonb,
    created_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP
);
