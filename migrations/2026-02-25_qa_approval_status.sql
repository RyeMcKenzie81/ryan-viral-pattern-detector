-- Migration: QA approval status for analyses and blueprints
-- Date: 2026-02-25
-- Purpose: Add qa_status, qa_notes, qa_reviewed_by, qa_reviewed_at to both
--          landing_page_analyses and landing_page_blueprints tables.
--          QA is non-blocking: pending status does NOT prevent template usage.

-- Analyses: "Is this template structurally sound?"
ALTER TABLE landing_page_analyses
  ADD COLUMN IF NOT EXISTS qa_status TEXT DEFAULT 'pending'
    CHECK (qa_status IN ('pending', 'approved', 'rejected', 'needs_revision'));
ALTER TABLE landing_page_analyses
  ADD COLUMN IF NOT EXISTS qa_notes TEXT;
ALTER TABLE landing_page_analyses
  ADD COLUMN IF NOT EXISTS qa_reviewed_by UUID;
ALTER TABLE landing_page_analyses
  ADD COLUMN IF NOT EXISTS qa_reviewed_at TIMESTAMPTZ;

CREATE INDEX IF NOT EXISTS idx_lpa_qa_approved
  ON landing_page_analyses(organization_id, qa_status)
  WHERE qa_status = 'approved';

-- Blueprints: "Is this brand output correct?"
ALTER TABLE landing_page_blueprints
  ADD COLUMN IF NOT EXISTS qa_status TEXT DEFAULT 'pending'
    CHECK (qa_status IN ('pending', 'approved', 'rejected', 'needs_revision'));
ALTER TABLE landing_page_blueprints
  ADD COLUMN IF NOT EXISTS qa_notes TEXT;
ALTER TABLE landing_page_blueprints
  ADD COLUMN IF NOT EXISTS qa_reviewed_by UUID;
ALTER TABLE landing_page_blueprints
  ADD COLUMN IF NOT EXISTS qa_reviewed_at TIMESTAMPTZ;

CREATE INDEX IF NOT EXISTS idx_lpb_qa_approved
  ON landing_page_blueprints(organization_id, qa_status)
  WHERE qa_status = 'approved';
