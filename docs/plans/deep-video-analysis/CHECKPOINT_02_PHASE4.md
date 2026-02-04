# Checkpoint: Phase 4 + 4.5 Complete

**Date:** 2026-02-03 (updated 2026-02-04)
**Status:** Phase 4 complete, Phase 4.5 complete and tested in production

---

## Phase 4 Summary: Classifier Integration

### What Was Implemented

**File:** `viraltracker/services/ad_intelligence/classifier_service.py`

1. **VideoAnalysisService Integration**
   - Added `_classify_video_with_analysis_service()` - calls deep video analysis
   - Added `_map_video_analysis_to_classification()` - maps VideoAnalysisResult to classification fields
   - Renamed original method to `_classify_video_with_gemini_legacy()` as fallback
   - Updated `_classify_video_with_gemini()` to delegate to new methods

2. **Landing Page Lookup**
   - Added LP lookup in `_fetch_ad_data()`:
     - Queries `meta_ad_destinations` for canonical URL
     - Matches to `brand_landing_pages` for landing_page_id
   - Populates `landing_page_id` and `lp_data` in ad_data

3. **Bug Fix: video_length_bucket**
   - Fixed `_duration_to_bucket()` to return constraint-compliant values
   - Changed from `"30-60s"` to `"long_30_60"` format

**Test Script:** `scripts/test_classifier_video_integration.py`

**Test Result:**
```
Ads classified: 4
- 3 ads used gemini_light (no video available)
- 1 ad used gemini_video (deep analysis)
- video_analysis_id: Not populated (duplicate key - analysis already existed)
- landing_page_id: Not populated (no matching LPs for these ad URLs)
```

**Commit:** `90d697e` - pushed to `feat/veo-avatar-tool`

---

## Gap Identified: Missing Landing Pages

### The Problem

When the classifier encounters an ad destination URL that doesn't match any existing `brand_landing_pages`:

1. Classifier looks up `meta_ad_destinations.canonical_url`
2. Tries to match to `brand_landing_pages.canonical_url`
3. **No match found** → `landing_page_id = None`
4. **Congruence analysis impossible** without LP data

### Current Behavior

```
Ad 120239848310260742:
  Destination: https://mywonderpaws.com/products/wonder-paws-collagen-3x...
  Landing Pages Available:
    - https://mywonderpaws.com/products/best-fish-oil-for-dogs-omega-max
    - https://mywonderpaws.com/collections/all
    - https://mywonderpaws.com/pages/dog-itch-relief
  Match: None (collagen product page not in system)
  Result: landing_page_id = None, no congruence possible
```

### Why This Matters

- Phase 5 (Deep Congruence) requires LP data to compare:
  - Hook ↔ headline alignment
  - Benefits match
  - Messaging angle consistency
  - Claims consistency
- Without LP data, congruence dimensions are marked "unevaluated"
- Ads with unmatched URLs never get full congruence analysis

---

## Phase 4.5: LP Auto-Scrape Feature

### Proposed Solution

Add optional synchronous LP scraping when a destination URL doesn't match.

**New parameter for `classify_ad()`:**
```python
async def classify_ad(
    self,
    meta_ad_id: str,
    brand_id: UUID,
    org_id: UUID,
    run_id: UUID,
    video_budget_remaining: int = 0,
    scrape_missing_lp: bool = False,  # NEW
) -> ClassificationResult:
```

### Behavior

| `scrape_missing_lp` | Unmatched URL Behavior |
|---------------------|------------------------|
| `False` (default)   | Return `landing_page_id = None` (current behavior) |
| `True`              | Create LP record → Scrape with FireCrawl → Use scraped data |

### Implementation Plan

**Step 1: Add helper method to ClassifierService**
```python
async def _ensure_landing_page_exists(
    self,
    canonical_url: str,
    destination_url: str,
    brand_id: UUID,
    org_id: UUID,
) -> Optional[Dict]:
    """Ensure landing page exists, creating + scraping if needed.

    Returns LP data dict with id, url, page_title, extracted_data.
    """
    # 1. Check if LP already exists
    existing = self.supabase.table("brand_landing_pages").select(
        "id, url, page_title, extracted_data"
    ).eq("brand_id", str(brand_id)).eq(
        "canonical_url", canonical_url
    ).limit(1).execute()

    if existing.data:
        return existing.data[0]

    # 2. Create pending LP record
    lp_id = uuid4()
    self.supabase.table("brand_landing_pages").insert({
        "id": str(lp_id),
        "brand_id": str(brand_id),
        "url": destination_url,
        "canonical_url": canonical_url,
        "scrape_status": "pending",
    }).execute()

    # 3. Scrape with FireCrawl
    from viraltracker.services.web_scraping_service import WebScrapingService
    scraper = WebScrapingService()
    scrape_result = await scraper.scrape_url(destination_url)

    if not scrape_result or scrape_result.get("error"):
        # Mark as failed, return None
        self.supabase.table("brand_landing_pages").update({
            "scrape_status": "failed",
            "scrape_error": scrape_result.get("error", "Unknown error"),
        }).eq("id", str(lp_id)).execute()
        return None

    # 4. Update LP with scraped data
    self.supabase.table("brand_landing_pages").update({
        "scrape_status": "complete",
        "page_title": scrape_result.get("title"),
        "extracted_data": scrape_result.get("data"),
        "scraped_at": datetime.utcnow().isoformat(),
    }).eq("id", str(lp_id)).execute()

    return {
        "id": str(lp_id),
        "url": destination_url,
        "page_title": scrape_result.get("title"),
        "extracted_data": scrape_result.get("data"),
    }
```

**Step 2: Update _fetch_ad_data() to use helper**
```python
# In _fetch_ad_data():
if dest_result.data:
    canonical_url = dest_result.data[0].get("canonical_url")
    destination_url = dest_result.data[0].get("destination_url")

    # Try to find existing LP
    lp_result = self.supabase.table("brand_landing_pages")...

    if lp_result.data:
        result["landing_page_id"] = lp_result.data[0]["id"]
        result["lp_data"] = lp_result.data[0]
    elif scrape_missing_lp:  # NEW: Auto-scrape if enabled
        lp_data = await self._ensure_landing_page_exists(
            canonical_url, destination_url, brand_id, org_id
        )
        if lp_data:
            result["landing_page_id"] = lp_data["id"]
            result["lp_data"] = lp_data
```

**Step 3: Thread parameter through classify_ad()**
- Add `scrape_missing_lp` parameter
- Pass to `_fetch_ad_data()`

### Recommended Usage

| Context | `scrape_missing_lp` | Reason |
|---------|---------------------|--------|
| Single ad UI classification | `True` | User wants complete analysis |
| Batch classification (100+ ads) | `False` | Speed; run backfill separately |
| Ad Intelligence run | `False` | Speed; backfill as separate step |
| Manual "Deep Analyze" button | `True` | User explicitly requested |

### Performance Considerations

- **FireCrawl scrape time:** 5-30 seconds per URL
- **Rate limits:** FireCrawl has account-level rate limits
- **Cost:** Each scrape uses FireCrawl credits
- **Failure handling:** If scrape fails, continue without LP data

### Impact on Later Phases

**Phase 5 (Deep Congruence):**
- With auto-scrape enabled, more ads will have LP data for congruence
- Congruence analysis becomes more complete on first pass
- No change to CongruenceAnalyzer logic needed

**Phase 6 (Batch Re-analysis):**
- Recommend running with `scrape_missing_lp=False` for speed
- Add separate step to backfill missing LPs before re-analysis:
  1. Run batch classification (fast, no scraping)
  2. Run `backfill_unmatched_landing_pages()`
  3. Run batch re-analysis with LP data available

**Phase 7 (Hook Performance Queries):**
- No impact - queries work regardless of LP availability

---

## Files to Modify

| File | Changes |
|------|---------|
| `classifier_service.py` | Add `scrape_missing_lp` param, add `_ensure_landing_page_exists()` |
| `scripts/test_classifier_video_integration.py` | Add test case with `scrape_missing_lp=True` |

---

## Test Plan

1. **Test without auto-scrape (current behavior):**
   - Classify ad with unmatched URL
   - Verify `landing_page_id = None`

2. **Test with auto-scrape enabled:**
   - Classify ad with unmatched URL, `scrape_missing_lp=True`
   - Verify LP record created in `brand_landing_pages`
   - Verify `landing_page_id` populated in classification
   - Verify `lp_data` available for congruence

3. **Test scrape failure handling:**
   - Classify ad with invalid/unreachable URL
   - Verify LP marked as `scrape_status="failed"`
   - Verify classification continues without LP data

---

## Production Testing Results (2026-02-04)

### Phase 3: Destination URL Sync ✅
```
Destination URLs fetched: 7
Stored in database: 7
Matched to LPs: 7
```

### Phase 4: Classifier with LP Lookup ✅
```
Ad: 120239089970340742
Destination: https://mywonderpaws.com/products/wonder-paws-collagen-3x...
LP already exists: YES
Landing Page ID: 3dbec166-e77d-44a5-8e86-8b37d6f88d8f
LP Status: analyzed
LP Title: Collagen Drops – Advanced Skin, Coat & Joint Suppo
```

### Phase 4.5: LP Auto-Scrape ✅
```
Ad: 120241392909170742
Destination: https://mywonderpaws.com/pages/collagen-for-dogs-back-to-movement
LP already exists: NO
Classifying with scrape_missing_lp=True...

Result:
  Source: gemini_light
  Landing Page ID: 11bf69a5-1163-42c6-b947-89345420b656
  LP URL: https://www.mywonderpaws.com/pages/collagen-for-dogs-back-to-movement
  LP Status: scraped
  LP Title: Wonder Paws Collagen for Dogs - Mobility Support

  SUCCESS: LP was auto-scraped and linked!
```

### Fixes Applied During Testing

1. **FireCrawl metadata handling:**
   - Issue: `'DocumentMetadata' object has no attribute 'get'`
   - Fix: Use `getattr()` for title, convert object to dict for JSON storage

2. **scrape_status constraint:**
   - Issue: `violates check constraint "brand_landing_pages_scrape_status_check"`
   - Fix: Changed from `'complete'` to `'scraped'` (allowed values: pending, scraped, analyzed, failed)

### Commits
- `90d697e` - Phase 4 integration
- `a62a599` - Phase 4.5 implementation
- `405d7c8` - Production fixes

---

## Next Steps

1. ~~Update main plan to mark Phase 4 complete~~ ✅
2. ~~Add Phase 4.5 to plan with implementation steps~~ ✅
3. ~~Implement Phase 4.5~~ ✅
4. ~~Test and verify in production~~ ✅
5. **Continue to Phase 5 (Deep Congruence)**
