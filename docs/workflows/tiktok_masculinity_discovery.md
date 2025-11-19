# TikTok Masculinity Content Discovery Workflow

## Overview
Two-phase workflow to discover and validate masculinity-focused TikTok creators, filtering out meme/edit accounts and identifying active, engaging content creators.

## Workflow Phases

### Phase 1: Keyword-Based Discovery
**Script:** `tiktok_masculinity_discovery.sh`

Searches 10 masculinity-related keywords to discover viral creators:
- masculinity
- men's health
- self improvement men
- fitness motivation
- alpha male
- modern masculinity
- men's lifestyle
- brotherhood
- father figure
- men's mental health

**Filters:**
- 50K+ views per post
- <200K followers (micro-influencers)
- <30 days old
- 100 posts per keyword

**Result:** 69 unique accounts discovered

### Phase 2: Account Validation
**Script:** `tiktok_masculinity_validation.sh`

Scrapes 50 posts per discovered account to validate content focus and activity patterns.

**Output:** Full post history saved to database for analysis

## Analysis Scripts

### 1. Count Accounts
**Script:** `count_masculinity_accounts.py`

Counts unique accounts discovered from Phase 1.

### 2. Export Account List
**Script:** `export_masculinity_accounts.py`

Exports discovered accounts to text file for Phase 2 input.

**Output:** `masculinity_accounts.txt` (69 accounts)

### 3. Filter by Activity Criteria
**Script:** `analyze_masculinity_accounts.py`

Filters accounts by:
- Posted within last 7 days
- Posting frequency ≥3 posts/week
- Views stable/growing (recent 1/3 of posts ≥80% of average)

**Output:** `qualifying_masculinity_accounts.txt` (5 accounts)

### 4. Activity Breakdown Analysis
**Script:** `analyze_masculinity_breakdown.py`

Shows filter funnel:
- Total accounts: 69
- Posted recently (7 days): 24 accounts
- High frequency (≥5 posts/week): 9 accounts
- Stable/growing views: 53 accounts
- **All criteria:** 5 accounts (with 3 posts/week threshold)

### 5. Filter Meme/Edit Accounts
**Script:** `filter_meme_accounts.py`

Identifies meme/edit accounts by analyzing:
- Username patterns (contains "edit", "meme", etc.)
- Caption keywords (editing, viral, fyp)
- Hashtag patterns (#edit, #meme, #fyp)
- Caption length (short captions indicate reposts)

**Meme Score Calculation:**
- Username contains edit/meme: +3 points
- >30% posts mention editing: +2 points
- >40% posts mention memes/viral/fyp: +2 points
- >50% posts have short captions: +1 point
- >30% posts use edit/meme hashtags: +2 points
- **Threshold:** ≥3 points = meme/edit account

**Results:**
- 24 meme/edit accounts identified
- 44 original content creators

**Output:** `original_masculinity_accounts.txt`

### 6. Find Contact Information
**Script:** `find_contact_info.py`

Searches post captions for:
- Email addresses (regex pattern)
- Instagram handles
- Business keywords (contact, collab, sponsorship, dm)

**Findings:**
- 1 email found: @goatedeagle (team@goatedeagle.com)
- 20 accounts with Instagram mentions or business keywords
- **Limitation:** Scraper doesn't capture profile bios where contact info is typically listed

## Key Technical Fix

### TikTok User Scraper Bug (CRITICAL)
**File:** `viraltracker/scrapers/tiktok.py:404-410`

**Problem:** Phase 2 validation failed with Apify error about incorrect input parameters.

**Root Cause:** `_start_user_scrape_run()` was sending wrong parameter format to Apify Clockworks actor.

**Fix:**
```python
# BEFORE (BROKEN):
actor_input = {
    "usernameToId_username": username,
    "userPosts_count": count,
    "userPosts_maxCursor": "0"
}

# AFTER (FIXED):
actor_input = {
    "profiles": [f"https://www.tiktok.com/@{username}"],
    "resultsPerPage": count,
    "shouldDownloadVideos": False,
    "shouldDownloadCovers": False,
    "shouldDownloadSubtitles": False,
}
```

**Result:** Phase 2 successfully scraped all 69 accounts (59 minutes runtime).

## Database Schema Notes

**Account Fields:**
- `platform_username` (NOT `username`)
- `display_name` (NOT `full_name`)
- `bio` - exists but NOT populated by scraper
- `external_url` - exists but NOT populated by scraper

**Important:** The TikTok scraper only captures:
- Post captions
- Account metadata (username, display_name, follower_count, is_verified)
- Engagement metrics (views, likes, comments, shares)

It does **NOT** capture:
- Profile bio
- Link in bio
- Direct contact information

## Top Original Content Accounts

1. @lauringreen_fit (157.4K followers) - Fitness creator
2. @shota__yamaguchi__ (116.3K followers) - Fitness/lifestyle
3. @unshakablepursuit (105.2K followers) - Motivation/masculinity
4. @letsbetechs (97.2K followers) - Tech/productivity
5. @goatedeagle (93.9K followers) - Sports motivation (has business email)
6. @bettermindbro (74.1K followers) - Self-improvement
7. @newamericanage (66.1K followers) - American lifestyle/culture
8. @mus.ello (54.4K followers) - Music/motivation
9. @alanathegreat (42.6K followers) - Fitness/wellness
10. @krissiileigh (28.7K followers) - Fitness/lifestyle

## Limitations & Next Steps

### Current Limitations:
1. No TikTok "related accounts" API feature available
2. Bio/contact info not captured by scraper
3. Manual profile visits needed for contact information

### Recommended Next Steps:
1. **Expand keyword search** - Add more specific masculinity topics
2. **Analyze common hashtags** - Find patterns in original creators' posts
3. **Manual research** - Visit top accounts' profiles for contact info
4. **Instagram cross-reference** - Many creators more active on Instagram
5. **Upgrade scraper** - Add bio/external_url capture if Apify supports it

## File Outputs

- `masculinity_accounts.txt` - All 69 discovered accounts
- `qualifying_masculinity_accounts.txt` - 5 accounts meeting activity criteria
- `original_masculinity_accounts.txt` - 44 non-meme/edit accounts

## Usage

```bash
# Phase 1: Discovery
chmod +x tiktok_masculinity_discovery.sh
./tiktok_masculinity_discovery.sh

# Phase 2: Validation
chmod +x tiktok_masculinity_validation.sh
./tiktok_masculinity_validation.sh

# Analysis
python count_masculinity_accounts.py
python export_masculinity_accounts.py
python analyze_masculinity_accounts.py
python analyze_masculinity_breakdown.py
python filter_meme_accounts.py
python find_contact_info.py
```

## Project Context

- **Brand:** masculinity-research
- **Project:** masculinity-tiktok
- **Database:** Supabase (viraltracker)
- **Scraper:** Apify Clockworks TikTok Scraper
- **Total Runtime:** ~70 minutes (Phase 1: 11 min, Phase 2: 59 min)
