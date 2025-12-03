-- Migration: Add template analysis caching
-- Date: 2025-12-03
-- Purpose: Cache expensive Opus 4.5 vision analysis results per template
--          to avoid re-running 4-8 minute analysis on template reuse

-- Create ad_templates table for caching template analysis
CREATE TABLE IF NOT EXISTS ad_templates (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),

    -- Template identification
    storage_path TEXT UNIQUE NOT NULL,  -- e.g., "reference-ads/uuid_filename.png"
    original_filename TEXT,              -- Display name

    -- Cached analysis (Stage 5: analyze_reference_ad)
    ad_analysis JSONB,
    -- Contains: format_type, layout_structure, fixed_elements, variable_elements,
    --           text_placement, color_palette, authenticity_markers, canvas_size, etc.

    -- Cached template angle (Stage 6a: extract_template_angle)
    template_angle JSONB,
    -- Contains: angle_type, original_text, messaging_template, tone, key_elements

    -- Metadata
    analysis_model TEXT,                 -- Model used for analysis (e.g., "claude-opus-4-5-20251101")
    analysis_created_at TIMESTAMPTZ,     -- When analysis was performed
    created_at TIMESTAMPTZ DEFAULT NOW(),
    updated_at TIMESTAMPTZ DEFAULT NOW()
);

-- Index for fast lookups by storage path
CREATE INDEX IF NOT EXISTS idx_ad_templates_storage_path ON ad_templates(storage_path);

-- Add comment explaining the table
COMMENT ON TABLE ad_templates IS 'Caches expensive vision AI analysis results for reference ad templates. Saves 4-8 minutes on subsequent uses of same template.';
COMMENT ON COLUMN ad_templates.ad_analysis IS 'Stage 5 analysis: format, layout, colors, elements (from analyze_reference_ad)';
COMMENT ON COLUMN ad_templates.template_angle IS 'Stage 6a extraction: angle type, messaging template (from extract_template_angle)';
