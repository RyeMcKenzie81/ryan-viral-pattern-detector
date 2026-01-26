-- Migration: Token/API Usage Tracking
-- Date: 2026-01-24
-- Purpose: Track all AI/API usage for billing and analytics
-- Phase: 4 Step 0 of Multi-Tenant Auth Plan

-- ============================================================================
-- 1. Create token_usage table
-- ============================================================================

CREATE TABLE token_usage (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),

    -- Who triggered the usage
    user_id UUID REFERENCES auth.users(id),
    organization_id UUID NOT NULL REFERENCES organizations(id),

    -- What was called
    provider TEXT NOT NULL,           -- 'anthropic', 'openai', 'google', 'elevenlabs'
    model TEXT NOT NULL,              -- 'claude-opus-4-5', 'gpt-4o', 'gemini-2.0-flash'
    tool_name TEXT,                   -- 'ad_creator', 'competitor_research', 'gemini_service'
    operation TEXT,                   -- 'generate_image', 'analyze_text', 'review_image'

    -- Token usage (for LLM calls)
    input_tokens INT DEFAULT 0,
    output_tokens INT DEFAULT 0,
    total_tokens INT GENERATED ALWAYS AS (input_tokens + output_tokens) STORED,

    -- Unit usage (for non-token APIs: images, video, audio)
    units NUMERIC,                    -- e.g., 1 for image, 30 for video seconds
    unit_type TEXT,                   -- 'images', 'video_seconds', 'characters'

    -- Cost tracking
    cost_usd NUMERIC(10, 6),          -- Calculated cost in USD

    -- Context and metadata
    request_metadata JSONB,           -- Additional context (brand_id, ad_id, etc.)

    -- Timing
    duration_ms INT,                  -- How long the API call took
    created_at TIMESTAMPTZ DEFAULT NOW()
);

COMMENT ON TABLE token_usage IS 'Tracks all AI/API usage for billing, limits, and analytics';
COMMENT ON COLUMN token_usage.provider IS 'AI provider: anthropic, openai, google, elevenlabs';
COMMENT ON COLUMN token_usage.model IS 'Specific model used';
COMMENT ON COLUMN token_usage.tool_name IS 'Which tool/service triggered the call';
COMMENT ON COLUMN token_usage.operation IS 'Specific operation performed';
COMMENT ON COLUMN token_usage.units IS 'Non-token units (images, seconds, characters)';
COMMENT ON COLUMN token_usage.cost_usd IS 'Calculated cost in USD';

-- ============================================================================
-- 2. Indexes for common queries
-- ============================================================================

-- Query by organization and time (billing)
CREATE INDEX idx_token_usage_org_created ON token_usage(organization_id, created_at DESC);

-- Query by user and time (user-level tracking)
CREATE INDEX idx_token_usage_user_created ON token_usage(user_id, created_at DESC);

-- Query by tool (identify expensive tools)
CREATE INDEX idx_token_usage_tool ON token_usage(tool_name, created_at DESC);

-- Query by provider (provider breakdown)
CREATE INDEX idx_token_usage_provider ON token_usage(provider, created_at DESC);

-- ============================================================================
-- 3. Helper function for summing usage
-- ============================================================================

CREATE OR REPLACE FUNCTION sum_token_usage(
    p_org_id UUID,
    p_column TEXT,
    p_start_date TIMESTAMPTZ
) RETURNS NUMERIC AS $$
DECLARE
    result NUMERIC;
BEGIN
    IF p_column = 'cost_usd' THEN
        SELECT COALESCE(SUM(cost_usd), 0) INTO result
        FROM token_usage
        WHERE organization_id = p_org_id AND created_at >= p_start_date;
    ELSIF p_column = 'total_tokens' THEN
        SELECT COALESCE(SUM(total_tokens), 0) INTO result
        FROM token_usage
        WHERE organization_id = p_org_id AND created_at >= p_start_date;
    ELSIF p_column = 'input_tokens' THEN
        SELECT COALESCE(SUM(input_tokens), 0) INTO result
        FROM token_usage
        WHERE organization_id = p_org_id AND created_at >= p_start_date;
    ELSIF p_column = 'output_tokens' THEN
        SELECT COALESCE(SUM(output_tokens), 0) INTO result
        FROM token_usage
        WHERE organization_id = p_org_id AND created_at >= p_start_date;
    ELSE
        result := 0;
    END IF;
    RETURN result;
END;
$$ LANGUAGE plpgsql;
