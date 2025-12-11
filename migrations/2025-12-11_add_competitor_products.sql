-- Migration: Add Competitor Products Support
-- Date: 2025-12-11
-- Purpose: Mirror brand product structure for competitors, enabling product-level
--          analysis and comparison (e.g., "your collagen" vs "their collagen")

-- ============================================================================
-- 1. COMPETITOR PRODUCTS TABLE (mirrors products)
-- ============================================================================

CREATE TABLE IF NOT EXISTS competitor_products (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    competitor_id UUID NOT NULL REFERENCES competitors(id) ON DELETE CASCADE,
    brand_id UUID NOT NULL REFERENCES brands(id) ON DELETE CASCADE,

    -- Product identity
    name TEXT NOT NULL,
    slug TEXT NOT NULL,
    description TEXT,
    product_code VARCHAR(4),  -- Short code for reference (optional)

    -- Status
    is_active BOOLEAN DEFAULT true,

    -- Timestamps
    created_at TIMESTAMPTZ DEFAULT NOW(),
    updated_at TIMESTAMPTZ DEFAULT NOW(),

    -- Constraints
    UNIQUE(competitor_id, slug)
);

-- Indexes for competitor_products
CREATE INDEX IF NOT EXISTS idx_competitor_products_competitor_id
    ON competitor_products(competitor_id);
CREATE INDEX IF NOT EXISTS idx_competitor_products_brand_id
    ON competitor_products(brand_id);
CREATE INDEX IF NOT EXISTS idx_competitor_products_slug
    ON competitor_products(slug);

COMMENT ON TABLE competitor_products IS 'Products sold by competitors, mirrors products table structure';
COMMENT ON COLUMN competitor_products.slug IS 'URL-safe identifier, unique per competitor';
COMMENT ON COLUMN competitor_products.product_code IS 'Short reference code (e.g., "WL1" for weight loss product 1)';

-- ============================================================================
-- 2. COMPETITOR PRODUCT VARIANTS TABLE (mirrors product_variants)
-- ============================================================================

CREATE TABLE IF NOT EXISTS competitor_product_variants (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    competitor_product_id UUID NOT NULL REFERENCES competitor_products(id) ON DELETE CASCADE,

    -- Variant identity
    name TEXT NOT NULL,  -- e.g., "Strawberry", "Large", "Bundle Pack"
    slug TEXT NOT NULL,
    sku TEXT,            -- Optional SKU/product code

    -- Variant type
    variant_type TEXT DEFAULT 'flavor' CHECK (variant_type IN ('flavor', 'size', 'color', 'bundle', 'other')),

    -- Details
    description TEXT,
    differentiators JSONB,  -- e.g., {"taste_profile": "fruity", "best_for": "morning use"}

    -- Pricing (if known)
    price DECIMAL(10,2),
    compare_at_price DECIMAL(10,2),

    -- Status & Display
    is_active BOOLEAN DEFAULT true,
    is_default BOOLEAN DEFAULT false,  -- Primary/hero variant
    display_order INT DEFAULT 0,

    -- Timestamps
    created_at TIMESTAMPTZ DEFAULT NOW(),
    updated_at TIMESTAMPTZ DEFAULT NOW(),

    -- Constraints
    UNIQUE(competitor_product_id, slug)
);

-- Indexes for competitor_product_variants
CREATE INDEX IF NOT EXISTS idx_competitor_product_variants_product_id
    ON competitor_product_variants(competitor_product_id);
CREATE INDEX IF NOT EXISTS idx_competitor_product_variants_variant_type
    ON competitor_product_variants(variant_type);
CREATE INDEX IF NOT EXISTS idx_competitor_product_variants_is_active
    ON competitor_product_variants(is_active);

COMMENT ON TABLE competitor_product_variants IS 'Product variants (flavors, sizes, colors) for competitor products';
COMMENT ON COLUMN competitor_product_variants.differentiators IS 'JSON object with variant-specific attributes';

-- ============================================================================
-- 3. COMPETITOR PRODUCT URLS TABLE (mirrors product_urls)
-- ============================================================================

CREATE TABLE IF NOT EXISTS competitor_product_urls (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    competitor_product_id UUID NOT NULL REFERENCES competitor_products(id) ON DELETE CASCADE,

    -- URL pattern matching
    url_pattern TEXT NOT NULL,
    match_type TEXT DEFAULT 'contains' CHECK (match_type IN ('exact', 'prefix', 'contains', 'regex')),

    -- Flags
    is_primary BOOLEAN DEFAULT false,   -- Main landing page
    is_fallback BOOLEAN DEFAULT false,  -- Fallback for research

    -- Metadata
    notes TEXT,

    -- Timestamps
    created_at TIMESTAMPTZ DEFAULT NOW(),
    updated_at TIMESTAMPTZ DEFAULT NOW(),

    -- Constraints
    UNIQUE(competitor_product_id, url_pattern)
);

-- Indexes for competitor_product_urls
CREATE INDEX IF NOT EXISTS idx_competitor_product_urls_product_id
    ON competitor_product_urls(competitor_product_id);
CREATE INDEX IF NOT EXISTS idx_competitor_product_urls_pattern
    ON competitor_product_urls(url_pattern);

COMMENT ON TABLE competitor_product_urls IS 'URL patterns for matching competitor ads to products';
COMMENT ON COLUMN competitor_product_urls.match_type IS 'How to match: exact, prefix, contains, or regex';

-- ============================================================================
-- 4. ALTER EXISTING TABLES TO ADD competitor_product_id
-- ============================================================================

-- 4a. competitor_ads - link ads to products
ALTER TABLE competitor_ads
    ADD COLUMN IF NOT EXISTS competitor_product_id UUID REFERENCES competitor_products(id) ON DELETE SET NULL;

ALTER TABLE competitor_ads
    ADD COLUMN IF NOT EXISTS product_match_confidence FLOAT;

ALTER TABLE competitor_ads
    ADD COLUMN IF NOT EXISTS product_match_method TEXT CHECK (product_match_method IN ('url', 'ai', 'manual'));

CREATE INDEX IF NOT EXISTS idx_competitor_ads_product_id
    ON competitor_ads(competitor_product_id);

COMMENT ON COLUMN competitor_ads.competitor_product_id IS 'Product this ad promotes (matched via URL or manual assignment)';
COMMENT ON COLUMN competitor_ads.product_match_confidence IS 'Confidence score 0.0-1.0 for URL-based matching';
COMMENT ON COLUMN competitor_ads.product_match_method IS 'How product was matched: url, ai, or manual';

-- 4b. competitor_amazon_urls - link Amazon products to competitor products
ALTER TABLE competitor_amazon_urls
    ADD COLUMN IF NOT EXISTS competitor_product_id UUID REFERENCES competitor_products(id) ON DELETE SET NULL;

CREATE INDEX IF NOT EXISTS idx_competitor_amazon_urls_product_id
    ON competitor_amazon_urls(competitor_product_id);

COMMENT ON COLUMN competitor_amazon_urls.competitor_product_id IS 'Competitor product this Amazon listing belongs to';

-- 4c. competitor_landing_pages - link landing pages to products
ALTER TABLE competitor_landing_pages
    ADD COLUMN IF NOT EXISTS competitor_product_id UUID REFERENCES competitor_products(id) ON DELETE SET NULL;

CREATE INDEX IF NOT EXISTS idx_competitor_landing_pages_product_id
    ON competitor_landing_pages(competitor_product_id);

COMMENT ON COLUMN competitor_landing_pages.competitor_product_id IS 'Competitor product this landing page promotes';

-- 4d. competitor_amazon_review_analysis - update unique constraint
-- First, drop the old unique constraint if it exists
DO $$
BEGIN
    -- Try to drop the old constraint (may not exist)
    ALTER TABLE competitor_amazon_review_analysis
        DROP CONSTRAINT IF EXISTS competitor_amazon_review_analysis_competitor_id_key;
EXCEPTION WHEN OTHERS THEN
    NULL; -- Ignore if doesn't exist
END $$;

-- Add competitor_product_id column
ALTER TABLE competitor_amazon_review_analysis
    ADD COLUMN IF NOT EXISTS competitor_product_id UUID REFERENCES competitor_products(id) ON DELETE CASCADE;

-- Add new unique constraint that allows either competitor-level OR product-level analysis
-- (competitor_id, competitor_product_id) where product_id can be NULL for competitor-level
CREATE UNIQUE INDEX IF NOT EXISTS idx_competitor_amazon_review_analysis_unique
    ON competitor_amazon_review_analysis(competitor_id, COALESCE(competitor_product_id, '00000000-0000-0000-0000-000000000000'::UUID));

COMMENT ON COLUMN competitor_amazon_review_analysis.competitor_product_id IS 'Product-level analysis (NULL for competitor-level)';

-- ============================================================================
-- 5. UPDATE personas_4d TABLE
-- ============================================================================

-- Add competitor_product_id for product-level competitor personas
ALTER TABLE personas_4d
    ADD COLUMN IF NOT EXISTS competitor_product_id UUID REFERENCES competitor_products(id) ON DELETE CASCADE;

CREATE INDEX IF NOT EXISTS idx_personas_4d_competitor_product_id
    ON personas_4d(competitor_product_id);

COMMENT ON COLUMN personas_4d.competitor_product_id IS 'For product-level competitor personas (optional, alternative to competitor_id)';

-- ============================================================================
-- 6. HELPER VIEW: Competitor Products with Variants
-- ============================================================================

CREATE OR REPLACE VIEW competitor_products_with_variants AS
SELECT
    cp.id AS product_id,
    cp.competitor_id,
    cp.brand_id,
    cp.name AS product_name,
    cp.slug AS product_slug,
    cp.description,
    cp.product_code,
    cp.is_active,
    cp.created_at,
    c.name AS competitor_name,
    COALESCE(
        json_agg(
            json_build_object(
                'id', cpv.id,
                'name', cpv.name,
                'slug', cpv.slug,
                'variant_type', cpv.variant_type,
                'is_default', cpv.is_default,
                'price', cpv.price
            ) ORDER BY cpv.display_order, cpv.name
        ) FILTER (WHERE cpv.id IS NOT NULL AND cpv.is_active = true),
        '[]'::json
    ) AS variants,
    COUNT(cpv.id) FILTER (WHERE cpv.is_active = true) AS variant_count
FROM competitor_products cp
LEFT JOIN competitors c ON c.id = cp.competitor_id
LEFT JOIN competitor_product_variants cpv ON cpv.competitor_product_id = cp.id
WHERE cp.is_active = true
GROUP BY cp.id, cp.competitor_id, cp.brand_id, cp.name, cp.slug,
         cp.description, cp.product_code, cp.is_active, cp.created_at, c.name;

COMMENT ON VIEW competitor_products_with_variants IS 'Competitor products with nested variant arrays';

-- ============================================================================
-- 7. UPDATED_AT TRIGGERS
-- ============================================================================

-- Trigger function (reuse if exists, create if not)
CREATE OR REPLACE FUNCTION update_updated_at_column()
RETURNS TRIGGER AS $$
BEGIN
    NEW.updated_at = NOW();
    RETURN NEW;
END;
$$ language 'plpgsql';

-- Triggers for new tables
DROP TRIGGER IF EXISTS update_competitor_products_updated_at ON competitor_products;
CREATE TRIGGER update_competitor_products_updated_at
    BEFORE UPDATE ON competitor_products
    FOR EACH ROW
    EXECUTE FUNCTION update_updated_at_column();

DROP TRIGGER IF EXISTS update_competitor_product_variants_updated_at ON competitor_product_variants;
CREATE TRIGGER update_competitor_product_variants_updated_at
    BEFORE UPDATE ON competitor_product_variants
    FOR EACH ROW
    EXECUTE FUNCTION update_updated_at_column();

DROP TRIGGER IF EXISTS update_competitor_product_urls_updated_at ON competitor_product_urls;
CREATE TRIGGER update_competitor_product_urls_updated_at
    BEFORE UPDATE ON competitor_product_urls
    FOR EACH ROW
    EXECUTE FUNCTION update_updated_at_column();

-- ============================================================================
-- MIGRATION COMPLETE
-- ============================================================================
-- New tables:
--   - competitor_products (mirrors products)
--   - competitor_product_variants (mirrors product_variants)
--   - competitor_product_urls (mirrors product_urls)
--
-- Altered tables:
--   - competitor_ads: added competitor_product_id, product_match_confidence, product_match_method
--   - competitor_amazon_urls: added competitor_product_id
--   - competitor_landing_pages: added competitor_product_id
--   - competitor_amazon_review_analysis: added competitor_product_id
--   - personas_4d: added competitor_product_id
--
-- New view:
--   - competitor_products_with_variants
-- ============================================================================
