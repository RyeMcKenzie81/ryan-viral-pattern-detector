"""
Whitespace Identification Service — Find untested high-potential element combos.

Phase 8B: Identifies competitive whitespace by scoring untested pairwise element
combinations based on individual performance, synergy effects, and novelty.

Tables:
    - whitespace_candidates: Ranked untested combos
    - creative_element_scores: Individual element performance
    - element_interactions: Synergy/conflict effects
    - element_combo_usage: Usage counts per combo
"""

import logging
import math
from itertools import product as iter_product
from typing import Dict, List, Optional, Any
from uuid import UUID

logger = logging.getLogger(__name__)

# From creative_genome_service.py
TRACKED_ELEMENTS = [
    "hook_type", "color_mode", "template_category",
    "awareness_stage", "canvas_size", "content_source",
]

# Scoring constants
NOVELTY_WEIGHT = 0.15
NOVELTY_DECAY = 3.0
MIN_INDIVIDUAL_SCORE = 0.5
MAX_USAGE_FOR_WHITESPACE = 5
MAX_CANDIDATES = 20


class WhitespaceIdentificationService:
    """Identify untested element combos with high predicted potential."""

    def __init__(self):
        from viraltracker.core.database import get_supabase_client
        self.supabase = get_supabase_client()

    async def identify_whitespace(
        self,
        brand_id: UUID,
        window_days: int = 90,
    ) -> Dict[str, Any]:
        """Find untested high-potential element combos and upsert to DB.

        Algorithm:
        1. Load individual element scores
        2. Load interaction effects (synergy/conflict)
        3. Load combo usage counts
        4. Generate valid cross-dimension pairwise combos
        5. Score: mean(score_a, score_b) + synergy + novelty
        6. Filter: both scores > 0.5, usage < 5, no conflicts
        7. Rank and keep top 20

        Args:
            brand_id: Brand UUID.
            window_days: Performance lookback window.

        Returns:
            Summary dict with candidates_found, new_candidates, updated.
        """
        # 1. Load individual element scores
        scores_result = self.supabase.table("creative_element_scores").select(
            "element_name, element_value, alpha, beta, total_observations"
        ).eq("brand_id", str(brand_id)).execute()

        element_scores: Dict[str, Dict[str, float]] = {}
        for row in (scores_result.data or []):
            name = row["element_name"]
            value = row["element_value"]
            alpha = row.get("alpha", 1.0)
            beta = row.get("beta", 1.0)
            mean_score = alpha / (alpha + beta) if (alpha + beta) > 0 else 0.5
            if name not in element_scores:
                element_scores[name] = {}
            element_scores[name][value] = mean_score

        if not element_scores:
            return {"candidates_found": 0, "new_candidates": 0, "updated": False}

        # 2. Load interaction effects
        interactions_result = self.supabase.table("element_interactions").select(
            "element_a_name, element_a_value, element_b_name, element_b_value, "
            "interaction_effect, effect_direction"
        ).eq("brand_id", str(brand_id)).execute()

        interactions: Dict[str, Dict[str, Any]] = {}
        for row in (interactions_result.data or []):
            key = f"{row['element_a_name']}={row['element_a_value']}|{row['element_b_name']}={row['element_b_value']}"
            interactions[key] = {
                "effect": row.get("interaction_effect", 0.0),
                "direction": row.get("effect_direction", "neutral"),
            }

        # 3. Load combo usage counts
        usage_result = self.supabase.table("element_combo_usage").select(
            "combo_key, times_used"
        ).eq("brand_id", str(brand_id)).execute()

        usage_counts: Dict[str, int] = {}
        for row in (usage_result.data or []):
            usage_counts[row["combo_key"]] = row.get("times_used", 0)

        # 4. Generate valid cross-dimension pairwise combos
        candidates = []
        element_names = [e for e in TRACKED_ELEMENTS if e in element_scores]

        for i, name_a in enumerate(element_names):
            for name_b in element_names[i + 1:]:
                for val_a, score_a in element_scores[name_a].items():
                    for val_b, score_b in element_scores[name_b].items():
                        # Filter: both individual scores above threshold
                        if score_a < MIN_INDIVIDUAL_SCORE or score_b < MIN_INDIVIDUAL_SCORE:
                            continue

                        # Build canonical combo key for usage lookup
                        parts = sorted([f"{name_a}={val_a}", f"{name_b}={val_b}"])
                        usage_key = "|".join(parts)
                        usage_count = usage_counts.get(usage_key, 0)

                        # Filter: low usage only
                        if usage_count >= MAX_USAGE_FOR_WHITESPACE:
                            continue

                        # Canonical ordering for interaction lookup
                        if (name_a, val_a) <= (name_b, val_b):
                            interaction_key = f"{name_a}={val_a}|{name_b}={val_b}"
                        else:
                            interaction_key = f"{name_b}={val_b}|{name_a}={val_a}"

                        interaction = interactions.get(interaction_key, {})
                        synergy = interaction.get("effect", 0.0)

                        # Filter: no known conflicts
                        if interaction.get("direction") == "conflict":
                            continue

                        # 5. Score
                        base_score = (score_a + score_b) / 2.0
                        novelty_bonus = NOVELTY_WEIGHT * math.exp(-usage_count / NOVELTY_DECAY)
                        synergy_bonus = max(0.0, synergy)  # only positive synergy

                        predicted_potential = base_score + synergy_bonus + novelty_bonus

                        candidates.append({
                            "element_a_name": name_a,
                            "element_a_value": val_a,
                            "element_b_name": name_b,
                            "element_b_value": val_b,
                            "predicted_potential": round(predicted_potential, 4),
                            "individual_a_score": round(score_a, 4),
                            "individual_b_score": round(score_b, 4),
                            "synergy_bonus": round(synergy_bonus, 4),
                            "usage_count": usage_count,
                        })

        # 6. Rank by predicted_potential, keep top N
        candidates.sort(key=lambda c: c["predicted_potential"], reverse=True)
        top_candidates = candidates[:MAX_CANDIDATES]

        # Assign ranks
        for rank, c in enumerate(top_candidates, 1):
            c["whitespace_rank"] = rank

        # 7. Upsert to DB
        new_count = 0
        for c in top_candidates:
            try:
                self.supabase.table("whitespace_candidates").upsert(
                    {
                        "brand_id": str(brand_id),
                        "element_a_name": c["element_a_name"],
                        "element_a_value": c["element_a_value"],
                        "element_b_name": c["element_b_name"],
                        "element_b_value": c["element_b_value"],
                        "predicted_potential": c["predicted_potential"],
                        "individual_a_score": c["individual_a_score"],
                        "individual_b_score": c["individual_b_score"],
                        "synergy_bonus": c["synergy_bonus"],
                        "usage_count": c["usage_count"],
                        "whitespace_rank": c["whitespace_rank"],
                        "status": "identified",
                    },
                    on_conflict="brand_id, element_a_name, element_a_value, element_b_name, element_b_value",
                ).execute()
                new_count += 1
            except Exception as e:
                logger.debug(f"Whitespace upsert failed for {c}: {e}")

        logger.info(f"Whitespace identification for brand {brand_id}: {len(top_candidates)} candidates")

        return {
            "candidates_found": len(top_candidates),
            "new_candidates": new_count,
            "updated": True,
        }

    def get_whitespace_candidates(
        self,
        brand_id: UUID,
        limit: int = 20,
    ) -> List[Dict[str, Any]]:
        """Read whitespace candidates from DB, ordered by rank.

        Args:
            brand_id: Brand UUID.
            limit: Max candidates to return.

        Returns:
            List of candidate dicts.
        """
        result = self.supabase.table("whitespace_candidates").select(
            "*"
        ).eq("brand_id", str(brand_id)).eq(
            "status", "identified"
        ).order("whitespace_rank").limit(limit).execute()

        return result.data or []

    def format_whitespace_advisory(
        self,
        candidates: List[Dict[str, Any]],
        limit: int = 3,
    ) -> Optional[str]:
        """Format whitespace candidates for prompt injection.

        Args:
            candidates: Whitespace candidate dicts.
            limit: Max candidates to include.

        Returns:
            Advisory string or None if no candidates.
        """
        if not candidates:
            return None

        top = candidates[:limit]
        lines = ["Untested high-potential combos to consider:"]
        for c in top:
            lines.append(
                f"  - {c['element_a_name']}={c['element_a_value']} + "
                f"{c['element_b_name']}={c['element_b_value']} "
                f"(potential: {c['predicted_potential']:.2f})"
            )

        return " | ".join(lines)
