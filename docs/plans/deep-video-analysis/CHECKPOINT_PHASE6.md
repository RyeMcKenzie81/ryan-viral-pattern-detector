# Phase 6 Checkpoint: Batch Re-analysis & Congruence Insights Dashboard

**Date:** 2026-02-04
**Status:** Complete (pending data investigation)

## What Was Built

### Workstream A: CongruenceInsightsService
**File:** `viraltracker/services/ad_intelligence/congruence_insights_service.py`

Methods:
- `get_eligible_for_reanalysis()` - Find ads needing congruence analysis
- `get_dimension_summary()` - Aggregate counts by dimension
- `get_weak_ads_by_dimension()` - Drill-down to specific issues
- `get_improvement_suggestions()` - Ranked suggestions by frequency
- `get_congruence_trends()` - Weekly score trends
- `get_ads_with_congruence()` - List ads with congruence data

### Workstream B: Batch Re-analysis Job
**File:** `viraltracker/worker/scheduler_worker.py`

Added `congruence_reanalysis` job type:
- Finds eligible ads (has video_analysis_id + landing_page_id, empty congruence_components)
- Re-classifies with `force=True` to trigger congruence analysis
- Respects `max_gemini_calls` limit
- Parameters: `batch_size`, `max_gemini_calls`, `brand_id`

### Workstream C: Congruence Insights Dashboard
**File:** `viraltracker/ui/pages/34_🔗_Congruence_Insights.py`

4 tabs:
1. **Overview** - Metrics + dimension bar chart + improvement suggestions
2. **By Dimension** - Drill-down to weak/missing ads per dimension
3. **Trends** - Weekly score trends (line + bar charts)
4. **Re-Analysis** - Eligible ads count + scheduled job SQL

### Navigation Registration
- Added `CONGRUENCE_INSIGHTS` to `FeatureKey` enum
- Registered page in `nav.py` under Ads section

## Testing Results

- UI loads correctly
- Service methods work (verified via CLI test)
- Data is sparse because most ads lack prerequisites:
  - `video_analysis_id` - requires deep video analysis
  - `landing_page_id` - requires LP linking
  - Only 1 Wonder Paws ad has both + populated congruence_components

## Open Issues

### Data Duplication in Ad Performance
User reported inflated counts:
- Videos: 63/921 (848 pending)
- Images: 217/2533 (2316 pending)
- But only ~130 active ads exist

**Root cause investigation needed** - see next task.

### Analyze Strategy Button
User couldn't find "Analyze Strategy" button on Ad Performance page.
Need to investigate location or add to tech debt.

## Next Steps

1. Investigate asset count duplication
2. Clean up duplicate data
3. Locate or document "Analyze Strategy" flow
4. Run full analysis on Wonder Paws to populate congruence data

## Files Changed

| Action | File |
|--------|------|
| CREATE | `viraltracker/services/ad_intelligence/congruence_insights_service.py` |
| MODIFY | `viraltracker/worker/scheduler_worker.py` |
| CREATE | `viraltracker/ui/pages/34_🔗_Congruence_Insights.py` |
| MODIFY | `viraltracker/services/feature_service.py` |
| MODIFY | `viraltracker/ui/nav.py` |

## Commits

- `619cda6` - feat: Phase 6 - Batch re-analysis and Congruence Insights Dashboard
- `697b02e` - docs: Add data pipeline improvement to tech debt
- `5740748` - fix: Replace plotly with native Streamlit charts
- `4e0d116` - fix: Register Congruence Insights page in nav.py with feature flag
