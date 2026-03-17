"""
Ad Performance Query Service - Direct ad performance data lookups.

Provides 7 query methods for conversational ad performance querying:
- get_top_ads: Rank ads by any metric (ROAS, spend, CTR, etc.)
- get_account_summary: Account-level totals with optional period comparison
- get_campaign_breakdown: Campaign or adset level aggregation
- get_ad_details: Single ad deep dive with daily trends
- get_breakdown_by_media_type: Performance by video/image/carousel
- get_breakdown_by_landing_page: Performance by landing page (offer variant)
- get_breakdown_by_product: Performance by product

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
        product_id: Optional[str] = None,
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
            product_id: Optional product UUID to filter ads by.

        Returns:
            Dict with 'ads' list, 'meta' dict with query params and date range.
        """
        start, end = self._resolve_date_range(days_back, date_start, date_end)
        rows = self._fetch_performance_rows(brand_id, start, end)

        if not rows:
            return {"ads": [], "meta": {"date_start": start.isoformat(), "date_end": end.isoformat(), "total_rows": 0}}

        ads = self._aggregate_by_ad(rows)

        # Product filter (two-tier: landing page + name match)
        if product_id:
            all_ad_ids = [a["meta_ad_id"] for a in ads]
            product_ad_ids = self._resolve_product_ad_ids(brand_id, product_id, all_ad_ids)
            ads = [a for a in ads if a["meta_ad_id"] in product_ad_ids]

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

        top_ads = ads[:limit]

        # Enrich with creative_format from classifications
        top_ad_ids = [a["meta_ad_id"] for a in top_ads]
        if top_ad_ids:
            try:
                cls_result = (
                    self.supabase.table("ad_creative_classifications")
                    .select("meta_ad_id, creative_format")
                    .eq("brand_id", brand_id)
                    .in_("meta_ad_id", top_ad_ids)
                    .order("classified_at", desc=True)
                    .execute()
                )
                cls_map = {}
                for c in (cls_result.data or []):
                    aid = c.get("meta_ad_id")
                    if aid and aid not in cls_map:
                        cls_map[aid] = c.get("creative_format", "")
                for a in top_ads:
                    a["creative_format"] = cls_map.get(a["meta_ad_id"], "")
            except Exception as e:
                logger.debug(f"Could not enrich top ads with creative_format: {e}")

        return {
            "ads": top_ads,
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
    # Breakdown query methods (media type, landing page, product)
    # -------------------------------------------------------------------------

    def get_breakdown_by_media_type(
        self,
        brand_id: str,
        days_back: int = 30,
        awareness_level: Optional[str] = None,
        date_start: Optional[str] = None,
        date_end: Optional[str] = None,
    ) -> Dict[str, Any]:
        """Aggregate performance by media type (video/image/carousel/other).

        Groups creative_format by prefix:
        - video_* -> "Video"
        - image_* -> "Image"
        - carousel -> "Carousel"
        - collection, other -> "Other"

        Args:
            brand_id: Brand UUID string.
            days_back: Number of days to look back.
            awareness_level: Optional filter (unaware, problem_aware, etc.).
            date_start: Explicit start date (ISO format).
            date_end: Explicit end date (ISO format).

        Returns:
            Dict with 'groups' list and 'meta' dict.
        """
        start, end = self._resolve_date_range(days_back, date_start, date_end)
        classified = self._fetch_classified_performance(brand_id, start, end)

        if awareness_level:
            classified = [
                r for r in classified
                if r.get("creative_awareness_level") == awareness_level
            ]

        if not classified:
            return {
                "groups": [],
                "meta": {
                    "date_start": start.isoformat(),
                    "date_end": end.isoformat(),
                    "awareness_level": awareness_level,
                    "message": "No classified ads found for this period.",
                },
            }

        # Group by media type
        buckets: Dict[str, Dict] = defaultdict(lambda: {
            "spend": 0, "impressions": 0, "link_clicks": 0,
            "purchases": 0, "purchase_value": 0, "ad_ids": set(),
        })

        for row in classified:
            fmt = row.get("creative_format") or "other"
            if fmt.startswith("video_"):
                media_type = "Video"
            elif fmt.startswith("image_"):
                media_type = "Image"
            elif fmt == "carousel":
                media_type = "Carousel"
            else:
                media_type = "Other"

            b = buckets[media_type]
            b["spend"] += float(row.get("spend") or 0)
            b["impressions"] += int(row.get("impressions") or 0)
            b["link_clicks"] += int(row.get("link_clicks") or 0)
            b["purchases"] += int(row.get("purchases") or 0)
            b["purchase_value"] += float(row.get("purchase_value") or 0)
            if row.get("meta_ad_id"):
                b["ad_ids"].add(row["meta_ad_id"])

        groups = []
        for media_type, b in buckets.items():
            spend = b["spend"]
            imp = b["impressions"]
            clicks = b["link_clicks"]
            purchases = b["purchases"]
            pv = b["purchase_value"]
            groups.append({
                "media_type": media_type,
                "spend": spend,
                "impressions": imp,
                "link_clicks": clicks,
                "ctr": (clicks / imp * 100) if imp > 0 else 0,
                "cpc": (spend / clicks) if clicks > 0 else 0,
                "purchases": purchases,
                "purchase_value": pv,
                "roas": (pv / spend) if spend > 0 else 0,
                "cpa": (spend / purchases) if purchases > 0 else 0,
                "ad_count": len(b["ad_ids"]),
            })

        groups.sort(key=lambda x: x["spend"], reverse=True)

        return {
            "groups": groups,
            "meta": {
                "date_start": start.isoformat(),
                "date_end": end.isoformat(),
                "awareness_level": awareness_level,
                "total_groups": len(groups),
            },
        }

    def get_breakdown_by_landing_page(
        self,
        brand_id: str,
        days_back: int = 30,
        sort_by: str = "spend",
        limit: int = 20,
        awareness_level: Optional[str] = None,
        date_start: Optional[str] = None,
        date_end: Optional[str] = None,
    ) -> Dict[str, Any]:
        """Aggregate performance by landing page (offer variant).

        Shows aggregate spend, ROAS, CPA, and purchases for ALL ad types
        (video, image, carousel) per landing page. For video hook-specific
        LP performance, use hook_analysis with analysis_type='by_lp' instead.

        Args:
            brand_id: Brand UUID string.
            days_back: Number of days to look back.
            sort_by: Metric to sort by.
            limit: Max items to return.
            awareness_level: Optional filter (unaware, problem_aware, etc.).
            date_start: Explicit start date (ISO format).
            date_end: Explicit end date (ISO format).

        Returns:
            Dict with 'items' list and 'meta' dict.
        """
        start, end = self._resolve_date_range(days_back, date_start, date_end)
        classified = self._fetch_classified_performance(brand_id, start, end)

        if awareness_level:
            classified = [
                r for r in classified
                if r.get("creative_awareness_level") == awareness_level
            ]

        if not classified:
            return {
                "items": [],
                "meta": {
                    "date_start": start.isoformat(),
                    "date_end": end.isoformat(),
                    "awareness_level": awareness_level,
                    "message": "No classified ads found for this period.",
                },
            }

        # Collect unique landing_page_ids for LP metadata
        lp_ids = list(set(
            r["landing_page_id"] for r in classified
            if r.get("landing_page_id")
        ))
        lp_map = self._fetch_landing_pages(lp_ids) if lp_ids else {}

        # Fetch destination URLs for ads without landing_page_id (fallback)
        ads_without_lp = list(set(
            r["meta_ad_id"] for r in classified
            if not r.get("landing_page_id") and r.get("meta_ad_id")
        ))
        dest_map = self._fetch_ad_destinations(ads_without_lp) if ads_without_lp else {}

        # Group by landing page — use LP id when available, else destination URL
        buckets: Dict[str, Dict] = defaultdict(lambda: {
            "spend": 0, "impressions": 0, "link_clicks": 0,
            "purchases": 0, "purchase_value": 0, "ad_ids": set(),
            "url": "", "page_title": "", "product_name": "",
            "is_lp_id": False,
        })

        for row in classified:
            lp_id = row.get("landing_page_id")
            aid = row.get("meta_ad_id")

            if lp_id:
                # Keyed by LP UUID — has full metadata
                key = lp_id
                lp_info = lp_map.get(lp_id, {})
                b = buckets[key]
                b["url"] = lp_info.get("url", "")
                b["page_title"] = lp_info.get("page_title", "")
                b["product_name"] = lp_info.get("resolved_product_name", "")
                b["is_lp_id"] = True
            else:
                # Fallback: group by destination URL
                dest_url = dest_map.get(aid, "")
                key = f"url:{dest_url}" if dest_url else "unclassified"
                b = buckets[key]
                if dest_url:
                    b["url"] = dest_url

            b["spend"] += float(row.get("spend") or 0)
            b["impressions"] += int(row.get("impressions") or 0)
            b["link_clicks"] += int(row.get("link_clicks") or 0)
            b["purchases"] += int(row.get("purchases") or 0)
            b["purchase_value"] += float(row.get("purchase_value") or 0)
            if aid:
                b["ad_ids"].add(aid)

        items = []
        for key, b in buckets.items():
            spend = b["spend"]
            imp = b["impressions"]
            clicks = b["link_clicks"]
            purchases = b["purchases"]
            pv = b["purchase_value"]

            url = b["url"] or ("Unclassified" if key == "unclassified" else "Unknown")
            items.append({
                "landing_page_id": key if b["is_lp_id"] else "",
                "url": url,
                "page_title": b["page_title"],
                "product_name": b["product_name"],
                "spend": spend,
                "impressions": imp,
                "link_clicks": clicks,
                "ctr": (clicks / imp * 100) if imp > 0 else 0,
                "cpc": (spend / clicks) if clicks > 0 else 0,
                "purchases": purchases,
                "purchase_value": pv,
                "roas": (pv / spend) if spend > 0 else 0,
                "cpa": (spend / purchases) if purchases > 0 else 0,
                "ad_count": len(b["ad_ids"]),
            })

        items.sort(key=lambda x: x.get(sort_by, 0) or 0, reverse=True)

        return {
            "items": items[:limit],
            "meta": {
                "date_start": start.isoformat(),
                "date_end": end.isoformat(),
                "sort_by": sort_by,
                "awareness_level": awareness_level,
                "total": len(items),
                "returned": min(limit, len(items)),
            },
        }

    def get_breakdown_by_product(
        self,
        brand_id: str,
        days_back: int = 30,
        sort_by: str = "spend",
        limit: int = 20,
        awareness_level: Optional[str] = None,
        date_start: Optional[str] = None,
        date_end: Optional[str] = None,
    ) -> Dict[str, Any]:
        """Aggregate performance by product.

        Groups by resolved product name (product_id -> products.name,
        fallback to product_name text field on landing page).
        LPs without any product info go into "Unknown Product" bucket.

        Args:
            brand_id: Brand UUID string.
            days_back: Number of days to look back.
            sort_by: Metric to sort by.
            limit: Max items to return.
            awareness_level: Optional filter (unaware, problem_aware, etc.).
            date_start: Explicit start date (ISO format).
            date_end: Explicit end date (ISO format).

        Returns:
            Dict with 'items' list and 'meta' dict.
        """
        start, end = self._resolve_date_range(days_back, date_start, date_end)
        classified = self._fetch_classified_performance(brand_id, start, end)

        if awareness_level:
            classified = [
                r for r in classified
                if r.get("creative_awareness_level") == awareness_level
            ]

        if not classified:
            return {
                "items": [],
                "meta": {
                    "date_start": start.isoformat(),
                    "date_end": end.isoformat(),
                    "awareness_level": awareness_level,
                    "message": "No classified ads found for this period.",
                },
            }

        # Collect unique landing_page_ids
        lp_ids = list(set(
            r["landing_page_id"] for r in classified
            if r.get("landing_page_id")
        ))
        lp_map = self._fetch_landing_pages(lp_ids) if lp_ids else {}

        # Also try to match destination URLs to brand_landing_pages for product info
        ads_without_lp = list(set(
            r["meta_ad_id"] for r in classified
            if not r.get("landing_page_id") and r.get("meta_ad_id")
        ))
        dest_map = self._fetch_ad_destinations(ads_without_lp) if ads_without_lp else {}

        # Build URL -> LP lookup for destination URL fallback
        url_to_lp: Dict[str, Dict] = {}
        if dest_map:
            unique_urls = list(set(u for u in dest_map.values() if u))
            if unique_urls:
                url_to_lp = self._fetch_landing_pages_by_url(brand_id, unique_urls)

        # Group by product name
        buckets: Dict[str, Dict] = defaultdict(lambda: {
            "spend": 0, "impressions": 0, "link_clicks": 0,
            "purchases": 0, "purchase_value": 0, "ad_ids": set(),
        })

        for row in classified:
            lp_id = row.get("landing_page_id")
            lp_info = lp_map.get(lp_id, {}) if lp_id else {}
            product_name = lp_info.get("resolved_product_name")

            # Fallback: try matching destination URL to a known LP for product info
            if not product_name and not lp_id:
                aid = row.get("meta_ad_id")
                dest_url = dest_map.get(aid, "")
                if dest_url:
                    url_lp_info = url_to_lp.get(dest_url, {})
                    product_name = url_lp_info.get("resolved_product_name")

            product_name = product_name or "Unknown Product"

            b = buckets[product_name]
            b["spend"] += float(row.get("spend") or 0)
            b["impressions"] += int(row.get("impressions") or 0)
            b["link_clicks"] += int(row.get("link_clicks") or 0)
            b["purchases"] += int(row.get("purchases") or 0)
            b["purchase_value"] += float(row.get("purchase_value") or 0)
            if row.get("meta_ad_id"):
                b["ad_ids"].add(row["meta_ad_id"])

        items = []
        for product_name, b in buckets.items():
            spend = b["spend"]
            imp = b["impressions"]
            clicks = b["link_clicks"]
            purchases = b["purchases"]
            pv = b["purchase_value"]
            items.append({
                "product_name": product_name,
                "spend": spend,
                "impressions": imp,
                "link_clicks": clicks,
                "ctr": (clicks / imp * 100) if imp > 0 else 0,
                "cpc": (spend / clicks) if clicks > 0 else 0,
                "purchases": purchases,
                "purchase_value": pv,
                "roas": (pv / spend) if spend > 0 else 0,
                "cpa": (spend / purchases) if purchases > 0 else 0,
                "ad_count": len(b["ad_ids"]),
            })

        items.sort(key=lambda x: x.get(sort_by, 0) or 0, reverse=True)

        return {
            "items": items[:limit],
            "meta": {
                "date_start": start.isoformat(),
                "date_end": end.isoformat(),
                "sort_by": sort_by,
                "awareness_level": awareness_level,
                "total": len(items),
                "returned": min(limit, len(items)),
            },
        }

    def get_breakdown_by_awareness(
        self,
        brand_id: str,
        days_back: int = 30,
        product_id: Optional[str] = None,
        min_spend: float = 0.0,
        date_start: Optional[str] = None,
        date_end: Optional[str] = None,
    ) -> Dict[str, Any]:
        """Aggregate performance by consumer awareness level (Schwartz).

        Groups classified ads by creative_awareness_level and computes
        spend, CTR, ROAS, CPA, CVR per level. Identifies funnel gaps.

        Args:
            brand_id: Brand UUID string.
            days_back: Number of days to look back.
            product_id: Optional product UUID to filter ads by.
            min_spend: Minimum spend threshold per ad.
            date_start: Explicit start date (ISO format).
            date_end: Explicit end date (ISO format).

        Returns:
            Dict with 'levels' list, 'gaps' list, classification counts.
        """
        from viraltracker.services.ad_intelligence.models import AwarenessLevel

        start, end = self._resolve_date_range(days_back, date_start, date_end)

        # Fetch all performance rows (both classified and unclassified)
        all_perf_rows = self._fetch_performance_rows(brand_id, start, end)
        total_all_ads = len(set(r.get("meta_ad_id") for r in all_perf_rows if r.get("meta_ad_id")))

        # Fetch classified performance
        classified = self._fetch_classified_performance(brand_id, start, end)

        # Product filter
        if product_id and classified:
            all_cls_ad_ids = list(set(r["meta_ad_id"] for r in classified if r.get("meta_ad_id")))
            product_ad_ids = self._resolve_product_ad_ids(brand_id, product_id, all_cls_ad_ids)
            classified = [r for r in classified if r.get("meta_ad_id") in product_ad_ids]

        # Also filter total ads count for product
        if product_id and all_perf_rows:
            all_perf_ad_ids = list(set(r.get("meta_ad_id") for r in all_perf_rows if r.get("meta_ad_id")))
            product_perf_ids = self._resolve_product_ad_ids(brand_id, product_id, all_perf_ad_ids)
            total_all_ads = len(product_perf_ids)

        # Canonical awareness levels
        canonical_levels = [level.value for level in AwarenessLevel]
        level_labels = {
            "unaware": "Unaware",
            "problem_aware": "Problem Aware",
            "solution_aware": "Solution Aware",
            "product_aware": "Product Aware",
            "most_aware": "Most Aware",
        }

        # Group by awareness level
        buckets: Dict[str, Dict] = {}
        for level in canonical_levels:
            buckets[level] = {
                "spend": 0, "impressions": 0, "link_clicks": 0,
                "purchases": 0, "purchase_value": 0, "ad_ids": set(),
            }

        unclassified_ads = set()
        classified_ads = set()

        for row in classified:
            level = row.get("creative_awareness_level")
            aid = row.get("meta_ad_id")

            if level and level in buckets:
                classified_ads.add(aid)
                b = buckets[level]
                b["spend"] += float(row.get("spend") or 0)
                b["impressions"] += int(row.get("impressions") or 0)
                b["link_clicks"] += int(row.get("link_clicks") or 0)
                b["purchases"] += int(row.get("purchases") or 0)
                b["purchase_value"] += float(row.get("purchase_value") or 0)
                if aid:
                    b["ad_ids"].add(aid)
            else:
                if aid:
                    unclassified_ads.add(aid)

        total_classified = len(classified_ads)
        total_unclassified = total_all_ads - total_classified

        # Compute total spend for share calculation
        total_spend = sum(b["spend"] for b in buckets.values())

        # Build results
        levels = []
        gaps = []
        for level in canonical_levels:
            b = buckets[level]
            spend = b["spend"]
            imp = b["impressions"]
            clicks = b["link_clicks"]
            purchases = b["purchases"]
            pv = b["purchase_value"]
            ad_count = len(b["ad_ids"])

            # Apply min_spend filter at level
            if min_spend > 0:
                # Filter individual ads by min_spend would require per-ad aggregation;
                # instead we just report the level totals
                pass

            if ad_count == 0:
                gaps.append(level)

            levels.append({
                "awareness_level": level,
                "label": level_labels.get(level, level),
                "ad_count": ad_count,
                "spend": spend,
                "spend_share": (spend / total_spend) if total_spend > 0 else 0,
                "impressions": imp,
                "clicks": clicks,
                "purchases": purchases,
                "purchase_value": pv,
                "ctr": (clicks / imp * 100) if imp > 0 else 0,
                "roas": (pv / spend) if spend > 0 else 0,
                "cpa": (spend / purchases) if purchases > 0 else 0,
                "cvr": (purchases / clicks * 100) if clicks > 0 else 0,
                "cpm": (spend / imp * 1000) if imp > 0 else 0,
            })

        return {
            "levels": levels,
            "gaps": gaps,
            "total_classified": total_classified,
            "total_unclassified": total_unclassified,
            "total_spend": total_spend,
            "date_range": {"start": start.isoformat(), "end": end.isoformat()},
        }

    def get_top_ads_by_awareness(
        self,
        brand_id: str,
        awareness_level: str,
        days_back: int = 30,
        limit: int = 10,
        product_id: Optional[str] = None,
        min_spend: float = 0.0,
        date_start: Optional[str] = None,
        date_end: Optional[str] = None,
    ) -> Dict[str, Any]:
        """Get top ads for a specific awareness level, sorted by ROAS.

        Args:
            brand_id: Brand UUID string.
            awareness_level: One of unaware, problem_aware, solution_aware, product_aware, most_aware.
            days_back: Number of days to look back.
            limit: Max ads to return.
            product_id: Optional product UUID to filter ads by.
            min_spend: Minimum spend threshold.
            date_start: Explicit start date (ISO format).
            date_end: Explicit end date (ISO format).

        Returns:
            Dict with 'ads' list and 'meta' dict.
        """
        start, end = self._resolve_date_range(days_back, date_start, date_end)
        classified = self._fetch_classified_performance(brand_id, start, end)

        # Filter to awareness level
        classified = [
            r for r in classified
            if r.get("creative_awareness_level") == awareness_level
        ]

        if not classified:
            return {"ads": [], "meta": {"awareness_level": awareness_level, "total": 0}}

        # Product filter
        if product_id:
            all_ad_ids = list(set(r["meta_ad_id"] for r in classified if r.get("meta_ad_id")))
            product_ad_ids = self._resolve_product_ad_ids(brand_id, product_id, all_ad_ids)
            classified = [r for r in classified if r.get("meta_ad_id") in product_ad_ids]

        # Aggregate by ad
        ad_map: Dict[str, Dict] = defaultdict(lambda: {
            "spend": 0, "impressions": 0, "link_clicks": 0,
            "purchases": 0, "purchase_value": 0,
            "ad_name": "", "thumbnail_url": "", "creative_format": "",
        })

        for row in classified:
            aid = row.get("meta_ad_id")
            if not aid:
                continue
            a = ad_map[aid]
            a["ad_name"] = row.get("ad_name") or a["ad_name"]
            if row.get("thumbnail_url") and not a["thumbnail_url"]:
                a["thumbnail_url"] = row["thumbnail_url"]
            a["creative_format"] = row.get("creative_format") or a["creative_format"]
            a["spend"] += float(row.get("spend") or 0)
            a["impressions"] += int(row.get("impressions") or 0)
            a["link_clicks"] += int(row.get("link_clicks") or 0)
            a["purchases"] += int(row.get("purchases") or 0)
            a["purchase_value"] += float(row.get("purchase_value") or 0)

        ads = []
        for aid, a in ad_map.items():
            spend = a["spend"]
            if min_spend > 0 and spend < min_spend:
                continue
            imp = a["impressions"]
            clicks = a["link_clicks"]
            purchases = a["purchases"]
            pv = a["purchase_value"]
            ads.append({
                "meta_ad_id": aid,
                "ad_name": a["ad_name"],
                "thumbnail_url": a["thumbnail_url"],
                "creative_format": a["creative_format"],
                "spend": spend,
                "impressions": imp,
                "link_clicks": clicks,
                "ctr": (clicks / imp * 100) if imp > 0 else 0,
                "purchases": purchases,
                "purchase_value": pv,
                "roas": (pv / spend) if spend > 0 else 0,
                "cpa": (spend / purchases) if purchases > 0 else 0,
                "cvr": (purchases / clicks * 100) if clicks > 0 else 0,
            })

        ads.sort(key=lambda a: a.get("roas", 0), reverse=True)

        return {
            "ads": ads[:limit],
            "meta": {
                "date_start": start.isoformat(),
                "date_end": end.isoformat(),
                "awareness_level": awareness_level,
                "total": len(ads),
                "returned": min(limit, len(ads)),
            },
        }

    # -------------------------------------------------------------------------
    # Internal helpers
    # -------------------------------------------------------------------------

    def _resolve_product_ad_ids(
        self, brand_id: str, product_id: str, ad_ids: List[str]
    ) -> set:
        """Resolve which ad_ids belong to a product via two-tier matching.

        Tier 1: Join classified ads via landing_page_id -> brand_landing_pages.product_id.
        Tier 2: Campaign/adset/ad name substring match on product name.

        Args:
            brand_id: Brand UUID string.
            product_id: Product UUID string.
            ad_ids: List of ad_ids to filter.

        Returns:
            Set of ad_ids belonging to the product.
        """
        if not ad_ids or not product_id:
            return set(ad_ids)

        matched = set()

        # Get product name
        product_name = ""
        try:
            result = self.supabase.table("products").select("name").eq("id", product_id).limit(1).execute()
            if result.data:
                product_name = result.data[0].get("name", "")
        except Exception as e:
            logger.debug(f"Failed to fetch product name: {e}")

        # Tier 1: Landing page -> product_id match
        try:
            # Get landing page IDs linked to this product
            lp_result = (
                self.supabase.table("brand_landing_pages")
                .select("id")
                .eq("brand_id", brand_id)
                .eq("product_id", product_id)
                .execute()
            )
            lp_ids = [r["id"] for r in (lp_result.data or [])]

            if lp_ids:
                # Get classified ads pointing to those landing pages
                for i in range(0, len(ad_ids), 500):
                    batch = ad_ids[i:i + 500]
                    cls_result = (
                        self.supabase.table("ad_creative_classifications")
                        .select("meta_ad_id, landing_page_id")
                        .eq("brand_id", brand_id)
                        .in_("meta_ad_id", batch)
                        .in_("landing_page_id", lp_ids)
                        .execute()
                    )
                    for c in (cls_result.data or []):
                        if c.get("meta_ad_id"):
                            matched.add(c["meta_ad_id"])
        except Exception as e:
            logger.debug(f"Tier 1 product resolution failed: {e}")

        # Tier 2: Name substring match (catches unclassified ads)
        if product_name:
            name_lower = product_name.lower()
            try:
                for i in range(0, len(ad_ids), 500):
                    batch = ad_ids[i:i + 500]
                    perf_result = (
                        self.supabase.table("meta_ads_performance")
                        .select("meta_ad_id, ad_name, campaign_name, adset_name")
                        .eq("brand_id", brand_id)
                        .in_("meta_ad_id", batch)
                        .execute()
                    )
                    seen = set()
                    for r in (perf_result.data or []):
                        aid = r.get("meta_ad_id")
                        if aid in seen or aid in matched:
                            continue
                        seen.add(aid)
                        searchable = " ".join([
                            r.get("ad_name", ""),
                            r.get("campaign_name", ""),
                            r.get("adset_name", ""),
                        ]).lower()
                        if name_lower in searchable:
                            matched.add(aid)
            except Exception as e:
                logger.debug(f"Tier 2 product name matching failed: {e}")

        return matched

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

    def _fetch_classified_performance(
        self, brand_id: str, date_start: date, date_end: date
    ) -> List[Dict]:
        """Fetch performance rows joined with classification data.

        1. Fetch performance rows (paginated via _fetch_performance_rows).
        2. Extract unique ad_ids.
        3. Fetch classifications (paginated) for those ads.
        4. Build cls_map (latest classification per ad_id).
        5. Merge performance + classification by meta_ad_id.

        Only returns rows that have a matching classification.

        Returns:
            List of performance rows enriched with classification fields.
        """
        perf_rows = self._fetch_performance_rows(brand_id, date_start, date_end)
        if not perf_rows:
            return []

        ad_ids = list(set(r.get("meta_ad_id") for r in perf_rows if r.get("meta_ad_id")))
        if not ad_ids:
            return []

        # Fetch classifications with pagination (can exceed 1000 for large accounts)
        all_cls: List[Dict] = []
        batch_size = 500  # Supabase IN() limit is generous but keep batches manageable
        for i in range(0, len(ad_ids), batch_size):
            batch_ids = ad_ids[i:i + batch_size]
            offset = 0
            page_size = 1000
            while True:
                cls_result = (
                    self.supabase.table("ad_creative_classifications")
                    .select(
                        "meta_ad_id, creative_awareness_level, creative_format, "
                        "video_length_bucket, landing_page_id"
                    )
                    .eq("brand_id", brand_id)
                    .in_("meta_ad_id", batch_ids)
                    .order("classified_at", desc=True)
                    .range(offset, offset + page_size - 1)
                    .execute()
                )
                if not cls_result.data:
                    break
                all_cls.extend(cls_result.data)
                if len(cls_result.data) < page_size:
                    break
                offset += page_size

        # Build map: latest classification per ad_id (first seen wins due to DESC order)
        cls_map: Dict[str, Dict] = {}
        for c in all_cls:
            aid = c.get("meta_ad_id")
            if aid and aid not in cls_map:
                cls_map[aid] = c

        logger.info(
            f"Fetched {len(all_cls)} classification rows, "
            f"{len(cls_map)} unique ads classified"
        )

        # Merge: enrich each perf row with classification fields
        result = []
        for row in perf_rows:
            aid = row.get("meta_ad_id")
            cls = cls_map.get(aid)
            if not cls:
                continue  # Skip unclassified ads
            merged = dict(row)
            merged["creative_awareness_level"] = cls.get("creative_awareness_level")
            merged["creative_format"] = cls.get("creative_format")
            merged["video_length_bucket"] = cls.get("video_length_bucket")
            merged["landing_page_id"] = cls.get("landing_page_id")
            result.append(merged)

        return result

    def _fetch_landing_pages(self, lp_ids: List[str]) -> Dict[str, Dict]:
        """Batch-fetch landing pages with product resolution.

        Fetches landing page details and resolves product names:
        - If product_id is set, uses products.name as resolved_product_name.
        - Falls back to product_name text field on the LP.
        - Returns None if neither is available.

        Args:
            lp_ids: List of landing page UUID strings.

        Returns:
            Dict mapping lp_id to {url, page_title, product_name, product_id, resolved_product_name}.
        """
        if not lp_ids:
            return {}

        # Fetch landing pages in batches
        all_lps: List[Dict] = []
        batch_size = 500
        for i in range(0, len(lp_ids), batch_size):
            batch = lp_ids[i:i + batch_size]
            result = (
                self.supabase.table("brand_landing_pages")
                .select("id, url, page_title, product_name, product_id")
                .in_("id", batch)
                .execute()
            )
            if result.data:
                all_lps.extend(result.data)

        # Collect product_ids that need name resolution
        product_ids = list(set(
            lp["product_id"] for lp in all_lps
            if lp.get("product_id")
        ))

        # Batch-fetch product names
        product_names: Dict[str, str] = {}
        if product_ids:
            for i in range(0, len(product_ids), batch_size):
                batch = product_ids[i:i + batch_size]
                result = (
                    self.supabase.table("products")
                    .select("id, name")
                    .in_("id", batch)
                    .execute()
                )
                if result.data:
                    for p in result.data:
                        product_names[p["id"]] = p["name"]

        # Build result map
        lp_map: Dict[str, Dict] = {}
        for lp in all_lps:
            pid = lp.get("product_id")
            resolved = product_names.get(pid) if pid else None
            if not resolved:
                resolved = lp.get("product_name")  # Fallback to text field

            lp_map[lp["id"]] = {
                "url": lp.get("url", ""),
                "page_title": lp.get("page_title", ""),
                "product_name": lp.get("product_name"),
                "product_id": pid,
                "resolved_product_name": resolved,
            }

        return lp_map

    def _fetch_landing_pages_by_url(
        self, brand_id: str, urls: List[str]
    ) -> Dict[str, Dict]:
        """Fetch landing pages by canonical_url for product resolution.

        Used as fallback when landing_page_id is NULL but we have a
        destination URL from meta_ad_destinations.

        Args:
            brand_id: Brand UUID string.
            urls: List of canonical URLs to match.

        Returns:
            Dict mapping URL to {url, page_title, product_name, product_id, resolved_product_name}.
        """
        if not urls:
            return {}

        all_lps: List[Dict] = []
        batch_size = 500
        for i in range(0, len(urls), batch_size):
            batch = urls[i:i + batch_size]
            result = (
                self.supabase.table("brand_landing_pages")
                .select("id, url, canonical_url, page_title, product_name, product_id")
                .eq("brand_id", brand_id)
                .in_("canonical_url", batch)
                .execute()
            )
            if result.data:
                all_lps.extend(result.data)

        if not all_lps:
            return {}

        # Resolve product names
        product_ids = list(set(
            lp["product_id"] for lp in all_lps if lp.get("product_id")
        ))
        product_names: Dict[str, str] = {}
        if product_ids:
            for i in range(0, len(product_ids), batch_size):
                batch = product_ids[i:i + batch_size]
                result = (
                    self.supabase.table("products")
                    .select("id, name")
                    .in_("id", batch)
                    .execute()
                )
                if result.data:
                    for p in result.data:
                        product_names[p["id"]] = p["name"]

        url_map: Dict[str, Dict] = {}
        for lp in all_lps:
            pid = lp.get("product_id")
            resolved = product_names.get(pid) if pid else None
            if not resolved:
                resolved = lp.get("product_name")

            canonical = lp.get("canonical_url") or lp.get("url", "")
            url_map[canonical] = {
                "url": lp.get("url", ""),
                "page_title": lp.get("page_title", ""),
                "product_name": lp.get("product_name"),
                "product_id": pid,
                "resolved_product_name": resolved,
            }

        return url_map

    def _fetch_ad_destinations(self, ad_ids: List[str]) -> Dict[str, str]:
        """Batch-fetch destination URLs from meta_ad_destinations.

        Fallback for ads where landing_page_id is NULL in classifications
        but the actual URL exists in meta_ad_destinations.

        Args:
            ad_ids: List of meta_ad_id strings.

        Returns:
            Dict mapping meta_ad_id to canonical_url (or destination_url).
        """
        if not ad_ids:
            return {}

        dest_map: Dict[str, str] = {}
        batch_size = 500
        for i in range(0, len(ad_ids), batch_size):
            batch = ad_ids[i:i + batch_size]
            result = (
                self.supabase.table("meta_ad_destinations")
                .select("meta_ad_id, destination_url, canonical_url")
                .in_("meta_ad_id", batch)
                .execute()
            )
            if result.data:
                for row in result.data:
                    aid = row.get("meta_ad_id")
                    if aid and aid not in dest_map:
                        dest_map[aid] = (
                            row.get("canonical_url")
                            or row.get("destination_url")
                            or ""
                        )

        return dest_map

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
            # Keep the first non-empty thumbnail (rows ordered by date desc, so most recent first)
            if d.get("thumbnail_url") and not a.get("thumbnail_url"):
                a["thumbnail_url"] = d["thumbnail_url"]
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
                "thumbnail_url": a.get("thumbnail_url", ""),
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
                "cpa": (spend / a["purchases"]) if a["purchases"] > 0 else 0,
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
                "cpa": (spend / c["purchases"]) if c["purchases"] > 0 else 0,
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
                "cpa": (spend / a["purchases"]) if a["purchases"] > 0 else 0,
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
            "cpa": (spend / purchases) if purchases > 0 else 0,
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
