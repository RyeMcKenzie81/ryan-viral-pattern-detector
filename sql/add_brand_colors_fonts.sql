-- Add brand colors and fonts columns to brands table
-- Phase 2 of color mode feature

-- Add brand_colors column (JSONB for flexible color storage)
ALTER TABLE brands
ADD COLUMN IF NOT EXISTS brand_colors JSONB DEFAULT NULL;

-- Add brand_fonts column (JSONB for font information)
ALTER TABLE brands
ADD COLUMN IF NOT EXISTS brand_fonts JSONB DEFAULT NULL;

-- Add brand_guidelines column for additional brand voice/style notes
ALTER TABLE brands
ADD COLUMN IF NOT EXISTS brand_guidelines TEXT DEFAULT NULL;

-- Comment on columns
COMMENT ON COLUMN brands.brand_colors IS 'Brand color palette as JSON: {"primary": "#4747C9", "secondary": "#FDBE2D", "background": "#F5F5F5", "all": ["#4747C9", "#FDBE2D", "#F5F5F5"]}';
COMMENT ON COLUMN brands.brand_fonts IS 'Brand fonts as JSON: {"primary": "Larsseit", "secondary": "Uomo Bold", "weights": ["Bold", "Medium", "Regular"]}';
COMMENT ON COLUMN brands.brand_guidelines IS 'Additional brand guidelines and style notes';

-- ============================================
-- Insert Wonder Paws brand colors and fonts
-- ============================================

-- First, find the Wonder Paws brand ID and update it
UPDATE brands
SET
    brand_colors = '{
        "primary": "#4747C9",
        "primary_name": "Purple",
        "secondary": "#FDBE2D",
        "secondary_name": "Marigold",
        "background": "#F5F5F5",
        "background_name": "Dove Grey",
        "all": ["#4747C9", "#FDBE2D", "#F5F5F5"],
        "usage_notes": "Use teal shades for depth. Gradated backgrounds for dimension. Neutrals (grey, cream) for warmth."
    }'::jsonb,
    brand_fonts = '{
        "primary": "Larsseit",
        "primary_weights": ["Bold", "Medium", "Regular"],
        "primary_usage": "Body copy to legal information",
        "secondary": "Uomo Bold",
        "secondary_usage": "Headlines and personality elements",
        "style_notes": "Friendly, modern sans-serif paired with fun personality font for visual hierarchy"
    }'::jsonb,
    brand_guidelines = 'A consistent palette maintains the distinct Wonder Paws look and feel. When color is used in photography (ex. as a background), use tonal, gradated shades to create depth and dimension (not flat). Neutrals (grey, cream) provide background hues that bring warmth to the brand.'
WHERE name ILIKE '%wonder paws%' OR name ILIKE '%wonderpaws%';

-- Verify the update
SELECT id, name, brand_colors, brand_fonts, brand_guidelines
FROM brands
WHERE name ILIKE '%wonder paws%' OR name ILIKE '%wonderpaws%';
