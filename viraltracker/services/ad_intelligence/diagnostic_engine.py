"""Layer 3: DiagnosticEngine — Rules-based per-ad diagnostics.

Evaluates each ad against a registry of diagnostic rules, each with metric
prerequisites and minimum sample thresholds. Produces per-ad health assessments
with fired/skipped rules and kill recommendations.

Rule aggregation types:
- "total": Pre-aggregated metrics over the rule's window → single values
- "daily_series": Per-day metric arrays → trend analysis

Kill determination:
- test_failure: CRITICAL efficiency + running > 7 days + spend > $100
- fatigue: CRITICAL fatigue category
- inefficient: zero conversions + spend > $200
"""

from __future__ import annotations

import logging
from datetime import date, datetime, timedelta
from typing import Any, Callable, Dict, List, Optional, Tuple
from uuid import UUID

from .helpers import (
    _safe_numeric,
    compute_roas,
    extract_conversions,
)
from .models import (
    AdDiagnostic,
    BaselineSnapshot,
    CreativeClassification,
    FiredRule,
    HealthStatus,
    RunConfig,
)

logger = logging.getLogger(__name__)


class DiagnosticRule:
    """A single diagnostic rule with prerequisites and evaluation logic.

    Attributes:
        rule_id: Unique rule identifier.
        rule_name: Human-readable name.
        category: Rule category (efficiency, fatigue, creative, funnel, frequency).
        required_metrics: Metrics that must be non-None for evaluation.
        min_impressions: Minimum total impressions to evaluate.
        min_days: Minimum days of data.
        aggregation: "total" (single aggregate) or "daily_series" (per-day arrays).
        window_days: Trailing window (0 = full run window).
        check_fn: Callable that performs the actual check.
    """

    def __init__(
        self,
        rule_id: str,
        rule_name: str,
        category: str,
        required_metrics: List[str],
        check_fn: Callable,
        min_impressions: int = 100,
        min_days: int = 3,
        aggregation: str = "total",
        window_days: int = 0,
    ):
        self.rule_id = rule_id
        self.rule_name = rule_name
        self.category = category
        self.required_metrics = required_metrics
        self.min_impressions = min_impressions
        self.min_days = min_days
        self.aggregation = aggregation
        self.window_days = window_days
        self.check_fn = check_fn

    def evaluate(
        self,
        ad_data: Dict[str, Any],
        baseline: Optional[BaselineSnapshot],
    ) -> Optional[FiredRule]:
        """Evaluate rule against ad data.

        1. Check metric prerequisites (return skipped if missing).
        2. Check min_impressions (return skipped if insufficient).
        3. Check min_days (return skipped if insufficient).
        4. Run check_fn.

        Args:
            ad_data: Pre-aggregated or daily-series ad metrics.
            baseline: Cohort baseline (may be None).

        Returns:
            FiredRule if the rule triggers or is skipped, None if rule doesn't fire.
        """
        # 1. Check prerequisites
        missing = [m for m in self.required_metrics if ad_data.get(m) is None]
        if missing:
            return FiredRule(
                rule_id=self.rule_id,
                rule_name=self.rule_name,
                category=self.category,
                severity="info",
                confidence=0.0,
                metric_name=self.required_metrics[0] if self.required_metrics else "",
                explanation=f"Skipped: missing metrics ({', '.join(missing)})",
                skipped=True,
                missing_metrics=missing,
                aggregation=self.aggregation,
                window_days=self.window_days if self.window_days > 0 else None,
            )

        # 2. Check min impressions
        total_impr = _safe_numeric(ad_data.get("total_impressions")) or 0
        if total_impr < self.min_impressions:
            return FiredRule(
                rule_id=self.rule_id,
                rule_name=self.rule_name,
                category=self.category,
                severity="info",
                confidence=0.0,
                metric_name=self.required_metrics[0] if self.required_metrics else "",
                explanation=f"Skipped: {int(total_impr)} impressions (need {self.min_impressions})",
                skipped=True,
                missing_metrics=[],
                aggregation=self.aggregation,
                window_days=self.window_days if self.window_days > 0 else None,
            )

        # 3. Check min days
        actual_days = ad_data.get("days_with_data", 0)
        if actual_days < self.min_days:
            return FiredRule(
                rule_id=self.rule_id,
                rule_name=self.rule_name,
                category=self.category,
                severity="info",
                confidence=0.0,
                metric_name=self.required_metrics[0] if self.required_metrics else "",
                explanation=f"Skipped: only {actual_days} days of data (need {self.min_days})",
                skipped=True,
                missing_metrics=[],
                aggregation=self.aggregation,
                window_days=self.window_days if self.window_days > 0 else None,
            )

        # 4. Run check
        return self.check_fn(ad_data, baseline)


# =============================================================================
# Rule Check Functions
# =============================================================================

def _check_ctr_below_p25(ad_data: Dict, baseline: Optional[BaselineSnapshot]) -> Optional[FiredRule]:
    """CTR below 25th percentile."""
    if not baseline or baseline.p25_ctr is None:
        return None
    actual = _safe_numeric(ad_data.get("link_ctr")) or 0
    if actual < baseline.p25_ctr and baseline.p25_ctr > 0:
        deviation = (baseline.p25_ctr - actual) / baseline.p25_ctr
        return FiredRule(
            rule_id="ctr_below_p25",
            rule_name="CTR Below 25th Percentile",
            category="efficiency",
            severity="warning",
            confidence=_compute_confidence(deviation, ad_data),
            metric_name="link_ctr",
            actual_value=actual,
            baseline_value=baseline.p25_ctr,
            explanation=f"CTR {actual:.4f} is below the 25th percentile ({baseline.p25_ctr:.4f})",
            aggregation="total",
        )
    return None


def _check_ctr_below_p10(ad_data: Dict, baseline: Optional[BaselineSnapshot]) -> Optional[FiredRule]:
    """CTR severely below — likely below 10th percentile (approximated as p25 * 0.6)."""
    if not baseline or baseline.p25_ctr is None:
        return None
    p10_approx = baseline.p25_ctr * 0.6
    actual = _safe_numeric(ad_data.get("link_ctr")) or 0
    if actual < p10_approx and p10_approx > 0:
        deviation = (p10_approx - actual) / p10_approx
        return FiredRule(
            rule_id="ctr_below_p10",
            rule_name="CTR Critically Low",
            category="efficiency",
            severity="critical",
            confidence=_compute_confidence(deviation, ad_data),
            metric_name="link_ctr",
            actual_value=actual,
            baseline_value=p10_approx,
            explanation=f"CTR {actual:.4f} is critically low (est. 10th percentile: {p10_approx:.4f})",
            aggregation="total",
        )
    return None


def _check_cpc_above_p75(ad_data: Dict, baseline: Optional[BaselineSnapshot]) -> Optional[FiredRule]:
    """CPC above 75th percentile — expensive clicks."""
    if not baseline or baseline.p75_cpc is None:
        return None
    actual = _safe_numeric(ad_data.get("link_cpc")) or 0
    if actual > baseline.p75_cpc and baseline.p75_cpc > 0:
        deviation = (actual - baseline.p75_cpc) / baseline.p75_cpc
        return FiredRule(
            rule_id="cpc_above_p75",
            rule_name="CPC Above 75th Percentile",
            category="efficiency",
            severity="warning",
            confidence=_compute_confidence(deviation, ad_data),
            metric_name="link_cpc",
            actual_value=actual,
            baseline_value=baseline.p75_cpc,
            explanation=f"CPC ${actual:.2f} exceeds 75th percentile (${baseline.p75_cpc:.2f})",
            aggregation="total",
        )
    return None


def _check_roas_below_p25(ad_data: Dict, baseline: Optional[BaselineSnapshot]) -> Optional[FiredRule]:
    """ROAS below 25th percentile."""
    if not baseline or baseline.p25_roas is None:
        return None
    actual = _safe_numeric(ad_data.get("roas")) or 0
    if actual < baseline.p25_roas and baseline.p25_roas > 0:
        deviation = (baseline.p25_roas - actual) / baseline.p25_roas
        return FiredRule(
            rule_id="roas_below_p25",
            rule_name="ROAS Below 25th Percentile",
            category="efficiency",
            severity="warning",
            confidence=_compute_confidence(deviation, ad_data),
            metric_name="roas",
            actual_value=actual,
            baseline_value=baseline.p25_roas,
            explanation=f"ROAS {actual:.2f}x is below 25th percentile ({baseline.p25_roas:.2f}x)",
            aggregation="total",
        )
    return None


def _check_frequency_above_threshold(ad_data: Dict, baseline: Optional[BaselineSnapshot]) -> Optional[FiredRule]:
    """Frequency above warning/critical threshold."""
    actual = _safe_numeric(ad_data.get("frequency")) or 0
    threshold = 4.0
    if baseline and baseline.p75_frequency:
        threshold = max(threshold, baseline.p75_frequency * 1.3)

    if actual > threshold:
        severity = "critical" if actual > 5.0 else "warning"
        return FiredRule(
            rule_id="frequency_above_threshold",
            rule_name="Frequency Above Threshold",
            category="fatigue",
            severity=severity,
            confidence=min(actual / threshold * 0.5, 1.0),
            metric_name="frequency",
            actual_value=actual,
            baseline_value=threshold,
            explanation=f"Frequency {actual:.1f} exceeds threshold ({threshold:.1f})",
            aggregation="total",
        )
    return None


def _check_frequency_trend_rising(ad_data: Dict, baseline: Optional[BaselineSnapshot]) -> Optional[FiredRule]:
    """Frequency trending upward over 7 days."""
    series = ad_data.get("frequency_series", [])
    if not series or len(series) < 5:
        return None

    # Simple linear trend: compare first half vs second half
    mid = len(series) // 2
    first_half = [_safe_numeric(v) for v in series[:mid] if _safe_numeric(v) is not None]
    second_half = [_safe_numeric(v) for v in series[mid:] if _safe_numeric(v) is not None]

    if not first_half or not second_half:
        return None

    avg_first = sum(first_half) / len(first_half)
    avg_second = sum(second_half) / len(second_half)

    if avg_first > 0 and avg_second > avg_first * 1.2:
        increase = (avg_second - avg_first) / avg_first
        return FiredRule(
            rule_id="frequency_trend_rising",
            rule_name="Frequency Trending Upward",
            category="fatigue",
            severity="warning",
            confidence=min(increase, 1.0),
            metric_name="frequency",
            actual_value=avg_second,
            baseline_value=avg_first,
            explanation=f"Frequency rising: {avg_first:.1f} → {avg_second:.1f} ({increase:+.0%})",
            aggregation="daily_series",
            window_days=7,
        )
    return None


def _check_ctr_declining_7d(ad_data: Dict, baseline: Optional[BaselineSnapshot]) -> Optional[FiredRule]:
    """CTR declining over 7-day trend."""
    series = ad_data.get("link_ctr_series", [])
    if not series or len(series) < 5:
        return None

    mid = len(series) // 2
    first_half = [_safe_numeric(v) for v in series[:mid] if _safe_numeric(v) is not None]
    second_half = [_safe_numeric(v) for v in series[mid:] if _safe_numeric(v) is not None]

    if not first_half or not second_half:
        return None

    avg_first = sum(first_half) / len(first_half)
    avg_second = sum(second_half) / len(second_half)

    if avg_first > 0 and avg_second < avg_first * 0.85:
        decline = (avg_first - avg_second) / avg_first
        return FiredRule(
            rule_id="ctr_declining_7d",
            rule_name="CTR Declining Over 7 Days",
            category="fatigue",
            severity="warning",
            confidence=min(decline, 1.0),
            metric_name="link_ctr",
            actual_value=avg_second,
            baseline_value=avg_first,
            explanation=f"CTR declining: {avg_first:.4f} → {avg_second:.4f} ({decline:+.0%})",
            aggregation="daily_series",
            window_days=7,
        )
    return None


def _check_spend_no_conversions(ad_data: Dict, baseline: Optional[BaselineSnapshot]) -> Optional[FiredRule]:
    """Spending with zero conversions."""
    total_spend = _safe_numeric(ad_data.get("total_spend")) or 0
    conversions = ad_data.get("total_conversions") or 0

    if total_spend > 50 and conversions == 0:
        severity = "critical" if total_spend > 200 else "warning"
        return FiredRule(
            rule_id="spend_no_conversions",
            rule_name="Spend Without Conversions",
            category="efficiency",
            severity=severity,
            confidence=min(total_spend / 200, 1.0),
            metric_name="conversions",
            actual_value=0,
            baseline_value=None,
            explanation=f"${total_spend:.2f} spent with zero conversions",
            aggregation="total",
        )
    return None


def _check_hook_rate_below_p25(ad_data: Dict, baseline: Optional[BaselineSnapshot]) -> Optional[FiredRule]:
    """Hook rate (3s views / impressions) below baseline."""
    if not baseline or baseline.median_hook_rate is None:
        return None
    actual = _safe_numeric(ad_data.get("hook_rate"))
    if actual is None:
        return None

    # Use median * 0.7 as approx p25
    p25_approx = baseline.median_hook_rate * 0.7
    if actual < p25_approx and p25_approx > 0:
        deviation = (p25_approx - actual) / p25_approx
        return FiredRule(
            rule_id="hook_rate_below_p25",
            rule_name="Low Hook Rate (Thumb-Stop)",
            category="creative",
            severity="warning",
            confidence=_compute_confidence(deviation, ad_data),
            metric_name="hook_rate",
            actual_value=actual,
            baseline_value=p25_approx,
            explanation=f"Hook rate {actual:.2%} is below est. 25th percentile ({p25_approx:.2%})",
            aggregation="total",
        )
    return None


def _check_hold_rate_below_p25(ad_data: Dict, baseline: Optional[BaselineSnapshot]) -> Optional[FiredRule]:
    """Hold rate (p25 watched / 3s views) below baseline."""
    if not baseline or baseline.median_hold_rate is None:
        return None
    actual = _safe_numeric(ad_data.get("hold_rate"))
    if actual is None:
        return None

    p25_approx = baseline.median_hold_rate * 0.7
    if actual < p25_approx and p25_approx > 0:
        deviation = (p25_approx - actual) / p25_approx
        return FiredRule(
            rule_id="hold_rate_below_p25",
            rule_name="Low Hold Rate (Viewer Retention)",
            category="creative",
            severity="warning",
            confidence=_compute_confidence(deviation, ad_data),
            metric_name="hold_rate",
            actual_value=actual,
            baseline_value=p25_approx,
            explanation=f"Hold rate {actual:.2%} is below est. 25th percentile ({p25_approx:.2%})",
            aggregation="total",
        )
    return None


def _check_congruence_below_threshold(ad_data: Dict, baseline: Optional[BaselineSnapshot]) -> Optional[FiredRule]:
    """Congruence score below threshold."""
    actual = _safe_numeric(ad_data.get("congruence_score"))
    if actual is None:
        return None

    threshold = 0.5
    if actual < threshold:
        return FiredRule(
            rule_id="congruence_below_threshold",
            rule_name="Low Creative-Copy Congruence",
            category="creative",
            severity="warning",
            confidence=1.0 - actual,
            metric_name="congruence_score",
            actual_value=actual,
            baseline_value=threshold,
            explanation=f"Congruence score {actual:.2f} indicates awareness level misalignment",
            aggregation="total",
        )
    return None


def _check_impression_starvation(ad_data: Dict, baseline: Optional[BaselineSnapshot]) -> Optional[FiredRule]:
    """Ad receiving very few impressions over 3+ days — may be throttled."""
    series = ad_data.get("impressions_series", [])
    if not series or len(series) < 3:
        return None

    recent = [_safe_numeric(v) or 0 for v in series[-3:]]
    if all(v < 50 for v in recent):
        return FiredRule(
            rule_id="impression_starvation",
            rule_name="Impression Starvation",
            category="funnel",
            severity="warning",
            confidence=0.7,
            metric_name="impressions",
            actual_value=sum(recent) / len(recent),
            baseline_value=None,
            explanation=f"Ad receiving < 50 impressions/day for {len(recent)} consecutive days",
            aggregation="daily_series",
            window_days=3,
        )
    return None


# =============================================================================
# Confidence Computation
# =============================================================================

def _compute_confidence(deviation_ratio: float, ad_data: Dict) -> float:
    """Compute confidence score from deviation ratio and data quality.

    Formula: min(deviation_ratio * 0.5 + days_consistency * 0.3 + data_quality * 0.2, 1.0)

    Args:
        deviation_ratio: How far the metric deviates from baseline (0-1+).
        ad_data: Ad data dict (for days_with_data and impressions).

    Returns:
        Confidence score (0.0 to 1.0).
    """
    days = ad_data.get("days_with_data", 0)
    impressions = _safe_numeric(ad_data.get("total_impressions")) or 0

    days_consistency = min(days / 14, 1.0) if days > 0 else 0
    data_quality = min(impressions / 5000, 1.0) if impressions > 0 else 0

    return min(
        deviation_ratio * 0.5 + days_consistency * 0.3 + data_quality * 0.2,
        1.0,
    )


# =============================================================================
# DiagnosticEngine
# =============================================================================

class DiagnosticEngine:
    """Rules-based diagnostic engine for ad health assessment.

    Evaluates each ad against all registered rules. Rules with unmet
    prerequisites are skipped (not silently dropped). Produces per-ad
    health assessments with fired rules and kill recommendations.
    """

    def __init__(self, supabase_client):
        """Initialize with Supabase client and rule registry.

        Args:
            supabase_client: Supabase client instance.
        """
        self.supabase = supabase_client
        self._classifier = None  # Lazy init

        # Rule registry
        self.RULES: List[DiagnosticRule] = [
            DiagnosticRule("ctr_below_p25", "CTR Below 25th Percentile", "efficiency",
                          ["link_ctr"], _check_ctr_below_p25, min_impressions=500, min_days=3),
            DiagnosticRule("ctr_below_p10", "CTR Critically Low", "efficiency",
                          ["link_ctr"], _check_ctr_below_p10, min_impressions=500, min_days=5),
            DiagnosticRule("cpc_above_p75", "CPC Above 75th Percentile", "efficiency",
                          ["link_cpc", "link_clicks"], _check_cpc_above_p75, min_impressions=500, min_days=3),
            DiagnosticRule("roas_below_p25", "ROAS Below 25th Percentile", "efficiency",
                          ["roas"], _check_roas_below_p25, min_impressions=500, min_days=7),
            DiagnosticRule("frequency_above_threshold", "Frequency Above Threshold", "fatigue",
                          ["frequency"], _check_frequency_above_threshold, min_impressions=1000, min_days=5),
            DiagnosticRule("frequency_trend_rising", "Frequency Trending Upward", "fatigue",
                          ["frequency"], _check_frequency_trend_rising,
                          min_impressions=1000, min_days=7, aggregation="daily_series", window_days=7),
            DiagnosticRule("ctr_declining_7d", "CTR Declining Over 7 Days", "fatigue",
                          ["link_ctr"], _check_ctr_declining_7d,
                          min_impressions=500, min_days=7, aggregation="daily_series", window_days=7),
            DiagnosticRule("spend_no_conversions", "Spend Without Conversions", "efficiency",
                          ["total_spend", "total_conversions"], _check_spend_no_conversions,
                          min_impressions=500, min_days=5),
            DiagnosticRule("hook_rate_below_p25", "Low Hook Rate", "creative",
                          ["hook_rate"], _check_hook_rate_below_p25, min_impressions=500, min_days=3),
            DiagnosticRule("hold_rate_below_p25", "Low Hold Rate", "creative",
                          ["hold_rate"], _check_hold_rate_below_p25, min_impressions=500, min_days=3),
            DiagnosticRule("congruence_below_threshold", "Low Congruence", "creative",
                          ["congruence_score"], _check_congruence_below_threshold,
                          min_impressions=100, min_days=1),
            DiagnosticRule("impression_starvation", "Impression Starvation", "funnel",
                          ["impressions"], _check_impression_starvation,
                          min_impressions=0, min_days=3, aggregation="daily_series", window_days=3),
        ]

    @property
    def classifier(self):
        """Lazy-init classifier to avoid circular imports."""
        if self._classifier is None:
            from .classifier_service import ClassifierService
            self._classifier = ClassifierService(self.supabase)
        return self._classifier

    async def diagnose_ad(
        self,
        meta_ad_id: str,
        brand_id: UUID,
        run_id: UUID,
        run_created_at: datetime,
        baseline: Optional[BaselineSnapshot],
        run_config: RunConfig,
    ) -> AdDiagnostic:
        """Diagnose a single ad's health.

        Fetches classification via classifier.get_classification_for_run()
        (deterministic selection). Evaluates all rules. Computes overall health
        and kill recommendation.

        Args:
            meta_ad_id: Meta ad ID string.
            brand_id: Brand UUID.
            run_id: Analysis run UUID.
            run_created_at: When the run was created.
            baseline: Cohort baseline (may be None).
            run_config: Run configuration.

        Returns:
            AdDiagnostic model.
        """
        # Get classification (deterministic policy)
        classification = await self.classifier.get_classification_for_run(
            meta_ad_id, brand_id, run_id, run_created_at
        )

        if not classification or not classification.id:
            return AdDiagnostic(
                meta_ad_id=meta_ad_id,
                brand_id=brand_id,
                run_id=run_id,
                overall_health=HealthStatus.INSUFFICIENT_DATA,
                fired_rules=[],
            )

        # Prepare ad data for rules
        ad_data = await self._prepare_ad_data(
            meta_ad_id, brand_id, run_config, classification
        )

        # Evaluate all rules
        fired_rules: List[FiredRule] = []
        for rule in self.RULES:
            # Use appropriate aggregation view
            if rule.aggregation == "daily_series":
                data_view = await self._prepare_series_data(
                    meta_ad_id, brand_id, run_config, rule.window_days
                )
                # Merge total data for prerequisites check
                merged = {**ad_data, **data_view}
            else:
                merged = ad_data

            result = rule.evaluate(merged, baseline)
            if result is not None:
                fired_rules.append(result)

        # Determine overall health
        overall_health = self._determine_health(fired_rules)

        # Determine kill recommendation
        kill, kill_reason = self._determine_kill(fired_rules, ad_data, run_config)

        # Determine trend
        trend = self._determine_trend(ad_data)

        diagnostic = AdDiagnostic(
            meta_ad_id=meta_ad_id,
            brand_id=brand_id,
            run_id=run_id,
            overall_health=overall_health,
            kill_recommendation=kill,
            kill_reason=kill_reason,
            fired_rules=fired_rules,
            trend_direction=trend,
            days_analyzed=ad_data.get("days_with_data"),
            baseline_id=baseline.id if baseline else None,
            classification_id=classification.id,
        )

        # Store diagnostic
        await self._store_diagnostic(diagnostic, run_config)

        return diagnostic

    async def diagnose_account(
        self,
        brand_id: UUID,
        run_id: UUID,
        run_created_at: datetime,
        active_ad_ids: List[str],
        baselines: List[BaselineSnapshot],
        run_config: RunConfig,
    ) -> List[AdDiagnostic]:
        """Diagnose all active ads in an account.

        Args:
            brand_id: Brand UUID.
            run_id: Analysis run UUID.
            run_created_at: When the run was created.
            active_ad_ids: List of active meta ad IDs.
            baselines: Available baselines (selects best match per ad).
            run_config: Run configuration.

        Returns:
            List of AdDiagnostic models.
        """
        # Build baseline lookup for fallback
        brand_wide_baseline = None
        for b in baselines:
            if b.awareness_level == "all" and b.creative_format == "all":
                brand_wide_baseline = b
                break

        diagnostics = []
        for meta_ad_id in active_ad_ids:
            try:
                # Find best baseline for this ad
                from .baseline_service import BaselineService
                bs = BaselineService(self.supabase)
                baseline = await bs.get_baseline_for_ad(
                    meta_ad_id, brand_id,
                    date_range_start=run_config.thresholds.get("date_range_start"),
                    date_range_end=run_config.thresholds.get("date_range_end"),
                )
                if not baseline:
                    baseline = brand_wide_baseline

                diag = await self.diagnose_ad(
                    meta_ad_id, brand_id, run_id, run_created_at,
                    baseline, run_config
                )
                diagnostics.append(diag)
            except Exception as e:
                logger.error(f"Error diagnosing ad {meta_ad_id}: {e}")
                diagnostics.append(AdDiagnostic(
                    meta_ad_id=meta_ad_id,
                    brand_id=brand_id,
                    run_id=run_id,
                    overall_health=HealthStatus.INSUFFICIENT_DATA,
                    fired_rules=[],
                ))

        logger.info(f"Diagnosed {len(diagnostics)} ads for brand {brand_id}")
        return diagnostics

    # =========================================================================
    # Health & Kill Determination
    # =========================================================================

    def _determine_health(self, fired_rules: List[FiredRule]) -> HealthStatus:
        """Determine overall health from fired rules.

        Args:
            fired_rules: List of fired/skipped rules.

        Returns:
            HealthStatus enum value.
        """
        non_skipped = [r for r in fired_rules if not r.skipped]

        if not non_skipped:
            # All rules skipped
            all_skipped = all(r.skipped for r in fired_rules) if fired_rules else True
            return HealthStatus.INSUFFICIENT_DATA if all_skipped else HealthStatus.HEALTHY

        critical_count = sum(1 for r in non_skipped if r.severity == "critical")
        warning_count = sum(1 for r in non_skipped if r.severity == "warning")

        if critical_count > 0:
            return HealthStatus.CRITICAL
        elif warning_count >= 2:
            return HealthStatus.WARNING
        elif warning_count >= 1:
            return HealthStatus.WARNING
        else:
            return HealthStatus.HEALTHY

    def _determine_kill(
        self,
        fired_rules: List[FiredRule],
        ad_data: Dict[str, Any],
        run_config: RunConfig,
    ) -> Tuple[bool, Optional[str]]:
        """Determine if an ad should be killed.

        Kill conditions:
        - test_failure: CRITICAL efficiency + running > 7 days + spend > $100
        - fatigue: CRITICAL fatigue category
        - inefficient: zero conversions + spend > $200

        Args:
            fired_rules: List of fired rules.
            ad_data: Ad performance data.
            run_config: Run configuration.

        Returns:
            Tuple of (should_kill, reason).
        """
        non_skipped = [r for r in fired_rules if not r.skipped]
        total_spend = _safe_numeric(ad_data.get("total_spend")) or 0
        days = ad_data.get("days_with_data", 0)

        # Test failure
        critical_efficiency = any(
            r.severity == "critical" and r.category == "efficiency"
            for r in non_skipped
        )
        if critical_efficiency and days > 7 and total_spend > 100:
            return True, "test_failure"

        # Fatigue
        critical_fatigue = any(
            r.severity == "critical" and r.category == "fatigue"
            for r in non_skipped
        )
        if critical_fatigue:
            return True, "fatigue"

        # Inefficient
        total_conversions = ad_data.get("total_conversions") or 0
        if total_conversions == 0 and total_spend > 200:
            return True, "inefficient"

        return False, None

    def _determine_trend(self, ad_data: Dict[str, Any]) -> Optional[str]:
        """Determine ad performance trend direction.

        Args:
            ad_data: Ad performance data with daily series.

        Returns:
            Trend direction string or None.
        """
        ctr_series = ad_data.get("link_ctr_series", [])
        if not ctr_series or len(ctr_series) < 5:
            return None

        recent = [_safe_numeric(v) for v in ctr_series[-3:] if _safe_numeric(v) is not None]
        older = [_safe_numeric(v) for v in ctr_series[-7:-3] if _safe_numeric(v) is not None]

        if not recent or not older:
            return None

        recent_avg = sum(recent) / len(recent)
        older_avg = sum(older) / len(older)

        if older_avg == 0:
            return "stable"

        change = (recent_avg - older_avg) / older_avg

        if change > 0.1:
            return "improving"
        elif change < -0.1:
            return "declining"
        else:
            return "stable"

    # =========================================================================
    # Data Preparation
    # =========================================================================

    async def _prepare_ad_data(
        self,
        meta_ad_id: str,
        brand_id: UUID,
        run_config: RunConfig,
        classification: Optional[CreativeClassification] = None,
    ) -> Dict[str, Any]:
        """Prepare aggregated ad data for rule evaluation.

        Fetches performance data and computes total aggregates.

        Args:
            meta_ad_id: Meta ad ID.
            brand_id: Brand UUID.
            run_config: Run configuration.
            classification: Ad classification (for congruence score).

        Returns:
            Dict with aggregated metrics for rules.
        """
        date_range_end = run_config.thresholds.get("date_range_end", date.today())
        date_range_start = run_config.thresholds.get(
            "date_range_start",
            date_range_end - timedelta(days=run_config.days_back) if isinstance(date_range_end, date) else date.today() - timedelta(days=run_config.days_back)
        )

        try:
            result = self.supabase.table("meta_ads_performance").select("*").eq(
                "meta_ad_id", meta_ad_id
            ).eq(
                "brand_id", str(brand_id)
            ).gte(
                "date", date_range_start.isoformat() if isinstance(date_range_start, date) else str(date_range_start)
            ).lte(
                "date", date_range_end.isoformat() if isinstance(date_range_end, date) else str(date_range_end)
            ).order("date").execute()

            rows = result.data or []
        except Exception as e:
            logger.error(f"Error fetching performance data for {meta_ad_id}: {e}")
            rows = []

        if not rows:
            return {"days_with_data": 0, "total_impressions": 0}

        # Aggregate totals
        total_impressions = sum(_safe_numeric(r.get("impressions")) or 0 for r in rows)
        total_spend = sum(_safe_numeric(r.get("spend")) or 0 for r in rows)
        total_clicks = sum(_safe_numeric(r.get("link_clicks")) or 0 for r in rows)
        total_video_views = sum(_safe_numeric(r.get("video_views")) or 0 for r in rows)
        total_p25_watched = sum(_safe_numeric(r.get("video_p25_watched")) or 0 for r in rows)

        # Weighted averages
        link_ctr = (total_clicks / total_impressions * 100) if total_impressions > 0 else None
        link_cpc = (total_spend / total_clicks) if total_clicks > 0 else None
        frequency = _safe_numeric(rows[-1].get("frequency"))  # Use latest

        # Video rates
        hook_rate = (total_video_views / total_impressions) if total_impressions > 0 and total_video_views > 0 else None
        hold_rate = (total_p25_watched / total_video_views) if total_video_views > 0 and total_p25_watched > 0 else None

        # Conversions
        total_conversions = 0
        for r in rows:
            conv = extract_conversions(r, run_config.primary_conversion_event)
            if conv is not None:
                total_conversions += conv

        roas = compute_roas(
            {"spend": total_spend, "purchase_value": sum(
                _safe_numeric(r.get("purchase_value")) or 0 for r in rows
            ), "roas": None},
            run_config.value_field,
        )
        # Also try pre-extracted roas as fallback
        if roas is None:
            roas_values = [_safe_numeric(r.get("roas")) for r in rows if _safe_numeric(r.get("roas"))]
            if roas_values:
                roas = sum(roas_values) / len(roas_values)

        # Build daily series for trend rules
        ctr_series = []
        freq_series = []
        impr_series = []
        for r in rows:
            ctr_series.append(_safe_numeric(r.get("link_ctr")))
            freq_series.append(_safe_numeric(r.get("frequency")))
            impr_series.append(_safe_numeric(r.get("impressions")))

        data = {
            "days_with_data": len(rows),
            "total_impressions": total_impressions,
            "total_spend": total_spend,
            "total_clicks": total_clicks,
            "total_conversions": total_conversions,
            "link_ctr": link_ctr,
            "link_cpc": link_cpc,
            "link_clicks": total_clicks,
            "frequency": frequency,
            "roas": roas,
            "hook_rate": hook_rate,
            "hold_rate": hold_rate,
            "impressions": total_impressions,
            # Series
            "link_ctr_series": ctr_series,
            "frequency_series": freq_series,
            "impressions_series": impr_series,
        }

        # Add congruence from classification
        if classification and classification.congruence_score is not None:
            data["congruence_score"] = classification.congruence_score

        return data

    async def _prepare_series_data(
        self,
        meta_ad_id: str,
        brand_id: UUID,
        run_config: RunConfig,
        window_days: int,
    ) -> Dict[str, Any]:
        """Prepare daily series data for trend-based rules.

        Args:
            meta_ad_id: Meta ad ID.
            brand_id: Brand UUID.
            run_config: Run configuration.
            window_days: Trailing window in days.

        Returns:
            Dict with per-day metric arrays.
        """
        date_range_end = run_config.thresholds.get("date_range_end", date.today())
        if isinstance(date_range_end, str):
            date_range_end = date.fromisoformat(date_range_end)
        window_start = date_range_end - timedelta(days=window_days)

        try:
            result = self.supabase.table("meta_ads_performance").select(
                "date, link_ctr, frequency, impressions"
            ).eq(
                "meta_ad_id", meta_ad_id
            ).eq(
                "brand_id", str(brand_id)
            ).gte(
                "date", window_start.isoformat()
            ).lte(
                "date", date_range_end.isoformat()
            ).order("date").execute()

            rows = result.data or []
        except Exception as e:
            logger.warning(f"Error fetching series data for {meta_ad_id}: {e}")
            rows = []

        return {
            "link_ctr_series": [r.get("link_ctr") for r in rows],
            "frequency_series": [r.get("frequency") for r in rows],
            "impressions_series": [r.get("impressions") for r in rows],
        }

    # =========================================================================
    # Storage
    # =========================================================================

    async def _store_diagnostic(
        self,
        diagnostic: AdDiagnostic,
        run_config: RunConfig,
    ) -> None:
        """Store diagnostic result in database.

        Uses UNIQUE(meta_ad_id, brand_id, run_id) constraint.

        Args:
            diagnostic: AdDiagnostic to store.
            run_config: Run configuration.
        """
        if not diagnostic.classification_id:
            logger.warning(
                f"Skipping diagnostic storage for {diagnostic.meta_ad_id}: "
                f"no classification_id"
            )
            return

        try:
            record = {
                "organization_id": str(diagnostic.organization_id) if diagnostic.organization_id else None,
                "brand_id": str(diagnostic.brand_id),
                "meta_ad_id": diagnostic.meta_ad_id,
                "run_id": str(diagnostic.run_id),
                "overall_health": diagnostic.overall_health.value,
                "kill_recommendation": diagnostic.kill_recommendation,
                "kill_reason": diagnostic.kill_reason,
                "fired_rules": [r.model_dump() for r in diagnostic.fired_rules],
                "trend_direction": diagnostic.trend_direction,
                "days_analyzed": diagnostic.days_analyzed,
                "baseline_id": str(diagnostic.baseline_id) if diagnostic.baseline_id else None,
                "classification_id": str(diagnostic.classification_id),
            }

            self.supabase.table("ad_intelligence_diagnostics").upsert(
                record,
                on_conflict="meta_ad_id,brand_id,run_id",
            ).execute()

        except Exception as e:
            logger.error(f"Error storing diagnostic for {diagnostic.meta_ad_id}: {e}")
