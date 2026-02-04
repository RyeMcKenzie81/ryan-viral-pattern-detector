# Phase 7 Checkpoint: HookAnalysisService Complete (Workstream A)

**Date:** 2026-02-04
**Status:** Workstream A Complete
**Next:** Workstreams B (Agent Tools) and C (UI Dashboard)

---

## Summary

Workstream A of Phase 7 is complete. The HookAnalysisService provides comprehensive hook performance queries that join `ad_video_analysis` (hook data) with `meta_ads_performance` (metrics) to surface which hooks work best for data-driven creative decisions.

---

## What Was Built

### HookAnalysisService
**File:** `viraltracker/services/ad_intelligence/hook_analysis_service.py`

#### Core Aggregation Methods

| Method | Purpose |
|--------|---------|
| `get_top_hooks_by_fingerprint()` | Top hooks with flexible sorting (roas, hook_rate, spend, ctr, cpa) |
| `get_hooks_by_quadrant()` | Categorize hooks into 4 quadrants (winners, hidden_gems, engaging_not_converting, losers) |
| `get_high_hook_rate_low_roas()` | High engagement, poor conversion - fix downstream |
| `get_high_hook_rate_high_roas()` | Winners to scale |
| `get_hooks_by_type()` | Aggregate by hook_type (question, claim, story, etc.) |
| `get_hooks_by_visual_type()` | Aggregate by hook_visual_type (unboxing, demo, etc.) |
| `get_hooks_by_landing_page()` | Hooks grouped by LP with best/worst hook per LP |

#### Detailed Analysis Methods

| Method | Purpose |
|--------|---------|
| `get_hook_details()` | Detailed info for specific fingerprint (all ads, LPs, variance) |
| `get_hook_comparison()` | Compare two hooks head-to-head with winner badges |
| `get_untested_hook_types()` | Gap analysis - find what hasn't been tested |

#### Insights & Recommendations

| Method | Purpose |
|--------|---------|
| `get_hook_insights()` | Generate actionable insights (top/worst performer, recommendations) |
| `get_winning_hooks_for_lp()` | Best hooks for specific landing page |

---

## Key Design Decisions

### 1. Hook Rate Calculation
Hook rate is computed as `video_views / impressions` (% viewers past first 3 seconds). This matches the existing diagnostic engine pattern.

### 2. Minimum Spend Threshold
Default `$100` minimum spend to filter noise. All "top" queries use this threshold to ensure statistical significance.

### 3. Quadrant Analysis
Plotting **Hook Rate vs ROAS** reveals actionable patterns:

```
                    HIGH ROAS
                        │
     🎯 WINNERS         │         🔍 HIDDEN GEMS
     High hook rate     │         Low hook rate
     High ROAS          │         High ROAS
     → SCALE THESE      │         → Why low engagement?
                        │
────────────────────────┼────────────────────────
                        │
     ⚠️ ENGAGING BUT    │         💀 LOSERS
        NOT CONVERTING  │         Low hook rate
     High hook rate     │         Low ROAS
     Low ROAS           │         → KILL THESE
     → Fix downstream   │
       (LP? offer?)     │
```

### 4. Database Joins
Joins performed in Python due to Supabase client limitations:
- `ad_video_analysis` → hook data (fingerprint, type, visual_type, transcript)
- `meta_ads_performance` → performance metrics (spend, impressions, video_views, purchases)
- `ad_creative_classifications` → links to landing pages via `video_analysis_id` and `landing_page_id`
- `brand_landing_pages` → LP details (url, title)

### 5. Configurable Thresholds
- `hook_rate_threshold`: Default 25% for "high" engagement
- `roas_threshold`: Default 1.0 for breakeven, 2.0 for "winners"
- `date_range_days`: Configurable lookback window

---

## Test Script

**File:** `scripts/test_hook_analysis.py`

Tests all 12 methods:
1. `get_top_hooks_by_fingerprint()`
2. `get_hooks_by_type()`
3. `get_hooks_by_visual_type()`
4. `get_hooks_by_landing_page()`
5. `get_hooks_by_quadrant()`
6. `get_high_hook_rate_low_roas()`
7. `get_untested_hook_types()`
8. `get_hook_insights()`
9. `get_hook_details()`
10. `get_hook_comparison()`

Run with:
```bash
python scripts/test_hook_analysis.py
```

---

## Files Created/Modified

| Action | File |
|--------|------|
| CREATE | `viraltracker/services/ad_intelligence/hook_analysis_service.py` |
| CREATE | `scripts/test_hook_analysis.py` |
| CREATE | `docs/plans/deep-video-analysis/CHECKPOINT_06_PHASE7_SERVICE.md` |

---

## Remaining Work (Workstreams B & C)

### Workstream B: Agent Tools (~20K tokens)
Add to `viraltracker/agent/agents/ad_intelligence_agent.py`:
- `/hook_analysis` - Main analysis tool with multiple modes
- `/top_hooks` - Quick view of winning hooks
- `/hooks_for_lp` - Best hooks for specific landing page

### Workstream C: UI Dashboard (~30K tokens)
Create `viraltracker/ui/pages/35_🎣_Hook_Analysis.py`:
- Overview tab - Top hooks + key metrics
- Quadrant tab - Hook Rate vs ROAS scatter plot
- By Type tab - Performance breakdown
- By Visual tab - Visual type breakdown
- By Landing Page tab - Hooks grouped by LP
- Compare tab - Side-by-side comparison

---

## Validation

```bash
# Syntax check passed
python3 -m py_compile viraltracker/services/ad_intelligence/hook_analysis_service.py

# Test script syntax passed
python3 -m py_compile scripts/test_hook_analysis.py
```

---

## Notes for Next Sessions

1. **Service is ready for use** - Agent tools and UI can call methods directly
2. **Test with Wonder Paws** - Brand ID: `bc8461a8-232d-4765-8775-c75eaafc5503`
3. **Lower thresholds for testing** - Use `min_spend=50` and `hook_rate_threshold=0.15` if data is sparse
4. **Landing page queries** - Require both `video_analysis_id` and `landing_page_id` in `ad_creative_classifications`
