-- Setup Italian Brainrot Test Project for YouTube Shorts
-- Channel: https://www.youtube.com/@animemes-collection
-- Date: 2025-10-15

-- Step 1: Create brand (if needed)
INSERT INTO brands (name, slug, description)
VALUES (
  'Test Brand',
  'test-brand',
  'Test brand for YouTube Shorts testing'
)
ON CONFLICT (slug) DO NOTHING
RETURNING id;

-- Note: Copy the brand ID from above, or get it with:
-- SELECT id FROM brands WHERE slug = 'test-brand';

-- Step 2: Create product (if needed)
-- Replace <brand-id> with the ID from step 1
INSERT INTO products (brand_id, name, slug, description)
VALUES (
  (SELECT id FROM brands WHERE slug = 'test-brand'),
  'Test Product',
  'test-product',
  'Test product for YouTube Shorts testing'
)
ON CONFLICT (brand_id, slug) DO NOTHING
RETURNING id;

-- Step 3: Create project
-- Replace <brand-id> and <product-id> with IDs from above
INSERT INTO projects (brand_id, product_id, name, slug, description, is_active)
VALUES (
  (SELECT id FROM brands WHERE slug = 'test-brand'),
  (SELECT id FROM products WHERE slug = 'test-product'),
  'Italian Brainrot',
  'italian-brainrot',
  'Test project for YouTube Shorts scraping - @animemes-collection',
  true
)
RETURNING id;

-- Note: Copy the project ID, or get it with:
-- SELECT id FROM projects WHERE slug = 'italian-brainrot';

-- Step 4: Add YouTube channel
-- Channel: animemes-collection (without @)
INSERT INTO accounts (
  handle,
  platform_id,
  platform_username,
  display_name,
  last_scraped_at
)
VALUES (
  'animemes-collection',
  '636fb6da-068b-4129-9efc-c90dd4a03db6',  -- YouTube Shorts platform ID
  'animemes-collection',
  'Animemes Collection',
  NULL
)
ON CONFLICT (platform_id, platform_username) DO UPDATE
SET handle = EXCLUDED.handle
RETURNING id;

-- Note: Copy the account ID, or get it with:
-- SELECT id FROM accounts WHERE platform_username = 'animemes-collection';

-- Step 5: Link channel to project
INSERT INTO project_accounts (project_id, account_id, priority, notes)
VALUES (
  (SELECT id FROM projects WHERE slug = 'italian-brainrot'),
  (SELECT id FROM accounts WHERE platform_username = 'animemes-collection'),
  1,
  'YouTube Shorts channel - @animemes-collection'
)
ON CONFLICT (project_id, account_id) DO NOTHING;

-- Verify setup
SELECT
  p.name as project_name,
  p.slug as project_slug,
  a.platform_username as channel,
  pl.name as platform
FROM projects p
JOIN project_accounts pa ON pa.project_id = p.id
JOIN accounts a ON a.id = pa.account_id
JOIN platforms pl ON pl.id = a.platform_id
WHERE p.slug = 'italian-brainrot';

-- Expected output:
-- project_name: Italian Brainrot
-- project_slug: italian-brainrot
-- channel: animemes-collection
-- platform: YouTube Shorts
