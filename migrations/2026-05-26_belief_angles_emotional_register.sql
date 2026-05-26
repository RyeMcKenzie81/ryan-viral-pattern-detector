-- Migration: Add emotional_register column to belief_angles
-- Date: 2026-05-26
-- Plan: docs/plans/angle-driven-ad-creator/PLAN.md (follow-up fix)
--
-- The ProposedAngle Pydantic model has an emotional_register field (one-word
-- emotional tone: relief/permission/defiance/urgency/etc.) that Opus produces
-- per angle. The 2026-05-25_angle_driven_ads.sql migration missed this column
-- when extending belief_angles. As a result:
--   - save_angles() never wrote it (silent drop on insert path)
--   - The "show existing angles" UI in PR #198 SELECT'd it and threw
--     'column belief_angles.emotional_register does not exist' (code 42703)
--
-- Fix: add the column. PR #199 also updates save_angles() to include
-- emotional_register in the insert payload so newly-generated angles persist
-- it going forward. Existing rows stay NULL — the angle's emotional vibe
-- still lives in belief_statement + explanation for those.

BEGIN;

ALTER TABLE belief_angles
    ADD COLUMN IF NOT EXISTS emotional_register TEXT;

COMMENT ON COLUMN belief_angles.emotional_register IS
    'One-word emotional tone tag from the angle generator (e.g. relief, '
    'permission, defiance, urgency, pride, safety, belonging, reclamation). '
    'Set on AI-generated angles; NULL on legacy/manual angles created before '
    '2026-05-26 or via paths that do not populate this field.';

COMMIT;
