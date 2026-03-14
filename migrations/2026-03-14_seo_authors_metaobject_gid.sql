-- Migration: Add shopify_metaobject_gid to seo_authors
-- Date: 2026-03-14
-- Purpose: Store Shopify metaobject GID for author reference metafield

ALTER TABLE seo_authors ADD COLUMN IF NOT EXISTS shopify_metaobject_gid TEXT;
COMMENT ON COLUMN seo_authors.shopify_metaobject_gid IS 'Shopify metaobject GID for author reference (e.g. gid://shopify/Metaobject/123)';
