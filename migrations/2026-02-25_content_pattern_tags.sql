-- Migration: Content pattern tags on analyses
-- Date: 2026-02-25
-- Purpose: Add content_patterns JSONB and primary_content_pattern columns to
--          landing_page_analyses for deterministic pattern tagging (listicle, faq, etc.)

ALTER TABLE landing_page_analyses
  ADD COLUMN IF NOT EXISTS content_patterns JSONB DEFAULT '{}';

ALTER TABLE landing_page_analyses
  ADD COLUMN IF NOT EXISTS primary_content_pattern TEXT;

CREATE INDEX IF NOT EXISTS idx_lpa_content_pattern
  ON landing_page_analyses(primary_content_pattern)
  WHERE primary_content_pattern IS NOT NULL;

CREATE INDEX IF NOT EXISTS idx_lpa_content_patterns_gin
  ON landing_page_analyses USING GIN (content_patterns jsonb_path_ops);
