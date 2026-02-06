"""FatigueDetector: Detects ad fatigue via frequency and CTR trend analysis.

Identifies ads that are fatigued (high frequency + declining CTR),
at-risk (approaching thresholds), or healthy.
"""

from __future__ import annotations

import logging
from datetime import date, timedelta
from typing import Any, Dict, List
from uuid import UUID

from .helpers import _safe_numeric, get_active_ad_ids
from .models import FatigueCheckResult

logger = logging.getLogger(__name__)


class FatigueDetector:
    """Detects ad fatigue via frequency and CTR trend analysis.

    Thresholds:
    - FREQUENCY_WARNING: 2.5 (at-risk)
    - FREQUENCY_CRITICAL: 4.0 (fatigued)
    - CTR_DECLINE_THRESHOLD: 0.15 (15% WoW decline = fatigue signal)
    """

    FREQUENCY_WARNING = 2.5
    FREQUENCY_CRITICAL = 4.0
    CTR_DECLINE_THRESHOLD = 0.15  # 15% WoW decline

    def __init__(self, supabase_client):
        """Initialize with Supabase client.

        Args:
            supabase_client: Supabase client instance.
        """
        self.supabase = supabase_client

    async def check_fatigue(
        self,
        brand_id: UUID,
        date_range_end: date,
        active_window_days: int = 7,
        days_back: int = 30,
    ) -> FatigueCheckResult:
        """Check all active ads for fatigue signals.

        Uses get_active_ad_ids with date_range_end parameter (not CURRENT_DATE)
        for reproducibility.

        Args:
            brand_id: Brand UUID.
            date_range_end: End of analysis window (anchor date).
            active_window_days: Days to look back for active ads.
            days_back: Days of trend data to analyze.

        Returns:
            FatigueCheckResult with fatigued, at-risk, and healthy counts.
        """
        # Get brand name
        brand_name = await self._get_brand_name(brand_id)

        # Get active ads
        active_ids = await get_active_ad_ids(
            self.supabase, brand_id, date_range_end, active_window_days
        )

        if not active_ids:
            return FatigueCheckResult(
                brand_name=brand_name,
                summary="No active ads found.",
            )

        # Fetch performance data for trend analysis
        trend_start = date_range_end - timedelta(days=days_back)
        perf_data = await self._fetch_performance_data(
            brand_id, active_ids, trend_start, date_range_end
        )

        fatigued: List[Dict[str, Any]] = []
        at_risk: List[Dict[str, Any]] = []
        healthy_count = 0

        for ad_id in active_ids:
            ad_rows = perf_data.get(ad_id, [])
            if not ad_rows:
                continue

            result = self._evaluate_ad_fatigue(ad_id, ad_rows, date_range_end)

            if result["status"] == "fatigued":
                fatigued.append(result)
            elif result["status"] == "at_risk":
                at_risk.append(result)
            else:
                healthy_count += 1

        summary = (
            f"Checked {len(active_ids)} active ads: "
            f"{len(fatigued)} fatigued, {len(at_risk)} at-risk, "
            f"{healthy_count} healthy."
        )

        return FatigueCheckResult(
            brand_name=brand_name,
            fatigued_ads=fatigued,
            at_risk_ads=at_risk,
            healthy_ads_count=healthy_count,
            summary=summary,
        )

    def _evaluate_ad_fatigue(
        self,
        meta_ad_id: str,
        rows: List[Dict],
        date_range_end: date,
    ) -> Dict[str, Any]:
        """Evaluate a single ad for fatigue signals.

        Checks:
        1. Current frequency vs thresholds
        2. CTR week-over-week decline

        Args:
            meta_ad_id: Meta ad ID.
            rows: Daily performance rows for this ad.
            date_range_end: End of analysis window.

        Returns:
            Dict with status, metrics, and trend info.
        """
        # Sort by date
        sorted_rows = sorted(rows, key=lambda r: r.get("date", ""))

        # Get latest metrics
        latest = sorted_rows[-1] if sorted_rows else {}
        ad_name = latest.get("ad_name", meta_ad_id)
        frequency = _safe_numeric(latest.get("frequency")) or 0

        # Calculate days running
        first_date = sorted_rows[0].get("date", "") if sorted_rows else ""
        last_date = sorted_rows[-1].get("date", "") if sorted_rows else ""
        days_running = len(sorted_rows)

        # Compute CTR trend (WoW)
        ctr_trend = self._compute_ctr_trend(sorted_rows)

        # Determine status
        is_high_freq = frequency >= self.FREQUENCY_CRITICAL
        is_declining_ctr = ctr_trend is not None and ctr_trend < -self.CTR_DECLINE_THRESHOLD
        is_warning_freq = frequency >= self.FREQUENCY_WARNING

        if is_high_freq or (is_warning_freq and is_declining_ctr):
            status = "fatigued"
        elif is_warning_freq or is_declining_ctr:
            status = "at_risk"
        else:
            status = "healthy"

        return {
            "meta_ad_id": meta_ad_id,
            "ad_name": ad_name,
            "frequency": round(frequency, 2),
            "ctr_trend": f"{ctr_trend:+.1%}" if ctr_trend is not None else "N/A",
            "ctr_trend_value": ctr_trend,
            "days_running": days_running,
            "status": status,
        }

    def _compute_ctr_trend(self, rows: List[Dict]) -> float | None:
        """Compute week-over-week CTR change.

        Compares average CTR in the last 7 days vs the previous 7 days.
        Returns fractional change (e.g., -0.15 = -15% decline).

        Args:
            rows: Sorted daily performance rows.

        Returns:
            Fractional WoW change or None if insufficient data.
        """
        if len(rows) < 7:
            return None

        # Split into recent week and previous week
        recent = rows[-7:]
        previous = rows[-14:-7] if len(rows) >= 14 else rows[:-7]

        if not previous:
            return None

        recent_ctrs = [_safe_numeric(r.get("link_ctr")) for r in recent]
        prev_ctrs = [_safe_numeric(r.get("link_ctr")) for r in previous]

        recent_ctrs = [c for c in recent_ctrs if c is not None and c > 0]
        prev_ctrs = [c for c in prev_ctrs if c is not None and c > 0]

        if not recent_ctrs or not prev_ctrs:
            return None

        recent_avg = sum(recent_ctrs) / len(recent_ctrs)
        prev_avg = sum(prev_ctrs) / len(prev_ctrs)

        if prev_avg == 0:
            return None

        return (recent_avg - prev_avg) / prev_avg

    async def _fetch_performance_data(
        self,
        brand_id: UUID,
        meta_ad_ids: List[str],
        start_date: date,
        end_date: date,
    ) -> Dict[str, List[Dict]]:
        """Fetch daily performance data grouped by ad ID.

        Args:
            brand_id: Brand UUID.
            meta_ad_ids: List of ad IDs.
            start_date: Start of trend window.
            end_date: End of trend window.

        Returns:
            Dict mapping meta_ad_id → list of daily rows.
        """
        try:
            result = self.supabase.table("meta_ads_performance").select(
                "meta_ad_id, ad_name, date, impressions, spend, frequency, link_ctr, link_cpc"
            ).eq(
                "brand_id", str(brand_id)
            ).in_(
                "meta_ad_id", meta_ad_ids
            ).gte(
                "date", start_date.isoformat()
            ).lte(
                "date", end_date.isoformat()
            ).order("date").execute()

            grouped: Dict[str, List[Dict]] = {}
            for row in result.data or []:
                ad_id = row.get("meta_ad_id")
                if ad_id:
                    if ad_id not in grouped:
                        grouped[ad_id] = []
                    grouped[ad_id].append(row)

            return grouped

        except Exception as e:
            logger.error(f"Error fetching performance data: {e}")
            return {}

    async def _get_brand_name(self, brand_id: UUID) -> str:
        """Look up brand name.

        Args:
            brand_id: Brand UUID.

        Returns:
            Brand name string.
        """
        try:
            result = self.supabase.table("brands").select("name").eq(
                "id", str(brand_id)
            ).limit(1).execute()
            if result.data:
                return result.data[0].get("name", "Unknown Brand")
        except Exception as e:
            logger.warning(f"Error fetching brand name: {e}")
        return "Unknown Brand"
