-- Migration: Add is_uploaded tracking to video_bucket_categorizations
-- Date: 2026-02-18
-- Purpose: Track which categorized videos have been uploaded to Facebook

ALTER TABLE video_bucket_categorizations
  ADD COLUMN IF NOT EXISTS is_uploaded BOOLEAN NOT NULL DEFAULT FALSE;

CREATE INDEX IF NOT EXISTS idx_video_bucket_cat_uploaded
  ON video_bucket_categorizations(product_id, organization_id)
  WHERE is_uploaded = TRUE;
