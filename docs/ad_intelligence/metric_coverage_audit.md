# Metric Coverage Audit

> **Purpose**: Map every metric used in the ad intelligence diagnostic system back to its source (database column, API field, or computed value). Identify gaps and known caveats.
>
> **Last Updated**: 2026-02-11

---

## 1. `meta_ads_performance` Table Schema

### 1.1 Core Performance Columns

| Column | Type | Meta API Source | Notes |
|--------|------|-----------------|-------|
| `impressions` | INTEGER | `impressions` | Total impressions for the ad |
| `spend` | NUMERIC(10,2) | `spend` | Amount spent in account currency |
| `reach` | INTEGER | `reach` | Unique users who saw the ad |
| `frequency` | NUMERIC(6,2) | `frequency` | Average times each person saw the ad |
| `link_clicks` | INTEGER | `actions` (type=`link_click`) | Clicks to destination |
| `link_ctr` | NUMERIC(6,4) | `outbound_clicks_ctr` or computed | Click-through rate as a percentage |
| `link_cpc` | NUMERIC(10,4) | `cost_per_outbound_click` or computed | Cost per link click |

### 1.2 Conversion Columns

| Column | Type | Meta API Source | Notes |
|--------|------|-----------------|-------|
| `purchases` | INTEGER | `actions` (type=`purchase`) | Total purchase actions |
| `purchase_value` | NUMERIC(12,2) | `action_values` (type=`purchase`) | Total purchase revenue |
| `roas` | NUMERIC(8,4) | Computed (`purchase_value / spend`) | Return on ad spend |
| `conversion_rate` | NUMERIC(8,6) | Computed (`purchases / link_clicks`) | Purchase conversion rate |
| `add_to_carts` | INTEGER | `actions` (type=`add_to_cart`) | Add-to-cart actions |
| `cost_per_add_to_cart` | NUMERIC(10,4) | Computed (`spend / add_to_carts`) | Cost efficiency for cart adds |
| `initiate_checkouts` | INTEGER | `actions` (type=`initiate_checkout`) | Initiate checkout actions. Added 2026-02-11. |
| `landing_page_views` | INTEGER | `actions` (type=`landing_page_view`) | Landing page view actions. Added 2026-02-11. |
| `content_views` | INTEGER | `actions` (type=`view_content`) | View content actions. Added 2026-02-11. |
| `cost_per_initiate_checkout` | NUMERIC(10,4) | `cost_per_action_type` (type=`initiate_checkout`) | Cost per initiate checkout. Added 2026-02-11. |

### 1.3 Video Metric Columns

| Column | Type | Meta API Field | Notes |
|--------|------|----------------|-------|
| `video_views` | INTEGER | `actions` (type=`video_view`) | 3-second video views. See Section 5 for details on source change. |
| `video_avg_watch_time` | NUMERIC(8,2) | `video_avg_time_watched_actions` | Average seconds watched |
| `video_p25_watched` | INTEGER | `video_p25_watched_actions` | Views reaching 25% of video |
| `video_p50_watched` | INTEGER | `video_p50_watched_actions` | Views reaching 50% of video |
| `video_p75_watched` | INTEGER | `video_p75_watched_actions` | Views reaching 75% of video |
| `video_p100_watched` | INTEGER | `video_p100_watched_actions` | Views reaching 100% of video |
| `video_p95_watched` | INTEGER | `video_p95_watched_actions` | Views reaching 95% of video. Added 2026-02-11. |
| `video_thruplay` | INTEGER | `video_thruplay_watched_actions` | ThruPlay views (15s or full completion). Added 2026-02-11. |

### 1.4 Derived Metric Columns

| Column | Type | Derivation | Notes |
|--------|------|------------|-------|
| `hold_rate` | NUMERIC(10,4) | `video_thruplay / video_views` | Measures ability to retain viewer past the hook (0-1). Added 2026-02-11. |
| `hook_rate` | NUMERIC(10,4) | `video_views / impressions` | Measures ability to stop the scroll (0-1). Added 2026-02-11. |

### 1.5 Raw Data & Metadata Columns

| Column | Type | Notes |
|--------|------|-------|
| `raw_actions` | JSONB | Full `actions` array from Meta API response |
| `raw_costs` | JSONB | Full `cost_per_action_type` array from Meta API response |
| `thumbnail_url` | TEXT | Ad thumbnail (populated by `update_missing_thumbnails` from AdCreative API) |
| `ad_name` | TEXT | Ad name from Meta |
| `meta_campaign_id` | TEXT | Campaign ID for grouping |
| `object_type` | TEXT | AdCreative object_type from Meta API (e.g. VIDEO, SHARE, PHOTO). Added 2026-02-11. Populated by `update_missing_thumbnails`, NOT from Insights API. |

---

## 2. `meta_ad_assets` Table Schema

### 2.1 Asset Pipeline Columns

| Column | Type | Notes |
|--------|------|-------|
| `meta_ad_id` | TEXT | Meta ad ID (part of unique key with `asset_type`) |
| `brand_id` | UUID | Brand this asset belongs to |
| `asset_type` | TEXT | `image` or `video` |
| `storage_path` | TEXT | Supabase Storage path. Empty string for non-downloaded entries. |
| `status` | TEXT | `downloaded`, `not_downloadable`, or `failed` |
| `not_downloadable_reason` | TEXT | Why the asset could not be downloaded. Added 2026-02-11. |

### 2.2 Failure Classification

Assets are classified by failure type to distinguish terminal from retriable errors:

| Failure | Status | Reason Code | Retries? |
|---------|--------|-------------|----------|
| No URL from API (creative has no image) | `not_downloadable` | `no_url_from_api` | No |
| No video source URL (e.g. Reels) | `not_downloadable` | `no_source_url` | No |
| HTTP 403 Forbidden | `not_downloadable` | `http_403` | No |
| HTTP 404 Not Found | `not_downloadable` | `http_404` | No |
| Per-ad creative API error | `failed` | `creative_fetch_failed` | Yes |
| HTTP 429 Rate Limited | `failed` | `http_429` | Yes |
| HTTP 5xx Server Error | `failed` | `http_5xx` | Yes |
| Timeout / network error | `failed` | `download_error` | Yes |

---

## 3. MetaAdsService INSIGHT_FIELDS

The `MetaAdsService` requests the following fields from the Meta Marketing API in its `INSIGHT_FIELDS` configuration:

- `impressions`, `spend`, `reach`, `frequency`
- `actions`, `action_values`, `cost_per_action_type`
- `outbound_clicks`, `outbound_clicks_ctr`, `cost_per_outbound_click`
- `video_play_actions`
- `video_avg_time_watched_actions`
- `video_p25_watched_actions`
- `video_p50_watched_actions`
- `video_p75_watched_actions`
- `video_p100_watched_actions`
- `video_p95_watched_actions` *(added 2026-02-11)*
- `video_thruplay_watched_actions` *(added 2026-02-11)*

### Extraction Logic

- **Simple fields** (`impressions`, `spend`, etc.) are read directly from the API response.
- **Action-based fields** (`purchases`, `link_clicks`, `add_to_carts`, `initiate_checkouts`, `landing_page_views`, `content_views`) are extracted from the `actions` array by matching on `action_type` via `_extract_action()`.
- **Video fields** (`video_p25_watched`, `video_p95_watched`, `video_thruplay`, etc.) are extracted via the `_extract_video_metric` helper, which reads the first entry from the video action array and returns its `value`.
- **Cost fields** (`cost_per_initiate_checkout`) are extracted from `cost_per_action_type` via `_extract_cost()`.
- **Derived fields** (`hold_rate`, `hook_rate`) are computed in `normalize_metrics()` from extracted values.

---

## 4. Diagnostic Rule Metric Mapping

The ad intelligence diagnostic rules reference the following metrics. Each is mapped to its authoritative source.

| Diagnostic Metric | Source | Column / Derivation |
|--------------------|--------|---------------------|
| `link_ctr` | `meta_ads_performance` | `link_ctr` (stored directly) |
| `link_cpc` | `meta_ads_performance` | `link_cpc` (stored directly) |
| `link_clicks` | `meta_ads_performance` | `link_clicks` (stored directly) |
| `impressions` | `meta_ads_performance` | `impressions` (stored directly) |
| `spend` | `meta_ads_performance` | `spend` (stored directly) |
| `frequency` | `meta_ads_performance` | `frequency` (stored directly) |
| `roas` | `meta_ads_performance` | `roas` (stored directly) OR computed via helper as `purchase_value / spend`) |
| `video_3s_views` | `meta_ads_performance` | **Aliased from `video_views`**. See Section 6 for details. |
| `video_p25_watched` | `meta_ads_performance` | `video_p25_watched` (stored directly) |
| `hold_rate` | `meta_ads_performance` | `hold_rate` (stored directly). ThruPlay / 3-sec video views. |
| `hook_rate` | `meta_ads_performance` | `hook_rate` (stored directly). 3-sec video views / impressions. |
| `congruence_score` | `ad_creative_classifications` | `congruence_score` (populated by the creative classifier) |
| `conversions` | `meta_ads_performance` | Extracted from `raw_actions` JSONB via helper functions (typically `purchase` action type) |

### Coverage Status

- **Fully covered (12/13)**: All metrics except `congruence_score` come from `meta_ads_performance`.
- **Cross-table dependency (1/13)**: `congruence_score` requires the creative classification pipeline to have run for the ad. If classification has not been performed, this metric will be NULL and rules referencing it should be skipped gracefully.

---

## 5. Missing Metrics (Not in Current Schema or INSIGHT_FIELDS)

| Metric | Meta API Field | Status | Notes |
|--------|----------------|--------|-------|
| `video_length_seconds` | N/A (not in Insights API) | **Requires separate API call** | Must be fetched from the Ad Creative object, not from the Insights endpoint. Would require a new DB column and a secondary fetch step. |
| `video_p3s_watched` | `video_p3s_watched_actions` | **NOT in INSIGHT_FIELDS** | True "3-second view" count. Currently approximated by `actions["video_view"]`. See Section 6. |

### Previously Missing, Now Implemented (2026-02-11)

The following metrics were listed as missing in v1 and have been implemented:

| Metric | Status | Migration |
|--------|--------|-----------|
| `video_p95_watched` | Now in INSIGHT_FIELDS + DB column | `2026-02-11_asset_pipeline_and_metrics.sql` |
| `video_thruplay` | Now in INSIGHT_FIELDS + DB column | `2026-02-11_asset_pipeline_and_metrics.sql` |
| `hold_rate` | Derived metric, stored in DB | Computed as `video_thruplay / video_views` |
| `hook_rate` | Derived metric, stored in DB | Computed as `video_views / impressions` |
| `initiate_checkouts` | Extracted from `actions` array | `2026-02-11_asset_pipeline_and_metrics.sql` |
| `landing_page_views` | Extracted from `actions` array | `2026-02-11_asset_pipeline_and_metrics.sql` |
| `content_views` | Extracted from `actions` array | `2026-02-11_asset_pipeline_and_metrics.sql` |
| `cost_per_initiate_checkout` | Extracted from `cost_per_action_type` | `2026-02-11_asset_pipeline_and_metrics.sql` |

### Impact of Remaining Missing Metrics

- **`video_length_seconds`**: Required to compute normalized watch-time rates (e.g., "average % of video watched"). Without it, we can only use the percentile columns for retention analysis. Medium priority.
- **`video_p3s_watched`**: Would provide the exact Meta "3-second view" count vs the current `actions["video_view"]` approximation. See Section 6 for details. Low-medium priority.

---

## 6. `video_views` Source and Hook Rate

### Current Implementation (Post-CHECKPOINT_08 Fix)

`video_views` is now sourced from `_extract_action(insight, "video_view")`, which extracts from the `actions` array with `action_type = "video_view"`. This is Meta's 3-second video view count — the number of times a video was watched for at least 3 seconds.

> **Note**: This was fixed in CHECKPOINT_08 (see `docs/plans/deep-video-analysis/CHECKPOINT_08_BUGFIXES.md`). Previously, `video_views` was incorrectly sourced from `video_play_actions` (play initiations, which approach ~100% with autoplay), which broke hook rate calculations.

### Derived Metrics Using `video_views`

- **`hook_rate`** = `video_views / impressions` — Measures ability to stop the scroll (0-1). Stored in `meta_ads_performance.hook_rate`.
- **`hold_rate`** = `video_thruplay / video_views` — Measures ability to retain viewer past the hook (0-1). Stored in `meta_ads_performance.hold_rate`.

Both are computed in `normalize_metrics()` with proper null/zero guards (division by zero returns `None`, zero numerator with nonzero denominator returns `0.0`).

### True "3-Second View" vs `actions["video_view"]`

Meta also provides `video_p3s_watched_actions` as a separate insight field specifically for "true" 3-second views. The `actions["video_view"]` value is a close equivalent per Meta's API definition, but `video_p3s_watched_actions` could provide marginally higher precision. This can be added as a future enhancement by adding it to `INSIGHT_FIELDS` and creating a dedicated `video_3s_views` column.

---

## 7. Asset Pipeline & Object Type

### `object_type` Column

The `object_type` column on `meta_ads_performance` stores the AdCreative object type from the Meta API (e.g., `VIDEO`, `SHARE`, `PHOTO`). This is fetched via the AdCreative API in `_fetch_thumbnails_sync()`, NOT from the Insights API.

**Key behaviors**:
- `_fetch_thumbnails_sync()` always returns entries with `fetch_ok=True` when the creative API succeeds, even if `thumbnail_url` is `None`.
- `update_missing_thumbnails()` queries for rows missing `thumbnail_url` OR missing `object_type`, and updates without clobbering existing non-null thumbnails.
- The classifier uses `object_type` in skip logging to help diagnose why an ad has no image.

### Video/Image Partitioning

The download pipeline uses set subtraction to determine image candidates:
- **Video ads**: Any ad with `is_video=true` on ANY row, OR `meta_video_id` not null, OR `object_type` containing `VIDEO`.
- **Image ads**: All unique ad IDs minus the video set.

This prevents video ads with incomplete metadata from leaking into the image download path.

---

## 8. Backfill

### `backfill_expanded_metrics()`

For existing data, the following columns can be backfilled from `raw_actions` and `raw_costs` JSONB without re-syncing from Meta:

| Column | Backfill Source | Available? |
|--------|----------------|------------|
| `initiate_checkouts` | `raw_actions` JSONB | Yes |
| `landing_page_views` | `raw_actions` JSONB | Yes |
| `content_views` | `raw_actions` JSONB | Yes |
| `cost_per_initiate_checkout` | `raw_costs` JSONB | Yes |
| `hook_rate` | Computed from existing `video_views` + `impressions` | Yes |

The following require a fresh Meta API sync (not in stored JSONB):

| Column | Why Not Backfillable |
|--------|---------------------|
| `video_p95_watched` | `video_p95_watched_actions` is an insight-level field, not in `raw_actions` |
| `video_thruplay` | `video_thruplay_watched_actions` is an insight-level field, not in `raw_actions` |
| `hold_rate` | Requires `video_thruplay` which needs fresh sync |

---

## 9. Summary

### What We Have

- Full coverage of core spend/engagement metrics (impressions, spend, reach, frequency, clicks, CTR, CPC)
- Full coverage of conversion metrics (purchases, purchase_value, ROAS, conversion_rate, add_to_carts)
- E-commerce funnel metrics (initiate_checkouts, landing_page_views, content_views, cost_per_initiate_checkout)
- Video retention at 25/50/75/95/100 percentile breakpoints
- Video ThruPlay (15s or completion)
- Derived engagement rates (hook_rate, hold_rate)
- 3-second video views (from `actions["video_view"]`)
- Raw action/cost JSON for ad-hoc extraction of any action type
- Congruence score from creative classification (cross-table)
- Asset download failure tracking with reason codes
- AdCreative `object_type` for ad format identification

### Remaining Enhancements

| Enhancement | Effort | Priority |
|-------------|--------|----------|
| Add `video_p3s_watched_actions` to INSIGHT_FIELDS + new column | Low | Low-Medium (marginal improvement over `actions["video_view"]`) |
| Fetch `video_length_seconds` from Creative API + new column | Medium | Medium |
