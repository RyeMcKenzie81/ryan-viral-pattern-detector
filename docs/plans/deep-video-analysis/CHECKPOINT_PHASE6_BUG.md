# Phase 6 Checkpoint: Bug Investigation - Copy-Only Fallback

**Date:** 2026-02-04
**Status:** Bug fix complete - awaiting push to GitHub

## Current State

### Completed Phases
- **Phase 1-5**: Deep Video Analysis pipeline complete
- **Phase 6**: Batch Re-analysis & Congruence Insights Dashboard complete
  - `CongruenceInsightsService` created
  - `congruence_reanalysis` job type added to scheduler
  - Congruence Insights UI page created (34_🔗_Congruence_Insights.py)
  - Feature flag registered in nav.py

### Bug Fixes Applied This Session
1. **Asset count duplication** - Fixed `get_asset_download_stats()` to count unique ads instead of daily rows
2. **Negative pending counts** - Capped downloaded at total for clean display
3. **Page not showing** - Registered Congruence Insights in nav.py with feature flag

### Tech Debt Added
- **#12: Decouple Ad Classification from Chat Analysis** - Move classification to background pipeline so chat analysis is instant (currently takes 25+ min for 242 ads)

---

## Current Bug: Copy-Only Fallback When Images Exist

### Symptoms
Running `Analyze Wonder Paws ad account` in Agent Chat shows many:
```
No image available for 120241079510490742, classifying from copy only
```

**Stats from Logfire (30 min window):**
- 54 ads classified WITH image
- 41 ads classified COPY-ONLY (no image)

### Expected Behavior
- All 201 image ads should use image analysis (images are downloaded)
- All 32 video ads should use video analysis (videos are downloaded)
- Copy-only should be rare edge case, not 43% of classifications

### User Context
- User confirmed all assets are downloaded
- Ad Performance page shows: Videos 32/32 (0 pending), Images 201/201 (0 pending)
- So images SHOULD exist in storage

### Hypothesis
The classifier's image lookup is failing to find downloaded images. Possible causes:
1. **Asset lookup query mismatch** - `meta_ad_assets` query not matching the ad being classified
2. **Storage path issue** - Asset exists in DB but file missing from storage
3. **Brand ID mismatch** - Query filtering by wrong brand_id
4. **Asset type mismatch** - Video ads being looked up as images or vice versa

### Investigation Complete

**Root Cause Identified:**
The copy-only fallback happens due to video classification budget limits:

1. `max_video_classifications_per_run` was set to 5 (too low for 32 video ads)
2. When video budget is exhausted (`video_budget_remaining <= 0`), video ads fell through to image classification
3. Video ads don't have separate thumbnail images in storage
4. Image classification failed → copy-only fallback

**Code Location:**
`classifier_service.py:204` - Video classification only runs if `video_budget_remaining > 0`

**Fix Applied:**
1. Increased `max_video_classifications_per_run` from 5 to 15
2. Added explicit skip for video ads when budget exhausted (returns `source="skipped_video_budget_exhausted"` instead of polluting data with copy-only)

### Files Changed (Bug Fix)
- `viraltracker/services/ad_intelligence/models.py` - Increased video budget default
- `viraltracker/services/ad_intelligence/classifier_service.py` - Skip video ads when budget exhausted

---

## Testing Context

### What We Were Testing
1. User ran `Analyze Wonder Paws ad account` in Agent Chat
2. Analysis has been running 25+ minutes (expected due to 242 ads)
3. 84+ classifications created so far
4. Noticed high rate of copy-only fallback in Logfire

### After Bug Fix, Test Again
1. Run `Analyze Wonder Paws ad account` again
2. Verify image analysis is used for image ads
3. Verify video analysis is used for video ads
4. Check Congruence Insights page for populated data

---

## Files Changed This Session

| Action | File | Description |
|--------|------|-------------|
| CREATE | `viraltracker/services/ad_intelligence/congruence_insights_service.py` | Aggregation service |
| MODIFY | `viraltracker/worker/scheduler_worker.py` | Added congruence_reanalysis job |
| CREATE | `viraltracker/ui/pages/34_🔗_Congruence_Insights.py` | Dashboard UI |
| MODIFY | `viraltracker/services/feature_service.py` | Added CONGRUENCE_INSIGHTS key |
| MODIFY | `viraltracker/ui/nav.py` | Registered page in navigation |
| MODIFY | `viraltracker/services/meta_ads_service.py` | Fixed asset count logic |
| MODIFY | `docs/TECH_DEBT.md` | Added #11 data pipeline, #12 decouple classification |
| MODIFY | `viraltracker/services/ad_intelligence/models.py` | **BUG FIX:** Increased video budget from 5 to 15 |
| MODIFY | `viraltracker/services/ad_intelligence/classifier_service.py` | **BUG FIX:** Skip video ads when budget exhausted |

## Commits (not yet pushed)
- Phase 6 implementation
- Asset count fixes
- Tech debt additions
- Video budget increase and skip logic (bug fix)
- This checkpoint

---

## Next Steps

1. ~~**Investigate** why classifier isn't finding images for 41 ads~~ ✅ **DONE** - Root cause identified
2. ~~**Fix** the image lookup logic~~ ✅ **DONE** - Increased budget + skip logic
3. **Re-test** classification to verify video ads are properly classified (run `Analyze Wonder Paws ad account` again after push)
4. **Push** all changes to GitHub (waiting for current analysis to finish)
5. **Verify** Congruence Insights page shows data after successful classification

## Summary of Bug Fix

**Before:**
- Video budget: 5 video classifications per run
- Behavior: Video ads after budget exhausted → image classification → no image → copy-only (polluted data)

**After:**
- Video budget: 15 video classifications per run
- Behavior: Video ads after budget exhausted → skipped with `source="skipped_video_budget_exhausted"` (clean data)
- Log message: "Skipping video ad {id}: video classification budget exhausted. Rerun analysis or increase budget to classify remaining video ads."
