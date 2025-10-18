# CHECKPOINT: Twitter Integration - In Progress

**Date:** 2025-10-16
**Branch:** `feature/twitter-integration`
**Status:** 🚧 Phase 1 Implementation - 30% Complete

---

## 🎯 What We're Building

Twitter integration for ViralTracker with two modes:
1. **Search mode** - Keyword/hashtag discovery with Twitter query language
2. **Account mode** - Per-account scraping with 3SD outlier detection (TikTok pattern)

**Actor:** `apidojo/tweet-scraper`
**Platform:** All content types (text, images, video)
**Filters:** Phase 1 = simple inclusion filters only

---

## ✅ Completed (30%)

### 1. Planning & Documentation
- ✅ **TWITTER_INTEGRATION_PLAN.md** - Complete implementation plan with:
  - Technical specifications
  - Actor integration details
  - Database schema
  - CLI design with examples
  - 8-test testing plan
  - Phase 1/2 separation

### 2. Feature Branch
- ✅ Created `feature/twitter-integration` branch
- ✅ Clean starting point from master

### 3. Database Migration
- ✅ **File:** `migrations/2025-10-16_add_twitter_platform.sql`
- ✅ **Status:** Run and verified
- ✅ **Platform ID:** `1bb5d3cd-3548-4640-860d-5fd3c34b7c4a`
- ✅ **Config:**
  ```json
  {
    "actor_id": "apidojo/tweet-scraper",
    "supports_search": true,
    "default_post_type": "tweet",
    "supports_account_scraping": true
  }
  ```

### 4. Twitter Scraper (COMPLETE)
- ✅ **File:** `viraltracker/scrapers/twitter.py` (1,009 lines)
- ✅ **Pattern:** Based on TikTok scraper, adapted for Twitter actor
- ✅ **Features:**
  - Search mode with automatic query building
  - Raw query mode for advanced users
  - Account scraping with date chunking (monthly/weekly/daily)
  - Batch processing (max 5 queries per run)
  - 50-tweet minimum enforcement
  - Outlier detection (3SD from trimmed mean)
  - All Phase 1 filters implemented

**Key Methods:**
```python
scrape_search(
    search_terms, max_tweets, min_likes, min_retweets, days_back,
    only_video, only_image, only_quote, only_verified, only_blue,
    raw_query, sort, language, project_slug
) -> Tuple[int, int]

scrape_accounts(
    project_id, max_tweets_per_account, days_back, chunk_by
) -> Dict[str, int]

_build_twitter_query(...) -> str
_chunk_date_ranges(...) -> List[Tuple[datetime, datetime]]
_normalize_tweets(...) -> pd.DataFrame
save_posts_to_db(...) -> List[str]
_calculate_outliers(...) -> List[str]
```

---

## 🚧 In Progress (0%)

Nothing currently in progress - ready for next file.

---

## ⏳ TODO (70%)

### 5. Twitter URL Importer
- ⏳ **File:** `viraltracker/importers/twitter.py`
- ⏳ **Pattern:** Follow Instagram/YouTube URL importer pattern
- ⏳ **Supported URLs:**
  - `https://twitter.com/username/status/1234567890`
  - `https://x.com/username/status/1234567890`

### 6. Twitter CLI Commands
- ⏳ **File:** `viraltracker/cli/twitter.py`
- ⏳ **Commands:**
  - `vt twitter search` - Search with all Phase 1 filters
  - Command help with examples

### 7. Update Scrape CLI
- ⏳ **File:** `viraltracker/cli/scrape.py`
- ⏳ **Changes:** Add `twitter` to platform choices
- ⏳ **Changes:** Add `--chunk-by` option for Twitter

### 8. Register Twitter Command
- ⏳ **File:** `viraltracker/cli/main.py`
- ⏳ **Changes:** Import and register `twitter_group`

### 9. Testing
- ⏳ **Test 1:** Basic search (50-100 tweets)
- ⏳ **Test 2:** Search with filters (likes, date, video)
- ⏳ **Test 3:** Raw query mode
- ⏳ **Test 4:** Account scraping with chunking
- ⏳ **Test 5:** URL import
- ⏳ **Test 6:** Batch query (3 terms)
- ⏳ **Test 7:** Error handling (min 50 enforcement)
- ⏳ **Test 8:** Date chunking (weekly)

### 10. Documentation
- ⏳ Update `README.md` with Twitter examples

### 11. Commit & Merge
- ⏳ Commit all changes
- ⏳ Merge `feature/twitter-integration` to `master`

---

## 📁 Files Status

### Created
- ✅ `TWITTER_INTEGRATION_PLAN.md` - Complete spec
- ✅ `migrations/2025-10-16_add_twitter_platform.sql` - Migration (run)
- ✅ `viraltracker/scrapers/twitter.py` - Scraper (complete)
- ✅ `CHECKPOINT_2025-10-16_twitter-integration.md` - This file

### To Create
- ⏳ `viraltracker/importers/twitter.py` - URL importer
- ⏳ `viraltracker/cli/twitter.py` - CLI commands

### To Modify
- ⏳ `viraltracker/cli/scrape.py` - Add Twitter platform
- ⏳ `viraltracker/cli/main.py` - Register Twitter
- ⏳ `README.md` - Add Twitter docs

---

## 🔑 Key Implementation Details

### Twitter Query Building
The scraper automatically builds Twitter queries:
```python
# Input: "dog training" + days_back=7 + min_likes=1000 + only_video=True
# Output: "dog training since:2024-10-09 min_faves:1000 filter:video -filter:retweets"
```

### Date Chunking for Accounts
Automatically splits account scraping into chunks to respect ~800 tweet limit:
```python
# Example: Monthly chunks for @NASA from 2023
queries = [
    "from:NASA since:2023-01-01 until:2023-02-01",
    "from:NASA since:2023-02-01 until:2023-03-01",
    # ... etc
]
```

### Batch Processing
Batches up to 5 search terms per Apify run:
```python
search_terms = ["dog training", "puppy tricks", "pet care"]
# Runs as single Apify call with all 3 terms
```

### Data Mapping
```python
# Actor output → Database
{
  "id": "123..." → posts.post_id
  "text": "..." → posts.caption
  "likeCount": 100 → posts.likes
  "replyCount": 20 → posts.comments
  "retweetCount": 50 → posts.shares
  "quoteCount": 10 → platform_specific_data.quoteCount
  "bookmarkCount": 5 → platform_specific_data.bookmarkCount
  "author.userName": "user" → accounts.platform_username
  "author.followers": 1000 → accounts.follower_count
}
```

---

## 🚨 Important Constraints

### Actor Limitations (Enforced in Code)
- ✅ **Min 50 tweets per query** - Hard validation in CLI
- ✅ **Max 5 queries batched** - Implemented in scraper
- ✅ **Max 1 concurrent run** - Documented (hard to enforce)
- ⏳ **Couple minutes between runs** - Not enforced (user responsibility)

### Phase 1 Limitations
- ✅ **Single filter only** - Validated in CLI
- ⏳ **No multi-filter OR logic** - Coming in Phase 2
- ⏳ **No advanced filters** - Coming in Phase 2 (geo, mentions, etc.)

---

## 📋 Implementation Order

**Completed:**
1. ✅ Document plan
2. ✅ Create feature branch
3. ✅ Create database migration
4. ✅ Create Twitter scraper

**Next Steps:**
5. ⏳ Create Twitter importer
6. ⏳ Create Twitter CLI
7. ⏳ Update scrape.py
8. ⏳ Update main.py
9. ⏳ Run all tests
10. ⏳ Update README
11. ⏳ Commit & merge

---

## 🔄 Git Status

**Branch:** `feature/twitter-integration`
**Commits:** None yet (all files staged but not committed)

**Staged Files:**
- `TWITTER_INTEGRATION_PLAN.md`
- `migrations/2025-10-16_add_twitter_platform.sql`
- `viraltracker/scrapers/twitter.py`

**Unstaged/Untracked:**
- Various test files from previous work
- Checkpoint/continuation docs

---

## 💡 Reference Information

### Platform ID
```
Twitter Platform ID: 1bb5d3cd-3548-4640-860d-5fd3c34b7c4a
```

### Example CLI Commands (To Be Implemented)
```bash
# Search mode
vt twitter search --terms "dog training" --count 100 --only-video

# With filters
vt twitter search --terms "viral dogs" --count 200 --min-likes 1000 --days-back 7

# Raw query
vt twitter search --terms "from:NASA filter:video" --count 500 --raw-query

# Account scraping
vt scrape --project my-twitter-project --platform twitter --chunk-by weekly
```

### Reference Files
- **Pattern reference:** `viraltracker/scrapers/tiktok.py` (TikTok scraper)
- **Importer reference:** `viraltracker/importers/instagram.py`, `viraltracker/importers/youtube.py`
- **CLI reference:** `viraltracker/cli/tiktok.py`, `viraltracker/cli/youtube.py`

---

## 📚 Documentation References

- **Implementation Plan:** `TWITTER_INTEGRATION_PLAN.md` (58 KB, complete spec)
- **Apify Actor:** `apidojo/tweet-scraper`
- **Twitter Query Syntax:** https://github.com/igorbrigadir/twitter-advanced-search

---

## ⚡ Quick Start for Next Session

1. **Read this checkpoint** - Understand current state
2. **Read TWITTER_INTEGRATION_PLAN.md** - Full implementation details
3. **Check current branch:** `git status` (should be on `feature/twitter-integration`)
4. **Continue with step 5:** Create `viraltracker/importers/twitter.py`
5. **Follow implementation order** through step 11

---

**Status:** Ready to continue implementation
**Next File:** `viraltracker/importers/twitter.py`
**Completion:** 30% (3/10 steps done)
