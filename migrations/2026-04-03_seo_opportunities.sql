-- Migration: Create seo_opportunities table for SEO feedback loop
-- Date: 2026-04-03
-- Purpose: Store scored opportunities for near-ranking keywords (positions 11-20)
--          with recommended actions and rank delta tracking

CREATE TABLE IF NOT EXISTS seo_opportunities (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    organization_id UUID NOT NULL REFERENCES organizations(id),
    brand_id UUID NOT NULL REFERENCES brands(id),
    article_id UUID REFERENCES seo_articles(id),
    keyword TEXT NOT NULL,
    current_position NUMERIC,
    position_at_identification NUMERIC,
    impression_trend TEXT,
    impressions_14d INTEGER,
    impressions_28d INTEGER,
    opportunity_score NUMERIC,
    recommended_action TEXT,
    action_reason TEXT,
    status TEXT DEFAULT 'identified',
    actioned_at TIMESTAMPTZ,
    result_article_id UUID REFERENCES seo_articles(id),
    rank_delta_7d NUMERIC,
    rank_delta_14d NUMERIC,
    rank_delta_28d NUMERIC,
    created_at TIMESTAMPTZ DEFAULT NOW(),
    updated_at TIMESTAMPTZ DEFAULT NOW(),
    UNIQUE (article_id, keyword)
);

COMMENT ON TABLE seo_opportunities IS 'Scored SEO opportunities for near-ranking keywords with action recommendations and rank delta tracking';
COMMENT ON COLUMN seo_opportunities.position_at_identification IS 'Baseline position when opportunity was first identified, used for rank_delta calculations';
COMMENT ON COLUMN seo_opportunities.impression_trend IS 'rising, stable, or declining based on 14d vs previous 14d comparison';
COMMENT ON COLUMN seo_opportunities.recommended_action IS 'new_supporting_content, refresh, or optimize_links';
COMMENT ON COLUMN seo_opportunities.status IS 'identified, actioned, resolved, or dismissed';
COMMENT ON COLUMN seo_opportunities.rank_delta_7d IS 'current_position minus position_at_identification after 7 days. Negative = improved (moved up). One-time snapshot.';
COMMENT ON COLUMN seo_opportunities.rank_delta_14d IS 'Rank delta at 14 days. One-time snapshot.';
COMMENT ON COLUMN seo_opportunities.rank_delta_28d IS 'Rank delta at 28 days. One-time snapshot.';

-- RLS: permissive pattern matching existing SEO tables
ALTER TABLE seo_opportunities ENABLE ROW LEVEL SECURITY;
CREATE POLICY "seo_opportunities_permissive" ON seo_opportunities USING (true);

-- Indexes
CREATE INDEX idx_seo_opportunities_brand ON seo_opportunities(brand_id);
CREATE INDEX idx_seo_opportunities_status ON seo_opportunities(status);
CREATE INDEX idx_seo_opportunities_score ON seo_opportunities(opportunity_score DESC);
