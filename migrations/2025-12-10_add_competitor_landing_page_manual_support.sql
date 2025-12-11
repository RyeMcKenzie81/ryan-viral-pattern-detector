-- Migration: Add manual landing page support for competitors
-- Date: 2025-12-10
-- Purpose: Allow manually adding landing page URLs for competitors

-- Add brand_id column (for consistency with other competitor tables)
ALTER TABLE competitor_landing_pages ADD COLUMN IF NOT EXISTS brand_id UUID REFERENCES brands(id) ON DELETE CASCADE;

-- Add is_manual flag to distinguish manually added URLs from ad-extracted ones
ALTER TABLE competitor_landing_pages ADD COLUMN IF NOT EXISTS is_manual BOOLEAN DEFAULT false;

-- Backfill brand_id from competitor
UPDATE competitor_landing_pages clp
SET brand_id = c.brand_id
FROM competitors c
WHERE clp.competitor_id = c.id
AND clp.brand_id IS NULL;

-- Add index for brand_id
CREATE INDEX IF NOT EXISTS idx_competitor_lp_brand ON competitor_landing_pages(brand_id);

COMMENT ON COLUMN competitor_landing_pages.is_manual IS 'True if URL was manually added, false if extracted from ads';
COMMENT ON COLUMN competitor_landing_pages.brand_id IS 'Brand this competitor belongs to (denormalized for easier queries)';
