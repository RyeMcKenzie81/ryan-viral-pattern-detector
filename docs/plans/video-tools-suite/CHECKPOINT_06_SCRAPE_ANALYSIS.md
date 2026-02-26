# Video Tools Suite - Scrape & Analysis Checkpoint

**Date:** 2026-02-26
**Branch:** `feat/ad-creator-v2-phase0`
**Previous Checkpoint:** `CHECKPOINT_05_TESTING.md`

---

## Status: Scraping & Media Download Working, Content Analysis In Progress

### Completed in This Session

#### 1. Fixed Apify Scraper — "details" → "posts" Mode
- **Problem:** `resultsType: "details"` only returned ~12 latest posts per profile (Instagram's initial GraphQL response). The `resultsLimit: 200` was ignored entirely in details mode.
- **Result:** Only 61 posts scraped across 6 accounts.
- **Fix:** Changed to `resultsType: "posts"` with `addParentData: True` for profile metadata.
- **Result after fix:** 696 posts across 6 accounts.
- **Commit:** `8368dfd`
- **Files:** `viraltracker/scrapers/instagram.py`
  - Refactored `_normalize_items` to handle both "details" and "posts" formats
  - Added `_extract_posts_from_details()`, `_extract_posts_from_posts_mode()`, `_extract_profile_metadata()`, `_normalize_single_post()` helper methods

#### 2. Fixed 30-Day Lookback Windows
- **Problem:** `get_content_stats()`, `calculate_outliers()`, and `get_top_content()` all defaulted to `days=30` but scraper fetches 120 days.
- **Fix:** Changed all three to `days=120`.
- **Commits:** `fed6079`, `7dc5d01`

#### 3. Added Force Re-scrape Checkbox
- **Problem:** "Scrape All Active" skipped recently-scraped accounts (min_scrape_interval).
- **Fix:** Added "Force re-scrape" checkbox to UI that passes `force=True`.
- **Commit:** `ee39093`

#### 4. Fixed Media Download — Store CDN URLs During Scrape
- **Problem:** `download_outlier_media` called `apify/instagram-post-scraper` per post to get CDN URLs. That actor now requires `username` as an array field, and making 100 Apify calls is slow and expensive.
- **Fix:** Store `cdn_video_url` and `cdn_image_url` during the initial scrape, then download directly from stored URLs.
- **Migration required (already run):**
  ```sql
  ALTER TABLE posts ADD COLUMN IF NOT EXISTS cdn_video_url TEXT;
  ALTER TABLE posts ADD COLUMN IF NOT EXISTS cdn_image_url TEXT;
  ```
- **Commits:** `e78fad6`, `f036f55`, `5c5ea00`
- **Files changed:**
  - `viraltracker/scrapers/instagram.py` — capture `videoUrl`/`displayUrl` in normalization, include in upsert
  - `viraltracker/services/instagram_content_service.py` — rewrite `_download_post_media` to use stored CDN URLs

#### 5. Fixed Superuser "all" org_id in Multiple Services
- **Problem:** `organization_id="all"` passed as UUID to Postgres in several places.
- **Fixes applied to:**
  - `instagram_analysis_service.py` — `analyze_video()`, `analyze_image()`, `get_analyses_for_brand()`, `_get_brand_id_for_post()`. Added `_resolve_org_id_from_post()` helper.
  - `video_recreation_service.py` — `list_candidates()`, `score_candidates()`
  - `instagram_content_service.py` — `add_watched_account()` (resolves from brand)
- **Commits:** `545cf4c`, `68e065d`, `238efac`, `0dc20e1`

#### 6. Media Stats Display (uncommitted, local only)
- Changed "Media Downloaded" stat from raw file count to `outliers_with_media/total_outlier_posts` format (e.g. "65/100")
- Files: `instagram_content_service.py`, `50_📸_Instagram_Content.py`

### Current State
- **6 watched accounts** scraped successfully
- **695 total posts** in database (120-day window)
- **100 outlier posts** detected
- **~65+ outlier posts** with media downloaded (videos + thumbnails to Supabase storage)
- **Content analysis running** — Gemini Flash analyzing downloaded videos/images
  - Analysis was failing due to "all" org_id bug — now fixed in commit `0dc20e1`
  - Some analyses may need to be re-run for posts that failed before the fix deployed

### Bugs Found & Fixed This Session
| # | Error | Location | Root Cause | Fix | Status |
|---|-------|----------|------------|-----|--------|
| 3 | `resultsType: "details"` only returns ~12 posts | `scrapers/instagram.py` | Apify ignores resultsLimit in details mode | Switch to `resultsType: "posts"` | FIXED |
| 4 | Stats show 136 instead of 696 posts | `instagram_content_service.py` | 30-day default lookback | Changed to 120 days | FIXED |
| 5 | "Scrape All Active" skips recently scraped | UI `50_📸_Instagram_Content.py` | `force=False` hardcoded | Added checkbox | FIXED |
| 6 | `Field input.username is required` on media download | `instagram_content_service.py` | `instagram-post-scraper` actor requires username | Eliminated Apify calls — use stored CDN URLs | FIXED |
| 7 | `"all"` org_id in video analysis INSERT | `instagram_analysis_service.py` | Superuser org passed to INSERT | Resolve real org from post→brand chain | FIXED |
| 8 | `"all"` org_id in Video Studio list_candidates | `video_recreation_service.py` | Superuser org passed to `.eq()` | Skip filter for "all" | FIXED |

### Tech Debt
- Item #40: Replace audio-first workflow with ElevenLabs Voice Changer post-processing

### Environment
- **Branch:** `feat/ad-creator-v2-phase0`
- **Push:** `git push origin feat/ad-creator-v2-phase0`
- **Wonder Paws brand ID:** `bc8461a8-232d-4765-8775-c75eaafc5503`
- **Migrations run:** Both Phase 2 + Phase 4 migrations, plus CDN URL columns
- **All unit tests passing** (423 passed, 1 pre-existing failure in `test_lpa_screenshot_storage`)

### Next Steps (Testing Pipeline)
1. ✅ Add watched accounts
2. ✅ Scrape accounts (696 posts)
3. ✅ Calculate outliers (100 found)
4. ✅ Download outlier media
5. 🔄 **Content analysis** — currently running, may need re-run for failed posts
6. ⬜ **Video Studio → Score Candidates** — score analyzed outliers
7. ⬜ **Video Studio → Adapt Storyboard** — adapt top candidate for Wonder Paws
8. ⬜ **Video Studio → Generate Clips** — VEO only (no Kling keys)
9. ⬜ (Optional) **Assemble final video** — FFmpeg concatenation
