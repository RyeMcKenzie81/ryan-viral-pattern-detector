-- Migration: idempotent internal-link records
-- Date: 2026-06-08
-- Purpose: §6 interlinking workstream (D5.2). interlink_cluster re-runs on every
-- cluster member publish (D1). Today _save_link_record does a plain INSERT every
-- pass, so re-runs accumulate duplicate (source, target, link_type) rows. That
-- inflates _batch_count_inbound_links and makes the §7 orphan/coverage metrics
-- lie. This dedupes existing rows and adds a unique index so the record write can
-- become an idempotent UPSERT.

-- 1. Dedupe existing rows: keep one row per (source, target, link_type).
--    ctid is the physical row id; `a.ctid < b.ctid` keeps the latest physical row.
DELETE FROM seo_internal_links a
USING seo_internal_links b
WHERE a.ctid < b.ctid
  AND a.source_article_id = b.source_article_id
  AND a.target_article_id IS NOT DISTINCT FROM b.target_article_id
  AND a.link_type IS NOT DISTINCT FROM b.link_type;

-- 2. Unique index so ON CONFLICT (upsert) has a target. Partial-safe: link_type
--    and target are expected non-null for real records; NULLs (if any) are left
--    to the app layer.
CREATE UNIQUE INDEX IF NOT EXISTS idx_seo_internal_links_unique
    ON seo_internal_links (source_article_id, target_article_id, link_type);

COMMENT ON INDEX idx_seo_internal_links_unique IS
    'Idempotency key for interlinking (§6 D5.2): one record per source+target+link_type. Enables UPSERT so re-running interlink_cluster on each publish does not inflate link counts.';
