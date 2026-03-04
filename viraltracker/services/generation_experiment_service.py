"""
Generation Experiment Service — Pipeline-level A/B testing.

Phase 8B: Supports 2-arm (control/variant) experiments for testing different
prompt versions, pipeline configs, review rubrics, or element strategies.

Uses Mann-Whitney U test (pure Python, no scipy) for statistical significance.
Deterministic arm assignment via SHA-256 hashing.

Tables:
    - generation_experiments: Experiment definitions + aggregate metrics
    - generation_experiment_runs: Per-pipeline-run arm assignments + outcomes
"""

import hashlib
import logging
import math
from datetime import datetime, timezone
from typing import Dict, List, Optional, Tuple, Any
from uuid import UUID

logger = logging.getLogger(__name__)

VALID_EXPERIMENT_TYPES = [
    "prompt_version", "pipeline_config", "review_rubric", "element_strategy"
]
VALID_STATUSES = ["draft", "active", "completed", "cancelled"]
P_VALUE_THRESHOLD = 0.05


class GenerationExperimentService:
    """Pipeline-level A/B testing for ad generation experiments."""

    def __init__(self):
        from viraltracker.core.database import get_supabase_client
        self.supabase = get_supabase_client()

    # =========================================================================
    # CRUD
    # =========================================================================

    def create_experiment(
        self,
        brand_id: UUID,
        name: str,
        experiment_type: str,
        control_config: Dict[str, Any],
        variant_config: Dict[str, Any],
        product_id: Optional[UUID] = None,
        split_ratio: float = 0.50,
        min_sample_size: int = 20,
        hypothesis: Optional[str] = None,
    ) -> Dict[str, Any]:
        """Create a new generation experiment.

        Enforces max 1 active experiment per brand.

        Args:
            brand_id: Brand UUID.
            name: Experiment name.
            experiment_type: One of VALID_EXPERIMENT_TYPES.
            control_config: JSONB config for control arm.
            variant_config: JSONB config for variant arm.
            product_id: Optional product scope.
            split_ratio: Fraction of traffic to variant (0-1).
            min_sample_size: Minimum ads per arm before analysis.
            hypothesis: Optional hypothesis text.

        Returns:
            Created experiment dict.

        Raises:
            ValueError: If validation fails or active experiment exists.
        """
        if experiment_type not in VALID_EXPERIMENT_TYPES:
            raise ValueError(
                f"experiment_type must be one of {VALID_EXPERIMENT_TYPES}"
            )

        if not 0.0 < split_ratio < 1.0:
            raise ValueError("split_ratio must be between 0 and 1 exclusive")

        # Check for existing active experiment
        existing = self.supabase.table("generation_experiments").select(
            "id", count="exact"
        ).eq("brand_id", str(brand_id)).eq("status", "active").execute()

        if existing.count and existing.count > 0:
            raise ValueError(
                f"Brand {brand_id} already has an active experiment. "
                "Complete or cancel it before creating a new one."
            )

        row = {
            "brand_id": str(brand_id),
            "name": name,
            "hypothesis": hypothesis,
            "experiment_type": experiment_type,
            "status": "draft",
            "control_config": control_config,
            "variant_config": variant_config,
            "split_ratio": split_ratio,
            "min_sample_size": min_sample_size,
            "control_metrics": {"ads_generated": 0, "ads_approved": 0, "ads_rejected": 0, "defects": 0, "review_score_sum": 0},
            "variant_metrics": {"ads_generated": 0, "ads_approved": 0, "ads_rejected": 0, "defects": 0, "review_score_sum": 0},
        }

        if product_id:
            row["product_id"] = str(product_id)

        result = self.supabase.table("generation_experiments").insert(row).execute()
        return result.data[0] if result.data else row

    def activate_experiment(self, experiment_id: str) -> Dict[str, Any]:
        """Activate a draft experiment."""
        result = self.supabase.table("generation_experiments").update({
            "status": "active",
            "started_at": datetime.now(timezone.utc).isoformat(),
        }).eq("id", experiment_id).eq("status", "draft").execute()

        if not result.data:
            raise ValueError(f"Experiment {experiment_id} not found or not in draft status")
        return result.data[0]

    def get_experiment(self, experiment_id: str) -> Optional[Dict[str, Any]]:
        """Get experiment by ID."""
        result = self.supabase.table("generation_experiments").select(
            "*"
        ).eq("id", experiment_id).execute()
        return result.data[0] if result.data else None

    def list_experiments(self, brand_id: UUID) -> List[Dict[str, Any]]:
        """List all experiments for a brand."""
        result = self.supabase.table("generation_experiments").select(
            "*"
        ).eq("brand_id", str(brand_id)).order("created_at", desc=True).execute()
        return result.data or []

    # =========================================================================
    # Arm Assignment
    # =========================================================================

    def assign_arm(
        self,
        brand_id: str,
        experiment_seed: str,
    ) -> Optional[Dict[str, Any]]:
        """Deterministic arm assignment for a pipeline run.

        Uses SHA-256 hash of (seed + experiment_id) for stable assignment.

        Args:
            brand_id: Brand ID string.
            experiment_seed: Stable seed from orchestrator (SHA-256 hex).

        Returns:
            Dict with arm, config, experiment_id, or None if no active experiment.
        """
        # Find active experiment for this brand
        result = self.supabase.table("generation_experiments").select(
            "id, split_ratio, control_config, variant_config"
        ).eq("brand_id", brand_id).eq("status", "active").limit(1).execute()

        if not result.data:
            return None

        experiment = result.data[0]
        experiment_id = experiment["id"]
        split_ratio = float(experiment.get("split_ratio", 0.50))

        # Deterministic assignment via SHA-256
        combined = f"{experiment_seed}:{experiment_id}"
        hash_val = int(hashlib.sha256(combined.encode()).hexdigest(), 16) % 100
        arm = "variant" if hash_val < (split_ratio * 100) else "control"
        config = experiment["variant_config"] if arm == "variant" else experiment["control_config"]

        return {
            "arm": arm,
            "config": config,
            "experiment_id": experiment_id,
        }

    # =========================================================================
    # Outcome Recording
    # =========================================================================

    def record_outcome(
        self,
        experiment_id: str,
        arm: str,
        ad_run_id: str,
        metrics: Dict[str, Any],
    ) -> None:
        """Record per-run metrics and update experiment aggregates.

        Args:
            experiment_id: Experiment UUID string.
            arm: 'control' or 'variant'.
            ad_run_id: Pipeline ad_run_id.
            metrics: Dict with ads_generated, ads_approved, ads_rejected, etc.
        """
        if arm not in ("control", "variant"):
            raise ValueError(f"arm must be 'control' or 'variant', got {arm}")

        # Insert run record
        self.supabase.table("generation_experiment_runs").insert({
            "experiment_id": experiment_id,
            "arm": arm,
            "ad_run_id": ad_run_id,
            "ads_generated": metrics.get("ads_generated", 0),
            "ads_approved": metrics.get("ads_approved", 0),
            "ads_rejected": metrics.get("ads_rejected", 0),
            "ads_flagged": metrics.get("ads_flagged", 0),
            "defects_found": metrics.get("defects_found", 0),
            "avg_review_score": metrics.get("avg_review_score"),
        }).execute()

        # Update aggregate metrics on experiment
        experiment = self.get_experiment(experiment_id)
        if not experiment:
            return

        metrics_key = f"{arm}_metrics"
        agg = experiment.get(metrics_key) or {
            "ads_generated": 0, "ads_approved": 0, "ads_rejected": 0,
            "defects": 0, "review_score_sum": 0,
        }

        agg["ads_generated"] = agg.get("ads_generated", 0) + metrics.get("ads_generated", 0)
        agg["ads_approved"] = agg.get("ads_approved", 0) + metrics.get("ads_approved", 0)
        agg["ads_rejected"] = agg.get("ads_rejected", 0) + metrics.get("ads_rejected", 0)
        agg["defects"] = agg.get("defects", 0) + metrics.get("defects_found", 0)
        if metrics.get("avg_review_score") is not None:
            agg["review_score_sum"] = agg.get("review_score_sum", 0) + (
                metrics["avg_review_score"] * metrics.get("ads_generated", 1)
            )

        self.supabase.table("generation_experiments").update({
            metrics_key: agg,
        }).eq("id", experiment_id).execute()

    # =========================================================================
    # Analysis — Mann-Whitney U
    # =========================================================================

    def run_analysis(self, experiment_id: str) -> Dict[str, Any]:
        """Run Mann-Whitney U analysis on experiment results.

        Compares ad-level binary approval outcomes between arms.

        Args:
            experiment_id: Experiment UUID string.

        Returns:
            Analysis dict with u_statistic, p_value, winner, effect_size, etc.
        """
        experiment = self.get_experiment(experiment_id)
        if not experiment:
            raise ValueError(f"Experiment {experiment_id} not found")

        min_sample = experiment.get("min_sample_size", 20)

        # Collect ad-level binary outcomes per arm
        control_outcomes = self._collect_ad_outcomes(experiment_id, "control")
        variant_outcomes = self._collect_ad_outcomes(experiment_id, "variant")

        result = {
            "control_n": len(control_outcomes),
            "variant_n": len(variant_outcomes),
            "control_approval_rate": (
                sum(control_outcomes) / len(control_outcomes) if control_outcomes else 0
            ),
            "variant_approval_rate": (
                sum(variant_outcomes) / len(variant_outcomes) if variant_outcomes else 0
            ),
            "min_sample_size": min_sample,
            "sufficient_data": (
                len(control_outcomes) >= min_sample and len(variant_outcomes) >= min_sample
            ),
        }

        # Need sufficient data for analysis
        if not result["sufficient_data"]:
            result["winner"] = None
            result["p_value"] = None
            result["message"] = (
                f"Insufficient data: control={len(control_outcomes)}, "
                f"variant={len(variant_outcomes)}, need {min_sample} per arm"
            )
            return result

        # Run Mann-Whitney U test
        u_stat, p_value = mann_whitney_u(control_outcomes, variant_outcomes)
        result["u_statistic"] = u_stat
        result["p_value"] = p_value

        # Determine winner
        if p_value < P_VALUE_THRESHOLD:
            if result["variant_approval_rate"] > result["control_approval_rate"]:
                result["winner"] = "variant"
            else:
                result["winner"] = "control"
        else:
            result["winner"] = "inconclusive"

        # Effect size (rank-biserial correlation)
        n_a = len(control_outcomes)
        n_b = len(variant_outcomes)
        if n_a * n_b > 0:
            result["effect_size"] = round(1 - (2 * u_stat) / (n_a * n_b), 4)
        else:
            result["effect_size"] = 0.0

        return result

    def conclude_experiment(self, experiment_id: str) -> Dict[str, Any]:
        """Conclude experiment with analysis results.

        Args:
            experiment_id: Experiment UUID string.

        Returns:
            Updated experiment dict.
        """
        analysis = self.run_analysis(experiment_id)

        update = {
            "status": "completed",
            "completed_at": datetime.now(timezone.utc).isoformat(),
            "winner": analysis.get("winner"),
            "confidence": analysis.get("p_value"),
        }

        result = self.supabase.table("generation_experiments").update(
            update
        ).eq("id", experiment_id).execute()

        return result.data[0] if result.data else update

    # =========================================================================
    # Internal helpers
    # =========================================================================

    def _collect_ad_outcomes(
        self,
        experiment_id: str,
        arm: str,
    ) -> List[float]:
        """Collect ad-level binary outcomes for an arm.

        Returns list of 1.0 (approved) or 0.0 (not approved) per ad.
        """
        # Get all runs for this arm
        runs_result = self.supabase.table("generation_experiment_runs").select(
            "ad_run_id"
        ).eq("experiment_id", experiment_id).eq("arm", arm).execute()

        if not runs_result.data:
            return []

        ad_run_ids = [r["ad_run_id"] for r in runs_result.data]

        # Get all generated ads for these runs
        outcomes = []
        for ad_run_id in ad_run_ids:
            ads_result = self.supabase.table("generated_ads").select(
                "final_status"
            ).eq("ad_run_id", ad_run_id).execute()

            for ad in (ads_result.data or []):
                status = ad.get("final_status", "")
                outcomes.append(1.0 if status == "approved" else 0.0)

        return outcomes


# =============================================================================
# Mann-Whitney U Test — Pure Python, no scipy
# =============================================================================

def mann_whitney_u(
    sample_a: List[float],
    sample_b: List[float],
) -> Tuple[float, float]:
    """Mann-Whitney U test with tie correction.

    Pure Python implementation following PLAN.md:1063 requirement.
    Uses normal approximation for n >= 20 with tie-corrected variance.
    Critical for binary data (approved/not) which produces many ties.

    Args:
        sample_a: First sample (control).
        sample_b: Second sample (variant).

    Returns:
        (u_statistic, p_value) tuple.
    """
    n_a = len(sample_a)
    n_b = len(sample_b)

    if n_a == 0 or n_b == 0:
        return (0.0, 1.0)

    # Combine and assign ranks with average-rank tie handling
    combined = [(v, 'a', i) for i, v in enumerate(sample_a)] + \
               [(v, 'b', i) for i, v in enumerate(sample_b)]
    combined.sort(key=lambda x: x[0])
    N = n_a + n_b

    # Assign ranks with tie handling
    ranks = [0.0] * N
    i = 0
    while i < N:
        j = i
        # Find all tied values
        while j < N and combined[j][0] == combined[i][0]:
            j += 1
        # Average rank for tied group
        avg_rank = (i + j + 1) / 2.0  # 1-indexed average
        for k in range(i, j):
            ranks[k] = avg_rank
        i = j

    # Sum ranks for sample_a
    R_a = sum(ranks[k] for k in range(N) if combined[k][1] == 'a')

    # Compute U statistic
    U_a = n_a * n_b + n_a * (n_a + 1) / 2.0 - R_a
    U_b = n_a * n_b - U_a
    U = min(U_a, U_b)  # Use smaller U for two-tailed test

    # Tie correction for variance
    # Count tied groups
    tie_correction = 0.0
    i = 0
    while i < N:
        j = i
        while j < N and combined[j][0] == combined[i][0]:
            j += 1
        t_k = j - i
        if t_k > 1:
            tie_correction += t_k ** 3 - t_k
        i = j

    # Corrected variance
    mu = n_a * n_b / 2.0
    if N * (N - 1) > 0:
        sigma_sq = (n_a * n_b / 12.0) * (N + 1 - tie_correction / (N * (N - 1)))
    else:
        sigma_sq = (n_a * n_b / 12.0) * (N + 1)

    if sigma_sq <= 0:
        return (U, 1.0)

    sigma = math.sqrt(sigma_sq)

    # Continuity correction
    z = (abs(U - mu) - 0.5) / sigma if sigma > 0 else 0.0

    # Two-tailed p-value from standard normal CDF via erfc
    p_value = math.erfc(abs(z) / math.sqrt(2))

    return (round(U, 4), round(p_value, 6))
