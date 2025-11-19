-- Phase 6: Video Scoring System
-- Creates tables and triggers for deterministic video scoring

-- Enable pgcrypto for gen_random_uuid()
CREATE EXTENSION IF NOT EXISTS pgcrypto;

-- ============================================================================
-- 1. Create video_scores table
-- ============================================================================

CREATE TABLE IF NOT EXISTS video_scores (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  post_id UUID NOT NULL REFERENCES posts(id) ON DELETE CASCADE,

  -- Metadata
  scorer_version TEXT NOT NULL DEFAULT '1.0.0',
  scored_at TIMESTAMP WITH TIME ZONE NOT NULL DEFAULT NOW(),

  -- 9 Subscores (0-100 each)
  hook_score FLOAT NOT NULL CHECK (hook_score >= 0 AND hook_score <= 100),
  story_score FLOAT NOT NULL CHECK (story_score >= 0 AND story_score <= 100),
  relatability_score FLOAT NOT NULL CHECK (relatability_score >= 0 AND relatability_score <= 100),
  visuals_score FLOAT NOT NULL CHECK (visuals_score >= 0 AND visuals_score <= 100),
  audio_score FLOAT NOT NULL CHECK (audio_score >= 0 AND audio_score <= 100),
  watchtime_score FLOAT NOT NULL CHECK (watchtime_score >= 0 AND watchtime_score <= 100),
  engagement_score FLOAT NOT NULL CHECK (engagement_score >= 0 AND engagement_score <= 100),
  shareability_score FLOAT NOT NULL CHECK (shareability_score >= 0 AND shareability_score <= 100),
  algo_score FLOAT NOT NULL CHECK (algo_score >= 0 AND algo_score <= 100),

  -- Penalties
  penalties_score FLOAT NOT NULL DEFAULT 0 CHECK (penalties_score >= 0),

  -- Overall score (computed by TypeScript scorer, stored as-is)
  -- This allows per-row weights, normalization, and future tuning flexibility
  overall_score FLOAT NOT NULL CHECK (overall_score >= 0 AND overall_score <= 100),

  -- Full scoring details (JSON with weights used, feature flags, diagnostics, etc.)
  score_details JSONB,

  -- Constraints
  UNIQUE(post_id, scorer_version)
);

-- Comments for documentation
COMMENT ON TABLE video_scores IS 'Deterministic scoring results from TypeScript evaluator';
COMMENT ON COLUMN video_scores.scorer_version IS 'Scorer version (allows re-scoring with different versions)';
COMMENT ON COLUMN video_scores.overall_score IS 'Weighted average of subscores minus penalties (0-100)';
COMMENT ON COLUMN video_scores.penalties_score IS 'Deductions for negative signals (spam, low quality, etc.)';
COMMENT ON COLUMN video_scores.score_details IS 'Full scorer output: weights, diagnostics, confidence, flags';

-- Indexes for performance
CREATE INDEX IF NOT EXISTS idx_video_scores_post_id ON video_scores(post_id);
CREATE INDEX IF NOT EXISTS idx_video_scores_overall ON video_scores(overall_score DESC);
CREATE INDEX IF NOT EXISTS idx_video_scores_scored_at ON video_scores(scored_at DESC);
CREATE INDEX IF NOT EXISTS idx_video_scores_version ON video_scores(scorer_version);

-- Partial index for latest scores only (unique constraint, no IF NOT EXISTS)
DROP INDEX IF EXISTS idx_video_scores_post_latest;
CREATE UNIQUE INDEX idx_video_scores_post_latest
  ON video_scores(post_id)
  WHERE scorer_version = '1.0.0';

-- GIN index on JSONB for filtering on details (flags/diagnostics/weights)
CREATE INDEX IF NOT EXISTS idx_video_scores_details_gin
  ON video_scores USING GIN (score_details jsonb_path_ops);

-- ============================================================================
-- 2. Add denormalized columns to video_analysis
-- ============================================================================

-- Add convenience columns for quick queries (denormalized from video_scores)
ALTER TABLE video_analysis
  ADD COLUMN IF NOT EXISTS overall_score FLOAT,
  ADD COLUMN IF NOT EXISTS scored_at TIMESTAMP WITH TIME ZONE;

COMMENT ON COLUMN video_analysis.overall_score IS 'Denormalized from video_scores for quick filtering';
COMMENT ON COLUMN video_analysis.scored_at IS 'Timestamp when video was last scored';

-- Index for sorting by score
CREATE INDEX IF NOT EXISTS idx_video_analysis_overall_score
  ON video_analysis(overall_score DESC NULLS LAST);

-- ============================================================================
-- 3. Trigger to sync overall_score between tables
-- ============================================================================

-- Function to sync overall_score from video_scores to video_analysis
CREATE OR REPLACE FUNCTION sync_overall_score()
RETURNS TRIGGER AS $sync_overall_score$
BEGIN
  UPDATE video_analysis
  SET
    overall_score = NEW.overall_score,
    scored_at = NEW.scored_at
  WHERE post_id = NEW.post_id;

  RETURN NEW;
END;
$sync_overall_score$ LANGUAGE plpgsql;

-- Trigger fires after INSERT or UPDATE on video_scores
DROP TRIGGER IF EXISTS sync_score_to_analysis ON video_scores;
CREATE TRIGGER sync_score_to_analysis
  AFTER INSERT OR UPDATE OF overall_score, scored_at ON video_scores
  FOR EACH ROW
  EXECUTE FUNCTION sync_overall_score();

-- ============================================================================
-- 4. Helper views for common queries
-- ============================================================================

-- View: Latest scores for each video (newest scorer_version, then newest scored_at)
CREATE OR REPLACE VIEW video_scores_latest AS
SELECT DISTINCT ON (post_id)
  vs.*
FROM video_scores vs
ORDER BY post_id, scorer_version DESC, scored_at DESC;

COMMENT ON VIEW video_scores_latest IS 'Latest score per post (newest scorer_version, then newest scored_at)';

-- View: Scored videos with full metadata
CREATE OR REPLACE VIEW scored_videos_full AS
SELECT
  p.id as post_id,
  p.created_at as posted_at,
  va.hook_transcript,
  va.hook_type,
  va.overall_score,
  va.scored_at,
  vs.hook_score,
  vs.story_score,
  vs.relatability_score,
  vs.visuals_score,
  vs.audio_score,
  vs.watchtime_score,
  vs.engagement_score,
  vs.shareability_score,
  vs.algo_score,
  vs.penalties_score,
  vs.scorer_version,
  vs.score_details
FROM posts p
JOIN video_analysis va ON p.id = va.post_id
LEFT JOIN video_scores_latest vs ON p.id = vs.post_id
WHERE va.overall_score IS NOT NULL
ORDER BY va.overall_score DESC NULLS LAST;

COMMENT ON VIEW scored_videos_full IS 'Full metadata for scored videos with all subscores';

-- ============================================================================
-- 5. Row-Level Security (RLS)
-- ============================================================================

-- Enable RLS for production security
ALTER TABLE video_scores ENABLE ROW LEVEL SECURITY;

-- Allow read access to all authenticated users (adjust as needed)
CREATE POLICY video_scores_read ON video_scores
  FOR SELECT
  USING (true);

-- Restrict writes to service role (configured at application layer)
-- No write policy = only service role can INSERT/UPDATE/DELETE

-- ============================================================================
-- 6. Migration validation
-- ============================================================================

-- Verify table structure
DO $validation$
BEGIN
  ASSERT (SELECT COUNT(*) FROM information_schema.tables
          WHERE table_name = 'video_scores') = 1,
         'video_scores table not created';

  ASSERT (SELECT COUNT(*) FROM information_schema.columns
          WHERE table_name = 'video_analysis' AND column_name = 'overall_score') = 1,
         'overall_score column not added to video_analysis';

  RAISE NOTICE 'Migration 04_video_scores.sql completed successfully';
END $validation$;
