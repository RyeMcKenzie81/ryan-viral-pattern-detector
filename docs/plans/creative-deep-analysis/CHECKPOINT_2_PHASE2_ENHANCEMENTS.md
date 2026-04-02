# Checkpoint 2: Phase 2 Enhancements Complete

**Date**: 2026-04-02
**Branch**: `RyeMcKenzie81/creative-correlation-fix` (merged to `main`)
**Status**: Phase 2 fully complete with all enhancements. Ready for Phase 3.

---

## What Was Built (This Session)

### PRs Merged

| PR | Title | What |
|----|-------|------|
| #22 | Correlation engine fixes | `cpa`→`cpm` fix, batch loading fix verified, product filter (URL-based), format filter, `destination_url` migration |
| #24 | Sales/revenue in hook leaderboard | `purchases` + `purchase_value` columns, min impressions/sales filters, sort-by selector |
| #29 | Split video/image leaderboards | Video Hook Leaderboard + Image Messaging Leaderboard (separate sections with format-appropriate metrics) |
| #30 | CTR format fix | `:.2%` → `:.2f%` (was multiplying already-percentage values by 100) |
| #31 | Strategic leverage messaging | Rewrote leverage move descriptions to be clear and actionable, added format badges (🖼️/🎬) |
| #35 | Heatmap cleanup | Proper 2D grid (rows=dimensions, cols=ranked values), 2-column bar chart layout |

### Features Now Live

1. **Video Hook Leaderboard** — Hooks ranked by CTR with hook rate, hold rate, impressions, sales, revenue, ROAS. Ad name + adset/campaign columns.
2. **Image Messaging Leaderboard** — Headlines ranked by CTR with messaging theme, impressions, sales, revenue, ROAS. Ad name + adset/campaign columns.
3. **Filters** — Min impressions, min sales, sort-by (CTR/Impressions/Sales/Revenue/ROAS), format filter (All/Images/Videos), product filter.
4. **Performance Heatmap** — 2D grid with dimensions as rows, values ranked best→worst. Per-dimension bar charts in 2-column layout.
5. **Combination Analysis** — Synergistic pairs of creative elements (e.g., hook_pattern × emotional_tone), min 3 ads per combo.
6. **Winning Recipes** — Top 5 combinations with vs_account_avg ≥ 1.3x, displayed as actionable callouts.
7. **Strategic Leverage Moves** — Creative insight moves with clear messaging ("Your [X] ads get [Y]x more clicks than average — make more of these").

### Bug Fixes

- `cpa` column doesn't exist → changed to `cpm` everywhere
- Supabase 1000-row limit → batch loading by meta_ad_id (fixed in prior session, verified this session)
- CTR callout format `:.2%` multiplied percentage values by 100
- Stuck scheduler job run (`ba8319ab`) manually cleared
- `mean_cpa` removed from `get_top_correlations` select (column doesn't exist)

---

## Architecture Summary

### Service: `CreativeCorrelationService`

```
viraltracker/services/creative_correlation_service.py

Key methods:
├── compute_correlations()      — Groups ads by analysis field values, computes vs_account_avg
├── get_hook_performance()      — Joins hooks/headlines with CTR data, returns ranked list
├── get_top_correlations()      — Reads stored correlations from DB
├── get_combination_performance() — Analyzes pairs of fields for synergistic combos
├── get_product_ad_ids()        — URL-based product→ad mapping via offer variants
└── _load_performance()         — Batch-loads meta_ads_performance with aggregation
```

### Performance Data Flow

```
meta_ads_performance (per day per ad)
    → _load_performance() batches by meta_ad_id (50 per batch)
    → Aggregation: impression-weighted CTR/ROAS/hook_rate/hold_rate, sum purchases/revenue
    → Minimum 100 impressions to qualify
    → Joined with image/video analyses for correlation computation
```

### Key Fields in Performance Aggregation

| Field | Source | Notes |
|-------|--------|-------|
| `link_ctr` | Meta API | Stored as percentage (4.46 = 4.46%), NOT decimal |
| `hook_rate`, `hold_rate` | Meta API | Stored as decimal (0.28 = 28%), converted to % in aggregation |
| `purchases`, `purchase_value` | Meta API | Summed (not averaged) across days |
| `ad_name`, `adset_name`, `campaign_name` | Meta API | Passed through to UI |

### URL-Based Product Mapping

```
product_offer_variants.landing_page_url
    → normalize (strip query params, trailing slash)
    → match against meta_ads_performance.destination_url
    → returns set of meta_ad_ids for that product
```

- Migration `2026-03-31_add_destination_url.sql` added `destination_url TEXT` to `meta_ads_performance`
- `meta_ads_service.py` extracts from `ad_creative.link_data.link` during thumbnail sync
- Requires FB sync to run to backfill existing ads

---

## What's Next: Phase 3

### Meta Demographic Breakdowns (from original plan)
- Age/gender/placement performance analysis
- Requires Meta API breakdowns endpoint (`/insights?breakdowns=age,gender,publisher_platform`)
- Could surface insights like "25-34 female converts 2x better" or "Instagram Stories outperforms Feed by 40%"

### Tech Debt #15: Strategic Messaging Layer
- Extract pain points, JTBDs, objections, benefits per ad via Gemini analysis
- Add to correlation engine for "what to say" insights (not just "how to say it")
- See `docs/TECH_DEBT.md` item #15 for full details

### Pending Verification
- FB sync needs to complete to backfill `destination_url` → then verify product filter works
- Recompute correlations with full dataset (currently 83 images, should be 140+)

---

## Key Files

| File | What Changed |
|------|-------------|
| `viraltracker/services/creative_correlation_service.py` | `cpa`→`cpm`, purchases/revenue aggregation, ad_name/adset/campaign passthrough, URL-based product mapping |
| `viraltracker/ui/pages/38_🔬_Iteration_Lab.py` | Split leaderboards, filters, heatmap 2D grid, CTR format fix |
| `viraltracker/services/account_leverage_service.py` | Clearer leverage move messaging, format badges |
| `viraltracker/services/meta_ads_service.py` | Extract `destination_url` from ad creative during sync |
| `migrations/2026-03-31_add_destination_url.sql` | Added `destination_url TEXT` to `meta_ads_performance` |
| `docs/TECH_DEBT.md` | Added #15: Strategic messaging layer |
