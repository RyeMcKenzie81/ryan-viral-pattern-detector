"""Layer 2: BaselineService — Contextual cohort baselines.

Computes p25/median/p75 percentile benchmarks per awareness level × creative format
cohort. Supports fallback chain (exact → drop length → drop objective → drop format
→ brand-wide) and anti-noise guardrails (min sample thresholds, winsorization).
"""

from __future__ import annotations

import logging
import math
from datetime import date
from typing import Any, Dict, List, Optional
from uuid import UUID

from .helpers import (
    _safe_numeric,
    extract_conversion_value,
    extract_conversions,
)
from .models import BaselineSnapshot, RunConfig

logger = logging.getLogger(__name__)


class BaselineService:
    """Computes and retrieves cohort-level performance baselines.

    Anti-noise guardrails:
    - Cohorts below MIN_COHORT_IMPRESSIONS or MIN_COHORT_SPEND are skipped.
    - Winsorization clips top/bottom 2% before percentile computation.
    - All thresholds are overrideable via RunConfig.thresholds.
    """

    # Defaults — all overrideable via RunConfig.thresholds
    MIN_SAMPLE_SIZE = 30
    MIN_UNIQUE_ADS = 5
    MIN_COHORT_IMPRESSIONS = 10_000
    MIN_COHORT_SPEND = 100.0
    WINSORIZE_PERCENTILE = 0.02

    def __init__(self, supabase_client):
        """Initialize with Supabase client.

        Args:
            supabase_client: Supabase client instance.
        """
        self.supabase = supabase_client

    async def compute_baselines(
        self,
        brand_id: UUID,
        run_config: RunConfig,
        date_range_start: date,
        date_range_end: date,
        org_id: Optional[UUID] = None,
        run_id: Optional[UUID] = None,
        force_recompute: bool = False,
    ) -> List[BaselineSnapshot]:
        """Compute cohort baselines for all awareness × format combinations.

        1. Query performance data joined with classifications.
        2. Group into cohorts by (awareness_level, creative_format).
        3. Filter: cohort must meet min impressions + spend thresholds.
        4. Winsorize: clip extreme values.
        5. Compute p25/median/p75 on winsorized data.
        6. Store/upsert with run_id if provided.

        Args:
            brand_id: Brand UUID.
            run_config: Run configuration with threshold overrides.
            date_range_start: Start of analysis window.
            date_range_end: End of analysis window.
            org_id: Organization UUID (for record storage).
            run_id: Analysis run UUID (optional audit linkage).
            force_recompute: Force recompute even if baselines exist.

        Returns:
            List of BaselineSnapshot models.
        """
        min_impressions = self._get_threshold(
            run_config, "baseline_min_cohort_impressions", self.MIN_COHORT_IMPRESSIONS
        )
        min_spend = self._get_threshold(
            run_config, "baseline_min_cohort_spend", self.MIN_COHORT_SPEND
        )
        winsorize_pct = self._get_threshold(
            run_config, "baseline_winsorize_percentile", self.WINSORIZE_PERCENTILE
        )

        # Check for existing baselines (skip if force_recompute)
        if not force_recompute:
            existing = await self._get_existing_baselines(
                brand_id, date_range_start, date_range_end
            )
            if existing:
                # Check if per-awareness roll-ups exist (format="all" but awareness != "all")
                has_awareness_rollups = any(
                    b.creative_format == "all" and b.awareness_level != "all"
                    for b in existing
                )
                if has_awareness_rollups:
                    logger.info(f"Returning {len(existing)} existing baselines for brand {brand_id}")
                    return existing
                else:
                    logger.info(f"Existing baselines missing awareness roll-ups, recomputing for brand {brand_id}")

        # Fetch classified ads with performance data
        perf_data = await self._fetch_classified_performance(
            brand_id, date_range_start, date_range_end
        )

        if not perf_data:
            logger.warning(f"No classified performance data for brand {brand_id}")
            return []

        # Group into cohorts
        cohorts = self._group_into_cohorts(perf_data)

        # Compute baselines per cohort
        baselines: List[BaselineSnapshot] = []
        for cohort_key, cohort_rows in cohorts.items():
            awareness_level, creative_format = cohort_key

            # Check sample size
            total_impressions = sum(
                _safe_numeric(r.get("impressions")) or 0 for r in cohort_rows
            )
            total_spend = sum(
                _safe_numeric(r.get("spend")) or 0 for r in cohort_rows
            )
            unique_ads = len(set(r.get("meta_ad_id") for r in cohort_rows if r.get("meta_ad_id")))

            if total_impressions < min_impressions or total_spend < min_spend:
                logger.debug(
                    f"Skipping cohort ({awareness_level}, {creative_format}): "
                    f"impressions={total_impressions}, spend={total_spend}"
                )
                continue

            if unique_ads < self._get_threshold(run_config, "baseline_min_unique_ads", self.MIN_UNIQUE_ADS):
                continue

            baseline = self._compute_cohort_baseline(
                cohort_rows,
                brand_id=brand_id,
                org_id=org_id,
                run_id=run_id,
                awareness_level=awareness_level,
                creative_format=creative_format,
                date_range_start=date_range_start,
                date_range_end=date_range_end,
                winsorize_pct=winsorize_pct,
                run_config=run_config,
            )
            if baseline:
                baselines.append(baseline)

        # Compute per-awareness-level roll-ups (all formats combined)
        awareness_rollups: Dict[str, List[Dict]] = {}
        for (awareness, fmt), rows in cohorts.items():
            if awareness not in awareness_rollups:
                awareness_rollups[awareness] = []
            awareness_rollups[awareness].extend(rows)

        for awareness, rows in awareness_rollups.items():
            if len(rows) >= self._get_threshold(run_config, "baseline_min_sample_size", self.MIN_SAMPLE_SIZE):
                awareness_baseline = self._compute_cohort_baseline(
                    rows,
                    brand_id=brand_id,
                    org_id=org_id,
                    run_id=run_id,
                    awareness_level=awareness,
                    creative_format="all",
                    date_range_start=date_range_start,
                    date_range_end=date_range_end,
                    winsorize_pct=winsorize_pct,
                    run_config=run_config,
                )
                if awareness_baseline:
                    baselines.append(awareness_baseline)

        # Also compute brand-wide baseline
        all_rows = [r for rows in cohorts.values() for r in rows]
        if len(all_rows) >= self._get_threshold(run_config, "baseline_min_sample_size", self.MIN_SAMPLE_SIZE):
            brand_wide = self._compute_cohort_baseline(
                all_rows,
                brand_id=brand_id,
                org_id=org_id,
                run_id=run_id,
                awareness_level="all",
                creative_format="all",
                date_range_start=date_range_start,
                date_range_end=date_range_end,
                winsorize_pct=winsorize_pct,
                run_config=run_config,
            )
            if brand_wide:
                baselines.append(brand_wide)

        # Store baselines
        for baseline in baselines:
            await self._store_baseline(baseline)

        logger.info(f"Computed {len(baselines)} baselines for brand {brand_id}")
        return baselines

    async def get_baseline_for_ad(
        self,
        meta_ad_id: str,
        brand_id: UUID,
        date_range_start: Optional[date] = None,
        date_range_end: Optional[date] = None,
    ) -> Optional[BaselineSnapshot]:
        """Get the best matching baseline for an ad using fallback chain.

        Fallback chain:
        1. Exact cohort (awareness_level + creative_format)
        2. Drop video_length_bucket
        3. Drop campaign_objective
        4. Drop creative_format (awareness-only)
        5. Brand-wide (all/all)

        Args:
            meta_ad_id: Meta ad ID string.
            brand_id: Brand UUID.
            date_range_start: Optional date range filter.
            date_range_end: Optional date range filter.

        Returns:
            Best matching BaselineSnapshot or None.
        """
        # Get ad's classification
        classification = self.supabase.table("ad_creative_classifications").select(
            "creative_awareness_level, creative_format, video_length_bucket"
        ).eq(
            "meta_ad_id", meta_ad_id
        ).eq(
            "brand_id", str(brand_id)
        ).order(
            "classified_at", desc=True
        ).limit(1).execute()

        if not classification.data:
            # No classification — try brand-wide
            return await self._query_baseline(brand_id, "all", "all", date_range_start, date_range_end)

        cls_data = classification.data[0]
        awareness = cls_data.get("creative_awareness_level", "all")
        fmt = cls_data.get("creative_format", "all")

        # Fallback chain
        for try_awareness, try_format in [
            (awareness, fmt),
            (awareness, "all"),
            ("all", fmt),
            ("all", "all"),
        ]:
            result = await self._query_baseline(
                brand_id, try_awareness, try_format, date_range_start, date_range_end
            )
            if result and result.is_sufficient:
                return result

        return None

    # =========================================================================
    # Private Methods
    # =========================================================================

    def _get_threshold(self, run_config: RunConfig, key: str, default: Any) -> Any:
        """Read threshold from run_config.thresholds, falling back to class default.

        Args:
            run_config: Run configuration.
            key: Threshold key name.
            default: Default value.

        Returns:
            Threshold value.
        """
        return run_config.thresholds.get(key, default)

    def _winsorize(self, values: List[float], pct: float = 0.02) -> List[float]:
        """Clip values below pct and above (1-pct) percentile.

        Reduces outlier noise before percentile computation.

        Args:
            values: List of numeric values.
            pct: Percentile to clip at (e.g., 0.02 = 2%).

        Returns:
            Winsorized list.
        """
        if not values or len(values) < 3:
            return values

        sorted_vals = sorted(values)
        n = len(sorted_vals)
        low_idx = max(0, int(math.floor(n * pct)))
        high_idx = min(n - 1, int(math.ceil(n * (1 - pct))))

        low_val = sorted_vals[low_idx]
        high_val = sorted_vals[high_idx]

        return [max(low_val, min(high_val, v)) for v in values]

    def _percentile(self, values: List[float], p: float) -> Optional[float]:
        """Compute percentile using linear interpolation.

        Args:
            values: Sorted list of numeric values.
            p: Percentile (0-100).

        Returns:
            Percentile value or None if empty.
        """
        if not values:
            return None
        sorted_vals = sorted(values)
        n = len(sorted_vals)
        if n == 1:
            return sorted_vals[0]

        k = (n - 1) * (p / 100.0)
        f = math.floor(k)
        c = math.ceil(k)

        if f == c:
            return sorted_vals[int(k)]

        return sorted_vals[int(f)] * (c - k) + sorted_vals[int(c)] * (k - f)

    async def _fetch_classified_performance(
        self,
        brand_id: UUID,
        date_range_start: date,
        date_range_end: date,
    ) -> List[Dict]:
        """Fetch performance data joined with classification info.

        Gets all performance rows in the date range, then joins with
        the latest classification for each ad. Uses pagination to ensure
        all rows are fetched (Supabase default limit is 1000).

        Args:
            brand_id: Brand UUID.
            date_range_start: Start date.
            date_range_end: End date.

        Returns:
            List of merged dicts (performance + classification).
        """
        # Fetch performance data with pagination
        all_perf_data = []
        offset = 0
        page_size = 1000

        while True:
            perf_result = self.supabase.table("meta_ads_performance").select("*").eq(
                "brand_id", str(brand_id)
            ).gte(
                "date", date_range_start.isoformat()
            ).lte(
                "date", date_range_end.isoformat()
            ).range(offset, offset + page_size - 1).execute()

            if not perf_result.data:
                break

            all_perf_data.extend(perf_result.data)

            if len(perf_result.data) < page_size:
                break

            offset += page_size

        if not all_perf_data:
            return []

        # Fetch latest classification for each ad
        ad_ids = list(set(r.get("meta_ad_id") for r in all_perf_data if r.get("meta_ad_id")))

        cls_result = self.supabase.table("ad_creative_classifications").select(
            "meta_ad_id, creative_awareness_level, creative_format, video_length_bucket"
        ).eq(
            "brand_id", str(brand_id)
        ).in_(
            "meta_ad_id", ad_ids
        ).order(
            "classified_at", desc=True
        ).execute()

        # Build classification lookup (latest per ad)
        cls_map: Dict[str, Dict] = {}
        for row in cls_result.data or []:
            ad_id = row.get("meta_ad_id")
            if ad_id and ad_id not in cls_map:
                cls_map[ad_id] = row

        # Merge performance with classification
        merged = []
        for perf in all_perf_data:
            ad_id = perf.get("meta_ad_id")
            cls_data = cls_map.get(ad_id, {})
            combined = {**perf, **cls_data}
            merged.append(combined)

        return merged

    def _group_into_cohorts(
        self, data: List[Dict]
    ) -> Dict[tuple, List[Dict]]:
        """Group performance data into awareness × format cohorts.

        Args:
            data: List of merged performance + classification dicts.

        Returns:
            Dict mapping (awareness_level, creative_format) → rows.
        """
        cohorts: Dict[tuple, List[Dict]] = {}
        for row in data:
            awareness = row.get("creative_awareness_level", "unknown")
            fmt = row.get("creative_format", "unknown")
            if awareness and fmt:
                key = (awareness, fmt)
                if key not in cohorts:
                    cohorts[key] = []
                cohorts[key].append(row)
        return cohorts

    def _compute_cohort_baseline(
        self,
        rows: List[Dict],
        brand_id: UUID,
        org_id: Optional[UUID],
        run_id: Optional[UUID],
        awareness_level: str,
        creative_format: str,
        date_range_start: date,
        date_range_end: date,
        winsorize_pct: float,
        run_config: RunConfig,
    ) -> Optional[BaselineSnapshot]:
        """Compute baseline statistics for a single cohort.

        Args:
            rows: Performance rows in this cohort.
            brand_id: Brand UUID.
            org_id: Organization UUID.
            run_id: Run UUID for audit linkage.
            awareness_level: Cohort awareness level.
            creative_format: Cohort creative format.
            date_range_start: Start of date range.
            date_range_end: End of date range.
            winsorize_pct: Winsorization percentile.
            run_config: Run configuration.

        Returns:
            BaselineSnapshot or None if insufficient data.
        """
        if len(rows) < self._get_threshold(run_config, "baseline_min_sample_size", self.MIN_SAMPLE_SIZE):
            return None

        unique_ads = len(set(r.get("meta_ad_id") for r in rows if r.get("meta_ad_id")))

        # ------------------------------------------------------------------
        # Aggregate raw counts per ad first, then compute derived ratios.
        # This avoids inflated baselines from low-volume daily rows where
        # e.g. 1 click + $80 spend yields link_cpc = $80.
        # ------------------------------------------------------------------
        ad_totals: Dict[str, Dict[str, float]] = {}
        for r in rows:
            ad_id = r.get("meta_ad_id", "unknown")
            if ad_id not in ad_totals:
                ad_totals[ad_id] = {
                    "spend": 0.0, "impressions": 0.0, "link_clicks": 0.0,
                    "add_to_carts": 0.0, "conversions": 0.0,
                    "conversion_value": 0.0,
                    "video_views": 0.0, "video_p25": 0.0, "video_p100": 0.0,
                    "frequency_sum": 0.0, "frequency_count": 0,
                }
            t = ad_totals[ad_id]
            t["spend"] += _safe_numeric(r.get("spend")) or 0
            t["impressions"] += _safe_numeric(r.get("impressions")) or 0
            t["link_clicks"] += _safe_numeric(r.get("link_clicks")) or 0
            t["video_views"] += _safe_numeric(r.get("video_views")) or 0
            t["video_p25"] += _safe_numeric(r.get("video_p25_watched")) or 0
            t["video_p100"] += _safe_numeric(r.get("video_p100_watched")) or 0

            # Conversions & value — use helpers to parse JSONB actions
            conv = extract_conversions(r, run_config.primary_conversion_event)
            if conv is not None:
                t["conversions"] += conv
            conv_val = None
            if run_config.value_field == "purchase_value":
                conv_val = _safe_numeric(r.get("purchase_value"))
            if conv_val is None:
                conv_val = extract_conversion_value(r, run_config.value_field)
            if conv_val is not None:
                t["conversion_value"] += conv_val

            # Add-to-cart from raw_actions or pre-extracted column
            atc = extract_conversions(r, "add_to_cart")
            if atc is not None:
                t["add_to_carts"] += atc

            # Frequency — average across days (weighted equally per day)
            freq = _safe_numeric(r.get("frequency"))
            if freq is not None and freq >= 0:
                t["frequency_sum"] += freq
                t["frequency_count"] += 1

        # Compute derived per-ad metrics from aggregated totals
        cpc_values, cpm_values, ctr_values = [], [], []
        roas_values, conv_rate_values, cpp_values, cpatc_values = [], [], [], []
        hook_values, hold_values, completion_values = [], [], []
        freq_values = []

        for ad_id, t in ad_totals.items():
            spend = t["spend"]
            impressions = t["impressions"]
            link_clicks = t["link_clicks"]

            # CPC = total_spend / total_clicks
            if link_clicks > 0:
                cpc_values.append(spend / link_clicks)
            # CPM = (total_spend / total_impressions) * 1000
            if impressions > 0:
                cpm_values.append((spend / impressions) * 1000)
            # CTR = total_clicks / total_impressions
            if impressions > 0:
                ctr_values.append(link_clicks / impressions)

            # ROAS = total_conversion_value / total_spend
            if spend > 0 and t["conversion_value"] > 0:
                roas_values.append(t["conversion_value"] / spend)

            # Conversion rate = total_conversions / total_clicks * 100
            if link_clicks > 0 and t["conversions"] > 0:
                conv_rate_values.append((t["conversions"] / link_clicks) * 100)

            # Cost per purchase = total_spend / total_conversions
            if t["conversions"] > 0:
                cpp_values.append(spend / t["conversions"])

            # Cost per add-to-cart = total_spend / total_atc
            if t["add_to_carts"] > 0:
                cpatc_values.append(spend / t["add_to_carts"])

            # Video metrics (already computed from raw counts, no change)
            video_views = t["video_views"]
            if video_views > 0 and impressions > 0:
                hook_values.append(video_views / impressions)
            if t["video_p25"] > 0 and video_views > 0:
                hold_values.append(t["video_p25"] / video_views)
            if t["video_p100"] > 0 and impressions > 0:
                completion_values.append(t["video_p100"] / impressions)

            # Frequency — average across daily rows for this ad
            if t["frequency_count"] > 0:
                freq_values.append(t["frequency_sum"] / t["frequency_count"])

        # Winsorize all metric arrays
        cpc_values = self._winsorize(cpc_values, winsorize_pct)
        cpm_values = self._winsorize(cpm_values, winsorize_pct)
        ctr_values = self._winsorize(ctr_values, winsorize_pct)
        roas_values = self._winsorize(roas_values, winsorize_pct)
        conv_rate_values = self._winsorize(conv_rate_values, winsorize_pct)
        cpp_values = self._winsorize(cpp_values, winsorize_pct)
        cpatc_values = self._winsorize(cpatc_values, winsorize_pct)
        freq_values = self._winsorize(freq_values, winsorize_pct)

        return BaselineSnapshot(
            brand_id=brand_id,
            organization_id=org_id,
            run_id=run_id,
            awareness_level=awareness_level,
            creative_format=creative_format,
            sample_size=len(rows),
            unique_ads=unique_ads,
            median_ctr=self._percentile(ctr_values, 50),
            p25_ctr=self._percentile(ctr_values, 25),
            p75_ctr=self._percentile(ctr_values, 75),
            median_cpc=self._percentile(cpc_values, 50),
            p25_cpc=self._percentile(cpc_values, 25),
            p75_cpc=self._percentile(cpc_values, 75),
            median_cpm=self._percentile(cpm_values, 50),
            p25_cpm=self._percentile(cpm_values, 25),
            p75_cpm=self._percentile(cpm_values, 75),
            median_roas=self._percentile(roas_values, 50),
            p25_roas=self._percentile(roas_values, 25),
            p75_roas=self._percentile(roas_values, 75),
            median_conversion_rate=self._percentile(conv_rate_values, 50),
            p25_conversion_rate=self._percentile(conv_rate_values, 25),
            p75_conversion_rate=self._percentile(conv_rate_values, 75),
            median_cost_per_purchase=self._percentile(cpp_values, 50),
            median_cost_per_add_to_cart=self._percentile(cpatc_values, 50) if cpatc_values else None,
            median_hook_rate=self._percentile(hook_values, 50) if hook_values else None,
            median_hold_rate=self._percentile(hold_values, 50) if hold_values else None,
            median_completion_rate=self._percentile(completion_values, 50) if completion_values else None,
            median_frequency=self._percentile(freq_values, 50),
            p75_frequency=self._percentile(freq_values, 75),
            date_range_start=date_range_start,
            date_range_end=date_range_end,
        )

    async def _store_baseline(self, baseline: BaselineSnapshot) -> None:
        """Upsert a baseline record.

        Uses the UNIQUE constraint on (brand_id, awareness_level, creative_format,
        video_length_bucket, campaign_objective, date_range_start, date_range_end).

        Args:
            baseline: BaselineSnapshot to store.
        """
        try:
            record = {
                "brand_id": str(baseline.brand_id),
                "organization_id": str(baseline.organization_id) if baseline.organization_id else None,
                "awareness_level": baseline.awareness_level,
                "creative_format": baseline.creative_format,
                "video_length_bucket": baseline.video_length_bucket,
                "campaign_objective": baseline.campaign_objective,
                "run_id": str(baseline.run_id) if baseline.run_id else None,
                "sample_size": baseline.sample_size,
                "unique_ads": baseline.unique_ads,
                "median_ctr": baseline.median_ctr,
                "p25_ctr": baseline.p25_ctr,
                "p75_ctr": baseline.p75_ctr,
                "median_cpc": baseline.median_cpc,
                "p25_cpc": baseline.p25_cpc,
                "p75_cpc": baseline.p75_cpc,
                "median_cpm": baseline.median_cpm,
                "p25_cpm": baseline.p25_cpm,
                "p75_cpm": baseline.p75_cpm,
                "median_roas": baseline.median_roas,
                "p25_roas": baseline.p25_roas,
                "p75_roas": baseline.p75_roas,
                "median_conversion_rate": baseline.median_conversion_rate,
                "p25_conversion_rate": baseline.p25_conversion_rate,
                "p75_conversion_rate": baseline.p75_conversion_rate,
                "median_cost_per_purchase": baseline.median_cost_per_purchase,
                "median_cost_per_add_to_cart": baseline.median_cost_per_add_to_cart,
                "median_hook_rate": baseline.median_hook_rate,
                "median_hold_rate": baseline.median_hold_rate,
                "median_completion_rate": baseline.median_completion_rate,
                "median_frequency": baseline.median_frequency,
                "p75_frequency": baseline.p75_frequency,
                "date_range_start": baseline.date_range_start.isoformat(),
                "date_range_end": baseline.date_range_end.isoformat(),
            }

            self.supabase.table("ad_intelligence_baselines").upsert(
                record,
                on_conflict="brand_id,awareness_level,creative_format,video_length_bucket,campaign_objective,date_range_start,date_range_end",
            ).execute()

        except Exception as e:
            logger.error(f"Error storing baseline: {e}")

    async def _get_existing_baselines(
        self,
        brand_id: UUID,
        date_range_start: date,
        date_range_end: date,
    ) -> List[BaselineSnapshot]:
        """Check for existing baselines for the same date range.

        Args:
            brand_id: Brand UUID.
            date_range_start: Start date.
            date_range_end: End date.

        Returns:
            List of existing BaselineSnapshot models (empty if none).
        """
        try:
            result = self.supabase.table("ad_intelligence_baselines").select("*").eq(
                "brand_id", str(brand_id)
            ).eq(
                "date_range_start", date_range_start.isoformat()
            ).eq(
                "date_range_end", date_range_end.isoformat()
            ).execute()

            if result.data:
                return [self._row_to_model(r) for r in result.data]
        except Exception as e:
            logger.warning(f"Error fetching existing baselines: {e}")

        return []

    async def _query_baseline(
        self,
        brand_id: UUID,
        awareness_level: str,
        creative_format: str,
        date_range_start: Optional[date] = None,
        date_range_end: Optional[date] = None,
    ) -> Optional[BaselineSnapshot]:
        """Query a specific baseline from the database.

        Args:
            brand_id: Brand UUID.
            awareness_level: Awareness level filter.
            creative_format: Creative format filter.
            date_range_start: Optional date range filter.
            date_range_end: Optional date range filter.

        Returns:
            BaselineSnapshot or None.
        """
        try:
            query = self.supabase.table("ad_intelligence_baselines").select("*").eq(
                "brand_id", str(brand_id)
            ).eq(
                "awareness_level", awareness_level
            ).eq(
                "creative_format", creative_format
            )

            if date_range_start:
                query = query.eq("date_range_start", date_range_start.isoformat())
            if date_range_end:
                query = query.eq("date_range_end", date_range_end.isoformat())

            result = query.order("computed_at", desc=True).limit(1).execute()

            if result.data:
                return self._row_to_model(result.data[0])
        except Exception as e:
            logger.warning(f"Error querying baseline: {e}")

        return None

    def _row_to_model(self, row: Dict) -> BaselineSnapshot:
        """Convert a DB row to a BaselineSnapshot model.

        Args:
            row: Database row dict.

        Returns:
            BaselineSnapshot model.
        """
        return BaselineSnapshot(
            id=row.get("id"),
            brand_id=UUID(row["brand_id"]) if row.get("brand_id") else UUID(int=0),
            organization_id=UUID(row["organization_id"]) if row.get("organization_id") else None,
            run_id=UUID(row["run_id"]) if row.get("run_id") else None,
            awareness_level=row.get("awareness_level", "all"),
            creative_format=row.get("creative_format", "all"),
            video_length_bucket=row.get("video_length_bucket", "all"),
            campaign_objective=row.get("campaign_objective", "all"),
            sample_size=row.get("sample_size", 0),
            unique_ads=row.get("unique_ads", 0),
            median_ctr=_safe_numeric(row.get("median_ctr")),
            p25_ctr=_safe_numeric(row.get("p25_ctr")),
            p75_ctr=_safe_numeric(row.get("p75_ctr")),
            median_cpc=_safe_numeric(row.get("median_cpc")),
            p25_cpc=_safe_numeric(row.get("p25_cpc")),
            p75_cpc=_safe_numeric(row.get("p75_cpc")),
            median_cpm=_safe_numeric(row.get("median_cpm")),
            p25_cpm=_safe_numeric(row.get("p25_cpm")),
            p75_cpm=_safe_numeric(row.get("p75_cpm")),
            median_roas=_safe_numeric(row.get("median_roas")),
            p25_roas=_safe_numeric(row.get("p25_roas")),
            p75_roas=_safe_numeric(row.get("p75_roas")),
            median_conversion_rate=_safe_numeric(row.get("median_conversion_rate")),
            p25_conversion_rate=_safe_numeric(row.get("p25_conversion_rate")),
            p75_conversion_rate=_safe_numeric(row.get("p75_conversion_rate")),
            median_cost_per_purchase=_safe_numeric(row.get("median_cost_per_purchase")),
            median_hook_rate=_safe_numeric(row.get("median_hook_rate")),
            median_hold_rate=_safe_numeric(row.get("median_hold_rate")),
            median_completion_rate=_safe_numeric(row.get("median_completion_rate")),
            median_frequency=_safe_numeric(row.get("median_frequency")),
            p75_frequency=_safe_numeric(row.get("p75_frequency")),
            date_range_start=row.get("date_range_start", date.today()),
            date_range_end=row.get("date_range_end", date.today()),
            computed_at=row.get("computed_at"),
        )
