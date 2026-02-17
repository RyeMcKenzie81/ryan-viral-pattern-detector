"""
Interaction Detector Service — Pairwise element effect detection.

Phase 8A: Detects top 15 element pair interactions from creative_element_rewards
joined with generated_ads.element_tags. Computes observed vs expected reward,
bootstrap confidence intervals, and stores in element_interactions table.
"""

import logging
import math
from collections import defaultdict
from itertools import combinations
from typing import Dict, List, Optional, Any, Tuple
from uuid import UUID

import numpy as np

logger = logging.getLogger(__name__)

# Elements tracked (from creative_genome_service.py)
TRACKED_ELEMENTS = [
    "hook_type", "color_mode", "template_category",
    "awareness_stage", "canvas_size", "content_source",
]

# Minimum ads with a pair to compute interaction
MIN_PAIR_SAMPLE = 10

# Effect direction thresholds
SYNERGY_THRESHOLD = 0.05
CONFLICT_THRESHOLD = -0.05


class InteractionDetectorService:
    """Detect element pair interaction effects from creative performance data."""

    async def detect_interactions(
        self,
        brand_id: UUID,
        window_days: int = 90,
        min_sample_size: int = MIN_PAIR_SAMPLE,
    ) -> Dict[str, Any]:
        """Detect top 15 element pair interactions.

        Method:
        1. Load matured ads with reward_score + element_tags for this brand
        2. For each pair of TRACKED_ELEMENTS values, compute observed vs expected
        3. Canonical ordering: (a_name, a_value) <= (b_name, b_value) alphabetically
        4. Expected = E[reward|A] * E[reward|B] / E[reward] (independence)
        5. Interaction effect = observed mean reward - expected
        6. Bootstrap 95% CI for effect estimate
        7. Rank by absolute effect size, keep top 15
        8. Classify: synergy (>0.05), conflict (<-0.05), neutral
        9. Upsert into element_interactions

        Args:
            brand_id: Brand UUID.
            window_days: How far back to analyze.
            min_sample_size: Minimum ads with pair for valid interaction.

        Returns:
            {interactions: [...], total_pairs_tested, total_ads_analyzed, brand_id}
        """
        from viraltracker.core.database import get_supabase_client
        from datetime import datetime, timedelta, timezone

        db = get_supabase_client()
        cutoff = (datetime.now(timezone.utc) - timedelta(days=window_days)).isoformat()

        # Load matured ads with rewards and element tags
        result = db.table("creative_element_rewards").select(
            "generated_ad_id, reward_score, "
            "generated_ads!inner(id, element_tags)"
        ).eq(
            "brand_id", str(brand_id)
        ).gte("created_at", cutoff).execute()

        rows = result.data or []
        if not rows:
            logger.info(f"No reward data for brand {brand_id}, skipping interaction detection")
            return {
                "interactions": [],
                "total_pairs_tested": 0,
                "total_ads_analyzed": 0,
                "brand_id": str(brand_id),
            }

        # Build ad records: [(reward, {element_name: element_value})]
        ad_records = []
        for row in rows:
            reward = row.get("reward_score")
            ad_data = row.get("generated_ads", {})
            tags = ad_data.get("element_tags") or {}

            if reward is None:
                continue

            elements = {}
            for elem_name in TRACKED_ELEMENTS:
                val = tags.get(elem_name)
                if val is not None:
                    elements[elem_name] = str(val)

            if elements:
                ad_records.append((float(reward), elements))

        if not ad_records:
            return {
                "interactions": [],
                "total_pairs_tested": 0,
                "total_ads_analyzed": 0,
                "brand_id": str(brand_id),
            }

        total_ads = len(ad_records)

        # Compute global mean reward
        all_rewards = [r for r, _ in ad_records]
        global_mean = np.mean(all_rewards)

        if global_mean == 0:
            global_mean = 1e-6  # avoid division by zero

        # Compute marginal means: E[reward | element_name=value]
        marginal_rewards = defaultdict(list)
        for reward, elements in ad_records:
            for elem_name, elem_value in elements.items():
                marginal_rewards[(elem_name, elem_value)].append(reward)

        marginal_means = {
            key: np.mean(rewards)
            for key, rewards in marginal_rewards.items()
        }

        # Compute pairwise interactions
        # Get all unique (element_name, element_value) pairs
        all_element_values = set()
        for _, elements in ad_records:
            for elem_name, elem_value in elements.items():
                all_element_values.add((elem_name, elem_value))

        pair_data = defaultdict(list)  # (a, b) -> [rewards]
        for reward, elements in ad_records:
            element_list = [(n, v) for n, v in elements.items()]
            for i in range(len(element_list)):
                for j in range(i + 1, len(element_list)):
                    a, b = element_list[i], element_list[j]
                    # Canonical ordering
                    if a > b:
                        a, b = b, a
                    pair_data[(a, b)].append(reward)

        # Compute interaction effects
        interactions = []
        total_pairs_tested = 0

        for (a, b), rewards in pair_data.items():
            if len(rewards) < min_sample_size:
                continue

            total_pairs_tested += 1

            observed_mean = np.mean(rewards)
            expected = (marginal_means.get(a, global_mean)
                       * marginal_means.get(b, global_mean)
                       / global_mean)

            effect = observed_mean - expected

            # Bootstrap 95% CI
            ci_low, ci_high = self._bootstrap_ci(rewards, expected, n_bootstrap=1000)

            # P-value approximation (z-test)
            se = np.std(rewards) / math.sqrt(len(rewards)) if len(rewards) > 1 else 1.0
            if se > 0:
                z = abs(effect) / se
                # Approximate two-sided p-value
                p_value = 2 * (1 - self._norm_cdf(z))
            else:
                p_value = 1.0

            # Effect direction
            if effect > SYNERGY_THRESHOLD:
                direction = "synergy"
            elif effect < CONFLICT_THRESHOLD:
                direction = "conflict"
            else:
                direction = "neutral"

            interactions.append({
                "element_a_name": a[0],
                "element_a_value": a[1],
                "element_b_name": b[0],
                "element_b_value": b[1],
                "interaction_effect": round(effect, 4),
                "effect_direction": direction,
                "confidence_interval_low": round(ci_low, 4),
                "confidence_interval_high": round(ci_high, 4),
                "sample_size": len(rewards),
                "p_value": round(p_value, 4),
            })

        # Rank by absolute effect size, keep top 15
        interactions.sort(key=lambda x: abs(x["interaction_effect"]), reverse=True)
        top_interactions = interactions[:15]

        # Assign ranks
        for i, interaction in enumerate(top_interactions):
            interaction["effect_rank"] = i + 1

        # Upsert into database
        await self._upsert_interactions(db, brand_id, top_interactions, window_days)

        logger.info(
            f"Detected {len(top_interactions)} interactions for brand {brand_id} "
            f"({total_pairs_tested} pairs tested, {total_ads} ads analyzed)"
        )

        return {
            "interactions": top_interactions,
            "total_pairs_tested": total_pairs_tested,
            "total_ads_analyzed": total_ads,
            "brand_id": str(brand_id),
        }

    async def get_top_interactions(
        self, brand_id: UUID, limit: int = 15
    ) -> List[Dict[str, Any]]:
        """Get top interactions from DB (latest computation).

        Args:
            brand_id: Brand UUID.
            limit: Max results.

        Returns:
            List of interaction dicts ordered by effect_rank.
        """
        from viraltracker.core.database import get_supabase_client

        db = get_supabase_client()
        result = db.table("element_interactions").select("*").eq(
            "brand_id", str(brand_id)
        ).order("effect_rank").limit(limit).execute()

        return result.data or []

    def format_advisory_context(self, interactions: List[Dict[str, Any]]) -> str:
        """Format interactions for genome advisory prompt injection.

        Args:
            interactions: List of interaction dicts.

        Returns:
            Natural language summary string.
        """
        if not interactions:
            return ""

        parts = []
        synergies = [i for i in interactions if i["effect_direction"] == "synergy"]
        conflicts = [i for i in interactions if i["effect_direction"] == "conflict"]

        for s in synergies[:3]:
            effect_pct = s["interaction_effect"] * 100
            parts.append(
                f"Strong synergy: {s['element_a_name']}={s['element_a_value']} + "
                f"{s['element_b_name']}={s['element_b_value']} "
                f"(+{effect_pct:.0f}% lift, N={s['sample_size']})"
            )

        for c in conflicts[:3]:
            effect_pct = abs(c["interaction_effect"]) * 100
            parts.append(
                f"Avoid: {c['element_a_name']}={c['element_a_value']} + "
                f"{c['element_b_name']}={c['element_b_value']} "
                f"(-{effect_pct:.0f}% drag, N={c['sample_size']})"
            )

        return " | ".join(parts) if parts else ""

    # ========================================================================
    # Internal helpers
    # ========================================================================

    def _bootstrap_ci(
        self,
        rewards: List[float],
        expected: float,
        n_bootstrap: int = 1000,
        alpha: float = 0.05,
    ) -> Tuple[float, float]:
        """Compute bootstrap confidence interval for interaction effect."""
        rng = np.random.default_rng(42)
        arr = np.array(rewards)
        effects = []

        for _ in range(n_bootstrap):
            sample = rng.choice(arr, size=len(arr), replace=True)
            effect = np.mean(sample) - expected
            effects.append(effect)

        effects = np.array(effects)
        ci_low = float(np.percentile(effects, 100 * alpha / 2))
        ci_high = float(np.percentile(effects, 100 * (1 - alpha / 2)))
        return ci_low, ci_high

    def _norm_cdf(self, x: float) -> float:
        """Standard normal CDF approximation."""
        return 0.5 * (1.0 + math.erf(x / math.sqrt(2.0)))

    async def _upsert_interactions(
        self,
        db,
        brand_id: UUID,
        interactions: List[Dict[str, Any]],
        window_days: int,
    ) -> None:
        """Upsert top interactions into element_interactions table.

        Deletes existing rows for this brand first (full refresh).
        """
        from datetime import datetime, timezone

        # Delete old interactions for this brand
        db.table("element_interactions").delete().eq(
            "brand_id", str(brand_id)
        ).execute()

        if not interactions:
            return

        now = datetime.now(timezone.utc).isoformat()

        rows = []
        for interaction in interactions:
            rows.append({
                "brand_id": str(brand_id),
                "element_a_name": interaction["element_a_name"],
                "element_a_value": interaction["element_a_value"],
                "element_b_name": interaction["element_b_name"],
                "element_b_value": interaction["element_b_value"],
                "interaction_effect": interaction["interaction_effect"],
                "effect_direction": interaction["effect_direction"],
                "confidence_interval_low": interaction["confidence_interval_low"],
                "confidence_interval_high": interaction["confidence_interval_high"],
                "sample_size": interaction["sample_size"],
                "p_value": interaction["p_value"],
                "effect_rank": interaction["effect_rank"],
                "computed_at": now,
                "computation_window_days": window_days,
            })

        db.table("element_interactions").insert(rows).execute()
