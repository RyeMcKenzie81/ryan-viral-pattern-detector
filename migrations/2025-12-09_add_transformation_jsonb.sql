-- Migration: Add transformation JSONB column
-- Date: 2025-12-09
-- Purpose: Store full transformation analysis with quotes and author attribution

-- Add transformation column to store {insights: [], quotes: [{text, author, rating}]}
ALTER TABLE amazon_review_analysis
ADD COLUMN IF NOT EXISTS transformation JSONB;

COMMENT ON COLUMN amazon_review_analysis.transformation IS 'Transformation analysis: {insights: [], quotes: [{text, author, rating}]}';
