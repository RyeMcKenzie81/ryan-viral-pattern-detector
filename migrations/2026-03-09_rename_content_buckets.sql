-- ============================================================================
-- Migration: Rename video_bucket_categorizations → content_bucket_categorizations
-- Date: 2026-03-09
-- Purpose: Add image support to Content Buckets. Renames table, renames
--          video_summary → summary, adds media_type + source columns.
-- ============================================================================

BEGIN;

-- 1. Rename table
ALTER TABLE video_bucket_categorizations
  RENAME TO content_bucket_categorizations;

-- 2. Rename column: video_summary → summary
ALTER TABLE content_bucket_categorizations
  RENAME COLUMN video_summary TO summary;

-- 3. Add media_type column with CHECK constraint
ALTER TABLE content_bucket_categorizations
  ADD COLUMN IF NOT EXISTS media_type TEXT NOT NULL DEFAULT 'video';

ALTER TABLE content_bucket_categorizations
  ADD CONSTRAINT content_bucket_categorizations_media_type_check
  CHECK (media_type IN ('image', 'video'));

-- 4. Add source column (upload vs google_drive)
ALTER TABLE content_bucket_categorizations
  ADD COLUMN IF NOT EXISTS source TEXT NOT NULL DEFAULT 'upload';

ALTER TABLE content_bucket_categorizations
  ADD CONSTRAINT content_bucket_categorizations_source_check
  CHECK (source IN ('upload', 'google_drive'));

-- 5. Rename indexes
ALTER INDEX IF EXISTS idx_video_bucket_cat_session
  RENAME TO idx_content_bucket_cat_session;
ALTER INDEX IF EXISTS idx_video_bucket_cat_product_org
  RENAME TO idx_content_bucket_cat_product_org;
ALTER INDEX IF EXISTS idx_video_bucket_cat_uploaded
  RENAME TO idx_content_bucket_cat_uploaded;

-- 6. Rename CHECK constraint on status column (auto-generated name)
ALTER TABLE content_bucket_categorizations
  RENAME CONSTRAINT video_bucket_categorizations_status_check
  TO content_bucket_categorizations_status_check;

-- 7. Update comments
COMMENT ON TABLE content_bucket_categorizations
  IS 'Per-file (image or video) analysis results and bucket assignments from Gemini.';
COMMENT ON COLUMN content_bucket_categorizations.media_type
  IS 'Type of media: image or video.';
COMMENT ON COLUMN content_bucket_categorizations.summary
  IS 'Content summary from Gemini analysis (was video_summary).';
COMMENT ON COLUMN content_bucket_categorizations.source
  IS 'Origin of the file: upload (local) or google_drive (imported).';

COMMIT;
