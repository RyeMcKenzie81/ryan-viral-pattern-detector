-- Migration: Add public share link columns to landing_page_analyses
-- Date: 2026-02-26
-- Purpose: Enable public sharing of analysis templates (pre-blueprint)
--          Mirrors the blueprint share link pattern from 2026-02-25_blueprint_share_links.sql

ALTER TABLE landing_page_analyses
  ADD COLUMN IF NOT EXISTS public_share_token TEXT UNIQUE;
ALTER TABLE landing_page_analyses
  ADD COLUMN IF NOT EXISTS public_share_enabled BOOLEAN DEFAULT FALSE;
ALTER TABLE landing_page_analyses
  ADD COLUMN IF NOT EXISTS public_share_created_at TIMESTAMPTZ;

-- Partial unique index: only index non-null tokens for efficient lookup
CREATE UNIQUE INDEX IF NOT EXISTS idx_lpa_share_token
  ON landing_page_analyses(public_share_token)
  WHERE public_share_token IS NOT NULL;
