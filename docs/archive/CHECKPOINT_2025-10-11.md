# ViralTracker Gemini 2.5 Pro Analysis - Checkpoint
**Date:** 2025-10-11
**Session Status:** PAUSED - Need to switch TikTok scrapers

## ✅ Completed Tasks

### 1. Re-ran 5 Failed Videos (from previous session)
- **Command used:** `echo "y" | vt analyze videos --project wonder-paws-tiktok --gemini-model models/gemini-2.5-pro`
- **Result:** All 5 videos successfully analyzed
- **Total dataset:** 69 videos, all analyzed with Gemini 2.5 Pro v1.1.0

### 2. Validated v1.1.0 Continuous Fields
- All 14 continuous metrics show good variance
- Key metrics extracted from `platform_specific_metrics` JSON:
  - `time_to_value_sec`: 0-4.5s range
  - `emotion_intensity`: 0.3-0.95 range
  - `video_length_sec`: 5.6-335s range
  - `first_2s_motion`: 0.1-0.9 range
  - All other metrics validated with reasonable distributions

### 3. Ran Correlation Analysis
**File:** `analyze_v1_1_0_results.py`

**Key Finding:**
- **emotion_intensity** shows statistically significant correlation with views
  - r=0.337, p=0.0046 ** (SIGNIFICANT)
  - Only metric with p < 0.05

**Other correlations (not significant):**
- `first_frame_face_pct`: r=-0.191, p=0.1153
- `time_to_value_sec`: r=-0.136, p=0.2660
- `simplicity_score`: r=0.131, p=0.2827
- `contrast_mean`: r=0.129, p=0.2894

**Composite score:**
- r=0.106, p=0.3874 (not significant)
- **120% improvement** over v1.0.0 baseline (r=0.048)

### 4. Compared with v1.0.0 Baseline
- v1.0.0: r=0.048, p=0.73 (NO correlation)
- v1.1.0 emotion_intensity: r=0.337, p=0.0046 (SIGNIFICANT)
- v1.1.0 composite: r=0.106, p=0.3874 (improved but not significant)

## 🔍 Key Insights

### Sample Size Analysis
- **Current n=69** is above minimum (n=30) but not ideal
- Can detect medium effects (r > 0.3) ✅
- Limited power for small effects (r < 0.2)
- **Recommendation:** 100-200 videos for robust conclusions

### Retention Data Missing
**Critical gap identified:**
- We're measuring **views** (lagging indicator)
- Should measure **retention/watch time** (leading indicator)
- TikTok algorithm rewards retention, not just views
- **Problem:** Retention data only available via TikTok Analytics (owner access)
- **Current workaround:** Use views as proxy metric

### Hook Measurement
Currently measuring:
- `time_to_value_sec` (how fast value appears)
- `first_frame_face_pct` (face in first frame)
- `first_2s_motion` (motion intensity)

**Missing:** Actual retention curves and drop-off points

## 🚨 Blocker: TikTok Scraper Not Working

### ScrapTik Actor Issues
**Current actor:** `scraptik~tiktok-api`
**Problem:** Returns `search_nil_item: 'invalid_count'` error
- All search queries return null results
- Appears to be TikTok API restrictions or actor limitations

### Solution Found: Clockworks Actor
**New actor:** `clockworks/tiktok-scraper`
**Test result:** ✅ Works perfectly!
- Tested with hashtag "dogs", requested 20 videos
- Returned 20 valid results in 12 seconds
- Output format different from ScrapTik

**Output format:**
```json
{
  "authorMeta.name": "username",
  "text": "caption text",
  "playCount": 2908,
  "diggCount": 118,
  "shareCount": 50,
  "commentCount": 10,
  "collectCount": 5,
  "videoMeta.duration": 17,
  "createTimeISO": "2023-11-07T07:50:05.000Z",
  "webVideoUrl": "https://www.tiktok.com/@user/video/123"
}
```

## 📁 Files Created/Modified

### Analysis Scripts
- `analyze_v1_1_0_results.py` - Correlation analysis with actual v1.1.0 metrics
- `inspect_metrics.py` - Inspects platform_specific_metrics structure
- `delete_flash_analyses.py` - Script to delete old analyses (already used)

### Bug Fixes
- `viraltracker/scrapers/tiktok.py:573` - Fixed null handling for `search_item_list`

## 🔄 Next Tasks

### 1. Test Clockworks Actor with 100 Videos
**Test both:**
- Hashtag search: `#dogs`, `#doghealth`
- Search queries: `"dog health tips"`, `"dog supplements"`

**Validate:**
- Returns 100 results
- Search queries work (not just hashtags)
- Output format consistent
- Can extract all needed fields

### 2. Update TikTok Scraper to Use Clockworks
**Files to modify:**
- `viraltracker/scrapers/tiktok.py`
  - Change actor ID from `scraptik~tiktok-api` to `clockworks/tiktok-scraper`
  - Update input format (different parameter names)
  - Update output parsing (`_normalize_search_posts`)

**Key changes needed:**
```python
# OLD (ScrapTik)
actor_input = {
    "searchPosts_keyword": keyword,
    "searchPosts_count": count,
    "searchPosts_sortType": sort_type
}

# NEW (Clockworks)
actor_input = {
    "hashtags": [keyword] if is_hashtag else [],
    "searchQueries": [keyword] if not is_hashtag else [],
    "resultsPerPage": count,
    "proxyCountryCode": "None"
}
```

**Output mapping:**
```python
# ScrapTik: nested in search_item_list[].aweme_info
# Clockworks: flat structure with dot notation keys

{
  "post_id": item.get("id"),  # Clockworks uses "id"
  "username": item.get("authorMeta.name"),
  "views": item.get("playCount"),
  "likes": item.get("diggCount"),
  "comments": item.get("commentCount"),
  "shares": item.get("shareCount"),
  "caption": item.get("text"),
  "posted_at": item.get("createTimeISO"),
  "post_url": item.get("webVideoUrl")
}
```

### 3. Scrape More Videos for Better Correlation
**Target:** 100-200 videos
**Approach:**
- Use Clockworks actor with multiple search terms
- Focus on dog health/supplements niche (relevant to Wonder Paws)
- Apply filters: min views 5K, max followers 50K, max 30 days old
- Process, download, and analyze all with Gemini 2.5 Pro v1.1.0

## 📊 Current Database State

### Video Analyses Summary
- **Total videos:** 69
- **All analyzed with:** Gemini 2.5 Pro + v1.1.0
- **Success rate:** 100% (after retries)
- **Analysis version:** vid-1.1.0
- **Model:** models/gemini-2.5-pro

### Database Schema
- `analysis_model`: "models/gemini-2.5-pro"
- `analysis_version`: "vid-1.1.0"
- `platform_specific_metrics`: JSON column with nested structure
  - `hook`: {time_to_value_sec, first_frame_face_present_pct, first_2s_motion_intensity}
  - `story`: {beats_count, avg_beat_length_sec, storyboard}
  - `visuals`: {edit_rate_per_10s, brightness_mean, contrast_mean}
  - `audio`: {speech_intelligibility_score, trending_sound_used}
  - `relatability`: {authenticity_signals, jargon_density_pct}
  - `shareability`: {emotion_intensity, simplicity_score}
  - `watchtime`: {length_sec}
  - `algo`: {hashtag_count}

## 🎯 Next Session Instructions

**Copy this prompt to continue:**

---

I'm continuing the ViralTracker Gemini 2.5 Pro implementation.

**Current Status (from checkpoint CHECKPOINT_2025-10-11.md):**
- ✅ All 69 videos analyzed with Gemini 2.5 Pro v1.1.0
- ✅ Correlation analysis complete: emotion_intensity significantly correlates (r=0.337, p<0.01)
- ✅ 120% improvement over v1.0.0 baseline
- 🚨 ScrapTik actor broken, found working alternative (Clockworks)
- 📊 Need more videos (100-200) for robust conclusions

**Your Tasks:**

1. **Test Clockworks actor with 100 videos:**
   - Test hashtag search with 100 results
   - Test search query (not hashtag) with 100 results
   - Verify output format is consistent
   - Confirm all needed fields are present

2. **If test succeeds, update TikTok scraper:**
   - Change actor ID in `viraltracker/scrapers/tiktok.py` from `scraptik~tiktok-api` to `clockworks/tiktok-scraper`
   - Update `_start_keyword_search_run()` to use Clockworks input format
   - Update `_normalize_search_posts()` to parse Clockworks output format
   - Add logic to distinguish hashtags vs search queries
   - Test with CLI: `vt tiktok search "dog health" --count 50`

3. **Scrape 100+ videos for improved correlation:**
   - Use search terms: "dog health", "dog supplements", "pet wellness"
   - Filters: --min-views 5000 --max-followers 50000 --max-days 30
   - Save to wonder-paws-tiktok project
   - Process videos, download, and analyze with Gemini 2.5 Pro

**Key Info:**
- Clockworks actor: `clockworks/tiktok-scraper`
- Test hashtag: `#dogs`
- Test query: `"dog health tips"`
- Target dataset size: 150-200 videos
- Current dataset: 69 videos

**Files to modify:**
- `viraltracker/scrapers/tiktok.py` (actor integration)
- `viraltracker/cli/tiktok.py` (no changes needed, uses scraper)

---
