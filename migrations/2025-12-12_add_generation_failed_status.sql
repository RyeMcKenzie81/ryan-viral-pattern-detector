-- Add 'generation_failed' to project_asset_requirements status constraint
-- Date: 2025-12-12

-- Drop the existing constraint
ALTER TABLE project_asset_requirements
DROP CONSTRAINT IF EXISTS project_asset_requirements_status_check;

-- Add new constraint with generation_failed included
ALTER TABLE project_asset_requirements
ADD CONSTRAINT project_asset_requirements_status_check
CHECK (status IN ('needed', 'matched', 'generating', 'generated', 'approved', 'rejected', 'generation_failed'));
