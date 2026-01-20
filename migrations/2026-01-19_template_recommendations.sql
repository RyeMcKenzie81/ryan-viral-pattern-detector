-- Migration: Template Recommendations
-- Date: 2026-01-19
-- Purpose: Add product_template_recommendations table for AI-powered template suggestions

-- =============================================================================
-- TABLE: product_template_recommendations
-- =============================================================================
-- Stores template recommendations for products with scoring and usage tracking.
-- Supports multiple recommendation methodologies (AI matching, performance-based, diversity).

CREATE TABLE IF NOT EXISTS product_template_recommendations (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),

    -- Foreign Keys
    product_id UUID NOT NULL REFERENCES products(id) ON DELETE CASCADE,
    template_id UUID NOT NULL REFERENCES scraped_templates(id) ON DELETE CASCADE,
    offer_variant_id UUID REFERENCES product_offer_variants(id) ON DELETE SET NULL,

    -- Recommendation Metadata
    methodology TEXT NOT NULL CHECK (methodology IN ('ai_match', 'performance', 'diversity')),
    score DECIMAL(4,3) NOT NULL CHECK (score >= 0 AND score <= 1),  -- 0.000 to 1.000
    score_breakdown JSONB DEFAULT '{}'::jsonb,  -- {niche_match: 0.9, awareness_match: 0.8, ...}
    reasoning TEXT,  -- AI explanation for the recommendation

    -- Usage Tracking
    used BOOLEAN DEFAULT FALSE,  -- Has this been used in an ad run?
    times_used INTEGER DEFAULT 0,
    last_used_at TIMESTAMPTZ,

    -- Lifecycle
    recommended_at TIMESTAMPTZ DEFAULT NOW(),
    recommended_by TEXT DEFAULT 'system',  -- user identifier or 'system'

    -- Timestamps
    created_at TIMESTAMPTZ DEFAULT NOW(),

    -- Constraints: One recommendation per product-template pair
    UNIQUE(product_id, template_id)
);

-- =============================================================================
-- INDEXES
-- =============================================================================

-- Primary lookup: Get all recommendations for a product
CREATE INDEX idx_ptr_product_id ON product_template_recommendations(product_id);

-- Reverse lookup: Find which products recommend a template
CREATE INDEX idx_ptr_template_id ON product_template_recommendations(template_id);

-- Filter: Get unused recommendations for a product (common query for Ad Creator)
CREATE INDEX idx_ptr_product_unused ON product_template_recommendations(product_id, used) WHERE NOT used;

-- Filter by methodology
CREATE INDEX idx_ptr_methodology ON product_template_recommendations(methodology);

-- Sort by score (for displaying top recommendations)
CREATE INDEX idx_ptr_score ON product_template_recommendations(score DESC);

-- =============================================================================
-- COMMENTS
-- =============================================================================

COMMENT ON TABLE product_template_recommendations IS
'Template recommendations for products. Stores which templates are recommended for each product with scoring, methodology tracking, and usage analytics.';

COMMENT ON COLUMN product_template_recommendations.methodology IS
'How this recommendation was generated: ai_match (AI analysis), performance (based on ad metrics), diversity (format variety)';

COMMENT ON COLUMN product_template_recommendations.score IS
'Overall recommendation score from 0.000 to 1.000, where higher is better';

COMMENT ON COLUMN product_template_recommendations.score_breakdown IS
'JSON breakdown of individual score components: niche_match, awareness_match, audience_match, format_fit';

COMMENT ON COLUMN product_template_recommendations.reasoning IS
'AI-generated explanation for why this template is recommended';

COMMENT ON COLUMN product_template_recommendations.used IS
'Whether this recommendation has been used in at least one ad run';

COMMENT ON COLUMN product_template_recommendations.times_used IS
'Number of times this recommended template has been used for this product';

COMMENT ON COLUMN product_template_recommendations.recommended_at IS
'When this recommendation was created (persists until manually removed)';
