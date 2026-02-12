-- Migration: URL Mapping support for Meta API ads
-- Date: 2026-02-11
-- Purpose: Add Meta ad ID tracking to review queue and create persistent
-- Meta product matches table (separate from facebook_ads.product_id).

-- Add Meta ad ID tracking to review queue
-- (sample_ad_ids is UUID[] for scraped ads; Meta IDs are TEXT, so need separate column)
ALTER TABLE url_review_queue ADD COLUMN IF NOT EXISTS sample_meta_ad_ids TEXT[];
COMMENT ON COLUMN url_review_queue.sample_meta_ad_ids IS 'Sample Meta ad IDs using this URL (max 5). Separate from sample_ad_ids which are UUID references to facebook_ads.';

-- Persistent Meta product matches (separate from facebook_ads.product_id)
-- Cardinality: ONE product per Meta ad (matches facebook_ads.product_id semantics)
CREATE TABLE IF NOT EXISTS meta_ad_product_matches (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    meta_ad_id TEXT NOT NULL,
    brand_id UUID NOT NULL REFERENCES brands(id),
    product_id UUID NOT NULL REFERENCES products(id),
    match_confidence FLOAT,
    match_method TEXT,  -- 'url', 'manual'
    matched_at TIMESTAMPTZ DEFAULT now(),
    UNIQUE(brand_id, meta_ad_id)  -- One product per meta ad per brand
);

CREATE INDEX IF NOT EXISTS idx_meta_product_matches_product
    ON meta_ad_product_matches(product_id);
