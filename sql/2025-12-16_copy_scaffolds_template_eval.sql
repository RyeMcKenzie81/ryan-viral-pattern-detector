-- ============================================
-- Migration: Copy Scaffolds & Template Evaluation
-- Date: 2025-12-16
-- Purpose: Add belief-safe copy generation and template phase eligibility
-- ============================================

-- ============================================
-- 1. COPY SCAFFOLDS TABLE
-- Tokenized templates for headlines and primary text
-- ============================================

CREATE TABLE IF NOT EXISTS copy_scaffolds (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    scope TEXT NOT NULL CHECK (scope IN ('headline', 'primary_text')),
    name TEXT NOT NULL,
    template_text TEXT NOT NULL,  -- Tokenized: "{SYMPTOM_1} is often {ANGLE_CLAIM}"
    phase_min INT DEFAULT 1,
    phase_max INT DEFAULT 6,
    awareness_targets TEXT[] DEFAULT ARRAY['problem-aware', 'early-solution-aware'],
    max_chars INT,  -- headlines: 40
    guardrails JSONB DEFAULT '{}',  -- {"no_discount": true, "no_medical_claims": true}
    template_requirements JSONB DEFAULT '{}',  -- Required tokens: ["ANGLE_CLAIM", "PRODUCT_NAME"]
    is_active BOOLEAN DEFAULT TRUE,
    created_at TIMESTAMPTZ DEFAULT NOW(),
    updated_at TIMESTAMPTZ DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_copy_scaffolds_scope ON copy_scaffolds(scope);
CREATE INDEX IF NOT EXISTS idx_copy_scaffolds_phase ON copy_scaffolds(phase_min, phase_max);
CREATE INDEX IF NOT EXISTS idx_copy_scaffolds_active ON copy_scaffolds(is_active);

COMMENT ON TABLE copy_scaffolds IS 'Tokenized copy templates for belief-safe ad generation';
COMMENT ON COLUMN copy_scaffolds.scope IS 'headline or primary_text';
COMMENT ON COLUMN copy_scaffolds.template_text IS 'Template with {TOKEN} placeholders';
COMMENT ON COLUMN copy_scaffolds.max_chars IS 'Max character limit (40 for headlines)';
COMMENT ON COLUMN copy_scaffolds.guardrails IS 'Validation rules (no_discount, no_medical_claims, etc.)';

-- ============================================
-- 2. ANGLE COPY SETS TABLE
-- Generated copy per angle (not per ad)
-- ============================================

CREATE TABLE IF NOT EXISTS angle_copy_sets (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    brand_id UUID REFERENCES brands(id),
    product_id UUID REFERENCES products(id),
    offer_id UUID REFERENCES belief_offers(id),
    persona_id UUID REFERENCES personas_4d(id),
    jtbd_framed_id UUID REFERENCES belief_jtbd_framed(id),
    angle_id UUID NOT NULL REFERENCES belief_angles(id) ON DELETE CASCADE,
    phase_id INT DEFAULT 1,
    headline_variants JSONB NOT NULL DEFAULT '[]',  -- [{text, scaffold_id, tokens_used}]
    primary_text_variants JSONB NOT NULL DEFAULT '[]',  -- [{text, scaffold_id, tokens_used}]
    token_context JSONB DEFAULT '{}',  -- The values used to fill tokens
    guardrails_validated BOOLEAN DEFAULT FALSE,
    created_at TIMESTAMPTZ DEFAULT NOW(),
    updated_at TIMESTAMPTZ DEFAULT NOW(),
    UNIQUE(angle_id, phase_id)  -- One copy set per angle per phase
);

CREATE INDEX IF NOT EXISTS idx_angle_copy_sets_angle ON angle_copy_sets(angle_id);
CREATE INDEX IF NOT EXISTS idx_angle_copy_sets_phase ON angle_copy_sets(phase_id);

COMMENT ON TABLE angle_copy_sets IS 'Generated copy variants per angle for belief testing';
COMMENT ON COLUMN angle_copy_sets.headline_variants IS 'Array of {text, scaffold_id, tokens_used}';
COMMENT ON COLUMN angle_copy_sets.token_context IS 'Token values used for generation';

-- ============================================
-- 3. TEMPLATE EVALUATIONS TABLE
-- Historical tracking of template phase eligibility scores
-- ============================================

CREATE TABLE IF NOT EXISTS template_evaluations (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    template_id UUID NOT NULL,
    template_source TEXT NOT NULL CHECK (template_source IN ('ad_brief_templates', 'scraped_templates')),
    phase_id INT NOT NULL,

    -- D1-D5 scored 0-3
    d1_belief_clarity INT CHECK (d1_belief_clarity BETWEEN 0 AND 3),
    d2_neutrality INT CHECK (d2_neutrality BETWEEN 0 AND 3),
    d3_reusability INT CHECK (d3_reusability BETWEEN 0 AND 3),
    d4_problem_aware_entry INT CHECK (d4_problem_aware_entry BETWEEN 0 AND 3),
    d5_slot_availability INT CHECK (d5_slot_availability BETWEEN 0 AND 3),

    -- D6 pass/fail
    d6_compliance_pass BOOLEAN NOT NULL DEFAULT FALSE,

    -- Computed fields
    total_score INT GENERATED ALWAYS AS (
        COALESCE(d1_belief_clarity, 0) +
        COALESCE(d2_neutrality, 0) +
        COALESCE(d3_reusability, 0) +
        COALESCE(d4_problem_aware_entry, 0) +
        COALESCE(d5_slot_availability, 0)
    ) STORED,

    -- Phase 1-2 eligible: D6 pass AND total >= 12 AND D2 >= 2
    eligible BOOLEAN GENERATED ALWAYS AS (
        d6_compliance_pass
        AND (COALESCE(d1_belief_clarity, 0) + COALESCE(d2_neutrality, 0) + COALESCE(d3_reusability, 0) + COALESCE(d4_problem_aware_entry, 0) + COALESCE(d5_slot_availability, 0)) >= 12
        AND COALESCE(d2_neutrality, 0) >= 2
    ) STORED,

    evaluation_notes TEXT,
    evaluated_by TEXT DEFAULT 'ai',  -- 'ai' or 'human'
    evaluated_at TIMESTAMPTZ DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_template_evaluations_template ON template_evaluations(template_id, template_source);
CREATE INDEX IF NOT EXISTS idx_template_evaluations_phase ON template_evaluations(phase_id);
CREATE INDEX IF NOT EXISTS idx_template_evaluations_eligible ON template_evaluations(eligible);
CREATE UNIQUE INDEX IF NOT EXISTS idx_template_evaluations_unique ON template_evaluations(template_id, template_source, phase_id);

COMMENT ON TABLE template_evaluations IS 'AI/human evaluation scores for template phase eligibility';
COMMENT ON COLUMN template_evaluations.d1_belief_clarity IS 'Can template clearly express a single belief? (0-3)';
COMMENT ON COLUMN template_evaluations.d2_neutrality IS 'Free of sales bias, offers, urgency? (0-3)';
COMMENT ON COLUMN template_evaluations.d3_reusability IS 'Can work across different angles? (0-3)';
COMMENT ON COLUMN template_evaluations.d4_problem_aware_entry IS 'Supports problem-aware audiences? (0-3)';
COMMENT ON COLUMN template_evaluations.d5_slot_availability IS 'Has clear text slots? (0-3)';
COMMENT ON COLUMN template_evaluations.d6_compliance_pass IS 'No before/after, medical claims, guarantees?';

-- ============================================
-- 4. ADD COLUMNS TO EXISTING TABLES
-- ============================================

-- Add copy_set_id to belief_plans (links plan to its copy)
ALTER TABLE belief_plans ADD COLUMN IF NOT EXISTS copy_set_id UUID REFERENCES angle_copy_sets(id);

COMMENT ON COLUMN belief_plans.copy_set_id IS 'Reference to generated copy for this plan';

-- Add evaluation columns to scraped_templates
ALTER TABLE scraped_templates ADD COLUMN IF NOT EXISTS phase_tags JSONB DEFAULT '{}';
ALTER TABLE scraped_templates ADD COLUMN IF NOT EXISTS slots JSONB DEFAULT '{}';
ALTER TABLE scraped_templates ADD COLUMN IF NOT EXISTS evaluation_score DECIMAL(4,2);
ALTER TABLE scraped_templates ADD COLUMN IF NOT EXISTS evaluation_notes TEXT;
ALTER TABLE scraped_templates ADD COLUMN IF NOT EXISTS evaluated_at TIMESTAMPTZ;

COMMENT ON COLUMN scraped_templates.phase_tags IS 'Phase eligibility metadata: {eligible_phases, awareness_targets, template_bias}';
COMMENT ON COLUMN scraped_templates.slots IS 'Template slot info: {headline, subhead, price_slot, etc.}';
COMMENT ON COLUMN scraped_templates.evaluation_score IS 'Cached total evaluation score (0-15)';

-- Add evaluation columns to ad_brief_templates
ALTER TABLE ad_brief_templates ADD COLUMN IF NOT EXISTS phase_tags JSONB DEFAULT '{}';
ALTER TABLE ad_brief_templates ADD COLUMN IF NOT EXISTS slots JSONB DEFAULT '{}';
ALTER TABLE ad_brief_templates ADD COLUMN IF NOT EXISTS evaluation_score DECIMAL(4,2);
ALTER TABLE ad_brief_templates ADD COLUMN IF NOT EXISTS evaluation_notes TEXT;
ALTER TABLE ad_brief_templates ADD COLUMN IF NOT EXISTS evaluated_at TIMESTAMPTZ;

COMMENT ON COLUMN ad_brief_templates.phase_tags IS 'Phase eligibility metadata: {eligible_phases, awareness_targets, template_bias}';
COMMENT ON COLUMN ad_brief_templates.slots IS 'Template slot info: {headline, subhead, price_slot, etc.}';
COMMENT ON COLUMN ad_brief_templates.evaluation_score IS 'Cached total evaluation score (0-15)';

-- ============================================
-- 5. RLS POLICIES
-- ============================================

-- Enable RLS
ALTER TABLE copy_scaffolds ENABLE ROW LEVEL SECURITY;
ALTER TABLE angle_copy_sets ENABLE ROW LEVEL SECURITY;
ALTER TABLE template_evaluations ENABLE ROW LEVEL SECURITY;

-- All authenticated users can read scaffolds (they're shared)
CREATE POLICY "copy_scaffolds_select" ON copy_scaffolds
    FOR SELECT TO authenticated USING (true);

-- All authenticated users can manage copy sets
CREATE POLICY "angle_copy_sets_all" ON angle_copy_sets
    FOR ALL TO authenticated USING (true) WITH CHECK (true);

-- All authenticated users can manage evaluations
CREATE POLICY "template_evaluations_all" ON template_evaluations
    FOR ALL TO authenticated USING (true) WITH CHECK (true);

-- ============================================
-- DONE
-- ============================================
