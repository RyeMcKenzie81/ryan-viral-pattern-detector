-- Migration: Add regenerate_parent_id to generated_ads
-- Date: 2026-01-30
-- Purpose: Track lineage when a rejected ad is regenerated with the same hook.
--          The new ad links back to the original rejected ad via this column.

ALTER TABLE generated_ads ADD COLUMN IF NOT EXISTS regenerate_parent_id UUID REFERENCES generated_ads(id);

COMMENT ON COLUMN generated_ads.regenerate_parent_id IS 'Source ad ID when this ad was regenerated from a rejected/flagged ad';
