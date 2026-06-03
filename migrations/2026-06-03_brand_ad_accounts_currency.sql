-- Migration: brand_ad_accounts.currency (ad-account billing currency)
-- Date: 2026-06-03
-- Purpose: Capture the Meta ad-account billing currency (from AdAccount.currency)
--   so the weekly per-product digest labels spend/CPA in the right currency.
--
-- IMPORTANT distinction:
--   brand_ad_accounts.currency = the AD-SPEND currency (one per Meta ad account;
--       CPA = spend/purchases is in this currency). Martin = CAD.
--   brand_markets.currency      = the STORE/REVENUE currency (US store USD, CA
--       store CAD) — for a future ROAS/break-even view, NOT the CPA digest.
-- Both are correct; they answer different questions.

ALTER TABLE brand_ad_accounts ADD COLUMN IF NOT EXISTS currency text;

COMMENT ON COLUMN brand_ad_accounts.currency IS
    'Meta ad-account billing currency (ISO, e.g. CAD/USD) from AdAccount.currency. The currency of ad SPEND/CPA — one per account. Distinct from brand_markets.currency (store/revenue currency).';

-- Seed Martin Clinic's primary account = CAD (confirmed with client 2026-06-03).
UPDATE brand_ad_accounts SET currency = 'CAD'
WHERE brand_id = 'd0cfa5c5-1132-447b-ade3-4db87995315b'
  AND is_primary = true
  AND currency IS NULL;
