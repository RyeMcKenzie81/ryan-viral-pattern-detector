-- Migration: Add C5 (Offer Accuracy) check to quality scoring config
-- Date: 2026-02-18
-- Purpose: Ensure ALL existing DB configs include C5 weight and auto-reject
--          to prevent hallucinated offers in generated ads.

-- Add C5 weight to ALL rows missing it (including custom org configs)
UPDATE quality_scoring_config
SET check_weights = check_weights || '{"C5": 1.5}'::jsonb
WHERE NOT (check_weights ? 'C5');

-- Add C5 to auto_reject_checks for ALL rows missing it
UPDATE quality_scoring_config
SET auto_reject_checks = auto_reject_checks || '["C5"]'::jsonb
WHERE NOT auto_reject_checks @> '["C5"]'::jsonb;
