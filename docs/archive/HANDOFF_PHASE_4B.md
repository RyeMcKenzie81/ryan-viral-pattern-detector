# Phase 4b Checkpoint - Ready to Start Apify Scraper Integration

**Date:** 2025-10-04
**Status:** Phase 4a Complete, Phase 4b Ready to Start

---

## What Was Completed

### ✅ Phase 4a: Project/Brand/Product Management CLI (COMPLETE)

**Achievements:**
- Built complete management CLI with 3 new modules
- ~780 lines of production code
- All commands tested and working
- Comprehensive documentation created
- Pushed to GitHub

**Commands Available:**
```bash
# Brand Management
vt brand list
vt brand show <slug>
vt brand create <name> [options]

# Product Management
vt product list [--brand <slug>]
vt product show <slug>
vt product create <name> --brand <slug> [options]

# Project Management
vt project list [--brand <slug>]
vt project show <slug>
vt project create <name> --brand <slug> [--product <slug>]
vt project add-accounts <slug> <file> [--platform <slug>]

# URL Import (from Phase 3)
vt import url <url> --project <slug>
vt import urls <file> --project <slug>
```

**Files Created:**
- `viraltracker/cli/brand.py`
- `viraltracker/cli/product.py`
- `viraltracker/cli/project.py`
- `PHASE_4A_SUMMARY.md`

---

## Current Database State

**Setup from migrations:**
- 1 brand: Yakety Pack
- 1 product: Core Deck
- 1 project: Yakety Pack Instagram
- 77 accounts (with platform_id)
- 1000+ posts (with platform_id, import_source)
- 3 platforms: Instagram, TikTok, YouTube Shorts

**Test data created:**
- Test Brand
- Test Product
- Test Project
- 3 test accounts added to Test Project

---

## Next: Phase 4b - Apify Scraper Integration

### Goal
Update legacy Instagram scraper to work with new multi-brand schema and populate metadata for imported URLs.

### Legacy Scraper Analysis

**Location:** `ryan-viral-pattern-detector/ryan_vpd.py`

**Current Behavior:**
1. Accepts usernames from CSV file (`--usernames <file>`)
2. Starts Apify actor run for Instagram scraping
3. Polls for completion and fetches dataset
4. Normalizes Apify data to DataFrame
5. Upserts accounts to database (uses `handle` field)
6. Upserts posts to database
7. Computes account summaries and flags outliers

**Key Functions:**
- `start_apify_run(usernames, days_back, post_type)` - Starts Apify scrape
- `poll_apify_run(run_id, timeout)` - Waits for completion
- `fetch_dataset(dataset_id)` - Gets results
- `normalize_items(items)` - Converts to standard format
- `upsert_accounts(df, supabase_client)` - Saves accounts
- `upsert_posts(df, account_map, supabase_client)` - Saves posts

**Apify Data Format:**
```python
{
    "ownerUsername": "username",
    "url": "https://instagram.com/p/...",
    "shortCode": "ABC123",
    "timestamp": "2024-01-01T12:00:00Z",
    "likesCount": 1000,
    "commentsCount": 50,
    "videoViewCount": 5000,
    "caption": "...",
    "videoDuration": 30
}
```

---

## Refactoring Plan for Phase 4b

### 1. Input Method Change
**From:** Accept usernames from CSV file
```bash
python ryan_vpd.py scrape --usernames accounts.csv
```

**To:** Accept project slug and query database
```bash
vt scrape --project yakety-pack-instagram
```

**Implementation:**
- Query `project_accounts` table to get accounts for project
- Join with `accounts` table to get `platform_username`
- Get `platform_id` from accounts (should all be same platform for a project)

### 2. Account Upserting Updates
**Current Schema Fields:**
```python
# Old fields
handle: str              # Legacy field
last_scraped_at: datetime

# New fields (already in DB from migration)
platform_id: uuid        # ✅ Already exists
platform_username: str   # ✅ Already exists
```

**Changes:**
- Query by `platform_username` AND `platform_id` (not just `handle`)
- Update `last_scraped_at` on existing accounts
- Use migrated data fields

### 3. Post Upserting Updates
**Add Required Fields:**
```python
{
    # Existing fields (keep as-is)
    "account_id": uuid,
    "post_url": str,
    "post_id": str,
    "views": int,
    "likes": int,
    "comments": int,
    "caption": str,
    "posted_at": datetime,
    "length_sec": int,

    # NEW: Add these fields
    "platform_id": uuid,        # Get from account
    "import_source": "scrape",  # Always "scrape" for Apify
    # is_own_content removed - set when linking to project
}
```

### 4. Project Linking (NEW Feature)
**After upserting posts, link them to the project:**

```python
# For each post upserted:
project_posts_data = {
    "project_id": project_id,      # From --project parameter
    "post_id": post_id,            # From upserted post
    "import_method": "scrape",     # Always "scrape" for Apify
    "is_own_content": False,       # Default to competitor content
    "notes": f"Scraped from Apify on {date}"
}

# Insert into project_posts (with duplicate check)
supabase.table("project_posts").upsert(
    project_posts_data,
    on_conflict="project_id,post_id"
).execute()
```

### 5. Metadata Population for Imported URLs (NEW Feature)
**Problem:** URLs imported via `vt import url` have no metadata (views, likes, etc.)

**Solution:** After Apify scrape, find and update imported URLs

```python
# After upserting posts from Apify:
# 1. Get all posts from this scrape batch
scraped_urls = [post['post_url'] for post in posts_data]

# 2. Find posts with same URLs but missing metadata
posts_to_update = supabase.table('posts')\
    .select('id, post_url')\
    .in_('post_url', scraped_urls)\
    .is_('views', None)\
    .execute()

# 3. Update metadata for each
for post in posts_to_update:
    # Find scraped version with same URL
    scraped_post = find_scraped_post_by_url(post['post_url'])

    # Update metadata
    supabase.table('posts').update({
        'views': scraped_post['views'],
        'likes': scraped_post['likes'],
        'comments': scraped_post['comments'],
        'caption': scraped_post['caption'],
        'posted_at': scraped_post['posted_at'],
        'length_sec': scraped_post['length_sec']
    }).eq('id', post['id']).execute()
```

---

## Implementation Approach

### Option A: Create New Scraper Module (RECOMMENDED)
Create `viraltracker/scrapers/instagram.py` with updated logic:

```
viraltracker/scrapers/
├── base.py              # Already exists (BaseScraper)
└── instagram.py         # NEW: InstagramScraper class
```

**Pros:**
- Clean separation from legacy code
- Uses new architecture
- Easier to test
- Legacy scraper still works

**Cons:**
- More code to write

### Option B: Modify Legacy Scraper
Update `ryan-viral-pattern-detector/ryan_vpd.py` in place

**Pros:**
- Reuse existing code
- Faster implementation

**Cons:**
- Risk breaking existing workflows
- Harder to maintain two approaches
- Legacy code style

**Recommendation:** Go with Option A for cleaner architecture.

---

## CLI Command Design

### New Command: `vt scrape`

```bash
vt scrape --project <slug> [options]

Options:
  --project, -p      Project slug (required)
  --days-back        Days to scrape back (default: 120)
  --post-type        Post type: reels, posts, tagged (default: reels)
  --timeout          Apify timeout in seconds (default: 300)

Examples:
  vt scrape --project yakety-pack-instagram
  vt scrape --project my-project --days-back 30
  vt scrape --project my-project --post-type posts --timeout 600
```

**Workflow:**
1. Get project from database
2. Get accounts linked to project via `project_accounts`
3. Start Apify run for those accounts
4. Poll for completion
5. Fetch and normalize data
6. Upsert accounts (update last_scraped_at)
7. Upsert posts (with platform_id, import_source)
8. Link posts to project via `project_posts`
9. Populate metadata for imported URLs
10. Display summary

---

## Files to Create

### 1. `viraltracker/scrapers/instagram.py`
Instagram scraper using new schema:
- `InstagramScraper` class (extends `BaseScraper`)
- `scrape_accounts()` method
- `populate_imported_urls_metadata()` method
- Apify integration
- Database operations

### 2. `viraltracker/cli/scrape.py`
CLI command for scraping:
- `vt scrape` command
- Progress reporting
- Error handling
- Summary display

### 3. Update `viraltracker/cli/main.py`
Register scrape command group

---

## Testing Plan

### Test 1: Basic Scrape
```bash
# Start with existing project
vt project show yakety-pack-instagram  # Should show 77 accounts

# Run scrape
vt scrape --project yakety-pack-instagram --days-back 7

# Verify results
vt project show yakety-pack-instagram  # Should show updated post count
```

### Test 2: URL Metadata Population
```bash
# Import a URL without metadata
vt import url https://instagram.com/reel/ABC123/ --project yakety-pack-instagram

# Check it has no metadata
# (query database)

# Run scrape (should pick up this URL if account is tracked)
vt scrape --project yakety-pack-instagram

# Check metadata is now populated
# (query database)
```

### Test 3: New Project from Scratch
```bash
# Create new project
vt brand create "Test Scraper Brand"
vt project create "Test Scrape" --brand test-scraper-brand

# Add accounts
echo "testuser1" > test_scrape_accounts.txt
echo "testuser2" >> test_scrape_accounts.txt
vt project add-accounts test-scrape accounts.txt

# Run scrape
vt scrape --project test-scrape

# Verify results
vt project show test-scrape  # Should show posts
```

---

## Success Criteria

✅ **Phase 4b Complete When:**
1. `vt scrape --project <slug>` command works
2. Scraper queries project_accounts for usernames
3. Posts saved with platform_id and import_source='scrape'
4. Posts linked to project via project_posts table
5. Imported URLs get metadata populated
6. Full workflow working: Create project → Add accounts → Import URLs → Scrape → URLs have metadata
7. Documentation complete
8. Tests passing

---

## Current File Structure

```
viraltracker/
├── sql/
│   └── 01_migration_multi_brand.sql
├── scripts/
│   └── migrate_existing_data.py
├── viraltracker/
│   ├── core/
│   │   ├── config.py
│   │   ├── database.py
│   │   └── models.py
│   ├── scrapers/
│   │   └── base.py
│   ├── importers/
│   │   ├── base.py
│   │   └── instagram.py
│   ├── cli/
│   │   ├── __init__.py
│   │   ├── main.py
│   │   ├── brand.py        # ✅ Phase 4a
│   │   ├── product.py      # ✅ Phase 4a
│   │   ├── project.py      # ✅ Phase 4a
│   │   └── import_urls.py  # ✅ Phase 3
├── ryan-viral-pattern-detector/  # Legacy scraper
│   └── ryan_vpd.py
├── vt                      # CLI executable
├── PHASE_2_SUMMARY.md
├── PHASE_3_SUMMARY.md
├── PHASE_4A_SUMMARY.md
├── HANDOFF_PHASE_4B.md     # ← This file
└── PROJECT_STATUS.md
```

---

## Environment Setup

```bash
cd /Users/ryemckenzie/projects/viraltracker
source ryan-viral-pattern-detector/venv/bin/activate

# Verify dependencies
pip list | grep -E "apify|supabase|click|pandas"

# Should have:
# - click
# - supabase
# - pandas
# - requests
# - tqdm
# - tenacity
```

---

## Key Points for Next Session

1. **Don't modify legacy code** - Create new scraper module
2. **Project-based scraping** - Query project_accounts, not CSV files
3. **Add platform_id** - All posts need platform_id from account
4. **Link to project** - Use project_posts junction table
5. **Populate imported URLs** - Update metadata for URLs added via CLI
6. **Test thoroughly** - Full workflow from project creation to scraping

---

## Estimated Effort

- **InstagramScraper class:** 2-3 hours
- **CLI command:** 1 hour
- **Testing:** 1-2 hours
- **Documentation:** 30 mins

**Total:** 4-7 hours of focused work

---

## Phase 4b Ready to Start! 🚀

All groundwork complete. Next session can jump straight into building the Instagram scraper module.
