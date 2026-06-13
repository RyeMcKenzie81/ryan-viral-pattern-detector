-- Migration: Recalibrate quality_scoring_config thresholds to the pinned review model
-- Date: 2026-06-12
-- Purpose: Google retired gemini-3-pro-preview and repointed the floating
--   "gemini-pro-latest" alias to 3.1, which grades the ad-review rubric ~2.3
--   points lower on a compressed scale. The 7.0 pass threshold sat above the
--   new model's ceiling, so every ad landed flagged. Thresholds below were
--   derived from a 12-ad calibration set (May ads with known outcomes
--   re-reviewed under gemini-3.1-pro-preview): old-approved scored 5.40-6.22,
--   old-rejected 4.54-4.99.
--   PAIRED WITH the code change pinning Config.VISION_MODEL to
--   gemini-3.1-pro-preview (fix/review-model-pin-recalibration). If the model
--   is ever bumped, re-run the calibration and update BOTH together.
--   (Already applied to production manually on 2026-06-12; kept here so the
--   change is reproducible on restore / other environments.)

UPDATE quality_scoring_config
SET pass_threshold = 5.5,
    borderline_range = '{"low": 4.9, "high": 5.5}'::jsonb
WHERE organization_id IS NULL
  AND is_active = true;
