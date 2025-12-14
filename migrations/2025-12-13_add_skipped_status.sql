-- Add 'skipped' to project_asset_requirements status constraint
-- Date: 2025-12-13
-- Purpose: Allow marking assets as "editor will handle" to skip AI generation

-- Drop the existing constraint
ALTER TABLE project_asset_requirements
DROP CONSTRAINT IF EXISTS project_asset_requirements_status_check;

-- Add new constraint with skipped included
ALTER TABLE project_asset_requirements
ADD CONSTRAINT project_asset_requirements_status_check
CHECK (status IN ('needed', 'matched', 'generating', 'generated', 'approved', 'rejected', 'generation_failed', 'skipped'));
