-- Migration: Add verified social proof columns to products
-- Date: 2025-12-03
-- Purpose: Store structured, verified social proof data to prevent AI from
--          inventing fake Trustpilot reviews, media mentions, etc.

-- Add review platforms (e.g., {"trustpilot": {"rating": 4.5, "count": 1200}})
ALTER TABLE products ADD COLUMN IF NOT EXISTS review_platforms JSONB;

-- Add media features (e.g., ["Forbes", "Good Morning America", "Today Show"])
ALTER TABLE products ADD COLUMN IF NOT EXISTS media_features JSONB;

-- Add awards and certifications (e.g., ["#1 Best Seller", "Vet Recommended"])
ALTER TABLE products ADD COLUMN IF NOT EXISTS awards_certifications JSONB;

-- Add comments
COMMENT ON COLUMN products.review_platforms IS 'Verified review platform ratings. Format: {"platform": {"rating": X.X, "count": N}}';
COMMENT ON COLUMN products.media_features IS 'Verified media outlets that have featured the brand. Array of strings.';
COMMENT ON COLUMN products.awards_certifications IS 'Verified awards and certifications. Array of strings.';
