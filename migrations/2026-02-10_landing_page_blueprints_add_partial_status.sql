-- Migration: Add 'partial' to landing_page_blueprints status check constraint
-- Date: 2026-02-10
-- Purpose: The code sets status='partial' when chunk 2 fails but chunk 1 succeeds.
--          The original CHECK constraint didn't include it.

ALTER TABLE landing_page_blueprints DROP CONSTRAINT IF EXISTS landing_page_blueprints_status_check;
ALTER TABLE landing_page_blueprints ADD CONSTRAINT landing_page_blueprints_status_check
    CHECK (status IN ('pending', 'processing', 'completed', 'partial', 'failed'));
