# TikTok Integration - Quick Start Guide

## Overview

ViralTracker now supports **TikTok** content analysis with 3 discovery modes:

1. **Keyword Search** - Find viral content by keyword
2. **Hashtag Tracking** - Monitor specific hashtags
3. **User/Creator Scraping** - Track specific accounts

All modes support outlier detection and AI analysis with Gemini.

---

## Prerequisites

1. **Apify API Token** - Set `APIFY_TOKEN` in `.env`
2. **Database Migration** - Run `sql/03_update_tiktok_scraper.sql` to configure ScrapTik
3. **Gemini API Key** - Set `GEMINI_API_KEY` in `.env` (for AI analysis)

---

## CLI Commands

### 1. Keyword Search

Find viral content from micro-influencers by keyword.

```bash
# Basic search
vt tiktok search "productivity apps"

# With custom filters
vt tiktok search "time management" \
  --count 100 \
  --min-views 50000 \
  --max-days 7 \
  --max-followers 100000

# Save to project
vt tiktok search "notion tips" \
  --project yakety-pack \
  --save
```

**Default Filters:**
- Views: 100,000+ (proven viral reach)
- Age: <10 days (current trends)
- Creator followers: <50,000 (micro-influencers)

**Options:**
- `--count` - Number of posts to fetch (default: 50)
- `--min-views` - Minimum views (default: 100K)
- `--max-days` - Maximum age in days (default: 10)
- `--max-followers` - Max creator followers (default: 50K)
- `--project` - Project slug to link posts
- `--save/--no-save` - Save to database (default: True)
- `--sort` - 0=Relevance, 1=Most Liked, 3=Date

---

### 2. Hashtag Search

Track specific hashtags for viral content.

```bash
# Basic hashtag search
vt tiktok hashtag productivityhack

# With project
vt tiktok hashtag appreviews \
  --project yakety-pack \
  --count 100

# Custom filters
vt tiktok hashtag studytok \
  --min-views 200000 \
  --max-days 5
```

**Options:** Same as keyword search

---

### 3. User/Creator Scraping

Scrape posts from specific TikTok accounts for outlier detection.

```bash
# Basic user scrape
vt tiktok user alexhormozi

# With outlier detection
vt tiktok user productivityguru \
  --project yakety-pack \
  --analyze-outliers

# Fetch more posts
vt tiktok user creator123 \
  --count 100 \
  --save
```

**Options:**
- `--count` - Number of posts (default: 50)
- `--project` - Project slug
- `--save/--no-save` - Save to database
- `--analyze-outliers` - Run outlier detection after scraping

**Note:** No filtering applied - fetches all posts to calculate baseline for statistical outlier detection.

---

## Workflow Examples

### Workflow 1: Keyword Search → Download → Analyze

```bash
# 1. Search for viral content
vt tiktok search "productivity apps" --project yakety-pack

# 2. Download videos
vt process videos --project yakety-pack

# 3. Analyze with Gemini AI
vt analyze videos --project yakety-pack --product core-deck
```

### Workflow 2: User Tracking → Outlier Detection → Analyze

```bash
# 1. Scrape user posts with outlier detection
vt tiktok user productivityguru \
  --project yakety-pack \
  --analyze-outliers

# 2. Download outlier videos only
vt process videos --project yakety-pack --unprocessed-outliers

# 3. Analyze outliers
vt analyze videos --project yakety-pack --product core-deck
```

### Workflow 3: Hashtag Monitoring → Filter → Batch Analysis

```bash
# 1. Track multiple hashtags
vt tiktok hashtag productivityhack --project yakety-pack
vt tiktok hashtag appreviews --project yakety-pack
vt tiktok hashtag studytok --project yakety-pack

# 2. Download all videos
vt process videos --project yakety-pack

# 3. Analyze all videos
vt analyze videos --project yakety-pack --product core-deck
```

---

## Outlier Detection

### Two Modes

**1. Keyword/Hashtag Search**
- Uses filtering criteria (already applied in scraper)
- No statistical outlier detection needed
- Finds: 100K+ views, <10 days old, <50K followers

**2. User/Creator Tracking**
- Uses statistical outlier detection (3 SD from trimmed mean)
- Identifies posts that overperformed for that specific creator
- Finds: Relative outliers based on user's baseline

### Run Outlier Detection Manually

```bash
# After scraping user posts
vt analyze outliers --project yakety-pack

# Custom threshold (default: 3.0)
vt analyze outliers --project yakety-pack --sd-threshold 2.5
```

---

## Pricing (ScrapTik via Apify)

- **$0.002 per request** (flat rate)
- 95% cheaper than per-result pricing
- No proxy management needed
- Includes all endpoints

**Examples:**
- 50 posts: $0.002 (single request)
- 500 posts: ~$0.02 (multiple requests with pagination)

---

## Data Captured

### TikTok-Specific Metrics

- **Views** - Play count
- **Likes** - Digg count
- **Comments** - Comment count
- **Shares** - Share count (TikTok exclusive!)
- **Play Duration** - Video length
- **Download URL** - Watermark-free video URL

### Creator Metadata

- Username
- Display name
- Follower count
- Verification status
- Bio/profile info

---

## Platform-Aware AI Analysis

Gemini analysis automatically detects platform and adjusts prompts:

```json
{
  "hook_analysis": {...},
  "viral_factors": {...},
  "platform_specific_insights": {
    "tiktok_sounds": "...",
    "tiktok_effects": "...",
    "algorithm_optimization": "..."
  },
  "product_adaptation": {...}
}
```

---

## Troubleshooting

### Issue: No results from search

**Solutions:**
- Lower filters: `--min-views 50000 --max-followers 100000`
- Increase count: `--count 100`
- Expand time range: `--max-days 30`
- Try different keywords/hashtags

### Issue: User scraping returns empty

**Check:**
- Username is correct (without @)
- Account is public
- Account has posts
- Apify token is valid

### Issue: Database errors

**Run migration:**
```bash
# In Supabase SQL Editor
-- Run: sql/03_update_tiktok_scraper.sql
```

---

## Architecture

```
┌─────────────────────────────────────────────────┐
│           TikTok Discovery Modes                │
├──────────────┬──────────────┬───────────────────┤
│   Keyword    │   Hashtag    │   User/Creator    │
│   Search     │   Tracking   │   Scraping        │
└──────┬───────┴──────┬───────┴─────────┬─────────┘
       │              │                 │
       └──────────────┼─────────────────┘
                      │
                      ▼
            ┌─────────────────────┐
            │  ScrapTik (Apify)   │
            │  $0.002/request     │
            └──────────┬──────────┘
                       │
                       ▼
            ┌─────────────────────┐
            │  Filter/Outliers    │
            │  - Keyword: Filter  │
            │  - User: 3 SD       │
            └──────────┬──────────┘
                       │
                       ▼
            ┌─────────────────────┐
            │  Download Videos    │
            │  (watermark-free)   │
            └──────────┬──────────┘
                       │
                       ▼
            ┌─────────────────────┐
            │  Gemini Analysis    │
            │  (platform-aware)   │
            └──────────┬──────────┘
                       │
                       ▼
            ┌─────────────────────┐
            │  Product Adaptation │
            │  (multi-brand)      │
            └─────────────────────┘
```

---

## Next Steps

1. **Run Database Migration**
   ```sql
   -- In Supabase SQL Editor
   -- Run: sql/03_update_tiktok_scraper.sql
   ```

2. **Test Search**
   ```bash
   vt tiktok search "your niche" --no-save
   ```

3. **Create Project**
   ```bash
   vt project create "TikTok Research" --brand yakety-pack
   ```

4. **Start Scraping**
   ```bash
   vt tiktok search "productivity" --project your-project
   ```

5. **Analyze Results**
   ```bash
   vt process videos --project your-project
   vt analyze videos --project your-project --product your-product
   ```

---

## Documentation

- **Outlier Detection Strategies**: `viraltracker/docs/outlier_detection_strategies.md`
- **TikTok Scraper**: `viraltracker/scrapers/tiktok.py`
- **TikTok CLI**: `viraltracker/cli/tiktok.py`
- **Video Analyzer**: `viraltracker/analysis/video_analyzer.py`

---

## Support

- ScrapTik Documentation: https://scraptik.com
- ViralTracker Issues: https://github.com/your-repo/issues
- Apify Dashboard: https://console.apify.com

---

**Happy analyzing! 🚀**
