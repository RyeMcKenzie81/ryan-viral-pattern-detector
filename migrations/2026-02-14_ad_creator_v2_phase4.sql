-- Migration: Ad Creator V2 Phase 4 — Congruence + Review Overhaul
-- Date: 2026-02-14
-- Purpose: Fix final_status CHECK, add review columns, create ad_review_overrides
--          and quality_scoring_config tables.

-- ============================================================================
-- Migration 1: Fix final_status CHECK constraint + add Phase 4 columns
-- ============================================================================

-- The existing CHECK allows only pending|approved|rejected|flagged.
-- The pipeline already emits review_failed and generation_failed, violating it.
ALTER TABLE generated_ads
  DROP CONSTRAINT IF EXISTS generated_ads_final_status_check;

ALTER TABLE generated_ads
  ADD CONSTRAINT generated_ads_final_status_check
  CHECK (final_status IN (
    'pending', 'approved', 'rejected', 'flagged',
    'review_failed', 'generation_failed'
  ));

-- Phase 4 new columns
ALTER TABLE generated_ads
  ADD COLUMN IF NOT EXISTS review_check_scores JSONB,
  ADD COLUMN IF NOT EXISTS defect_scan_result JSONB,
  ADD COLUMN IF NOT EXISTS congruence_score NUMERIC(4,3),
  ADD COLUMN IF NOT EXISTS override_status TEXT;

-- override_status CHECK: idempotent (drop-then-add) because ADD COLUMN IF NOT EXISTS
-- won't retroactively add a CHECK if the column already existed without one.
ALTER TABLE generated_ads
  DROP CONSTRAINT IF EXISTS generated_ads_override_status_check;
ALTER TABLE generated_ads
  ADD CONSTRAINT generated_ads_override_status_check
  CHECK (override_status IN ('override_approved', 'override_rejected', 'confirmed'));

COMMENT ON COLUMN generated_ads.review_check_scores IS
  'Structured 15-check review scores: V1-V9 visual, C1-C4 content, G1-G2 congruence (0-10 each). NULL for Stage-1-rejected and generation-failed ads.';
COMMENT ON COLUMN generated_ads.defect_scan_result IS
  'Stage 1 defect scan result: {passed: bool, defects: [{type, description}], model, latency_ms}. Present for all successfully generated V2 ads. NULL for generation_failed.';
COMMENT ON COLUMN generated_ads.congruence_score IS
  'Headline <-> offer variant <-> hero section congruence score (0.000-1.000). NULL if no offer_variant_id.';
COMMENT ON COLUMN generated_ads.override_status IS
  'Human override status. NULL = no override.';

-- ============================================================================
-- Migration 2: ad_review_overrides table
-- ============================================================================

CREATE TABLE IF NOT EXISTS ad_review_overrides (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    generated_ad_id UUID NOT NULL REFERENCES generated_ads(id) ON DELETE CASCADE,
    organization_id UUID NOT NULL,
    user_id UUID NOT NULL,
    override_action TEXT NOT NULL CHECK (override_action IN ('override_approve', 'override_reject', 'confirm')),
    previous_status TEXT,              -- AI status before override
    check_overrides JSONB,             -- per-check granularity: {"V1": {"ai_score": 6.0, "human_override": "pass"}}
    reason TEXT,                       -- optional human notes
    superseded_by UUID REFERENCES ad_review_overrides(id),  -- latest override chain
    created_at TIMESTAMPTZ DEFAULT NOW()
);

-- No UNIQUE on generated_ad_id — multiple overrides per ad allowed (see PLAN.md P2-2)
CREATE INDEX IF NOT EXISTS idx_aro_ad ON ad_review_overrides(generated_ad_id, created_at DESC);
CREATE INDEX IF NOT EXISTS idx_aro_org ON ad_review_overrides(organization_id);

-- ============================================================================
-- Migration 3: quality_scoring_config table
-- ============================================================================

CREATE TABLE IF NOT EXISTS quality_scoring_config (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    organization_id UUID,             -- NULL = global default
    version INT NOT NULL DEFAULT 1,
    is_active BOOLEAN NOT NULL DEFAULT FALSE,
    pass_threshold NUMERIC(4,2) NOT NULL DEFAULT 7.00,  -- weighted score out of 10
    check_weights JSONB NOT NULL DEFAULT '{
        "V1": 1.5, "V2": 1.5, "V3": 1.0, "V4": 0.8, "V5": 0.8,
        "V6": 1.0, "V7": 1.0, "V8": 0.8, "V9": 1.2,
        "C1": 1.0, "C2": 0.8, "C3": 0.8, "C4": 0.8,
        "G1": 1.0, "G2": 0.8
    }',
    borderline_range JSONB NOT NULL DEFAULT '{"low": 5.0, "high": 7.0}',
    auto_reject_checks JSONB NOT NULL DEFAULT '["V9"]',  -- checks that auto-reject if below 3.0
    created_at TIMESTAMPTZ DEFAULT NOW(),
    created_by UUID,
    notes TEXT
);

-- Enforce unique version per org (COALESCE handles NULL org_id for global rows)
CREATE UNIQUE INDEX IF NOT EXISTS idx_qsc_unique_version
  ON quality_scoring_config (COALESCE(organization_id, '00000000-0000-0000-0000-000000000000'), version);

-- Enforce at most one active config per org (including global)
CREATE UNIQUE INDEX IF NOT EXISTS idx_qsc_single_active
  ON quality_scoring_config (COALESCE(organization_id, '00000000-0000-0000-0000-000000000000'))
  WHERE is_active = TRUE;

COMMENT ON TABLE quality_scoring_config IS
  'Versioned quality thresholds for ad review. Partial unique index enforces single is_active per org. Phase 6 adds adaptive calibration.';

-- Seed global default (version 1, active)
INSERT INTO quality_scoring_config (organization_id, version, is_active, notes)
VALUES (NULL, 1, TRUE, 'Phase 4 initial static thresholds')
ON CONFLICT DO NOTHING;
