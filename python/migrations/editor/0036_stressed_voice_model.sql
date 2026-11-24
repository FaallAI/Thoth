-- Stressed narration delivery (2026-11-24): projects still on the old default voice model
-- eleven_multilingual_v2 move to eleven_v4, which reads inline audio tags. A project that chose
-- its own model is left alone, and so is every stored narration's preset snapshot, so a single
-- beat re-voiced on an older draft keeps the voice its other beats have.
-- The revision steps so an open Studio tab cannot save the old model back unnoticed.
-- Rollback to an image before 0036: older images send voice_settings.speed, which eleven_v4
-- rejects, so first run
--   UPDATE narration_presets SET preset = jsonb_set(preset, '{voice_model}',
--     '"eleven_multilingual_v2"'::jsonb) WHERE preset->>'voice_model' = 'eleven_v4';
UPDATE narration_presets
SET preset = jsonb_set(preset, '{voice_model}', '"eleven_v4"'::jsonb),
    revision = revision + 1,
    updated_at = CURRENT_TIMESTAMP
WHERE preset->>'voice_model' = 'eleven_multilingual_v2';
