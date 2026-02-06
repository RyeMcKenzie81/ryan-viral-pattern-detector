-- Migration: Organization Feature Flags
-- Date: 2026-01-23
-- Purpose: Enable/disable features per organization
-- Phase: 6 of Multi-Tenant Auth Plan

-- ============================================================================
-- 1. Create org_features table
-- ============================================================================

CREATE TABLE org_features (
    organization_id UUID NOT NULL REFERENCES organizations(id) ON DELETE CASCADE,
    feature_key TEXT NOT NULL,
    enabled BOOLEAN DEFAULT false,
    config JSONB DEFAULT '{}',
    created_at TIMESTAMPTZ DEFAULT NOW(),
    updated_at TIMESTAMPTZ DEFAULT NOW(),
    PRIMARY KEY (organization_id, feature_key)
);

COMMENT ON TABLE org_features IS 'Feature flags per organization - controls access to app features';
COMMENT ON COLUMN org_features.feature_key IS 'Feature identifier (e.g., ad_creator, veo_avatars)';
COMMENT ON COLUMN org_features.enabled IS 'Whether the feature is enabled for this org';
COMMENT ON COLUMN org_features.config IS 'Optional feature-specific configuration';

-- Index for efficient lookups
CREATE INDEX idx_org_features_org ON org_features(organization_id);

-- ============================================================================
-- 2. Enable all features for Default Workspace (your org)
-- ============================================================================

INSERT INTO org_features (organization_id, feature_key, enabled) VALUES
    ('00000000-0000-0000-0000-000000000001', 'ad_creator', true),
    ('00000000-0000-0000-0000-000000000001', 'ad_library', true),
    ('00000000-0000-0000-0000-000000000001', 'ad_scheduler', true),
    ('00000000-0000-0000-0000-000000000001', 'ad_planning', true),
    ('00000000-0000-0000-0000-000000000001', 'veo_avatars', true),
    ('00000000-0000-0000-0000-000000000001', 'competitor_research', true),
    ('00000000-0000-0000-0000-000000000001', 'reddit_research', true),
    ('00000000-0000-0000-0000-000000000001', 'brand_research', true),
    ('00000000-0000-0000-0000-000000000001', 'belief_canvas', true),
    ('00000000-0000-0000-0000-000000000001', 'content_pipeline', true),
    ('00000000-0000-0000-0000-000000000001', 'research_insights', true);
