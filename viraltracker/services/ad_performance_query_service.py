"""
Ad Performance Query Service - Direct ad performance data lookups.

Provides 4 query methods for conversational ad performance querying:
- get_top_ads: Rank ads by any metric (ROAS, spend, CTR, etc.)
- get_account_summary: Account-level totals with optional period comparison
- get_campaign_breakdown: Campaign or adset level aggregation
- get_ad_details: Single ad deep dive with daily trends

All methods are sync (Supabase client is sync). Returns structured dicts.
Aggregation logic ported from viraltracker/ui/pages/30_Ad_Performance.py.
"""

import logging
from collections import defaultdict
from datetime import date, datetime, timedelta
from typing import Any, Dict, List, Optional, Tuple

logger = logging.getLogger(__name__)


class AdPerformanceQueryService:
    """Service for querying ad performance data from meta_ads_performance."""

    def __init__(self, supabase_client):
        self.supabase = supabase_client

    # -------------------------------------------------------------------------
    # Public query methods
    # -------------------------------------------------------------------------

    def get_top_ads(
        self,
        brand_id: str,
        sort_by: str = "roas",
        days_back: int = 30,
        limit: int = 10,
        sort_order: str = "desc",
        status_filter: str = "all",
        min_spend: float = 0.0,
        campaign_name_filter: str = "",
        date_start: Optional[str] = None,
        date_end: Optional[str] = None,
    ) -> Dict[str, Any]:
        """Get top/bottom ads ranked by a metric.

        Args:
            brand_id: Brand UUID string.
            sort_by: Metric to sort by.
            days_back: Number of days to look back (used if date_start/date_end not set).
            limit: Max ads to return.
            sort_order: 'desc' for top, 'asc' for bottom.
            status_filter: 'all', 'active', or 'paused'.
            min_spend: Minimum spend threshold.
            campaign_name_filter: Filter by campaign name substring (case-insensitive).
            date_start: Explicit start date (ISO format, e.g. '2026-01-01').
            date_end: Explicit end date (ISO format).

        Returns:
            Dict with 'ads' list, 'meta' dict with query params and date range.
        """
        start, end = self._resolve_date_range(days_back, date_start, date_end)
        rows = self._fetch_performance_rows(brand_id, start, end)

        if not rows:
            return {"ads": [], "meta": {"date_start": start.isoformat(), "date_end": end.isoformat(), "total_rows": 0}}

        ads = self._aggregate_by_ad(rows)

        # Apply filters
        if status_filter == "active":
            ads = [a for a in ads if (a.get("ad_status") or "").upper() == "ACTIVE"]
        elif status_filter == "paused":
            ads = [a for a in ads if (a.get("ad_status") or "").upper() == "PAUSED"]

        if min_spend > 0:
            ads = [a for a in ads if a["spend"] >= min_spend]

        if campaign_name_filter:
            filter_lower = campaign_name_filter.lower()
            ads = [a for a in ads if filter_lower in (a.get("campaign_name") or "").lower()]

        # Sort
        reverse = sort_order == "desc"
        ads.sort(key=lambda a: a.get(sort_by, 0) or 0, reverse=reverse)

        return {
            "ads": ads[:limit],
            "meta": {
                "date_start": start.isoformat(),
                "date_end": end.isoformat(),
                "sort_by": sort_by,
                "sort_order": sort_order,
                "total_matching": len(ads),
                "returned": min(limit, len(ads)),
            },
        }

    def get_account_summary(
        self,
        brand_id: str,
        days_back: int = 30,
        compare_previous: bool = False,
        date_start: Optional[str] = None,
        date_end: Optional[str] = None,
    ) -> Dict[str, Any]:
        """Get account-level summary with optional period-over-period comparison.

        Args:
            brand_id: Brand UUID string.
            days_back: Number of days to look back.
            compare_previous: If True, also compute previous period of same length.
            date_start: Explicit start date (ISO format).
            date_end: Explicit end date (ISO format).

        Returns:
            Dict with 'current' period totals, optional 'previous' period totals,
            and optional 'change' with percentage deltas.
        """
        start, end = self._resolve_date_range(days_back, date_start, date_end)
        rows = self._fetch_performance_rows(brand_id, start, end)
        current = self._compute_period_totals(rows)

        result: Dict[str, Any] = {
            "current": current,
            "meta": {
                "date_start": start.isoformat(),
                "date_end": end.isoformat(),
                "days": (end - start).days + 1,
            },
        }

        if compare_previous:
            period_days = (end - start).days + 1
            prev_end = start - timedelta(days=1)
            prev_start = prev_end - timedelta(days=period_days - 1)

            prev_rows = self._fetch_performance_rows(brand_id, prev_start, prev_end)
            previous = self._compute_period_totals(prev_rows)

            result["previous"] = previous
            result["previous_meta"] = {
                "date_start": prev_start.isoformat(),
                "date_end": prev_end.isoformat(),
            }
            result["change"] = self._compute_change(current, previous)

        return result

    def get_campaign_breakdown(
        self,
        brand_id: str,
        level: str = "campaign",
        days_back: int = 30,
        sort_by: str = "spend",
        limit: int = 20,
        date_start: Optional[str] = None,
        date_end: Optional[str] = None,
    ) -> Dict[str, Any]:
        """Get performance breakdown by campaign or adset.

        Args:
            brand_id: Brand UUID string.
            level: 'campaign' or 'adset'.
            days_back: Number of days to look back.
            sort_by: Metric to sort by.
            limit: Max items to return.
            date_start: Explicit start date (ISO format).
            date_end: Explicit end date (ISO format).

        Returns:
            Dict with 'items' list and 'meta' dict.
        """
        start, end = self._resolve_date_range(days_back, date_start, date_end)
        rows = self._fetch_performance_rows(brand_id, start, end)

        if not rows:
            return {"items": [], "meta": {"date_start": start.isoformat(), "date_end": end.isoformat(), "level": level}}

        if level == "adset":
            items = self._aggregate_by_adset(rows)
        else:
            items = self._aggregate_by_campaign(rows)

        items.sort(key=lambda x: x.get(sort_by, 0) or 0, reverse=True)

        return {
            "items": items[:limit],
            "meta": {
                "date_start": start.isoformat(),
                "date_end": end.isoformat(),
                "level": level,
                "sort_by": sort_by,
                "total": len(items),
                "returned": min(limit, len(items)),
            },
        }

    def get_ad_details(
        self,
        brand_id: str,
        ad_identifier: str,
        days_back: int = 30,
        date_start: Optional[str] = None,
        date_end: Optional[str] = None,
    ) -> Dict[str, Any]:
        """Get detailed performance for a single ad with daily trends.

        Args:
            brand_id: Brand UUID string.
            ad_identifier: Meta ad ID or ad name substring for search.
            days_back: Number of days to look back.
            date_start: Explicit start date (ISO format).
            date_end: Explicit end date (ISO format).

        Returns:
            Dict with 'ad' summary, 'daily' trend data, and 'meta' dict.
        """
        start, end = self._resolve_date_range(days_back, date_start, date_end)
        rows = self._fetch_performance_rows(brand_id, start, end)

        if not rows:
            return {"ad": None, "daily": [], "meta": {"ad_identifier": ad_identifier, "error": "No performance data found"}}

        # Try exact ID match first
        ad_rows = [r for r in rows if r.get("meta_ad_id") == ad_identifier]

        # Fallback to name search
        if not ad_rows:
            search_lower = ad_identifier.lower()
            ad_rows = [r for r in rows if search_lower in (r.get("ad_name") or "").lower()]

        if not ad_rows:
            # Return available ad names for user to refine
            all_ads = self._aggregate_by_ad(rows)
            suggestions = [{"ad_name": a["ad_name"], "meta_ad_id": a["meta_ad_id"], "spend": a["spend"]} for a in all_ads[:10]]
            return {
                "ad": None,
                "daily": [],
                "meta": {
                    "ad_identifier": ad_identifier,
                    "error": f"No ad found matching '{ad_identifier}'",
                    "suggestions": suggestions,
                },
            }

        # If name search matched multiple ads, pick the highest-spend one
        if len(set(r.get("meta_ad_id") for r in ad_rows)) > 1:
            # Group by ad_id, pick highest spend
            by_id: Dict[str, list] = defaultdict(list)
            for r in ad_rows:
                by_id[r.get("meta_ad_id", "")].append(r)
            best_id = max(by_id.keys(), key=lambda k: sum(float(r.get("spend") or 0) for r in by_id[k]))
            ad_rows = by_id[best_id]

        # Build aggregate summary
        agg = self._aggregate_by_ad(ad_rows)
        ad_summary = agg[0] if agg else {}

        # Build daily trend
        daily = []
        for r in sorted(ad_rows, key=lambda x: x.get("date", "")):
            spend = float(r.get("spend") or 0)
            impressions = int(r.get("impressions") or 0)
            link_clicks = int(r.get("link_clicks") or 0)
            purchases = int(r.get("purchases") or 0)
            purchase_value = float(r.get("purchase_value") or 0)

            daily.append({
                "date": r.get("date"),
                "spend": spend,
                "impressions": impressions,
                "link_clicks": link_clicks,
                "ctr": (link_clicks / impressions * 100) if impressions > 0 else 0,
                "cpc": (spend / link_clicks) if link_clicks > 0 else 0,
                "purchases": purchases,
                "purchase_value": purchase_value,
                "roas": (purchase_value / spend) if spend > 0 else 0,
                "reach": int(r.get("reach") or 0),
                "frequency": float(r.get("frequency") or 0),
                "video_views": int(r.get("video_views") or 0),
                "hook_rate": float(r.get("hook_rate") or 0),
                "hold_rate": float(r.get("hold_rate") or 0),
            })

        return {
            "ad": ad_summary,
            "daily": daily,
            "meta": {
                "date_start": start.isoformat(),
                "date_end": end.isoformat(),
                "ad_identifier": ad_identifier,
                "days_with_data": len(daily),
            },
        }

    # -------------------------------------------------------------------------
    # Internal helpers
    # -------------------------------------------------------------------------

    def _resolve_date_range(
        self,
        days_back: Optional[int],
        date_start: Optional[str],
        date_end: Optional[str],
    ) -> Tuple[date, date]:
        """Resolve date range from either explicit dates or days_back.

        Explicit dates take precedence over days_back.

        Returns:
            Tuple of (start_date, end_date).
        """
        if date_start and date_end:
            return (
                datetime.strptime(date_start, "%Y-%m-%d").date(),
                datetime.strptime(date_end, "%Y-%m-%d").date(),
            )

        if date_start:
            start = datetime.strptime(date_start, "%Y-%m-%d").date()
            return start, date.today()

        if date_end:
            end = datetime.strptime(date_end, "%Y-%m-%d").date()
            d = days_back or 30
            return end - timedelta(days=d - 1), end

        d = days_back or 30
        end = date.today()
        start = end - timedelta(days=d - 1)
        return start, end

    def _fetch_performance_rows(
        self, brand_id: str, date_start: date, date_end: date
    ) -> List[Dict]:
        """Fetch raw performance rows with pagination.

        Supabase PostgREST silently truncates at 1000 rows.
        Paginates using .range() until all rows are fetched.
        """
        all_rows: List[Dict] = []
        offset = 0
        page_size = 1000

        while True:
            result = (
                self.supabase.table("meta_ads_performance")
                .select("*")
                .eq("brand_id", brand_id)
                .gte("date", date_start.isoformat())
                .lte("date", date_end.isoformat())
                .order("date", desc=True)
                .range(offset, offset + page_size - 1)
                .execute()
            )

            if not result.data:
                break

            all_rows.extend(result.data)

            if len(result.data) < page_size:
                break

            offset += page_size

        logger.info(
            f"Fetched {len(all_rows)} performance rows for brand {brand_id} "
            f"({date_start} to {date_end})"
        )
        return all_rows

    def _aggregate_by_ad(self, rows: List[Dict]) -> List[Dict]:
        """Aggregate daily rows into per-ad summaries.

        Ported from viraltracker/ui/pages/30_Ad_Performance.py:aggregate_by_ad.
        """
        ads: Dict[str, Dict] = defaultdict(lambda: {
            "spend": 0, "impressions": 0, "link_clicks": 0,
            "add_to_carts": 0, "purchases": 0, "purchase_value": 0,
            "reach": 0,
        })

        for d in rows:
            aid = d.get("meta_ad_id")
            if not aid:
                continue
            a = ads[aid]
            a["ad_name"] = d.get("ad_name") or a.get("ad_name", "Unknown")
            if not a.get("ad_status"):
                a["ad_status"] = d.get("ad_status") or ""
            a["adset_name"] = d.get("adset_name") or a.get("adset_name", "")
            a["campaign_name"] = d.get("campaign_name") or a.get("campaign_name", "")
            a["meta_adset_id"] = d.get("meta_adset_id") or a.get("meta_adset_id", "")
            a["meta_campaign_id"] = d.get("meta_campaign_id") or a.get("meta_campaign_id", "")
            a["spend"] += float(d.get("spend") or 0)
            a["impressions"] += int(d.get("impressions") or 0)
            a["link_clicks"] += int(d.get("link_clicks") or 0)
            a["add_to_carts"] += int(d.get("add_to_carts") or 0)
            a["purchases"] += int(d.get("purchases") or 0)
            a["purchase_value"] += float(d.get("purchase_value") or 0)
            a["reach"] += int(d.get("reach") or 0)

        result = []
        for aid, a in ads.items():
            imp = a["impressions"]
            clicks = a["link_clicks"]
            spend = a["spend"]
            pv = a["purchase_value"]

            result.append({
                "meta_ad_id": aid,
                "ad_name": a["ad_name"],
                "ad_status": a["ad_status"],
                "adset_name": a["adset_name"],
                "campaign_name": a["campaign_name"],
                "meta_adset_id": a["meta_adset_id"],
                "meta_campaign_id": a["meta_campaign_id"],
                "spend": spend,
                "impressions": imp,
                "reach": a["reach"],
                "link_clicks": clicks,
                "ctr": (clicks / imp * 100) if imp > 0 else 0,
                "cpm": (spend / imp * 1000) if imp > 0 else 0,
                "cpc": (spend / clicks) if clicks > 0 else 0,
                "add_to_carts": a["add_to_carts"],
                "purchases": a["purchases"],
                "purchase_value": pv,
                "roas": (pv / spend) if spend > 0 else 0,
                "conversion_rate": (a["purchases"] / clicks * 100) if clicks > 0 else 0,
                "frequency": (imp / a["reach"]) if a["reach"] > 0 else 0,
            })

        return result

    def _aggregate_by_campaign(self, rows: List[Dict]) -> List[Dict]:
        """Aggregate daily rows into per-campaign summaries.

        Ported from viraltracker/ui/pages/30_Ad_Performance.py:aggregate_by_campaign.
        """
        campaigns: Dict[str, Dict] = defaultdict(lambda: {
            "spend": 0, "impressions": 0, "link_clicks": 0,
            "add_to_carts": 0, "purchases": 0, "purchase_value": 0,
            "ad_ids": set(), "adset_ids": set(),
        })

        for d in rows:
            cid = d.get("meta_campaign_id")
            if not cid:
                continue
            c = campaigns[cid]
            c["campaign_name"] = d.get("campaign_name") or c.get("campaign_name", "Unknown")
            c["spend"] += float(d.get("spend") or 0)
            c["impressions"] += int(d.get("impressions") or 0)
            c["link_clicks"] += int(d.get("link_clicks") or 0)
            c["add_to_carts"] += int(d.get("add_to_carts") or 0)
            c["purchases"] += int(d.get("purchases") or 0)
            c["purchase_value"] += float(d.get("purchase_value") or 0)
            if d.get("meta_adset_id"):
                c["adset_ids"].add(d["meta_adset_id"])
            if d.get("meta_ad_id"):
                c["ad_ids"].add(d["meta_ad_id"])

        result = []
        for cid, c in campaigns.items():
            imp = c["impressions"]
            clicks = c["link_clicks"]
            spend = c["spend"]
            pv = c["purchase_value"]

            result.append({
                "meta_campaign_id": cid,
                "campaign_name": c["campaign_name"],
                "spend": spend,
                "impressions": imp,
                "link_clicks": clicks,
                "ctr": (clicks / imp * 100) if imp > 0 else 0,
                "cpm": (spend / imp * 1000) if imp > 0 else 0,
                "cpc": (spend / clicks) if clicks > 0 else 0,
                "add_to_carts": c["add_to_carts"],
                "purchases": c["purchases"],
                "purchase_value": pv,
                "roas": (pv / spend) if spend > 0 else 0,
                "conversion_rate": (c["purchases"] / clicks * 100) if clicks > 0 else 0,
                "adset_count": len(c["adset_ids"]),
                "ad_count": len(c["ad_ids"]),
            })

        return result

    def _aggregate_by_adset(self, rows: List[Dict]) -> List[Dict]:
        """Aggregate daily rows into per-adset summaries.

        Ported from viraltracker/ui/pages/30_Ad_Performance.py:aggregate_by_adset.
        """
        adsets: Dict[str, Dict] = defaultdict(lambda: {
            "spend": 0, "impressions": 0, "link_clicks": 0,
            "add_to_carts": 0, "purchases": 0, "purchase_value": 0,
            "ad_ids": set(),
        })

        for d in rows:
            asid = d.get("meta_adset_id")
            if not asid:
                continue
            a = adsets[asid]
            a["adset_name"] = d.get("adset_name") or a.get("adset_name", "Unknown")
            a["campaign_name"] = d.get("campaign_name") or a.get("campaign_name", "")
            a["meta_campaign_id"] = d.get("meta_campaign_id") or a.get("meta_campaign_id", "")
            a["spend"] += float(d.get("spend") or 0)
            a["impressions"] += int(d.get("impressions") or 0)
            a["link_clicks"] += int(d.get("link_clicks") or 0)
            a["add_to_carts"] += int(d.get("add_to_carts") or 0)
            a["purchases"] += int(d.get("purchases") or 0)
            a["purchase_value"] += float(d.get("purchase_value") or 0)
            if d.get("meta_ad_id"):
                a["ad_ids"].add(d["meta_ad_id"])

        result = []
        for asid, a in adsets.items():
            imp = a["impressions"]
            clicks = a["link_clicks"]
            spend = a["spend"]
            pv = a["purchase_value"]

            result.append({
                "meta_adset_id": asid,
                "adset_name": a["adset_name"],
                "campaign_name": a["campaign_name"],
                "meta_campaign_id": a["meta_campaign_id"],
                "spend": spend,
                "impressions": imp,
                "link_clicks": clicks,
                "ctr": (clicks / imp * 100) if imp > 0 else 0,
                "cpm": (spend / imp * 1000) if imp > 0 else 0,
                "cpc": (spend / clicks) if clicks > 0 else 0,
                "add_to_carts": a["add_to_carts"],
                "purchases": a["purchases"],
                "purchase_value": pv,
                "roas": (pv / spend) if spend > 0 else 0,
                "conversion_rate": (a["purchases"] / clicks * 100) if clicks > 0 else 0,
                "ad_count": len(a["ad_ids"]),
            })

        return result

    def _compute_period_totals(self, rows: List[Dict]) -> Dict[str, Any]:
        """Compute aggregate totals for a set of rows."""
        spend = sum(float(r.get("spend") or 0) for r in rows)
        impressions = sum(int(r.get("impressions") or 0) for r in rows)
        link_clicks = sum(int(r.get("link_clicks") or 0) for r in rows)
        purchases = sum(int(r.get("purchases") or 0) for r in rows)
        purchase_value = sum(float(r.get("purchase_value") or 0) for r in rows)
        add_to_carts = sum(int(r.get("add_to_carts") or 0) for r in rows)
        reach = sum(int(r.get("reach") or 0) for r in rows)

        unique_ads = len(set(r.get("meta_ad_id") for r in rows if r.get("meta_ad_id")))
        unique_campaigns = len(set(r.get("meta_campaign_id") for r in rows if r.get("meta_campaign_id")))

        return {
            "spend": spend,
            "impressions": impressions,
            "reach": reach,
            "link_clicks": link_clicks,
            "ctr": (link_clicks / impressions * 100) if impressions > 0 else 0,
            "cpm": (spend / impressions * 1000) if impressions > 0 else 0,
            "cpc": (spend / link_clicks) if link_clicks > 0 else 0,
            "add_to_carts": add_to_carts,
            "purchases": purchases,
            "purchase_value": purchase_value,
            "roas": (purchase_value / spend) if spend > 0 else 0,
            "conversion_rate": (purchases / link_clicks * 100) if link_clicks > 0 else 0,
            "unique_ads": unique_ads,
            "unique_campaigns": unique_campaigns,
        }

    def _compute_change(
        self, current: Dict[str, Any], previous: Dict[str, Any]
    ) -> Dict[str, Any]:
        """Compute percentage change between two period totals."""
        change = {}
        for key in ["spend", "impressions", "link_clicks", "purchases", "purchase_value",
                     "roas", "ctr", "cpm", "cpc", "add_to_carts", "conversion_rate"]:
            cur = current.get(key, 0) or 0
            prev = previous.get(key, 0) or 0
            if prev > 0:
                change[key] = ((cur - prev) / prev) * 100
            elif cur > 0:
                change[key] = 100.0  # New activity
            else:
                change[key] = 0.0
        return change
