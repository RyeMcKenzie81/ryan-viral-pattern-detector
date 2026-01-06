# Checkpoint 11: Testing & Bug Fixes

**Date:** 2026-01-06
**Phase:** Testing (Post-Implementation)
**Status:** Complete

## Summary

Comprehensive testing of the Angle Pipeline revealed several bugs that have been fixed. The pipeline is now working end-to-end.

## Tests Completed

| Test | Status | Notes |
|------|--------|-------|
| Belief-First Analysis Extraction | ✅ | Fixed extraction visibility check |
| Amazon Review Analysis | ✅ | Fixed JSON parsing with Pydantic structured output |
| Pattern Discovery - Embeddings | ✅ | Fixed string serialization parsing |
| Pattern Discovery - Clustering | ✅ | Fixed negative distance matrix values |
| Pattern Discovery - Names | ✅ | Improved pattern name generation |
| Scheduler Belief-First Modes | ✅ | Fixed content_source validation |

## Bugs Fixed

### 1. Extraction Section Not Showing for Belief-First Analyzed Pages

**File:** `viraltracker/ui/pages/12_🔍_Competitor_Research.py`

**Issue:** Extraction section only checked `analyzed_at`, not `belief_first_analyzed_at`

**Fix:** Added `landing_pages_belief_first` stat check

### 2. Candidates Showing Raw JSON Dicts

**File:** `viraltracker/services/angle_candidate_service.py`

**Issue:** Belief-first analysis data is structured with nested objects, not plain strings

**Fix:** Added `_extract_belief_text_from_layer()` method to properly parse structured data

### 3. UUID Error in Research Insights

**File:** `viraltracker/ui/pages/32_💡_Research_Insights.py`

**Issue:** `AttributeError: 'UUID' object has no attribute 'replace'`

**Fix:** Convert `candidate_id` to string before storing in session state

### 4. Amazon Review Count Mismatch

**File:** `viraltracker/ui/pages/12_🔍_Competitor_Research.py`

**Issue:** Count showed 944 reviews but analysis found 0 (count didn't filter by product)

**Fix:** Updated count query to respect product filter

### 5. Missing `competitor_product_id` Column

**File:** `migrations/2026-01-06_add_competitor_product_id_to_reviews.sql`

**Issue:** Reviews scraped without product ID because column didn't exist

**Fix:** Created migration to add column and backfill from source URL records

### 6. JSON Parsing Error in Amazon Analysis

**File:** `viraltracker/services/competitor_service.py`

**Issue:** "Failed to parse analysis: Expecting ',' delimiter"

**Fix:** Switched to Pydantic structured output with `output_type=AmazonReviewAnalysis`

### 7. Pattern Discovery - Embedding String Conversion

**File:** `viraltracker/services/pattern_discovery_service.py`

**Issue:** `could not convert string to float: np.str_('[0.055...]')`

**Fix:** Added `_parse_embedding()` method to handle various serialization formats:
- JSON arrays
- numpy string repr (`np.str_('[...]')`)
- Plain string arrays

### 8. Pattern Discovery - Negative Distance Matrix

**File:** `viraltracker/services/pattern_discovery_service.py`

**Issue:** "Negative values in data passed to X" from DBSCAN

**Fix:** Clip distance matrix: `np.clip(1 - similarity_matrix, 0, 2)`

### 9. Pattern Names Too Cryptic

**File:** `viraltracker/services/pattern_discovery_service.py`

**Issue:** Names like "Pain: Watching Beloved Lose" from word fragments

**Fix:** Improved `_generate_pattern_name()` to use first candidate's name with smart truncation

### 10. Scheduler content_source Validation

**Files:**
- `viraltracker/api/models.py` - Pydantic regex
- `viraltracker/agent/agents/ad_creation_agent.py` - Runtime validation

**Issue:** `content_source must be one of ['hooks', 'recreate_template'], got angles`

**Fix:** Added `plan` and `angles` to all validation layers

## Documentation Updates

### CLAUDE.md

Added "Validation Consistency (CRITICAL)" section with:
- Checklist of layers to verify
- Grep commands for auditing
- Example showing content_source fix

### TECH_DEBT.md

Added "Pattern Discovery - Suggested Actions for Low Confidence" feature idea

## Remaining Tests

| Test | Status | How to Test |
|------|--------|-------------|
| Platform Settings → Angle Pipeline tab | ⏳ | Navigate to Platform Settings, verify settings display and save |
| Extraction Pipeline via code | ⏳ | Run `extract_candidates()` and check Logfire traces |

## Commits

- `7cf12fb` - fix: Handle string-serialized embeddings in Pattern Discovery
- `4ccbd8c` - fix: Clip distance matrix to prevent negative values in DBSCAN
- `f8edd3f` - fix: Improve pattern name generation for readability
- `6ee9b7a` - fix: Add 'plan' and 'angles' as valid content sources for scheduler
- `f30e0ba` - fix: Add 'plan' and 'angles' to content_source Pydantic validation
- `97f389e` - docs: Add validation consistency checklist to CLAUDE.md

---

## Next Steps

1. Test Platform Settings → Angle Pipeline tab
2. Verify extraction pipeline Logfire traces
3. Consider merging `feature/antigravity-setup` to `main`
