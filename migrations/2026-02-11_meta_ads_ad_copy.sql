-- Migration: Add ad_copy column to meta_ads_performance
-- Date: 2026-02-11
-- Purpose: Store the primary text/body of ad creatives extracted from object_story_spec.
-- Currently the classifier falls back to ad_name as "ad copy", but the actual text
-- is available from the creative's object_story_spec (already fetched for thumbnails).

ALTER TABLE meta_ads_performance ADD COLUMN IF NOT EXISTS ad_copy TEXT;
COMMENT ON COLUMN meta_ads_performance.ad_copy IS 'Primary text/body of the ad creative, extracted from object_story_spec';
