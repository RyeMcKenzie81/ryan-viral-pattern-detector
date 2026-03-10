-- Rollback: Undo content_bucket_categorizations rename
BEGIN;

ALTER TABLE content_bucket_categorizations
  DROP CONSTRAINT IF EXISTS content_bucket_categorizations_source_check;
ALTER TABLE content_bucket_categorizations
  DROP CONSTRAINT IF EXISTS content_bucket_categorizations_media_type_check;

ALTER TABLE content_bucket_categorizations DROP COLUMN IF EXISTS source;
ALTER TABLE content_bucket_categorizations DROP COLUMN IF EXISTS media_type;

ALTER TABLE content_bucket_categorizations RENAME COLUMN summary TO video_summary;

ALTER INDEX IF EXISTS idx_content_bucket_cat_session
  RENAME TO idx_video_bucket_cat_session;
ALTER INDEX IF EXISTS idx_content_bucket_cat_product_org
  RENAME TO idx_video_bucket_cat_product_org;
ALTER INDEX IF EXISTS idx_content_bucket_cat_uploaded
  RENAME TO idx_video_bucket_cat_uploaded;

ALTER TABLE content_bucket_categorizations
  RENAME CONSTRAINT content_bucket_categorizations_status_check
  TO video_bucket_categorizations_status_check;

ALTER TABLE content_bucket_categorizations
  RENAME TO video_bucket_categorizations;

COMMIT;
