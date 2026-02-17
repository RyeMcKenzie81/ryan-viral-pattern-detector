"""
Experiment Service — Structured A/B testing with Bayesian analysis.

Phase 7B: Experimentation Framework.
- Hypothesis-driven experiments with control/treatment arms
- Power analysis for budget/sample-size gating
- Bayesian analysis (Beta-Binomial for CTR, Normal conjugate for CPA/ROAS)
- Monte Carlo P(best) with configurable decision rules
- Causal knowledge base for evidence-graded effects
- Manual Meta deployment with ID linking and validation

Tables:
    - experiments: Experiment definitions with protocol JSONB
    - experiment_arms: Control and treatment arms
    - experiment_analyses: Daily Bayesian analysis snapshots
    - causal_effects: Knowledge base of measured effects
"""

import logging
import math
from datetime import date, datetime, timezone
from typing import Any, Dict, List, Optional
from uuid import UUID

import numpy as np

logger = logging.getLogger(__name__)


# =============================================================================
# Constants
# =============================================================================

DEFAULT_MIN_IMPRESSIONS_PER_ARM = 1000
DEFAULT_MIN_DAYS_RUNNING = 7
DEFAULT_MAX_DAYS_RUNNING = 14
P_BEST_WINNER_THRESHOLD = 0.90
FUTILITY_MAX_RELATIVE_LIFT = 0.02  # < 2% relative lift after max days = futile
MONTE_CARLO_SAMPLES = 10_000
DEFAULT_BASELINE_CTR = 0.015        # Conservative default for power analysis
DEFAULT_MIN_DETECTABLE_EFFECT = 0.20  # 20% relative lift
DEFAULT_POWER = 0.80

# Method type → base quality grade
METHOD_TYPE_TO_BASE_GRADE = {
    "strict_ab": "causal",
    "pragmatic_split": "quasi",
    "observational": "observational",
}

# Required protocol fields for causal grade
CAUSAL_REQUIRED_PROTOCOL_FIELDS = [
    "method_type", "budget_strategy", "randomization_unit",
    "min_impressions_per_arm", "min_days_running",
]

# Valid status transitions
VALID_TRANSITIONS = {
    "draft": ["ready", "cancelled"],
    "ready": ["deploying", "cancelled"],
    "deploying": ["running", "cancelled"],
    "running": ["analyzing", "cancelled"],
    "analyzing": ["concluded", "cancelled"],
    "concluded": [],
    "cancelled": [],
}

MAX_ARMS = 4


class ExperimentService:
    """Service for structured A/B testing with Bayesian analysis."""

    def __init__(self):
        from viraltracker.core.database import get_supabase_client
        self.supabase = get_supabase_client()

    # =========================================================================
    # Guards
    # =========================================================================

    async def has_meta_account(self, brand_id: UUID) -> bool:
        """Check if brand has a linked Meta ad account.

        Args:
            brand_id: Brand UUID.

        Returns:
            True if brand has at least one linked Meta ad account.
        """
        result = self.supabase.table("brand_ad_accounts").select(
            "id", count="exact"
        ).eq("brand_id", str(brand_id)).limit(1).execute()
        return (result.count or 0) > 0

    async def require_meta_account(self, brand_id: UUID) -> None:
        """Raise ValueError if brand has no Meta ad account.

        Args:
            brand_id: Brand UUID.

        Raises:
            ValueError: If brand has no linked Meta ad account.
        """
        if not await self.has_meta_account(brand_id):
            raise ValueError(
                "Experiments require a Meta ad account. "
                "Link a Meta account in Brand Manager first."
            )

    # =========================================================================
    # CRUD
    # =========================================================================

    async def create_experiment(
        self,
        brand_id: UUID,
        name: str,
        hypothesis: str,
        test_variable: str,
        product_id: Optional[UUID] = None,
        protocol: Optional[Dict[str, Any]] = None,
    ) -> Dict[str, Any]:
        """Create a new experiment in draft status.

        Args:
            brand_id: Brand UUID.
            name: Experiment name.
            hypothesis: Hypothesis text.
            test_variable: Element being tested (e.g., hook_type, color_mode).
            product_id: Optional product UUID.
            protocol: Optional initial protocol config.

        Returns:
            Created experiment record.

        Raises:
            ValueError: If brand has no Meta ad account.
        """
        await self.require_meta_account(brand_id)

        record = {
            "brand_id": str(brand_id),
            "name": name,
            "hypothesis": hypothesis,
            "test_variable": test_variable,
            "status": "draft",
            "protocol": protocol or {},
        }
        if product_id:
            record["product_id"] = str(product_id)

        result = self.supabase.table("experiments").insert(record).execute()
        if not result.data:
            raise ValueError("Failed to create experiment")

        logger.info(f"Created experiment '{name}' for brand {brand_id}")
        return result.data[0]

    async def get_experiment(self, experiment_id: UUID) -> Dict[str, Any]:
        """Get experiment with arms and latest analysis.

        Args:
            experiment_id: Experiment UUID.

        Returns:
            Experiment dict with 'arms' and 'latest_analysis' keys.

        Raises:
            ValueError: If experiment not found.
        """
        result = self.supabase.table("experiments").select("*").eq(
            "id", str(experiment_id)
        ).limit(1).execute()

        if not result.data:
            raise ValueError(f"Experiment {experiment_id} not found")

        experiment = result.data[0]

        # Fetch arms
        arms = self.supabase.table("experiment_arms").select("*").eq(
            "experiment_id", str(experiment_id)
        ).order("arm_order").execute()
        experiment["arms"] = arms.data or []

        # Fetch latest analysis
        analysis = self.supabase.table("experiment_analyses").select("*").eq(
            "experiment_id", str(experiment_id)
        ).order("analysis_date", desc=True).limit(1).execute()
        experiment["latest_analysis"] = analysis.data[0] if analysis.data else None

        return experiment

    async def list_experiments(
        self,
        brand_id: UUID,
        status: Optional[str] = None,
    ) -> List[Dict[str, Any]]:
        """List experiments for a brand.

        Args:
            brand_id: Brand UUID.
            status: Optional status filter.

        Returns:
            List of experiment dicts.
        """
        query = self.supabase.table("experiments").select("*").eq(
            "brand_id", str(brand_id)
        ).order("created_at", desc=True)

        if status:
            query = query.eq("status", status)

        result = query.execute()
        return result.data or []

    async def update_experiment(
        self,
        experiment_id: UUID,
        updates: Dict[str, Any],
    ) -> Dict[str, Any]:
        """Update experiment fields.

        Args:
            experiment_id: Experiment UUID.
            updates: Fields to update.

        Returns:
            Updated experiment record.
        """
        updates["updated_at"] = datetime.now(timezone.utc).isoformat()
        result = self.supabase.table("experiments").update(updates).eq(
            "id", str(experiment_id)
        ).execute()

        if not result.data:
            raise ValueError(f"Experiment {experiment_id} not found")
        return result.data[0]

    async def transition_status(
        self,
        experiment_id: UUID,
        new_status: str,
    ) -> Dict[str, Any]:
        """Transition experiment status with validation gates.

        Gates:
            draft → ready: >= 2 arms with exactly 1 control, Meta account exists,
                           power analysis computed
            deploying → running: All arms have meta_adset_id linked,
                                 all arms reference same meta_ad_account_id,
                                 all arms reference same campaign
            analyzing → concluded: decision is 'winner' or 'inconclusive'
            any → cancelled: always allowed

        Args:
            experiment_id: Experiment UUID.
            new_status: Target status.

        Returns:
            Updated experiment record.

        Raises:
            ValueError: If transition is invalid or gate conditions not met.
        """
        experiment = await self.get_experiment(experiment_id)
        current = experiment["status"]

        # Cancellation is always allowed
        if new_status != "cancelled":
            if new_status not in VALID_TRANSITIONS.get(current, []):
                raise ValueError(
                    f"Cannot transition from '{current}' to '{new_status}'. "
                    f"Valid: {VALID_TRANSITIONS.get(current, [])}"
                )

        arms = experiment.get("arms", [])

        # Gate: draft → ready
        if current == "draft" and new_status == "ready":
            await self.require_meta_account(UUID(experiment["brand_id"]))

            if len(arms) < 2:
                raise ValueError("Need at least 2 arms to mark as ready")
            control_count = sum(1 for a in arms if a.get("is_control"))
            if control_count != 1:
                raise ValueError(f"Exactly 1 control arm required, found {control_count}")

            protocol = experiment.get("protocol") or {}
            if not protocol.get("required_impressions_per_arm"):
                raise ValueError(
                    "Power analysis must be computed before marking as ready. "
                    "Run compute_required_sample_size() first."
                )

        # Gate: deploying → running
        if current == "deploying" and new_status == "running":
            unlinked = [a for a in arms if not a.get("meta_adset_id")]
            if unlinked:
                names = [a["name"] for a in unlinked]
                raise ValueError(f"All arms must have meta_adset_id linked. Missing: {names}")

            account_ids = {a.get("meta_ad_account_id") for a in arms if a.get("meta_ad_account_id")}
            if len(account_ids) > 1:
                raise ValueError(f"All arms must reference same ad account. Found: {account_ids}")

            if not experiment.get("meta_campaign_id"):
                raise ValueError("Experiment must have meta_campaign_id linked")

        # Gate: analyzing → concluded
        if current == "analyzing" and new_status == "concluded":
            latest = experiment.get("latest_analysis")
            if not latest:
                raise ValueError("No analysis exists. Run analysis first.")
            decision = latest.get("decision")
            if decision not in ("winner", "inconclusive", "futility"):
                raise ValueError(
                    f"Cannot conclude with decision '{decision}'. "
                    f"Need 'winner', 'inconclusive', or 'futility'."
                )

        updates = {"status": new_status, "updated_at": datetime.now(timezone.utc).isoformat()}

        if new_status == "running":
            updates["started_at"] = datetime.now(timezone.utc).isoformat()
        elif new_status in ("concluded", "cancelled"):
            updates["concluded_at"] = datetime.now(timezone.utc).isoformat()

        result = self.supabase.table("experiments").update(updates).eq(
            "id", str(experiment_id)
        ).execute()

        if not result.data:
            raise ValueError(f"Failed to update experiment {experiment_id}")

        logger.info(f"Experiment {experiment_id}: {current} → {new_status}")
        return result.data[0]

    # =========================================================================
    # Arms
    # =========================================================================

    async def add_arm(
        self,
        experiment_id: UUID,
        name: str,
        variable_value: str,
        is_control: bool = False,
        generated_ad_id: Optional[UUID] = None,
        hold_constant_tags: Optional[Dict[str, Any]] = None,
        notes: Optional[str] = None,
    ) -> Dict[str, Any]:
        """Add an arm to a draft experiment.

        Args:
            experiment_id: Experiment UUID.
            name: Arm name (e.g., 'Control', 'Treatment A').
            variable_value: Value of the test variable for this arm.
            is_control: Whether this is the control arm.
            generated_ad_id: Optional linked generated ad.
            hold_constant_tags: Optional snapshot of held-constant elements.
            notes: Optional notes.

        Returns:
            Created arm record.

        Raises:
            ValueError: If experiment not in draft, max arms reached, or duplicate control.
        """
        experiment = await self.get_experiment(experiment_id)
        if experiment["status"] != "draft":
            raise ValueError("Can only add arms to draft experiments")

        arms = experiment.get("arms", [])
        if len(arms) >= MAX_ARMS:
            raise ValueError(f"Maximum {MAX_ARMS} arms per experiment")

        if is_control:
            existing_control = [a for a in arms if a.get("is_control")]
            if existing_control:
                raise ValueError("Experiment already has a control arm")

        arm_order = max((a.get("arm_order", 0) for a in arms), default=-1) + 1

        record = {
            "experiment_id": str(experiment_id),
            "name": name,
            "variable_value": variable_value,
            "is_control": is_control,
            "arm_order": arm_order,
        }
        if generated_ad_id:
            record["generated_ad_id"] = str(generated_ad_id)
        if hold_constant_tags:
            record["hold_constant_tags"] = hold_constant_tags
        if notes:
            record["notes"] = notes

        result = self.supabase.table("experiment_arms").insert(record).execute()
        if not result.data:
            raise ValueError("Failed to create arm")

        logger.info(f"Added arm '{name}' to experiment {experiment_id}")
        return result.data[0]

    async def remove_arm(self, arm_id: UUID) -> None:
        """Remove an arm from a draft experiment.

        Args:
            arm_id: Arm UUID.

        Raises:
            ValueError: If arm not found or experiment not in draft.
        """
        arm = self.supabase.table("experiment_arms").select(
            "id, experiment_id"
        ).eq("id", str(arm_id)).limit(1).execute()

        if not arm.data:
            raise ValueError(f"Arm {arm_id} not found")

        experiment = await self.get_experiment(UUID(arm.data[0]["experiment_id"]))
        if experiment["status"] != "draft":
            raise ValueError("Can only remove arms from draft experiments")

        self.supabase.table("experiment_arms").delete().eq("id", str(arm_id)).execute()
        logger.info(f"Removed arm {arm_id}")

    async def link_arm_to_meta(
        self,
        arm_id: UUID,
        meta_adset_id: str,
        meta_adset_name: Optional[str] = None,
        meta_ad_id: Optional[str] = None,
    ) -> Dict[str, Any]:
        """Link an arm to a Meta ad set ID after manual deployment.

        Validates:
        1. meta_adset_id is not already linked to another arm in this experiment
        2. meta_adset_id exists in meta_adsets table for the brand's ad account
        3. If experiment has meta_campaign_id, the adset belongs to that campaign
        4. Stores meta_ad_account_id on the arm (from meta_adsets lookup)

        Args:
            arm_id: Arm UUID.
            meta_adset_id: Meta ad set ID.
            meta_adset_name: Optional display name.
            meta_ad_id: Optional Meta ad ID.

        Returns:
            Updated arm record.

        Raises:
            ValueError: If validation fails.
        """
        # Load arm + experiment
        arm = self.supabase.table("experiment_arms").select("*").eq(
            "id", str(arm_id)
        ).limit(1).execute()
        if not arm.data:
            raise ValueError(f"Arm {arm_id} not found")
        arm_data = arm.data[0]
        experiment_id = arm_data["experiment_id"]

        experiment = await self.get_experiment(UUID(experiment_id))

        # 1. Check for duplicate adset_id across arms in this experiment
        existing = self.supabase.table("experiment_arms").select("id, name").eq(
            "experiment_id", experiment_id
        ).eq("meta_adset_id", meta_adset_id).neq(
            "id", str(arm_id)
        ).execute()
        if existing.data:
            raise ValueError(
                f"Ad set '{meta_adset_id}' is already linked to arm "
                f"'{existing.data[0]['name']}' in this experiment"
            )

        # 2. Validate adset exists in meta_adsets for brand's ad account
        brand_id = experiment["brand_id"]
        accounts = self.supabase.table("brand_ad_accounts").select(
            "meta_ad_account_id"
        ).eq("brand_id", brand_id).execute()
        account_ids = [a["meta_ad_account_id"] for a in (accounts.data or [])]

        if not account_ids:
            raise ValueError("Brand has no linked Meta ad accounts")

        adset_lookup = self.supabase.table("meta_adsets").select(
            "meta_ad_account_id, meta_campaign_id, name"
        ).eq("meta_adset_id", meta_adset_id).execute()

        if not adset_lookup.data:
            raise ValueError(
                f"Ad set '{meta_adset_id}' not found in synced Meta data. "
                f"Run a Meta sync first."
            )

        adset_row = adset_lookup.data[0]
        adset_account = adset_row["meta_ad_account_id"]

        if adset_account not in account_ids:
            raise ValueError(
                f"Ad set '{meta_adset_id}' belongs to account '{adset_account}' "
                f"which is not linked to this brand"
            )

        # 3. Campaign validation
        if experiment.get("meta_campaign_id"):
            if adset_row["meta_campaign_id"] != experiment["meta_campaign_id"]:
                raise ValueError(
                    f"Ad set '{meta_adset_id}' belongs to campaign "
                    f"'{adset_row['meta_campaign_id']}', but experiment is linked to "
                    f"campaign '{experiment['meta_campaign_id']}'"
                )

        # 4. Update arm
        update_data = {
            "meta_adset_id": meta_adset_id,
            "meta_ad_account_id": adset_account,
        }
        if meta_adset_name:
            update_data["meta_adset_name"] = meta_adset_name
        elif adset_row.get("name"):
            update_data["meta_adset_name"] = adset_row["name"]
        if meta_ad_id:
            update_data["meta_ad_id"] = meta_ad_id

        result = self.supabase.table("experiment_arms").update(update_data).eq(
            "id", str(arm_id)
        ).execute()

        logger.info(f"Linked arm {arm_id} to adset {meta_adset_id}")
        return result.data[0] if result.data else update_data

    async def link_campaign_to_experiment(
        self,
        experiment_id: UUID,
        meta_campaign_id: str,
        meta_campaign_name: Optional[str] = None,
    ) -> Dict[str, Any]:
        """Link a Meta campaign ID to the experiment.

        Args:
            experiment_id: Experiment UUID.
            meta_campaign_id: Meta campaign ID.
            meta_campaign_name: Optional display name.

        Returns:
            Updated experiment record.
        """
        updates = {
            "meta_campaign_id": meta_campaign_id,
            "updated_at": datetime.now(timezone.utc).isoformat(),
        }
        if meta_campaign_name:
            updates["meta_campaign_name"] = meta_campaign_name

        result = self.supabase.table("experiments").update(updates).eq(
            "id", str(experiment_id)
        ).execute()

        if not result.data:
            raise ValueError(f"Experiment {experiment_id} not found")

        logger.info(f"Linked campaign {meta_campaign_id} to experiment {experiment_id}")
        return result.data[0]

    # =========================================================================
    # Power Analysis
    # =========================================================================

    async def compute_required_sample_size(
        self,
        experiment_id: UUID,
        baseline_rate: Optional[float] = None,
        min_detectable_effect: float = DEFAULT_MIN_DETECTABLE_EFFECT,
        power: float = DEFAULT_POWER,
        num_arms: Optional[int] = None,
    ) -> Dict[str, Any]:
        """Compute required sample size and budget per arm.

        Uses normal approximation to binomial for CTR:
          n = (Z_alpha/2 + Z_beta)^2 * (p1*(1-p1) + p2*(1-p2)) / (p1-p2)^2
        With Bonferroni correction for multiple arms.

        If brand has historical CPM data, estimates daily budget:
          daily_budget_per_arm = (n / estimated_days) * (CPM / 1000)

        Stores result in experiment.protocol JSONB.

        Args:
            experiment_id: Experiment UUID.
            baseline_rate: Baseline CTR. Uses brand P50 if None.
            min_detectable_effect: Minimum detectable relative lift (default 0.20 = 20%).
            power: Statistical power (default 0.80).
            num_arms: Number of arms (auto-detected if None).

        Returns:
            Dict with required_impressions_per_arm, estimated_budget, estimated_days.
        """
        experiment = await self.get_experiment(experiment_id)

        # Auto-detect number of arms
        if num_arms is None:
            num_arms = len(experiment.get("arms", []))
        if num_arms < 2:
            raise ValueError("Need at least 2 arms for power analysis")

        # Get baseline CTR from brand data if not provided
        if baseline_rate is None:
            baseline_rate = await self._get_brand_baseline_ctr(UUID(experiment["brand_id"]))

        # Normal approximation
        p1 = baseline_rate
        p2 = baseline_rate * (1 + min_detectable_effect)

        # Bonferroni correction for multiple comparisons (num_arms - 1 comparisons)
        alpha = 0.05 / max(num_arms - 1, 1)

        z_alpha = _z_score(1 - alpha / 2)
        z_beta = _z_score(power)

        numerator = (z_alpha + z_beta) ** 2 * (p1 * (1 - p1) + p2 * (1 - p2))
        denominator = (p2 - p1) ** 2

        if denominator == 0:
            raise ValueError("Baseline rate and detectable effect result in zero effect size")

        n_per_arm = math.ceil(numerator / denominator)
        n_per_arm = max(n_per_arm, DEFAULT_MIN_IMPRESSIONS_PER_ARM)

        # Estimate days and budget
        protocol = experiment.get("protocol") or {}
        min_days = protocol.get("min_days_running", DEFAULT_MIN_DAYS_RUNNING)
        max_days = protocol.get("max_days_running", DEFAULT_MAX_DAYS_RUNNING)
        estimated_days = max(min_days, min(max_days, math.ceil(n_per_arm / 500)))

        # Try to get CPM from brand's recent data
        daily_budget = await self._estimate_daily_budget(
            UUID(experiment["brand_id"]), n_per_arm, estimated_days
        )

        # Store in protocol
        power_data = {
            "required_impressions_per_arm": n_per_arm,
            "required_daily_budget_per_arm": daily_budget,
            "estimated_days": estimated_days,
            "detectable_effect_size": min_detectable_effect,
            "power_analysis_params": {
                "baseline_rate": baseline_rate,
                "power": power,
                "alpha": alpha,
                "num_arms": num_arms,
                "n_formula": "normal_approximation_bonferroni",
            },
        }
        protocol.update(power_data)

        await self.update_experiment(experiment_id, {"protocol": protocol})

        logger.info(
            f"Power analysis for experiment {experiment_id}: "
            f"{n_per_arm} impressions/arm, ~${daily_budget}/arm/day, "
            f"~{estimated_days} days"
        )

        return {
            "required_impressions_per_arm": n_per_arm,
            "required_daily_budget_per_arm": daily_budget,
            "estimated_days": estimated_days,
            "baseline_ctr": baseline_rate,
            "detectable_effect": min_detectable_effect,
            "num_arms": num_arms,
        }

    async def _get_brand_baseline_ctr(self, brand_id: UUID) -> float:
        """Get brand's median CTR from recent performance data.

        Falls back to DEFAULT_BASELINE_CTR if no data.
        """
        result = self.supabase.table("meta_ads_performance").select(
            "link_ctr"
        ).eq("brand_id", str(brand_id)).not_.is_("link_ctr", "null").gt(
            "link_ctr", "0"
        ).order("date", desc=True).limit(100).execute()

        if not result.data or len(result.data) < 5:
            return DEFAULT_BASELINE_CTR

        ctrs = [float(r["link_ctr"]) for r in result.data]
        return float(np.median(ctrs))

    async def _estimate_daily_budget(
        self,
        brand_id: UUID,
        n_per_arm: int,
        estimated_days: int,
    ) -> Optional[float]:
        """Estimate daily budget per arm using brand's historical CPM."""
        result = self.supabase.table("meta_ads_performance").select(
            "spend, impressions"
        ).eq("brand_id", str(brand_id)).not_.is_("impressions", "null").gt(
            "impressions", "0"
        ).order("date", desc=True).limit(30).execute()

        if not result.data or len(result.data) < 3:
            return None

        # Calculate CPM from recent data
        total_spend = sum(float(r.get("spend", 0) or 0) for r in result.data)
        total_impr = sum(int(r.get("impressions", 0) or 0) for r in result.data)

        if total_impr == 0:
            return None

        cpm = (total_spend / total_impr) * 1000
        daily_impressions = n_per_arm / max(estimated_days, 1)
        daily_budget = round((daily_impressions / 1000) * cpm, 2)

        return daily_budget

    # =========================================================================
    # Deployment Checklist
    # =========================================================================

    async def get_deployment_checklist(
        self,
        experiment_id: UUID,
    ) -> Dict[str, Any]:
        """Generate Meta deployment instructions for an experiment.

        Returns structured checklist with budget from power analysis,
        arm descriptions, and step-by-step instructions.

        Args:
            experiment_id: Experiment UUID.

        Returns:
            Dict with checklist items, budget info, and arm details.
        """
        experiment = await self.get_experiment(experiment_id)
        arms = experiment.get("arms", [])
        protocol = experiment.get("protocol") or {}

        budget_per_arm = protocol.get("required_daily_budget_per_arm")
        impressions_per_arm = protocol.get("required_impressions_per_arm", DEFAULT_MIN_IMPRESSIONS_PER_ARM)
        estimated_days = protocol.get("estimated_days", DEFAULT_MIN_DAYS_RUNNING)
        method_type = protocol.get("method_type", "pragmatic_split")
        audience_rules = protocol.get("audience_rules", "Same audience for all ad sets")
        hold_constant = protocol.get("hold_constant", [])

        arm_instructions = []
        for arm in arms:
            arm_info = {
                "name": arm["name"],
                "variable_value": arm["variable_value"],
                "is_control": arm["is_control"],
            }
            if arm.get("generated_ad_id"):
                arm_info["generated_ad_id"] = arm["generated_ad_id"]
            arm_instructions.append(arm_info)

        total_daily_budget = None
        if budget_per_arm:
            total_daily_budget = round(budget_per_arm * len(arms), 2)

        steps = [
            {
                "step": 1,
                "title": "Create Campaign",
                "description": (
                    f"Create a new campaign in Meta Ads Manager. "
                    f"Use '{experiment['name']}' as campaign name. "
                    f"Method: {method_type}."
                ),
            },
            {
                "step": 2,
                "title": "Create Ad Sets",
                "description": (
                    f"Create {len(arms)} ad sets — one per arm. "
                    f"Each ad set should target the same audience. "
                    f"Audience rules: {audience_rules}."
                ),
                "arms": arm_instructions,
            },
            {
                "step": 3,
                "title": "Set Budgets",
                "description": (
                    f"Set each ad set to "
                    f"{'$' + str(budget_per_arm) + '/day' if budget_per_arm else 'equal daily budget'}. "
                    f"Total daily budget: "
                    f"{'$' + str(total_daily_budget) if total_daily_budget else 'TBD'}. "
                    f"Run for ~{estimated_days} days to reach "
                    f"{impressions_per_arm:,} impressions per arm."
                ),
            },
            {
                "step": 4,
                "title": "Upload Creatives",
                "description": (
                    "Upload the ad creative for each arm's ad set. "
                    "Only the test variable should differ between arms. "
                    f"Hold constant: {', '.join(hold_constant) if hold_constant else 'all other elements'}."
                ),
            },
            {
                "step": 5,
                "title": "Launch & Link IDs",
                "description": (
                    "Publish the campaign, then return here to link the "
                    "campaign ID and each arm's ad set ID."
                ),
            },
        ]

        return {
            "experiment_name": experiment["name"],
            "hypothesis": experiment["hypothesis"],
            "test_variable": experiment["test_variable"],
            "method_type": method_type,
            "steps": steps,
            "budget": {
                "per_arm_daily": budget_per_arm,
                "total_daily": total_daily_budget,
                "estimated_days": estimated_days,
                "target_impressions_per_arm": impressions_per_arm,
            },
            "arms": arm_instructions,
        }

    # =========================================================================
    # Bayesian Analysis
    # =========================================================================

    async def run_analysis(
        self,
        experiment_id: UUID,
        analysis_date: Optional[date] = None,
    ) -> Dict[str, Any]:
        """Run daily Bayesian analysis for an experiment.

        Idempotent: upserts on (experiment_id, analysis_date).

        Args:
            experiment_id: Experiment UUID.
            analysis_date: Date to analyze (defaults to today).

        Returns:
            Analysis result dict.
        """
        if analysis_date is None:
            analysis_date = date.today()

        experiment = await self.get_experiment(experiment_id)

        if experiment["status"] not in ("running", "analyzing"):
            raise ValueError(
                f"Cannot analyze experiment in '{experiment['status']}' status. "
                f"Must be 'running' or 'analyzing'."
            )

        arms = experiment.get("arms", [])
        protocol = experiment.get("protocol") or {}
        min_impressions = protocol.get("min_impressions_per_arm", DEFAULT_MIN_IMPRESSIONS_PER_ARM)
        min_days = protocol.get("min_days_running", DEFAULT_MIN_DAYS_RUNNING)
        max_days = protocol.get("max_days_running", DEFAULT_MAX_DAYS_RUNNING)

        # Calculate days running
        started = experiment.get("started_at")
        if started:
            start_date = datetime.fromisoformat(started.replace("Z", "+00:00")).date()
            days_running = (analysis_date - start_date).days
        else:
            days_running = 0

        # Fetch performance data for each arm
        arm_results = []
        for arm in arms:
            perf = await self._fetch_arm_performance(arm)
            arm_results.append({
                "arm_id": arm["id"],
                "arm_name": arm["name"],
                "is_control": arm["is_control"],
                "variable_value": arm["variable_value"],
                **perf,
            })

        # Check if all arms meet minimum impressions
        all_met_min = all(
            ar.get("impressions", 0) >= min_impressions for ar in arm_results
        )

        # Compute posteriors and P(best)
        primary_metric = "ctr"
        posteriors = self._compute_posteriors_ctr(arm_results)

        for i, ar in enumerate(arm_results):
            ar["posterior_alpha"] = posteriors[i]["alpha"]
            ar["posterior_beta"] = posteriors[i]["beta"]

        p_best_values = self._monte_carlo_p_best(posteriors, metric_type="ctr")
        for i, ar in enumerate(arm_results):
            ar["p_best"] = p_best_values[i]

        # Determine winner
        best_idx = int(np.argmax(p_best_values))
        winner_arm_id = arm_results[best_idx]["arm_id"]
        winner_p_best = float(p_best_values[best_idx])

        # Decision
        decision = self._determine_decision(
            arm_results=arm_results,
            p_best_values=p_best_values,
            all_met_min=all_met_min,
            days_running=days_running,
            min_days=min_days,
            max_days=max_days,
        )

        # Quality grading
        quality_grade, quality_notes = self._grade_quality(experiment)

        # Upsert analysis
        analysis_record = {
            "experiment_id": str(experiment_id),
            "product_id": experiment.get("product_id"),
            "analysis_date": analysis_date.isoformat(),
            "arm_results": arm_results,
            "primary_metric": primary_metric,
            "winner_arm_id": winner_arm_id if decision in ("winner", "leading") else None,
            "winner_p_best": winner_p_best,
            "decision": decision,
            "quality_grade": quality_grade,
            "quality_notes": quality_notes,
            "all_arms_met_min_impressions": all_met_min,
            "days_running": days_running,
            "monte_carlo_samples": MONTE_CARLO_SAMPLES,
            "computed_at": datetime.now(timezone.utc).isoformat(),
        }

        self.supabase.table("experiment_analyses").upsert(
            analysis_record,
            on_conflict="experiment_id,analysis_date",
        ).execute()

        # Auto-transition running → analyzing when decision is actionable
        if experiment["status"] == "running" and decision in ("winner", "futility", "inconclusive"):
            try:
                await self.transition_status(experiment_id, "analyzing")
            except ValueError as e:
                logger.debug(f"Auto-transition to analyzing skipped: {e}")

        logger.info(
            f"Analysis for experiment {experiment_id} on {analysis_date}: "
            f"decision={decision}, winner_p_best={winner_p_best:.3f}"
        )

        return analysis_record

    async def _fetch_arm_performance(self, arm: Dict[str, Any]) -> Dict[str, Any]:
        """Fetch aggregated performance for an arm from meta_ads_performance.

        Queries by meta_adset_id if available, returns zeros if not linked.

        Args:
            arm: Arm dict with meta_adset_id.

        Returns:
            Dict with impressions, clicks, ctr, spend, cpa, roas.
        """
        meta_adset_id = arm.get("meta_adset_id")
        if not meta_adset_id:
            return {
                "impressions": 0, "clicks": 0, "ctr": 0.0,
                "spend": 0.0, "purchases": 0, "cpa": None, "roas": None,
            }

        # Performance is keyed by meta_ad_id, not meta_adset_id.
        # If meta_ad_id is set on the arm, query directly; otherwise
        # look up ad IDs for this adset from meta_ads table.
        if arm.get("meta_ad_id"):
            result = self.supabase.table("meta_ads_performance").select(
                "impressions, link_clicks, spend, purchases, purchase_value, roas"
            ).eq("meta_ad_id", arm["meta_ad_id"]).execute()
        else:
            ads_in_adset = self.supabase.table("meta_ads").select(
                "meta_ad_id"
            ).eq("meta_adset_id", meta_adset_id).execute()

            if not ads_in_adset.data:
                return {
                    "impressions": 0, "clicks": 0, "ctr": 0.0,
                    "spend": 0.0, "purchases": 0, "cpa": None, "roas": None,
                }

            ad_ids = [a["meta_ad_id"] for a in ads_in_adset.data]
            result = self.supabase.table("meta_ads_performance").select(
                "impressions, link_clicks, spend, purchases, purchase_value, roas"
            ).in_("meta_ad_id", ad_ids).execute()

        if not result.data:
            return {
                "impressions": 0, "clicks": 0, "ctr": 0.0,
                "spend": 0.0, "purchases": 0, "cpa": None, "roas": None,
            }

        # Aggregate across dates
        total_impressions = sum(int(r.get("impressions", 0) or 0) for r in result.data)
        total_clicks = sum(int(r.get("link_clicks", 0) or 0) for r in result.data)
        total_spend = sum(float(r.get("spend", 0) or 0) for r in result.data)
        total_purchases = sum(int(r.get("purchases", 0) or 0) for r in result.data)
        total_purchase_value = sum(float(r.get("purchase_value", 0) or 0) for r in result.data)

        ctr = total_clicks / total_impressions if total_impressions > 0 else 0.0
        cpa = total_spend / total_purchases if total_purchases > 0 else None
        roas = total_purchase_value / total_spend if total_spend > 0 else None

        return {
            "impressions": total_impressions,
            "clicks": total_clicks,
            "ctr": round(ctr, 6),
            "spend": round(total_spend, 2),
            "purchases": total_purchases,
            "cpa": round(cpa, 2) if cpa else None,
            "roas": round(roas, 4) if roas else None,
        }

    def _compute_posteriors_ctr(
        self,
        arm_results: List[Dict[str, Any]],
    ) -> List[Dict[str, float]]:
        """Compute Beta-Binomial posteriors for CTR.

        Prior: Beta(1, 1) (uninformative).
        Posterior: Beta(1 + clicks, 1 + impressions - clicks).

        Args:
            arm_results: List of arm result dicts with impressions and clicks.

        Returns:
            List of dicts with alpha and beta posterior params.
        """
        posteriors = []
        for ar in arm_results:
            clicks = ar.get("clicks", 0)
            impressions = ar.get("impressions", 0)
            alpha = 1 + clicks
            beta = 1 + max(impressions - clicks, 0)
            posteriors.append({"alpha": alpha, "beta": beta})
        return posteriors

    def _compute_posteriors_continuous(
        self,
        arm_results: List[Dict[str, Any]],
        metric_key: str,
    ) -> List[Dict[str, float]]:
        """Compute Normal conjugate posteriors for continuous metrics (CPA, ROAS).

        Prior: N(grand_mean, 100*var). Posterior via precision weighting.

        Args:
            arm_results: List of arm result dicts.
            metric_key: Key to extract ('cpa' or 'roas').

        Returns:
            List of dicts with mean and variance posterior params.
        """
        # Collect all non-None values for grand mean
        all_values = [float(ar[metric_key]) for ar in arm_results if ar.get(metric_key) is not None]
        if not all_values:
            return [{"mean": 0.0, "variance": 1.0} for _ in arm_results]

        grand_mean = np.mean(all_values)
        grand_var = max(np.var(all_values), 0.0001)
        prior_var = 100 * grand_var

        posteriors = []
        for ar in arm_results:
            val = ar.get(metric_key)
            n = ar.get("impressions", 0)

            if val is None or n == 0:
                posteriors.append({"mean": float(grand_mean), "variance": float(prior_var)})
                continue

            # Precision weighting
            prior_precision = 1.0 / prior_var
            likelihood_precision = n / grand_var
            posterior_precision = prior_precision + likelihood_precision
            posterior_mean = (prior_precision * grand_mean + likelihood_precision * float(val)) / posterior_precision
            posterior_var = 1.0 / posterior_precision

            posteriors.append({"mean": float(posterior_mean), "variance": float(posterior_var)})

        return posteriors

    def _monte_carlo_p_best(
        self,
        posteriors: List[Dict[str, float]],
        metric_type: str = "ctr",
        n_samples: int = MONTE_CARLO_SAMPLES,
    ) -> List[float]:
        """Compute P(best) per arm via Monte Carlo sampling.

        For CTR/ROAS: argmax wins (higher is better).
        For CPA: argmin wins (lower is better).

        Args:
            posteriors: List of posterior parameter dicts.
            metric_type: 'ctr', 'roas', or 'cpa'.
            n_samples: Number of MC samples.

        Returns:
            List of P(best) values, one per arm.
        """
        n_arms = len(posteriors)
        if n_arms == 0:
            return []

        rng = np.random.default_rng()
        samples = np.zeros((n_samples, n_arms))

        for i, post in enumerate(posteriors):
            if "alpha" in post and "beta" in post:
                # Beta distribution for CTR
                samples[:, i] = rng.beta(post["alpha"], post["beta"], size=n_samples)
            else:
                # Normal distribution for CPA/ROAS
                std = max(np.sqrt(post.get("variance", 1.0)), 1e-10)
                samples[:, i] = rng.normal(post["mean"], std, size=n_samples)

        if metric_type == "cpa":
            # Lower is better
            winners = np.argmin(samples, axis=1)
        else:
            # Higher is better (CTR, ROAS)
            winners = np.argmax(samples, axis=1)

        p_best = []
        for i in range(n_arms):
            p_best.append(float(np.mean(winners == i)))

        return p_best

    def _determine_decision(
        self,
        arm_results: List[Dict[str, Any]],
        p_best_values: List[float],
        all_met_min: bool,
        days_running: int,
        min_days: int,
        max_days: int,
    ) -> str:
        """Determine experiment decision based on rules.

        Applied in order:
        1. collecting: any arm below min_impressions
        2. winner: best arm P(best) >= 0.90 AND min_days met
        3. futility: max_days reached AND best-vs-second relative lift < 2%
        4. inconclusive: max_days reached without winner or futility
        5. leading: none of the above

        Args:
            arm_results: List of arm result dicts.
            p_best_values: P(best) per arm.
            all_met_min: Whether all arms met min impressions.
            days_running: Days since experiment started.
            min_days: Minimum days required.
            max_days: Maximum days allowed.

        Returns:
            Decision string.
        """
        # 1. Collecting
        if not all_met_min:
            return "collecting"

        best_idx = int(np.argmax(p_best_values))
        best_p = p_best_values[best_idx]

        # 2. Winner
        if best_p >= P_BEST_WINNER_THRESHOLD and days_running >= min_days:
            return "winner"

        # 3. Futility (max days reached + no practical difference)
        if days_running >= max_days:
            # Check relative lift between best and second-best CTR
            ctrs = [ar.get("ctr", 0.0) for ar in arm_results]
            sorted_ctrs = sorted(ctrs, reverse=True)
            if len(sorted_ctrs) >= 2 and sorted_ctrs[1] > 0:
                relative_lift = (sorted_ctrs[0] - sorted_ctrs[1]) / sorted_ctrs[1]
                if relative_lift < FUTILITY_MAX_RELATIVE_LIFT:
                    return "futility"

            # 4. Inconclusive (max days, no winner, not futile)
            return "inconclusive"

        # 5. Leading
        return "leading"

    def _grade_quality(
        self,
        experiment: Dict[str, Any],
    ) -> tuple:
        """Determine evidence quality grade based on protocol.

        Rules:
        - strict_ab + all required fields + all arms linked = causal
        - pragmatic_split or partial = quasi
        - observational or missing = observational

        Args:
            experiment: Experiment dict with protocol and arms.

        Returns:
            Tuple of (quality_grade, quality_notes).
        """
        protocol = experiment.get("protocol") or {}
        method_type = protocol.get("method_type", "observational")

        base_grade = METHOD_TYPE_TO_BASE_GRADE.get(method_type, "observational")
        notes = []

        if base_grade == "causal":
            # Verify all required protocol fields are present
            missing = [f for f in CAUSAL_REQUIRED_PROTOCOL_FIELDS if not protocol.get(f)]
            if missing:
                base_grade = "quasi"
                notes.append(f"Downgraded from causal: missing protocol fields {missing}")

            # Verify all arms are linked
            arms = experiment.get("arms", [])
            unlinked = [a["name"] for a in arms if not a.get("meta_adset_id")]
            if unlinked:
                base_grade = "quasi"
                notes.append(f"Downgraded from causal: unlinked arms {unlinked}")

        return base_grade, "; ".join(notes) if notes else None

    # =========================================================================
    # Conclusion + Causal Effects
    # =========================================================================

    async def declare_winner(
        self,
        experiment_id: UUID,
    ) -> Dict[str, Any]:
        """Conclude experiment with winner, compute ATE, store causal_effects.

        Args:
            experiment_id: Experiment UUID.

        Returns:
            Dict with winner info and causal effects stored.

        Raises:
            ValueError: If no analysis or decision is not 'winner'.
        """
        experiment = await self.get_experiment(experiment_id)
        latest = experiment.get("latest_analysis")

        if not latest:
            raise ValueError("No analysis exists")
        if latest.get("decision") != "winner":
            raise ValueError(f"Decision is '{latest.get('decision')}', not 'winner'")

        winner_arm_id = latest.get("winner_arm_id")
        arm_results = latest.get("arm_results", [])

        # Find control and winner arms
        control = next((ar for ar in arm_results if ar.get("is_control")), None)
        winner = next((ar for ar in arm_results if ar.get("arm_id") == winner_arm_id), None)

        if not control or not winner:
            raise ValueError("Cannot find control or winner arm in results")

        # Store causal effects for each treatment arm vs control
        effects_stored = []
        for ar in arm_results:
            if ar.get("is_control"):
                continue
            effect = await self._store_causal_effect(experiment, control, ar, latest)
            effects_stored.append(effect)

        # Transition to concluded
        await self.transition_status(experiment_id, "concluded")

        return {
            "winner_arm_id": winner_arm_id,
            "winner_arm_name": winner.get("arm_name"),
            "winner_p_best": latest.get("winner_p_best"),
            "quality_grade": latest.get("quality_grade"),
            "causal_effects_stored": len(effects_stored),
        }

    async def mark_inconclusive(
        self,
        experiment_id: UUID,
    ) -> Dict[str, Any]:
        """Conclude experiment without winner.

        Still stores observational-grade causal effects for knowledge base.

        Args:
            experiment_id: Experiment UUID.

        Returns:
            Dict with conclusion info.
        """
        experiment = await self.get_experiment(experiment_id)
        latest = experiment.get("latest_analysis")

        if not latest:
            raise ValueError("No analysis exists")

        arm_results = latest.get("arm_results", [])
        control = next((ar for ar in arm_results if ar.get("is_control")), None)

        # Store effects even for inconclusive (lower quality grade)
        effects_stored = []
        if control:
            for ar in arm_results:
                if ar.get("is_control"):
                    continue
                effect = await self._store_causal_effect(experiment, control, ar, latest)
                effects_stored.append(effect)

        await self.transition_status(experiment_id, "concluded")

        return {
            "decision": latest.get("decision"),
            "quality_grade": latest.get("quality_grade"),
            "causal_effects_stored": len(effects_stored),
        }

    async def _store_causal_effect(
        self,
        experiment: Dict[str, Any],
        control: Dict[str, Any],
        treatment: Dict[str, Any],
        analysis: Dict[str, Any],
    ) -> Dict[str, Any]:
        """Store a single causal_effects row for a treatment vs control comparison.

        Args:
            experiment: Experiment dict.
            control: Control arm results.
            treatment: Treatment arm results.
            analysis: Analysis dict with quality_grade.

        Returns:
            Stored causal effect record.
        """
        control_ctr = control.get("ctr", 0.0)
        treatment_ctr = treatment.get("ctr", 0.0)

        ate = treatment_ctr - control_ctr
        ate_relative = (ate / control_ctr) if control_ctr > 0 else None

        # Compute 95% credible interval from posteriors
        rng = np.random.default_rng(42)
        control_samples = rng.beta(
            control.get("posterior_alpha", 1),
            control.get("posterior_beta", 1),
            size=MONTE_CARLO_SAMPLES,
        )
        treatment_samples = rng.beta(
            treatment.get("posterior_alpha", 1),
            treatment.get("posterior_beta", 1),
            size=MONTE_CARLO_SAMPLES,
        )
        diff_samples = treatment_samples - control_samples
        ci_lower = float(np.percentile(diff_samples, 2.5))
        ci_upper = float(np.percentile(diff_samples, 97.5))

        record = {
            "experiment_id": experiment["id"],
            "brand_id": experiment["brand_id"],
            "product_id": experiment.get("product_id"),
            "test_variable": experiment["test_variable"],
            "control_value": control.get("variable_value", ""),
            "treatment_value": treatment.get("variable_value", ""),
            "metric": "ctr",
            "ate": round(ate, 8),
            "ate_relative": round(ate_relative, 6) if ate_relative is not None else None,
            "ci_lower": round(ci_lower, 8),
            "ci_upper": round(ci_upper, 8),
            "p_best": treatment.get("p_best"),
            "quality_grade": analysis.get("quality_grade", "observational"),
            "control_impressions": control.get("impressions", 0),
            "treatment_impressions": treatment.get("impressions", 0),
            "concluded_at": datetime.now(timezone.utc).isoformat(),
        }

        result = self.supabase.table("causal_effects").insert(record).execute()
        logger.info(
            f"Stored causal effect: {experiment['test_variable']} "
            f"({control.get('variable_value')} → {treatment.get('variable_value')}) "
            f"ATE={ate:.6f}, grade={analysis.get('quality_grade')}"
        )
        return result.data[0] if result.data else record

    # =========================================================================
    # Queries
    # =========================================================================

    async def get_experiment_status(
        self,
        experiment_id: UUID,
    ) -> Dict[str, Any]:
        """Get full experiment status with latest analysis.

        Args:
            experiment_id: Experiment UUID.

        Returns:
            Dict with experiment data, arms, and latest analysis.
        """
        return await self.get_experiment(experiment_id)

    async def get_causal_knowledge_base(
        self,
        brand_id: UUID,
        product_id: Optional[UUID] = None,
        test_variable: Optional[str] = None,
    ) -> List[Dict[str, Any]]:
        """Query causal_effects knowledge base.

        Args:
            brand_id: Brand UUID.
            product_id: Optional product filter.
            test_variable: Optional variable filter.

        Returns:
            List of causal effect records, sorted by quality then ATE.
        """
        query = self.supabase.table("causal_effects").select("*").eq(
            "brand_id", str(brand_id)
        )

        if product_id:
            query = query.eq("product_id", str(product_id))
        if test_variable:
            query = query.eq("test_variable", test_variable)

        result = query.order("created_at", desc=True).execute()
        effects = result.data or []

        # Sort: causal first, then quasi, then observational; within grade by |ATE| desc
        grade_order = {"causal": 0, "quasi": 1, "observational": 2}
        effects.sort(key=lambda e: (
            grade_order.get(e.get("quality_grade", "observational"), 2),
            -(abs(e.get("ate_relative") or 0)),
        ))

        return effects


# =============================================================================
# Helper Functions (module-level, testable)
# =============================================================================

def _z_score(p: float) -> float:
    """Compute z-score for cumulative probability p using rational approximation.

    Uses Abramowitz and Stegun approximation (accurate to ~4.5e-4).

    Args:
        p: Cumulative probability (0 < p < 1).

    Returns:
        z-score.
    """
    if p <= 0 or p >= 1:
        raise ValueError(f"p must be in (0, 1), got {p}")

    # Use symmetry for p < 0.5
    if p < 0.5:
        return -_z_score(1 - p)

    # Rational approximation constants
    t = math.sqrt(-2 * math.log(1 - p))
    c0 = 2.515517
    c1 = 0.802853
    c2 = 0.010328
    d1 = 1.432788
    d2 = 0.189269
    d3 = 0.001308

    z = t - (c0 + c1 * t + c2 * t ** 2) / (1 + d1 * t + d2 * t ** 2 + d3 * t ** 3)
    return z
