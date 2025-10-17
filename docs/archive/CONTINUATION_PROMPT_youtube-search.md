# Continuation Prompt: YouTube Search Implementation

## Context
I'm working on the ViralTracker project. We just completed:
1. ✅ Fixed scorer v1.2.0 database schema (nullable subscores)
2. ✅ Added query batching for large projects (1,000+ posts)
3. ✅ Both merged to master and working

## Current Task
Implement YouTube search functionality (keyword/hashtag discovery) using the **`streamers/youtube-scraper`** Apify actor.

## What to Do

**Read this checkpoint document first:**
```
/Users/ryemckenzie/projects/viraltracker/CHECKPOINT_2025-10-16_youtube-search-implementation.md
```

This document contains:
- Complete implementation plan
- Actor documentation (`streamers/youtube-scraper`)
- Step-by-step code examples
- Testing plan with 4 test cases
- File structure and reference files

**Then implement the YouTube search feature:**

1. Create new feature branch: `feature/youtube-search`
2. Create `viraltracker/scrapers/youtube_search.py` (model after `tiktok.py`)
3. Create `viraltracker/cli/youtube.py` (new CLI command)
4. Register command in `viraltracker/cli/main.py`
5. Test all 4 scenarios from the checkpoint
6. Commit and merge to master

**Key Points:**
- Use `streamers/youtube-scraper` Apify actor (NOT `youtube-shorts-scraper`)
- Support Shorts, videos, and streams with separate limits
- Use absolute filters (min_views, days_back) like TikTok pattern
- Set `import_source='search'` to distinguish from channel scrapes
- Model after `viraltracker/scrapers/tiktok.py` search functionality

## Testing Commands
```bash
# Test 1: Basic search
vt youtube search --terms "dog training" --max-shorts 50

# Test 2: With filters
vt youtube search --terms "viral dogs" --max-shorts 100 --days-back 7 --min-views 100000

# Test 3: Link to project
vt youtube search --terms "golden retriever" --max-shorts 50 --project wonder-paws-tiktok

# Test 4: Mixed content
vt youtube search --terms "puppy guide" --max-shorts 20 --max-videos 30
```

## Reference Files
- **TikTok search pattern:** `viraltracker/scrapers/tiktok.py` (lines 200-400)
- **YouTube channel scraper:** `viraltracker/scrapers/youtube.py` (for data normalization patterns)
- **TikTok CLI:** `viraltracker/cli/tiktok.py` (for CLI structure)

## Current Git Status
- **Branch:** `master`
- **Latest commits:**
  - `e3de2c9` Add query batching to handle large projects
  - `e2c9c94` Fix scorer v1.2.0 database schema compatibility

## Success Criteria
Implementation complete when:
1. `vt youtube search` command works
2. Can scrape Shorts/videos by keyword
3. Can filter by views, date, sort order
4. Results save to database with `import_source='search'`
5. Can link results to projects
6. All 4 test cases pass

Start by reading the checkpoint document, then create the feature branch and begin implementation.
