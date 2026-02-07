-- Migration: Dataset freshness tracking
-- Date: 2026-02-06
-- Purpose: Track when each dataset was last refreshed per brand,
--          enabling freshness banners and health dashboards.

CREATE TABLE IF NOT EXISTS dataset_status (
    id UUID DEFAULT gen_random_uuid() PRIMARY KEY,
    brand_id UUID NOT NULL REFERENCES brands(id) ON DELETE CASCADE,
    dataset_key TEXT NOT NULL,

    -- Freshness: separate success from attempt
    last_success_at TIMESTAMPTZ,
    last_attempt_at TIMESTAMPTZ,
    last_status TEXT NOT NULL DEFAULT 'unknown'
        CHECK (last_status IN ('completed', 'failed', 'running', 'unknown')),

    -- Context
    last_run_id UUID,
    records_affected INT DEFAULT 0,
    error_message TEXT,
    metadata JSONB DEFAULT '{}',

    -- Multi-tenant
    organization_id UUID REFERENCES organizations(id),

    created_at TIMESTAMPTZ DEFAULT NOW(),
    updated_at TIMESTAMPTZ DEFAULT NOW(),
    UNIQUE(brand_id, dataset_key)
);

COMMENT ON TABLE dataset_status IS 'Tracks freshness of each dataset per brand for health dashboards and readiness banners';
COMMENT ON COLUMN dataset_status.last_success_at IS 'Only updated on successful refresh — freshness checks always use this';
COMMENT ON COLUMN dataset_status.last_attempt_at IS 'Updated on every attempt (start or finish) — tracks whether job is running';
COMMENT ON COLUMN dataset_status.last_run_id IS 'Plain UUID reference to scheduled_job_runs (no FK to avoid order-of-operations issues)';

-- Auto-update updated_at on every change
CREATE OR REPLACE FUNCTION update_dataset_status_updated_at()
RETURNS TRIGGER AS $$
BEGIN
    NEW.updated_at = NOW();
    RETURN NEW;
END;
$$ LANGUAGE plpgsql;

DROP TRIGGER IF EXISTS trigger_dataset_status_updated_at ON dataset_status;
CREATE TRIGGER trigger_dataset_status_updated_at
    BEFORE UPDATE ON dataset_status
    FOR EACH ROW
    EXECUTE FUNCTION update_dataset_status_updated_at();

CREATE INDEX IF NOT EXISTS idx_dataset_status_brand ON dataset_status(brand_id);
CREATE INDEX IF NOT EXISTS idx_dataset_status_org ON dataset_status(organization_id);
