-- Migration: Add metadata JSONB column to seo_articles
-- Date: 2026-04-03
-- Purpose: Store metadata flags like time_sensitive for opportunity classification

ALTER TABLE seo_articles ADD COLUMN IF NOT EXISTS metadata JSONB DEFAULT '{}';

COMMENT ON COLUMN seo_articles.metadata IS 'Metadata flags (e.g., time_sensitive) used by OpportunityMinerService classification';
