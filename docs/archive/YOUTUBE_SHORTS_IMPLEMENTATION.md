# YouTube Shorts Integration - Implementation Summary

**Branch:** `feature/youtube-shorts`
**Date:** 2025-10-15
**Pattern:** Instagram scraper pattern (per-channel outlier detection)

---

## ✅ What Was Implemented

### 1. YouTube Shorts Scraper (`viraltracker/scrapers/youtube.py`)
- **Pattern:** Exact copy of Instagram scraper pattern
- **Apify Actor:** `streamers/youtube-shorts-scraper`
- **Functionality:**
  - Scrapes all channels linked to a project
  - Extracts Shorts with full metadata (views, likes, comments, duration)
  - Updates channel metadata (subscribers, verified status)
  - Populates metadata for imported URLs
  - Links Shorts to projects via `project_posts` table

**Key Method:**
```python
scraper.scrape_project(
    project_slug='my-youtube-project',
    max_results=50,          # Shorts per channel
    days_back=None,          # Optional filter
    sort_by='NEWEST',        # NEWEST, POPULAR, OLDEST
    timeout=300
)
```

### 2. YouTube URL Importer (`viraltracker/importers/youtube.py`)
- Validates YouTube Shorts URLs (all formats)
- Extracts video IDs
- Saves URLs to database for later metadata population
- Supports:
  - `https://www.youtube.com/shorts/VIDEO_ID`
  - `https://youtu.be/VIDEO_ID`
  - `https://www.youtube.com/watch?v=VIDEO_ID`

### 3. Updated CLI (`viraltracker/cli/scrape.py`)
- Extended `vt scrape` command to support both platforms
- Platform-specific options via `--platform` flag

**Commands:**
```bash
# Instagram (default)
vt scrape --project yakety-pack-instagram

# YouTube Shorts
vt scrape --project my-youtube-project --platform youtube_shorts

# YouTube with options
vt scrape --project my-yt-project --platform youtube_shorts \
  --max-results 100 \
  --sort-by POPULAR \
  --days-back 30
```

---

## 📋 Before You Can Use This

### 1. Add YouTube Platform to Database

Run this SQL in Supabase:

```sql
INSERT INTO platforms (name, slug, scraper_type, scraper_config, max_video_length_sec, typical_video_length_sec, aspect_ratio)
VALUES (
  'YouTube Shorts',
  'youtube_shorts',
  'apify',
  '{"actor_id": "streamers/youtube-shorts-scraper"}'::jsonb,
  180,  -- 3 minutes max (updated Oct 2024)
  45,   -- typical 30-60 seconds
  '9:16'
);
```

### 2. Create YouTube Channels in Database

For each channel you want to track:

```sql
-- Get the YouTube platform ID first
SELECT id FROM platforms WHERE slug = 'youtube_shorts';

-- Insert channel
INSERT INTO accounts (handle, platform_id, platform_username, last_scraped_at)
VALUES (
  'channelname',           -- username without @
  '<youtube-platform-id>', -- from above query
  'channelname',           -- username without @
  NULL
);
```

### 3. Link Channels to Project

```sql
-- Get account ID
SELECT id FROM accounts WHERE platform_username = 'channelname';

-- Get project ID
SELECT id FROM projects WHERE slug = 'my-youtube-project';

-- Link them
INSERT INTO project_accounts (project_id, account_id, priority, notes)
VALUES (
  '<project-id>',
  '<account-id>',
  1,
  'YouTube Shorts channel for outlier detection'
);
```

---

## 🎯 How It Works (Same as Instagram)

### Workflow:
1. **Add channels to project** (via database, CLI coming later)
2. **Run scraper:** `vt scrape --project my-yt-project --platform youtube_shorts`
3. **Scraper fetches all Shorts** from linked channels (up to `--max-results` per channel)
4. **Saves to database** with full metadata
5. **Run outlier detection:** `vt analyze outliers --project my-yt-project --sd-threshold 3.0`
6. **Find viral Shorts** (X standard deviations above channel's trimmed mean)

### Same as Instagram Pattern:
- Per-channel outlier detection (not cross-channel)
- Scrapes ALL content from channel (no viral filters)
- Calculates baseline performance per channel
- Finds anomalies (viral content) relative to that baseline

---

## 📂 Files Created/Modified

### New Files:
- `viraltracker/scrapers/youtube.py` - YouTube Shorts scraper (Instagram pattern)
- `viraltracker/importers/youtube.py` - YouTube URL importer
- `YOUTUBE_SHORTS_IMPLEMENTATION.md` - This file

### Modified Files:
- `viraltracker/cli/scrape.py` - Added `--platform youtube_shorts` support
- `viraltracker/cli/main.py` - Import cleanup (reverted YouTube command group)

---

## 🚫 What We Avoided

**NOT Included (Intentionally):**
- ❌ No keyword/hashtag search (will come from second Apify actor later)
- ❌ No yt-dlp for scraping (only for single URL fetches if needed)
- ❌ No rate limit risks (all scraping via Apify)
- ❌ No TikTok-style discovery modes

This keeps the pattern clean and consistent with Instagram.

---

## 🔄 Integration with Existing System

### Works With:
- ✅ Existing outlier detection (`vt analyze outliers`)
- ✅ Video downloading (`vt process videos`)
- ✅ Gemini video analysis (`vt analyze videos`)
- ✅ Scoring system (v1.1.0 continuous formulas)
- ✅ Project management
- ✅ URL imports

### Database Schema:
- Uses existing `platforms`, `accounts`, `posts`, `project_posts` tables
- No schema changes needed (already multi-platform ready)
- Just needs `youtube_shorts` platform entry

---

## 🧪 Testing Checklist

Before merging:

1. **Database Setup:**
   - [ ] Add YouTube platform to `platforms` table
   - [ ] Create test YouTube channel in `accounts`
   - [ ] Link channel to test project

2. **Scraping Test:**
   - [ ] Run: `vt scrape --project test-yt --platform youtube_shorts`
   - [ ] Verify Shorts appear in database
   - [ ] Check metadata (views, likes, comments, duration)

3. **Outlier Detection:**
   - [ ] Run: `vt analyze outliers --project test-yt --sd-threshold 3.0`
   - [ ] Verify outliers are correctly identified

4. **URL Import:**
   - [ ] Run: `vt import url <youtube-shorts-url> --project test-yt`
   - [ ] Verify URL is saved
   - [ ] Re-run scraper to populate metadata

---

## 📝 Next Steps

1. **Add YouTube platform** to database (SQL above)
2. **Create CLI commands** for adding YouTube channels to projects (currently manual via SQL)
3. **Test with real channels**
4. **Implement second Apify actor** for keyword/search discovery (future)
5. **Merge to master** when testing complete

---

## 🤝 Comparison: Instagram vs YouTube Shorts

| Feature | Instagram | YouTube Shorts | Notes |
|---------|-----------|----------------|-------|
| **Scraper Pattern** | Per-account outlier | Per-channel outlier | ✅ Same |
| **Apify Actor** | `apify/instagram-scraper` | `streamers/youtube-shorts-scraper` | Different actors |
| **CLI Command** | `vt scrape --project X` | `vt scrape --project X --platform youtube_shorts` | Unified |
| **Discovery Mode** | Account scraping only | Channel scraping only | ✅ Same |
| **Outlier Detection** | 3 SD from trimmed mean | 3 SD from trimmed mean | ✅ Same |
| **Metadata** | Views, likes, comments | Views, likes, comments | ✅ Same structure |
| **URL Import** | Supported | Supported | ✅ Same |

---

## 🔍 Code References

- YouTube scraper: `viraltracker/scrapers/youtube.py`
- YouTube importer: `viraltracker/importers/youtube.py`
- Unified CLI: `viraltracker/cli/scrape.py:21` (--platform option)
- Instagram pattern reference: `viraltracker/scrapers/instagram.py`

---

**Status:** Ready for database setup and testing
**Blockers:** None - all code complete
**Next:** Add YouTube platform to database, then test scraping
