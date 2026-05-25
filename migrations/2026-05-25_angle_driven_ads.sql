-- Migration: Angle-Driven Ad Creator V1 schema
-- Date: 2026-05-25
-- Plan: docs/plans/angle-driven-ad-creator/PLAN.md
--
-- This migration enables the strategy-first ad creation flow:
--   1. Extends belief_angles to support AI-generated angles (decoupled from
--      curated belief_jtbd_framed rows; see decision OV-1 in PLAN.md).
--   2. Adds hook_embedding + ad_creation_run_id to generated_ads for the
--      cross-angle hook similarity falsifiability metric (P4).
--   3. Creates angle_generation_runs as the audit table for "generate N angles
--      for (persona, offer, LP)" events.
--   4. Folds the deprecated content_source='belief_first' into 'angles' (UX-1).
--
-- Decisions captured in PLAN.md (12 total). Key invariants this migration
-- preserves:
--   - belief_angles.jtbd_framed_id was NOT NULL; we drop the NOT NULL so the
--     generator can write angles without polluting belief_jtbd_framed with
--     synthetic rows. Manual / curated angles can still set jtbd_framed_id.
--   - generated_ads.angle_id already exists (sql/migration_generated_ads_belief_metadata.sql);
--     this migration does NOT touch it. The new flow simply populates it.
--   - HNSW index on hook_embedding (not ivfflat) because writes are continuous;
--     ivfflat would require periodic REINDEX as the distribution drifts.

BEGIN;

-- =============================================================================
-- 0. PREAMBLE
-- =============================================================================

-- pgvector required for hook_embedding. Idempotent.
-- Confirmed installed on production Supabase as v0.8.0 (2026-05-25 preflight).
CREATE EXTENSION IF NOT EXISTS vector;


-- =============================================================================
-- 1. belief_angles EXTENSIONS
-- =============================================================================

-- Drop NOT NULL on jtbd_framed_id: AI-generated angles store their JTBD as
-- text on the angle row itself rather than auto-creating belief_jtbd_framed
-- rows (which would pollute the curated-jobs semantic over time).
ALTER TABLE belief_angles
    ALTER COLUMN jtbd_framed_id DROP NOT NULL;

-- New columns capturing generation provenance + strategic content
ALTER TABLE belief_angles
    ADD COLUMN IF NOT EXISTS generation_method TEXT,
    ADD COLUMN IF NOT EXISTS source_persona_id UUID REFERENCES personas_4d(id) ON DELETE SET NULL,
    ADD COLUMN IF NOT EXISTS source_offer_variant_id UUID REFERENCES product_offer_variants(id) ON DELETE SET NULL,
    ADD COLUMN IF NOT EXISTS source_landing_page_url TEXT,
    ADD COLUMN IF NOT EXISTS jtbd_text TEXT,
    ADD COLUMN IF NOT EXISTS pain_points JSONB,
    ADD COLUMN IF NOT EXISTS desired_outcome TEXT,
    ADD COLUMN IF NOT EXISTS angle_generation_run_id UUID;

-- Indexes for the new lookup paths
CREATE INDEX IF NOT EXISTS idx_belief_angles_source_persona
    ON belief_angles(source_persona_id)
    WHERE source_persona_id IS NOT NULL;

CREATE INDEX IF NOT EXISTS idx_belief_angles_source_offer_variant
    ON belief_angles(source_offer_variant_id)
    WHERE source_offer_variant_id IS NOT NULL;

CREATE INDEX IF NOT EXISTS idx_belief_angles_generation_method
    ON belief_angles(generation_method)
    WHERE generation_method IS NOT NULL;

-- Column docs
COMMENT ON COLUMN belief_angles.generation_method IS
    'How this angle was created. Examples: persona_offer_lp_v1, manual, bre_promoted, reddit_candidate.';
COMMENT ON COLUMN belief_angles.source_persona_id IS
    'Snapshot of the persona this angle was generated for. NULL for non-generated angles.';
COMMENT ON COLUMN belief_angles.source_offer_variant_id IS
    'Snapshot of the offer_variant this angle was generated for. NULL for non-generated angles.';
COMMENT ON COLUMN belief_angles.source_landing_page_url IS
    'Landing page URL captured at generation time. URL only, no body snapshot (intentional YAGNI).';
COMMENT ON COLUMN belief_angles.jtbd_text IS
    'JTBD text for AI-generated angles. When set, jtbd_framed_id is typically NULL. When jtbd_framed_id is set (curated angle), this is typically NULL.';
COMMENT ON COLUMN belief_angles.pain_points IS
    'Array of pain point strings the angle leans on. JSONB to allow flexible schema.';
COMMENT ON COLUMN belief_angles.desired_outcome IS
    'The felt state the persona enters if the angle works. One sentence in the persona''s language.';
COMMENT ON COLUMN belief_angles.angle_generation_run_id IS
    'FK to angle_generation_runs. Identifies the "generate N angles" event that produced this row. NULL for manual angles.';


-- =============================================================================
-- 2. angle_generation_runs TABLE (new)
-- =============================================================================

-- Audit table for "generate N angles for (persona, offer, LP)" events.
-- Separate from generated_ads.ad_creation_run_id (which tracks scheduler runs
-- producing ads from saved angles). See decision 1C in PLAN.md.
CREATE TABLE IF NOT EXISTS angle_generation_runs (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    created_by_user_id UUID,

    -- Inputs
    persona_id UUID REFERENCES personas_4d(id) ON DELETE SET NULL,
    offer_variant_id UUID REFERENCES product_offer_variants(id) ON DELETE SET NULL,
    landing_page_url TEXT,
    n_angles_requested INTEGER NOT NULL CHECK (n_angles_requested > 0),

    -- Prompt versioning
    generator_prompt_version TEXT NOT NULL,

    -- Outputs (populated after generation completes)
    angle_ids UUID[]
);

COMMENT ON TABLE angle_generation_runs IS
    'Audit log for AngleGeneratorService runs. One row per "generate N angles" event. Joined to belief_angles via angle_generation_run_id.';
COMMENT ON COLUMN angle_generation_runs.generator_prompt_version IS
    'Prompt version string (e.g. "angle_generation_v1"). Enables A/B-style comparison across prompt revisions.';
COMMENT ON COLUMN angle_generation_runs.angle_ids IS
    'Array of belief_angles.id rows produced by this run. Denormalized for fast lookup of "all angles from one generation."';

CREATE INDEX IF NOT EXISTS idx_angle_generation_runs_persona
    ON angle_generation_runs(persona_id)
    WHERE persona_id IS NOT NULL;

CREATE INDEX IF NOT EXISTS idx_angle_generation_runs_offer_variant
    ON angle_generation_runs(offer_variant_id)
    WHERE offer_variant_id IS NOT NULL;

CREATE INDEX IF NOT EXISTS idx_angle_generation_runs_created_at
    ON angle_generation_runs(created_at DESC);

-- RLS following the project's belief_planning pattern
ALTER TABLE angle_generation_runs ENABLE ROW LEVEL SECURITY;

DROP POLICY IF EXISTS "Allow authenticated users full access to angle_generation_runs"
    ON angle_generation_runs;
CREATE POLICY "Allow authenticated users full access to angle_generation_runs"
    ON angle_generation_runs
    FOR ALL TO authenticated
    USING (true) WITH CHECK (true);

-- FK from belief_angles.angle_generation_run_id (added now that the table exists)
ALTER TABLE belief_angles
    DROP CONSTRAINT IF EXISTS belief_angles_angle_generation_run_id_fkey;
ALTER TABLE belief_angles
    ADD CONSTRAINT belief_angles_angle_generation_run_id_fkey
    FOREIGN KEY (angle_generation_run_id)
    REFERENCES angle_generation_runs(id)
    ON DELETE SET NULL;

CREATE INDEX IF NOT EXISTS idx_belief_angles_angle_generation_run
    ON belief_angles(angle_generation_run_id)
    WHERE angle_generation_run_id IS NOT NULL;


-- =============================================================================
-- 3. generated_ads EXTENSIONS
-- =============================================================================

-- hook_embedding for cross-angle similarity falsifiability metric (decision P6
-- in PLAN.md). VECTOR(1536) matches text-embedding-3-small, consistent with
-- discovered_patterns.centroid_embedding (migrations/2026-01-05_discovered_patterns.sql:68).
ALTER TABLE generated_ads
    ADD COLUMN IF NOT EXISTS hook_embedding VECTOR(1536);

COMMENT ON COLUMN generated_ads.hook_embedding IS
    'OpenAI text-embedding-3-small (1536d) embedding of hook_text. Populated by HookDiversityChecker at generation time. Used for in-batch diversity rejection and the 30-day cross-angle similarity falsifiability report (PLAN.md P4).';

-- ad_creation_run_id FK to scheduled_jobs.id (decision 1C in PLAN.md).
-- Groups ads created in one scheduler run, distinct from belief_angles.angle_generation_run_id.
ALTER TABLE generated_ads
    ADD COLUMN IF NOT EXISTS ad_creation_run_id UUID;

-- Soft FK reference (no constraint, since scheduled_jobs may have its own lifecycle).
COMMENT ON COLUMN generated_ads.ad_creation_run_id IS
    'FK reference to scheduled_jobs.id — which scheduler run produced this ad. Required for the cross-angle hook similarity report (groups ads created head-to-head in the same run, then groups by angle_id within the run).';

CREATE INDEX IF NOT EXISTS idx_generated_ads_ad_creation_run
    ON generated_ads(ad_creation_run_id)
    WHERE ad_creation_run_id IS NOT NULL;

-- HNSW index for similarity search (decision 1D). HNSW preferred over ivfflat
-- for incremental writes: no REINDEX needed as the data distribution evolves.
CREATE INDEX IF NOT EXISTS idx_generated_ads_hook_embedding_hnsw
    ON generated_ads
    USING hnsw (hook_embedding vector_cosine_ops);


-- =============================================================================
-- 4. UX-1 DATA MIGRATION: fold content_source='belief_first' into 'angles'
-- =============================================================================

-- The deprecated 'belief_first' mode in viraltracker/ui/pages/21b_🎨_Ad_Creator_V2.py
-- is being removed (UX-1 decision). Its semantics fold into 'angles' since both
-- used belief context as prompting input. Any in-flight or historical scheduled
-- jobs referencing 'belief_first' need their parameters JSONB rewritten so the
-- worker still finds them under the new mode name.
UPDATE scheduled_jobs
   SET parameters = jsonb_set(parameters, '{content_source}', '"angles"'::jsonb)
 WHERE parameters->>'content_source' = 'belief_first';


COMMIT;

-- =============================================================================
-- POST-MIGRATION VERIFICATION
-- =============================================================================
-- After running, verify with:
--
--   SELECT extname, extversion FROM pg_extension WHERE extname = 'vector';
--   -- expect: vector | 0.8.0 (or higher)
--
--   \d belief_angles
--   -- expect: jtbd_framed_id nullable; 8 new columns present
--
--   \d generated_ads
--   -- expect: hook_embedding VECTOR(1536), ad_creation_run_id UUID,
--   --         HNSW index idx_generated_ads_hook_embedding_hnsw
--
--   \d angle_generation_runs
--   -- expect: table exists with RLS enabled
--
--   SELECT COUNT(*) FROM scheduled_jobs WHERE parameters->>'content_source' = 'belief_first';
--   -- expect: 0 (all migrated to 'angles')
