-- Remove legacy image columns from products table
-- These have been migrated to the product_images table
-- Run this AFTER verifying product_images table has all the data

-- Remove the columns
ALTER TABLE products DROP COLUMN IF EXISTS main_image_storage_path;
ALTER TABLE products DROP COLUMN IF EXISTS reference_image_storage_paths;

-- Verify columns are removed
SELECT column_name, data_type
FROM information_schema.columns
WHERE table_name = 'products'
ORDER BY ordinal_position;
