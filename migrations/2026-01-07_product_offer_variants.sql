-- Migration: Product Offer Variants
-- Date: 2026-01-07
-- Purpose: Enable products to have multiple landing page variants with distinct messaging
-- Part of: Product Offer Variants feature

-- ============================================
-- Table: product_offer_variants
-- Links products to landing pages with messaging context
-- ============================================
CREATE TABLE IF NOT EXISTS product_offer_variants (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    product_id UUID NOT NULL REFERENCES products(id) ON DELETE CASCADE,

    -- Identification
    name TEXT NOT NULL,                           -- e.g., "Blood Pressure Angle"
    slug TEXT NOT NULL,                           -- e.g., "blood-pressure"

    -- Destination (REQUIRED)
    landing_page_url TEXT NOT NULL,               -- e.g., "https://infiniteage.com/bp"

    -- Messaging Context
    pain_points TEXT[] DEFAULT '{}',              -- ["high blood pressure", "cholesterol"]
    desires_goals TEXT[] DEFAULT '{}',            -- ["heart health", "better energy"]
    benefits TEXT[] DEFAULT '{}',                 -- ["supports healthy BP", "promotes circulation"]
    target_audience TEXT,                         -- Optional demographics override

    -- State
    is_default BOOLEAN DEFAULT false,             -- Which variant to use if not specified
    is_active BOOLEAN DEFAULT true,
    display_order INT DEFAULT 0,

    -- Metadata
    notes TEXT,                                   -- Internal notes for team

    -- Timestamps
    created_at TIMESTAMPTZ DEFAULT NOW(),
    updated_at TIMESTAMPTZ DEFAULT NOW(),

    -- Constraints
    UNIQUE(product_id, slug)
);

-- ============================================
-- Indexes
-- ============================================
CREATE INDEX IF NOT EXISTS idx_pov_product_id ON product_offer_variants(product_id);
CREATE INDEX IF NOT EXISTS idx_pov_is_active ON product_offer_variants(is_active);

-- Ensure only one default per product (partial unique index)
CREATE UNIQUE INDEX IF NOT EXISTS idx_pov_single_default
    ON product_offer_variants(product_id)
    WHERE is_default = true;

-- ============================================
-- Trigger: Auto-update updated_at
-- ============================================
CREATE OR REPLACE FUNCTION update_product_offer_variants_updated_at()
RETURNS TRIGGER AS $$
BEGIN
    NEW.updated_at = NOW();
    RETURN NEW;
END;
$$ LANGUAGE plpgsql;

DROP TRIGGER IF EXISTS trigger_pov_updated_at ON product_offer_variants;
CREATE TRIGGER trigger_pov_updated_at
    BEFORE UPDATE ON product_offer_variants
    FOR EACH ROW
    EXECUTE FUNCTION update_product_offer_variants_updated_at();

-- ============================================
-- Extend generated_ads table
-- ============================================
ALTER TABLE generated_ads ADD COLUMN IF NOT EXISTS destination_url TEXT;
ALTER TABLE generated_ads ADD COLUMN IF NOT EXISTS
    offer_variant_id UUID REFERENCES product_offer_variants(id) ON DELETE SET NULL;

CREATE INDEX IF NOT EXISTS idx_generated_ads_offer_variant ON generated_ads(offer_variant_id);

-- ============================================
-- Comments
-- ============================================
COMMENT ON TABLE product_offer_variants IS 'Product offer variants with landing page URLs and messaging context for ad creation. Each variant represents a different marketing angle for the same product.';
COMMENT ON COLUMN product_offer_variants.name IS 'Display name for the variant (e.g., "Blood Pressure Angle")';
COMMENT ON COLUMN product_offer_variants.slug IS 'URL-safe identifier, unique per product';
COMMENT ON COLUMN product_offer_variants.landing_page_url IS 'The landing page URL for ads using this variant (REQUIRED)';
COMMENT ON COLUMN product_offer_variants.pain_points IS 'Pain points this landing page addresses - array of strings';
COMMENT ON COLUMN product_offer_variants.desires_goals IS 'Desires and goals this offer targets - array of strings';
COMMENT ON COLUMN product_offer_variants.benefits IS 'Key benefits to highlight in ads - array of strings';
COMMENT ON COLUMN product_offer_variants.target_audience IS 'Optional target audience override (demographics, etc.)';
COMMENT ON COLUMN product_offer_variants.is_default IS 'Default offer variant when none specified. Only one per product allowed.';
COMMENT ON COLUMN generated_ads.destination_url IS 'Landing page URL for this ad';
COMMENT ON COLUMN generated_ads.offer_variant_id IS 'Product offer variant used for generating this ad';

-- ============================================
-- MIGRATION COMPLETE
-- ============================================
-- New table: product_offer_variants
-- Extended: generated_ads with destination_url and offer_variant_id
-- ============================================
