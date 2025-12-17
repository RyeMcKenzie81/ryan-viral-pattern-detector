-- Migration: Add belief plan metadata to generated_ads
-- Date: 2025-12-17
-- Purpose: Link generated ads to their angles, templates, and copy scaffolds
--          so users can see which ads test which beliefs and what copy goes with them

-- Add angle reference
ALTER TABLE generated_ads ADD COLUMN IF NOT EXISTS angle_id UUID REFERENCES belief_angles(id);

-- Add template reference (no FK since templates can be from different tables)
ALTER TABLE generated_ads ADD COLUMN IF NOT EXISTS template_id UUID;

-- Add belief plan reference
ALTER TABLE generated_ads ADD COLUMN IF NOT EXISTS belief_plan_id UUID REFERENCES belief_plans(id);

-- Add copy scaffold fields (what shows in Meta ad placement)
ALTER TABLE generated_ads ADD COLUMN IF NOT EXISTS meta_headline TEXT;
ALTER TABLE generated_ads ADD COLUMN IF NOT EXISTS meta_primary_text TEXT;

-- Indexes for efficient queries
CREATE INDEX IF NOT EXISTS idx_generated_ads_angle ON generated_ads(angle_id);
CREATE INDEX IF NOT EXISTS idx_generated_ads_belief_plan ON generated_ads(belief_plan_id);
CREATE INDEX IF NOT EXISTS idx_generated_ads_template ON generated_ads(template_id);

-- Comments for documentation
COMMENT ON COLUMN generated_ads.angle_id IS 'Which belief angle this ad tests';
COMMENT ON COLUMN generated_ads.template_id IS 'Which template was used as style reference';
COMMENT ON COLUMN generated_ads.belief_plan_id IS 'Which belief plan this ad belongs to';
COMMENT ON COLUMN generated_ads.meta_headline IS 'Headline for Meta ad (below image) - angle + reframe';
COMMENT ON COLUMN generated_ads.meta_primary_text IS 'Primary text for Meta ad (above image) - full copy scaffold';
