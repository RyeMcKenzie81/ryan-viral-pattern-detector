-- Migration: Video awareness — opening / ending split
-- Date: 2026-06-05
-- Purpose: ad_video_analysis now records the awareness stage the video MEETS the
--   viewer at (opening, ~first 10 seconds = entry temperature) and the stage it
--   leaves them at (ending), instead of a single whole-video awareness_level.
--   Video ads progress the viewer down the funnel, so the whole-video label filed
--   cold/top-funnel videos as most-aware and broke the digest's awareness waterfall.
--   The digest buckets by the OPENING (mapped to creative_awareness_level). The
--   legacy awareness_level column is kept (= opening) for back-compat; ending is
--   captured for future journey/progression analysis (not yet used in the digest).
--   Paired with VideoAnalysisService.PROMPT_VERSION bump v2 -> v3.

ALTER TABLE ad_video_analysis
    ADD COLUMN IF NOT EXISTS awareness_level_opening TEXT,
    ADD COLUMN IF NOT EXISTS awareness_level_opening_confidence NUMERIC,
    ADD COLUMN IF NOT EXISTS awareness_level_ending TEXT,
    ADD COLUMN IF NOT EXISTS awareness_level_ending_confidence NUMERIC;

COMMENT ON COLUMN ad_video_analysis.awareness_level_opening IS
    'Awareness stage the video positions the viewer at in roughly the first 10s '
    '(entry temperature, past any pure attention-grab). Drives digest bucketing '
    'via creative_awareness_level. Legacy awareness_level is kept = this value.';
COMMENT ON COLUMN ad_video_analysis.awareness_level_ending IS
    'Awareness stage the video leaves the viewer at by its close. Captured for '
    'future journey/progression analysis; not yet used in the digest.';
