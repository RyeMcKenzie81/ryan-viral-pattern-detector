"""CongruenceChecker: Creative-copy-LP alignment checker.

Evaluates whether the awareness levels of creative, copy, and landing page
are congruent. Large gaps indicate misalignment that may hurt conversion.
"""

from __future__ import annotations

import logging
from typing import Any, Dict, List
from uuid import UUID

from .helpers import _safe_numeric
from .models import CongruenceCheckResult

logger = logging.getLogger(__name__)


class CongruenceChecker:
    """Checks creative-copy-LP awareness level alignment.

    Score formula: 1.0 - (max_ordinal_gap / 4)
    - Perfect alignment (all same level) → 1.0
    - Max misalignment (unaware ↔ most_aware) → 0.0
    - Uses 2-way score when LP data is missing
    """

    AWARENESS_ORDINAL = {
        "unaware": 1,
        "problem_aware": 2,
        "solution_aware": 3,
        "product_aware": 4,
        "most_aware": 5,
    }

    def __init__(self, supabase_client):
        """Initialize with Supabase client.

        Args:
            supabase_client: Supabase client instance.
        """
        self.supabase = supabase_client

    async def check_congruence(
        self,
        brand_id: UUID,
    ) -> CongruenceCheckResult:
        """Check congruence across all classified ads for a brand.

        Fetches latest classification per ad, computes congruence score,
        and identifies misaligned ads (score < 0.75).

        Args:
            brand_id: Brand UUID.

        Returns:
            CongruenceCheckResult with scores and misaligned ads.
        """
        brand_name = await self._get_brand_name(brand_id)

        # Fetch all classifications
        classifications = await self._get_classifications(brand_id)

        if not classifications:
            return CongruenceCheckResult(
                brand_name=brand_name,
            )

        misaligned: List[Dict[str, Any]] = []
        scores: List[float] = []

        for cls in classifications:
            creative_level = cls.get("creative_awareness_level")
            copy_level = cls.get("copy_awareness_level")

            if not creative_level or not copy_level:
                continue

            lp_level = cls.get("landing_page_awareness_level")
            score = self._compute_score(creative_level, copy_level, lp_level)

            if score is not None:
                scores.append(score)

                # Threshold for misalignment
                if score < 0.75:
                    misaligned.append({
                        "meta_ad_id": cls.get("meta_ad_id", ""),
                        "ad_name": cls.get("meta_ad_id", ""),
                        "creative_level": creative_level,
                        "copy_level": copy_level,
                        "lp_level": lp_level or "N/A",
                        "congruence_score": round(score, 3),
                    })

        avg_congruence = sum(scores) / len(scores) if scores else 0.0

        return CongruenceCheckResult(
            brand_name=brand_name,
            checked_ads=len(classifications),
            misaligned_ads=sorted(misaligned, key=lambda x: x["congruence_score"]),
            average_congruence=round(avg_congruence, 3),
        )

    def _compute_score(
        self,
        creative_level: str,
        copy_level: str,
        lp_level: str | None = None,
    ) -> float | None:
        """Compute congruence score between awareness levels.

        Score = 1.0 - (max_ordinal_gap / 4).
        Uses 2-way score when LP data missing.

        Args:
            creative_level: Creative awareness level.
            copy_level: Copy awareness level.
            lp_level: Landing page awareness level (optional).

        Returns:
            Score (0.0 to 1.0) or None if levels invalid.
        """
        creative_ord = self.AWARENESS_ORDINAL.get(creative_level, 0)
        copy_ord = self.AWARENESS_ORDINAL.get(copy_level, 0)

        if creative_ord == 0 or copy_ord == 0:
            return None

        if lp_level and self.AWARENESS_ORDINAL.get(lp_level, 0) > 0:
            lp_ord = self.AWARENESS_ORDINAL[lp_level]
            max_gap = max(
                abs(creative_ord - copy_ord),
                abs(creative_ord - lp_ord),
                abs(copy_ord - lp_ord),
            )
        else:
            max_gap = abs(creative_ord - copy_ord)

        return 1.0 - (max_gap / 4.0)

    async def _get_classifications(
        self, brand_id: UUID
    ) -> List[Dict]:
        """Get latest classifications for all ads of a brand.

        Args:
            brand_id: Brand UUID.

        Returns:
            List of classification dicts (latest per ad).
        """
        try:
            result = self.supabase.table("ad_creative_classifications").select(
                "meta_ad_id, creative_awareness_level, copy_awareness_level, "
                "landing_page_awareness_level, congruence_score"
            ).eq(
                "brand_id", str(brand_id)
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
