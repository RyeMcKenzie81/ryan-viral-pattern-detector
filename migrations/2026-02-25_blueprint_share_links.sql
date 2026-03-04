-- Migration: Public shareable links for blueprint previews
-- Date: 2026-02-25
-- Purpose: Add public_share_token, public_share_enabled, public_share_created_at
--          to landing_page_blueprints for unauthenticated preview sharing.

ALTER TABLE landing_page_blueprints
  ADD COLUMN IF NOT EXISTS public_share_token TEXT UNIQUE;
ALTER TABLE landing_page_blueprints
  ADD COLUMN IF NOT EXISTS public_share_enabled BOOLEAN DEFAULT FALSE;
ALTER TABLE landing_page_blueprints
  ADD COLUMN IF NOT EXISTS public_share_created_at TIMESTAMPTZ;

CREATE UNIQUE INDEX IF NOT EXISTS idx_lpb_share_token
  ON landing_page_blueprints(public_share_token)
  WHERE public_share_token IS NOT NULL;
