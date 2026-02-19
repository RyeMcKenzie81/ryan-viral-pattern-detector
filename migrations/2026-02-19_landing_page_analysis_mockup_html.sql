-- Migration: Add analysis_mockup_html to landing_page_analyses
-- Date: 2026-02-19
-- Purpose: Cache AI-generated analysis mockup HTML to avoid re-calling Gemini on page refresh.

ALTER TABLE landing_page_analyses
  ADD COLUMN IF NOT EXISTS analysis_mockup_html TEXT;

COMMENT ON COLUMN landing_page_analyses.analysis_mockup_html IS
  'Cached HTML from generate_analysis_mockup(). Avoids re-calling Gemini on refresh.';
