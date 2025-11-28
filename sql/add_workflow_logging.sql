-- Add workflow logging to track image generation details
-- Run this in Supabase SQL Editor

-- 1. Add columns to generated_ads for model tracking
ALTER TABLE generated_ads ADD COLUMN IF NOT EXISTS model_requested TEXT;
ALTER TABLE generated_ads ADD COLUMN IF NOT EXISTS model_used TEXT;
ALTER TABLE generated_ads ADD COLUMN IF NOT EXISTS generation_time_ms INT;
ALTER TABLE generated_ads ADD COLUMN IF NOT EXISTS generation_retries INT DEFAULT 0;

-- 2. Create workflow_logs table for detailed step-by-step logging
CREATE TABLE IF NOT EXISTS workflow_logs (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    ad_run_id UUID REFERENCES ad_runs(id) ON DELETE CASCADE NOT NULL,
    generated_ad_id UUID REFERENCES generated_ads(id) ON DELETE CASCADE,

    -- Step info
    step_name TEXT NOT NULL,  -- e.g., 'analyze_reference', 'generate_copy', 'generate_image', 'claude_review', 'gemini_review'
    step_index INT,  -- For ordered steps (e.g., variation 1, 2, 3...)

    -- Timing
    started_at TIMESTAMPTZ DEFAULT NOW(),
    completed_at TIMESTAMPTZ,
    duration_ms INT,

    -- Model info
    model_requested TEXT,
    model_used TEXT,

    -- Status
    status TEXT DEFAULT 'started' CHECK (status IN ('started', 'success', 'failed', 'retried', 'fallback')),
    retry_count INT DEFAULT 0,

    -- Details (flexible JSONB for step-specific data)
    input_summary JSONB,  -- Summary of inputs (not full prompt, just key info)
    output_summary JSONB,  -- Summary of outputs
    error_message TEXT,
    error_details JSONB,

    -- Metadata
    created_at TIMESTAMPTZ DEFAULT NOW()
);

-- Indexes for efficient querying
CREATE INDEX idx_workflow_logs_run ON workflow_logs(ad_run_id);
CREATE INDEX idx_workflow_logs_ad ON workflow_logs(generated_ad_id);
CREATE INDEX idx_workflow_logs_step ON workflow_logs(step_name);
CREATE INDEX idx_workflow_logs_status ON workflow_logs(status);
CREATE INDEX idx_workflow_logs_created ON workflow_logs(created_at DESC);

-- Comments
COMMENT ON TABLE workflow_logs IS 'Detailed step-by-step logs for ad creation workflow debugging';
COMMENT ON COLUMN workflow_logs.model_requested IS 'Model we requested (e.g., gemini-3-pro-image-preview)';
COMMENT ON COLUMN workflow_logs.model_used IS 'Model that actually processed the request (may differ due to fallback)';
COMMENT ON COLUMN workflow_logs.status IS 'Step outcome: started, success, failed, retried, fallback';

-- 3. Add summary columns to ad_runs for quick overview
ALTER TABLE ad_runs ADD COLUMN IF NOT EXISTS workflow_summary JSONB;

COMMENT ON COLUMN ad_runs.workflow_summary IS 'Summary of workflow execution including models used, timing, and any issues';

-- Verify
SELECT column_name, data_type
FROM information_schema.columns
WHERE table_name = 'generated_ads'
AND column_name IN ('model_requested', 'model_used', 'generation_time_ms', 'generation_retries');
