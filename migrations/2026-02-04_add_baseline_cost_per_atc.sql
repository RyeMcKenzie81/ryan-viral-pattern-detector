-- Migration: Add median_cost_per_add_to_cart to ad_intelligence_baselines
-- Date: 2026-02-04
-- Purpose: Track cost per add-to-cart baseline metric for account analysis

ALTER TABLE ad_intelligence_baselines
ADD COLUMN IF NOT EXISTS median_cost_per_add_to_cart NUMERIC(12, 4);

COMMENT ON COLUMN ad_intelligence_baselines.median_cost_per_add_to_cart IS 'Median cost per add-to-cart event for the cohort';
