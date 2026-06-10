-- Migration: track which awareness prompt version graded each template
-- Date: 2026-06-10
-- Purpose: Template awareness is now judged by the shared calibrated AWARENESS_RUBRIC
--   (template prompt v2, same judge model as the ads path). This column records the
--   version that graded each row so stale templates are queryable after future rubric
--   bumps (WHERE awareness_prompt_version IS DISTINCT FROM '<current>') and the
--   library backfill is resumable/idempotent. NULL = legacy v1 (bare 1-5 prompt) or
--   an ungraded row.
-- NOTE: the 1-5 CHECK on awareness_level already exists
--   (sql/2025-12-04_template_ai_analysis_fields.sql) — not re-added here.

ALTER TABLE scraped_templates
    ADD COLUMN IF NOT EXISTS awareness_prompt_version TEXT;

COMMENT ON COLUMN scraped_templates.awareness_prompt_version IS
    'TEMPLATE_ANALYSIS_PROMPT_VERSION that graded awareness_level (v2 = shared '
    'calibrated AWARENESS_RUBRIC on gemini-pro-latest). NULL = legacy bare-prompt '
    'grade or ungraded. Stale set: WHERE awareness_prompt_version IS DISTINCT FROM current.';

CREATE INDEX IF NOT EXISTS idx_scraped_templates_awareness_version
    ON scraped_templates (awareness_prompt_version);
