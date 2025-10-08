-- Test script for 04_video_scores.sql migration
-- Run this AFTER the migration to verify everything works

-- ============================================================================
-- Test 1: Insert a sample score and verify trigger fires
-- ============================================================================

DO $test$
DECLARE
  test_post_id UUID;
  test_overall_score FLOAT;
  va_overall_score FLOAT;
BEGIN
  -- Get a real post_id from your database that has video_analysis
  SELECT va.post_id INTO test_post_id
  FROM video_analysis va
  LIMIT 1;

  IF test_post_id IS NULL THEN
    RAISE NOTICE 'No analyzed videos found - skipping trigger test';
    RETURN;
  END IF;

  RAISE NOTICE 'Testing with post_id: %', test_post_id;

  -- Insert test score
  INSERT INTO video_scores
    (post_id, scorer_version, hook_score, story_score, relatability_score,
     visuals_score, audio_score, watchtime_score, engagement_score,
     shareability_score, algo_score, penalties_score, overall_score, score_details)
  VALUES
    (test_post_id, '1.0.0-test', 90, 80, 70, 85, 88, 92, 75, 81, 65, 5, 82.3,
     '{"weights":{"watchtime":0.25},"flags":{"incomplete":false}}'::jsonb)
  ON CONFLICT (post_id, scorer_version) DO UPDATE
    SET overall_score = EXCLUDED.overall_score,
        scored_at = NOW();

  -- Verify trigger updated video_analysis
  SELECT overall_score INTO va_overall_score
  FROM video_analysis
  WHERE post_id = test_post_id;

  IF va_overall_score = 82.3 THEN
    RAISE NOTICE '✅ Test passed: Trigger synced overall_score (%.1f)', va_overall_score;
  ELSE
    RAISE EXCEPTION 'Test failed: Expected 82.3, got %', va_overall_score;
  END IF;

  -- Clean up test data
  DELETE FROM video_scores WHERE post_id = test_post_id AND scorer_version = '1.0.0-test';

  RAISE NOTICE '✅ Test cleanup complete';
END $test$;

-- ============================================================================
-- Test 2: Verify indexes exist
-- ============================================================================

DO $indexes$
DECLARE
  idx_count INT;
BEGIN
  SELECT COUNT(*) INTO idx_count
  FROM pg_indexes
  WHERE tablename = 'video_scores'
    AND indexname IN (
      'idx_video_scores_post_id',
      'idx_video_scores_overall',
      'idx_video_scores_scored_at',
      'idx_video_scores_version',
      'idx_video_scores_post_latest',
      'idx_video_scores_details_gin'
    );

  IF idx_count = 6 THEN
    RAISE NOTICE '✅ All 6 indexes created successfully';
  ELSE
    RAISE WARNING 'Expected 6 indexes, found %', idx_count;
  END IF;
END $indexes$;

-- ============================================================================
-- Test 3: Verify views work
-- ============================================================================

DO $views$
DECLARE
  latest_count INT;
  full_count INT;
BEGIN
  SELECT COUNT(*) INTO latest_count FROM video_scores_latest;
  SELECT COUNT(*) INTO full_count FROM scored_videos_full;

  RAISE NOTICE '✅ Views accessible: video_scores_latest (% rows), scored_videos_full (% rows)',
    latest_count, full_count;
END $views$;

-- ============================================================================
-- Test 4: Verify RLS is enabled
-- ============================================================================

DO $rls$
DECLARE
  rls_enabled BOOLEAN;
BEGIN
  SELECT relrowsecurity INTO rls_enabled
  FROM pg_class
  WHERE relname = 'video_scores';

  IF rls_enabled THEN
    RAISE NOTICE '✅ RLS enabled on video_scores table';
  ELSE
    RAISE WARNING 'RLS not enabled on video_scores table';
  END IF;
END $rls$;

-- ============================================================================
-- Summary
-- ============================================================================

RAISE NOTICE '';
RAISE NOTICE '========================================';
RAISE NOTICE 'Migration validation complete!';
RAISE NOTICE 'Next step: Test scoring from Python CLI';
RAISE NOTICE '========================================';
