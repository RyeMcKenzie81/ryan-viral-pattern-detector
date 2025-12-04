-- ============================================================================
-- Migration: 4D Persona & Competitive Analysis Schema
-- Date: 2025-12-04
-- Purpose: Create tables for 4D persona framework and competitor analysis
-- ============================================================================

-- ============================================================================
-- 4D PERSONA TABLES
-- ============================================================================

-- Main 4D persona table (used for both own brand and competitors)
CREATE TABLE IF NOT EXISTS personas_4d (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),

    -- Ownership (one of these will be set)
    brand_id UUID REFERENCES brands(id) ON DELETE CASCADE,
    product_id UUID REFERENCES products(id) ON DELETE SET NULL,
    competitor_id UUID,  -- Will reference competitors table once created

    -- Classification
    persona_type TEXT NOT NULL CHECK (persona_type IN ('own_brand', 'product_specific', 'competitor')),
    name TEXT NOT NULL,
    is_primary BOOLEAN DEFAULT false,

    -- ========================================
    -- DIMENSION 1: BASICS
    -- ========================================
    snapshot TEXT,  -- Big picture description
    demographics JSONB DEFAULT '{}',  -- {age_range, gender, location, income, education, occupation, family_status}
    behavior_habits JSONB DEFAULT '{}',  -- {daily_routines, media_consumption, free_time, work_life, health_habits}
    digital_presence JSONB DEFAULT '{}',  -- {platforms, content_consumption, shopping_behavior, device_prefs}
    purchase_drivers JSONB DEFAULT '{}',  -- {triggers, research_method, price_sensitivity, brand_loyalty}
    cultural_context JSONB DEFAULT '{}',  -- {background, regional, generational, subcultures}
    typology_profile JSONB DEFAULT '{}',  -- {mbti, enneagram, disc, other}

    -- ========================================
    -- DIMENSION 2: PSYCHOGRAPHIC MAPPING
    -- ========================================
    transformation_map JSONB DEFAULT '{}',  -- {before: [], after: []}

    -- Core desires with verbiage instances
    -- {
    --   "survival_life_extension": [{text: "...", source: "ad/review"}],
    --   "freedom_from_fear": [...],
    --   "superiority_status": [...],
    --   "care_protection": [...],
    --   "social_approval": [...],
    --   "self_actualization": [...],
    --   ... (all 10 categories)
    -- }
    desires JSONB DEFAULT '{}',

    -- ========================================
    -- DIMENSION 3: IDENTITY
    -- ========================================
    self_narratives TEXT[],  -- "Because I am X, therefore I Y"
    current_self_image TEXT,
    past_failures JSONB DEFAULT '{}',  -- {failures: [], blame_attribution: []}
    desired_self_image TEXT,
    identity_artifacts TEXT[],  -- Brands/objects associated with desired image

    -- ========================================
    -- DIMENSION 4: SOCIAL DYNAMICS
    -- ========================================
    -- {
    --   "admire": [],
    --   "envy": [],
    --   "want_to_impress": [],
    --   "love_loyalty": [],
    --   "dislike_animosity": [],
    --   "compared_to": [],
    --   "influence_decisions": [],
    --   "fear_judged_by": [],
    --   "want_to_belong": [],
    --   "distance_from": []
    -- }
    social_relations JSONB DEFAULT '{}',

    -- ========================================
    -- DIMENSION 5: WORLDVIEW
    -- ========================================
    worldview TEXT,  -- General worldview/reality interpretation
    world_stories TEXT,  -- Heroes/villains, cause/effect narratives
    core_values TEXT[],
    forces_of_good TEXT[],
    forces_of_evil TEXT[],
    cultural_zeitgeist TEXT,  -- The era/moment they believe they're in
    allergies JSONB DEFAULT '{}',  -- {trigger: reaction} - things that trigger negative reactions

    -- ========================================
    -- DIMENSION 6: DOMAIN SENTIMENT (Product-Specific)
    -- ========================================
    outcomes_jtbd JSONB DEFAULT '{}',  -- {emotional: [], social: [], functional: []}
    pain_points JSONB DEFAULT '{}',  -- {emotional: [], social: [], functional: []}
    desired_features TEXT[],
    failed_solutions TEXT[],
    buying_objections JSONB DEFAULT '{}',  -- {emotional: [], social: [], functional: []}
    familiar_promises TEXT[],  -- Claims they've heard before

    -- ========================================
    -- DIMENSION 7: PURCHASE BEHAVIOR
    -- ========================================
    pain_symptoms TEXT[],  -- Observable signs of pain points
    activation_events TEXT[],  -- What triggers purchase NOW
    purchasing_habits TEXT,
    decision_process TEXT,
    current_workarounds TEXT[],  -- Hacks they use instead of buying

    -- ========================================
    -- DIMENSION 8: 3D OBJECTIONS
    -- ========================================
    emotional_risks TEXT[],
    barriers_to_behavior TEXT[],

    -- ========================================
    -- META
    -- ========================================
    source_type TEXT CHECK (source_type IN ('manual', 'ai_generated', 'competitor_analysis', 'hybrid')),
    source_data JSONB DEFAULT '{}',  -- Raw analysis data that generated this persona
    confidence_score FLOAT,

    created_at TIMESTAMPTZ DEFAULT NOW(),
    updated_at TIMESTAMPTZ DEFAULT NOW(),
    created_by TEXT DEFAULT 'system'
);

-- Indexes for personas_4d
CREATE INDEX IF NOT EXISTS idx_personas_4d_brand ON personas_4d(brand_id);
CREATE INDEX IF NOT EXISTS idx_personas_4d_product ON personas_4d(product_id);
CREATE INDEX IF NOT EXISTS idx_personas_4d_competitor ON personas_4d(competitor_id);
CREATE INDEX IF NOT EXISTS idx_personas_4d_type ON personas_4d(persona_type);
CREATE INDEX IF NOT EXISTS idx_personas_4d_primary ON personas_4d(is_primary) WHERE is_primary = true;

-- Junction table for products with multiple personas
CREATE TABLE IF NOT EXISTS product_personas (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    product_id UUID REFERENCES products(id) ON DELETE CASCADE NOT NULL,
    persona_id UUID REFERENCES personas_4d(id) ON DELETE CASCADE NOT NULL,
    is_primary BOOLEAN DEFAULT false,
    weight FLOAT DEFAULT 1.0,  -- For weighted persona targeting
    notes TEXT,
    created_at TIMESTAMPTZ DEFAULT NOW(),
    UNIQUE(product_id, persona_id)
);

CREATE INDEX IF NOT EXISTS idx_product_personas_product ON product_personas(product_id);
CREATE INDEX IF NOT EXISTS idx_product_personas_persona ON product_personas(persona_id);

-- Ensure only one primary persona per product
CREATE UNIQUE INDEX IF NOT EXISTS idx_product_personas_primary
ON product_personas(product_id)
WHERE is_primary = true;

-- ============================================================================
-- COMPETITOR TABLES
-- ============================================================================

CREATE TABLE IF NOT EXISTS competitors (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    brand_id UUID REFERENCES brands(id) ON DELETE CASCADE NOT NULL,  -- Our brand tracking this competitor
    name TEXT NOT NULL,
    facebook_page_id TEXT,
    website_url TEXT,
    ad_library_url TEXT,
    industry TEXT,
    notes TEXT,

    -- Analysis status
    last_scraped_at TIMESTAMPTZ,
    last_analyzed_at TIMESTAMPTZ,
    ads_count INTEGER DEFAULT 0,

    created_at TIMESTAMPTZ DEFAULT NOW(),
    updated_at TIMESTAMPTZ DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_competitors_brand ON competitors(brand_id);

-- Now add the foreign key to personas_4d for competitor_id
ALTER TABLE personas_4d
ADD CONSTRAINT fk_personas_4d_competitor
FOREIGN KEY (competitor_id) REFERENCES competitors(id) ON DELETE CASCADE;

-- Competitor ads (separate from facebook_ads to avoid mixing data)
CREATE TABLE IF NOT EXISTS competitor_ads (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    competitor_id UUID REFERENCES competitors(id) ON DELETE CASCADE NOT NULL,
    ad_archive_id TEXT,
    page_name TEXT,
    ad_body TEXT,
    ad_title TEXT,
    link_url TEXT,
    cta_text TEXT,
    started_running DATE,
    is_active BOOLEAN DEFAULT true,
    platforms TEXT[],
    snapshot_data JSONB DEFAULT '{}',

    created_at TIMESTAMPTZ DEFAULT NOW(),
    UNIQUE(competitor_id, ad_archive_id)
);

CREATE INDEX IF NOT EXISTS idx_competitor_ads_competitor ON competitor_ads(competitor_id);

-- Competitor ad assets
CREATE TABLE IF NOT EXISTS competitor_ad_assets (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    competitor_ad_id UUID REFERENCES competitor_ads(id) ON DELETE CASCADE NOT NULL,
    asset_type TEXT CHECK (asset_type IN ('image', 'video')),
    storage_path TEXT,  -- Path in Supabase storage
    original_url TEXT,
    mime_type TEXT,
    file_size INTEGER,

    created_at TIMESTAMPTZ DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_competitor_assets_ad ON competitor_ad_assets(competitor_ad_id);

-- Competitor analysis results (individual ad analyses)
CREATE TABLE IF NOT EXISTS competitor_ad_analysis (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    competitor_id UUID REFERENCES competitors(id) ON DELETE CASCADE NOT NULL,
    competitor_ad_id UUID REFERENCES competitor_ads(id) ON DELETE CASCADE,
    asset_id UUID REFERENCES competitor_ad_assets(id) ON DELETE SET NULL,

    analysis_type TEXT CHECK (analysis_type IN ('ad_creative', 'ad_copy', 'landing_page', 'combined')),

    -- Extracted data
    raw_response JSONB DEFAULT '{}',

    -- Structured extractions
    products_mentioned TEXT[],
    benefits_mentioned TEXT[],
    pain_points_addressed TEXT[],
    desires_appealed JSONB DEFAULT '{}',  -- {desire_category: [instances]}
    hooks_extracted JSONB DEFAULT '[]',  -- [{text, type, notes}]
    messaging_patterns TEXT[],
    awareness_level INTEGER CHECK (awareness_level BETWEEN 1 AND 5),

    -- AI metadata
    model_used TEXT,
    tokens_used INTEGER,
    cost_usd FLOAT,

    created_at TIMESTAMPTZ DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_competitor_analysis_competitor ON competitor_ad_analysis(competitor_id);
CREATE INDEX IF NOT EXISTS idx_competitor_analysis_ad ON competitor_ad_analysis(competitor_ad_id);

-- Competitor landing page analysis
CREATE TABLE IF NOT EXISTS competitor_landing_pages (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    competitor_id UUID REFERENCES competitors(id) ON DELETE CASCADE NOT NULL,
    url TEXT NOT NULL,

    -- Scraped content (via FireCrawl)
    page_title TEXT,
    meta_description TEXT,
    raw_markdown TEXT,

    -- AI analysis
    products JSONB DEFAULT '[]',  -- [{name, price, description}]
    offers JSONB DEFAULT '[]',  -- [{type, details, urgency}]
    social_proof JSONB DEFAULT '[]',  -- [{type, content, source}]
    guarantees TEXT[],
    usps TEXT[],
    objection_handling JSONB DEFAULT '[]',  -- [{objection, response}]

    -- Meta
    scraped_at TIMESTAMPTZ,
    analyzed_at TIMESTAMPTZ,
    model_used TEXT,

    created_at TIMESTAMPTZ DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_competitor_lp_competitor ON competitor_landing_pages(competitor_id);

-- ============================================================================
-- COMMENTS
-- ============================================================================

COMMENT ON TABLE personas_4d IS '4D persona profiles for own brand products and competitors';
COMMENT ON TABLE product_personas IS 'Junction table linking products to multiple personas';
COMMENT ON TABLE competitors IS 'Competitors being tracked for competitive analysis';
COMMENT ON TABLE competitor_ads IS 'Ads scraped from competitor Ad Library pages';
COMMENT ON TABLE competitor_ad_assets IS 'Images/videos from competitor ads';
COMMENT ON TABLE competitor_ad_analysis IS 'AI analysis of individual competitor ads';
COMMENT ON TABLE competitor_landing_pages IS 'Scraped and analyzed competitor landing pages';

-- Column comments for personas_4d
COMMENT ON COLUMN personas_4d.persona_type IS 'own_brand = brand-level, product_specific = for a product, competitor = extracted from competitor';
COMMENT ON COLUMN personas_4d.snapshot IS 'Big picture 2-3 sentence description of this persona';
COMMENT ON COLUMN personas_4d.transformation_map IS 'Before/after transformation: {before: [], after: []}';
COMMENT ON COLUMN personas_4d.desires IS '10 core desires with verbiage instances: {category: [{text, source}]}';
COMMENT ON COLUMN personas_4d.social_relations IS '10 social relationship types: admire, envy, impress, etc.';
COMMENT ON COLUMN personas_4d.allergies IS 'Things that trigger negative reactions: {trigger: reaction}';
COMMENT ON COLUMN personas_4d.activation_events IS 'What triggers them to buy NOW';
COMMENT ON COLUMN personas_4d.source_type IS 'How this persona was created: manual, ai_generated, competitor_analysis, hybrid';
