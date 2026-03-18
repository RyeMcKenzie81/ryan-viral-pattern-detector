# Keyword Data Enrichment — Checkpoint

**Date**: 2026-03-18
**Branch**: feat/ad-creator-v2-phase0
**Commit**: 6fcae7d

## What's Done

### Phase 1: DataForSEO Service Upgrade
- ✅ Switched from clickstream to Google Ads endpoint (`keywords_data/google_ads/search_volume/live`)
- ✅ Added `_clickstream_fallback()` — automatic fallback for child-related keywords blocked by Google Ads
- ✅ Added `_normalize_competition()` — maps Google Ads string ("LOW"/"MEDIUM"/"HIGH") to float (0.33/0.66/1.0)
- ✅ Added `enrich_keywords_google_ads()` with clickstream fallback
- ✅ Added `get_keyword_suggestions()` — keyword expansion via DataForSEO Labs
- ✅ Fixed keyword parsing: `item["keyword"]` not `kw_info.get("keyword")`
- ✅ Added `enrich_with_cache()` — 7-day DB cache with force-refresh option

### Phase 2: Cluster Research Enrichment
- ✅ Pre-cluster enrichment switched to `enrich_with_cache()`
- ✅ Fixed key mismatch: `search_volume`/`keyword_difficulty` keys (was `volume`/`kd`)
- ✅ Post-cluster enrichment: enriches pillar + spoke keywords, merges vol/KD/CPC/competition/intent
- ✅ Cluster-level aggregates: `total_volume`, `avg_difficulty`, `estimated_traffic`
- ✅ Removed `estimated_difficulty` from Claude prompt (real data now)

### Phase 3: UI — Cluster Data Display
- ✅ Cluster header metrics: total volume, color-coded avg KD, est traffic, spoke count
- ✅ Expandable keyword data table per cluster with pandas DataFrame
- ✅ Color-coded KD column (green <30, yellow 30-60, red >60)
- ✅ Competition display handles both string and float values

### Phase 4: Keyword Explorer Tab
- ✅ Third tab added: "Keyword Explorer"
- ✅ Seed input, DataForSEO suggestions, summary metrics
- ✅ Filters: volume range, KD range, intent
- ✅ Sortable DataFrame with color-coded KD
- ✅ "Add to Cluster Research Seeds" and "Save to Project" action buttons

### Phase 5: Cache
- ✅ Migration written: `migrations/2026-03-18_seo_keyword_metrics_cache.sql`
- ✅ `enrich_with_cache()` with 7-day freshness + force-refresh
- ✅ Force-refresh checkbox in cluster builder UI

### Critical Discovery: Google Ads Child Keyword Restriction
- Google Ads blocks volume/CPC/competition for keywords containing "kids", "children", "baby", "babies"
- ALL DataForSEO Labs endpoints inherit this restriction (null metrics)
- **Clickstream bulk** (`keywords_data/clickstream_data/bulk_search_volume/live`) is the only endpoint with data
- Clickstream volumes are ~30-70% of Google Ads numbers but better than nothing
- Implemented automatic clickstream fallback in all enrichment methods

## Post-Plan Review Findings (Blocking)

1. **G2**: Bare `except Exception: pass` in UI keyword save loop — needs logging
2. **G3**: Raw DB query + private method call in UI "Save to Project" — needs service method
3. **T1**: No unit tests for `dataforseo_service.py` (7 methods)
4. **Phase 3.3 partial**: No explicit opportunity badge (green/yellow/red icons)
5. **Phase 4.3 partial**: Missing CPC range slider and word count filter

## Pending

- [ ] Fix G2: Add logging to save loop
- [ ] Fix G3: Extract save-to-project into service method
- [ ] Create `tests/test_dataforseo_service.py`
- [ ] Add opportunity badges to cluster headers
- [ ] Add CPC + word count filters to explorer
- [ ] Run migration on Supabase
- [ ] Deploy to Railway and test full flow
