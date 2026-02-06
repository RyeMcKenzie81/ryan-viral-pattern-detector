# Phase 6 Checkpoint: Complete

**Date:** 2026-02-04
**Status:** Complete

---

## Summary

Phase 6 implemented Batch Re-analysis & Congruence Insights Dashboard, plus several bug fixes discovered during testing.

---

## What Was Built

### 1. CongruenceInsightsService
**File:** `viraltracker/services/ad_intelligence/congruence_insights_service.py`

Methods:
- `get_eligible_for_reanalysis()` - Find ads needing congruence analysis
- `get_dimension_summary()` - Aggregate counts by dimension
- `get_weak_ads_by_dimension()` - Drill-down to specific issues
- `get_improvement_suggestions()` - Ranked suggestions by frequency
- `get_congruence_trends()` - Weekly score trends
- `get_ads_with_congruence()` - List ads with congruence data

### 2. Batch Re-analysis Scheduler Job
**File:** `viraltracker/worker/scheduler_worker.py`

- Added `congruence_reanalysis` job type
- Finds eligible ads (has video_analysis_id + landing_page_id, empty congruence_components)
- Re-classifies with `force=True` to trigger congruence analysis
- Respects `max_gemini_calls` limit

### 3. Congruence Insights Dashboard
**File:** `viraltracker/ui/pages/34_🔗_Congruence_Insights.py`

4 tabs:
- **Overview** - Metrics + dimension bar chart + improvement suggestions
- **By Dimension** - Drill-down to weak/missing ads per dimension
- **Trends** - Weekly score trends
- **Re-Analysis** - Eligible ads count + scheduled job SQL

### 4. Navigation Registration
- Added `CONGRUENCE_INSIGHTS` to `FeatureKey` enum
- Registered page in `nav.py` under Ads section

---

## Bug Fixes Applied

### 1. Asset Count Duplication
**Problem:** Ad Performance showed "Videos: 63/921" when only ~130 ads exist
**Root cause:** `get_asset_download_stats()` counted rows (daily data) not unique ads
**Fix:** Deduplicate by `meta_ad_id` using set()

### 2. Negative Pending Counts
**Problem:** Shows "63/32 (-41 pending)" after fix
**Root cause:** More downloaded assets than current unique ads (legacy)
**Fix:** Cap with `min(downloaded, total)` and `max(0, pending)`

### 3. Video Classification Copy-Only Fallback
**Problem:** 43% of video ads classified with copy-only instead of video analysis
**Root cause:** `max_video_classifications_per_run` was 5, video ads after budget fell back to image → no image → copy-only
**Fix:**
- Increased budget from 5 to 15
- Skip video ads when budget exhausted (no copy-only pollution)
- Skip video ads with missing `meta_video_id` (need Download Assets)
- Clear log messages for each skip reason

### 4. Gemini Model Upgrade
**Change:** Upgraded video analysis from `gemini-2.5-flash` to `gemini-3-flash-preview`

---

## Files Changed

| Action | File | Description |
|--------|------|-------------|
| CREATE | `viraltracker/services/ad_intelligence/congruence_insights_service.py` | Aggregation service |
| MODIFY | `viraltracker/worker/scheduler_worker.py` | Added congruence_reanalysis job |
| CREATE | `viraltracker/ui/pages/34_🔗_Congruence_Insights.py` | Dashboard UI |
| MODIFY | `viraltracker/services/feature_service.py` | Added CONGRUENCE_INSIGHTS key |
| MODIFY | `viraltracker/ui/nav.py` | Registered page in navigation |
| MODIFY | `viraltracker/services/meta_ads_service.py` | Fixed asset count logic |
| MODIFY | `viraltracker/services/ad_intelligence/models.py` | Increased video budget 5→15 |
| MODIFY | `viraltracker/services/ad_intelligence/classifier_service.py` | Skip logic for video ads, model upgrade |
| MODIFY | `viraltracker/services/video_analysis_service.py` | Model upgrade to gemini-3-flash-preview |
| MODIFY | `docs/TECH_DEBT.md` | Added #10, #11, #12 |

---

## Commits

```
3c7d4c9 feat: Display per-dimension congruence in /congruence_check
89de577 feat: Phase 5 - Add per-dimension congruence analysis
70f4520 fix: Increase video classification budget and prevent copy-only fallback
95a6dc0 fix: Skip video ads with missing video_id (not just budget exhaustion)
263d92d feat: Upgrade video analysis from gemini-2.5-flash to gemini-2.5-pro
ab0cf0f feat: Use gemini-3-flash-preview for video analysis
```

---

## Testing Results

### Congruence Insights Page
- ✅ Overview tab: Shows 107 ads analyzed, dimension breakdown
- ✅ By Dimension tab: Drill-down working with suggestions
- ✅ Trends tab: Weekly summary with 0.804 avg score
- ✅ Re-Analysis tab: Shows eligible count and SQL helper

### Video Classification
- ✅ Video ads with proper IDs get video analysis
- ✅ Video ads without IDs are skipped (not copy-only)
- ✅ Budget exhaustion handled cleanly

---

## Tech Debt Added

- **#10:** Deep Video Analysis - UI & Agent Visibility
- **#11:** Improve Data Pipeline Infrastructure
- **#12:** Decouple Ad Classification from Chat Analysis (HIGH PRIORITY)

---

## Next Phase Options

### Option A: Phase 7 - UI & Agent Visibility (Tech Debt #10)
- Update `/congruence_check` to show per-dimension results
- Add `/hook_analysis` or `/top_hooks` agent tool
- Add video analysis detail view to Ad Performance page
- Hook performance dashboard

### Option B: Decouple Classification (Tech Debt #12) - RECOMMENDED
- Move classification to background pipeline
- Make chat analysis instant (seconds instead of 25+ min)
- Event-driven triggers after Meta sync / asset download

### Option C: Data Pipeline Infrastructure (Tech Debt #11)
- Better retry logic, observability
- Parallelization of classification

---

## Before Next Phase: Test Analyze Feature

**IMPORTANT:** Before starting the next phase, verify the analyze feature works correctly with the new `gemini-3-flash-preview` model:

1. Run `Analyze Wonder Paws ad account` in Agent Chat
2. Check Logfire for:
   - Video analysis using `gemini-3-flash-preview`
   - No "copy only" fallbacks for video ads
   - Proper skip messages for video ads without `meta_video_id`
3. Verify Congruence Insights page shows updated data
4. Check classification quality with the new model

---

## Session Stats

- Duration: ~2 hours
- Bug fixes: 4
- New files: 2
- Modified files: 8
- Model upgrade: gemini-2.5-flash → gemini-3-flash-preview
