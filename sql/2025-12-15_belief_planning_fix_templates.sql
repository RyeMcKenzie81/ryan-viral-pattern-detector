-- ============================================
-- FIX: Allow scraped templates in belief_plan_templates
-- Migration: 2025-12-15 (hotfix)
--
-- Problem: belief_plan_templates.template_id references only ad_brief_templates
-- But we also want to use scraped_templates
--
-- Solution: Remove FK constraint and add template_source column
-- ============================================

-- Drop the existing foreign key constraint
ALTER TABLE belief_plan_templates
DROP CONSTRAINT IF EXISTS belief_plan_templates_template_id_fkey;

-- Add a column to track which table the template comes from
ALTER TABLE belief_plan_templates
ADD COLUMN IF NOT EXISTS template_source TEXT DEFAULT 'ad_brief_templates'
CHECK (template_source IN ('ad_brief_templates', 'scraped_templates'));

COMMENT ON COLUMN belief_plan_templates.template_source IS 'Which table the template_id references: ad_brief_templates or scraped_templates';

-- ============================================
-- DONE
-- ============================================
