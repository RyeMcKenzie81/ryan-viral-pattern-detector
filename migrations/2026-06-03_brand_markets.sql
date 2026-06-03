-- Migration: brand_markets (per-brand market / host → market map)
-- Date: 2026-06-03
-- Purpose: Configure a brand's markets (US, CA, …) and the destination hostnames
--   that map to each, so per-product reporting can SPLIT by market instead of
--   blending (e.g. us.martinclinic.com = US/USD vs martinclinic.com = CA/CAD).
--
-- Model: one product, market is a dimension. The market of an ad is derived from
-- its captured destination host via this map — no per-offer-variant tagging. The
-- weekly digest / analysis groups a product's spend+CPA by market and labels the
-- currency, so a CAD funnel never blends into a USD CPA.
--
-- Per-region PRICE (for ROAS/margin) is intentionally NOT here — that belongs on
-- the offer variant (per-offer terms) and is a later phase. This table holds the
-- brand-level market definitions + currency.

CREATE TABLE IF NOT EXISTS brand_markets (
    id            uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    brand_id      uuid NOT NULL REFERENCES brands(id) ON DELETE CASCADE,
    code          text NOT NULL,                       -- short code, e.g. 'US', 'CA'
    label         text,                                -- display name, e.g. 'United States'
    currency      text NOT NULL DEFAULT 'USD',         -- ISO code, e.g. 'USD', 'CAD'
    host_patterns text[] NOT NULL DEFAULT '{}',        -- exact destination hosts mapping to this market
    is_default    boolean NOT NULL DEFAULT false,      -- fallback market when a host matches none
    sort_order    integer NOT NULL DEFAULT 0,
    created_at    timestamptz NOT NULL DEFAULT now(),
    updated_at    timestamptz NOT NULL DEFAULT now(),
    CONSTRAINT brand_markets_brand_code_uniq UNIQUE (brand_id, code)
);

CREATE INDEX IF NOT EXISTS idx_brand_markets_brand ON brand_markets (brand_id);

COMMENT ON TABLE brand_markets IS
    'Per-brand market definitions + the destination hostnames that map to each. Drives market-split (US/CA) reporting so multi-market/multi-currency spend never blends into one CPA.';
COMMENT ON COLUMN brand_markets.host_patterns IS
    'Exact destination hostnames (lowercase) whose ads belong to this market, e.g. {us.martinclinic.com}.';
COMMENT ON COLUMN brand_markets.is_default IS
    'When an ad''s destination host matches no market, fall back to the default market (at most one per brand).';

-- Seed Martin Clinic's two markets as a working example (idempotent). Edit/extend
-- via Brand Manager → Markets. us.martinclinic.com = US/USD, martinclinic.com = CA/CAD.
INSERT INTO brand_markets (brand_id, code, label, currency, host_patterns, is_default, sort_order)
SELECT 'd0cfa5c5-1132-447b-ade3-4db87995315b', 'US', 'United States', 'USD',
       ARRAY['us.martinclinic.com'], true, 0
WHERE NOT EXISTS (SELECT 1 FROM brand_markets
  WHERE brand_id='d0cfa5c5-1132-447b-ade3-4db87995315b' AND code='US');

INSERT INTO brand_markets (brand_id, code, label, currency, host_patterns, is_default, sort_order)
SELECT 'd0cfa5c5-1132-447b-ade3-4db87995315b', 'CA', 'Canada', 'CAD',
       ARRAY['martinclinic.com'], false, 1
WHERE NOT EXISTS (SELECT 1 FROM brand_markets
  WHERE brand_id='d0cfa5c5-1132-447b-ade3-4db87995315b' AND code='CA');
