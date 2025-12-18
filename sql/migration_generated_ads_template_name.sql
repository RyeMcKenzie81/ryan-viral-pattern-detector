-- Migration: Add template_name to generated_ads
-- Date: 2025-12-18
-- Purpose: Store template name for display without needing joins

ALTER TABLE generated_ads ADD COLUMN IF NOT EXISTS template_name TEXT;
COMMENT ON COLUMN generated_ads.template_name IS 'Name of template used as style reference';
