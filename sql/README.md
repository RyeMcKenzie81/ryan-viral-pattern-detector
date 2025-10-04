# Database Migration Guide

## Multi-Brand, Multi-Platform Migration

This directory contains the SQL migration for transforming ViralTracker from a single-brand Instagram tool into a multi-brand, multi-platform system.

---

## Prerequisites

- Access to Supabase SQL Editor
- Python 3.11+ (for data migration script)
- Supabase credentials in `.env` file

---

## Migration Steps

### Step 1: Run SQL Migration

1. Open your Supabase project dashboard
2. Go to **SQL Editor**
3. Copy the contents of `01_migration_multi_brand.sql`
4. Paste into SQL Editor
5. Click **Run**

This will:
- ✅ Create new tables: `brands`, `products`, `platforms`, `projects`, `project_accounts`, `project_posts`, `product_adaptations`
- ✅ Modify existing tables: `accounts`, `posts`, `video_analysis`
- ✅ Insert default platform data (Instagram, TikTok, YouTube Shorts)

**Expected output:** All tables created successfully

---

### Step 2: Test Migration (Dry Run)

Before migrating your data, test what will happen:

```bash
cd /Users/ryemckenzie/projects/viraltracker
python scripts/migrate_existing_data.py --dry-run
```

This shows exactly what will be migrated without making any changes.

**Review the output** to ensure everything looks correct.

---

### Step 3: Run Data Migration

Migrate your existing Yakety Pack data:

```bash
python scripts/migrate_existing_data.py
```

This will:
- ✅ Create "Yakety Pack" brand
- ✅ Create "Core Deck" product with existing context
- ✅ Create "Yakety Pack Instagram" project
- ✅ Update all accounts with Instagram `platform_id`
- ✅ Update all posts with Instagram `platform_id` and `import_source='scrape'`
- ✅ Link all accounts to the project
- ✅ Link all posts to the project
- ✅ Update video analyses with platform info
- ✅ Verify migration succeeded

**Expected output:**
```
[2025-10-03 14:30:00] INFO: Starting migration...
[2025-10-03 14:30:01] INFO: ✓ Created brand 'Yakety Pack'
[2025-10-03 14:30:02] INFO: ✓ Created product 'Core Deck'
[2025-10-03 14:30:03] INFO: ✓ Created project 'Yakety Pack Instagram'
[2025-10-03 14:30:04] INFO: ✓ Migrated 50 accounts
[2025-10-03 14:30:10] INFO: ✓ Migrated 1000 posts
[2025-10-03 14:30:15] INFO: ✓ Migrated 104 video analyses
[2025-10-03 14:30:16] INFO: ✓ Migration verification complete!
```

---

### Step 4: Verify Migration

Run verification queries in Supabase SQL Editor:

```sql
-- Check platform counts
SELECT slug, name, COUNT(accounts.id) as account_count
FROM platforms
LEFT JOIN accounts ON accounts.platform_id = platforms.id
GROUP BY platforms.id, platforms.slug, platforms.name;

-- Check brand and product setup
SELECT b.name as brand, p.name as product, pr.name as project
FROM brands b
LEFT JOIN products p ON p.brand_id = b.id
LEFT JOIN projects pr ON pr.brand_id = b.id;

-- Check import sources
SELECT import_source, COUNT(*) as count
FROM posts
WHERE import_source IS NOT NULL
GROUP BY import_source;

-- Check posts with/without accounts
SELECT
  COUNT(*) FILTER (WHERE account_id IS NOT NULL) as with_account,
  COUNT(*) FILTER (WHERE account_id IS NULL) as without_account
FROM posts;
```

**Expected results:**
- All accounts should have Instagram platform_id
- All posts should have `import_source = 'scrape'`
- 1 brand (Yakety Pack)
- 1 product (Core Deck)
- 1 project (Yakety Pack Instagram)
- 3 platforms (Instagram, TikTok, YouTube Shorts)

---

## What Changed

### New Tables

1. **brands** - Different brands using the system
2. **products** - Products per brand with adaptation contexts
3. **platforms** - Social media platforms (Instagram, TikTok, YouTube)
4. **projects** - Content creation projects (brand + product + accounts)
5. **project_accounts** - Links accounts to projects (many-to-many)
6. **project_posts** - Links posts to projects (supports direct URL imports)
7. **product_adaptations** - AI-generated content adaptations

### Modified Tables

1. **accounts** - Added `platform_id`, `platform_username`
2. **posts** - Added `platform_id`, `import_source`, `is_own_content`, made `account_id` nullable
3. **video_analysis** - Added `platform_id`, `platform_specific_metrics`

---

## Backward Compatibility

✅ All existing data is preserved
✅ All existing relationships are maintained
✅ Old queries will still work (platform_id defaults to Instagram)

---

## Rollback

If you need to rollback this migration:

⚠️ **WARNING: This will delete all new tables and data!**

Uncomment and run the rollback section at the bottom of `01_migration_multi_brand.sql`.

---

## Troubleshooting

### "platforms table does not exist"
- Run the SQL migration first (Step 1)

### "Instagram platform not found"
- Check that Step 1 completed successfully
- The SQL migration should have inserted Instagram platform

### "Brand already exists"
- Migration is idempotent - safe to run multiple times
- It will skip existing records

### Python import errors
- Ensure you have dependencies: `pip install supabase python-dotenv`
- Check your `.env` file has correct Supabase credentials

---

## Next Steps

After successful migration:

1. ✅ Your existing Yakety Pack data is now in the new schema
2. ✅ Ready for Phase 2: Core Refactoring
3. ✅ Can start adding new brands, products, and platforms

See `MULTI_BRAND_PLATFORM_PLAN.md` for the full roadmap.
