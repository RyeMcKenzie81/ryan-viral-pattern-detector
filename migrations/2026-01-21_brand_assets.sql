-- Migration: Brand Assets Table
-- Date: 2026-01-21
-- Purpose: Add brand_assets table for storing brand-level images (logos, etc.)
-- Following the same pattern as product_images table

-- Brand assets table for logos and other brand-level images
CREATE TABLE IF NOT EXISTS brand_assets (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    brand_id UUID NOT NULL REFERENCES brands(id) ON DELETE CASCADE,
    storage_path TEXT NOT NULL,
    asset_type VARCHAR(50) NOT NULL DEFAULT 'logo',  -- logo, logo_white, logo_dark, logo_horizontal, etc.
    filename TEXT,
    is_primary BOOLEAN DEFAULT FALSE,
    sort_order INTEGER DEFAULT 0,
    created_at TIMESTAMPTZ DEFAULT NOW(),
    updated_at TIMESTAMPTZ DEFAULT NOW(),

    -- Optional metadata (matching product_images pattern)
    image_analysis JSONB DEFAULT NULL,
    analyzed_at TIMESTAMPTZ,
    notes TEXT
);

-- Indexes for efficient queries
CREATE INDEX IF NOT EXISTS idx_brand_assets_brand_id ON brand_assets(brand_id);
CREATE INDEX IF NOT EXISTS idx_brand_assets_type ON brand_assets(asset_type);
CREATE INDEX IF NOT EXISTS idx_brand_assets_primary ON brand_assets(brand_id, is_primary) WHERE is_primary = TRUE;

-- Comments for documentation
COMMENT ON TABLE brand_assets IS 'Brand-level images like logos, following the product_images pattern';
COMMENT ON COLUMN brand_assets.asset_type IS 'Type of asset: logo, logo_white, logo_dark, logo_horizontal, etc.';
COMMENT ON COLUMN brand_assets.is_primary IS 'Whether this is the primary asset of its type for the brand';
COMMENT ON COLUMN brand_assets.image_analysis IS 'AI analysis results (colors, style, etc.) in JSONB format';

-- Note: Storage bucket 'brand-assets' should be created in Supabase dashboard
-- Storage pattern: brand-assets/{brand_id}/logo_{variant}.{ext}
