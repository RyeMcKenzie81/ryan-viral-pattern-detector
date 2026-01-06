-- Migration: Create system_settings table
-- Date: 2026-01-06
-- Purpose: Store configurable system settings for Angle Pipeline and other features

CREATE TABLE IF NOT EXISTS system_settings (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    key TEXT UNIQUE NOT NULL,
    value JSONB NOT NULL,
    description TEXT,
    created_at TIMESTAMPTZ DEFAULT NOW(),
    updated_at TIMESTAMPTZ DEFAULT NOW()
);

-- Create index on key for fast lookups
CREATE INDEX IF NOT EXISTS idx_system_settings_key ON system_settings(key);

-- Add RLS policy (allow all authenticated users to read/write for now)
ALTER TABLE system_settings ENABLE ROW LEVEL SECURITY;

CREATE POLICY "Allow authenticated users to read system_settings"
    ON system_settings FOR SELECT
    TO authenticated
    USING (true);

CREATE POLICY "Allow authenticated users to insert system_settings"
    ON system_settings FOR INSERT
    TO authenticated
    WITH CHECK (true);

CREATE POLICY "Allow authenticated users to update system_settings"
    ON system_settings FOR UPDATE
    TO authenticated
    USING (true);

-- Insert default Angle Pipeline settings
INSERT INTO system_settings (key, value, description) VALUES
    ('angle_pipeline.stale_threshold_days', '30', 'Days without evidence before candidate is considered stale'),
    ('angle_pipeline.evidence_decay_halflife_days', '60', 'Half-life for evidence frequency decay scoring'),
    ('angle_pipeline.min_candidates_pattern_discovery', '10', 'Minimum candidates required to run pattern discovery'),
    ('angle_pipeline.max_ads_per_scheduled_run', '50', 'Maximum ads generated per scheduled job run'),
    ('angle_pipeline.cluster_eps', '0.3', 'DBSCAN epsilon - clustering sensitivity (lower = tighter clusters)'),
    ('angle_pipeline.cluster_min_samples', '2', 'Minimum candidates per cluster')
ON CONFLICT (key) DO NOTHING;

COMMENT ON TABLE system_settings IS 'Configurable system settings for various features';
COMMENT ON COLUMN system_settings.key IS 'Unique setting key (e.g., angle_pipeline.stale_threshold_days)';
COMMENT ON COLUMN system_settings.value IS 'Setting value stored as JSONB';
