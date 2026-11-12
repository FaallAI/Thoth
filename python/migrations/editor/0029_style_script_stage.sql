-- Style templates (spec 2026-11-10): the style_script prompt stage, whose project binding is kept
-- per style template (variant). Every existing binding keeps variant '' and reads as before.
-- Rollback: images before 0029 read bindings by (project_id, stage_id) and never see a style row;
-- style_script rows stay harmless until removed.
ALTER TABLE prompt_template_revisions DROP CONSTRAINT prompt_template_revisions_stage_id_check,
    ADD CONSTRAINT prompt_template_revisions_stage_id_check
    CHECK (stage_id IN ('narrative_plan', 'visual_plan', 'caption_copy', 'story_assist', 'narration_script', 'style_script'));
ALTER TABLE project_prompt_bindings DROP CONSTRAINT project_prompt_bindings_stage_id_check,
    ADD CONSTRAINT project_prompt_bindings_stage_id_check
    CHECK (stage_id IN ('narrative_plan', 'visual_plan', 'caption_copy', 'story_assist', 'narration_script', 'style_script'));
ALTER TABLE prompt_provider_preferences DROP CONSTRAINT prompt_provider_preferences_stage_id_check,
    ADD CONSTRAINT prompt_provider_preferences_stage_id_check
    CHECK (stage_id IN ('narrative_plan', 'visual_plan', 'caption_copy', 'story_assist', 'narration_script', 'style_script'));
ALTER TABLE prompt_layer_locks DROP CONSTRAINT prompt_layer_locks_stage_id_check,
    ADD CONSTRAINT prompt_layer_locks_stage_id_check
    CHECK (stage_id IN ('narrative_plan', 'visual_plan', 'caption_copy', 'story_assist', 'narration_script', 'style_script'));
ALTER TABLE prompt_proposals DROP CONSTRAINT prompt_proposals_stage_id_check,
    ADD CONSTRAINT prompt_proposals_stage_id_check
    CHECK (stage_id IN ('narrative_plan', 'visual_plan', 'caption_copy', 'story_assist', 'narration_script', 'style_script'));
ALTER TABLE prompt_proposal_applications DROP CONSTRAINT prompt_proposal_applications_stage_id_check,
    ADD CONSTRAINT prompt_proposal_applications_stage_id_check
    CHECK (stage_id IN ('narrative_plan', 'visual_plan', 'caption_copy', 'story_assist', 'narration_script', 'style_script'));

ALTER TABLE project_prompt_bindings ADD COLUMN variant TEXT NOT NULL DEFAULT '';
ALTER TABLE project_prompt_bindings DROP CONSTRAINT project_prompt_bindings_pkey,
    ADD PRIMARY KEY (project_id, stage_id, variant);
