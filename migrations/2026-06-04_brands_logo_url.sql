-- Migration: add brands.logo_url
-- Date: 2026-06-04
-- Purpose: Brand logo image URL, rendered in the weekly digest HTML report
--          header (a blue band, so prefer a logo that reads on a dark/color
--          background, e.g. a white-letter variant).

ALTER TABLE brands ADD COLUMN IF NOT EXISTS logo_url TEXT;

COMMENT ON COLUMN brands.logo_url IS
  'Brand logo image URL, shown in the weekly digest HTML report header (blue band — prefer a light/white-letter logo variant).';

-- Seed Martin Clinic's logo (white-letter variant, reads on the blue header band).
UPDATE brands
SET logo_url = 'https://martinclinic.com/cdn/shop/files/MartinClinic-TweakedLogo-WhiteLetters.png?v=1613664001&width=600'
WHERE id = 'd0cfa5c5-1132-447b-ade3-4db87995315b';
