-- Add brand_name and banned_terms columns to products table
-- Run this in Supabase SQL Editor

-- Add brand_name column
ALTER TABLE products ADD COLUMN IF NOT EXISTS brand_name TEXT;

-- Add banned_terms column (array of text for competitor names)
ALTER TABLE products ADD COLUMN IF NOT EXISTS banned_terms TEXT[];

-- Update Wonder Paws 3x Collagen with brand name and banned terms
UPDATE products
SET
    brand_name = 'Wonder Paws',
    banned_terms = ARRAY['Wuffes', 'PupVitality', 'PetHonesty', 'Zesty Paws']
WHERE name ILIKE '%Wonder Paws%' OR name ILIKE '%3x Collagen%';

-- Verify the update
SELECT id, name, brand_name, banned_terms FROM products WHERE brand_name IS NOT NULL;
