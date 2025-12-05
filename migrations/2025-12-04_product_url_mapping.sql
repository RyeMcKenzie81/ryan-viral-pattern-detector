-- Migration: Product URL Mapping System
-- Date: 2025-12-04
-- Purpose: Enable URL-based product identification for Facebook ads
--          Supports both brand-level and product-level persona generation

-- ============================================================
-- 1. Product URLs Table
-- ============================================================
-- Stores known landing page URLs for each product
-- Supports multiple URLs per product and flexible matching

CREATE TABLE IF NOT EXISTS product_urls (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    product_id UUID NOT NULL REFERENCES products(id) ON DELETE CASCADE,
    url_pattern TEXT NOT NULL,
    match_type TEXT DEFAULT 'contains' CHECK (match_type IN ('exact', 'prefix', 'contains', 'regex')),
    is_primary BOOLEAN DEFAULT false,
    notes TEXT,
    created_at TIMESTAMPTZ DEFAULT NOW(),
    updated_at TIMESTAMPTZ DEFAULT NOW(),
    UNIQUE(product_id, url_pattern)
);

CREATE INDEX idx_product_urls_product ON product_urls(product_id);
CREATE INDEX idx_product_urls_pattern ON product_urls(url_pattern);

COMMENT ON TABLE product_urls IS 'Maps landing page URLs to products for ad identification';
COMMENT ON COLUMN product_urls.url_pattern IS 'URL or pattern to match (e.g., "mywonderpaws.com/products/plaque")';
COMMENT ON COLUMN product_urls.match_type IS 'How to match: exact, prefix (startswith), contains, or regex';
COMMENT ON COLUMN product_urls.is_primary IS 'Primary landing page for this product';

-- ============================================================
-- 2. URL Review Queue Table
-- ============================================================
-- Tracks unmatched URLs discovered during ad scraping
-- Allows manual review and assignment to products

CREATE TABLE IF NOT EXISTS url_review_queue (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    brand_id UUID NOT NULL REFERENCES brands(id) ON DELETE CASCADE,
    url TEXT NOT NULL,
    normalized_url TEXT,  -- URL without query params, lowercase
    occurrence_count INT DEFAULT 1,
    sample_ad_ids UUID[],  -- Sample of ads using this URL (max 5)
    suggested_product_id UUID REFERENCES products(id),
    suggestion_confidence FLOAT,
    status TEXT DEFAULT 'pending' CHECK (status IN ('pending', 'assigned', 'new_product', 'ignored')),
    reviewed_by TEXT,
    reviewed_at TIMESTAMPTZ,
    created_at TIMESTAMPTZ DEFAULT NOW(),
    updated_at TIMESTAMPTZ DEFAULT NOW(),
    UNIQUE(brand_id, normalized_url)
);

CREATE INDEX idx_url_review_queue_brand ON url_review_queue(brand_id);
CREATE INDEX idx_url_review_queue_status ON url_review_queue(status);

COMMENT ON TABLE url_review_queue IS 'Queue of unmatched URLs discovered in ads, awaiting review';
COMMENT ON COLUMN url_review_queue.normalized_url IS 'Cleaned URL for deduplication (no query params, lowercase)';
COMMENT ON COLUMN url_review_queue.sample_ad_ids IS 'Array of up to 5 ad IDs using this URL for preview';

-- ============================================================
-- 3. Add Product Columns to Facebook Ads
-- ============================================================
-- Link scraped ads to specific products

ALTER TABLE facebook_ads ADD COLUMN IF NOT EXISTS product_id UUID REFERENCES products(id);
ALTER TABLE facebook_ads ADD COLUMN IF NOT EXISTS product_match_confidence FLOAT;
ALTER TABLE facebook_ads ADD COLUMN IF NOT EXISTS product_match_method TEXT CHECK (product_match_method IN ('url', 'ai', 'manual'));
ALTER TABLE facebook_ads ADD COLUMN IF NOT EXISTS product_matched_at TIMESTAMPTZ;

CREATE INDEX idx_facebook_ads_product ON facebook_ads(product_id);
CREATE INDEX idx_facebook_ads_brand_product ON facebook_ads(brand_id, product_id);

COMMENT ON COLUMN facebook_ads.product_id IS 'Product this ad promotes (identified via URL or AI)';
COMMENT ON COLUMN facebook_ads.product_match_confidence IS 'Confidence score of product match (0.0-1.0)';
COMMENT ON COLUMN facebook_ads.product_match_method IS 'How product was identified: url, ai, or manual';

-- ============================================================
-- 4. Add Persona Level to personas_4d
-- ============================================================
-- Support both brand-level and product-level personas

ALTER TABLE personas_4d ADD COLUMN IF NOT EXISTS persona_level TEXT
    DEFAULT 'product' CHECK (persona_level IN ('brand', 'product'));

CREATE INDEX idx_personas_4d_level ON personas_4d(brand_id, persona_level);

COMMENT ON COLUMN personas_4d.persona_level IS 'brand = aggregated from all products, product = specific to one product';

-- ============================================================
-- 5. Update Triggers
-- ============================================================

-- Trigger to update updated_at on product_urls
CREATE OR REPLACE FUNCTION update_product_urls_updated_at()
RETURNS TRIGGER AS $$
BEGIN
    NEW.updated_at = NOW();
    RETURN NEW;
END;
$$ LANGUAGE plpgsql;

DROP TRIGGER IF EXISTS product_urls_updated_at ON product_urls;
CREATE TRIGGER product_urls_updated_at
    BEFORE UPDATE ON product_urls
    FOR EACH ROW
    EXECUTE FUNCTION update_product_urls_updated_at();

-- Trigger to update updated_at on url_review_queue
CREATE OR REPLACE FUNCTION update_url_review_queue_updated_at()
RETURNS TRIGGER AS $$
BEGIN
    NEW.updated_at = NOW();
    RETURN NEW;
END;
$$ LANGUAGE plpgsql;

DROP TRIGGER IF EXISTS url_review_queue_updated_at ON url_review_queue;
CREATE TRIGGER url_review_queue_updated_at
    BEFORE UPDATE ON url_review_queue
    FOR EACH ROW
    EXECUTE FUNCTION update_url_review_queue_updated_at();
