-- Migration: Template Element Detection Support
-- Date: 2026-01-21
-- Purpose: Add columns for template element detection and asset matching

-- Add template_elements JSONB to scraped_templates for storing detected elements
ALTER TABLE scraped_templates
ADD COLUMN IF NOT EXISTS template_elements JSONB DEFAULT '{}'::jsonb;

ALTER TABLE scraped_templates
ADD COLUMN IF NOT EXISTS element_detection_version TEXT;

ALTER TABLE scraped_templates
ADD COLUMN IF NOT EXISTS element_detection_at TIMESTAMPTZ;

-- Index for efficient querying of template elements
CREATE INDEX IF NOT EXISTS idx_scraped_templates_elements
ON scraped_templates USING GIN (template_elements);

-- Add asset_tags to product_images for matching
ALTER TABLE product_images
ADD COLUMN IF NOT EXISTS asset_tags JSONB DEFAULT '[]'::jsonb;

-- Index for efficient querying of asset tags
CREATE INDEX IF NOT EXISTS idx_product_images_asset_tags
ON product_images USING GIN (asset_tags);

-- Comments for documentation
COMMENT ON COLUMN scraped_templates.template_elements IS 'Detected visual elements in template (people, objects, text_areas, logo_areas, required_assets, optional_assets)';
COMMENT ON COLUMN scraped_templates.element_detection_version IS 'Version of the detection algorithm used';
COMMENT ON COLUMN scraped_templates.element_detection_at IS 'Timestamp when element detection was last run';
COMMENT ON COLUMN product_images.asset_tags IS 'Semantic tags for asset matching (e.g., ["person:vet", "product:bottle", "logo"])';
