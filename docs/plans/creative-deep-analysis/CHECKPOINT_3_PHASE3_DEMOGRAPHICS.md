# Checkpoint 3: Phase 3 — Meta Demographic Breakdowns

**Date**: 2026-04-02
**Branch**: `RyeMcKenzie81/creative-correlation-fix`
**Status**: Implementation complete, ready for testing.

---

## What Was Built

### New Table: `meta_ads_demographic_performance`

- **Migration**: `migrations/2026-04-02_meta_ads_demographic_performance.sql`
- Stores per-ad daily performance broken down by demographics (age/gender) and placement (platform/position)
- Two breakdown types: `age_gender` and `placement`
- Composite unique constraint on `(meta_ad_id, date, breakdown_type, age_range, gender, publisher_platform, platform_position)`
- Uses empty strings (not NULLs) for unused dimension columns to ensure UNIQUE works with Supabase upsert

### Meta API Breakdown Fetching

**File**: `viraltracker/services/meta_ads_service.py`

- `BREAKDOWN_INSIGHT_FIELDS` — subset of insight fields (no video detail metrics)
- `_fetch_breakdown_insights_sync()` — low-level SDK call with `breakdowns` param
- `get_ad_insights_with_breakdowns(brand_id, days_back)` — makes 2 API calls:
  - Call 1: `breakdowns=["age", "gender"]` → age×gender cross-product
  - Call 2: `breakdowns=["publisher_platform", "platform_position"]` → placement combos
  - Reuses existing rate limiting, retry/backoff, and metric normalization
  - Returns `{"age_gender": [...], "placement": [...]}`
- `sync_demographic_performance_to_db(breakdown_data, brand_id)` — upserts breakdown rows

### Scheduler Integration

**File**: `viraltracker/worker/scheduler_worker.py`

- Added **Step 4.7** in `execute_meta_sync_job()` between destination URL fetch (Step 4.5) and auto-classify (Step 5)
- Non-fatal: wrapped in try/except, logs warning on failure, job continues
- Dataset freshness tracking via `freshness.record_start/success/failure`
- Optional `skip_demographics` param to disable
- Rate limit impact: +2 API calls per sync (~1.2s added delay)

### Demographic Analysis Service

**New file**: `viraltracker/services/demographic_analysis_service.py`

- `get_demographic_performance(brand_id, breakdown_type, days_back, product_id)` — aggregates breakdown data across all ads, computes impression-weighted CTR/ROAS and vs_account_avg
- `get_top_segments(brand_id, days_back, metric, limit, product_id)` — top-performing segments across both breakdown types with human-readable labels
- `get_creative_demographic_cross(brand_id, analysis_field, breakdown_type, days_back, product_id)` — crosses creative elements with demographics for matrix heatmap visualization
- Product filtering via `CreativeCorrelationService.get_product_ad_ids()`

### UI: Demographic Performance Section

**File**: `viraltracker/ui/pages/38_🔬_Iteration_Lab.py`

Added to Creative Intelligence tab (Tab 5), between Creative Combinations and Recompute button:

1. **Headline Insights** — Top 3 outperforming segments as green callouts
2. **Age × Gender Heatmap** — Plotly heatmap with metric toggle (ROAS/CTR/Spend), red/white/green color scale centered at 1.0x
3. **Placement Performance Bar Chart** — Horizontal bars sorted by vs_account_avg, green/yellow/red coloring
4. **Creative × Demographic Cross-Analysis** — Expander with selectboxes for creative dimension and demographic dimension, generates cross-analysis heatmap on button click
5. **30-minute caching** — Same session state pattern as rest of tab

---

## Key Design Decisions

| Decision | Rationale |
|----------|-----------|
| Separate table (not columns on `meta_ads_performance`) | Breakdown rows have different cardinality (N rows per ad per day vs. 1) |
| 2 API calls (age+gender, platform+position) | Age×gender cross-product is natively useful; combining all would create too many rows |
| Empty strings for unused dimensions | PostgreSQL UNIQUE treats NULLs as distinct — empty strings work with Supabase upsert |
| New service (not extending CreativeCorrelationService) | Different data source and aggregation logic; single responsibility |
| Non-fatal scheduler step | Don't break existing meta_sync if demographics API fails |

---

## Pending

- [ ] **Run migration** on Supabase: `migrations/2026-04-02_meta_ads_demographic_performance.sql`
- [ ] **Trigger meta_sync** to populate demographic data (will auto-run Step 4.7)
- [ ] **Verify UI** — check Iteration Lab → Creative Intelligence → Demographic Performance section
- [ ] **Test edge cases**: brand with no demographic data, single-segment data, product filter

---

## Key Files

| File | What Changed |
|------|-------------|
| `migrations/2026-04-02_meta_ads_demographic_performance.sql` | **NEW** — table + indexes |
| `viraltracker/services/meta_ads_service.py` | `BREAKDOWN_INSIGHT_FIELDS`, `get_ad_insights_with_breakdowns()`, `sync_demographic_performance_to_db()` |
| `viraltracker/services/demographic_analysis_service.py` | **NEW** — 3 analysis methods |
| `viraltracker/worker/scheduler_worker.py` | Step 4.7 (non-fatal demographic sync) |
| `viraltracker/ui/pages/38_🔬_Iteration_Lab.py` | Demographic Performance section in Creative Intelligence tab |
