-- Migration: Add Product Variants Support
-- Date: 2025-12-09
-- Purpose: Allow products to have multiple variants (e.g., flavors, sizes, colors)

-- ============================================================================
-- Product Variants Table
-- ============================================================================

CREATE TABLE IF NOT EXISTS product_variants (
    id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    product_id uuid NOT NULL REFERENCES products(id) ON DELETE CASCADE,

    -- Variant identification
    name text NOT NULL,                    -- e.g., "Strawberry", "Chocolate", "Vanilla"
    slug text NOT NULL,                    -- e.g., "strawberry", "chocolate", "vanilla"
    sku text,                              -- Optional SKU/product code

    -- Variant type (for grouping/filtering)
    variant_type text DEFAULT 'flavor',    -- 'flavor', 'size', 'color', 'bundle', 'other'

    -- Variant-specific details
    description text,                      -- Variant-specific description
    differentiators jsonb,                 -- What makes this variant unique
                                           -- e.g., {"taste_profile": "fruity", "best_for": "morning use"}

    -- Pricing (optional - if variants have different prices)
    price decimal(10,2),
    compare_at_price decimal(10,2),

    -- Status
    is_active boolean DEFAULT true,
    is_default boolean DEFAULT false,      -- Primary/hero variant for the product
    display_order int DEFAULT 0,           -- Sort order in UI

    -- Timestamps
    created_at timestamptz DEFAULT now(),
    updated_at timestamptz DEFAULT now(),

    -- Constraints
    UNIQUE(product_id, slug)
);

-- Indexes
CREATE INDEX idx_product_variants_product_id ON product_variants(product_id);
CREATE INDEX idx_product_variants_variant_type ON product_variants(variant_type);
CREATE INDEX idx_product_variants_is_active ON product_variants(is_active);
CREATE INDEX idx_product_variants_display_order ON product_variants(display_order);

-- Comments
COMMENT ON TABLE product_variants IS 'Product variants (flavors, sizes, colors, etc.)';
COMMENT ON COLUMN product_variants.variant_type IS 'Type of variant: flavor, size, color, bundle, other';
COMMENT ON COLUMN product_variants.differentiators IS 'JSON object with variant-specific attributes';
COMMENT ON COLUMN product_variants.is_default IS 'True for the primary/hero variant shown by default';

-- ============================================================================
-- Variant Images Junction Table
-- ============================================================================
-- Links variants to specific product images (optional - for variant-specific imagery)

CREATE TABLE IF NOT EXISTS variant_images (
    id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    variant_id uuid NOT NULL REFERENCES product_variants(id) ON DELETE CASCADE,
    product_image_id uuid NOT NULL REFERENCES product_images(id) ON DELETE CASCADE,
    is_primary boolean DEFAULT false,      -- Primary image for this variant
    display_order int DEFAULT 0,
    created_at timestamptz DEFAULT now(),

    UNIQUE(variant_id, product_image_id)
);

CREATE INDEX idx_variant_images_variant_id ON variant_images(variant_id);
CREATE INDEX idx_variant_images_product_image_id ON variant_images(product_image_id);

COMMENT ON TABLE variant_images IS 'Links product variants to specific product images';

-- ============================================================================
-- Update ad_runs to optionally track variant
-- ============================================================================

DO $$
BEGIN
    IF NOT EXISTS (
        SELECT 1 FROM information_schema.columns
        WHERE table_name = 'ad_runs' AND column_name = 'variant_id'
    ) THEN
        ALTER TABLE ad_runs ADD COLUMN variant_id uuid REFERENCES product_variants(id) ON DELETE SET NULL;
        CREATE INDEX idx_ad_runs_variant_id ON ad_runs(variant_id);
        COMMENT ON COLUMN ad_runs.variant_id IS 'Optional variant this ad run was created for';
    END IF;
END $$;

-- ============================================================================
-- Helper View: Products with Variants
-- ============================================================================

CREATE OR REPLACE VIEW products_with_variants AS
SELECT
    p.id as product_id,
    p.name as product_name,
    p.brand_id,
    b.name as brand_name,
    COALESCE(
        jsonb_agg(
            jsonb_build_object(
                'id', v.id,
                'name', v.name,
                'slug', v.slug,
                'variant_type', v.variant_type,
                'is_default', v.is_default,
                'is_active', v.is_active
            ) ORDER BY v.display_order, v.name
        ) FILTER (WHERE v.id IS NOT NULL),
        '[]'::jsonb
    ) as variants,
    COUNT(v.id) as variant_count
FROM products p
JOIN brands b ON b.id = p.brand_id
LEFT JOIN product_variants v ON v.product_id = p.id AND v.is_active = true
GROUP BY p.id, p.name, p.brand_id, b.name;

COMMENT ON VIEW products_with_variants IS 'Products with their active variants as JSON array';
