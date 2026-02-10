-- Migration: Add persona_id to landing_page_blueprints
-- Date: 2026-02-09
-- Purpose: Track which persona was targeted when generating a blueprint (nullable = auto mode)

ALTER TABLE landing_page_blueprints ADD COLUMN IF NOT EXISTS persona_id UUID;

COMMENT ON COLUMN landing_page_blueprints.persona_id IS 'FK to personas_4d — which persona was targeted (null = auto / LLM-chosen)';
