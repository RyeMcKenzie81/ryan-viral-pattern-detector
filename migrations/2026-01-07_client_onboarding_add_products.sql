-- Migration: Add products column to client_onboarding_sessions
-- Date: 2026-01-07
-- Purpose: Support product-level data collection during onboarding
-- Part of: Client Onboarding Pipeline - Phase 10

-- Add products JSONB column
ALTER TABLE client_onboarding_sessions
ADD COLUMN IF NOT EXISTS products JSONB DEFAULT '[]';

-- Add comment documenting the schema
COMMENT ON COLUMN client_onboarding_sessions.products IS
'Products array - JSON schema: [{name, description, product_url, amazon_url, asin, dimensions: {width, height, depth, unit}, weight: {value, unit}, target_audience: {demographics, pain_points, desires_goals}, images: [{filename, is_main}]}]';
