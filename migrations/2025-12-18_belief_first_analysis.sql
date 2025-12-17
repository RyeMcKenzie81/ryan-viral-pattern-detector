-- Migration: Add belief-first landing page analysis columns
-- Date: 2025-12-18
-- Purpose: Support 13-layer belief-first evaluation canvas for landing pages

-- Add belief-first analysis columns to brand landing pages
ALTER TABLE brand_landing_pages
ADD COLUMN IF NOT EXISTS belief_first_analysis JSONB;

ALTER TABLE brand_landing_pages
ADD COLUMN IF NOT EXISTS belief_first_analyzed_at TIMESTAMPTZ;

COMMENT ON COLUMN brand_landing_pages.belief_first_analysis IS
  '13-layer belief-first evaluation canvas analysis (JSONB with layers, summary)';

COMMENT ON COLUMN brand_landing_pages.belief_first_analyzed_at IS
  'Timestamp when belief-first analysis was completed';

-- Add belief-first analysis columns to competitor landing pages
ALTER TABLE competitor_landing_pages
ADD COLUMN IF NOT EXISTS belief_first_analysis JSONB;

ALTER TABLE competitor_landing_pages
ADD COLUMN IF NOT EXISTS belief_first_analyzed_at TIMESTAMPTZ;

COMMENT ON COLUMN competitor_landing_pages.belief_first_analysis IS
  '13-layer belief-first evaluation canvas analysis (JSONB with layers, summary)';

COMMENT ON COLUMN competitor_landing_pages.belief_first_analyzed_at IS
  'Timestamp when belief-first analysis was completed';

-- Aggregation summary table for macro-level analysis
CREATE TABLE IF NOT EXISTS landing_page_belief_analysis_summary (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),

  -- Scope identifiers (one of brand_id or competitor_id will be set)
  brand_id UUID REFERENCES brands(id) ON DELETE CASCADE,
  competitor_id UUID REFERENCES competitors(id) ON DELETE CASCADE,
  product_id UUID REFERENCES products(id) ON DELETE SET NULL,
  competitor_product_id UUID,  -- References competitor_products if needed

  -- Scope type
  scope TEXT NOT NULL CHECK (scope IN ('brand', 'competitor')),

  -- Aggregated layer stats
  -- Example: {"market_context": {"clear": 5, "weak": 2, "missing": 1, "conflicting": 0}, ...}
  layer_summary JSONB NOT NULL DEFAULT '{}',

  -- Problem pages ranked by issues
  -- Example: [{"page_id": "...", "url": "...", "issue_count": 5, "score": 4.5, "top_issues": [...]}]
  problem_pages JSONB NOT NULL DEFAULT '[]',

  -- Overall statistics
  total_pages_analyzed INT DEFAULT 0,
  average_score DECIMAL(3,1),
  most_common_issues JSONB DEFAULT '[]',
  strongest_layers JSONB DEFAULT '[]',

  -- Metadata
  model_used TEXT,
  generated_at TIMESTAMPTZ DEFAULT NOW(),

  created_at TIMESTAMPTZ DEFAULT NOW(),
  updated_at TIMESTAMPTZ DEFAULT NOW()
);

-- Indexes for efficient querying
CREATE INDEX IF NOT EXISTS idx_lp_belief_summary_brand
  ON landing_page_belief_analysis_summary(brand_id)
  WHERE brand_id IS NOT NULL;

CREATE INDEX IF NOT EXISTS idx_lp_belief_summary_competitor
  ON landing_page_belief_analysis_summary(competitor_id)
  WHERE competitor_id IS NOT NULL;

CREATE INDEX IF NOT EXISTS idx_lp_belief_summary_scope
  ON landing_page_belief_analysis_summary(scope);

-- Unique constraint to prevent duplicate summaries
CREATE UNIQUE INDEX IF NOT EXISTS idx_lp_belief_summary_unique_brand
  ON landing_page_belief_analysis_summary(brand_id, product_id)
  WHERE scope = 'brand' AND brand_id IS NOT NULL;

CREATE UNIQUE INDEX IF NOT EXISTS idx_lp_belief_summary_unique_competitor
  ON landing_page_belief_analysis_summary(competitor_id, competitor_product_id)
  WHERE scope = 'competitor' AND competitor_id IS NOT NULL;

COMMENT ON TABLE landing_page_belief_analysis_summary IS
  'Aggregated belief-first analysis summaries across landing pages for brand or competitor';
