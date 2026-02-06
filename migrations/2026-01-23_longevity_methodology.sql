-- Migration: Add longevity methodology to template recommendations
-- Date: 2026-01-23
-- Purpose: Add 'longevity' option to recommendation methodology (longest running ads)

-- Update CHECK constraint to include 'longevity' methodology
ALTER TABLE product_template_recommendations
DROP CONSTRAINT IF EXISTS product_template_recommendations_methodology_check;

ALTER TABLE product_template_recommendations
ADD CONSTRAINT product_template_recommendations_methodology_check
CHECK (methodology IN ('ai_match', 'performance', 'diversity', 'longevity'));

-- Update comment to reflect new methodology
COMMENT ON COLUMN product_template_recommendations.methodology IS
'How this recommendation was generated: ai_match (AI analysis), performance (based on ad metrics), diversity (format variety), longevity (longest running ads)';
