-- Migration: push baseline for Shopify manual-edit auto-detection
-- Date: 2026-06-10
-- Purpose: §10 increment 2 (b). content_locked (increment 1) protects a manual
-- Shopify edit ONLY if a human remembers to set the flag first. This adds the
-- baseline so the pipeline can DETECT a manual edit on its own and auto-lock
-- before overwriting it.
--
--   last_pushed_at        — Shopify's OWN updated_at from our last body push
--                           (not our local clock — avoids skew; compares
--                           Shopify timestamps to themselves).
--   last_pushed_body_hash — sha256 of the body_html Shopify STORED on that push
--                           (captured from the push response, so a later
--                           get_article hash-matches unless a human edited it).
--
-- Detection (cms_publisher_service.detect_manual_edit), before any re-push of
-- an already-published article: fetch the live article; if Shopify's updated_at
-- moved since last_pushed_at AND the live body hash differs from
-- last_pushed_body_hash, a human edited it -> skip the push + set content_locked.
-- The hash is the confirmation, so our own non-body writes (metafields, author,
-- status) that bump updated_at do NOT false-positive into an auto-lock.
--
-- Degrades gracefully if absent: detect_manual_edit returns False (proceed)
-- whenever the baseline is missing, so pre-migration / first-push articles
-- publish normally and the baseline self-populates on the next push.

ALTER TABLE seo_articles
    ADD COLUMN IF NOT EXISTS last_pushed_at TIMESTAMPTZ,
    ADD COLUMN IF NOT EXISTS last_pushed_body_hash TEXT;

COMMENT ON COLUMN seo_articles.last_pushed_at IS
    'Shopify updated_at captured from our last body push. Baseline for manual-edit detection (§10 inc 2): live updated_at > this => something changed it after us.';
COMMENT ON COLUMN seo_articles.last_pushed_body_hash IS
    'sha256 of the body_html Shopify stored on our last push. The CONFIRMATION signal: live body hash != this => a real body edit (not just our own metadata write).';
