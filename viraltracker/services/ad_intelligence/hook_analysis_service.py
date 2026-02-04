"""HookAnalysisService - Analyze hook performance across video ads.

Provides comprehensive hook analysis for Phase 7 of Deep Video Analysis:
- Top hooks by fingerprint with flexible sorting (ROAS, hook rate, spend, CTR)
- Hook aggregation by type, visual type, and landing page
- Quadrant analysis (hook rate vs ROAS)
- Gap analysis for untested hook types
- Detailed hook comparison and insights

Key metrics:
- Hook Rate = video_views / impressions (% viewers past first 3 seconds)
- ROAS = purchase_value / spend
- Supports configurable minimum spend threshold to filter noise
"""

from __future__ import annotations

import logging
from datetime import date, timedelta
from typing import Any, Dict, List, Optional
from uuid import UUID

from .helpers import _safe_numeric

logger = logging.getLogger(__name__)

# Default thresholds
DEFAULT_MIN_SPEND = 100.0  # Minimum $100 spend for statistical significance
DEFAULT_HOOK_RATE_THRESHOLD = 0.25  # 25% = good hook rate
DEFAULT_ROAS_THRESHOLD = 1.0  # 1.0 = breakeven

# All possible hook types for gap analysis
ALL_HOOK_TYPES = [
    "question", "claim", "story", "callout", "transformation",
    "shock", "relatable", "statistic", "before_after", "authority", "other"
]

# All possible visual hook types for gap analysis
ALL_VISUAL_HOOK_TYPES = [
    "unboxing", "transformation", "demonstration", "testimonial",
    "lifestyle", "problem_agitation", "authority", "social_proof",
    "product_hero", "curiosity", "other"
]


class HookAnalysisService:
    """Service for analyzing hook performance across video ads.

    Joins ad_video_analysis (hook data) with meta_ads_performance (metrics)
    to surface which hooks work best for data-driven creative decisions.
    """

    def __init__(self, supabase_client):
        """Initialize HookAnalysisService.

        Args:
            supabase_client: Supabase client instance.
        """
        self.supabase = supabase_client

    # =========================================================================
    # Core Aggregation Methods
    # =========================================================================

    def get_top_hooks_by_fingerprint(
        self,
        brand_id: UUID,
        limit: int = 20,
        min_spend: float = DEFAULT_MIN_SPEND,
        date_range_days: int = 30,
        sort_by: str = "roas",  # roas, hook_rate, spend, ctr, cpa
        sort_order: str = "desc"
    ) -> List[Dict]:
        """Get top performing hooks by unique fingerprint.

        Returns hooks grouped by fingerprint with aggregated performance metrics.

        Args:
            brand_id: Brand UUID.
            limit: Maximum hooks to return.
            min_spend: Minimum total spend threshold.
            date_range_days: Number of days to look back.
            sort_by: Sort metric (roas, hook_rate, spend, ctr, cpa).
            sort_order: Sort order (asc or desc).

        Returns:
            List of hook dicts with:
            - hook_fingerprint, hook_type, hook_visual_type
            - hook_transcript_spoken, hook_transcript_overlay
            - hook_visual_description, hook_visual_elements
            - ad_count, total_spend, avg_roas, avg_ctr, avg_hook_rate
            - example_ad_ids (top 3 by spend)
        """
        try:
            date_cutoff = (date.today() - timedelta(days=date_range_days)).isoformat()

            # Get all video analysis records with performance data
            # Note: We join in Python due to Supabase limitations
            video_analysis_result = self.supabase.table("ad_video_analysis").select(
                "meta_ad_id, hook_fingerprint, hook_type, hook_visual_type, "
                "hook_transcript_spoken, hook_transcript_overlay, "
                "hook_visual_description, hook_visual_elements"
            ).eq(
                "brand_id", str(brand_id)
            ).not_.is_("hook_fingerprint", "null").execute()

            if not video_analysis_result.data:
                return []

            # Get performance data for the date range
            perf_result = self.supabase.table("meta_ads_performance").select(
                "meta_ad_id, spend, impressions, video_views, "
                "purchase_value, purchases, link_ctr, date"
            ).eq(
                "brand_id", str(brand_id)
            ).gte(
                "date", date_cutoff
            ).execute()

            if not perf_result.data:
                return []

            # Build lookup: meta_ad_id -> video analysis data
            ad_to_hook: Dict[str, Dict] = {}
            for row in video_analysis_result.data:
                ad_id = row.get("meta_ad_id")
                if ad_id and row.get("hook_fingerprint"):
                    ad_to_hook[ad_id] = row

            # Aggregate performance by hook fingerprint
            fingerprint_stats: Dict[str, Dict[str, Any]] = {}

            for perf in perf_result.data:
                ad_id = perf.get("meta_ad_id")
                if ad_id not in ad_to_hook:
                    continue

                hook_data = ad_to_hook[ad_id]
                fp = hook_data["hook_fingerprint"]

                if fp not in fingerprint_stats:
                    fingerprint_stats[fp] = {
                        "hook_fingerprint": fp,
                        "hook_type": hook_data.get("hook_type"),
                        "hook_visual_type": hook_data.get("hook_visual_type"),
                        "hook_transcript_spoken": hook_data.get("hook_transcript_spoken"),
                        "hook_transcript_overlay": hook_data.get("hook_transcript_overlay"),
                        "hook_visual_description": hook_data.get("hook_visual_description"),
                        "hook_visual_elements": hook_data.get("hook_visual_elements", []),
                        "ad_ids": set(),
                        "total_spend": 0.0,
                        "total_impressions": 0,
                        "total_video_views": 0,
                        "total_purchase_value": 0.0,
                        "total_purchases": 0,
                        "ctr_sum": 0.0,
                        "ctr_count": 0,
                        "ad_spend_list": [],  # For sorting example ads
                    }

                stats = fingerprint_stats[fp]
                stats["ad_ids"].add(ad_id)

                spend = _safe_numeric(perf.get("spend")) or 0.0
                stats["total_spend"] += spend
                stats["total_impressions"] += _safe_numeric(perf.get("impressions")) or 0
                stats["total_video_views"] += _safe_numeric(perf.get("video_views")) or 0
                stats["total_purchase_value"] += _safe_numeric(perf.get("purchase_value")) or 0.0
                stats["total_purchases"] += int(_safe_numeric(perf.get("purchases")) or 0)

                ctr = _safe_numeric(perf.get("link_ctr"))
                if ctr is not None:
                    stats["ctr_sum"] += ctr
                    stats["ctr_count"] += 1

                stats["ad_spend_list"].append((ad_id, spend))

            # Compute derived metrics and filter by min_spend
            results = []
            for fp, stats in fingerprint_stats.items():
                if stats["total_spend"] < min_spend:
                    continue

                ad_count = len(stats["ad_ids"])
                avg_roas = (
                    stats["total_purchase_value"] / stats["total_spend"]
                    if stats["total_spend"] > 0 else 0.0
                )
                avg_ctr = (
                    stats["ctr_sum"] / stats["ctr_count"]
                    if stats["ctr_count"] > 0 else 0.0
                )
                avg_hook_rate = (
                    stats["total_video_views"] / stats["total_impressions"]
                    if stats["total_impressions"] > 0 else 0.0
                )
                cpa = (
                    stats["total_spend"] / stats["total_purchases"]
                    if stats["total_purchases"] > 0 else None
                )

                # Get top 3 example ads by spend
                sorted_ads = sorted(stats["ad_spend_list"], key=lambda x: x[1], reverse=True)
                example_ad_ids = [ad_id for ad_id, _ in sorted_ads[:3]]

                results.append({
                    "hook_fingerprint": fp,
                    "hook_type": stats["hook_type"],
                    "hook_visual_type": stats["hook_visual_type"],
                    "hook_transcript_spoken": stats["hook_transcript_spoken"],
                    "hook_transcript_overlay": stats["hook_transcript_overlay"],
                    "hook_visual_description": stats["hook_visual_description"],
                    "hook_visual_elements": stats["hook_visual_elements"],
                    "ad_count": ad_count,
                    "total_spend": round(stats["total_spend"], 2),
                    "avg_roas": round(avg_roas, 2),
                    "avg_ctr": round(avg_ctr, 4),
                    "avg_hook_rate": round(avg_hook_rate, 4),
                    "cpa": round(cpa, 2) if cpa else None,
                    "total_purchases": stats["total_purchases"],
                    "example_ad_ids": example_ad_ids,
                })

            # Sort results
            sort_key_map = {
                "roas": "avg_roas",
                "hook_rate": "avg_hook_rate",
                "spend": "total_spend",
                "ctr": "avg_ctr",
                "cpa": "cpa",
            }
            sort_key = sort_key_map.get(sort_by, "avg_roas")
            reverse = sort_order.lower() == "desc"

            # Handle None values in CPA
            if sort_key == "cpa":
                results = sorted(
                    results,
                    key=lambda x: (x[sort_key] is None, x[sort_key] or 0),
                    reverse=reverse
                )
            else:
                results = sorted(results, key=lambda x: x[sort_key], reverse=reverse)

            return results[:limit]

        except Exception as e:
            logger.error(f"Error getting top hooks by fingerprint for brand {brand_id}: {e}")
            return []

    def get_hooks_by_quadrant(
        self,
        brand_id: UUID,
        date_range_days: int = 30,
        min_spend: float = DEFAULT_MIN_SPEND,
        hook_rate_threshold: float = DEFAULT_HOOK_RATE_THRESHOLD,
        roas_threshold: float = DEFAULT_ROAS_THRESHOLD
    ) -> Dict[str, List[Dict]]:
        """Categorize hooks into quadrants based on hook_rate vs ROAS.

        Quadrant analysis reveals actionable patterns:
        - Winners: High hook rate + High ROAS -> Scale these
        - Hidden Gems: Low hook rate + High ROAS -> Investigate why low engagement
        - Engaging but Not Converting: High hook rate + Low ROAS -> Fix downstream
        - Losers: Low hook rate + Low ROAS -> Kill these

        Args:
            brand_id: Brand UUID.
            date_range_days: Number of days to look back.
            min_spend: Minimum spend threshold.
            hook_rate_threshold: Threshold for "high" hook rate (default 25%).
            roas_threshold: Threshold for "high" ROAS (default 1.0 = breakeven).

        Returns:
            Dict with quadrant keys: winners, hidden_gems,
            engaging_not_converting, losers. Each contains list of hook dicts.
        """
        try:
            # Get all hooks with metrics
            all_hooks = self.get_top_hooks_by_fingerprint(
                brand_id=brand_id,
                limit=1000,  # Get all
                min_spend=min_spend,
                date_range_days=date_range_days,
                sort_by="spend"
            )

            quadrants: Dict[str, List[Dict]] = {
                "winners": [],
                "hidden_gems": [],
                "engaging_not_converting": [],
                "losers": [],
            }

            for hook in all_hooks:
                hook_rate = hook["avg_hook_rate"]
                roas = hook["avg_roas"]

                high_hook_rate = hook_rate >= hook_rate_threshold
                high_roas = roas >= roas_threshold

                # Add suggested action to each hook
                hook = hook.copy()

                if high_hook_rate and high_roas:
                    hook["suggested_action"] = "SCALE - This hook is performing well on both engagement and conversion"
                    hook["quadrant"] = "winners"
                    quadrants["winners"].append(hook)
                elif not high_hook_rate and high_roas:
                    hook["suggested_action"] = "INVESTIGATE - Good ROAS but low engagement. Why aren't more people watching?"
                    hook["quadrant"] = "hidden_gems"
                    quadrants["hidden_gems"].append(hook)
                elif high_hook_rate and not high_roas:
                    hook["suggested_action"] = "FIX DOWNSTREAM - Hook is engaging but not converting. Check LP, offer, or video body"
                    hook["quadrant"] = "engaging_not_converting"
                    quadrants["engaging_not_converting"].append(hook)
                else:
                    hook["suggested_action"] = "KILL - Low engagement and low conversion. Replace with new creative"
                    hook["quadrant"] = "losers"
                    quadrants["losers"].append(hook)

            # Sort each quadrant by spend (most investment first)
            for key in quadrants:
                quadrants[key] = sorted(
                    quadrants[key],
                    key=lambda x: x["total_spend"],
                    reverse=True
                )

            return quadrants

        except Exception as e:
            logger.error(f"Error getting hooks by quadrant for brand {brand_id}: {e}")
            return {
                "winners": [],
                "hidden_gems": [],
                "engaging_not_converting": [],
                "losers": [],
            }

    def get_high_hook_rate_low_roas(
        self,
        brand_id: UUID,
        date_range_days: int = 30,
        min_spend: float = DEFAULT_MIN_SPEND,
        hook_rate_threshold: float = DEFAULT_HOOK_RATE_THRESHOLD,
        roas_threshold: float = DEFAULT_ROAS_THRESHOLD,
        limit: int = 10
    ) -> List[Dict]:
        """Get hooks with high engagement but poor conversion.

        These hooks are WORKING to grab attention but something downstream
        is broken (landing page mismatch, weak offer, bad video body, etc.).

        Args:
            brand_id: Brand UUID.
            date_range_days: Number of days to look back.
            min_spend: Minimum spend threshold.
            hook_rate_threshold: Threshold for "high" hook rate.
            roas_threshold: Threshold for "low" ROAS (below this is bad).
            limit: Maximum hooks to return.

        Returns:
            List of hook dicts with diagnostic suggestions.
        """
        try:
            quadrants = self.get_hooks_by_quadrant(
                brand_id=brand_id,
                date_range_days=date_range_days,
                min_spend=min_spend,
                hook_rate_threshold=hook_rate_threshold,
                roas_threshold=roas_threshold
            )

            # Add diagnostic suggestions for each hook
            results = []
            for hook in quadrants["engaging_not_converting"][:limit]:
                hook = hook.copy()
                hook["diagnostic_suggestions"] = [
                    "Check if landing page matches hook promise",
                    "Review video body content after hook - does it maintain interest?",
                    "Evaluate if the offer/price point aligns with hook audience",
                    "Check for audience mismatch - is the hook attracting wrong customers?",
                    "Review checkout/funnel for friction points"
                ]
                results.append(hook)

            return results

        except Exception as e:
            logger.error(f"Error getting high hook rate low ROAS hooks for brand {brand_id}: {e}")
            return []

    def get_high_hook_rate_high_roas(
        self,
        brand_id: UUID,
        date_range_days: int = 30,
        min_spend: float = DEFAULT_MIN_SPEND,
        hook_rate_threshold: float = DEFAULT_HOOK_RATE_THRESHOLD,
        roas_threshold: float = 2.0,  # Higher threshold for "winners"
        limit: int = 10
    ) -> List[Dict]:
        """Get winning hooks - high engagement AND high conversion.

        These are your best performers. Scale these.

        Args:
            brand_id: Brand UUID.
            date_range_days: Number of days to look back.
            min_spend: Minimum spend threshold.
            hook_rate_threshold: Threshold for "high" hook rate.
            roas_threshold: Threshold for "high" ROAS (default 2.0 for winners).
            limit: Maximum hooks to return.

        Returns:
            List of winning hook dicts.
        """
        try:
            quadrants = self.get_hooks_by_quadrant(
                brand_id=brand_id,
                date_range_days=date_range_days,
                min_spend=min_spend,
                hook_rate_threshold=hook_rate_threshold,
                roas_threshold=roas_threshold
            )

            return quadrants["winners"][:limit]

        except Exception as e:
            logger.error(f"Error getting winning hooks for brand {brand_id}: {e}")
            return []

    def get_hooks_by_type(
        self,
        brand_id: UUID,
        date_range_days: int = 30
    ) -> List[Dict]:
        """Aggregate hook performance by hook_type.

        Returns performance breakdown for each hook type (question, claim, etc.).

        Args:
            brand_id: Brand UUID.
            date_range_days: Number of days to look back.

        Returns:
            List of dicts per hook_type with:
            - hook_type, ad_count, total_spend, avg_spend_per_ad
            - avg_roas, avg_ctr, avg_hook_rate
            - top_performing_fingerprint (best ROAS in this type)
        """
        try:
            # Get all hooks
            all_hooks = self.get_top_hooks_by_fingerprint(
                brand_id=brand_id,
                limit=1000,
                min_spend=0,  # Include all for type breakdown
                date_range_days=date_range_days,
                sort_by="spend"
            )

            # Aggregate by hook_type
            type_stats: Dict[str, Dict[str, Any]] = {}

            for hook in all_hooks:
                hook_type = hook.get("hook_type") or "unknown"

                if hook_type not in type_stats:
                    type_stats[hook_type] = {
                        "hook_type": hook_type,
                        "ad_count": 0,
                        "total_spend": 0.0,
                        "total_purchases": 0,
                        "total_purchase_value": 0.0,
                        "roas_sum": 0.0,
                        "ctr_sum": 0.0,
                        "hook_rate_sum": 0.0,
                        "count": 0,
                        "best_roas": 0.0,
                        "best_fingerprint": None,
                    }

                stats = type_stats[hook_type]
                stats["ad_count"] += hook["ad_count"]
                stats["total_spend"] += hook["total_spend"]
                stats["total_purchases"] += hook["total_purchases"]
                stats["roas_sum"] += hook["avg_roas"]
                stats["ctr_sum"] += hook["avg_ctr"]
                stats["hook_rate_sum"] += hook["avg_hook_rate"]
                stats["count"] += 1

                if hook["avg_roas"] > stats["best_roas"]:
                    stats["best_roas"] = hook["avg_roas"]
                    stats["best_fingerprint"] = hook["hook_fingerprint"]

            # Build results
            results = []
            for hook_type, stats in type_stats.items():
                count = stats["count"]
                results.append({
                    "hook_type": hook_type,
                    "ad_count": stats["ad_count"],
                    "total_spend": round(stats["total_spend"], 2),
                    "avg_spend_per_ad": round(stats["total_spend"] / stats["ad_count"], 2) if stats["ad_count"] > 0 else 0,
                    "avg_roas": round(stats["roas_sum"] / count, 2) if count > 0 else 0,
                    "avg_ctr": round(stats["ctr_sum"] / count, 4) if count > 0 else 0,
                    "avg_hook_rate": round(stats["hook_rate_sum"] / count, 4) if count > 0 else 0,
                    "top_performing_fingerprint": stats["best_fingerprint"],
                })

            # Sort by total spend
            return sorted(results, key=lambda x: x["total_spend"], reverse=True)

        except Exception as e:
            logger.error(f"Error getting hooks by type for brand {brand_id}: {e}")
            return []

    def get_hooks_by_visual_type(
        self,
        brand_id: UUID,
        date_range_days: int = 30
    ) -> List[Dict]:
        """Aggregate hook performance by hook_visual_type.

        Returns performance breakdown for each visual type (unboxing, demo, etc.).

        Args:
            brand_id: Brand UUID.
            date_range_days: Number of days to look back.

        Returns:
            List of dicts per visual_type with:
            - hook_visual_type, ad_count, total_spend
            - avg_roas, avg_ctr, avg_hook_rate
            - common_visual_elements (most frequent)
            - example_ad_ids
        """
        try:
            # Get all hooks
            all_hooks = self.get_top_hooks_by_fingerprint(
                brand_id=brand_id,
                limit=1000,
                min_spend=0,
                date_range_days=date_range_days,
                sort_by="spend"
            )

            # Aggregate by visual type
            visual_stats: Dict[str, Dict[str, Any]] = {}

            for hook in all_hooks:
                visual_type = hook.get("hook_visual_type") or "unknown"

                if visual_type not in visual_stats:
                    visual_stats[visual_type] = {
                        "hook_visual_type": visual_type,
                        "ad_count": 0,
                        "total_spend": 0.0,
                        "roas_sum": 0.0,
                        "ctr_sum": 0.0,
                        "hook_rate_sum": 0.0,
                        "count": 0,
                        "visual_elements_counter": {},
                        "example_ad_ids": [],
                    }

                stats = visual_stats[visual_type]
                stats["ad_count"] += hook["ad_count"]
                stats["total_spend"] += hook["total_spend"]
                stats["roas_sum"] += hook["avg_roas"]
                stats["ctr_sum"] += hook["avg_ctr"]
                stats["hook_rate_sum"] += hook["avg_hook_rate"]
                stats["count"] += 1

                # Count visual elements
                for elem in hook.get("hook_visual_elements", []):
                    stats["visual_elements_counter"][elem] = stats["visual_elements_counter"].get(elem, 0) + 1

                # Collect example ads
                stats["example_ad_ids"].extend(hook.get("example_ad_ids", [])[:2])

            # Build results
            results = []
            for visual_type, stats in visual_stats.items():
                count = stats["count"]

                # Get top 5 most common visual elements
                sorted_elements = sorted(
                    stats["visual_elements_counter"].items(),
                    key=lambda x: x[1],
                    reverse=True
                )
                common_elements = [elem for elem, _ in sorted_elements[:5]]

                results.append({
                    "hook_visual_type": visual_type,
                    "ad_count": stats["ad_count"],
                    "total_spend": round(stats["total_spend"], 2),
                    "avg_roas": round(stats["roas_sum"] / count, 2) if count > 0 else 0,
                    "avg_ctr": round(stats["ctr_sum"] / count, 4) if count > 0 else 0,
                    "avg_hook_rate": round(stats["hook_rate_sum"] / count, 4) if count > 0 else 0,
                    "common_visual_elements": common_elements,
                    "example_ad_ids": stats["example_ad_ids"][:3],
                })

            # Sort by total spend
            return sorted(results, key=lambda x: x["total_spend"], reverse=True)

        except Exception as e:
            logger.error(f"Error getting hooks by visual type for brand {brand_id}: {e}")
            return []

    def get_hooks_by_landing_page(
        self,
        brand_id: UUID,
        date_range_days: int = 30,
        limit: int = 20
    ) -> List[Dict]:
        """Aggregate hooks grouped by landing page.

        Shows which hooks are used with each LP and their performance.

        Args:
            brand_id: Brand UUID.
            date_range_days: Number of days to look back.
            limit: Maximum LPs to return.

        Returns:
            List of dicts per landing page with:
            - landing_page_id, landing_page_url, landing_page_title
            - hook_count (distinct hooks used)
            - hooks: [{fingerprint, type, visual_type, spend, roas}]
            - total_spend, avg_roas
            - best_hook_fingerprint, worst_hook_fingerprint
        """
        try:
            date_cutoff = (date.today() - timedelta(days=date_range_days)).isoformat()

            # Get classifications with landing page info and video analysis link
            classifications_result = self.supabase.table("ad_creative_classifications").select(
                "meta_ad_id, landing_page_id, video_analysis_id"
            ).eq(
                "brand_id", str(brand_id)
            ).not_.is_("landing_page_id", "null").not_.is_("video_analysis_id", "null").execute()

            if not classifications_result.data:
                return []

            # Get landing page details
            lp_ids = list(set(row["landing_page_id"] for row in classifications_result.data if row.get("landing_page_id")))
            if not lp_ids:
                return []

            lp_result = self.supabase.table("brand_landing_pages").select(
                "id, url, title"
            ).in_("id", lp_ids).execute()

            lp_lookup = {row["id"]: row for row in (lp_result.data or [])}

            # Get video analysis for hooks
            va_ids = list(set(row["video_analysis_id"] for row in classifications_result.data if row.get("video_analysis_id")))
            if not va_ids:
                return []

            va_result = self.supabase.table("ad_video_analysis").select(
                "id, meta_ad_id, hook_fingerprint, hook_type, hook_visual_type"
            ).in_("id", va_ids).execute()

            va_lookup = {row["id"]: row for row in (va_result.data or [])}

            # Get performance data
            perf_result = self.supabase.table("meta_ads_performance").select(
                "meta_ad_id, spend, purchase_value"
            ).eq(
                "brand_id", str(brand_id)
            ).gte(
                "date", date_cutoff
            ).execute()

            # Aggregate performance by ad
            ad_perf: Dict[str, Dict] = {}
            for perf in (perf_result.data or []):
                ad_id = perf.get("meta_ad_id")
                if not ad_id:
                    continue
                if ad_id not in ad_perf:
                    ad_perf[ad_id] = {"spend": 0.0, "value": 0.0}
                ad_perf[ad_id]["spend"] += _safe_numeric(perf.get("spend")) or 0.0
                ad_perf[ad_id]["value"] += _safe_numeric(perf.get("purchase_value")) or 0.0

            # Build classification lookup: ad -> (lp_id, va_id)
            ad_to_lp_va: Dict[str, tuple] = {}
            for row in classifications_result.data:
                ad_id = row.get("meta_ad_id")
                lp_id = row.get("landing_page_id")
                va_id = row.get("video_analysis_id")
                if ad_id and lp_id and va_id:
                    ad_to_lp_va[ad_id] = (lp_id, va_id)

            # Aggregate by landing page
            lp_stats: Dict[str, Dict[str, Any]] = {}

            for ad_id, (lp_id, va_id) in ad_to_lp_va.items():
                if va_id not in va_lookup:
                    continue
                va = va_lookup[va_id]
                hook_fp = va.get("hook_fingerprint")
                if not hook_fp:
                    continue

                if lp_id not in lp_stats:
                    lp_info = lp_lookup.get(lp_id, {})
                    lp_stats[lp_id] = {
                        "landing_page_id": lp_id,
                        "landing_page_url": lp_info.get("url"),
                        "landing_page_title": lp_info.get("title"),
                        "hooks": {},  # fp -> {spend, value, type, visual_type}
                        "total_spend": 0.0,
                        "total_value": 0.0,
                    }

                perf = ad_perf.get(ad_id, {"spend": 0.0, "value": 0.0})
                stats = lp_stats[lp_id]
                stats["total_spend"] += perf["spend"]
                stats["total_value"] += perf["value"]

                if hook_fp not in stats["hooks"]:
                    stats["hooks"][hook_fp] = {
                        "fingerprint": hook_fp,
                        "type": va.get("hook_type"),
                        "visual_type": va.get("hook_visual_type"),
                        "spend": 0.0,
                        "value": 0.0,
                    }

                stats["hooks"][hook_fp]["spend"] += perf["spend"]
                stats["hooks"][hook_fp]["value"] += perf["value"]

            # Build results
            results = []
            for lp_id, stats in lp_stats.items():
                hooks_list = []
                best_hook = None
                worst_hook = None
                best_roas = -1
                worst_roas = float("inf")

                for fp, hook_data in stats["hooks"].items():
                    roas = hook_data["value"] / hook_data["spend"] if hook_data["spend"] > 0 else 0
                    hook_dict = {
                        "fingerprint": fp,
                        "type": hook_data["type"],
                        "visual_type": hook_data["visual_type"],
                        "spend": round(hook_data["spend"], 2),
                        "roas": round(roas, 2),
                    }
                    hooks_list.append(hook_dict)

                    if roas > best_roas:
                        best_roas = roas
                        best_hook = fp
                    if roas < worst_roas and hook_data["spend"] > 50:  # Only consider hooks with some spend
                        worst_roas = roas
                        worst_hook = fp

                # Sort hooks by spend
                hooks_list = sorted(hooks_list, key=lambda x: x["spend"], reverse=True)

                avg_roas = stats["total_value"] / stats["total_spend"] if stats["total_spend"] > 0 else 0

                results.append({
                    "landing_page_id": lp_id,
                    "landing_page_url": stats["landing_page_url"],
                    "landing_page_title": stats["landing_page_title"],
                    "hook_count": len(hooks_list),
                    "hooks": hooks_list,
                    "total_spend": round(stats["total_spend"], 2),
                    "avg_roas": round(avg_roas, 2),
                    "best_hook_fingerprint": best_hook,
                    "worst_hook_fingerprint": worst_hook,
                })

            # Sort by total spend
            results = sorted(results, key=lambda x: x["total_spend"], reverse=True)
            return results[:limit]

        except Exception as e:
            logger.error(f"Error getting hooks by landing page for brand {brand_id}: {e}")
            return []

    # =========================================================================
    # Detailed Analysis Methods
    # =========================================================================

    def get_hook_details(
        self,
        brand_id: UUID,
        hook_fingerprint: str
    ) -> Optional[Dict]:
        """Get detailed info for a specific hook fingerprint.

        Args:
            brand_id: Brand UUID.
            hook_fingerprint: Hook fingerprint to look up.

        Returns:
            Dict with:
            - Full hook data (spoken, overlay, visual, type, elements)
            - All ads using this hook
            - Performance metrics per ad
            - Landing pages this hook is used with
            - Performance variance (is it consistent or variable?)
        """
        try:
            # Get video analysis records with this fingerprint
            va_result = self.supabase.table("ad_video_analysis").select(
                "meta_ad_id, hook_type, hook_visual_type, "
                "hook_transcript_spoken, hook_transcript_overlay, "
                "hook_visual_description, hook_visual_elements, "
                "full_transcript, benefits_shown, angles_used"
            ).eq(
                "brand_id", str(brand_id)
            ).eq(
                "hook_fingerprint", hook_fingerprint
            ).execute()

            if not va_result.data:
                return None

            # Use first record for hook details
            hook_data = va_result.data[0]
            ad_ids = [row["meta_ad_id"] for row in va_result.data]

            # Get performance data for all ads
            perf_result = self.supabase.table("meta_ads_performance").select(
                "meta_ad_id, date, spend, impressions, video_views, "
                "purchase_value, purchases, link_ctr, roas"
            ).eq(
                "brand_id", str(brand_id)
            ).in_(
                "meta_ad_id", ad_ids
            ).execute()

            # Aggregate by ad
            ad_metrics: Dict[str, Dict] = {}
            for perf in (perf_result.data or []):
                ad_id = perf["meta_ad_id"]
                if ad_id not in ad_metrics:
                    ad_metrics[ad_id] = {
                        "meta_ad_id": ad_id,
                        "spend": 0.0,
                        "impressions": 0,
                        "video_views": 0,
                        "purchase_value": 0.0,
                        "purchases": 0,
                        "days": 0,
                    }
                m = ad_metrics[ad_id]
                m["spend"] += _safe_numeric(perf.get("spend")) or 0.0
                m["impressions"] += _safe_numeric(perf.get("impressions")) or 0
                m["video_views"] += _safe_numeric(perf.get("video_views")) or 0
                m["purchase_value"] += _safe_numeric(perf.get("purchase_value")) or 0.0
                m["purchases"] += int(_safe_numeric(perf.get("purchases")) or 0)
                m["days"] += 1

            # Compute per-ad metrics
            ads_data = []
            roas_values = []
            hook_rate_values = []

            for ad_id, m in ad_metrics.items():
                roas = m["purchase_value"] / m["spend"] if m["spend"] > 0 else 0
                hook_rate = m["video_views"] / m["impressions"] if m["impressions"] > 0 else 0

                roas_values.append(roas)
                hook_rate_values.append(hook_rate)

                ads_data.append({
                    "meta_ad_id": ad_id,
                    "spend": round(m["spend"], 2),
                    "roas": round(roas, 2),
                    "hook_rate": round(hook_rate, 4),
                    "purchases": m["purchases"],
                    "days_active": m["days"],
                })

            # Get landing pages
            class_result = self.supabase.table("ad_creative_classifications").select(
                "meta_ad_id, landing_page_id"
            ).eq(
                "brand_id", str(brand_id)
            ).in_(
                "meta_ad_id", ad_ids
            ).not_.is_("landing_page_id", "null").execute()

            lp_ids = list(set(
                row["landing_page_id"]
                for row in (class_result.data or [])
                if row.get("landing_page_id")
            ))

            landing_pages = []
            if lp_ids:
                lp_result = self.supabase.table("brand_landing_pages").select(
                    "id, url, title"
                ).in_("id", lp_ids).execute()
                landing_pages = lp_result.data or []

            # Compute variance (std dev / mean)
            def compute_cv(values):
                """Compute coefficient of variation."""
                if len(values) < 2:
                    return 0
                mean = sum(values) / len(values)
                if mean == 0:
                    return 0
                variance = sum((x - mean) ** 2 for x in values) / len(values)
                std_dev = variance ** 0.5
                return std_dev / mean

            roas_cv = compute_cv(roas_values)
            hook_rate_cv = compute_cv(hook_rate_values)

            consistency = "consistent"
            if roas_cv > 0.5 or hook_rate_cv > 0.3:
                consistency = "variable"
            elif roas_cv > 0.3 or hook_rate_cv > 0.2:
                consistency = "somewhat_variable"

            # Build result
            total_spend = sum(m["spend"] for m in ad_metrics.values())
            total_value = sum(m["purchase_value"] for m in ad_metrics.values())
            total_impressions = sum(m["impressions"] for m in ad_metrics.values())
            total_views = sum(m["video_views"] for m in ad_metrics.values())

            return {
                "hook_fingerprint": hook_fingerprint,
                "hook_type": hook_data.get("hook_type"),
                "hook_visual_type": hook_data.get("hook_visual_type"),
                "hook_transcript_spoken": hook_data.get("hook_transcript_spoken"),
                "hook_transcript_overlay": hook_data.get("hook_transcript_overlay"),
                "hook_visual_description": hook_data.get("hook_visual_description"),
                "hook_visual_elements": hook_data.get("hook_visual_elements", []),
                "benefits_shown": hook_data.get("benefits_shown", []),
                "angles_used": hook_data.get("angles_used", []),
                "ad_count": len(ad_ids),
                "ads": sorted(ads_data, key=lambda x: x["spend"], reverse=True),
                "landing_pages": landing_pages,
                "aggregate_metrics": {
                    "total_spend": round(total_spend, 2),
                    "avg_roas": round(total_value / total_spend, 2) if total_spend > 0 else 0,
                    "avg_hook_rate": round(total_views / total_impressions, 4) if total_impressions > 0 else 0,
                },
                "performance_consistency": consistency,
                "roas_coefficient_of_variation": round(roas_cv, 3),
                "hook_rate_coefficient_of_variation": round(hook_rate_cv, 3),
            }

        except Exception as e:
            logger.error(f"Error getting hook details for fingerprint {hook_fingerprint}: {e}")
            return None

    def get_hook_comparison(
        self,
        brand_id: UUID,
        fingerprint_a: str,
        fingerprint_b: str
    ) -> Dict:
        """Compare two hooks head-to-head.

        Args:
            brand_id: Brand UUID.
            fingerprint_a: First hook fingerprint.
            fingerprint_b: Second hook fingerprint.

        Returns:
            Dict with:
            - hook_a: Details + metrics
            - hook_b: Details + metrics
            - winner_by: {spend, roas, ctr, hook_rate}
            - statistical_confidence: Based on sample size
        """
        try:
            hook_a = self.get_hook_details(brand_id, fingerprint_a)
            hook_b = self.get_hook_details(brand_id, fingerprint_b)

            if not hook_a or not hook_b:
                return {
                    "error": "One or both hooks not found",
                    "hook_a": hook_a,
                    "hook_b": hook_b,
                }

            # Determine winners
            winners = {}
            a_metrics = hook_a["aggregate_metrics"]
            b_metrics = hook_b["aggregate_metrics"]

            winners["spend"] = "A" if a_metrics["total_spend"] > b_metrics["total_spend"] else "B"
            winners["roas"] = "A" if a_metrics["avg_roas"] > b_metrics["avg_roas"] else "B"
            winners["hook_rate"] = "A" if a_metrics["avg_hook_rate"] > b_metrics["avg_hook_rate"] else "B"

            # Statistical confidence based on sample size
            min_ads = min(hook_a["ad_count"], hook_b["ad_count"])
            min_spend = min(a_metrics["total_spend"], b_metrics["total_spend"])

            if min_ads >= 5 and min_spend >= 500:
                confidence = "high"
            elif min_ads >= 3 and min_spend >= 200:
                confidence = "medium"
            else:
                confidence = "low"

            return {
                "hook_a": {
                    "fingerprint": fingerprint_a,
                    "type": hook_a["hook_type"],
                    "visual_type": hook_a["hook_visual_type"],
                    "transcript_spoken": hook_a["hook_transcript_spoken"],
                    "ad_count": hook_a["ad_count"],
                    "metrics": a_metrics,
                    "consistency": hook_a["performance_consistency"],
                },
                "hook_b": {
                    "fingerprint": fingerprint_b,
                    "type": hook_b["hook_type"],
                    "visual_type": hook_b["hook_visual_type"],
                    "transcript_spoken": hook_b["hook_transcript_spoken"],
                    "ad_count": hook_b["ad_count"],
                    "metrics": b_metrics,
                    "consistency": hook_b["performance_consistency"],
                },
                "winner_by": winners,
                "statistical_confidence": confidence,
                "recommendation": self._generate_comparison_recommendation(hook_a, hook_b, winners)
            }

        except Exception as e:
            logger.error(f"Error comparing hooks: {e}")
            return {"error": str(e)}

    def _generate_comparison_recommendation(
        self,
        hook_a: Dict,
        hook_b: Dict,
        winners: Dict
    ) -> str:
        """Generate recommendation based on hook comparison."""
        a_wins = sum(1 for v in winners.values() if v == "A")
        b_wins = sum(1 for v in winners.values() if v == "B")

        if a_wins > b_wins:
            winner_hook = hook_a
            loser_hook = hook_b
            winner_label = "Hook A"
        else:
            winner_hook = hook_b
            loser_hook = hook_a
            winner_label = "Hook B"

        # Check if loser has higher hook rate but lower ROAS
        if winners["hook_rate"] != winners["roas"]:
            return (
                f"{winner_label} performs better overall. "
                f"However, the losing hook has higher engagement - "
                f"consider testing its hook style with better downstream content."
            )

        return (
            f"{winner_label} outperforms across metrics. "
            f"Consider scaling this hook and testing variations of its approach."
        )

    def get_untested_hook_types(
        self,
        brand_id: UUID
    ) -> List[Dict]:
        """Find hook types/visual types not yet tested.

        Returns gap analysis showing what hasn't been tried.

        Args:
            brand_id: Brand UUID.

        Returns:
            List with:
            - untested_hook_types: Types with < 2 ads
            - untested_visual_types: Visual types with < 2 ads
            - suggestions: What to test next
        """
        try:
            # Get all hooks
            all_hooks = self.get_top_hooks_by_fingerprint(
                brand_id=brand_id,
                limit=1000,
                min_spend=0,
                date_range_days=90,  # Look at longer history
                sort_by="spend"
            )

            # Count by type
            type_counts: Dict[str, int] = {}
            visual_counts: Dict[str, int] = {}

            for hook in all_hooks:
                hook_type = hook.get("hook_type") or "unknown"
                visual_type = hook.get("hook_visual_type") or "unknown"

                type_counts[hook_type] = type_counts.get(hook_type, 0) + hook["ad_count"]
                visual_counts[visual_type] = visual_counts.get(visual_type, 0) + hook["ad_count"]

            # Find gaps
            untested_hook_types = []
            undertested_hook_types = []
            for ht in ALL_HOOK_TYPES:
                count = type_counts.get(ht, 0)
                if count == 0:
                    untested_hook_types.append(ht)
                elif count < 3:
                    undertested_hook_types.append({"type": ht, "ad_count": count})

            untested_visual_types = []
            undertested_visual_types = []
            for vt in ALL_VISUAL_HOOK_TYPES:
                count = visual_counts.get(vt, 0)
                if count == 0:
                    untested_visual_types.append(vt)
                elif count < 3:
                    undertested_visual_types.append({"type": vt, "ad_count": count})

            # Generate suggestions
            suggestions = []

            if untested_hook_types:
                suggestions.append(
                    f"Test these untried hook types: {', '.join(untested_hook_types[:3])}"
                )

            if untested_visual_types:
                suggestions.append(
                    f"Test these untried visual styles: {', '.join(untested_visual_types[:3])}"
                )

            if undertested_hook_types:
                best = undertested_hook_types[0]
                suggestions.append(
                    f"Get more data on '{best['type']}' hooks - only {best['ad_count']} ads tested"
                )

            # Find best performing type to suggest variations
            by_type = self.get_hooks_by_type(brand_id, date_range_days=30)
            if by_type:
                best_type = max(by_type, key=lambda x: x["avg_roas"])
                if best_type["avg_roas"] > 1.0:
                    suggestions.append(
                        f"Your best performing hook type is '{best_type['hook_type']}' "
                        f"({best_type['avg_roas']}x ROAS) - test more variations"
                    )

            return {
                "untested_hook_types": untested_hook_types,
                "undertested_hook_types": undertested_hook_types,
                "untested_visual_types": untested_visual_types,
                "undertested_visual_types": undertested_visual_types,
                "tested_hook_types": list(type_counts.keys()),
                "tested_visual_types": list(visual_counts.keys()),
                "suggestions": suggestions,
            }

        except Exception as e:
            logger.error(f"Error getting untested hook types for brand {brand_id}: {e}")
            return {
                "untested_hook_types": [],
                "undertested_hook_types": [],
                "untested_visual_types": [],
                "undertested_visual_types": [],
                "tested_hook_types": [],
                "tested_visual_types": [],
                "suggestions": [],
            }

    # =========================================================================
    # Insights & Recommendations
    # =========================================================================

    def get_hook_insights(
        self,
        brand_id: UUID,
        date_range_days: int = 30
    ) -> Dict:
        """Generate actionable hook insights.

        Args:
            brand_id: Brand UUID.
            date_range_days: Number of days to look back.

        Returns:
            Dict with:
            - top_performer: Best hook by ROAS with details
            - worst_performer: Worst hook by ROAS (with min spend)
            - coverage_gaps: Untested hook types
            - recommendations: List of actionable suggestions
            - summary_stats: Overall hook performance summary
        """
        try:
            # Get top hooks by ROAS
            top_hooks = self.get_top_hooks_by_fingerprint(
                brand_id=brand_id,
                limit=50,
                min_spend=DEFAULT_MIN_SPEND,
                date_range_days=date_range_days,
                sort_by="roas",
                sort_order="desc"
            )

            if not top_hooks:
                return {
                    "top_performer": None,
                    "worst_performer": None,
                    "coverage_gaps": self.get_untested_hook_types(brand_id),
                    "recommendations": ["No hooks with sufficient spend found. Run more video ads to generate data."],
                    "summary_stats": {},
                }

            # Top and worst performers
            top_performer = top_hooks[0] if top_hooks else None

            # Get worst by ROAS (still needs min spend)
            worst_hooks = self.get_top_hooks_by_fingerprint(
                brand_id=brand_id,
                limit=10,
                min_spend=DEFAULT_MIN_SPEND,
                date_range_days=date_range_days,
                sort_by="roas",
                sort_order="asc"
            )
            worst_performer = worst_hooks[0] if worst_hooks else None

            # Get quadrant analysis for recommendations
            quadrants = self.get_hooks_by_quadrant(
                brand_id=brand_id,
                date_range_days=date_range_days,
                min_spend=DEFAULT_MIN_SPEND
            )

            # Get gaps
            gaps = self.get_untested_hook_types(brand_id)

            # Generate recommendations
            recommendations = []

            # Winner recommendations
            if quadrants["winners"]:
                winner = quadrants["winners"][0]
                recommendations.append(
                    f"SCALE: Your best hook ({winner['hook_type']}) has {winner['avg_roas']:.1f}x ROAS "
                    f"and {winner['avg_hook_rate']:.1%} hook rate. Consider increasing budget."
                )

            # Engaging but not converting
            if quadrants["engaging_not_converting"]:
                problem_hook = quadrants["engaging_not_converting"][0]
                recommendations.append(
                    f"FIX DOWNSTREAM: '{problem_hook['hook_type']}' hook has great engagement "
                    f"({problem_hook['avg_hook_rate']:.1%}) but poor ROAS ({problem_hook['avg_roas']:.1f}x). "
                    f"Check landing page and offer alignment."
                )

            # Losers to kill
            if quadrants["losers"]:
                loser = quadrants["losers"][0]
                if loser["total_spend"] > 200:
                    recommendations.append(
                        f"KILL: '{loser['hook_type']}' hook has ${loser['total_spend']:.0f} spend "
                        f"but only {loser['avg_roas']:.1f}x ROAS. Consider pausing these ads."
                    )

            # Gap recommendations
            if gaps["suggestions"]:
                recommendations.extend(gaps["suggestions"][:2])

            # Summary stats
            total_spend = sum(h["total_spend"] for h in top_hooks)
            avg_roas = sum(h["avg_roas"] * h["total_spend"] for h in top_hooks) / total_spend if total_spend > 0 else 0
            avg_hook_rate = sum(h["avg_hook_rate"] for h in top_hooks) / len(top_hooks) if top_hooks else 0

            return {
                "top_performer": top_performer,
                "worst_performer": worst_performer,
                "quadrant_summary": {
                    "winners": len(quadrants["winners"]),
                    "hidden_gems": len(quadrants["hidden_gems"]),
                    "engaging_not_converting": len(quadrants["engaging_not_converting"]),
                    "losers": len(quadrants["losers"]),
                },
                "coverage_gaps": gaps,
                "recommendations": recommendations,
                "summary_stats": {
                    "total_hooks_analyzed": len(top_hooks),
                    "total_spend": round(total_spend, 2),
                    "weighted_avg_roas": round(avg_roas, 2),
                    "avg_hook_rate": round(avg_hook_rate, 4),
                },
            }

        except Exception as e:
            logger.error(f"Error generating hook insights for brand {brand_id}: {e}")
            return {
                "top_performer": None,
                "worst_performer": None,
                "coverage_gaps": {},
                "recommendations": [f"Error generating insights: {e}"],
                "summary_stats": {},
            }

    def get_winning_hooks_for_lp(
        self,
        brand_id: UUID,
        landing_page_id: UUID
    ) -> List[Dict]:
        """Get best performing hooks for a specific landing page.

        Useful for: "What hooks work best with this LP?"

        Args:
            brand_id: Brand UUID.
            landing_page_id: Landing page UUID.

        Returns:
            List of hook dicts sorted by ROAS for this LP.
        """
        try:
            # Get LP data
            lp_data = self.get_hooks_by_landing_page(
                brand_id=brand_id,
                date_range_days=30,
                limit=100
            )

            # Find the specific LP
            for lp in lp_data:
                if lp["landing_page_id"] == str(landing_page_id):
                    # Sort hooks by ROAS
                    hooks = sorted(
                        lp.get("hooks", []),
                        key=lambda x: x.get("roas", 0),
                        reverse=True
                    )

                    # Enrich with more details for top hooks
                    enriched_hooks = []
                    for hook in hooks[:10]:
                        details = self.get_hook_details(brand_id, hook["fingerprint"])
                        if details:
                            enriched_hooks.append({
                                **hook,
                                "hook_transcript_spoken": details.get("hook_transcript_spoken"),
                                "hook_visual_description": details.get("hook_visual_description"),
                                "ad_count": details.get("ad_count"),
                            })
                        else:
                            enriched_hooks.append(hook)

                    return enriched_hooks

            return []

        except Exception as e:
            logger.error(f"Error getting winning hooks for LP {landing_page_id}: {e}")
            return []
