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

### 3. Follow-up Fixes (Ad Performance page)

- **None ad_status fix**: `d.get("ad_status", "")` returns `None` when key exists with null value. Changed to `(d.get("ad_status") or "")`.
- **Facebook Ads Manager links**: Added `_ads_manager_url()` helper and ↗ links next to each ad name in Top/Bottom Performers. Links open the ad directly in Facebook Ads Manager.
- **Bracket escaping**: Ad names like `[video][Silja]` broke markdown link syntax. Escaped with backslashes.
- **Correct domain**: Changed from `www.facebook.com` to `adsmanager.facebook.com` (the former ignores `act=` parameter).
- **Per-row account ID**: Used `meta_ad_account_id` from the performance data row (from Meta sync) instead of the brand-level `brand_ad_accounts` table, which had a stale/wrong ID for Wonder Paws.
- **Preserve account ID in aggregation**: Added `meta_ad_account_id` to `aggregate_by_ad()` output so it survives aggregation.

### 4. Known Issue Discovered

**Purchase data sync gap**: Wonder Paws ads show 0 purchases/ROAS in our system but have purchases in Facebook Ads Manager. Root cause: Meta returns purchases under `action_type: "omni_purchase"` but our sync only extracts `action_type: "purchase"`. The Ads Manager URL confirms this with `actions:omni_purchase` column. This is a pre-existing sync bug — needs separate fix + data re-sync.

## Files Modified

| File | Change |
|------|--------|
| `viraltracker/services/ad_intelligence/baseline_service.py` | Refactored `_compute_cohort_baseline()` metric aggregation |
| `viraltracker/ui/pages/30_📈_Ad_Performance.py` | Deep analysis expandables, Ads Manager links, null safety fixes, aggregate_by_ad account ID, performance window selector, fixed active-ad filter, guarded ad_status, removed dead fields |
| `viraltracker/services/models.py` | Added `campaign_name` and `thumbnail_url` to `MetaAdPerformance` |
| `docs/TECH_DEBT.md` | Moved #8 to Completed, updated #10 as partial |
| `docs/checkpoints/CHECKPOINT_2026-02-05_baseline_and_video_ui.md` | This file |

### 5. Top/Bottom Performers Window Fix

**Problem**: Top/Bottom Performers showed different results than Facebook Ads Manager due to two bugs:
1. **Active-ad filter discarded multi-day data** — `ad_status` is only populated on the most recent sync day; older rows have `ad_status = null` and were excluded, so aggregation used a single day's data.
2. **No configurable performance window** — users couldn't control the aggregation window (7/14/30 days) to match their Ads Manager view.

**Fixes applied**:
- **Performance window selector** (7/14/30 days, default 7) — computes `window_cutoff` from max date and filters rows
- **Fixed active-ad filter** — scans ALL data to find each ad's latest `ad_status`, determines "recent activity" (last 3 days), includes all windowed rows for active ads
- **Consolidated `max_date_dt` scoping** — parsed once before both window and filter blocks instead of fragile nested try/except
- **Guarded `ad_status` in `aggregate_by_ad`** — keeps first (most recent) non-empty value instead of letting older rows overwrite
- **Removed dead fields** from `aggregate_by_ad` output — `image_url`, `headline`, `body` were never in DB schema
- **Added `campaign_name` and `thumbnail_url`** to `MetaAdPerformance` Pydantic model to match DB schema

**Tech debt noted** (not fixed here): Business logic functions (`aggregate_by_ad`, `get_top_performers`, `get_worst_performers`) live in UI page file; should be in a service.

## Verification Results

1. **CPC Baseline** — Confirmed fixed. Infi p75 CPC: $4.96 (was inflated). Wonder Paws p75 CPC: $1.80 (was $79.58).
2. **Deep Analysis UI** — Confirmed working. Classification, congruence, hooks, transcript, storyboard all display.
3. **Ads Manager Links** — Confirmed working with correct account after per-row fix.
4. **Diagnostic Engine** — Confirmed still flags appropriate ads with corrected baselines.
5. **Top/Bottom Performers** — Window selector added; active-ad filter uses multi-day data; `ad_status` preserved correctly in aggregation.
