-- Add product_dimensions column if it doesn't exist
ALTER TABLE products
ADD COLUMN IF NOT EXISTS product_dimensions TEXT;

-- Update Wonder Paws Collagen with physical dimensions
-- Dimensions: 6.22 x 4.53 x 2.2 inches; 8.78 ounces
UPDATE products
SET product_dimensions = '8.78 oz bottle (approximately 6.2 inches tall x 4.5 inches wide x 2.2 inches deep), similar in size to a small water bottle or shampoo bottle, fits comfortably in one hand'
WHERE id = '83166c93-632f-47ef-a929-922230e05f82';

-- Verify the update
SELECT
  id,
  name,
  product_dimensions
FROM products
WHERE id = '83166c93-632f-47ef-a929-922230e05f82';
