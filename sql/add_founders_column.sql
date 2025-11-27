-- Add founders column to products table
-- Run this in Supabase SQL Editor

-- Add the column
ALTER TABLE products ADD COLUMN IF NOT EXISTS founders TEXT;

-- Update Yakety Pack with founders
UPDATE products
SET founders = 'Chris, Kevin, D''Arcy, and Ryan'
WHERE id = '40c461f0-e3c8-4029-bd51-31ded412353c';

-- Verify the update
SELECT id, name, founders FROM products WHERE founders IS NOT NULL;
