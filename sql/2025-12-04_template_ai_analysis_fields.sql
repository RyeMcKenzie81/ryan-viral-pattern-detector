-- Migration: Add AI analysis fields to template approval workflow
-- Date: 2025-12-04
-- Purpose: Support two-step approval with AI-suggested metadata

-- =============================================================================
-- Step 1: Add new columns to scraped_templates table
-- =============================================================================

-- Source tracking (from facebook_ads)
ALTER TABLE scraped_templates ADD COLUMN IF NOT EXISTS source_brand TEXT;
COMMENT ON COLUMN scraped_templates.source_brand IS 'Brand/page name the ad was scraped from';

ALTER TABLE scraped_templates ADD COLUMN IF NOT EXISTS source_landing_page TEXT;
COMMENT ON COLUMN scraped_templates.source_landing_page IS 'Landing page URL from the ad';

-- Industry/niche classification
ALTER TABLE scraped_templates ADD COLUMN IF NOT EXISTS industry_niche TEXT;
COMMENT ON COLUMN scraped_templates.industry_niche IS 'Industry category: supplements, pets, skincare, fitness, etc.';

-- Target audience
ALTER TABLE scraped_templates ADD COLUMN IF NOT EXISTS target_sex TEXT CHECK (target_sex IN ('male', 'female', 'unisex'));
COMMENT ON COLUMN scraped_templates.target_sex IS 'Primary target gender: male, female, or unisex';

-- Consumer awareness level (Eugene Schwartz)
ALTER TABLE scraped_templates ADD COLUMN IF NOT EXISTS awareness_level INTEGER CHECK (awareness_level BETWEEN 1 AND 5);
COMMENT ON COLUMN scraped_templates.awareness_level IS 'Consumer awareness level 1-5 (Unaware to Most Aware)';

ALTER TABLE scraped_templates ADD COLUMN IF NOT EXISTS awareness_level_name TEXT;
COMMENT ON COLUMN scraped_templates.awareness_level_name IS 'Human-readable awareness level name';

-- Sales event tagging
ALTER TABLE scraped_templates ADD COLUMN IF NOT EXISTS sales_event TEXT;
COMMENT ON COLUMN scraped_templates.sales_event IS 'Sales event category if applicable: black_friday, cyber_monday, etc.';

-- AI analysis storage
ALTER TABLE scraped_templates ADD COLUMN IF NOT EXISTS ai_suggested_name TEXT;
COMMENT ON COLUMN scraped_templates.ai_suggested_name IS 'AI-generated template name suggestion';

ALTER TABLE scraped_templates ADD COLUMN IF NOT EXISTS ai_suggested_description TEXT;
COMMENT ON COLUMN scraped_templates.ai_suggested_description IS 'AI-generated template description';

ALTER TABLE scraped_templates ADD COLUMN IF NOT EXISTS ai_analysis_raw JSONB DEFAULT '{}';
COMMENT ON COLUMN scraped_templates.ai_analysis_raw IS 'Full AI analysis response for reference';

-- =============================================================================
-- Step 2: Update template_queue status to include 'pending_details'
-- =============================================================================

-- First, drop the existing check constraint if it exists
ALTER TABLE template_queue DROP CONSTRAINT IF EXISTS template_queue_status_check;

-- Add new check constraint with 'pending_details' status
ALTER TABLE template_queue ADD CONSTRAINT template_queue_status_check
    CHECK (status IN ('pending', 'pending_details', 'approved', 'rejected', 'archived'));

COMMENT ON COLUMN template_queue.status IS 'Review status: pending, pending_details (awaiting AI review confirmation), approved, rejected, archived';

-- =============================================================================
-- Step 3: Add AI suggestions storage to template_queue (for intermediate state)
-- =============================================================================

ALTER TABLE template_queue ADD COLUMN IF NOT EXISTS ai_suggestions JSONB DEFAULT '{}';
COMMENT ON COLUMN template_queue.ai_suggestions IS 'AI-generated suggestions awaiting user confirmation';

-- =============================================================================
-- Step 4: Create indexes for new columns
-- =============================================================================

CREATE INDEX IF NOT EXISTS idx_scraped_templates_industry ON scraped_templates(industry_niche);
CREATE INDEX IF NOT EXISTS idx_scraped_templates_awareness ON scraped_templates(awareness_level);
CREATE INDEX IF NOT EXISTS idx_scraped_templates_target_sex ON scraped_templates(target_sex);
CREATE INDEX IF NOT EXISTS idx_scraped_templates_sales_event ON scraped_templates(sales_event) WHERE sales_event IS NOT NULL;
