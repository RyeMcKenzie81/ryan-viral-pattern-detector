-- ============================================
-- BELIEF-FIRST PLANNING TABLES
-- Migration: 2025-12-15
-- Purpose: Create tables for belief-first ad planning system
--
-- Tables created:
--   - belief_offers: Versioned offers for products
--   - belief_sublayers: Persona relevance modifiers (6 types)
--   - belief_jtbd_framed: Persona-framed JTBDs for plan linking
--   - belief_angles: Angle beliefs (main new entity)
--   - belief_plans: Plan configuration + compiled payload
--   - belief_plan_angles: Many-to-many plan ↔ angles
--   - belief_plan_templates: Many-to-many plan ↔ templates
--   - belief_plan_runs: Phase run tracking
--
-- VERIFIED: No naming collisions with existing tables
-- ============================================

-- ============================================
-- 1. BELIEF OFFERS
-- Proper offer versioning (vs products.current_offer string)
-- ============================================
CREATE TABLE IF NOT EXISTS belief_offers (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    product_id UUID NOT NULL REFERENCES products(id) ON DELETE CASCADE,
    name TEXT NOT NULL,
    description TEXT,
    urgency_drivers JSONB DEFAULT '[]'::jsonb, -- ["limited time", "bonus gift", etc.]
    active BOOLEAN DEFAULT true,
    created_by UUID,
    created_at TIMESTAMPTZ DEFAULT NOW(),
    updated_at TIMESTAMPTZ DEFAULT NOW()
);

COMMENT ON TABLE belief_offers IS 'Versioned offers for products (vs products.current_offer string)';
COMMENT ON COLUMN belief_offers.urgency_drivers IS 'Array of urgency/incentive drivers: limited time, bonus, discount, etc.';

-- ============================================
-- 2. BELIEF SUBLAYERS
-- Persona relevance modifiers (6 canonical types only)
-- Schema for PHASE_3 - UI not in MVP
-- ============================================
CREATE TABLE IF NOT EXISTS belief_sublayers (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    persona_id UUID NOT NULL REFERENCES personas_4d(id) ON DELETE CASCADE,
    sublayer_type TEXT NOT NULL CHECK (sublayer_type IN (
        'geography_locale',
        'asset_specific',
        'environment_context',
        'lifestyle_usage',
        'purchase_constraints',
        'values_identity'
    )),
    name TEXT NOT NULL,
    values JSONB NOT NULL DEFAULT '[]'::jsonb, -- ["Vancouver", "BC", "Canada"] or ["Labrador", "Golden Retriever"]
    notes TEXT,
    created_by UUID,
    created_at TIMESTAMPTZ DEFAULT NOW()
);

COMMENT ON TABLE belief_sublayers IS 'Persona relevance modifiers (6 canonical types only). Used in PHASE_3.';
COMMENT ON COLUMN belief_sublayers.sublayer_type IS 'One of: geography_locale, asset_specific, environment_context, lifestyle_usage, purchase_constraints, values_identity';
COMMENT ON COLUMN belief_sublayers.values IS 'Array of values for this sublayer type';

-- ============================================
-- 3. BELIEF JTBD FRAMED
-- Persona-framed JTBDs for explicit plan linking
-- ============================================
CREATE TABLE IF NOT EXISTS belief_jtbd_framed (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    persona_id UUID NOT NULL REFERENCES personas_4d(id) ON DELETE CASCADE,
    product_id UUID NOT NULL REFERENCES products(id) ON DELETE CASCADE,
    name TEXT NOT NULL,
    description TEXT,
    progress_statement TEXT, -- "When I..., I want to..., so I can..."
    source TEXT DEFAULT 'manual' CHECK (source IN ('manual', 'extracted_from_persona', 'ai_generated')),
    created_by UUID,
    created_at TIMESTAMPTZ DEFAULT NOW()
);

COMMENT ON TABLE belief_jtbd_framed IS 'Persona-framed JTBDs (advertising-relevant, for plan linking)';
COMMENT ON COLUMN belief_jtbd_framed.progress_statement IS 'Progress statement format: When I..., I want to..., so I can...';
COMMENT ON COLUMN belief_jtbd_framed.source IS 'How this JTBD was created: manual, extracted_from_persona, or ai_generated';

-- ============================================
-- 4. BELIEF ANGLES
-- The main new entity - angle beliefs
-- ============================================
CREATE TABLE IF NOT EXISTS belief_angles (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    jtbd_framed_id UUID NOT NULL REFERENCES belief_jtbd_framed(id) ON DELETE CASCADE,
    name TEXT NOT NULL,
    belief_statement TEXT NOT NULL, -- The core belief/explanation
    explanation TEXT, -- Why this angle works
    status TEXT DEFAULT 'untested' CHECK (status IN ('untested', 'testing', 'winner', 'loser')),
    created_by UUID,
    created_at TIMESTAMPTZ DEFAULT NOW()
);

COMMENT ON TABLE belief_angles IS 'Angle beliefs that explain why the JTBD exists and why this solution works';
COMMENT ON COLUMN belief_angles.belief_statement IS 'The core belief or explanation this angle represents';
COMMENT ON COLUMN belief_angles.status IS 'Testing status: untested, testing, winner, or loser';

-- ============================================
-- 5. BELIEF PLANS
-- Plan configuration + compiled payload
-- ============================================
CREATE TABLE IF NOT EXISTS belief_plans (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    name TEXT NOT NULL,
    brand_id UUID NOT NULL REFERENCES brands(id) ON DELETE CASCADE,
    product_id UUID NOT NULL REFERENCES products(id) ON DELETE CASCADE,
    offer_id UUID REFERENCES belief_offers(id) ON DELETE SET NULL,
    persona_id UUID NOT NULL REFERENCES personas_4d(id) ON DELETE CASCADE,
    jtbd_framed_id UUID NOT NULL REFERENCES belief_jtbd_framed(id) ON DELETE CASCADE,
    phase_id INTEGER NOT NULL DEFAULT 1 CHECK (phase_id BETWEEN 1 AND 6),
    template_strategy TEXT DEFAULT 'fixed' CHECK (template_strategy IN ('fixed', 'random')),
    ads_per_angle INTEGER DEFAULT 3 CHECK (ads_per_angle > 0),
    status TEXT DEFAULT 'draft' CHECK (status IN ('draft', 'ready', 'running', 'completed')),
    compiled_payload JSONB, -- Generator-ready deterministic payload
    created_by UUID,
    created_at TIMESTAMPTZ DEFAULT NOW(),
    compiled_at TIMESTAMPTZ
);

COMMENT ON TABLE belief_plans IS 'Ad testing plans with compiled payload for ad creator';
COMMENT ON COLUMN belief_plans.phase_id IS 'Testing phase 1-6: 1=Discovery, 2=Confirmation, 3=SubLayer, 4=Mechanism, 5=Benefit, 6=Format';
COMMENT ON COLUMN belief_plans.template_strategy IS 'How templates are assigned: fixed or random';
COMMENT ON COLUMN belief_plans.compiled_payload IS 'Deterministic JSON payload for ad generator consumption';

-- ============================================
-- 6. BELIEF PLAN ANGLES
-- Many-to-many: plan ↔ angles
-- ============================================
CREATE TABLE IF NOT EXISTS belief_plan_angles (
    plan_id UUID NOT NULL REFERENCES belief_plans(id) ON DELETE CASCADE,
    angle_id UUID NOT NULL REFERENCES belief_angles(id) ON DELETE CASCADE,
    display_order INTEGER DEFAULT 0,
    PRIMARY KEY (plan_id, angle_id)
);

COMMENT ON TABLE belief_plan_angles IS 'Junction table linking plans to their selected angles';

-- ============================================
-- 7. BELIEF PLAN TEMPLATES
-- Many-to-many: plan ↔ templates
-- ============================================
CREATE TABLE IF NOT EXISTS belief_plan_templates (
    plan_id UUID NOT NULL REFERENCES belief_plans(id) ON DELETE CASCADE,
    template_id UUID NOT NULL REFERENCES ad_brief_templates(id) ON DELETE CASCADE,
    display_order INTEGER DEFAULT 0,
    PRIMARY KEY (plan_id, template_id)
);

COMMENT ON TABLE belief_plan_templates IS 'Junction table linking plans to their selected templates';

-- ============================================
-- 8. BELIEF PLAN RUNS
-- Phase run tracking (for future PHASE_3+)
-- ============================================
CREATE TABLE IF NOT EXISTS belief_plan_runs (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    plan_id UUID NOT NULL REFERENCES belief_plans(id) ON DELETE CASCADE,
    phase_id INTEGER NOT NULL CHECK (phase_id BETWEEN 1 AND 6),
    status TEXT DEFAULT 'pending' CHECK (status IN ('pending', 'running', 'completed', 'failed')),
    started_at TIMESTAMPTZ,
    completed_at TIMESTAMPTZ,
    results JSONB, -- Performance data, winner angles, etc.
    created_at TIMESTAMPTZ DEFAULT NOW()
);

COMMENT ON TABLE belief_plan_runs IS 'Track phase execution history for a plan';
COMMENT ON COLUMN belief_plan_runs.results IS 'Performance data, winner/loser angles, CPA metrics, etc.';

-- ============================================
-- INDEXES
-- ============================================
CREATE INDEX IF NOT EXISTS idx_belief_offers_product ON belief_offers(product_id);
CREATE INDEX IF NOT EXISTS idx_belief_offers_active ON belief_offers(product_id, active) WHERE active = true;

CREATE INDEX IF NOT EXISTS idx_belief_sublayers_persona ON belief_sublayers(persona_id);
CREATE INDEX IF NOT EXISTS idx_belief_sublayers_type ON belief_sublayers(sublayer_type);

CREATE INDEX IF NOT EXISTS idx_belief_jtbd_framed_persona ON belief_jtbd_framed(persona_id);
CREATE INDEX IF NOT EXISTS idx_belief_jtbd_framed_product ON belief_jtbd_framed(product_id);
CREATE INDEX IF NOT EXISTS idx_belief_jtbd_framed_persona_product ON belief_jtbd_framed(persona_id, product_id);

CREATE INDEX IF NOT EXISTS idx_belief_angles_jtbd ON belief_angles(jtbd_framed_id);
CREATE INDEX IF NOT EXISTS idx_belief_angles_status ON belief_angles(status);

CREATE INDEX IF NOT EXISTS idx_belief_plans_brand ON belief_plans(brand_id);
CREATE INDEX IF NOT EXISTS idx_belief_plans_product ON belief_plans(product_id);
CREATE INDEX IF NOT EXISTS idx_belief_plans_status ON belief_plans(status);
CREATE INDEX IF NOT EXISTS idx_belief_plans_phase ON belief_plans(phase_id);

CREATE INDEX IF NOT EXISTS idx_belief_plan_runs_plan ON belief_plan_runs(plan_id);
CREATE INDEX IF NOT EXISTS idx_belief_plan_runs_status ON belief_plan_runs(status);

-- ============================================
-- RLS POLICIES (basic - user sees own data)
-- ============================================

-- Enable RLS on all tables
ALTER TABLE belief_offers ENABLE ROW LEVEL SECURITY;
ALTER TABLE belief_sublayers ENABLE ROW LEVEL SECURITY;
ALTER TABLE belief_jtbd_framed ENABLE ROW LEVEL SECURITY;
ALTER TABLE belief_angles ENABLE ROW LEVEL SECURITY;
ALTER TABLE belief_plans ENABLE ROW LEVEL SECURITY;
ALTER TABLE belief_plan_angles ENABLE ROW LEVEL SECURITY;
ALTER TABLE belief_plan_templates ENABLE ROW LEVEL SECURITY;
ALTER TABLE belief_plan_runs ENABLE ROW LEVEL SECURITY;

-- For now, allow all authenticated users full access
-- TODO: Add workspace/team-based RLS when multi-tenant is implemented

CREATE POLICY "Allow authenticated users full access to belief_offers"
    ON belief_offers FOR ALL TO authenticated USING (true) WITH CHECK (true);

CREATE POLICY "Allow authenticated users full access to belief_sublayers"
    ON belief_sublayers FOR ALL TO authenticated USING (true) WITH CHECK (true);

CREATE POLICY "Allow authenticated users full access to belief_jtbd_framed"
    ON belief_jtbd_framed FOR ALL TO authenticated USING (true) WITH CHECK (true);

CREATE POLICY "Allow authenticated users full access to belief_angles"
    ON belief_angles FOR ALL TO authenticated USING (true) WITH CHECK (true);

CREATE POLICY "Allow authenticated users full access to belief_plans"
    ON belief_plans FOR ALL TO authenticated USING (true) WITH CHECK (true);

CREATE POLICY "Allow authenticated users full access to belief_plan_angles"
    ON belief_plan_angles FOR ALL TO authenticated USING (true) WITH CHECK (true);

CREATE POLICY "Allow authenticated users full access to belief_plan_templates"
    ON belief_plan_templates FOR ALL TO authenticated USING (true) WITH CHECK (true);

CREATE POLICY "Allow authenticated users full access to belief_plan_runs"
    ON belief_plan_runs FOR ALL TO authenticated USING (true) WITH CHECK (true);

-- ============================================
-- DONE
-- ============================================
