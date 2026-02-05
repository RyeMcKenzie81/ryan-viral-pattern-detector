# Checkpoint: CPC Baseline Fix + Ad Performance Video Analysis UI

**Date**: 2026-02-05
**Branch**: `feat/veo-avatar-tool`

## Changes

### 1. CPC Baseline Fix (baseline_service.py)

**Problem**: `_compute_cohort_baseline()` used per-row daily values for CPC, CPM, CTR, cost-per-purchase, and cost-per-ATC. On low-volume days (1 click, $80 spend), `link_cpc` = $80, inflating p75 baselines to ~$79 when actual aggregate CPC was ~$2.

**Fix**: Refactored to aggregate raw counts per-ad first, then compute derived ratios from totals:
- CPC = total_spend / total_link_clicks (per ad)
- CPM = (total_spend / total_impressions) * 1000 (per ad)
- CTR = total_link_clicks / total_impressions (per ad)
- Cost per purchase = total_spend / total_conversions (per ad)
- Cost per ATC = total_spend / total_add_to_carts (per ad)
- ROAS = total_conversion_value / total_spend (per ad)
- Conversion rate = total_conversions / total_clicks * 100 (per ad)
- Frequency = average of daily values per ad

**Not changed** (already correct): Video metrics (hook_rate, hold_rate, completion_rate) were already computed from raw counts.

### 2. Ad Performance Deep Analysis UI (30_Ad_Performance.py)

**Added**:
- `_fetch_batch_deep_analysis()` — batch fetches classification + video analysis for a list of ads in 2 queries (avoids N+1)
- `_render_ad_deep_analysis()` — renders expandable section with:
  - Classification summary (awareness level, format, congruence score)
  - Per-dimension congruence breakdown with aligned/weak/missing indicators
  - Hook analysis (spoken, overlay, type, visual type)
  - Benefits and angles
  - Claims with proof indicators
  - Collapsible transcript and storyboard
- Wired into both Top Performers and Bottom Performers sections

**Cleanup**: Removed DEBUG st.write statements from the existing analyze strategy section.

## Files Modified

| File | Change |
|------|--------|
| `viraltracker/services/ad_intelligence/baseline_service.py` | Refactored `_compute_cohort_baseline()` metric aggregation |
| `viraltracker/ui/pages/30_📈_Ad_Performance.py` | Added deep analysis helpers + expandable sections |
| `docs/TECH_DEBT.md` | Moved #8 to Completed, updated #10 as partial |
| `docs/checkpoints/CHECKPOINT_2026-02-05_baseline_and_video_ui.md` | This file |

## Verification Needed After Deploy

1. Re-run baseline computation for a brand — verify p75_cpc is ~$2-5 (not ~$79)
2. Navigate to Ad Performance > Charts & Analysis > Top/Bottom Performers
3. Expand "Deep Analysis" for a video ad — verify classification, congruence, hooks show
4. Verify diagnostic engine still flags appropriate ads with corrected baselines
