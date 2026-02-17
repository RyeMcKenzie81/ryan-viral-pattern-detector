-- Migration: Ad Creator V2 Phase 8A — Core Autonomous Intelligence
-- Date: 2026-02-16
-- Purpose: 5 new tables for exemplar library, visual embeddings, element interactions,
--          element combo usage, and calibration proposals. Seeds quality_calibration job.

-- ============================================================================
-- 1. Ensure pgvector extension
-- ============================================================================
CREATE EXTENSION IF NOT EXISTS vector;


-- ============================================================================
-- 2. exemplar_library — Curated calibration ads per brand
-- ============================================================================
CREATE TABLE IF NOT EXISTS exemplar_library (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    brand_id UUID NOT NULL REFERENCES brands(id) ON DELETE CASCADE,
    generated_ad_id UUID NOT NULL REFERENCES generated_ads(id) ON DELETE CASCADE,

    -- Classification
    category TEXT NOT NULL,  -- gold_approve, gold_reject, edge_case

    -- Provenance
    source TEXT NOT NULL DEFAULT 'manual',  -- auto, manual
    source_reason TEXT,
    created_by UUID,

    -- Diversity attributes (for balanced curation)
    template_category TEXT,
    canvas_size TEXT,
    color_mode TEXT,
    persona_id UUID,

    -- Embedding link
    visual_embedding_id UUID,

    -- Status
    is_active BOOLEAN NOT NULL DEFAULT TRUE,
    deactivated_at TIMESTAMPTZ,
    deactivated_reason TEXT,

    created_at TIMESTAMPTZ DEFAULT NOW(),

    UNIQUE(brand_id, generated_ad_id)
);

ALTER TABLE exemplar_library
ADD CONSTRAINT exemplar_library_category_check
CHECK (category IN ('gold_approve', 'gold_reject', 'edge_case'));

ALTER TABLE exemplar_library
ADD CONSTRAINT exemplar_library_source_check
CHECK (source IN ('auto', 'manual'));

CREATE INDEX IF NOT EXISTS idx_exemplar_library_brand
  ON exemplar_library(brand_id) WHERE is_active = TRUE;


-- ============================================================================
-- 3. visual_embeddings — Structured descriptors + pgvector
-- ============================================================================
CREATE TABLE IF NOT EXISTS visual_embeddings (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    generated_ad_id UUID NOT NULL REFERENCES generated_ads(id) ON DELETE CASCADE,
    brand_id UUID NOT NULL,

    -- Structured descriptors (from Gemini Flash)
    visual_descriptors JSONB NOT NULL,

    -- Embedding (OpenAI text-embedding-3-small, 1536 dims)
    embedding VECTOR(1536),

    -- Versioning for future upgrades
    descriptor_schema_version TEXT NOT NULL DEFAULT 'v1',
    descriptor_embedding_version TEXT NOT NULL DEFAULT 'text-embedding-3-small-v1',
    extraction_model TEXT NOT NULL DEFAULT 'gemini-2.0-flash',

    created_at TIMESTAMPTZ DEFAULT NOW(),

    UNIQUE(generated_ad_id)
);

CREATE INDEX IF NOT EXISTS idx_visual_embeddings_vector
  ON visual_embeddings USING ivfflat (embedding vector_cosine_ops)
  WITH (lists = 100);

CREATE INDEX IF NOT EXISTS idx_visual_embeddings_brand
  ON visual_embeddings(brand_id);


-- ============================================================================
-- 4. element_interactions — Pairwise element effects
-- ============================================================================
CREATE TABLE IF NOT EXISTS element_interactions (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    brand_id UUID NOT NULL REFERENCES brands(id) ON DELETE CASCADE,

    -- Element pair (canonical ordering: a < b)
    element_a_name TEXT NOT NULL,
    element_a_value TEXT NOT NULL,
    element_b_name TEXT NOT NULL,
    element_b_value TEXT NOT NULL,

    -- Effect metrics
    interaction_effect FLOAT NOT NULL,
    effect_direction TEXT NOT NULL,
    confidence_interval_low FLOAT,
    confidence_interval_high FLOAT,
    sample_size INT NOT NULL,
    p_value FLOAT,

    -- Ranking
    effect_rank INT,

    -- Metadata
    computed_at TIMESTAMPTZ DEFAULT NOW(),
    computation_window_days INT DEFAULT 90,

    UNIQUE(brand_id, element_a_name, element_a_value, element_b_name, element_b_value)
);

ALTER TABLE element_interactions
ADD CONSTRAINT element_interactions_direction_check
CHECK (effect_direction IN ('synergy', 'conflict', 'neutral'));

CREATE INDEX IF NOT EXISTS idx_element_interactions_brand
  ON element_interactions(brand_id);


-- ============================================================================
-- 5. element_combo_usage — Combo usage tracking for fatigue
-- ============================================================================
CREATE TABLE IF NOT EXISTS element_combo_usage (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    brand_id UUID NOT NULL,
    product_id UUID,

    -- Combo key (sorted canonical form)
    combo_key TEXT NOT NULL,

    -- Individual elements (for querying)
    hook_type TEXT,
    color_mode TEXT,
    template_category TEXT,
    awareness_stage TEXT,

    -- Usage tracking
    last_used_at TIMESTAMPTZ NOT NULL,
    times_used INT NOT NULL DEFAULT 1,

    -- Performance at last use
    last_reward_score FLOAT,

    -- Idempotency guard
    last_ad_run_id UUID
);

-- Functional expression index for unique combo per brand+product
CREATE UNIQUE INDEX IF NOT EXISTS idx_ecu_unique_combo
  ON element_combo_usage(brand_id, COALESCE(product_id, '00000000-0000-0000-0000-000000000000'::uuid), combo_key);

CREATE INDEX IF NOT EXISTS idx_ecu_brand_product
  ON element_combo_usage(brand_id, product_id);

CREATE INDEX IF NOT EXISTS idx_ecu_last_used
  ON element_combo_usage(last_used_at);


-- ============================================================================
-- 6. calibration_proposals — Pending threshold changes
-- ============================================================================
CREATE TABLE IF NOT EXISTS calibration_proposals (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    organization_id UUID,

    -- Current vs proposed config
    current_config_id UUID REFERENCES quality_scoring_config(id),
    proposed_pass_threshold NUMERIC(4,2) NOT NULL,
    proposed_check_weights JSONB NOT NULL,
    proposed_borderline_range JSONB NOT NULL,
    proposed_auto_reject_checks JSONB NOT NULL,

    -- Analysis metrics
    analysis_window_start DATE NOT NULL,
    analysis_window_end DATE NOT NULL,
    total_overrides_analyzed INT NOT NULL,
    false_positive_rate FLOAT,
    false_negative_rate FLOAT,
    expected_approval_rate_change FLOAT,

    -- Safety checks
    meets_min_sample_size BOOLEAN NOT NULL DEFAULT FALSE,
    within_delta_bounds BOOLEAN NOT NULL DEFAULT FALSE,
    min_sample_size_required INT NOT NULL DEFAULT 30,
    max_threshold_delta NUMERIC(4,2) NOT NULL DEFAULT 1.00,

    -- Status
    status TEXT NOT NULL DEFAULT 'proposed',
    proposed_by_job_id UUID,
    proposed_at TIMESTAMPTZ DEFAULT NOW(),
    activated_by UUID,
    activated_at TIMESTAMPTZ,
    activated_config_id UUID,
    dismissed_by UUID,
    dismissed_at TIMESTAMPTZ,
    dismissed_reason TEXT,

    notes TEXT
);

ALTER TABLE calibration_proposals
ADD CONSTRAINT calibration_proposals_status_check
CHECK (status IN ('proposed', 'activated', 'dismissed', 'insufficient_evidence'));

CREATE INDEX IF NOT EXISTS idx_calibration_proposals_status
  ON calibration_proposals(status) WHERE status = 'proposed';


-- ============================================================================
-- 7. Seed weekly quality_calibration job
-- ============================================================================
-- Cron parser uses Python weekday() (Mon=0..Sun=6), NOT standard cron (Sun=0).
-- All cron times are PST (calculate_next_run uses datetime.now(PST)).
INSERT INTO scheduled_jobs (
    job_type, name, schedule_type, cron_expression,
    next_run_at, status, parameters
)
SELECT 'quality_calibration', 'Weekly Quality Calibration', 'recurring',
       '0 3 * * 6',                   -- 6 = Sunday in Python weekday()
       NOW() + interval '5 minutes',  -- near-immediate first run to verify handler
       'active', '{"window_days": 30}'::jsonb
WHERE NOT EXISTS (
    SELECT 1 FROM scheduled_jobs WHERE job_type = 'quality_calibration'
);


-- ============================================================================
-- 8. Add FK from exemplar_library to visual_embeddings
-- ============================================================================
ALTER TABLE exemplar_library
ADD CONSTRAINT exemplar_library_visual_embedding_fk
FOREIGN KEY (visual_embedding_id) REFERENCES visual_embeddings(id) ON DELETE SET NULL;
