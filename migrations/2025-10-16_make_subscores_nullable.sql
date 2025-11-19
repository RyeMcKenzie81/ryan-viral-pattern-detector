-- Migration: Make subscore columns nullable in video_scores table
-- Date: 2025-10-16
-- Reason: Scorer v1.2.0 uses continuous formulas that don't decompose into subscores
--         It calculates overall score directly and returns null for all subscores
-- Branch: fix/scorer-database-schema

-- Make all subscore columns nullable to match scorer v1.2.0 output
ALTER TABLE video_scores
  ALTER COLUMN hook_score DROP NOT NULL,
  ALTER COLUMN story_score DROP NOT NULL,
  ALTER COLUMN relatability_score DROP NOT NULL,
  ALTER COLUMN visuals_score DROP NOT NULL,
  ALTER COLUMN audio_score DROP NOT NULL,
  ALTER COLUMN watchtime_score DROP NOT NULL,
  ALTER COLUMN engagement_score DROP NOT NULL,
  ALTER COLUMN shareability_score DROP NOT NULL,
  ALTER COLUMN algo_score DROP NOT NULL;

-- Verify the changes (optional - run to check)
-- SELECT column_name, is_nullable
-- FROM information_schema.columns
-- WHERE table_name = 'video_scores'
-- AND column_name LIKE '%_score'
-- ORDER BY column_name;

-- Expected result after migration:
-- All 9 subscore columns should show is_nullable = 'YES'
-- overall_score should remain NOT NULL (scorer always provides this)
