# Metric Coverage Audit

> **Purpose**: Map every metric used in the ad intelligence diagnostic system back to its source (database column, API field, or computed value). Identify gaps and known caveats.
>
> **Last Updated**: 2026-02-02

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

### 1.3 Video Metric Columns

| Column | Type | Meta API Field | Notes |
|--------|------|----------------|-------|
| `video_views` | INTEGER | `video_play_actions` | Extracted via `_extract_video_metric`. See Section 5 for caveat. |
| `video_avg_watch_time` | NUMERIC(8,2) | `video_avg_time_watched_actions` | Average seconds watched |
| `video_p25_watched` | INTEGER | `video_p25_watched_actions` | Views reaching 25% of video |
| `video_p50_watched` | INTEGER | `video_p50_watched_actions` | Views reaching 50% of video |
| `video_p75_watched` | INTEGER | `video_p75_watched_actions` | Views reaching 75% of video |
| `video_p100_watched` | INTEGER | `video_p100_watched_actions` | Views reaching 100% of video |

### 1.4 Raw Data & Metadata Columns

| Column | Type | Notes |
|--------|------|-------|
| `raw_actions` | JSONB | Full `actions` array from Meta API response |
| `raw_costs` | JSONB | Full `cost_per_action_type` array from Meta API response |
| `thumbnail_url` | TEXT | Ad thumbnail (added post-launch) |
| `ad_name` | TEXT | Ad name from Meta |
| `meta_campaign_id` | TEXT | Campaign ID for grouping |

---

## 2. MetaAdsService INSIGHT_FIELDS

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

### Extraction Logic

- **Simple fields** (`impressions`, `spend`, etc.) are read directly from the API response.
- **Action-based fields** (`purchases`, `link_clicks`, `add_to_carts`) are extracted from the `actions` array by matching on `action_type`.
- **Video fields** are extracted via the `_extract_video_metric` helper, which reads the first entry from the video action array and returns its `value`.

---

## 3. Diagnostic Rule Metric Mapping

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
| `video_3s_views` | `meta_ads_performance` | **Aliased from `video_views`**. See Section 5 for important caveat. |
| `video_p25_watched` | `meta_ads_performance` | `video_p25_watched` (stored directly) |
| `congruence_score` | `ad_creative_classifications` | `congruence_score` (populated by the creative classifier) |
| `conversions` | `meta_ads_performance` | Extracted from `raw_actions` JSONB via helper functions (typically `purchase` action type) |

### Coverage Status

- **Fully covered (10/11)**: All metrics except `congruence_score` come from `meta_ads_performance`.
- **Cross-table dependency (1/11)**: `congruence_score` requires the creative classification pipeline to have run for the ad. If classification has not been performed, this metric will be NULL and rules referencing it should be skipped gracefully.

---

## 4. Missing Metrics (Not in Current Schema or INSIGHT_FIELDS)

The following metrics have been discussed in planning but are **not currently collected or stored**:

| Metric | Meta API Field | Status | Notes |
|--------|----------------|--------|-------|
| `video_p95_watched` | `video_p95_watched_actions` | **NOT in INSIGHT_FIELDS** | Would require adding to API request and a new DB column |
| `video_thruplay_watched` | `video_thruplay_watched_actions` | **NOT in INSIGHT_FIELDS** | ThruPlay = views to 97% or 15s (whichever comes first). Would require adding to API request and a new DB column |
| `video_length_seconds` | N/A (not in Insights API) | **Requires separate API call** | Must be fetched from the Ad Creative object, not from the Insights endpoint. Would require a new DB column and a secondary fetch step. |

### Impact of Missing Metrics

- **`video_p95_watched`**: Would improve drop-off analysis granularity between p75 and p100. Low priority for v1.
- **`video_thruplay_watched`**: Industry-standard completion metric. Useful for benchmarking but not required for current diagnostic rules. Medium priority for v2.
- **`video_length_seconds`**: Required to compute normalized watch-time rates (e.g., "average % of video watched"). Without it, we can only use the percentile columns for retention analysis. Medium priority for v2.

---

## 5. `video_3s_views` Validation and Caveat

### What Meta Actually Returns

The Meta Marketing API field `video_play_actions` is documented as:

> "The number of times your video starts to play. This is counted for each impression of a video, and excludes replays."

This is a **video play initiation** metric, not a "3-second view" metric.

### The "3-Second View" Distinction

The true "3-second video view" metric in Meta's API is `video_p3s_watched_actions` (also referred to as `video_3_sec_watched_actions` in older API versions). This counts views where the video was watched for at least 3 seconds. **This field is not currently in our INSIGHT_FIELDS.**

There is also Meta's ThruPlay metric (`video_thruplay_watched_actions`), which counts views to either 97% completion or 15 seconds, whichever comes first.

### v1 Decision

For v1 of the ad intelligence system, we alias `video_views` (sourced from `video_play_actions`) as the **hook rate denominator** in diagnostic rules that reference `video_3s_views`. This is the best available proxy given current data collection.

**Rationale**:
- `video_play_actions` is already collected and stored.
- For most video ads of reasonable length (>3 seconds), the difference between "video started playing" and "video watched for 3 seconds" is modest.
- Adding `video_p3s_watched_actions` to INSIGHT_FIELDS is a straightforward future enhancement.

### Important Note

> **`video_views` in our database is NOT exactly "3-second video views."** It is "video play initiations." Diagnostic rules that use this value for hook rate calculations should be understood as approximate. When higher precision is needed, add `video_p3s_watched_actions` to `MetaAdsService.INSIGHT_FIELDS` and create a corresponding `video_3s_views` column in `meta_ads_performance`.

---

## 6. Summary

### What We Have (v1)

- Full coverage of core spend/engagement metrics (impressions, spend, reach, frequency, clicks, CTR, CPC)
- Full coverage of conversion metrics (purchases, purchase_value, ROAS, conversion_rate, add_to_carts)
- Video retention at 25/50/75/100 percentile breakpoints
- Video play count (as a proxy for 3-second views)
- Raw action/cost JSON for ad-hoc extraction of any action type
- Congruence score from creative classification (cross-table)

### What We Need for v2

| Enhancement | Effort | Priority |
|-------------|--------|----------|
| Add `video_p3s_watched_actions` to INSIGHT_FIELDS + new column | Low | High (improves hook rate accuracy) |
| Add `video_p95_watched_actions` to INSIGHT_FIELDS + new column | Low | Low |
| Add `video_thruplay_watched_actions` to INSIGHT_FIELDS + new column | Low | Medium |
| Fetch `video_length_seconds` from Creative API + new column | Medium | Medium |
