# Continuation Prompt: Twitter Integration (In Progress)

## Context
We're implementing Twitter integration for ViralTracker (Phase 1 of 2). We are **30% complete** and ready to continue.

---

## Current Status

### ✅ Completed (Steps 1-4)
1. ✅ Planning complete - `TWITTER_INTEGRATION_PLAN.md` (full spec)
2. ✅ Feature branch created - `feature/twitter-integration`
3. ✅ Database migration run - Twitter platform added and verified
4. ✅ Twitter scraper complete - `viraltracker/scrapers/twitter.py` (1,009 lines)

### 🎯 Current Task (Step 5)
Create **Twitter URL importer** at `viraltracker/importers/twitter.py`

### ⏳ Remaining (Steps 6-11)
6. Create Twitter CLI commands
7. Update scrape.py for Twitter
8. Update main.py to register Twitter
9. Run all 8 tests
10. Update README.md
11. Commit & merge to master

---

## What to Do Next

### Step 5: Create Twitter URL Importer

**File:** `viraltracker/importers/twitter.py`

**Requirements:**
- Follow the Instagram/YouTube URL importer pattern
- Support both `twitter.com` and `x.com` URLs
- Validate URL format
- Extract tweet ID from URL
- Use `BaseURLImporter` class

**Supported URL formats:**
```
https://twitter.com/username/status/1234567890
https://x.com/username/status/1234567890
```

**Reference files:**
- `viraltracker/importers/instagram.py`
- `viraltracker/importers/youtube.py`

**Pattern to follow:**
```python
class TwitterURLImporter(BaseURLImporter):
    def __init__(self, supabase_client):
        super().__init__(
            platform_slug="twitter",
            supabase_client=supabase_client
        )

    def validate_url(self, url: str) -> bool:
        # Validate twitter.com or x.com URLs

    def extract_post_id(self, url: str) -> str:
        # Extract tweet ID from /status/1234567890
```

---

## Important Files to Read

### 1. **CHECKPOINT_2025-10-16_twitter-integration.md**
- Current status and progress
- What's done, what's left
- Key implementation details

### 2. **TWITTER_INTEGRATION_PLAN.md**
- Complete implementation specification
- All technical details
- Testing plan
- Actor documentation

### 3. **viraltracker/scrapers/twitter.py**
- Review the completed scraper
- Understand data structures
- See how tweets are normalized

---

## Implementation Order (Remaining)

### Step 5: Twitter Importer (CURRENT)
- Create `viraltracker/importers/twitter.py`
- ~80-100 lines (simple pattern)

### Step 6: Twitter CLI
- Create `viraltracker/cli/twitter.py`
- Implement `twitter search` command with all filters
- Add help text and examples
- Validate 50-tweet minimum
- Validate single filter in Phase 1

### Step 7: Update Scrape CLI
- Modify `viraltracker/cli/scrape.py`
- Add `twitter` to platform choices
- Add `--chunk-by` option for Twitter

### Step 8: Register Command
- Modify `viraltracker/cli/main.py`
- Import `twitter_group`
- Add to CLI

### Step 9: Testing (8 tests)
```bash
# Test 1: Basic search
vt twitter search --terms "dog training" --count 100

# Test 2: Filters
vt twitter search --terms "viral dogs" --count 200 --min-likes 1000 --days-back 7 --only-video

# Test 3: Raw query
vt twitter search --terms "from:NASA filter:video" --count 500 --raw-query

# Test 4: Account scraping
vt scrape --project test-twitter --platform twitter

# Test 5: URL import
vt import url https://twitter.com/elonmusk/status/1728108619189874825 --project test-twitter

# Test 6: Batch
vt twitter search --terms "puppy,kitten,bunny" --count 100

# Test 7: Error (min enforcement)
vt twitter search --terms "test" --count 25  # Should error

# Test 8: Chunking
vt scrape --project test-twitter --platform twitter --chunk-by weekly
```

### Step 10: Documentation
- Update `README.md`
- Add Twitter search examples
- Add to platform list

### Step 11: Commit & Merge
- Stage all files
- Commit with detailed message
- Merge to master

---

## Key Constraints & Rules

### Actor Limitations
- ✅ **Min 50 tweets** - Enforce in CLI (hard validation)
- ✅ **Max 5 queries batched** - Already in scraper
- ⚠️ **Max 1 concurrent run** - Document only
- ⚠️ **Couple minutes between runs** - User responsibility

### Phase 1 Filters
- ✅ **Single filter only** - Validate in CLI
- Options: `--only-video`, `--only-image`, `--only-quote`, `--only-verified`, `--only-blue`
- If user specifies multiple, error and suggest Phase 2

### Phase 2 (Future)
- Multi-filter support (OR logic)
- Advanced filters (geo, mentions, etc.)

---

## Database Info

**Platform ID:** `1bb5d3cd-3548-4640-860d-5fd3c34b7c4a`

**Platform Config:**
```json
{
  "actor_id": "apidojo/tweet-scraper",
  "supports_search": true,
  "default_post_type": "tweet",
  "supports_account_scraping": true
}
```

**Platform Slug:** `twitter`

---

## Git Info

**Branch:** `feature/twitter-integration`

**Staged but not committed:**
- `TWITTER_INTEGRATION_PLAN.md`
- `migrations/2025-10-16_add_twitter_platform.sql`
- `viraltracker/scrapers/twitter.py`

**Migration Status:** Already run on database (verified)

---

## Quick Reference

### Twitter Scraper Methods
```python
TwitterScraper.scrape_search(
    search_terms: List[str],
    max_tweets: int = 100,  # min 50
    min_likes: Optional[int] = None,
    min_retweets: Optional[int] = None,
    days_back: Optional[int] = None,
    only_video: bool = False,
    only_image: bool = False,
    only_quote: bool = False,
    only_verified: bool = False,
    only_blue: bool = False,
    raw_query: bool = False,
    sort: str = "Latest",
    language: str = "en",
    project_slug: Optional[str] = None,
    timeout: int = 300
) -> Tuple[int, int]

TwitterScraper.scrape_accounts(
    project_id: str,
    max_tweets_per_account: int = 500,
    days_back: Optional[int] = None,
    chunk_by: str = "monthly",  # weekly, daily
    timeout: int = 300
) -> Dict[str, int]
```

### Data Structures
```python
# Normalized tweet DataFrame columns:
[
  'post_id', 'post_url', 'username', 'display_name',
  'follower_count', 'is_verified', 'likes', 'retweets',
  'replies', 'quotes', 'bookmarks', 'caption', 'lang',
  'posted_at', 'is_reply', 'is_retweet', 'is_quote',
  'platform_id', 'video_type'
]
```

---

## Success Criteria

Phase 1 complete when:
- ✅ All files created
- ✅ All 8 tests pass
- ✅ 50-tweet minimum enforced
- ✅ Single filter validation works
- ✅ Query batching works
- ✅ Date chunking works
- ✅ Outlier detection works
- ✅ README updated
- ✅ Committed and merged

---

## Start Command

```bash
# 1. Verify you're on the right branch
git status

# 2. Read checkpoint for context
cat CHECKPOINT_2025-10-16_twitter-integration.md

# 3. Read implementation plan
cat TWITTER_INTEGRATION_PLAN.md

# 4. Start with Step 5: Create Twitter importer
# File: viraltracker/importers/twitter.py
```

---

**Ready to continue! Start with Step 5: Twitter URL Importer**
