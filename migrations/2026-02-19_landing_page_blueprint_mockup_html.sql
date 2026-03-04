-- Migration: Add blueprint_mockup_html to landing_page_blueprints
-- Date: 2026-02-19
-- Purpose: Cache AI-rewritten blueprint mockup HTML to avoid re-calling Claude on page refresh.

ALTER TABLE landing_page_blueprints
  ADD COLUMN IF NOT EXISTS blueprint_mockup_html TEXT;

COMMENT ON COLUMN landing_page_blueprints.blueprint_mockup_html IS
  'Cached HTML from generate_blueprint_mockup(). Avoids re-calling Claude AI rewrite on refresh.';
