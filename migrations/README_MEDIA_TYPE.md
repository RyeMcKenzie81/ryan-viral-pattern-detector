# Media Type Migration - Phase 2A

**Date**: 2025-10-31
**Status**: REQUIRES MANUAL EXECUTION

## Purpose

Add media type tracking to the `posts` table to enable:
1. Filtering out video/image content from outlier detection
2. Better content adaptation (text-only tweets are easier to adapt to long-form)
3. Hook analysis that understands media context

## Migration File

`2025-10-31_add_media_type_to_posts.sql`

## How to Run

### Option 1: Via Supabase Dashboard

1. Go to your Supabase project dashboard
2. Navigate to SQL Editor
3. Copy the contents of `2025-10-31_add_media_type_to_posts.sql`
4. Paste and execute

### Option 2: Via psql

```bash
psql $DATABASE_URL -f migrations/2025-10-31_add_media_type_to_posts.sql
```

## What It Does

1. Adds 4 new columns to `posts` table:
   - `has_video` (BOOLEAN)
   - `has_image` (BOOLEAN)
   - `has_media` (BOOLEAN)
   - `media_type` (VARCHAR) - 'text', 'image', 'video', 'mixed', 'poll', 'quote'

2. Creates indexes for efficient filtering:
   - `idx_posts_media_type`
   - `idx_posts_has_video`

3. Backfills existing data:
   - Posts with `length_sec > 0` → marked as video
   - All other posts → marked as 'text'

## Impact on Existing Data

- **Non-destructive**: Only adds columns, doesn't modify existing data
- **Backward compatible**: Existing code will continue to work
- **Future scrapes**: New tweets will have media type automatically detected

## After Migration

New tweets scraped from Twitter will automatically have media type detected based on:
- Apify actor media fields (`media`, `photos`, `videos`)
- Quote tweet status
- Fallback to 'text' if no media detected

## Testing

After running migration, test with:

```bash
# Test text-only filtering
vt twitter find-outliers -p yakety-pack-instagram \
  --days-back 30 \
  --min-views 1000 \
  --text-only \
  --method percentile \
  --threshold 5.0

# Should show fewer outliers (only text-based tweets)
```

## Rollback (if needed)

```sql
ALTER TABLE posts DROP COLUMN has_video;
ALTER TABLE posts DROP COLUMN has_image;
ALTER TABLE posts DROP COLUMN has_media;
ALTER TABLE posts DROP COLUMN media_type;
DROP INDEX idx_posts_media_type;
DROP INDEX idx_posts_has_video;
```
