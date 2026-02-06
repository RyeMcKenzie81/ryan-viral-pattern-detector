"""CongruenceInsightsService: Aggregation and insights for congruence data.

Provides methods to:
- Find ads eligible for re-analysis (have video_analysis_id + landing_page_id but no congruence_components)
- Aggregate congruence by dimension across a brand
- Get weak ads by specific dimension
- Aggregate improvement suggestions
- Track congruence trends over time
"""

from __future__ import annotations

import logging
from collections import Counter
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List, Optional
from uuid import UUID

logger = logging.getLogger(__name__)


class CongruenceInsightsService:
    """Service for aggregating and analyzing congruence data across ads."""

    # The 5 congruence dimensions from CongruenceAnalyzer
    DIMENSIONS = [
        "awareness_alignment",
        "hook_headline",
        "benefits_match",
        "messaging_angle",
        "claims_consistency",
    ]

    # Assessment values
    ASSESSMENTS = ["aligned", "weak", "missing", "unevaluated"]

    def __init__(self, supabase_client):
        """Initialize with Supabase client.

        Args:
            supabase_client: Supabase client instance.
        """
        self.supabase = supabase_client

    def get_eligible_for_reanalysis(
        self,
        brand_id: Optional[UUID] = None,
        organization_id: Optional[UUID] = None,
        limit: int = 100,
    ) -> List[Dict]:
        """Find ads eligible for congruence re-analysis.

        Eligible ads have:
        - video_analysis_id IS NOT NULL (has deep video analysis)
        - landing_page_id IS NOT NULL (has LP data)
        - congruence_components IS NULL or empty (needs analysis)
        - Video analysis status = 'ok'
        - Landing page scrape_status = 'scraped'

        Args:
            brand_id: Optional brand filter. If None, returns all brands.
            organization_id: Optional organization filter for multi-tenant.
            limit: Maximum number of ads to return.

        Returns:
            List of dicts with ad info needed for re-analysis.
        """
        try:
            # Build query to find eligible ads
            # We need to join with ad_video_analysis and brand_landing_pages
            # to verify status conditions
            query = self.supabase.table("ad_creative_classifications").select(
                "id, meta_ad_id, brand_id, organization_id, video_analysis_id, "
                "landing_page_id, congruence_components, classified_at"
            )

            # Add brand filter if specified
            if brand_id:
                query = query.eq("brand_id", str(brand_id))

            if organization_id:
                query = query.eq("organization_id", str(organization_id))

            # Filter for ads with video analysis and LP but no congruence
            query = query.not_.is_("video_analysis_id", "null")
            query = query.not_.is_("landing_page_id", "null")

            # Order by most recent first
            query = query.order("classified_at", desc=True)

            # Execute query
            result = query.limit(limit * 3).execute()  # Get extra to filter

            if not result.data:
                return []

            # Filter to ads with empty or null congruence_components
            # and verify video/LP status
            eligible = []
            video_ids_to_check = set()
            lp_ids_to_check = set()

            for row in result.data:
                components = row.get("congruence_components")
                # Check if congruence is empty/null
                if components is None or components == [] or components == "[]":
                    video_ids_to_check.add(row["video_analysis_id"])
                    lp_ids_to_check.add(row["landing_page_id"])

            if not video_ids_to_check:
                return []

            # Batch check video analysis status
            video_result = self.supabase.table("ad_video_analysis").select(
                "id, status"
            ).in_("id", list(video_ids_to_check)).execute()

            ok_video_ids = {
                r["id"] for r in (video_result.data or [])
                if r.get("status") == "ok"
            }

            # Batch check LP scrape status
            lp_result = self.supabase.table("brand_landing_pages").select(
                "id, scrape_status"
            ).in_("id", list(lp_ids_to_check)).execute()

            scraped_lp_ids = {
                r["id"] for r in (lp_result.data or [])
                if r.get("scrape_status") == "scraped"
            }

            # Filter to eligible ads
            for row in result.data:
                components = row.get("congruence_components")
                if components is None or components == [] or components == "[]":
                    video_id = row.get("video_analysis_id")
                    lp_id = row.get("landing_page_id")
                    if video_id in ok_video_ids and lp_id in scraped_lp_ids:
                        eligible.append({
                            "id": row["id"],
                            "meta_ad_id": row["meta_ad_id"],
                            "brand_id": row["brand_id"],
                            "organization_id": row["organization_id"],
                            "video_analysis_id": video_id,
                            "landing_page_id": lp_id,
                            "classified_at": row.get("classified_at"),
                        })
                        if len(eligible) >= limit:
                            break

            return eligible

        except Exception as e:
            logger.error(f"Error finding eligible ads for reanalysis: {e}")
            return []

    def get_dimension_summary(
        self,
        brand_id: UUID,
        date_range_days: int = 30,
    ) -> Dict[str, Any]:
        """Get aggregated congruence summary by dimension.

        Args:
            brand_id: Brand UUID.
            date_range_days: Number of days to look back.

        Returns:
            Dict with:
            - dimensions: {dimension_name: {aligned: N, weak: N, missing: N, unevaluated: N}}
            - overall_health: float (0-1, weighted average)
            - total_analyzed: int
            - fully_aligned_count: int
        """
        try:
            cutoff = (datetime.now(timezone.utc) - timedelta(days=date_range_days)).isoformat()

            # Fetch all classifications with congruence_components
            result = self.supabase.table("ad_creative_classifications").select(
                "meta_ad_id, congruence_components, congruence_score"
            ).eq(
                "brand_id", str(brand_id)
            ).gte(
                "classified_at", cutoff
            ).not_.is_(
                "congruence_components", "null"
            ).order(
                "classified_at", desc=True
            ).execute()

            if not result.data:
                return {
                    "dimensions": {d: {"aligned": 0, "weak": 0, "missing": 0, "unevaluated": 0}
                                   for d in self.DIMENSIONS},
                    "overall_health": None,
                    "total_analyzed": 0,
                    "fully_aligned_count": 0,
                }

            # Dedupe by meta_ad_id (latest per ad)
            seen = set()
            unique_rows = []
            for row in result.data:
                ad_id = row.get("meta_ad_id")
                if ad_id and ad_id not in seen:
                    seen.add(ad_id)
                    unique_rows.append(row)

            # Initialize counters
            dimension_counts = {d: Counter() for d in self.DIMENSIONS}
            fully_aligned_count = 0
            scores = []

            for row in unique_rows:
                components = row.get("congruence_components", [])
                if not components:
                    continue

                # Handle string or list
                if isinstance(components, str):
                    import json
                    try:
                        components = json.loads(components)
                    except Exception:
                        continue

                # Count by dimension and assessment
                all_aligned = True
                for comp in components:
                    dim = comp.get("dimension")
                    assessment = comp.get("assessment", "unevaluated")
                    if dim in dimension_counts:
                        dimension_counts[dim][assessment] += 1
                        if assessment != "aligned":
                            all_aligned = False

                if all_aligned and len(components) == len(self.DIMENSIONS):
                    fully_aligned_count += 1

                # Track scores for overall health
                score = row.get("congruence_score")
                if score is not None:
                    scores.append(float(score))

            # Build summary
            dimensions_summary = {}
            for dim in self.DIMENSIONS:
                dimensions_summary[dim] = {
                    "aligned": dimension_counts[dim].get("aligned", 0),
                    "weak": dimension_counts[dim].get("weak", 0),
                    "missing": dimension_counts[dim].get("missing", 0),
                    "unevaluated": dimension_counts[dim].get("unevaluated", 0),
                }

            overall_health = sum(scores) / len(scores) if scores else None

            return {
                "dimensions": dimensions_summary,
                "overall_health": round(overall_health, 3) if overall_health else None,
                "total_analyzed": len(unique_rows),
                "fully_aligned_count": fully_aligned_count,
            }

        except Exception as e:
            logger.error(f"Error getting dimension summary: {e}")
            return {
                "dimensions": {d: {"aligned": 0, "weak": 0, "missing": 0, "unevaluated": 0}
                               for d in self.DIMENSIONS},
                "overall_health": None,
                "total_analyzed": 0,
                "fully_aligned_count": 0,
            }

    def get_weak_ads_by_dimension(
        self,
        brand_id: UUID,
        dimension: str,
        limit: int = 20,
    ) -> List[Dict]:
        """Get ads with weak or missing assessment for a specific dimension.

        Args:
            brand_id: Brand UUID.
            dimension: Dimension name (e.g., "hook_headline").
            limit: Maximum number of ads to return.

        Returns:
            List of dicts with ad info, explanation, and suggestion.
        """
        if dimension not in self.DIMENSIONS:
            logger.warning(f"Invalid dimension: {dimension}")
            return []

        try:
            # Fetch recent classifications with congruence data
            result = self.supabase.table("ad_creative_classifications").select(
                "meta_ad_id, congruence_components, congruence_score, classified_at"
            ).eq(
                "brand_id", str(brand_id)
            ).not_.is_(
                "congruence_components", "null"
            ).order(
                "classified_at", desc=True
            ).limit(500).execute()

            if not result.data:
                return []

            # Dedupe by meta_ad_id
            seen = set()
            weak_ads = []

            for row in result.data:
                ad_id = row.get("meta_ad_id")
                if ad_id in seen:
                    continue
                seen.add(ad_id)

                components = row.get("congruence_components", [])
                if not components:
                    continue

                if isinstance(components, str):
                    import json
                    try:
                        components = json.loads(components)
                    except Exception:
                        continue

                # Find the target dimension
                for comp in components:
                    if comp.get("dimension") == dimension:
                        assessment = comp.get("assessment")
                        if assessment in ("weak", "missing"):
                            weak_ads.append({
                                "meta_ad_id": ad_id,
                                "assessment": assessment,
                                "explanation": comp.get("explanation", ""),
                                "suggestion": comp.get("suggestion"),
                                "congruence_score": row.get("congruence_score"),
                                "classified_at": row.get("classified_at"),
                            })
                        break

                if len(weak_ads) >= limit:
                    break

            # Sort by assessment (missing first, then weak)
            weak_ads.sort(key=lambda x: (0 if x["assessment"] == "missing" else 1))

            return weak_ads

        except Exception as e:
            logger.error(f"Error getting weak ads by dimension: {e}")
            return []

    def get_improvement_suggestions(
        self,
        brand_id: UUID,
        limit: int = 10,
    ) -> List[Dict]:
        """Get aggregated improvement suggestions ranked by frequency.

        Clusters similar suggestions together and ranks by how often they appear.

        Args:
            brand_id: Brand UUID.
            limit: Maximum suggestions to return.

        Returns:
            List of dicts with suggestion, frequency, dimension, and sample ads.
        """
        try:
            # Fetch recent classifications
            result = self.supabase.table("ad_creative_classifications").select(
                "meta_ad_id, congruence_components"
            ).eq(
                "brand_id", str(brand_id)
            ).not_.is_(
                "congruence_components", "null"
            ).order(
                "classified_at", desc=True
            ).limit(500).execute()

            if not result.data:
                return []

            # Dedupe by meta_ad_id
            seen = set()
            unique_rows = []
            for row in result.data:
                ad_id = row.get("meta_ad_id")
                if ad_id and ad_id not in seen:
                    seen.add(ad_id)
                    unique_rows.append(row)

            # Collect all suggestions
            suggestion_data = []  # (suggestion, dimension, ad_id)

            for row in unique_rows:
                components = row.get("congruence_components", [])
                if not components:
                    continue

                if isinstance(components, str):
                    import json
                    try:
                        components = json.loads(components)
                    except Exception:
                        continue

                for comp in components:
                    suggestion = comp.get("suggestion")
                    if suggestion:
                        suggestion_data.append((
                            suggestion,
                            comp.get("dimension", "unknown"),
                            row.get("meta_ad_id"),
                        ))

            if not suggestion_data:
                return []

            # Group similar suggestions
            # Simple approach: use first N characters as key
            from collections import defaultdict
            suggestion_groups = defaultdict(list)

            for suggestion, dimension, ad_id in suggestion_data:
                # Normalize suggestion for grouping
                key = suggestion[:80].lower().strip()
                suggestion_groups[key].append({
                    "suggestion": suggestion,
                    "dimension": dimension,
                    "ad_id": ad_id,
                })

            # Build ranked list
            ranked = []
            for key, items in suggestion_groups.items():
                # Use most common full suggestion from group
                suggestion_counter = Counter(i["suggestion"] for i in items)
                most_common = suggestion_counter.most_common(1)[0][0]

                # Get dimension(s)
                dimensions = list(set(i["dimension"] for i in items))
                sample_ads = list(set(i["ad_id"] for i in items[:5]))

                ranked.append({
                    "suggestion": most_common,
                    "frequency": len(items),
                    "dimensions": dimensions,
                    "sample_ad_ids": sample_ads,
                })

            # Sort by frequency
            ranked.sort(key=lambda x: x["frequency"], reverse=True)

            return ranked[:limit]

        except Exception as e:
            logger.error(f"Error getting improvement suggestions: {e}")
            return []

    def get_congruence_trends(
        self,
        brand_id: UUID,
        lookback_weeks: int = 4,
    ) -> List[Dict]:
        """Get weekly congruence score trends.

        Args:
            brand_id: Brand UUID.
            lookback_weeks: Number of weeks to look back.

        Returns:
            List of dicts with week_start, avg_score, ad_count, aligned_pct.
        """
        try:
            cutoff = datetime.now(timezone.utc) - timedelta(weeks=lookback_weeks)

            # Fetch classifications
            result = self.supabase.table("ad_creative_classifications").select(
                "meta_ad_id, congruence_score, congruence_components, classified_at"
            ).eq(
                "brand_id", str(brand_id)
            ).gte(
                "classified_at", cutoff.isoformat()
            ).not_.is_(
                "congruence_score", "null"
            ).order(
                "classified_at", desc=True
            ).execute()

            if not result.data:
                return []

            # Dedupe by meta_ad_id
            seen = set()
            unique_rows = []
            for row in result.data:
                ad_id = row.get("meta_ad_id")
                if ad_id and ad_id not in seen:
                    seen.add(ad_id)
                    unique_rows.append(row)

            # Group by week
            from collections import defaultdict
            weekly_data = defaultdict(list)

            for row in unique_rows:
                classified_at = row.get("classified_at")
                if not classified_at:
                    continue

                # Parse date
                try:
                    if isinstance(classified_at, str):
                        dt = datetime.fromisoformat(classified_at.replace("Z", "+00:00"))
                    else:
                        dt = classified_at
                except Exception:
                    continue

                # Get week start (Monday)
                week_start = dt.date() - timedelta(days=dt.weekday())
                weekly_data[week_start].append(row)

            # Compute weekly stats
            trends = []
            for week_start, rows in sorted(weekly_data.items()):
                scores = [r["congruence_score"] for r in rows if r.get("congruence_score")]

                # Count fully aligned
                aligned_count = 0
                for row in rows:
                    components = row.get("congruence_components", [])
                    if components:
                        if isinstance(components, str):
                            import json
                            try:
                                components = json.loads(components)
                            except Exception:
                                continue

                        if all(c.get("assessment") == "aligned" for c in components):
                            aligned_count += 1

                if scores:
                    trends.append({
                        "week_start": week_start.isoformat(),
                        "avg_score": round(sum(scores) / len(scores), 3),
                        "ad_count": len(rows),
                        "aligned_pct": round(aligned_count / len(rows) * 100, 1) if rows else 0,
                    })

            return trends

        except Exception as e:
            logger.error(f"Error getting congruence trends: {e}")
            return []

    def get_ads_with_congruence(
        self,
        brand_id: UUID,
        limit: int = 50,
    ) -> List[Dict]:
        """Get ads with congruence analysis for dashboard display.

        Args:
            brand_id: Brand UUID.
            limit: Maximum ads to return.

        Returns:
            List of dicts with ad info and congruence data.
        """
        try:
            result = self.supabase.table("ad_creative_classifications").select(
                "meta_ad_id, congruence_score, congruence_components, "
                "creative_awareness_level, copy_awareness_level, "
                "landing_page_awareness_level, classified_at"
            ).eq(
                "brand_id", str(brand_id)
            ).not_.is_(
                "congruence_components", "null"
            ).order(
                "classified_at", desc=True
            ).limit(limit * 2).execute()

            if not result.data:
                return []

            # Dedupe by meta_ad_id
            seen = set()
            unique_rows = []
            for row in result.data:
                ad_id = row.get("meta_ad_id")
                if ad_id and ad_id not in seen:
                    seen.add(ad_id)
                    unique_rows.append(row)
                    if len(unique_rows) >= limit:
                        break

            return unique_rows

        except Exception as e:
            logger.error(f"Error getting ads with congruence: {e}")
            return []
