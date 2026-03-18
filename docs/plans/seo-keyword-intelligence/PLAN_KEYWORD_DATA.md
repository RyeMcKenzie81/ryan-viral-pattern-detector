# Keyword Data Enrichment & Explorer

**Status**: Planning
**Branch**: feat/ad-creator-v2-phase0
**Date**: 2026-03-18

## Problem

Cluster research shows no real keyword data because:
1. **Wrong API endpoint**: Using DataForSEO's `clickstream_data/bulk_search_volume` which only covers popular keywords. Returns data for ~3% of our long-tail niche keywords.
2. **No post-cluster enrichment pipeline**: Even when data exists, Claude's spoke keywords may not match the enriched input keywords.
3. **No keyword exploration tool**: Users can't browse keyword data to find opportunities before building clusters.

## Solution — Two Features

### Feature A: Fix Cluster Data Enrichment

Switch from clickstream to **Google Ads Search Volume** endpoint (`keywords_data/google/search_volume/live`) which uses Google Keyword Planner data — much broader coverage for long-tail keywords. Add expandable data tables per cluster in the UI.

### Feature B: Keyword Explorer Tab

New "Keyword Explorer" tab in SEO Workflow page. Enter seed keywords → DataForSEO keyword_suggestions returns hundreds of related keywords with vol/KD/CPC/competition → filter/sort table → select keywords to add to clusters or save.

---

## Phase 1: DataForSEO Service Upgrade

### 1.1 Switch search volume endpoint

**File**: `viraltracker/services/seo_pipeline/services/dataforseo_service.py`

Change `enrich_keywords_bulk()` to use Google Ads endpoint instead of clickstream:

| Current | New |
|---------|-----|
| `keywords_data/clickstream_data/bulk_search_volume/live` | `keywords_data/google/search_volume/live` |
| 1,000 keywords/request | 700 keywords/request |
| Clickstream panel data (poor long-tail coverage) | Google Keyword Planner data (broad coverage) |

Response fields from Google Ads endpoint:
- `search_volume` (int) — monthly average
- `cpc` (float) — average cost per click in USD
- `competition` (float) — 0.0-1.0 competition level
- `monthly_searches` (array) — 12-month history

Also return `cpc` and `competition` from the new endpoint (currently only returning volume).

### 1.2 Add keyword suggestions method

**File**: `viraltracker/services/seo_pipeline/services/dataforseo_service.py`

New method: `get_keyword_suggestions(seed, limit=100, location_code=2840, language_code="en")`

Endpoint: `dataforseo_labs/google/keyword_suggestions/live`

Returns per keyword:
- `keyword` (str)
- `search_volume` (int) — from `keyword_info.search_volume`
- `cpc` (float) — from `keyword_info.cpc`
- `competition` (float) — from `keyword_info.competition`
- `keyword_difficulty` (int) — from `keyword_properties.keyword_difficulty`
- `search_intent` (str) — from `search_intent_info.main_intent`

This single endpoint returns volume, CPC, competition, KD, AND intent — no need for separate KD call.

### 1.3 Add bulk enrichment with Google Ads data

New method: `enrich_keywords_google_ads(keywords, location_code=2840, language_code="en")`

Uses `keywords_data/google/search_volume/live` for up to 700 keywords.
Returns: `[{keyword, search_volume, cpc, competition}, ...]`

Keep `enrich_keywords_bulk()` working as-is (it's used elsewhere) but add the new method for the cluster research flow.

---

## Phase 2: Cluster Research Enrichment Fix

### 2.1 Post-cluster spoke enrichment

**File**: `viraltracker/services/seo_pipeline/services/seo_workflow_service.py`

In `_deep_cluster_research()`, after Claude returns clusters:
1. Collect all spoke keywords from all clusters
2. Call new `enrich_keywords_google_ads()` (up to 700 spokes)
3. Call `bulk_keyword_difficulty` for KD scores
4. Merge vol/KD/CPC/competition into each spoke dict
5. Calculate `estimated_monthly_traffic` per spoke: `search_volume * ctr_estimate(position_target=5)` where CTR for position 5 ≈ 5%
6. Calculate cluster-level totals: `total_volume`, `avg_difficulty`, `total_estimated_traffic`

### 2.2 Pre-cluster input enrichment

Also enrich the INPUT keywords before sending to Claude (already attempted, but switch to Google Ads endpoint). Include vol/KD in the prompt so Claude makes better clustering decisions.

### 2.3 Remove `estimated_difficulty` from Claude prompt

Stop asking Claude to guess difficulty. We have real data now — just ask for clustering/angles/priority order.

---

## Phase 3: UI — Cluster Data Display

**File**: `viraltracker/ui/pages/53_🚀_SEO_Workflow.py`

### 3.1 Cluster header metrics

For each cluster card, add summary metrics below the score:

```
Score: 0.9 | Summary: ...
📊 Total Volume: 4,200/mo | Avg KD: 32 | Est. Traffic: 210/mo | Spokes: 9
```

### 3.2 Expandable keyword data table

Replace the bullet list of spokes with a compact display + expandable table:

**Default view** (collapsed): Same as now — keyword + angle, but with vol/KD inline:
```
• best games for young kids — Age-segmented recommendations (vol: 480, KD: 22)
• gaming chair worth it for kids — Ergonomic discussion (vol: 320, KD: 18)
```

**Expanded view** (via expander): Full `st.dataframe` table with columns:
| Keyword | Volume | KD | CPC | Competition | Est. Traffic | Intent |
|---------|--------|----|-----|-------------|-------------|--------|
| best games for young kids | 480 | 22 | $0.45 | 0.12 | 24/mo | commercial |

Sortable by any column. Color-code KD: green (<30), yellow (30-60), red (>60).

### 3.3 Cluster-level opportunity badge

Add visual badge based on aggregated data:
- 🟢 **High Opportunity**: high total volume + low avg KD
- 🟡 **Medium Opportunity**: moderate volume or moderate KD
- 🔴 **Competitive**: high avg KD regardless of volume

---

## Phase 4: Keyword Explorer Tab

**File**: `viraltracker/ui/pages/53_🚀_SEO_Workflow.py`

### 4.1 New tab: "Keyword Explorer"

Add third tab alongside "Quick Write" and "Cluster Builder":

```python
tab_write, tab_cluster, tab_explorer = st.tabs(["Quick Write", "Cluster Builder", "Keyword Explorer"])
```

### 4.2 Explorer UI flow

1. **Input**: Text area for seed keywords (1 per line, max 10)
2. **Button**: "Explore Keywords"
3. **Processing**: For each seed, call `dataforseo.get_keyword_suggestions(seed, limit=200)`
4. **Results table**: `st.dataframe` with columns:
   - Keyword, Volume, KD, CPC, Competition, Intent, Source Seed
   - Sortable, filterable
   - Color-coded KD column
5. **Summary stats** above table:
   - Total keywords found
   - Volume range (min-max)
   - KD distribution (% easy/medium/hard)
6. **Actions**:
   - Checkbox column to select keywords
   - "Add to Cluster Research" button → pushes selected keywords into the cluster builder seeds
   - "Save to Project" button → saves selected keywords to `seo_keywords` table with vol/KD

### 4.3 Filters sidebar

Within the explorer results:
- Volume range slider (min-max)
- KD range slider (0-100)
- CPC range slider
- Intent filter (informational, commercial, transactional, navigational)
- Min word count filter

---

## Phase 5: Keyword Metrics Cache (DB)

### 5.1 Problem

DataForSEO calls cost money. The same keyword may be queried multiple times across cluster research runs, explorer sessions, and enrichment flows. We should cache keyword metrics in the DB with a freshness timestamp and skip re-fetching if data is fresh (< 7 days).

### 5.2 Schema changes

**Extend `seo_keywords` table** (existing columns: `search_volume`, `keyword_difficulty`, `search_intent`):

```sql
ALTER TABLE seo_keywords ADD COLUMN IF NOT EXISTS cpc FLOAT;
ALTER TABLE seo_keywords ADD COLUMN IF NOT EXISTS competition FLOAT;
ALTER TABLE seo_keywords ADD COLUMN IF NOT EXISTS metrics_refreshed_at TIMESTAMPTZ;
```

**New table `seo_keyword_metrics_cache`** — for keywords NOT yet in `seo_keywords` (transient explorer/research data):

```sql
CREATE TABLE IF NOT EXISTS seo_keyword_metrics_cache (
    keyword TEXT NOT NULL,
    location_code INT NOT NULL DEFAULT 2840,
    search_volume INT,
    keyword_difficulty FLOAT,
    cpc FLOAT,
    competition FLOAT,
    search_intent TEXT,
    refreshed_at TIMESTAMPTZ DEFAULT NOW(),
    PRIMARY KEY (keyword, location_code)
);
```

This is a simple lookup cache keyed on `(keyword, location_code)`. No foreign keys — any keyword from any context can be cached here.

### 5.3 Cache-aware enrichment flow

In `DataForSEOService`, add `enrich_with_cache()`:

1. **Check cache**: For each keyword, look up in `seo_keyword_metrics_cache` where `refreshed_at > NOW() - INTERVAL '7 days'`
2. **Partition**: Split into `cached` (have fresh data) and `stale` (need API call)
3. **Fetch stale**: Call Google Ads endpoint only for stale keywords
4. **Store**: Upsert results into `seo_keyword_metrics_cache`
5. **Return**: Merge cached + fresh results

The 7-day freshness window is the default. The caller can pass `force_refresh=True` to bypass the cache entirely.

### 5.4 UI override

In both the cluster research and keyword explorer UIs, add a checkbox:
```
☐ Force refresh keyword data (bypasses 7-day cache)
```

Default unchecked. When checked, all keywords get re-fetched from DataForSEO regardless of cache age.

---

## File Changes Summary

| File | Change |
|------|--------|
| `dataforseo_service.py` | Add `enrich_keywords_google_ads()`, `get_keyword_suggestions()`, `enrich_with_cache()` |
| `seo_workflow_service.py` | Switch enrichment to Google Ads endpoint, use cache, add cluster-level metrics |
| `53_🚀_SEO_Workflow.py` | Expandable data tables, cluster metrics, Keyword Explorer tab, force-refresh checkbox |
| **Migration** | Add `cpc`, `competition`, `metrics_refreshed_at` to `seo_keywords`; create `seo_keyword_metrics_cache` table |

---

## Cost Estimate

Per cluster research run (assuming ~50 spoke keywords):
- Google Ads search volume: 1 request (up to 700 kw) ≈ $0.05
- Keyword difficulty: 1 request ≈ $0.02
- Total: ~$0.07 per run

Per keyword explorer session (5 seeds × 200 suggestions):
- Keyword suggestions: 5 requests ≈ $0.50
- Total: ~$0.50 per exploration

---

## Implementation Order

1. Phase 1 (Service) → test with script
2. Phase 2 (Enrichment) → test cluster research sees data
3. Phase 3 (UI tables) → visual QA
4. Phase 4 (Explorer) → full QA

Each phase gets a `py_compile` check and manual verification before moving to the next.
