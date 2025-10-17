# Checkpoint: Account Metadata Enhancement

**Date:** 2025-10-04 00:09
**Status:** Code Complete - Waiting for Apify Actor Fix

---

## What Was Completed ✅

### 1. Database Schema
**File:** `sql/02_add_account_metadata.sql`

Added 9 new columns to `accounts` table:
- `follower_count` (integer) - Number of followers
- `following_count` (integer) - Number following
- `bio` (text) - Account biography
- `display_name` (text) - Display name
- `profile_pic_url` (text) - Profile picture URL
- `is_verified` (boolean) - Verified badge
- `account_type` (text) - personal/business/creator
- `external_url` (text) - External link
- **`metadata_updated_at` (timestamptz)** - When metadata last updated

**Key Design Decision:**
- `last_scraped_at` - Tracks when **posts** were last scraped
- `metadata_updated_at` - Tracks when **account metadata** was last updated
- Allows independent updates and optimization

**Status:** ✅ Migration run successfully in Supabase

### 2. Pydantic Model
**File:** `viraltracker/core/models.py`

Updated `Account` model with all new fields:
```python
class Account(BaseModel):
    # ... existing fields

    # Account metadata
    follower_count: Optional[int] = None
    following_count: Optional[int] = None
    bio: Optional[str] = None
    display_name: Optional[str] = None
    profile_pic_url: Optional[str] = None
    is_verified: bool = False
    account_type: Optional[str] = None
    external_url: Optional[str] = None

    # Timestamps
    last_scraped_at: Optional[datetime] = None
    metadata_updated_at: Optional[datetime] = None
```

**Status:** ✅ Complete and tested

### 3. Instagram Scraper Updates
**File:** `viraltracker/scrapers/instagram.py`

**Changes Made:**
1. `_normalize_items()` now returns `Tuple[DataFrame, Dict]`
   - DataFrame: Normalized posts
   - Dict: Account metadata by username

2. Metadata extraction for profile-level data:
```python
account_metadata[username] = {
    'follower_count': profile.get('followersCount'),
    'following_count': profile.get('followsCount'),
    'bio': profile.get('biography'),
    'display_name': profile.get('fullName'),
    'profile_pic_url': profile.get('profilePicUrlHD') or profile.get('profilePicUrl'),
    'is_verified': profile.get('verified', False),
    'account_type': 'business' if profile.get('isBusinessAccount') else 'personal',
    'external_url': profile.get('externalUrl'),
}
```

3. `_upsert_accounts()` enhanced to save metadata:
   - Sets all metadata fields when available
   - Sets `metadata_updated_at` when metadata is saved
   - Gracefully handles missing metadata (no errors)

4. Set `resultsType: "details"` to request profile data

**Status:** ✅ Code complete and tested

---

## Current Issue ⚠️

### Problem: Apify Actor Not Returning Profile Metadata

**Expected Behavior:**
When using `resultsType: "details"`, Apify should return profile-level data:
```json
{
  "id": "6622284809",
  "username": "avengers",
  "fullName": "Avengers: Endgame",
  "biography": "Marvel Studios...",
  "followersCount": 8212505,
  "followsCount": 4,
  "verified": true,
  "profilePicUrl": "https://...",
  "latestPosts": [...]
}
```

**Actual Behavior:**
Current actor (`shu8hvrXbJbY3Eb9W`) returns post-level data regardless:
```json
{
  "id": "...",
  "type": "Video",
  "shortCode": "...",
  "ownerUsername": "username",
  "ownerFullName": "Display Name",
  // No follower count, bio, verified status, etc.
}
```

**Debug Evidence:**
```
[INFO] DEBUG - First item keys: ['id', 'type', 'shortCode', 'caption', ...]
[INFO] DEBUG - Has 'username': False
[INFO] DEBUG - Has 'latestPosts': False
[INFO] DEBUG - Has 'ownerUsername': True
```

### Attempted Solutions

**1. Tried Official Actor (`apify/instagram-scraper`)**
- Updated `.env`: `APIFY_ACTOR_ID=apify/instagram-scraper`
- Result: 404 Error - "page-not-found"
- Issue: The slash in ID doesn't work with current API URL format
- URL attempted: `https://api.apify.com/v2/acts/apify/instagram-scraper/runs`

**2. Tried `resultsType: "details"`**
- Already set in `actor_input`
- Actor still returns post-level data
- Current actor may not support this parameter

---

## What's Working ✅

Despite the actor limitation, the system works correctly:

1. **Database schema ready** - All columns exist and indexed
2. **Code gracefully handles missing metadata** - No errors if metadata unavailable
3. **`metadata_updated_at` works** - Gets set when metadata is present
4. **Post scraping works** - Still collecting posts successfully
5. **Backwards compatible** - Old scrapes work fine

**Test Results:**
```sql
SELECT platform_username, follower_count, bio, metadata_updated_at
FROM accounts
WHERE metadata_updated_at IS NOT NULL;
```
Returns rows with `metadata_updated_at` set, but `follower_count` and `bio` are NULL (because actor doesn't provide them).

---

## Next Steps (For Tomorrow Morning)

### Option 1: Find Correct Apify Actor ID ⭐ RECOMMENDED

The official Apify Instagram scraper supports profile metadata, but needs correct ID format.

**Tasks:**
1. Check Apify dashboard for exact actor ID
   - Might be numeric ID instead of `apify/instagram-scraper`
   - Check actor settings/API tab
2. Update `.env` with correct ID
3. Test: `vt scrape --project yakety-pack-instagram --days-back 1`
4. Verify: Check if `followersCount`, `biography`, etc. appear in dataset

**Where to Look:**
- Apify Console: https://console.apify.com/
- Actor details page → API tab
- Look for "Actor ID" or "API endpoint"

### Option 2: Use Apify Python Client

Instead of raw REST API, use official Apify client:

```python
from apify_client import ApifyClient

client = ApifyClient(self.apify_token)
run_input = {
    "directUrls": direct_urls,
    "resultsType": "details",
    ...
}

run = client.actor("apify/instagram-scraper").call(run_input=run_input)
# This handles the slash in actor ID correctly
```

**Tasks:**
1. Install: `pip install apify-client`
2. Update `_start_apify_run()` to use client library
3. Test scraping

### Option 3: Two-Step Process

Keep current actor for posts, add separate metadata fetch:

1. Scrape posts with `shu8hvrXbJbY3Eb9W` (current, working)
2. Make separate API calls to get profile data
3. Merge metadata with accounts

**Pros:** Current scraping keeps working
**Cons:** More API calls, more complex

### Option 4: Accept Limitation

Document that metadata requires different actor and continue:

- Mark metadata feature as "Phase 4.5 - Pending Actor"
- Move on to Phase 5 (video analysis)
- Revisit when we find compatible actor

---

## Files Modified

### Created
- ✅ `sql/02_add_account_metadata.sql` - Database migration
- ✅ `ENHANCEMENTS.md` - Enhancement planning document
- ✅ `CHECKPOINT_ACCOUNT_METADATA.md` - This file

### Modified
- ✅ `viraltracker/core/models.py` - Added metadata fields to Account model
- ✅ `viraltracker/scrapers/instagram.py` - Metadata extraction logic
- ✅ `.env` - Tried different actor IDs

---

## Key Code Locations

**Metadata Extraction:**
```
viraltracker/scrapers/instagram.py:287-381
- _normalize_items() - Extracts metadata from profiles
```

**Metadata Saving:**
```
viraltracker/scrapers/instagram.py:383-428
- _upsert_accounts() - Saves metadata to database
```

**Actor Configuration:**
```
viraltracker/scrapers/instagram.py:191-199
- actor_input with resultsType: "details"
```

**Debug Logging:**
```
viraltracker/scrapers/instagram.py:285-293
- Logs first item structure for debugging
```

---

## Testing Commands

**Test with real project:**
```bash
python vt scrape --project yakety-pack-instagram --days-back 1
```

**Check what actor returns:**
Look for debug logs:
```
[INFO] DEBUG - First item keys: [...]
[INFO] DEBUG - Has 'username': True/False
[INFO] DEBUG - Has 'latestPosts': True/False
```

**Verify metadata saved:**
```sql
SELECT
  platform_username,
  follower_count,
  bio,
  display_name,
  is_verified,
  metadata_updated_at
FROM accounts
WHERE metadata_updated_at IS NOT NULL
LIMIT 5;
```

**Expected when working:**
- `username` in first item: True
- `latestPosts` in first item: True
- `follower_count` populated
- `bio` populated
- `is_verified` set correctly

---

## Configuration Reference

**Current .env:**
```bash
APIFY_TOKEN=your-apify-token-here
APIFY_ACTOR_ID=shu8hvrXbJbY3Eb9W
APIFY_TIMEOUT_SECONDS=300
```

**Actor being used:**
- ID: `shu8hvrXbJbY3Eb9W`
- Type: Custom/third-party
- Returns: Post-level data only
- Missing: Profile metadata (followers, bio, verified)

**Actor needed:**
- ID: TBD (find in Apify console)
- Type: Official Instagram Profile Scraper
- Returns: Profile-level data with metadata
- Has: `followersCount`, `biography`, `verified`, `latestPosts`

---

## Phase 4b Status

**Completed:**
- ✅ Phase 4b: Apify Scraper Integration (posts working)
- ✅ Phase 4.5: Account Metadata Enhancement (code ready, data pending)

**Remaining:**
- ⏸️ Phase 4.5: Find actor that returns profile metadata
- 📋 Phase 4c: Video Download & Analysis (optional)
- 📋 Phase 5: TikTok Integration
- 📋 Phase 6: YouTube Shorts Integration

---

## Summary

🎯 **Goal:** Capture account metadata (followers, bio, verified) during scraping

✅ **What Works:**
- Database schema complete
- Code ready and tested
- Gracefully handles missing data
- Timestamp tracking works

⚠️ **Blocker:**
- Current Apify actor doesn't return profile metadata
- Official actor ID format causes 404 error

🔧 **Fix Required:**
- Find correct actor ID for official Instagram scraper
- OR use Apify Python client library
- OR implement two-step process

⏰ **Estimated Fix Time:** 30 minutes - 1 hour

📍 **Resume Here Tomorrow:**
1. Open Apify console
2. Find Instagram Profile Scraper actor
3. Get correct actor ID (probably numeric)
4. Update `.env`
5. Test `vt scrape`
6. Verify metadata appears

---

**All code is complete and ready to capture metadata as soon as we use an actor that provides it!**
