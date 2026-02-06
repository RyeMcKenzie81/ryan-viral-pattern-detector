-- Migration: Smart Ad Editing Support
-- Date: 2026-01-21
-- Purpose: Add columns to track edited ads and their relationships to parent ads

-- Add edit tracking columns to generated_ads
ALTER TABLE generated_ads
ADD COLUMN IF NOT EXISTS edit_parent_id UUID REFERENCES generated_ads(id);

ALTER TABLE generated_ads
ADD COLUMN IF NOT EXISTS edit_prompt TEXT;

ALTER TABLE generated_ads
ADD COLUMN IF NOT EXISTS edit_temperature DECIMAL(2,1);

ALTER TABLE generated_ads
ADD COLUMN IF NOT EXISTS is_edit BOOLEAN DEFAULT FALSE;

-- Index for efficient lookup of edit history
CREATE INDEX IF NOT EXISTS idx_generated_ads_edit_parent
ON generated_ads(edit_parent_id) WHERE edit_parent_id IS NOT NULL;

-- Comments for documentation
COMMENT ON COLUMN generated_ads.edit_parent_id IS 'UUID of the original ad this was edited from (NULL for original ads)';
COMMENT ON COLUMN generated_ads.edit_prompt IS 'The edit instruction used to modify the original ad';
COMMENT ON COLUMN generated_ads.edit_temperature IS 'Temperature used for the edit generation (0.0-1.0)';
COMMENT ON COLUMN generated_ads.is_edit IS 'True if this ad was created by editing another ad';
