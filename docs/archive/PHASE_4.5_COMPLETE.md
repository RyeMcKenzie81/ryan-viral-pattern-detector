# Phase 4.5: Account Metadata Enhancement - COMPLETE ✅

**Date:** 2025-10-06
**Status:** Production Ready
**Estimated Time:** 30 minutes
**Actual Time:** 45 minutes

---

## Overview

Enhanced Instagram scraper to capture comprehensive account metadata (follower counts, bios, verified status, etc.) alongside post data.

## Problem Statement

The previous Apify actor (`shu8hvrXbJbY3Eb9W`) returned individual posts without profile-level metadata. We needed:
- Follower counts
- Bio/biography
- Display names
- Verified status
- Profile pictures
- Account type (business/personal)

## Solution Implemented

### 1. Switched to Official Apify Instagram Scraper

**Changed from:**
- Actor ID: `shu8hvrXbJbY3Eb9W` (custom/third-party)
- Returns: Post-level data only

**Changed to:**
- Actor ID: `apify/instagram-scraper` (official)
- Returns: Profile objects with metadata + `latestPosts` arrays

### 2. Implemented Apify Python Client

**Why:** The slash in `apify/instagram-scraper` caused 404 errors with direct REST API calls.

**Solution:** Used `apify-client` Python library which handles actor ID formats correctly.

```python
from apify_client import ApifyClient

client = ApifyClient(self.apify_token)
run = client.actor(self.apify_actor_id).call(run_input=actor_input, build="latest")
```

### 3. Fixed Input Parameters

**Removed:** `isUserReelFeedURL: true` (was forcing post-level results)
**Kept:** `resultsType: "details"` (returns profile objects with metadata)

### 4. Added Post Deduplication

Added deduplication logic to prevent duplicate `post_url` errors when same post appears in multiple accounts' feeds:

```python
df = df.drop_duplicates(subset=['post_url'], keep='first')
```

---

## Database Schema (Already Complete)

From Phase 4.5 database migration:

```sql
ALTER TABLE accounts ADD COLUMN follower_count INTEGER;
ALTER TABLE accounts ADD COLUMN following_count INTEGER;
ALTER TABLE accounts ADD COLUMN bio TEXT;
ALTER TABLE accounts ADD COLUMN display_name TEXT;
ALTER TABLE accounts ADD COLUMN profile_pic_url TEXT;
ALTER TABLE accounts ADD COLUMN is_verified BOOLEAN DEFAULT FALSE;
ALTER TABLE accounts ADD COLUMN account_type TEXT;
ALTER TABLE accounts ADD COLUMN external_url TEXT;
ALTER TABLE accounts ADD COLUMN metadata_updated_at TIMESTAMPTZ;
```

---

## Files Modified

### 1. `.env`
```bash
# Changed from: APIFY_ACTOR_ID=shu8hvrXbJbY3Eb9W
APIFY_ACTOR_ID=apify/instagram-scraper
```

### 2. `viraltracker/scrapers/instagram.py`

**Imports:**
```python
from apify_client import ApifyClient
```

**Initialization:**
```python
def __init__(self, ...):
    # ... existing code ...
    self.apify_client = ApifyClient(self.apify_token)
```

**Start Run (replaced REST API with client):**
```python
def _start_apify_run(self, usernames, days_back, post_type):
    actor_input = {
        "directUrls": direct_urls,
        "resultsType": "details",  # Profile metadata + latestPosts
        "resultsLimit": 200,
        "onlyPostsNewerThan": f"{days_back} days",
        # NOT using isUserReelFeedURL - it prevents metadata
    }

    run = self.apify_client.actor(self.apify_actor_id).call(
        run_input=actor_input,
        build="latest"
    )
    return run["id"]
```

**Deduplication:**
```python
def _normalize_items(self, items):
    # ... existing normalization ...

    df = pd.DataFrame(normalized_data)
    if len(df) > 0:
        # Deduplicate by post_url
        original_count = len(df)
        df = df.drop_duplicates(subset=['post_url'], keep='first')
        if len(df) < original_count:
            logger.info(f"Removed {original_count - len(df)} duplicate posts")

    return df, account_metadata
```

### 3. Virtual Environment

Created `venv/` and installed dependencies:
```bash
python3 -m venv venv
source venv/bin/activate
pip install apify-client pandas requests python-dotenv supabase tenacity click tqdm
```

Updated `vt` CLI script to use venv python (shebang remains `#!/usr/bin/env python3` for portability).

---

## Test Results

### Scrape Test: 77 Accounts, 1 Day Back

```
📊 Summary:
   Accounts scraped: 77
   Posts scraped: 910
```

**Metadata Sample:**
```
Username: healthygamer_gg
Display Name: Healthy Gamer
Followers: 259,517
Verified: ✓
Bio: Developed by Dr. K 🧠 Mental health for the internet 💚

Username: fleurdellie
Display Name: Ellie Owens
Followers: 304,680
Verified: ✓
Bio: American mom living in Denmark 🇩🇰 Mama to 5: 👦🏼👦🏼👧🏼 and twins 👶🏼👶🏻

Username: keiki_app
Display Name: Keiki - Preschool Learning App
Followers: 727,051
Verified: ✗
Bio: 👶 Fun learning apps for kids age 2-7 👩‍🏫 Made by early learning experts
```

**Performance:**
- Removed 2 duplicate posts
- Updated 76 accounts with metadata
- Upserted 910 posts successfully
- Linked 910 posts to project
- No database errors

---

## What's Working ✅

1. **Account Metadata Capture**
   - Follower counts
   - Following counts
   - Bios/biographies
   - Display names
   - Profile picture URLs
   - Verified status
   - Account type (business/personal)
   - External URLs
   - Metadata update timestamps

2. **Post Scraping**
   - Posts from `latestPosts` arrays
   - Deduplication working
   - All post data captured (views, likes, comments, captions, etc.)

3. **Database Operations**
   - Account metadata saves correctly
   - Posts upsert without conflicts
   - Project relationships maintained
   - Timestamps tracked separately (`last_scraped_at` vs `metadata_updated_at`)

---

## Architecture Benefits

### Separation of Concerns
- `last_scraped_at` - Tracks when **posts** were last scraped
- `metadata_updated_at` - Tracks when **account metadata** was last updated
- Allows independent refresh strategies

### Scalability
- Can refresh metadata less frequently than posts
- Single scrape captures both data types
- Efficient use of Apify credits

### Data Quality
- Official Apify actor = more reliable
- Deduplication prevents database conflicts
- Graceful handling of missing data

---

## Configuration Reference

### Environment Variables
```bash
APIFY_TOKEN=your-apify-token-here
APIFY_ACTOR_ID=apify/instagram-scraper
APIFY_TIMEOUT_SECONDS=300
```

### Apify Actor Details
- **Official Name:** Instagram Scraper
- **Actor ID:** `apify/instagram-scraper`
- **Documentation:** https://apify.com/apify/instagram-scraper
- **Pricing:** Pay-per-result model

---

## Usage

### Scrape with Metadata
```bash
python vt scrape --project yakety-pack-instagram --days-back 120
```

### Query Metadata
```sql
SELECT
    platform_username,
    display_name,
    follower_count,
    is_verified,
    bio,
    metadata_updated_at
FROM accounts
WHERE metadata_updated_at IS NOT NULL
ORDER BY follower_count DESC;
```

---

## Next Steps (Future Enhancements)

### Optional Improvements
1. **Metadata Refresh Strategy**
   - Add CLI flag: `--refresh-metadata-only`
   - Refresh metadata without re-scraping posts
   - Useful for tracking follower growth

2. **Follower Tracking**
   - Create `account_metadata_history` table
   - Track follower count changes over time
   - Generate growth reports

3. **Metadata-Based Filtering**
   - Filter accounts by follower count
   - Filter by verified status
   - Filter by account type

---

## Dependencies Added

```
apify-client==2.1.0
apify-shared==2.1.0
colorama==0.4.6
impit==0.7.1
more-itertools==10.8.0
tqdm==4.67.1
```

---

## Key Learnings

1. **Actor ID Formats:** Apify client library handles `apify/actor-name` format correctly; REST API requires different approach
2. **Parameter Conflicts:** `isUserReelFeedURL: true` overrides `resultsType: "details"` and prevents metadata
3. **Deduplication Essential:** When scraping multiple accounts, same posts may appear in multiple feeds
4. **Virtual Environments:** macOS requires venv for Python package management (externally-managed environment)

---

## Completion Status

| Component | Status |
|-----------|--------|
| Database Schema | ✅ Complete |
| Pydantic Models | ✅ Complete |
| Scraper Logic | ✅ Complete |
| Apify Integration | ✅ Complete |
| Deduplication | ✅ Complete |
| Testing | ✅ Complete |
| Documentation | ✅ Complete |

**Phase 4.5: 100% Complete** 🎉

**Ready for Production:** Yes
**Backwards Compatible:** Yes
**Breaking Changes:** None

---

**Previous Phase:** [Phase 4b - Apify Scraper Integration](PHASE_4B_COMPLETE.md)
**Next Phase:** TBD - See [Multi-Brand Platform Plan](MULTI_BRAND_PLATFORM_PLAN.md)
