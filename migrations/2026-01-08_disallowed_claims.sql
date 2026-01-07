-- Migration: Disallowed Claims & Compliance
-- Date: 2026-01-08
-- Purpose: Add compliance fields to brands and product_offer_variants
-- Part of: Landing Page Analyzer & Disallowed Claims feature

-- ============================================
-- Brand-level disallowed claims
-- ============================================
ALTER TABLE brands ADD COLUMN IF NOT EXISTS disallowed_claims TEXT[] DEFAULT '{}';

COMMENT ON COLUMN brands.disallowed_claims IS 'Claims that must NOT appear in any ads for this brand (e.g., "No FDA claims", "No competitor mentions")';

-- ============================================
-- Offer Variant-level compliance
-- ============================================
ALTER TABLE product_offer_variants
    ADD COLUMN IF NOT EXISTS disallowed_claims TEXT[] DEFAULT '{}';

ALTER TABLE product_offer_variants
    ADD COLUMN IF NOT EXISTS required_disclaimers TEXT;

COMMENT ON COLUMN product_offer_variants.disallowed_claims IS 'Claims that must NOT appear in ads for this specific offer variant/landing page';
COMMENT ON COLUMN product_offer_variants.required_disclaimers IS 'Legal disclaimers that MUST appear in ads for this offer variant';

-- ============================================
-- MIGRATION COMPLETE
-- ============================================
-- Added: brands.disallowed_claims
-- Added: product_offer_variants.disallowed_claims
-- Added: product_offer_variants.required_disclaimers
-- ============================================
