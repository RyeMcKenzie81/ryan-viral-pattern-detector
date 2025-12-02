-- Add social_proof column to products table
ALTER TABLE products
ADD COLUMN IF NOT EXISTS social_proof TEXT;

-- Update Wonder Paws Collagen 3X with social proof
UPDATE products
SET social_proof = '100,000+ Bottles Sold'
WHERE id = '83166c93-632f-47ef-a929-922230e05f82';

-- Verify the update
SELECT
  id,
  name,
  social_proof
FROM products
WHERE id = '83166c93-632f-47ef-a929-922230e05f82';
