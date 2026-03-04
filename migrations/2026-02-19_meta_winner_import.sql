-- Migration: Meta Winner Import & Evolution
-- Date: 2026-02-19
-- Purpose: Schema changes for importing winning Meta ads into the generated_ads
--          system as synthetic records, enabling winner evolution, exemplar marking,
--          and Thompson Sampling integration.
--
-- Changes:
--   1. Add is_imported + meta_ad_id columns to generated_ads
--   2. Add score_processed_at to creative_element_rewards (idempotent scoring)
--   3. Create creative_element_score_events table (idempotent Thompson updates)
--   4. Allow fractional total_observations in creative_element_scores
--   5. Ensure ad_runs.parameters JSONB column exists with default
--   6. Create get_linked_ads_for_brand() RPC for brand-scoped link queries
--   7. Create cleanup_stale_element_scores() RPC for score maintenance

-- ============================================================================
-- 1. Import tracking columns on generated_ads
-- ============================================================================

ALTER TABLE generated_ads ADD COLUMN IF NOT EXISTS is_imported BOOLEAN NOT NULL DEFAULT FALSE;
ALTER TABLE generated_ads ADD COLUMN IF NOT EXISTS meta_ad_id TEXT;

CREATE INDEX IF NOT EXISTS idx_generated_ads_meta_ad_id
  ON generated_ads(meta_ad_id) WHERE meta_ad_id IS NOT NULL;
CREATE INDEX IF NOT EXISTS idx_generated_ads_is_imported
  ON generated_ads(is_imported) WHERE is_imported = TRUE;

-- Unique constraint: prevent double-import of same Meta ad
CREATE UNIQUE INDEX IF NOT EXISTS idx_generated_ads_meta_import_unique
  ON generated_ads(meta_ad_id) WHERE meta_ad_id IS NOT NULL AND is_imported = TRUE;

COMMENT ON COLUMN generated_ads.is_imported IS 'TRUE for ads imported from Meta (not pipeline-generated). Used to filter health KPIs and downweight Thompson Sampling.';
COMMENT ON COLUMN generated_ads.meta_ad_id IS 'Meta ad ID for imported ads. Also used by meta_ad_mapping for pipeline-generated ads.';


-- ============================================================================
-- 2. Idempotent scoring: mark rewards already processed
-- ============================================================================

ALTER TABLE creative_element_rewards
  ADD COLUMN IF NOT EXISTS score_processed_at TIMESTAMPTZ;

CREATE INDEX IF NOT EXISTS idx_creative_element_rewards_unprocessed
  ON creative_element_rewards(brand_id) WHERE score_processed_at IS NULL;

COMMENT ON COLUMN creative_element_rewards.score_processed_at IS 'Timestamp when this reward was processed into score events. NULL = unprocessed.';


-- ============================================================================
-- 3. Idempotent score events for Thompson Sampling
-- ============================================================================

CREATE TABLE IF NOT EXISTS creative_element_score_events (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    reward_id UUID NOT NULL REFERENCES creative_element_rewards(id) ON DELETE CASCADE,
    brand_id UUID NOT NULL REFERENCES brands(id) ON DELETE CASCADE,
    element_name TEXT NOT NULL,
    element_value TEXT NOT NULL,
    alpha_delta DOUBLE PRECISION NOT NULL,
    beta_delta DOUBLE PRECISION NOT NULL,
    obs_delta DOUBLE PRECISION NOT NULL,
    reward_score DOUBLE PRECISION NOT NULL,
    created_at TIMESTAMPTZ DEFAULT NOW(),
    UNIQUE(reward_id, element_name, element_value)
);

CREATE INDEX IF NOT EXISTS idx_score_events_brand_element
  ON creative_element_score_events(brand_id, element_name, element_value);

COMMENT ON TABLE creative_element_score_events IS 'Idempotent score events for Thompson Sampling. One row per (reward, element_name, element_value). UNIQUE constraint prevents double-counting on retries.';
COMMENT ON COLUMN creative_element_score_events.alpha_delta IS 'Increment to alpha (weight if reward >= 0.5, else 0). Weight is 1.0 for native ads, 0.3 for imported.';
COMMENT ON COLUMN creative_element_score_events.beta_delta IS 'Increment to beta (weight if reward < 0.5, else 0). Weight is 1.0 for native ads, 0.3 for imported.';
COMMENT ON COLUMN creative_element_score_events.obs_delta IS 'Observation weight (1.0 native, 0.3 imported). Used for weighted mean and fractional total_observations.';


-- ============================================================================
-- 4. Allow fractional total_observations for weighted Thompson Sampling
-- ============================================================================
-- NOTE: This ALTER requires ACCESS EXCLUSIVE lock and table rewrite.
-- Run during low-traffic window.

ALTER TABLE creative_element_scores
  ALTER COLUMN total_observations TYPE DOUBLE PRECISION;

COMMENT ON COLUMN creative_element_scores.total_observations IS 'Weighted observation count. Fractional for imported ads (0.3 per import vs 1.0 per native). Used in cross-brand prior weighting.';


-- ============================================================================
-- 5. Ensure ad_runs.parameters JSONB exists with default
-- ============================================================================
-- Synthetic ad_runs use parameters.source = 'meta_import' for provenance.

ALTER TABLE ad_runs ADD COLUMN IF NOT EXISTS parameters JSONB DEFAULT '{}'::jsonb;
ALTER TABLE ad_runs ALTER COLUMN parameters SET DEFAULT '{}'::jsonb;

COMMENT ON COLUMN ad_runs.parameters IS 'JSONB parameters for the ad run. Import provenance: {source: "meta_import", batch_id: "..."}';


-- ============================================================================
-- 6. RPC: Brand-scoped linked ads query
-- ============================================================================
-- Replaces the unscoped meta_ad_mapping query in Ad Performance UI.
-- Joins through generated_ads -> ad_runs -> products to filter by brand.

CREATE OR REPLACE FUNCTION get_linked_ads_for_brand(p_brand_id UUID)
RETURNS TABLE(
  meta_ad_id TEXT,
  generated_ad_id UUID,
  linked_by TEXT,
  meta_ad_account_id TEXT,
  meta_campaign_id TEXT,
  storage_path TEXT,
  hook_text TEXT,
  final_status TEXT,
  is_imported BOOLEAN
) AS $$
  SELECT m.meta_ad_id, m.generated_ad_id, m.linked_by,
         m.meta_ad_account_id, m.meta_campaign_id,
         g.storage_path, g.hook_text, g.final_status, g.is_imported
  FROM meta_ad_mapping m
  JOIN generated_ads g ON g.id = m.generated_ad_id
  JOIN ad_runs r ON r.id = g.ad_run_id
  JOIN products p ON p.id = r.product_id
  WHERE p.brand_id = p_brand_id;
$$ LANGUAGE sql STABLE;

-- Safe for authenticated: brand_id param validated by caller, join enforces scope.
GRANT EXECUTE ON FUNCTION get_linked_ads_for_brand(UUID) TO authenticated;


-- ============================================================================
-- 7. RPC: Cleanup stale element scores
-- ============================================================================
-- Removes creative_element_scores rows with no backing score events.
-- Called after event-based recomputation to clean up legacy rows.

CREATE OR REPLACE FUNCTION cleanup_stale_element_scores(p_brand_id UUID)
RETURNS void AS $$
  DELETE FROM creative_element_scores s
  WHERE s.brand_id = p_brand_id
    AND NOT EXISTS (
      SELECT 1 FROM creative_element_score_events e
      WHERE e.brand_id = s.brand_id
        AND e.element_name = s.element_name
        AND e.element_value = s.element_value
    );
$$ LANGUAGE sql;

-- Service-role only: mutates scores.
GRANT EXECUTE ON FUNCTION cleanup_stale_element_scores(UUID) TO service_role;
