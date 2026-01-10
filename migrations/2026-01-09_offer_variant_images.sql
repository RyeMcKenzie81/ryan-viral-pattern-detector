-- Migration: Add offer_variant_images junction table
-- Date: 2026-01-09
-- Purpose: Track which images were scraped from which offer variant's landing page

-- Junction table linking offer variants to their scraped images
CREATE TABLE IF NOT EXISTS offer_variant_images (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    offer_variant_id UUID NOT NULL REFERENCES product_offer_variants(id) ON DELETE CASCADE,
    product_image_id UUID NOT NULL REFERENCES product_images(id) ON DELETE CASCADE,
    is_primary BOOLEAN DEFAULT FALSE,
    display_order INTEGER DEFAULT 0,
    created_at TIMESTAMPTZ DEFAULT NOW(),
    UNIQUE(offer_variant_id, product_image_id)
);

-- Indexes for efficient lookups
CREATE INDEX IF NOT EXISTS idx_ovi_offer_variant ON offer_variant_images(offer_variant_id);
CREATE INDEX IF NOT EXISTS idx_ovi_product_image ON offer_variant_images(product_image_id);

-- Comments
COMMENT ON TABLE offer_variant_images IS 'Junction table tracking which product images were scraped from which offer variant landing page';
COMMENT ON COLUMN offer_variant_images.offer_variant_id IS 'Reference to the offer variant whose landing page was scraped';
COMMENT ON COLUMN offer_variant_images.product_image_id IS 'Reference to the scraped product image';
COMMENT ON COLUMN offer_variant_images.is_primary IS 'Whether this is the primary/hero image for the offer variant';
COMMENT ON COLUMN offer_variant_images.display_order IS 'Display order for sorting images within an offer variant';

-- Summary:
-- New table: offer_variant_images (junction between product_offer_variants and product_images)
