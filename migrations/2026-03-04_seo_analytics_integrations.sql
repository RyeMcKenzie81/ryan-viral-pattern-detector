-- Migration: SEO analytics integrations
-- Date: 2026-03-04
-- Purpose: Add seo_article_analytics table for GSC/GA4/Shopify data,
--          add source/impressions/clicks/ctr columns to seo_article_rankings

CREATE TABLE IF NOT EXISTS seo_article_analytics (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    article_id UUID NOT NULL REFERENCES seo_articles(id) ON DELETE CASCADE,
    organization_id UUID NOT NULL REFERENCES organizations(id),
    date DATE NOT NULL,
    source TEXT NOT NULL,          -- 'gsc', 'ga4', 'shopify'
    impressions INT DEFAULT 0,
    clicks INT DEFAULT 0,
    ctr FLOAT DEFAULT 0.0,
    average_position FLOAT,
    sessions INT DEFAULT 0,
    pageviews INT DEFAULT 0,
    avg_time_on_page FLOAT DEFAULT 0.0,
    bounce_rate FLOAT,
    conversions INT DEFAULT 0,
    revenue NUMERIC(12, 2) DEFAULT 0.00,
    raw_data JSONB DEFAULT '{}',
    synced_at TIMESTAMPTZ DEFAULT NOW(),
    created_at TIMESTAMPTZ DEFAULT NOW(),
    UNIQUE(article_id, date, source)
);

-- Indexes for common query patterns
CREATE INDEX IF NOT EXISTS idx_seo_article_analytics_article_id ON seo_article_analytics(article_id);
CREATE INDEX IF NOT EXISTS idx_seo_article_analytics_date ON seo_article_analytics(date);
CREATE INDEX IF NOT EXISTS idx_seo_article_analytics_source ON seo_article_analytics(source);
CREATE INDEX IF NOT EXISTS idx_seo_article_analytics_org ON seo_article_analytics(organization_id);

-- RLS (matches existing SEO table pattern)
ALTER TABLE seo_article_analytics ENABLE ROW LEVEL SECURITY;
CREATE POLICY seo_article_analytics_policy ON seo_article_analytics
    FOR ALL TO authenticated USING (true) WITH CHECK (true);

-- Add source column to existing rankings table
ALTER TABLE seo_article_rankings ADD COLUMN IF NOT EXISTS source TEXT DEFAULT 'manual';
ALTER TABLE seo_article_rankings ADD COLUMN IF NOT EXISTS impressions INT DEFAULT 0;
ALTER TABLE seo_article_rankings ADD COLUMN IF NOT EXISTS clicks INT DEFAULT 0;
ALTER TABLE seo_article_rankings ADD COLUMN IF NOT EXISTS ctr FLOAT DEFAULT 0.0;
