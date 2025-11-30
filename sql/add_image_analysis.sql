-- Add image analysis columns to product_images table
-- Stores Vision AI analysis for smart product image selection

-- Add image_analysis JSONB column
-- Stores ProductImageAnalysis schema from viraltracker/agent/schemas/image_analysis.py
ALTER TABLE product_images
ADD COLUMN IF NOT EXISTS image_analysis JSONB DEFAULT NULL;

-- Add timestamp for when image was analyzed
ALTER TABLE product_images
ADD COLUMN IF NOT EXISTS analyzed_at TIMESTAMP WITH TIME ZONE DEFAULT NULL;

-- Add model used for analysis (for tracking/debugging)
ALTER TABLE product_images
ADD COLUMN IF NOT EXISTS analysis_model VARCHAR(100) DEFAULT NULL;

-- Add analysis version for schema migrations
ALTER TABLE product_images
ADD COLUMN IF NOT EXISTS analysis_version VARCHAR(20) DEFAULT NULL;

-- Index for finding unanalyzed images
CREATE INDEX IF NOT EXISTS idx_product_images_unanalyzed
ON product_images(product_id)
WHERE analyzed_at IS NULL;

-- Index for querying by analysis date
CREATE INDEX IF NOT EXISTS idx_product_images_analyzed_at
ON product_images(analyzed_at DESC)
WHERE analyzed_at IS NOT NULL;

-- Index for querying by quality score (JSONB path)
CREATE INDEX IF NOT EXISTS idx_product_images_quality
ON product_images((image_analysis->>'quality_score'))
WHERE image_analysis IS NOT NULL;

-- Comments
COMMENT ON COLUMN product_images.image_analysis IS 'Vision AI analysis stored as JSONB (ProductImageAnalysis schema)';
COMMENT ON COLUMN product_images.analyzed_at IS 'Timestamp when image was analyzed by Vision AI';
COMMENT ON COLUMN product_images.analysis_model IS 'Model used for analysis (e.g., claude-opus-4-5-20251101)';
COMMENT ON COLUMN product_images.analysis_version IS 'Version of analysis schema/prompt (e.g., v1)';

-- ============================================================================
-- Verification query
-- ============================================================================

-- Check columns were added
SELECT
    column_name,
    data_type,
    is_nullable
FROM information_schema.columns
WHERE table_name = 'product_images'
AND column_name IN ('image_analysis', 'analyzed_at', 'analysis_model', 'analysis_version')
ORDER BY column_name;
