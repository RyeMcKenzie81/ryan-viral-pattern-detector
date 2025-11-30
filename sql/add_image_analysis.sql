-- Create product_images table with Vision AI analysis support
-- This table stores product images and their AI analysis for smart auto-selection

-- Create the table if it doesn't exist
CREATE TABLE IF NOT EXISTS product_images (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    product_id UUID NOT NULL REFERENCES products(id) ON DELETE CASCADE,
    storage_path TEXT NOT NULL,
    filename TEXT,
    is_main BOOLEAN DEFAULT FALSE,
    sort_order INTEGER DEFAULT 0,
    created_at TIMESTAMP WITH TIME ZONE DEFAULT NOW(),
    updated_at TIMESTAMP WITH TIME ZONE DEFAULT NOW(),

    -- Image analysis columns (for Vision AI smart selection)
    image_analysis JSONB DEFAULT NULL,
    analyzed_at TIMESTAMP WITH TIME ZONE DEFAULT NULL,
    analysis_model VARCHAR(100) DEFAULT NULL,
    analysis_version VARCHAR(20) DEFAULT NULL
);

-- If table already exists, add the analysis columns
ALTER TABLE product_images
ADD COLUMN IF NOT EXISTS image_analysis JSONB DEFAULT NULL;

ALTER TABLE product_images
ADD COLUMN IF NOT EXISTS analyzed_at TIMESTAMP WITH TIME ZONE DEFAULT NULL;

ALTER TABLE product_images
ADD COLUMN IF NOT EXISTS analysis_model VARCHAR(100) DEFAULT NULL;

ALTER TABLE product_images
ADD COLUMN IF NOT EXISTS analysis_version VARCHAR(20) DEFAULT NULL;

-- Indexes
CREATE INDEX IF NOT EXISTS idx_product_images_product_id
ON product_images(product_id);

CREATE INDEX IF NOT EXISTS idx_product_images_is_main
ON product_images(product_id)
WHERE is_main = TRUE;

CREATE INDEX IF NOT EXISTS idx_product_images_unanalyzed
ON product_images(product_id)
WHERE analyzed_at IS NULL;

CREATE INDEX IF NOT EXISTS idx_product_images_analyzed_at
ON product_images(analyzed_at DESC)
WHERE analyzed_at IS NOT NULL;

CREATE INDEX IF NOT EXISTS idx_product_images_quality
ON product_images((image_analysis->>'quality_score'))
WHERE image_analysis IS NOT NULL;

-- Comments
COMMENT ON TABLE product_images IS 'Product images with Vision AI analysis for smart selection';
COMMENT ON COLUMN product_images.image_analysis IS 'Vision AI analysis stored as JSONB (ProductImageAnalysis schema)';
COMMENT ON COLUMN product_images.analyzed_at IS 'Timestamp when image was analyzed by Vision AI';
COMMENT ON COLUMN product_images.analysis_model IS 'Model used for analysis (e.g., claude-opus-4-5-20251101)';
COMMENT ON COLUMN product_images.analysis_version IS 'Version of analysis schema/prompt (e.g., v1)';

-- ============================================================================
-- Verification query
-- ============================================================================

SELECT
    column_name,
    data_type,
    is_nullable
FROM information_schema.columns
WHERE table_name = 'product_images'
ORDER BY ordinal_position;
