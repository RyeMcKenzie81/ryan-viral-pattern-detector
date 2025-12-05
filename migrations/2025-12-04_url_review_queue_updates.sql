-- Migration: URL Review Queue Updates
-- Date: 2025-12-04
-- Purpose: Add 'brand_level' status and 'notes' column for URL categorization

-- ============================================================
-- 1. Add 'notes' column to url_review_queue
-- ============================================================

ALTER TABLE url_review_queue ADD COLUMN IF NOT EXISTS notes TEXT;

COMMENT ON COLUMN url_review_queue.notes IS 'Notes about the URL categorization (e.g., ignore reason, brand-level designation)';

-- ============================================================
-- 2. Update status CHECK constraint to include 'brand_level'
-- ============================================================

-- Drop existing constraint and recreate with new value
ALTER TABLE url_review_queue DROP CONSTRAINT IF EXISTS url_review_queue_status_check;

ALTER TABLE url_review_queue ADD CONSTRAINT url_review_queue_status_check
    CHECK (status IN ('pending', 'assigned', 'new_product', 'ignored', 'brand_level'));

-- ============================================================
-- 3. Add index for status queries
-- ============================================================

CREATE INDEX IF NOT EXISTS idx_url_review_queue_brand_status
    ON url_review_queue(brand_id, status);
