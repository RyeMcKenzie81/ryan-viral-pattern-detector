-- Migration: Add ad_archive_id to brand_ad_analysis
-- Date: 2026-01-08
-- Purpose: Enable tracking of analyzed ads from Facebook Ad Library for resume functionality

-- ============================================
-- Add ad_archive_id column for Ad Library ads
-- ============================================

-- This column stores the Facebook Ad Library archive ID (string)
-- Used to track which ads have already been analyzed during client onboarding
-- Allows resuming analysis if it crashes mid-way
ALTER TABLE brand_ad_analysis
ADD COLUMN IF NOT EXISTS ad_archive_id TEXT;

-- Index for efficient querying of already-analyzed ads
CREATE INDEX IF NOT EXISTS idx_brand_analysis_archive_id
ON brand_ad_analysis(ad_archive_id)
WHERE ad_archive_id IS NOT NULL;

-- ============================================
-- Comments
-- ============================================
COMMENT ON COLUMN brand_ad_analysis.ad_archive_id IS 'Facebook Ad Library archive ID (string) - used for resume functionality in client onboarding';

-- ============================================
-- MIGRATION COMPLETE
-- ============================================
-- Added: ad_archive_id (TEXT) - stores Ad Library IDs for resume tracking
-- Added: Index on ad_archive_id for efficient lookups
-- ============================================
