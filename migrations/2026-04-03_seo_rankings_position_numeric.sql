-- Migration: Change seo_article_rankings.position from INT to NUMERIC
-- Date: 2026-04-03
-- Purpose: Support GSC's fractional average positions (e.g., 12.3)

ALTER TABLE seo_article_rankings ALTER COLUMN position TYPE NUMERIC;
