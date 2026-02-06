-- Migration: Usage Limits
-- Date: 2026-01-27
-- Purpose: Per-organization usage limits and enforcement
-- Phase: 7 of Multi-Tenant Auth Plan

-- ============================================================================
-- 1. Create usage_limits table
-- ============================================================================

CREATE TABLE usage_limits (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    organization_id UUID NOT NULL REFERENCES organizations(id) ON DELETE CASCADE,
    limit_type TEXT NOT NULL CHECK (limit_type IN (
        'monthly_tokens', 'monthly_cost', 'daily_ads', 'daily_requests'
    )),
    limit_value NUMERIC NOT NULL,
    period TEXT NOT NULL DEFAULT 'monthly' CHECK (period IN ('daily', 'monthly')),
    alert_threshold NUMERIC DEFAULT 0.8,
    enabled BOOLEAN DEFAULT true,
    created_at TIMESTAMPTZ DEFAULT NOW(),
    updated_at TIMESTAMPTZ DEFAULT NOW(),
    UNIQUE(organization_id, limit_type)
);

COMMENT ON TABLE usage_limits IS 'Per-organization usage limits for billing enforcement';
COMMENT ON COLUMN usage_limits.limit_type IS 'Type of limit: monthly_tokens, monthly_cost, daily_ads, daily_requests';
COMMENT ON COLUMN usage_limits.limit_value IS 'Maximum allowed value for the limit type';
COMMENT ON COLUMN usage_limits.period IS 'Limit period: daily or monthly';
COMMENT ON COLUMN usage_limits.alert_threshold IS 'Percentage (0-1) at which to show a warning (default: 0.8 = 80%)';
COMMENT ON COLUMN usage_limits.enabled IS 'Whether this limit is actively enforced';

-- ============================================================================
-- 2. Index for lookups by organization
-- ============================================================================

CREATE INDEX idx_usage_limits_org ON usage_limits(organization_id);
