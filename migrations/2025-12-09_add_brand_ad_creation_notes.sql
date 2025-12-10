-- Migration: Add Ad Creation Notes to Brands
-- Date: 2025-12-09
-- Purpose: Allow brands to have default instructions for ad generation (e.g., "white backdrops work best")

-- Add ad_creation_notes column to brands table
DO $$
BEGIN
    IF NOT EXISTS (
        SELECT 1 FROM information_schema.columns
        WHERE table_name = 'brands' AND column_name = 'ad_creation_notes'
    ) THEN
        ALTER TABLE brands ADD COLUMN ad_creation_notes text;
        COMMENT ON COLUMN brands.ad_creation_notes IS 'Default instructions/notes for ad generation (e.g., style preferences, backdrop colors, brand-specific guidelines)';
    END IF;
END $$;
