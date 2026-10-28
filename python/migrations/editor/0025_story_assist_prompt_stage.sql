-- Story mode (2026-10-27) registered the story_assist prompt stage in code only, so every
-- Prompt Lab table still refused it: an Assist model preference could never be saved.
ALTER TABLE prompt_template_revisions DROP CONSTRAINT prompt_template_revisions_stage_id_check,
    ADD CONSTRAINT prompt_template_revisions_stage_id_check
    CHECK (stage_id IN ('narrative_plan', 'visual_plan', 'caption_copy', 'story_assist'));
ALTER TABLE project_prompt_bindings DROP CONSTRAINT project_prompt_bindings_stage_id_check,
    ADD CONSTRAINT project_prompt_bindings_stage_id_check
    CHECK (stage_id IN ('narrative_plan', 'visual_plan', 'caption_copy', 'story_assist'));
ALTER TABLE prompt_provider_preferences DROP CONSTRAINT prompt_provider_preferences_stage_id_check,
    ADD CONSTRAINT prompt_provider_preferences_stage_id_check
    CHECK (stage_id IN ('narrative_plan', 'visual_plan', 'caption_copy', 'story_assist'));
ALTER TABLE prompt_layer_locks DROP CONSTRAINT prompt_layer_locks_stage_id_check,
    ADD CONSTRAINT prompt_layer_locks_stage_id_check
    CHECK (stage_id IN ('narrative_plan', 'visual_plan', 'caption_copy', 'story_assist'));
ALTER TABLE prompt_proposals DROP CONSTRAINT prompt_proposals_stage_id_check,
    ADD CONSTRAINT prompt_proposals_stage_id_check
    CHECK (stage_id IN ('narrative_plan', 'visual_plan', 'caption_copy', 'story_assist'));
ALTER TABLE prompt_proposal_applications DROP CONSTRAINT prompt_proposal_applications_stage_id_check,
    ADD CONSTRAINT prompt_proposal_applications_stage_id_check
    CHECK (stage_id IN ('narrative_plan', 'visual_plan', 'caption_copy', 'story_assist'));
