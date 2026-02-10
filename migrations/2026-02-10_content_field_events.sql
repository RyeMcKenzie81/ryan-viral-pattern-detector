-- Migration: Content Field Events — Provenance tracking for Content Gap Filler
-- Date: 2026-02-10
-- Purpose: Append-only audit trail for every gap fill action (manual entry, source use, AI suggestion, skip)

CREATE TABLE IF NOT EXISTS content_field_events (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    organization_id UUID NOT NULL REFERENCES organizations(id),

    -- What was changed
    target_table TEXT NOT NULL,       -- "products", "brands", "product_offer_variants"
    target_id UUID NOT NULL,          -- row ID in target table
    target_column TEXT NOT NULL,      -- "guarantee", "pain_points", etc.
    gap_key TEXT NOT NULL,            -- "product.guarantee", "offer_variant.pain_points", etc.

    -- Who / when
    user_id UUID,
    blueprint_id UUID REFERENCES landing_page_blueprints(id),  -- which blueprint triggered this (nullable)
    request_id UUID NOT NULL,         -- groups all events from a single "Fix All" or manual save action

    -- What happened
    action TEXT NOT NULL CHECK (action IN ('set', 'overwrite', 'append', 'skip_not_applicable', 'undo_skip')),
    old_value JSONB,                  -- previous value (for overwrite audit)
    new_value JSONB,                  -- value that was saved (null for skip_not_applicable)
    source_type TEXT NOT NULL,        -- "manual", "cached_source", "ai_suggestion", "fresh_scrape", "system"
    source_detail JSONB DEFAULT '{}', -- {source: "brand_landing_pages", snippet: "...", url: "...", confidence: "high"}
    source_hash TEXT,                 -- SHA-256 of canonical evidence JSON blob (for staleness detection)

    created_at TIMESTAMPTZ DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_content_field_events_target
    ON content_field_events(target_table, target_id, target_column);
CREATE INDEX IF NOT EXISTS idx_content_field_events_org
    ON content_field_events(organization_id);
CREATE INDEX IF NOT EXISTS idx_content_field_events_blueprint
    ON content_field_events(blueprint_id);
CREATE INDEX IF NOT EXISTS idx_content_field_events_request
    ON content_field_events(request_id);

-- Prevent exact duplicate events from double-clicks/retries
CREATE UNIQUE INDEX IF NOT EXISTS idx_content_field_events_dedup
    ON content_field_events(request_id, target_table, target_id, target_column, gap_key, action);

-- Fast lookup for is_gap_dismissed() — "most recent event for (blueprint_id, target_id, gap_key)"
CREATE INDEX IF NOT EXISTS idx_content_field_events_dismiss_lookup
    ON content_field_events(blueprint_id, target_id, gap_key, created_at DESC);
