-- Migration: Create meta_ad_destinations table for ad landing page URLs
-- Date: 2026-02-03
-- Purpose: Store ad destination URLs from Meta Marketing API for landing page matching.
--          Stores both original URL and canonicalized URL for matching to brand_landing_pages.

CREATE TABLE IF NOT EXISTS meta_ad_destinations (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    organization_id UUID NOT NULL REFERENCES organizations(id),
    brand_id UUID NOT NULL REFERENCES brands(id) ON DELETE CASCADE,
    meta_ad_id TEXT NOT NULL,
    destination_url TEXT NOT NULL,    -- Original URL from Meta API
    canonical_url TEXT NOT NULL,      -- Normalized for matching (lowercase host, no www, no query params)
    fetched_at TIMESTAMPTZ DEFAULT NOW(),
    updated_at TIMESTAMPTZ DEFAULT NOW(),

    UNIQUE(brand_id, meta_ad_id, canonical_url)
);

-- Index for canonical URL matching to brand_landing_pages
CREATE INDEX IF NOT EXISTS idx_ad_destinations_canonical
    ON meta_ad_destinations(brand_id, canonical_url);

-- Index for ad lookups/updates (per user request)
CREATE INDEX IF NOT EXISTS idx_ad_destinations_ad
    ON meta_ad_destinations(brand_id, meta_ad_id);

COMMENT ON TABLE meta_ad_destinations IS 'Landing page URLs from Meta Marketing API for congruence matching';
COMMENT ON COLUMN meta_ad_destinations.destination_url IS 'Original URL as returned by Meta API (may include UTMs, variant params)';
COMMENT ON COLUMN meta_ad_destinations.canonical_url IS 'Normalized URL: lowercase host, no www, no query params, no trailing slash';

-- Also add canonical_url column to brand_landing_pages for matching
ALTER TABLE brand_landing_pages ADD COLUMN IF NOT EXISTS canonical_url TEXT;

-- Backfill canonical_url from url (simple lowercase + remove trailing slash for now)
-- Full canonicalization will be done by url_canonicalizer.py
UPDATE brand_landing_pages
SET canonical_url = LOWER(RTRIM(url, '/'))
WHERE canonical_url IS NULL;

-- Index for canonical matching
CREATE INDEX IF NOT EXISTS idx_brand_landing_pages_canonical
    ON brand_landing_pages(brand_id, canonical_url) WHERE canonical_url IS NOT NULL;

COMMENT ON COLUMN brand_landing_pages.canonical_url IS 'Normalized URL for matching to meta_ad_destinations.canonical_url';
