"""
Winner Evolution Service — Evolve winning ads into improved variants.

Phase 7A: Three evolution modes:
1. Winner Iteration (a): Change ONE creative element, regenerate via V2 pipeline
2. Anti-Fatigue Refresh (c): Same psychology, fresh visual execution
3. Cross-Size Expansion (d): Generate winner in untested canvas sizes

Architecture: Job builder wrapping run_ad_creation_v2().
- Validates winner criteria and iteration limits
- Selects variable to change via information-gain weighted Thompson Sampling
- Builds V2 pipeline params with the change applied
- Records lineage entries after pipeline completion

Tables:
    - ad_lineage: Parent→child evolution tracking
    - creative_element_rewards: Winner criteria (reward_score)
    - creative_element_scores: Beta(α,β) for variable selection
"""

import base64
import logging
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional, Tuple
from uuid import UUID

import numpy as np

logger = logging.getLogger(__name__)


# =============================================================================
# Constants
# =============================================================================

# Winner criteria
WINNER_MIN_DAYS = 7
WINNER_MIN_IMPRESSIONS = 1000
WINNER_MIN_REWARD_SCORE = 0.65

# Iteration limits
MAX_ITERATIONS_PER_WINNER = 5
MAX_ROUNDS_ON_ANCESTOR = 3

# Evolution modes
EVOLUTION_MODES = ["winner_iteration", "anti_fatigue_refresh", "cross_size_expansion"]

# All valid canvas sizes for cross-size expansion
ALL_CANVAS_SIZES = ["1080x1080px", "1080x1350px", "1080x1920px"]

# Variable selection priority weights (higher = more important to test)
VARIABLE_PRIORITY_WEIGHTS = {
    "hook_type": 0.9,
    "awareness_stage": 0.85,
    "template_category": 0.6,
    "color_mode": 0.4,
}

# Elements eligible for single-variable iteration
ITERABLE_ELEMENTS = list(VARIABLE_PRIORITY_WEIGHTS.keys())


class WinnerEvolutionService:
    """Service for evolving winning ads into improved variants."""

    def __init__(self):
        from viraltracker.core.database import get_supabase_client
        self.supabase = get_supabase_client()

    # =========================================================================
    # Winner Detection
    # =========================================================================

    async def check_winner_criteria(self, ad_id: UUID) -> Dict[str, Any]:
        """Check if a specific ad meets winner criteria.

        Winner criteria (all must be met):
        - >= 7 days of matured performance data
        - >= 1000 impressions
        - reward_score >= 0.65 OR CTR in top quartile OR ROAS in top quartile

        Args:
            ad_id: Generated ad UUID.

        Returns:
            Dict with is_winner flag and supporting data.
        """
        # Look up reward
        reward_row = self.supabase.table("creative_element_rewards").select(
            "reward_score, impressions_at_maturity, matured_at, campaign_objective"
        ).eq("generated_ad_id", str(ad_id)).limit(1).execute()

        if not reward_row.data:
            return {
                "is_winner": False,
                "reason": "No performance data (ad not yet matured)",
                "reward_score": None,
                "impressions": None,
                "days_matured": None,
            }

        row = reward_row.data[0]
        reward_score = row.get("reward_score") or 0.0
        impressions = row.get("impressions_at_maturity") or 0

        # Calculate days since maturation
        matured_at = row.get("matured_at")
        days_matured = None
        if matured_at:
            try:
                matured_dt = datetime.fromisoformat(
                    matured_at.replace("Z", "+00:00")
                )
                days_matured = (datetime.now(timezone.utc) - matured_dt).days
            except (ValueError, TypeError):
                pass

        # Check impression threshold
        if impressions < WINNER_MIN_IMPRESSIONS:
            return {
                "is_winner": False,
                "reason": f"Insufficient impressions ({impressions} < {WINNER_MIN_IMPRESSIONS})",
                "reward_score": reward_score,
                "impressions": impressions,
                "days_matured": days_matured,
            }

        # Check reward score threshold
        is_reward_winner = reward_score >= WINNER_MIN_REWARD_SCORE

        # Check CTR/ROAS quartile (via performance data)
        is_quartile_winner = False
        quartile_details = {}
        if not is_reward_winner:
            quartile_details = await self._check_top_quartile(ad_id)
            is_quartile_winner = quartile_details.get("in_top_quartile", False)

        is_winner = is_reward_winner or is_quartile_winner

        result = {
            "is_winner": is_winner,
            "reward_score": reward_score,
            "impressions": impressions,
            "days_matured": days_matured,
            "campaign_objective": row.get("campaign_objective"),
        }

        if is_winner:
            if is_reward_winner:
                result["reason"] = f"Reward score {reward_score:.3f} >= {WINNER_MIN_REWARD_SCORE}"
            else:
                result["reason"] = f"Top quartile: {quartile_details.get('quartile_metric', 'CTR/ROAS')}"
                result["quartile_details"] = quartile_details
        else:
            result["reason"] = (
                f"Reward {reward_score:.3f} < {WINNER_MIN_REWARD_SCORE} "
                f"and not in top quartile"
            )

        return result

    async def identify_winners(self, brand_id: UUID) -> List[Dict[str, Any]]:
        """Find all ads meeting winner criteria for a brand.

        Args:
            brand_id: Brand UUID.

        Returns:
            List of winner dicts with ad info and criteria details.
        """
        # Get all rewarded ads for this brand
        rewards = self.supabase.table("creative_element_rewards").select(
            "generated_ad_id, reward_score, impressions_at_maturity, matured_at"
        ).eq("brand_id", str(brand_id)).gte(
            "impressions_at_maturity", WINNER_MIN_IMPRESSIONS
        ).execute()

        if not rewards.data:
            return []

        winners = []
        for row in rewards.data:
            reward_score = row.get("reward_score") or 0.0
            if reward_score < WINNER_MIN_REWARD_SCORE:
                # Could still be top-quartile winner, but skip for efficiency
                # (identify_winners is for bulk discovery, not precision checks)
                continue

            ad_id = row["generated_ad_id"]

            # Look up element_tags and storage_path
            ad_data = self.supabase.table("generated_ads").select(
                "id, element_tags, storage_path, hook_text, canvas_size, "
                "color_mode, ad_run_id, final_status"
            ).eq("id", ad_id).limit(1).execute()

            if not ad_data.data:
                continue

            ad = ad_data.data[0]
            if ad.get("final_status") != "approved":
                continue

            winners.append({
                "ad_id": ad_id,
                "reward_score": reward_score,
                "impressions": row.get("impressions_at_maturity"),
                "element_tags": ad.get("element_tags"),
                "storage_path": ad.get("storage_path"),
                "hook_text": ad.get("hook_text"),
                "canvas_size": ad.get("canvas_size"),
                "color_mode": ad.get("color_mode"),
            })

        logger.info(f"Found {len(winners)} winners for brand {brand_id}")
        return winners

    async def _check_top_quartile(self, ad_id: UUID) -> Dict[str, Any]:
        """Check if an ad's CTR or ROAS is in the top quartile for its brand.

        Args:
            ad_id: Generated ad UUID.

        Returns:
            Dict with in_top_quartile flag and metric details.
        """
        try:
            # Get the meta_ad_id for this generated ad
            mapping = self.supabase.table("meta_ad_mapping").select(
                "meta_ad_id"
            ).eq("generated_ad_id", str(ad_id)).limit(1).execute()

            if not mapping.data:
                return {"in_top_quartile": False, "reason": "No Meta mapping"}

            meta_ad_id = mapping.data[0]["meta_ad_id"]

            # Get this ad's performance
            perf = self.supabase.table("meta_ads_performance").select(
                "link_ctr, roas, brand_id"
            ).eq("meta_ad_id", meta_ad_id).order(
                "date", desc=True
            ).limit(7).execute()

            if not perf.data:
                return {"in_top_quartile": False, "reason": "No performance data"}

            brand_id = perf.data[0].get("brand_id")
            avg_ctr = _safe_avg([r.get("link_ctr") for r in perf.data])
            avg_roas = _safe_avg([r.get("roas") for r in perf.data])

            # Get brand-level P75 baselines
            from viraltracker.services.creative_genome_service import CreativeGenomeService
            genome = CreativeGenomeService()
            baselines = genome._load_baselines(UUID(brand_id) if brand_id else ad_id)

            p75_ctr = baselines.get("p75_ctr", 0.02)
            p75_roas = baselines.get("p75_roas", 3.0)

            ctr_top = avg_ctr is not None and avg_ctr >= p75_ctr
            roas_top = avg_roas is not None and avg_roas >= p75_roas

            return {
                "in_top_quartile": ctr_top or roas_top,
                "avg_ctr": avg_ctr,
                "avg_roas": avg_roas,
                "p75_ctr": p75_ctr,
                "p75_roas": p75_roas,
                "quartile_metric": "CTR" if ctr_top else ("ROAS" if roas_top else None),
            }
        except Exception as e:
            logger.warning(f"Top quartile check failed for ad {ad_id}: {e}")
            return {"in_top_quartile": False, "reason": str(e)}

    # =========================================================================
    # Iteration Limits
    # =========================================================================

    async def check_iteration_limits(self, ad_id: UUID) -> Dict[str, Any]:
        """Check if evolution limits are reached for this ad.

        Limits:
        - Max 5 single-variable iterations per winner
        - Max 3 rounds on same ancestor

        Args:
            ad_id: Generated ad UUID.

        Returns:
            Dict with can_evolve flag and limit details.
        """
        # Count direct iterations from this ad (it as parent)
        direct = self.supabase.table("ad_lineage").select(
            "id", count="exact"
        ).eq("parent_ad_id", str(ad_id)).execute()
        iteration_count = direct.count if direct.count else 0

        # Find ancestor and count rounds
        ancestor_id = await self.get_ancestor(ad_id)
        ancestor_round = 0
        if ancestor_id and str(ancestor_id) != str(ad_id):
            rounds = self.supabase.table("ad_lineage").select(
                "iteration_round"
            ).eq("ancestor_ad_id", str(ancestor_id)).order(
                "iteration_round", desc=True
            ).limit(1).execute()
            if rounds.data:
                ancestor_round = rounds.data[0].get("iteration_round", 0)

        can_evolve = (
            iteration_count < MAX_ITERATIONS_PER_WINNER
            and ancestor_round < MAX_ROUNDS_ON_ANCESTOR
        )

        reason = None
        if not can_evolve:
            if iteration_count >= MAX_ITERATIONS_PER_WINNER:
                reason = f"Max iterations reached ({iteration_count}/{MAX_ITERATIONS_PER_WINNER})"
            else:
                reason = f"Max ancestor rounds reached ({ancestor_round}/{MAX_ROUNDS_ON_ANCESTOR})"

        return {
            "can_evolve": can_evolve,
            "iteration_count": iteration_count,
            "iteration_limit": MAX_ITERATIONS_PER_WINNER,
            "ancestor_round": ancestor_round,
            "ancestor_round_limit": MAX_ROUNDS_ON_ANCESTOR,
            "ancestor_id": str(ancestor_id) if ancestor_id else None,
            "reason": reason,
        }

    async def get_ancestor(self, ad_id: UUID) -> Optional[UUID]:
        """Find the root ancestor of an ad in the lineage chain.

        Walks up the lineage tree to find the original winner.
        If ad has no lineage, it IS the ancestor (returns itself).

        Args:
            ad_id: Generated ad UUID.

        Returns:
            Ancestor UUID, or ad_id itself if no lineage exists.
        """
        # Check if this ad is a child in any lineage
        child_entry = self.supabase.table("ad_lineage").select(
            "ancestor_ad_id"
        ).eq("child_ad_id", str(ad_id)).limit(1).execute()

        if child_entry.data:
            ancestor_str = child_entry.data[0].get("ancestor_ad_id")
            return UUID(ancestor_str) if ancestor_str else ad_id

        # No lineage — this ad is the root
        return ad_id

    # =========================================================================
    # Evolution Options
    # =========================================================================

    async def get_evolution_options(self, ad_id: UUID) -> Dict[str, Any]:
        """Get available evolution modes for an ad.

        Checks winner criteria, iteration limits, fatigue status,
        and untested sizes to determine which modes are available.

        Args:
            ad_id: Generated ad UUID.

        Returns:
            Dict with is_winner, available_modes, and limit details.
        """
        # Check winner criteria
        winner = await self.check_winner_criteria(ad_id)
        if not winner["is_winner"]:
            return {
                "is_winner": False,
                "winner_details": winner,
                "available_modes": [],
            }

        # Check iteration limits
        limits = await self.check_iteration_limits(ad_id)

        # Get ad data for mode-specific checks
        ad_data = self.supabase.table("generated_ads").select(
            "element_tags, canvas_size, storage_path, ad_run_id"
        ).eq("id", str(ad_id)).limit(1).execute()

        if not ad_data.data:
            return {
                "is_winner": True,
                "winner_details": winner,
                "available_modes": [],
                "error": "Ad data not found",
            }

        ad = ad_data.data[0]
        element_tags = ad.get("element_tags") or {}
        current_size = ad.get("canvas_size") or element_tags.get("canvas_size")

        modes = []

        # Mode a: Winner Iteration
        if limits["can_evolve"]:
            modes.append({
                "mode": "winner_iteration",
                "available": True,
                "reason": "Single-variable testing available",
                "estimated_variants": 1,
            })
        else:
            modes.append({
                "mode": "winner_iteration",
                "available": False,
                "reason": limits["reason"],
                "estimated_variants": 0,
            })

        # Mode c: Anti-Fatigue Refresh
        fatigue_status = await self._check_fatigue_status(ad_id)
        if fatigue_status.get("approaching_fatigue"):
            modes.append({
                "mode": "anti_fatigue_refresh",
                "available": limits["can_evolve"],
                "reason": (
                    fatigue_status.get("fatigue_reason", "Approaching fatigue")
                    if limits["can_evolve"]
                    else limits["reason"]
                ),
                "estimated_variants": 3,
            })
        else:
            modes.append({
                "mode": "anti_fatigue_refresh",
                "available": False,
                "reason": "Ad not approaching fatigue",
                "estimated_variants": 0,
            })

        # Mode d: Cross-Size Expansion
        untested_sizes = await self._get_untested_sizes(ad_id, current_size)
        modes.append({
            "mode": "cross_size_expansion",
            "available": len(untested_sizes) > 0 and limits["can_evolve"],
            "reason": (
                f"{len(untested_sizes)} untested sizes available"
                if untested_sizes and limits["can_evolve"]
                else (limits["reason"] if not limits["can_evolve"] else "All sizes tested")
            ),
            "estimated_variants": len(untested_sizes),
            "untested_sizes": untested_sizes,
        })

        return {
            "is_winner": True,
            "winner_details": winner,
            "available_modes": modes,
            "iteration_count": limits["iteration_count"],
            "iteration_limit": MAX_ITERATIONS_PER_WINNER,
            "ancestor_round": limits["ancestor_round"],
            "ancestor_round_limit": MAX_ROUNDS_ON_ANCESTOR,
        }

    async def _check_fatigue_status(self, ad_id: UUID) -> Dict[str, Any]:
        """Check if an ad is approaching fatigue using FatigueDetector signals.

        Args:
            ad_id: Generated ad UUID.

        Returns:
            Dict with approaching_fatigue flag and details.
        """
        try:
            # Get meta mapping
            mapping = self.supabase.table("meta_ad_mapping").select(
                "meta_ad_id"
            ).eq("generated_ad_id", str(ad_id)).limit(1).execute()

            if not mapping.data:
                return {"approaching_fatigue": False, "reason": "No Meta mapping"}

            meta_ad_id = mapping.data[0]["meta_ad_id"]

            # Get recent performance for frequency + CTR trend
            perf = self.supabase.table("meta_ads_performance").select(
                "frequency, link_ctr, date"
            ).eq("meta_ad_id", meta_ad_id).order(
                "date", desc=True
            ).limit(14).execute()

            if not perf.data:
                return {"approaching_fatigue": False, "reason": "No performance data"}

            # Check latest frequency
            latest_freq = perf.data[0].get("frequency") or 0
            if isinstance(latest_freq, str):
                try:
                    latest_freq = float(latest_freq)
                except (ValueError, TypeError):
                    latest_freq = 0

            # Check CTR trend (WoW)
            ctr_trend = None
            if len(perf.data) >= 7:
                recent_ctrs = [r.get("link_ctr") for r in perf.data[:7] if r.get("link_ctr")]
                older_ctrs = [r.get("link_ctr") for r in perf.data[7:14] if r.get("link_ctr")]
                if recent_ctrs and older_ctrs:
                    recent_avg = sum(recent_ctrs) / len(recent_ctrs)
                    older_avg = sum(older_ctrs) / len(older_ctrs)
                    if older_avg > 0:
                        ctr_trend = (recent_avg - older_avg) / older_avg

            # Approaching fatigue if frequency >= 2.5 OR CTR declining > 10%
            freq_warning = latest_freq >= 2.5
            ctr_declining = ctr_trend is not None and ctr_trend < -0.10

            approaching = freq_warning or ctr_declining
            reasons = []
            if freq_warning:
                reasons.append(f"Frequency {latest_freq:.1f} >= 2.5")
            if ctr_declining:
                reasons.append(f"CTR declining {ctr_trend:+.1%} WoW")

            return {
                "approaching_fatigue": approaching,
                "frequency": latest_freq,
                "ctr_trend": ctr_trend,
                "fatigue_reason": "; ".join(reasons) if reasons else None,
            }
        except Exception as e:
            logger.warning(f"Fatigue check failed for ad {ad_id}: {e}")
            return {"approaching_fatigue": False, "reason": str(e)}

    async def _get_untested_sizes(
        self, ad_id: UUID, current_size: Optional[str]
    ) -> List[str]:
        """Get canvas sizes this ad hasn't been tested in.

        Checks both the ad's own size and any cross-size children in lineage.

        Args:
            ad_id: Generated ad UUID.
            current_size: The ad's current canvas size.

        Returns:
            List of untested canvas size strings.
        """
        tested_sizes = set()
        if current_size:
            tested_sizes.add(current_size)

        # Check lineage for cross-size expansions
        ancestor_id = await self.get_ancestor(ad_id)
        lineage = self.supabase.table("ad_lineage").select(
            "child_ad_id, variable_new_value"
        ).eq(
            "ancestor_ad_id", str(ancestor_id)
        ).eq(
            "evolution_mode", "cross_size_expansion"
        ).execute()

        for entry in (lineage.data or []):
            size_val = entry.get("variable_new_value")
            if size_val:
                tested_sizes.add(size_val)

        return [s for s in ALL_CANVAS_SIZES if s not in tested_sizes]

    # =========================================================================
    # Causal Priors (Phase 7B integration)
    # =========================================================================

    async def get_causal_priors(
        self,
        brand_id: UUID,
        product_id: Optional[UUID] = None,
    ) -> Dict[str, List[Dict]]:
        """Read causal_effects to inform variable selection.

        Returns dict keyed by test_variable, each containing a list of
        {control_value, treatment_value, ate_relative, quality_grade, ci_lower, ci_upper}
        sorted by quality_grade (causal first) then ate_relative (largest first).

        Used by select_evolution_variable() to:
        1. Boost priority weight for variables with causal evidence of large effect
        2. Avoid re-testing variable/value combos that already have causal-grade evidence

        Args:
            brand_id: Brand UUID.
            product_id: Optional product UUID for filtering.

        Returns:
            Dict keyed by test_variable with lists of causal effect summaries.
        """
        query = self.supabase.table("causal_effects").select(
            "test_variable, control_value, treatment_value, "
            "ate_relative, quality_grade, ci_lower, ci_upper"
        ).eq("brand_id", str(brand_id))

        if product_id:
            query = query.eq("product_id", str(product_id))

        result = query.execute()

        priors: Dict[str, List[Dict]] = {}
        for row in (result.data or []):
            var = row["test_variable"]
            if var not in priors:
                priors[var] = []
            priors[var].append({
                "control_value": row["control_value"],
                "treatment_value": row["treatment_value"],
                "ate_relative": row.get("ate_relative"),
                "quality_grade": row.get("quality_grade", "observational"),
                "ci_lower": row.get("ci_lower"),
                "ci_upper": row.get("ci_upper"),
            })

        # Sort each variable's effects: causal first, then by |ATE| desc
        grade_order = {"causal": 0, "quasi": 1, "observational": 2}
        for var in priors:
            priors[var].sort(key=lambda e: (
                grade_order.get(e.get("quality_grade", "observational"), 2),
                -(abs(e.get("ate_relative") or 0)),
            ))

        return priors

    # =========================================================================
    # Variable Selection
    # =========================================================================

    async def select_evolution_variable(
        self,
        brand_id: UUID,
        parent_element_tags: Dict[str, Any],
    ) -> Dict[str, Any]:
        """Select which variable to change using information-gain weighted Thompson Sampling.

        For each iterable element:
        1. Compute uncertainty = variance of Beta(α,β) distribution
        2. Multiply by priority weight
        3. Apply causal boost from experiment results (Phase 7B)
        4. Pick element with highest information gain

        Then for the selected element, use Thompson Sampling to pick a new value
        different from the parent's.

        Args:
            brand_id: Brand UUID.
            parent_element_tags: Parent ad's element_tags dict.

        Returns:
            Dict with variable, new_value, information_gain, and candidates.
        """
        # Load causal priors from completed experiments
        try:
            causal_priors = await self.get_causal_priors(brand_id)
        except Exception:
            causal_priors = {}

        candidates = []

        for elem_name in ITERABLE_ELEMENTS:
            parent_value = parent_element_tags.get(elem_name)
            priority = VARIABLE_PRIORITY_WEIGHTS.get(elem_name, 0.5)

            # Get Beta distributions for this element
            scores = self.supabase.table("creative_element_scores").select(
                "element_value, alpha, beta, total_observations"
            ).eq("brand_id", str(brand_id)).eq(
                "element_name", elem_name
            ).execute()

            if not scores.data or len(scores.data) < 2:
                # Need at least 2 values to change to something different
                continue

            # Compute uncertainty for each value (variance of Beta distribution)
            total_uncertainty = 0.0
            for row in scores.data:
                a = row["alpha"]
                b = row["beta"]
                # Beta variance = αβ / ((α+β)²(α+β+1))
                variance = (a * b) / ((a + b) ** 2 * (a + b + 1))
                total_uncertainty += variance

            avg_uncertainty = total_uncertainty / len(scores.data)
            information_gain = avg_uncertainty * priority

            # Apply causal boost: if experiments show large effect for this variable,
            # boost its priority; if already well-known (causal grade), deprioritize
            elem_priors = causal_priors.get(elem_name, [])
            if elem_priors:
                causal_entries = [e for e in elem_priors if e["quality_grade"] == "causal"]
                if causal_entries:
                    # Already have causal evidence — deprioritize (already known)
                    information_gain *= 0.5
                else:
                    # Have quasi/observational evidence of large effect — boost
                    max_ate = max(abs(e.get("ate_relative") or 0) for e in elem_priors)
                    if max_ate > 0.10:  # > 10% relative effect
                        information_gain *= 1.3

            candidates.append({
                "variable": elem_name,
                "information_gain": information_gain,
                "uncertainty": avg_uncertainty,
                "priority": priority,
                "num_values": len(scores.data),
                "parent_value": str(parent_value) if parent_value else None,
            })

        if not candidates:
            # Fallback: pick a random iterable element
            fallback_elem = np.random.choice(ITERABLE_ELEMENTS)
            return {
                "variable": fallback_elem,
                "new_value": None,  # Caller must handle
                "information_gain": 0.0,
                "fallback": True,
                "all_candidates": [],
            }

        # Sort by information gain (highest first)
        candidates.sort(key=lambda x: x["information_gain"], reverse=True)
        selected = candidates[0]
        selected_elem = selected["variable"]
        parent_value = selected["parent_value"]

        # Use Thompson Sampling to pick a new value (different from parent)
        from viraltracker.services.creative_genome_service import CreativeGenomeService
        genome = CreativeGenomeService()
        sampled = genome.sample_element_scores(brand_id, selected_elem)

        new_value = None
        for s in sampled:
            if s["value"] != parent_value:
                new_value = s["value"]
                break

        return {
            "variable": selected_elem,
            "new_value": new_value,
            "information_gain": selected["information_gain"],
            "uncertainty": selected["uncertainty"],
            "priority": selected["priority"],
            "parent_value": parent_value,
            "all_candidates": candidates,
        }

    # =========================================================================
    # Evolution Execution
    # =========================================================================

    async def evolve_winner(
        self,
        parent_ad_id: UUID,
        mode: str,
        variable_override: Optional[str] = None,
        job_id: Optional[UUID] = None,
    ) -> Dict[str, Any]:
        """Execute winner evolution: validate, build V2 params, run pipeline, record lineage.

        Args:
            parent_ad_id: The winning ad to evolve from.
            mode: Evolution mode (winner_iteration, anti_fatigue_refresh, cross_size_expansion).
            variable_override: Optional override for which variable to change (winner_iteration only).
            job_id: Optional scheduled_job ID for tracking.

        Returns:
            Dict with ad_run_id, child_ad_ids, lineage_entries, mode, variable_changed.

        Raises:
            ValueError: If mode is invalid, ad doesn't meet winner criteria, or limits exceeded.
        """
        if mode not in EVOLUTION_MODES:
            raise ValueError(f"Invalid evolution mode: {mode}. Must be one of {EVOLUTION_MODES}")

        # 1. Validate winner criteria
        winner = await self.check_winner_criteria(parent_ad_id)
        if not winner["is_winner"]:
            raise ValueError(f"Ad {parent_ad_id} does not meet winner criteria: {winner['reason']}")

        # 2. Check iteration limits
        limits = await self.check_iteration_limits(parent_ad_id)
        if not limits["can_evolve"]:
            raise ValueError(f"Evolution limit reached: {limits['reason']}")

        # 3. Load parent ad data
        parent_ad = self.supabase.table("generated_ads").select(
            "id, element_tags, storage_path, hook_text, hook_id, "
            "canvas_size, color_mode, ad_run_id, prompt_version"
        ).eq("id", str(parent_ad_id)).limit(1).execute()

        if not parent_ad.data:
            raise ValueError(f"Parent ad {parent_ad_id} not found")

        parent = parent_ad.data[0]
        element_tags = parent.get("element_tags") or {}

        # Get product_id and brand_id from ad_run
        ad_run = self.supabase.table("ad_runs").select(
            "product_id, brand_id"
        ).eq("id", parent["ad_run_id"]).limit(1).execute()

        if not ad_run.data:
            raise ValueError(f"Ad run {parent['ad_run_id']} not found")

        product_id = ad_run.data[0]["product_id"]
        brand_id = UUID(ad_run.data[0]["brand_id"])

        # 4. Download parent ad image as base64
        from viraltracker.services.ad_creation_service import AdCreationService
        ad_service = AdCreationService()

        storage_path = parent.get("storage_path")
        if not storage_path:
            raise ValueError(f"Parent ad {parent_ad_id} has no storage_path")

        parent_image_bytes = await ad_service.download_image(storage_path)
        parent_image_b64 = base64.b64encode(parent_image_bytes).decode("utf-8")

        # 5. Build V2 pipeline params based on mode
        ancestor_id = await self.get_ancestor(parent_ad_id)
        iteration_round = limits["ancestor_round"] + 1

        if mode == "winner_iteration":
            result = await self._evolve_winner_iteration(
                parent=parent,
                element_tags=element_tags,
                parent_image_b64=parent_image_b64,
                product_id=product_id,
                brand_id=brand_id,
                variable_override=variable_override,
            )
        elif mode == "anti_fatigue_refresh":
            result = await self._evolve_anti_fatigue(
                parent=parent,
                element_tags=element_tags,
                parent_image_b64=parent_image_b64,
                product_id=product_id,
            )
        elif mode == "cross_size_expansion":
            result = await self._evolve_cross_size(
                parent=parent,
                element_tags=element_tags,
                parent_image_b64=parent_image_b64,
                product_id=product_id,
            )
        else:
            raise ValueError(f"Unhandled mode: {mode}")

        # 6. Record lineage
        child_ad_ids = result.get("child_ad_ids", [])
        lineage_count = 0
        if child_ad_ids:
            lineage_count = await self.record_lineage(
                parent_ad_id=parent_ad_id,
                child_ad_ids=[UUID(c) for c in child_ad_ids],
                ancestor_ad_id=ancestor_id,
                mode=mode,
                variable_changed=result.get("variable_changed"),
                old_value=result.get("old_value"),
                new_value=result.get("new_value"),
                iteration_round=iteration_round,
                parent_reward=winner.get("reward_score"),
                job_id=job_id,
            )

        return {
            "ad_run_ids": result.get("ad_run_ids", []),
            "child_ad_ids": child_ad_ids,
            "lineage_entries": lineage_count,
            "mode": mode,
            "variable_changed": result.get("variable_changed"),
            "old_value": result.get("old_value"),
            "new_value": result.get("new_value"),
            "iteration_round": iteration_round,
        }

    async def _evolve_winner_iteration(
        self,
        parent: Dict,
        element_tags: Dict,
        parent_image_b64: str,
        product_id: str,
        brand_id: UUID,
        variable_override: Optional[str] = None,
    ) -> Dict[str, Any]:
        """Execute winner iteration: change ONE element, regenerate.

        Args:
            parent: Parent ad dict from generated_ads.
            element_tags: Parent's element_tags.
            parent_image_b64: Base64-encoded parent image.
            product_id: Product UUID string.
            brand_id: Brand UUID.
            variable_override: Optional override for which variable to change.

        Returns:
            Dict with ad_run_ids, child_ad_ids, variable_changed, old/new values.
        """
        # Select variable to change
        if variable_override and variable_override in ITERABLE_ELEMENTS:
            variable = variable_override
            # Use Thompson Sampling to pick new value
            from viraltracker.services.creative_genome_service import CreativeGenomeService
            genome = CreativeGenomeService()
            sampled = genome.sample_element_scores(brand_id, variable)
            parent_value = str(element_tags.get(variable, ""))
            new_value = None
            for s in sampled:
                if s["value"] != parent_value:
                    new_value = s["value"]
                    break
        else:
            selection = await self.select_evolution_variable(brand_id, element_tags)
            variable = selection["variable"]
            new_value = selection["new_value"]
            parent_value = selection.get("parent_value", "")

        if not new_value:
            raise ValueError(
                f"No alternative value found for variable '{variable}'. "
                f"Need at least 2 tracked values in creative_element_scores."
            )

        # Build V2 pipeline params with the changed variable
        pipeline_params = self._build_base_pipeline_params(parent, element_tags, parent_image_b64, product_id)

        # Apply the single variable change
        if variable == "hook_type":
            # Need to find a hook with the new hook_type
            pipeline_params["content_source"] = "hooks"
            pipeline_params["additional_instructions"] = (
                f"EVOLUTION: Use a hook with persuasion type '{new_value}'. "
                f"Keep all other creative elements identical to the reference."
            )
        elif variable == "color_mode":
            pipeline_params["color_modes"] = [new_value]
        elif variable == "template_category":
            # Pick a different template (service will select based on category)
            pipeline_params["additional_instructions"] = (
                f"EVOLUTION: Use a '{new_value}' template style. "
                f"Keep the same hook, messaging, and overall approach."
            )
        elif variable == "awareness_stage":
            pipeline_params["additional_instructions"] = (
                f"EVOLUTION: Adapt the ad for '{new_value}' awareness stage. "
                f"Keep the same visual style and template structure."
            )

        pipeline_params["num_variations"] = 1

        # Run V2 pipeline
        child_ad_ids, ad_run_ids = await self._run_v2_pipeline(pipeline_params)

        return {
            "ad_run_ids": ad_run_ids,
            "child_ad_ids": child_ad_ids,
            "variable_changed": variable,
            "old_value": parent_value,
            "new_value": new_value,
        }

    async def _evolve_anti_fatigue(
        self,
        parent: Dict,
        element_tags: Dict,
        parent_image_b64: str,
        product_id: str,
    ) -> Dict[str, Any]:
        """Execute anti-fatigue refresh: same psychology, fresh visual.

        Args:
            parent: Parent ad dict from generated_ads.
            element_tags: Parent's element_tags.
            parent_image_b64: Base64-encoded parent image.
            product_id: Product UUID string.

        Returns:
            Dict with ad_run_ids, child_ad_ids, variable_changed.
        """
        pipeline_params = self._build_base_pipeline_params(parent, element_tags, parent_image_b64, product_id)

        # Keep psychology identical, change surface
        parent_color = element_tags.get("color_mode", "original")
        refresh_colors = [c for c in ["original", "complementary", "brand"] if c != parent_color]
        if not refresh_colors:
            refresh_colors = ["complementary"]

        pipeline_params["color_modes"] = refresh_colors[:1]
        pipeline_params["content_source"] = "recreate_template"
        pipeline_params["num_variations"] = 3
        pipeline_params["additional_instructions"] = (
            "ANTI-FATIGUE REFRESH: Maintain the exact same psychological approach, "
            "messaging, and hook type. Only change the visual execution — new layout, "
            "new color palette, slightly reworded headline. "
            "The core belief and persuasion mechanism must stay identical."
        )
        # Don't use the same template — let the pipeline pick a different one
        pipeline_params.pop("template_id", None)

        child_ad_ids, ad_run_ids = await self._run_v2_pipeline(pipeline_params)

        return {
            "ad_run_ids": ad_run_ids,
            "child_ad_ids": child_ad_ids,
            "variable_changed": "visual_execution",
            "old_value": parent_color,
            "new_value": pipeline_params["color_modes"][0],
        }

    async def _evolve_cross_size(
        self,
        parent: Dict,
        element_tags: Dict,
        parent_image_b64: str,
        product_id: str,
    ) -> Dict[str, Any]:
        """Execute cross-size expansion: generate winner in untested sizes.

        Args:
            parent: Parent ad dict from generated_ads.
            element_tags: Parent's element_tags.
            parent_image_b64: Base64-encoded parent image.
            product_id: Product UUID string.

        Returns:
            Dict with ad_run_ids, child_ad_ids, variable_changed.
        """
        current_size = parent.get("canvas_size") or element_tags.get("canvas_size")
        parent_ad_id = UUID(parent["id"])
        untested_sizes = await self._get_untested_sizes(parent_ad_id, current_size)

        if not untested_sizes:
            raise ValueError("All canvas sizes already tested for this ad")

        all_child_ids = []
        all_run_ids = []

        for new_size in untested_sizes:
            pipeline_params = self._build_base_pipeline_params(
                parent, element_tags, parent_image_b64, product_id
            )
            pipeline_params["canvas_sizes"] = [new_size]
            pipeline_params["num_variations"] = 1

            child_ids, run_ids = await self._run_v2_pipeline(pipeline_params)
            all_child_ids.extend(child_ids)
            all_run_ids.extend(run_ids)

        return {
            "ad_run_ids": all_run_ids,
            "child_ad_ids": all_child_ids,
            "variable_changed": "canvas_size",
            "old_value": current_size,
            "new_value": ",".join(untested_sizes),
        }

    def _build_base_pipeline_params(
        self,
        parent: Dict,
        element_tags: Dict,
        parent_image_b64: str,
        product_id: str,
    ) -> Dict[str, Any]:
        """Build base V2 pipeline parameters from parent ad data.

        Args:
            parent: Parent ad dict from generated_ads.
            element_tags: Parent's element_tags.
            parent_image_b64: Base64-encoded parent image.
            product_id: Product UUID string.

        Returns:
            Dict of pipeline parameters for run_ad_creation_v2().
        """
        params = {
            "product_id": product_id,
            "reference_ad_base64": parent_image_b64,
            "template_id": element_tags.get("template_id"),
            "canvas_sizes": [parent.get("canvas_size") or element_tags.get("canvas_size", "1080x1080px")],
            "color_modes": [parent.get("color_mode") or element_tags.get("color_mode", "original")],
            "content_source": element_tags.get("content_source", "hooks"),
            "persona_id": element_tags.get("persona_id"),
            "image_resolution": "2K",
            "auto_retry_rejected": False,
        }

        # Imported ads have no template_id — force recreate_template so the
        # V2 pipeline uses the parent image as the reference.
        if not element_tags.get("template_id") and element_tags.get("extraction_method") == "ai_import":
            params["content_source"] = "recreate_template"

        return params

    async def _run_v2_pipeline(
        self,
        params: Dict[str, Any],
    ) -> Tuple[List[str], List[str]]:
        """Run the V2 ad creation pipeline with given parameters.

        Args:
            params: Pipeline parameters for run_ad_creation_v2().

        Returns:
            Tuple of (child_ad_ids, ad_run_ids).
        """
        from viraltracker.pipelines.ad_creation_v2.orchestrator import run_ad_creation_v2

        try:
            result = await run_ad_creation_v2(**params)

            ad_run_id = result.get("ad_run_id")
            ad_run_ids = [ad_run_id] if ad_run_id else []

            # Extract child ad IDs from generated_ads in result
            child_ids = []
            for ad in result.get("generated_ads", []):
                ad_id = ad.get("ad_id") or ad.get("id")
                if ad_id and ad.get("final_status") in ("approved", "flagged"):
                    child_ids.append(str(ad_id))

            return child_ids, ad_run_ids

        except Exception as e:
            logger.error(f"V2 pipeline failed during evolution: {e}")
            raise

    # =========================================================================
    # Lineage Recording
    # =========================================================================

    async def record_lineage(
        self,
        parent_ad_id: UUID,
        child_ad_ids: List[UUID],
        ancestor_ad_id: UUID,
        mode: str,
        variable_changed: Optional[str],
        old_value: Optional[str],
        new_value: Optional[str],
        iteration_round: int,
        parent_reward: Optional[float],
        job_id: Optional[UUID] = None,
    ) -> int:
        """Record lineage entries for evolved ads.

        Args:
            parent_ad_id: Parent ad UUID.
            child_ad_ids: List of child ad UUIDs.
            ancestor_ad_id: Root ancestor UUID.
            mode: Evolution mode.
            variable_changed: Element that was changed.
            old_value: Parent's value for the changed variable.
            new_value: Child's value for the changed variable.
            iteration_round: Iteration round from ancestor.
            parent_reward: Parent's reward score at time of evolution.
            job_id: Optional scheduled_job ID.

        Returns:
            Number of lineage entries inserted.
        """
        inserted = 0
        for child_id in child_ad_ids:
            try:
                self.supabase.table("ad_lineage").insert({
                    "parent_ad_id": str(parent_ad_id),
                    "child_ad_id": str(child_id),
                    "ancestor_ad_id": str(ancestor_ad_id),
                    "evolution_mode": mode,
                    "variable_changed": variable_changed,
                    "variable_old_value": old_value,
                    "variable_new_value": new_value,
                    "iteration_round": iteration_round,
                    "parent_reward_score": parent_reward,
                    "evolution_job_id": str(job_id) if job_id else None,
                }).execute()
                inserted += 1
            except Exception as e:
                logger.error(
                    f"Failed to record lineage {parent_ad_id} → {child_id}: {e}"
                )

        logger.info(f"Recorded {inserted} lineage entries for mode={mode}")
        return inserted

    # =========================================================================
    # Lineage Queries
    # =========================================================================

    async def get_lineage_tree(self, ad_id: UUID) -> Dict[str, Any]:
        """Get full lineage tree for an ad (ancestors and descendants).

        Args:
            ad_id: Generated ad UUID.

        Returns:
            Dict with ancestor, parent_chain, and descendants.
        """
        ancestor_id = await self.get_ancestor(ad_id)

        # Get all lineage entries for this ancestor
        lineage = self.supabase.table("ad_lineage").select(
            "parent_ad_id, child_ad_id, evolution_mode, variable_changed, "
            "variable_old_value, variable_new_value, iteration_round, "
            "parent_reward_score, child_reward_score, outperformed_parent, "
            "created_at"
        ).eq("ancestor_ad_id", str(ancestor_id)).order("created_at").execute()

        return {
            "ad_id": str(ad_id),
            "ancestor_id": str(ancestor_id),
            "lineage_entries": lineage.data or [],
            "total_descendants": len(lineage.data) if lineage.data else 0,
        }

    # =========================================================================
    # Performance Comparison
    # =========================================================================

    async def update_evolution_outcomes(self, brand_id: UUID) -> Dict[str, Any]:
        """After child ads mature, compare to parent and update outperformed_parent.

        Looks for lineage entries where child_reward_score is null but the child
        ad now has a reward in creative_element_rewards.

        Args:
            brand_id: Brand UUID.

        Returns:
            Dict with updated, outperformed, and underperformed counts.
        """
        # Find lineage entries missing child_reward_score
        pending = self.supabase.table("ad_lineage").select(
            "id, child_ad_id, parent_reward_score"
        ).is_("child_reward_score", "null").execute()

        if not pending.data:
            return {"updated": 0, "outperformed": 0, "underperformed": 0}

        updated = 0
        outperformed = 0
        underperformed = 0

        for entry in pending.data:
            child_id = entry["child_ad_id"]
            parent_reward = entry.get("parent_reward_score") or 0.0

            # Check if child has a reward now
            reward = self.supabase.table("creative_element_rewards").select(
                "reward_score"
            ).eq("generated_ad_id", child_id).eq(
                "brand_id", str(brand_id)
            ).limit(1).execute()

            if not reward.data:
                continue

            child_reward = reward.data[0].get("reward_score", 0.0)
            beat_parent = child_reward > parent_reward

            try:
                self.supabase.table("ad_lineage").update({
                    "child_reward_score": child_reward,
                    "outperformed_parent": beat_parent,
                }).eq("id", entry["id"]).execute()

                updated += 1
                if beat_parent:
                    outperformed += 1
                else:
                    underperformed += 1
            except Exception as e:
                logger.error(f"Failed to update lineage outcome {entry['id']}: {e}")

        logger.info(
            f"Updated {updated} evolution outcomes: "
            f"{outperformed} outperformed, {underperformed} underperformed"
        )
        return {
            "updated": updated,
            "outperformed": outperformed,
            "underperformed": underperformed,
        }


# =============================================================================
# Helpers
# =============================================================================

def _safe_avg(values: List[Optional[float]]) -> Optional[float]:
    """Compute average of non-None values."""
    valid = [v for v in values if v is not None]
    if not valid:
        return None
    return sum(valid) / len(valid)
