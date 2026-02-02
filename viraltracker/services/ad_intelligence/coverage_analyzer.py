"""CoverageAnalyzer: Builds awareness × format coverage matrix, identifies gaps.

Analyzes the distribution of active ads across awareness levels and creative
formats to identify blind spots and single-points-of-failure (SPOFs).
"""

from __future__ import annotations

import logging
from datetime import date
from typing import Any, Dict, List
from uuid import UUID

from .helpers import get_active_ad_ids
from .models import AwarenessLevel, CoverageGapResult, CreativeFormat

logger = logging.getLogger(__name__)

# Key awareness levels to check (all enum values)
AWARENESS_LEVELS = [level.value for level in AwarenessLevel]

# Simplified format groups for coverage analysis
FORMAT_GROUPS = {
    "video": ["video_ugc", "video_professional", "video_testimonial", "video_demo"],
    "image": ["image_static", "image_before_after", "image_testimonial", "image_product"],
    "carousel": ["carousel"],
    "other": ["collection", "other"],
}


class CoverageAnalyzer:
    """Analyzes ad inventory coverage by awareness level and creative format.

    Identifies:
    - Hard gaps: Zero ads in a cell
    - SPOFs: < 2 ads (single point of failure)
    - Percentage gaps: < 10% of total active ads
    """

    def __init__(self, supabase_client):
        """Initialize with Supabase client.

        Args:
            supabase_client: Supabase client instance.
        """
        self.supabase = supabase_client

    async def analyze_coverage(
        self,
        brand_id: UUID,
        date_range_end: date,
        active_window_days: int = 7,
    ) -> CoverageGapResult:
        """Analyze ad inventory coverage and identify gaps.

        Uses get_active_ad_ids(date_range_end=date_range_end) for ad scope.
        Builds AwarenessLevel × CreativeFormat matrix of active ad counts.

        Args:
            brand_id: Brand UUID.
            date_range_end: End of analysis window (anchor date).
            active_window_days: Days to look back for active ads.

        Returns:
            CoverageGapResult with matrix, gaps, and recommendations.
        """
        brand_name = await self._get_brand_name(brand_id)

        # Get active ads
        active_ids = await get_active_ad_ids(
            self.supabase, brand_id, date_range_end, active_window_days
        )

        if not active_ids:
            return CoverageGapResult(
                brand_name=brand_name,
                gaps=[{"description": "No active ads found", "severity": "critical"}],
                recommendations=["Start running ads to build coverage data."],
            )

        # Get classifications for active ads
        classifications = await self._get_classifications(brand_id, active_ids)

        # Build coverage matrix
        matrix = self._build_matrix(classifications)

        # Identify gaps
        total_ads = len(active_ids)
        gaps = self._identify_gaps(matrix, total_ads)

        # Generate recommendations
        recommendations = self._generate_recommendations(gaps, matrix)

        return CoverageGapResult(
            brand_name=brand_name,
            coverage_matrix=matrix,
            gaps=gaps,
            recommendations=recommendations,
        )

    def _build_matrix(
        self, classifications: List[Dict]
    ) -> Dict[str, Dict[str, int]]:
        """Build awareness × format coverage matrix.

        Args:
            classifications: List of classification dicts.

        Returns:
            Nested dict: awareness_level → format_group → count.
        """
        matrix: Dict[str, Dict[str, int]] = {}

        for level in AWARENESS_LEVELS:
            matrix[level] = {}
            for group in FORMAT_GROUPS:
                matrix[level][group] = 0

        for cls in classifications:
            awareness = cls.get("creative_awareness_level")
            fmt = cls.get("creative_format")

            if not awareness or awareness not in matrix:
                continue

            # Map format to group
            group = self._format_to_group(fmt)
            if group in matrix[awareness]:
                matrix[awareness][group] += 1

        return matrix

    def _format_to_group(self, creative_format: str | None) -> str:
        """Map a specific creative format to its format group.

        Args:
            creative_format: Specific format string (e.g., "video_ugc").

        Returns:
            Format group name (e.g., "video").
        """
        if not creative_format:
            return "other"
        for group, formats in FORMAT_GROUPS.items():
            if creative_format in formats:
                return group
        return "other"

    def _identify_gaps(
        self,
        matrix: Dict[str, Dict[str, int]],
        total_ads: int,
    ) -> List[Dict[str, Any]]:
        """Identify coverage gaps in the matrix.

        Gap types:
        - Hard gap: Zero ads (severity: warning or critical)
        - SPOF: < 2 ads (severity: warning)
        - Percentage gap: < 10% of total (severity: info)

        Args:
            matrix: Coverage matrix.
            total_ads: Total number of active ads.

        Returns:
            List of gap descriptions.
        """
        gaps: List[Dict[str, Any]] = []
        threshold_pct = 0.10  # 10% of total

        for level, formats in matrix.items():
            level_total = sum(formats.values())
            level_label = level.replace("_", " ").title()

            # Check entire awareness level
            if level_total == 0:
                gaps.append({
                    "awareness_level": level,
                    "format": "all",
                    "count": 0,
                    "severity": "critical" if level in ("problem_aware", "solution_aware") else "warning",
                    "description": f"No ads targeting {level_label} awareness level",
                    "gap_type": "hard_gap",
                })
                continue

            # Check per-format within this level
            for fmt, count in formats.items():
                fmt_label = fmt.replace("_", " ").title()

                if count == 0:
                    # Don't flag every zero cell — only important combos
                    if fmt in ("video", "image"):
                        gaps.append({
                            "awareness_level": level,
                            "format": fmt,
                            "count": 0,
                            "severity": "warning",
                            "description": f"No {fmt_label} ads for {level_label}",
                            "gap_type": "hard_gap",
                        })

                elif count < 2:
                    gaps.append({
                        "awareness_level": level,
                        "format": fmt,
                        "count": count,
                        "severity": "warning",
                        "description": f"Only {count} {fmt_label} ad(s) for {level_label} (SPOF risk)",
                        "gap_type": "spof",
                    })

            # Check if this level has < 10% of total
            if total_ads > 10 and level_total < total_ads * threshold_pct:
                gaps.append({
                    "awareness_level": level,
                    "format": "all",
                    "count": level_total,
                    "severity": "info",
                    "description": (
                        f"{level_label} has only {level_total} ads "
                        f"({level_total / total_ads:.0%} of total)"
                    ),
                    "gap_type": "percentage_gap",
                })

        return gaps

    def _generate_recommendations(
        self,
        gaps: List[Dict[str, Any]],
        matrix: Dict[str, Dict[str, int]],
    ) -> List[str]:
        """Generate actionable recommendations based on gaps.

        Args:
            gaps: List of identified gaps.
            matrix: Coverage matrix.

        Returns:
            List of recommendation strings.
        """
        recs: List[str] = []

        critical_gaps = [g for g in gaps if g["severity"] == "critical"]
        warning_gaps = [g for g in gaps if g["severity"] == "warning"]

        if critical_gaps:
            levels = set(g["awareness_level"] for g in critical_gaps)
            for level in levels:
                label = level.replace("_", " ").title()
                recs.append(
                    f"Create ads targeting {label} awareness — "
                    f"this is a major gap in your funnel coverage."
                )

        spofs = [g for g in warning_gaps if g.get("gap_type") == "spof"]
        if spofs:
            recs.append(
                f"Address {len(spofs)} single-point-of-failure risks by "
                f"creating backup creatives for at-risk cells."
            )

        format_gaps = [g for g in warning_gaps if g.get("gap_type") == "hard_gap"]
        if format_gaps:
            formats_needed = set(g["format"] for g in format_gaps)
            for fmt in formats_needed:
                label = fmt.replace("_", " ").title()
                recs.append(f"Test {label} creatives for under-served awareness levels.")

        if not recs:
            recs.append("Coverage looks solid. Consider testing new angles within existing cells.")

        return recs

    async def _get_classifications(
        self,
        brand_id: UUID,
        meta_ad_ids: List[str],
    ) -> List[Dict]:
        """Get latest classifications for a set of ads.

        Args:
            brand_id: Brand UUID.
            meta_ad_ids: List of meta ad IDs.

        Returns:
            List of classification dicts (latest per ad).
        """
        try:
            result = self.supabase.table("ad_creative_classifications").select(
                "meta_ad_id, creative_awareness_level, creative_format"
            ).eq(
                "brand_id", str(brand_id)
            ).in_(
                "meta_ad_id", meta_ad_ids
            ).order(
                "classified_at", desc=True
            ).execute()

            # Deduplicate to latest per ad
            seen = set()
            deduplicated = []
            for row in result.data or []:
                ad_id = row.get("meta_ad_id")
                if ad_id and ad_id not in seen:
                    seen.add(ad_id)
                    deduplicated.append(row)

            return deduplicated

        except Exception as e:
            logger.error(f"Error fetching classifications: {e}")
            return []

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
