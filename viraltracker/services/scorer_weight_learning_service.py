"""
Scorer Weight Learning Service — Thompson Sampling for scorer weights.

Phase 8B: Upgrades template scoring from static weights to autonomously
learned weights per brand. Uses Beta(α,β) posteriors with credit assignment
from matured ad rewards.

Transition: cold (static) → warm (blended) → hot (fully learned).

Tables:
    - scorer_weight_posteriors: Beta(α,β) per (brand, scorer_name)
    - selection_weight_snapshots: Weights + scores at selection time
"""

import logging
import math
from datetime import datetime, timezone
from typing import Dict, List, Optional, Any
from uuid import UUID

logger = logging.getLogger(__name__)

# Static weight presets (must match SMART_SELECT_WEIGHTS in template_scoring_service.py)
STATIC_WEIGHTS: Dict[str, float] = {
    "asset_match": 1.0,
    "unused_bonus": 0.8,
    "category_match": 0.6,
    "awareness_align": 0.5,
    "audience_match": 0.4,
    "belief_clarity": 0.6,
    "performance": 0.3,
    "fatigue": 0.4,
}

# Phase transition thresholds
COLD_MAX = 29       # 0-29 observations: static only
WARM_MAX = 99       # 30-99: blended
HOT_MIN = 100       # 100+: fully learned

# Safety rails
WEIGHT_FLOOR = 0.1
WEIGHT_CEILING = 2.0
MAX_DELTA_PER_UPDATE = 0.15
REWARD_BINARIZE_THRESHOLD = 0.5

# Credit assignment: high-contribution scorers get full update, low get soft
SOFT_UPDATE_FACTOR = 0.3


class ScorerWeightLearningService:
    """Thompson Sampling for scorer weight optimization."""

    def __init__(self):
        from viraltracker.core.database import get_supabase_client
        self.supabase = get_supabase_client()

    # =========================================================================
    # Public: Get effective weights
    # =========================================================================

    def get_learned_weights(
        self,
        brand_id: UUID,
        mode: str = "smart_select",
    ) -> Dict[str, float]:
        """Return effective weights dict, same format as SMART_SELECT_WEIGHTS.

        For roll_the_dice mode, always returns static weights.
        For smart_select, blends based on learning phase.

        Args:
            brand_id: Brand UUID.
            mode: 'smart_select' or 'roll_the_dice'.

        Returns:
            Dict mapping scorer_name → effective weight.
        """
        if mode == "roll_the_dice":
            return dict(STATIC_WEIGHTS)

        posteriors = self._get_posteriors(brand_id)
        if not posteriors:
            return dict(STATIC_WEIGHTS)

        weights = {}
        for scorer_name, static_w in STATIC_WEIGHTS.items():
            posterior = posteriors.get(scorer_name)
            if not posterior:
                weights[scorer_name] = static_w
                continue

            obs = posterior["total_observations"]
            phase = posterior["learning_phase"]
            alpha = posterior["alpha"]
            beta_val = posterior["beta"]

            if phase == "cold" or obs <= COLD_MAX:
                weights[scorer_name] = static_w
            elif phase == "hot" or obs >= HOT_MIN:
                learned = alpha / (alpha + beta_val) if (alpha + beta_val) > 0 else static_w
                # Scale learned mean (0-1) to weight range using static as reference
                learned_weight = learned * (static_w / 0.5) if static_w > 0 else learned
                weights[scorer_name] = self._clamp_weight(learned_weight)
            else:
                # Warm: blend
                blend_alpha = (obs - COLD_MAX) / (HOT_MIN - COLD_MAX - 1)  # 0→1
                learned = alpha / (alpha + beta_val) if (alpha + beta_val) > 0 else static_w
                learned_weight = learned * (static_w / 0.5) if static_w > 0 else learned
                learned_weight = self._clamp_weight(learned_weight)
                blended = (1 - blend_alpha) * static_w + blend_alpha * learned_weight
                weights[scorer_name] = self._clamp_weight(blended)

        return weights

    def get_weight_status(self, brand_id: UUID) -> List[Dict[str, Any]]:
        """Return per-scorer learning status for UI display.

        Returns:
            List of dicts with scorer_name, phase, observations, static_weight,
            learned_weight, effective_weight.
        """
        posteriors = self._get_posteriors(brand_id)
        effective = self.get_learned_weights(brand_id, mode="smart_select")

        status = []
        for scorer_name, static_w in STATIC_WEIGHTS.items():
            posterior = posteriors.get(scorer_name, {})
            alpha = posterior.get("alpha", 1.0)
            beta_val = posterior.get("beta", 1.0)
            obs = posterior.get("total_observations", 0)
            phase = posterior.get("learning_phase", "cold")

            learned_mean = alpha / (alpha + beta_val) if (alpha + beta_val) > 0 else None

            status.append({
                "scorer_name": scorer_name,
                "learning_phase": phase,
                "total_observations": obs,
                "static_weight": static_w,
                "learned_mean": round(learned_mean, 4) if learned_mean else None,
                "effective_weight": round(effective.get(scorer_name, static_w), 4),
                "alpha": round(alpha, 2),
                "beta": round(beta_val, 2),
            })

        return status

    # =========================================================================
    # Public: Record selection snapshot
    # =========================================================================

    def record_selection_snapshot(
        self,
        brand_id: UUID,
        ad_run_id: str,
        template_id: Optional[str],
        weights_used: Dict[str, float],
        scorer_breakdown: Dict[str, float],
        composite_score: Optional[float],
        selection_mode: Optional[str],
    ) -> None:
        """Record what weights and scores were used at selection time.

        Called from CompileResultsNode after ad_run_id is available.
        """
        try:
            posteriors = self._get_posteriors(brand_id)
            phase = "cold"
            if posteriors:
                min_obs = min(p.get("total_observations", 0) for p in posteriors.values())
                if min_obs >= HOT_MIN:
                    phase = "hot"
                elif min_obs > COLD_MAX:
                    phase = "warm"

            self.supabase.table("selection_weight_snapshots").insert({
                "brand_id": str(brand_id),
                "ad_run_id": ad_run_id,
                "template_id": template_id,
                "weights_used": weights_used,
                "scorer_breakdown": scorer_breakdown,
                "composite_score": composite_score,
                "learning_phase": phase,
                "selection_mode": selection_mode,
            }).execute()
        except Exception as e:
            logger.warning(f"Failed to record selection snapshot: {e}")

    # =========================================================================
    # Public: Initialize posteriors for a brand
    # =========================================================================

    def initialize_posteriors(self, brand_id: UUID) -> None:
        """Seed scorer_weight_posteriors with static weights for a brand.

        Idempotent — skips if already initialized.
        """
        existing = self.supabase.table("scorer_weight_posteriors").select(
            "id", count="exact"
        ).eq("brand_id", str(brand_id)).execute()

        if existing.count and existing.count > 0:
            return

        rows = []
        for scorer_name, static_w in STATIC_WEIGHTS.items():
            rows.append({
                "brand_id": str(brand_id),
                "scorer_name": scorer_name,
                "alpha": 1.0,
                "beta": 1.0,
                "total_observations": 0,
                "static_weight": static_w,
                "learning_phase": "cold",
            })

        if rows:
            self.supabase.table("scorer_weight_posteriors").insert(rows).execute()
            logger.info(f"Initialized {len(rows)} scorer posteriors for brand {brand_id}")

    # =========================================================================
    # Public: Update posteriors from matured ad rewards
    # =========================================================================

    async def update_scorer_posteriors(self, brand_id: UUID) -> Dict[str, Any]:
        """Weekly job: attribute rewards to scorer weights via credit assignment.

        Algorithm:
        1. Find matured ads with rewards that have selection_weight_snapshots
        2. For each ad: compute each scorer's contribution
        3. Binarize reward at threshold
        4. Update Beta distributions with contribution-weighted credit

        Returns:
            Summary dict with ads_processed, updates_applied.
        """
        # Get selection snapshots with rewards
        snapshots_result = self.supabase.table("selection_weight_snapshots").select(
            "*, creative_element_rewards!inner(reward_score)"
        ).eq("brand_id", str(brand_id)).is_("scorer_breakdown", "not.null").execute()

        # Fallback: join manually if the above foreign key join doesn't work
        if not snapshots_result.data:
            snapshots_result = self.supabase.table("selection_weight_snapshots").select(
                "*"
            ).eq("brand_id", str(brand_id)).execute()

        if not snapshots_result.data:
            return {"ads_processed": 0, "updates_applied": 0}

        # Load rewards keyed by ad_run_id
        ad_run_ids = [s["ad_run_id"] for s in snapshots_result.data]
        rewards_result = self.supabase.table("creative_element_rewards").select(
            "ad_run_id, reward_score"
        ).eq("brand_id", str(brand_id)).in_("ad_run_id", ad_run_ids).execute()

        reward_map: Dict[str, float] = {}
        for r in (rewards_result.data or []):
            ad_run = r.get("ad_run_id")
            if ad_run:
                reward_map[ad_run] = r["reward_score"]

        # Load current posteriors
        posteriors = self._get_posteriors(brand_id)
        if not posteriors:
            self.initialize_posteriors(brand_id)
            posteriors = self._get_posteriors(brand_id)

        # Accumulate updates
        updates: Dict[str, Dict[str, float]] = {
            name: {"alpha_delta": 0.0, "beta_delta": 0.0, "count": 0}
            for name in STATIC_WEIGHTS
        }

        ads_processed = 0
        for snapshot in snapshots_result.data:
            ad_run_id = snapshot.get("ad_run_id")
            reward = reward_map.get(ad_run_id)
            if reward is None:
                continue

            weights_used = snapshot.get("weights_used") or {}
            scorer_breakdown = snapshot.get("scorer_breakdown") or {}

            if not weights_used or not scorer_breakdown:
                continue

            # Compute weighted contributions
            contributions = {}
            total_contribution = 0.0
            for scorer_name in STATIC_WEIGHTS:
                w = weights_used.get(scorer_name, 0.0)
                s = scorer_breakdown.get(scorer_name, 0.0)
                contrib = w * s
                contributions[scorer_name] = contrib
                total_contribution += contrib

            if total_contribution <= 0:
                continue

            # Normalize contributions
            for name in contributions:
                contributions[name] /= total_contribution

            # Compute median contribution for high/low split
            contrib_values = sorted(contributions.values())
            median_contrib = contrib_values[len(contrib_values) // 2] if contrib_values else 0.0

            # Binarize reward
            is_success = reward >= REWARD_BINARIZE_THRESHOLD

            # Credit assignment
            for scorer_name, contrib in contributions.items():
                is_high = contrib >= median_contrib
                update_strength = 1.0 if is_high else SOFT_UPDATE_FACTOR

                if is_success:
                    updates[scorer_name]["alpha_delta"] += update_strength
                else:
                    updates[scorer_name]["beta_delta"] += update_strength
                updates[scorer_name]["count"] += 1

            ads_processed += 1

        # Apply updates with safety rails
        updates_applied = 0
        now = datetime.now(timezone.utc).isoformat()

        for scorer_name, deltas in updates.items():
            if deltas["count"] == 0:
                continue

            posterior = posteriors.get(scorer_name)
            if not posterior:
                continue

            old_alpha = posterior["alpha"]
            old_beta = posterior["beta"]
            old_obs = posterior["total_observations"]

            # Clamp deltas per update cycle
            alpha_delta = min(deltas["alpha_delta"], MAX_DELTA_PER_UPDATE * deltas["count"])
            beta_delta = min(deltas["beta_delta"], MAX_DELTA_PER_UPDATE * deltas["count"])

            new_alpha = old_alpha + alpha_delta
            new_beta = old_beta + beta_delta
            new_obs = old_obs + deltas["count"]

            # Determine phase
            if new_obs <= COLD_MAX:
                phase = "cold"
            elif new_obs <= WARM_MAX:
                phase = "warm"
            else:
                phase = "hot"

            # Compute mean reward for this scorer
            mean_reward = new_alpha / (new_alpha + new_beta) if (new_alpha + new_beta) > 0 else None

            self.supabase.table("scorer_weight_posteriors").update({
                "alpha": round(new_alpha, 4),
                "beta": round(new_beta, 4),
                "total_observations": new_obs,
                "mean_reward": round(mean_reward, 4) if mean_reward else None,
                "learning_phase": phase,
                "last_updated": now,
            }).eq("brand_id", str(brand_id)).eq("scorer_name", scorer_name).execute()

            updates_applied += 1

        logger.info(
            f"Scorer weight learning for brand {brand_id}: "
            f"{ads_processed} ads processed, {updates_applied} scorers updated"
        )

        return {"ads_processed": ads_processed, "updates_applied": updates_applied}

    # =========================================================================
    # Internal helpers
    # =========================================================================

    def _get_posteriors(self, brand_id: UUID) -> Dict[str, Dict[str, Any]]:
        """Load posteriors for a brand, keyed by scorer_name."""
        result = self.supabase.table("scorer_weight_posteriors").select(
            "scorer_name, alpha, beta, total_observations, mean_reward, "
            "static_weight, learning_phase"
        ).eq("brand_id", str(brand_id)).execute()

        return {
            r["scorer_name"]: r
            for r in (result.data or [])
        }

    @staticmethod
    def _clamp_weight(w: float) -> float:
        """Clamp weight to [WEIGHT_FLOOR, WEIGHT_CEILING]."""
        return max(WEIGHT_FLOOR, min(WEIGHT_CEILING, w))
