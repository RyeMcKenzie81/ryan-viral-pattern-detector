-- Migration: Product Offer Variant Mechanism Fields
-- Date: 2026-01-08
-- Purpose: Add unique mechanism (UM/UMP/UMS) fields for belief-first messaging
-- Part of: Client Onboarding Auto-Analyze feature

-- ============================================
-- Unique Mechanism Fields (Belief-First Framework)
-- ============================================

-- Mechanism name (the named approach/method)
ALTER TABLE product_offer_variants
    ADD COLUMN IF NOT EXISTS mechanism_name TEXT;

-- Unique Mechanism Problem (UMP) - the reframed root cause
ALTER TABLE product_offer_variants
    ADD COLUMN IF NOT EXISTS mechanism_problem TEXT;

-- Unique Mechanism Solution (UMS) - how the mechanism solves the problem
ALTER TABLE product_offer_variants
    ADD COLUMN IF NOT EXISTS mechanism_solution TEXT;

-- Sample hooks extracted from ads
ALTER TABLE product_offer_variants
    ADD COLUMN IF NOT EXISTS sample_hooks TEXT[] DEFAULT '{}';

-- Source metadata for tracking where data came from
ALTER TABLE product_offer_variants
    ADD COLUMN IF NOT EXISTS source TEXT;

ALTER TABLE product_offer_variants
    ADD COLUMN IF NOT EXISTS source_metadata JSONB DEFAULT '{}';

-- ============================================
-- Comments
-- ============================================
COMMENT ON COLUMN product_offer_variants.mechanism_name IS 'The unique mechanism name (e.g., "Nitric Oxide Pathway", "Triple-Enzyme Complex")';
COMMENT ON COLUMN product_offer_variants.mechanism_problem IS 'UMP - The reframed root cause explaining why past solutions failed';
COMMENT ON COLUMN product_offer_variants.mechanism_solution IS 'UMS - How the unique mechanism solves the root cause problem';
COMMENT ON COLUMN product_offer_variants.sample_hooks IS 'Sample ad hooks extracted from existing ads - array of strings';
COMMENT ON COLUMN product_offer_variants.source IS 'How this variant was created: manual, ad_analysis, amazon_analysis, landing_page_analysis';
COMMENT ON COLUMN product_offer_variants.source_metadata IS 'Additional data about the source (ad_count, review_count, etc.)';

-- ============================================
-- MIGRATION COMPLETE
-- ============================================
-- Added: mechanism_name (TEXT)
-- Added: mechanism_problem (TEXT)
-- Added: mechanism_solution (TEXT)
-- Added: sample_hooks (TEXT[])
-- Added: source (TEXT)
-- Added: source_metadata (JSONB)
-- ============================================
