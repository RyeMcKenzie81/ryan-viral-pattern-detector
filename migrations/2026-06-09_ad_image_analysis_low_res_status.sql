-- Migration: allow ad_image_analysis.status = 'low_res'
-- Date: 2026-06-09
-- Purpose: The static-awareness completeness gate persists a low_res "settling"
--   marker row in ad_image_analysis (status='low_res', awareness_level NULL) for
--   images too small to classify (64x64 thumbnails). The classifier prefetch reads
--   these markers to stop re-downloading them every run, and the weekly digest reads
--   them to show that spend on a separate "cannot classify" line (excluded from the
--   completeness gate denominator). NO ad_creative_classifications row is written for a
--   skip — only this marker — so latest-classification consumers are never poisoned.
-- Non-breaking: every existing ad_image_analysis row has status='ok'.

ALTER TABLE ad_image_analysis
    DROP CONSTRAINT IF EXISTS ad_image_analysis_status_check;

ALTER TABLE ad_image_analysis
    ADD CONSTRAINT ad_image_analysis_status_check
    CHECK (status IN ('ok', 'error', 'low_res'));

COMMENT ON COLUMN ad_image_analysis.status IS
    'ok = analyzed; error = analysis failed; low_res = image too small to classify '
    '(settling marker, awareness_level NULL; the digest counts this as "cannot classify, '
    'needs high-res re-fetch", excluded from the completeness gate denominator).';
