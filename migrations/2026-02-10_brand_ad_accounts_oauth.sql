-- Migration: Prepare brand_ad_accounts for future OAuth support
-- Date: 2026-02-10
-- Purpose: Add auth_method tracking and OAuth token columns.
--          UNIQUE(brand_id, meta_ad_account_id) confirmed from 2025-12-18 migration (inline constraint).

ALTER TABLE brand_ad_accounts
    ADD COLUMN IF NOT EXISTS auth_method TEXT DEFAULT 'system_user'
        CHECK (auth_method IN ('system_user', 'oauth'));

ALTER TABLE brand_ad_accounts
    ADD COLUMN IF NOT EXISTS access_token TEXT;

ALTER TABLE brand_ad_accounts
    ADD COLUMN IF NOT EXISTS token_expires_at TIMESTAMPTZ;

ALTER TABLE brand_ad_accounts
    ADD COLUMN IF NOT EXISTS refresh_token TEXT;

COMMENT ON COLUMN brand_ad_accounts.auth_method IS 'Authentication method: system_user (default) or oauth';
COMMENT ON COLUMN brand_ad_accounts.access_token IS 'OAuth access token (encrypted at rest via Supabase)';
COMMENT ON COLUMN brand_ad_accounts.token_expires_at IS 'When the OAuth access token expires';
COMMENT ON COLUMN brand_ad_accounts.refresh_token IS 'OAuth refresh token for token renewal';
