"""
Creative Genome Service — Thompson Sampling performance feedback loop.

Closes the ad creation learning loop:
1. Computes composite reward scores for matured ads (CTR, Conv, ROAS)
2. Updates Beta(α,β) distributions per creative element via Thompson Sampling
3. Provides pre-generation scores and advisory performance context
4. Handles cold-start with cross-brand priors

Tables:
    - creative_element_scores: Beta(α,β) per (brand, element_name, element_value)
    - creative_element_rewards: Composite reward per matured ad
    - system_alerts: Monitoring alerts for genome health
"""

import logging
import math
from datetime import datetime, timedelta, timezone
from typing import Dict, List, Optional, Tuple, Any
from uuid import UUID

import numpy as np

logger = logging.getLogger(__name__)


# =============================================================================
# Constants
# =============================================================================

# Maturation windows: (min_days, min_impressions)
MATURATION_WINDOWS = {
    "ctr": (3, 500),
    "conv": (7, 500),
    "roas": (10, 500),
}

# Reward weights per campaign objective
REWARD_WEIGHTS = {
    "CONVERSIONS": {"ctr": 0.2, "conv": 0.5, "roas": 0.3},
    "SALES": {"ctr": 0.2, "conv": 0.3, "roas": 0.5},
    "TRAFFIC": {"ctr": 0.6, "conv": 0.2, "roas": 0.2},
    "AWARENESS": {"ctr": 0.7, "conv": 0.1, "roas": 0.2},
    "ENGAGEMENT": {"ctr": 0.5, "conv": 0.3, "roas": 0.2},
    "DEFAULT": {"ctr": 0.4, "conv": 0.3, "roas": 0.3},
}

# Elements tracked by the genome
TRACKED_ELEMENTS = [
    "hook_type", "color_mode", "template_category",
    "awareness_stage", "canvas_size", "content_source",
]

# Cold-start shrinkage factor for cross-brand priors
CROSS_BRAND_SHRINKAGE = 0.3

# Exploration boost decay
EXPLORATION_FLOOR = 0.05
EXPLORATION_INITIAL = 0.30
EXPLORATION_DECAY_RATE = 100  # total_matured_ads / this

# Monitoring thresholds (Section 13 of plan)
MONITORING_THRESHOLDS = {
    "approval_rate": {"warning": 0.20, "critical": 0.10},
    "prediction_accuracy": {"warning": 0.40, "critical": 0.25},
    "generation_success_rate": {"warning": 0.70, "critical": 0.50},
    "data_freshness_days": {"warning": 14, "critical": 30},
    "winner_rate": {"warning": 0.05, "critical": 0.02},
}


class CreativeGenomeService:
    """Creative Genome — Thompson Sampling performance feedback loop."""

    def __init__(self):
        from viraltracker.core.database import get_supabase_client
        self.supabase = get_supabase_client()

    # =========================================================================
    # 6.2: Reward Computation
    # =========================================================================

    async def compute_rewards(self, brand_id: UUID) -> Dict[str, Any]:
        """Find matured ads, compute composite reward, store in creative_element_rewards.

        Returns:
            Summary dict with new_rewards count and details.
        """
        matured_ads = await self.get_matured_ads(brand_id)
        if not matured_ads:
            return {"new_rewards": 0, "message": "No matured ads found"}

        # Load baselines for normalization
        baselines = self._load_baselines(brand_id)

        new_rewards = 0
        for ad in matured_ads:
            try:
                objective = ad.get("campaign_objective") or "DEFAULT"
                reward_score, components = self._compute_composite_reward(
                    ad, baselines, objective
                )

                # Insert into creative_element_rewards
                self.supabase.table("creative_element_rewards").insert({
                    "generated_ad_id": ad["generated_ad_id"],
                    "brand_id": str(brand_id),
                    "reward_score": reward_score,
                    "reward_components": components,
                    "campaign_objective": objective,
                    "matured_at": datetime.now(timezone.utc).isoformat(),
                    "impressions_at_maturity": ad.get("total_impressions", 0),
                }).execute()

                new_rewards += 1
            except Exception as e:
                logger.error(f"Failed to compute reward for ad {ad.get('generated_ad_id')}: {e}")

        logger.info(f"Computed {new_rewards} new rewards for brand {brand_id}")
        return {"new_rewards": new_rewards, "brand_id": str(brand_id)}

    def _compute_composite_reward(
        self,
        perf_row: Dict,
        baselines: Dict,
        objective: str,
    ) -> Tuple[float, Dict]:
        """Weighted reward: w_ctr*norm_ctr + w_conv*norm_conv + w_roas*norm_roas.

        Returns:
            (reward_score, components_dict)
        """
        weights = REWARD_WEIGHTS.get(objective, REWARD_WEIGHTS["DEFAULT"])

        # Normalize each metric using baselines
        ctr_norm = self._normalize_metric(
            perf_row.get("avg_ctr"),
            baselines.get("p25_ctr", 0.005),
            baselines.get("p75_ctr", 0.02),
        )
        conv_norm = self._normalize_metric(
            perf_row.get("avg_conversion_rate"),
            baselines.get("p25_conversion_rate", 0.005),
            baselines.get("p75_conversion_rate", 0.03),
        )
        roas_norm = self._normalize_metric(
            perf_row.get("avg_roas"),
            baselines.get("p25_roas", 0.5),
            baselines.get("p75_roas", 3.0),
        )

        reward_score = (
            weights["ctr"] * ctr_norm
            + weights["conv"] * conv_norm
            + weights["roas"] * roas_norm
        )
        # Clamp to [0, 1]
        reward_score = max(0.0, min(1.0, reward_score))

        components = {
            "ctr_norm": ctr_norm,
            "conv_norm": conv_norm,
            "roas_norm": roas_norm,
            "weights": weights,
            "objective": objective,
        }
        return reward_score, components

    def _normalize_metric(
        self,
        value: Optional[float],
        p25: float,
        p75: float,
    ) -> float:
        """Normalize to [0,1] using baselines. p25→0.0, p75→1.0, clamped.

        Args:
            value: Raw metric value (may be None)
            p25: 25th percentile baseline
            p75: 75th percentile baseline

        Returns:
            Normalized value in [0, 1]
        """
        if value is None:
            return 0.5  # neutral when metric unavailable

        if p75 == p25:
            return 0.5  # avoid division by zero

        normalized = (value - p25) / (p75 - p25)
        return max(0.0, min(1.0, normalized))

    async def get_matured_ads(self, brand_id: UUID) -> List[Dict]:
        """Find generated_ads with meta performance data meeting maturation windows.

        Joins generated_ads → meta_ad_mapping → meta_ads_performance.
        Filters by CTR maturation window (3 days, 500 impressions).
        Skips ads already in creative_element_rewards.

        Returns:
            List of dicts with ad + aggregated performance data.
        """
        # Get already-rewarded ad IDs
        existing = self.supabase.table("creative_element_rewards").select(
            "generated_ad_id"
        ).eq("brand_id", str(brand_id)).execute()
        existing_ids = {r["generated_ad_id"] for r in (existing.data or [])}

        # Find mapped ads with performance data
        # Join: generated_ads → meta_ad_mapping → meta_ads_performance
        mapped = self.supabase.table("meta_ad_mapping").select(
            "generated_ad_id, meta_ad_id"
        ).execute()

        if not mapped.data:
            return []

        # Filter to ads with element_tags (Phase 6+ ads)
        gen_ads = self.supabase.table("generated_ads").select(
            "id, element_tags, ad_run_id"
        ).eq(
            "ad_run_id",
            # We need to filter by brand - get ad_runs for this brand
            # Actually, let's filter via the ad_runs table
        ).not_.is_("element_tags", "null").execute()

        # Get ad_runs for this brand to filter generated_ads
        ad_runs = self.supabase.table("ad_runs").select(
            "id"
        ).eq("brand_id", str(brand_id)).execute()
        brand_run_ids = {r["id"] for r in (ad_runs.data or [])}

        # Build lookup of generated_ads with element_tags for this brand
        eligible_ads = {}
        for ga in (gen_ads.data or []):
            if ga["ad_run_id"] in brand_run_ids and ga["id"] not in existing_ids:
                eligible_ads[ga["id"]] = ga

        if not eligible_ads:
            return []

        # Match mapped ads to eligible ads
        matured = []
        cutoff_date = (datetime.now(timezone.utc) - timedelta(days=3)).strftime("%Y-%m-%d")

        for mapping in mapped.data:
            gen_ad_id = mapping["generated_ad_id"]
            if gen_ad_id not in eligible_ads:
                continue

            meta_ad_id = mapping["meta_ad_id"]

            # Get aggregated performance for this meta ad
            perf = self.supabase.table("meta_ads_performance").select(
                "impressions, link_ctr, conversion_rate, roas, date, campaign_objective"
            ).eq(
                "meta_ad_id", meta_ad_id
            ).lte("date", cutoff_date).execute()

            if not perf.data:
                continue

            # Aggregate: sum impressions, weighted avg of metrics
            total_imp = sum(r.get("impressions") or 0 for r in perf.data)
            if total_imp < 500:
                continue  # Not matured yet

            # Weighted average CTR, conversion_rate, ROAS
            avg_ctr = self._weighted_avg(perf.data, "link_ctr", "impressions")
            avg_conv = self._weighted_avg(perf.data, "conversion_rate", "impressions")
            avg_roas = self._weighted_avg(perf.data, "roas", "impressions")

            # Get campaign objective from most recent row
            objective = perf.data[-1].get("campaign_objective") or "DEFAULT"

            matured.append({
                "generated_ad_id": gen_ad_id,
                "element_tags": eligible_ads[gen_ad_id].get("element_tags"),
                "total_impressions": total_imp,
                "avg_ctr": avg_ctr,
                "avg_conversion_rate": avg_conv,
                "avg_roas": avg_roas,
                "campaign_objective": objective,
            })

        return matured

    def _weighted_avg(
        self,
        rows: List[Dict],
        metric_key: str,
        weight_key: str,
    ) -> Optional[float]:
        """Compute weighted average of a metric across rows."""
        total_weight = 0
        weighted_sum = 0.0
        for row in rows:
            val = row.get(metric_key)
            weight = row.get(weight_key) or 0
            if val is not None and weight > 0:
                weighted_sum += val * weight
                total_weight += weight
        if total_weight == 0:
            return None
        return weighted_sum / total_weight

    def _load_baselines(self, brand_id: UUID) -> Dict:
        """Load ad_intelligence_baselines for normalization.

        Returns the most recent baseline row for this brand, or defaults.
        """
        try:
            result = self.supabase.table("ad_intelligence_baselines").select(
                "p25_ctr, p75_ctr, p25_conversion_rate, p75_conversion_rate, "
                "p25_roas, p75_roas"
            ).eq(
                "brand_id", str(brand_id)
            ).order(
                "computed_at", desc=True
            ).limit(1).execute()

            if result.data:
                return result.data[0]
        except Exception as e:
            logger.warning(f"Failed to load baselines for brand {brand_id}: {e}")

        # Defaults if no baselines exist
        return {
            "p25_ctr": 0.005,
            "p75_ctr": 0.02,
            "p25_conversion_rate": 0.005,
            "p75_conversion_rate": 0.03,
            "p25_roas": 0.5,
            "p75_roas": 3.0,
        }

    # =========================================================================
    # 6.3: Thompson Sampling
    # =========================================================================

    async def update_element_scores(self, brand_id: UUID) -> Dict[str, Any]:
        """Update Beta(α,β) distributions from new rewards.

        For each rewarded ad, extracts element_tags and updates the
        corresponding creative_element_scores rows.

        Returns:
            Summary dict with elements_updated count.
        """
        # Get all rewards for this brand that have element_tags
        rewards = self.supabase.table("creative_element_rewards").select(
            "generated_ad_id, reward_score"
        ).eq("brand_id", str(brand_id)).execute()

        if not rewards.data:
            return {"elements_updated": 0}

        # Batch-fetch generated_ads element_tags
        reward_ad_ids = [r["generated_ad_id"] for r in rewards.data]
        reward_map = {r["generated_ad_id"]: r["reward_score"] for r in rewards.data}

        # Fetch element_tags for rewarded ads
        ads_data = self.supabase.table("generated_ads").select(
            "id, element_tags"
        ).in_("id", reward_ad_ids).execute()

        # Build element → reward accumulations
        element_updates: Dict[str, Dict[str, List[float]]] = {}
        for ad in (ads_data.data or []):
            tags = ad.get("element_tags") or {}
            reward = reward_map.get(ad["id"])
            if reward is None:
                continue

            for elem_name in TRACKED_ELEMENTS:
                elem_val = tags.get(elem_name)
                if elem_val is None:
                    continue
                elem_val = str(elem_val)

                key = f"{elem_name}:{elem_val}"
                if key not in element_updates:
                    element_updates[key] = {"rewards": []}
                element_updates[key]["rewards"].append(reward)

        # Upsert creative_element_scores
        elements_updated = 0
        for key, data in element_updates.items():
            elem_name, elem_val = key.split(":", 1)
            rewards_list = data["rewards"]

            # Calculate alpha/beta increments
            alpha_inc = sum(1 for r in rewards_list if r >= 0.5)
            beta_inc = sum(1 for r in rewards_list if r < 0.5)
            mean_reward = sum(rewards_list) / len(rewards_list) if rewards_list else 0.5

            try:
                # Try to fetch existing
                existing = self.supabase.table("creative_element_scores").select(
                    "id, alpha, beta, total_observations"
                ).eq("brand_id", str(brand_id)).eq(
                    "element_name", elem_name
                ).eq("element_value", elem_val).execute()

                now = datetime.now(timezone.utc).isoformat()

                if existing.data:
                    row = existing.data[0]
                    self.supabase.table("creative_element_scores").update({
                        "alpha": row["alpha"] + alpha_inc,
                        "beta": row["beta"] + beta_inc,
                        "total_observations": row["total_observations"] + len(rewards_list),
                        "mean_reward": mean_reward,
                        "last_updated": now,
                    }).eq("id", row["id"]).execute()
                else:
                    self.supabase.table("creative_element_scores").insert({
                        "brand_id": str(brand_id),
                        "element_name": elem_name,
                        "element_value": elem_val,
                        "alpha": 1.0 + alpha_inc,
                        "beta": 1.0 + beta_inc,
                        "total_observations": len(rewards_list),
                        "mean_reward": mean_reward,
                        "last_updated": now,
                    }).execute()

                elements_updated += 1
            except Exception as e:
                logger.error(f"Failed to update element score {key}: {e}")

        logger.info(f"Updated {elements_updated} element scores for brand {brand_id}")
        return {"elements_updated": elements_updated, "brand_id": str(brand_id)}

    def sample_element_scores(
        self,
        brand_id: UUID,
        element_name: str,
    ) -> List[Dict]:
        """Sample from Beta distributions for each value of an element.

        Returns ranked list of {value, sample, alpha, beta, mean_reward}.
        """
        result = self.supabase.table("creative_element_scores").select(
            "element_value, alpha, beta, mean_reward, total_observations"
        ).eq("brand_id", str(brand_id)).eq(
            "element_name", element_name
        ).execute()

        if not result.data:
            return []

        samples = []
        for row in result.data:
            alpha = row["alpha"]
            beta_param = row["beta"]
            sample = np.random.beta(alpha, beta_param)
            samples.append({
                "value": row["element_value"],
                "sample": float(sample),
                "alpha": alpha,
                "beta": beta_param,
                "mean_reward": row.get("mean_reward"),
                "total_observations": row.get("total_observations", 0),
            })

        # Sort by sample (highest first = exploitation + exploration)
        samples.sort(key=lambda x: x["sample"], reverse=True)
        return samples

    async def get_pre_gen_score(
        self,
        brand_id: UUID,
        element_tags: Dict,
    ) -> float:
        """Score a proposed ad config using current element posteriors.

        For each tracked element in element_tags, samples from the posterior
        and averages across all elements. Returns [0, 1].

        Args:
            brand_id: Brand UUID
            element_tags: Dict of element_name → element_value

        Returns:
            Float score in [0, 1], or 0.5 if no data.
        """
        scores = []
        for elem_name in TRACKED_ELEMENTS:
            elem_val = element_tags.get(elem_name)
            if elem_val is None:
                continue
            elem_val = str(elem_val)

            # Look up posterior
            result = self.supabase.table("creative_element_scores").select(
                "alpha, beta"
            ).eq("brand_id", str(brand_id)).eq(
                "element_name", elem_name
            ).eq("element_value", elem_val).execute()

            if result.data:
                row = result.data[0]
                # Use mean of Beta distribution instead of sampling for deterministic score
                alpha = row["alpha"]
                beta_param = row["beta"]
                mean = alpha / (alpha + beta_param)
                scores.append(mean)

        if not scores:
            return 0.5  # neutral when no data

        return sum(scores) / len(scores)

    async def get_performance_context(self, brand_id: UUID) -> Dict[str, Any]:
        """Build advisory performance context for prompt injection.

        Returns dict with top performers, cold-start level, and optimization notes.
        """
        # Determine cold-start level
        total_rewards = self.supabase.table("creative_element_rewards").select(
            "id", count="exact"
        ).eq("brand_id", str(brand_id)).execute()
        total_count = total_rewards.count if total_rewards.count is not None else 0

        if total_count == 0:
            cold_start_level = 0
        elif total_count < 30:
            cold_start_level = 1
        elif total_count < 100:
            cold_start_level = 2
        else:
            cold_start_level = 3

        # Get top performing elements
        top_elements = {}
        for elem_name in TRACKED_ELEMENTS:
            samples = self.sample_element_scores(brand_id, elem_name)
            if samples:
                top_elements[elem_name] = {
                    "top_values": [s["value"] for s in samples[:3]],
                    "top_scores": [round(s["sample"], 3) for s in samples[:3]],
                }

        # Get recent approval rate
        approval_rate = await self._compute_approval_rate(brand_id)

        # Build optimization notes
        notes = []
        if cold_start_level <= 1:
            notes.append("Limited performance data available. Exploring broadly.")
        if approval_rate is not None and approval_rate < 0.3:
            notes.append(f"Low approval rate ({approval_rate:.1%}). Focus on quality.")

        for elem_name, data in top_elements.items():
            if data["top_scores"] and data["top_scores"][0] > 0.7:
                notes.append(
                    f"Strong signal: {elem_name}={data['top_values'][0]} "
                    f"(score: {data['top_scores'][0]})"
                )

        # Phase 8A: Include interaction effects in advisory context
        interaction_context = None
        try:
            from viraltracker.services.interaction_detector_service import InteractionDetectorService
            detector = InteractionDetectorService()
            interactions = await detector.get_top_interactions(brand_id, limit=6)
            if interactions:
                interaction_context = detector.format_advisory_context(interactions)
                if interaction_context:
                    notes.append(interaction_context)
        except Exception as e:
            logger.debug(f"Interaction data unavailable for advisory: {e}")

        return {
            "cold_start_level": cold_start_level,
            "total_matured_ads": total_count,
            "top_performing_elements": top_elements,
            "historical_approval_rate": approval_rate,
            "optimization_notes": " | ".join(notes) if notes else None,
            "exploration_rate": self._exploration_rate(total_count),
            "interaction_effects": interaction_context,
        }

    async def get_category_priors(
        self,
        element_name: str,
    ) -> Tuple[float, float]:
        """Cross-brand aggregate priors with 0.3x shrinkage for cold-start.

        Aggregates all brands' element scores for this element_name,
        then applies shrinkage toward the uniform prior.

        Returns:
            (alpha_prior, beta_prior) tuple
        """
        result = self.supabase.table("creative_element_scores").select(
            "alpha, beta, total_observations"
        ).eq("element_name", element_name).execute()

        if not result.data:
            return (1.0, 1.0)  # uniform prior

        # Aggregate: weighted by observations
        total_alpha = sum(r["alpha"] * r.get("total_observations", 1) for r in result.data)
        total_beta = sum(r["beta"] * r.get("total_observations", 1) for r in result.data)
        total_obs = sum(r.get("total_observations", 1) for r in result.data)

        if total_obs == 0:
            return (1.0, 1.0)

        # Average then shrink toward uniform
        avg_alpha = total_alpha / total_obs
        avg_beta = total_beta / total_obs

        prior_alpha = 1.0 + CROSS_BRAND_SHRINKAGE * (avg_alpha - 1.0)
        prior_beta = 1.0 + CROSS_BRAND_SHRINKAGE * (avg_beta - 1.0)

        return (max(0.5, prior_alpha), max(0.5, prior_beta))

    # =========================================================================
    # 6.4: Monitoring + Validation
    # =========================================================================

    async def run_validation(self, brand_id: UUID) -> Dict[str, Any]:
        """Run genome health validation and create alerts if thresholds exceeded.

        Returns:
            Summary dict with metrics and alerts created.
        """
        metrics = {}
        alerts_created = 0

        # 1. Approval rate
        approval_rate = await self._compute_approval_rate(brand_id)
        if approval_rate is not None:
            metrics["approval_rate"] = approval_rate
            alerts_created += self._check_threshold(
                brand_id, "approval_rate", approval_rate,
                lower_is_worse=True,
            )

        # 2. Generation success rate
        success_rate = await self._compute_generation_success_rate(brand_id)
        if success_rate is not None:
            metrics["generation_success_rate"] = success_rate
            alerts_created += self._check_threshold(
                brand_id, "generation_success_rate", success_rate,
                lower_is_worse=True,
            )

        # 3. Data freshness (days since last reward)
        freshness_days = await self._compute_data_freshness(brand_id)
        if freshness_days is not None:
            metrics["data_freshness_days"] = freshness_days
            alerts_created += self._check_threshold(
                brand_id, "data_freshness_days", freshness_days,
                lower_is_worse=False,  # higher days = worse
            )

        # 4. Winner rate (ads with reward >= 0.7)
        winner_rate = await self._compute_winner_rate(brand_id)
        if winner_rate is not None:
            metrics["winner_rate"] = winner_rate
            alerts_created += self._check_threshold(
                brand_id, "winner_rate", winner_rate,
                lower_is_worse=True,
            )

        logger.info(f"Validation for brand {brand_id}: {metrics}, alerts={alerts_created}")
        return {
            "brand_id": str(brand_id),
            "metrics": metrics,
            "alerts_created": alerts_created,
        }

    def _check_threshold(
        self,
        brand_id: UUID,
        metric_name: str,
        value: float,
        lower_is_worse: bool = True,
    ) -> int:
        """Check metric against warning/critical thresholds. Returns alerts created count."""
        thresholds = MONITORING_THRESHOLDS.get(metric_name)
        if not thresholds:
            return 0

        warning_thresh = thresholds["warning"]
        critical_thresh = thresholds["critical"]

        severity = None
        if lower_is_worse:
            if value < critical_thresh:
                severity = "critical"
            elif value < warning_thresh:
                severity = "warning"
        else:
            if value > critical_thresh:
                severity = "critical"
            elif value > warning_thresh:
                severity = "warning"

        if severity is None:
            return 0

        try:
            self.supabase.table("system_alerts").insert({
                "brand_id": str(brand_id),
                "alert_type": metric_name,
                "severity": severity,
                "metric_value": value,
                "threshold_value": critical_thresh if severity == "critical" else warning_thresh,
                "message": (
                    f"{metric_name} is {value:.3f} "
                    f"({'below' if lower_is_worse else 'above'} "
                    f"{severity} threshold {critical_thresh if severity == 'critical' else warning_thresh})"
                ),
            }).execute()
            return 1
        except Exception as e:
            logger.error(f"Failed to create alert for {metric_name}: {e}")
            return 0

    # =========================================================================
    # Internal helpers
    # =========================================================================

    async def _compute_approval_rate(self, brand_id: UUID) -> Optional[float]:
        """Compute recent approval rate for this brand (last 30 days)."""
        try:
            cutoff = (datetime.now(timezone.utc) - timedelta(days=30)).isoformat()

            # Get ad_runs for this brand
            runs = self.supabase.table("ad_runs").select(
                "id"
            ).eq("brand_id", str(brand_id)).gte(
                "created_at", cutoff
            ).execute()

            if not runs.data:
                return None

            run_ids = [r["id"] for r in runs.data]

            # Count approved and total
            total = self.supabase.table("generated_ads").select(
                "id", count="exact"
            ).in_("ad_run_id", run_ids).in_(
                "final_status", ["approved", "rejected"]
            ).execute()

            approved = self.supabase.table("generated_ads").select(
                "id", count="exact"
            ).in_("ad_run_id", run_ids).eq(
                "final_status", "approved"
            ).execute()

            total_count = total.count if total.count else 0
            approved_count = approved.count if approved.count else 0

            if total_count == 0:
                return None

            return approved_count / total_count
        except Exception as e:
            logger.warning(f"Failed to compute approval rate: {e}")
            return None

    async def _compute_generation_success_rate(self, brand_id: UUID) -> Optional[float]:
        """Compute generation success rate (last 30 days)."""
        try:
            cutoff = (datetime.now(timezone.utc) - timedelta(days=30)).isoformat()

            runs = self.supabase.table("ad_runs").select(
                "id"
            ).eq("brand_id", str(brand_id)).gte(
                "created_at", cutoff
            ).execute()

            if not runs.data:
                return None

            run_ids = [r["id"] for r in runs.data]

            total = self.supabase.table("generated_ads").select(
                "id", count="exact"
            ).in_("ad_run_id", run_ids).execute()

            failed = self.supabase.table("generated_ads").select(
                "id", count="exact"
            ).in_("ad_run_id", run_ids).eq(
                "final_status", "generation_failed"
            ).execute()

            total_count = total.count if total.count else 0
            failed_count = failed.count if failed.count else 0

            if total_count == 0:
                return None

            return (total_count - failed_count) / total_count
        except Exception as e:
            logger.warning(f"Failed to compute generation success rate: {e}")
            return None

    async def _compute_data_freshness(self, brand_id: UUID) -> Optional[float]:
        """Compute days since last reward for this brand."""
        try:
            result = self.supabase.table("creative_element_rewards").select(
                "matured_at"
            ).eq("brand_id", str(brand_id)).order(
                "matured_at", desc=True
            ).limit(1).execute()

            if not result.data or not result.data[0].get("matured_at"):
                return None

            last_matured = datetime.fromisoformat(
                result.data[0]["matured_at"].replace("Z", "+00:00")
            )
            delta = datetime.now(timezone.utc) - last_matured
            return delta.total_seconds() / 86400  # days
        except Exception as e:
            logger.warning(f"Failed to compute data freshness: {e}")
            return None

    async def _compute_winner_rate(self, brand_id: UUID) -> Optional[float]:
        """Compute fraction of ads with reward >= 0.7."""
        try:
            total = self.supabase.table("creative_element_rewards").select(
                "id", count="exact"
            ).eq("brand_id", str(brand_id)).execute()

            winners = self.supabase.table("creative_element_rewards").select(
                "id", count="exact"
            ).eq("brand_id", str(brand_id)).gte(
                "reward_score", 0.7
            ).execute()

            total_count = total.count if total.count else 0
            winner_count = winners.count if winners.count else 0

            if total_count == 0:
                return None

            return winner_count / total_count
        except Exception as e:
            logger.warning(f"Failed to compute winner rate: {e}")
            return None

    def _exploration_rate(self, total_matured_ads: int) -> float:
        """Compute exploration boost rate.

        max(0.05, 0.30 * exp(-total_matured_ads / 100))
        """
        return max(
            EXPLORATION_FLOOR,
            EXPLORATION_INITIAL * math.exp(-total_matured_ads / EXPLORATION_DECAY_RATE),
        )
