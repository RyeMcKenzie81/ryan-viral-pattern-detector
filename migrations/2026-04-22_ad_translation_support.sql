-- Migration: Ad Translation Support
-- Date: 2026-04-22
-- Purpose: Add language tracking, translation lineage, and fast ID prefix lookup
--          to generated_ads table for multi-language ad translation feature.
-- VERIFIED: No naming collisions with existing tables/columns.

-- Language column: IETF language tag (en, es-MX, pt-BR, etc.)
-- Default 'en' covers all existing rows automatically.
ALTER TABLE generated_ads
ADD COLUMN IF NOT EXISTS language TEXT DEFAULT 'en';

COMMENT ON COLUMN generated_ads.language IS 'IETF language tag (en, es-MX, pt-BR). Default en for English.';

-- Translation lineage: FK to the original ad this was translated from
ALTER TABLE generated_ads
ADD COLUMN IF NOT EXISTS translation_parent_id UUID REFERENCES generated_ads(id);

COMMENT ON COLUMN generated_ads.translation_parent_id IS 'FK to original ad this was translated from. NULL for originals.';

-- Fast fragment lookup: first 8 chars of UUID as indexed text column.
-- Enables fast lookups by ad ID fragment (e.g., "65bb40" from SAV-FTS-65bb40-04161b-SQ).
ALTER TABLE generated_ads
ADD COLUMN IF NOT EXISTS id_prefix TEXT GENERATED ALWAYS AS (LEFT(id::text, 8)) STORED;

COMMENT ON COLUMN generated_ads.id_prefix IS 'First 8 chars of UUID for fast fragment lookup (generated column).';

-- Indexes
CREATE INDEX IF NOT EXISTS idx_generated_ads_language
ON generated_ads(language);

CREATE INDEX IF NOT EXISTS idx_generated_ads_translation_parent
ON generated_ads(translation_parent_id);

CREATE INDEX IF NOT EXISTS idx_generated_ads_id_prefix
ON generated_ads(id_prefix);

-- Idempotency: prevent duplicate translations of same ad into same language.
-- Partial unique index only applies when translation_parent_id is set.
CREATE UNIQUE INDEX IF NOT EXISTS idx_generated_ads_translation_unique
ON generated_ads(translation_parent_id, language)
WHERE translation_parent_id IS NOT NULL;
