"""AdIntelligenceService: Orchestration facade for the 4-layer system.

Wires together classifier, baseline, diagnostic, recommendation, fatigue,
coverage, and congruence services. Manages run lifecycle (create → execute
→ complete/fail). Added to AgentDependencies for tool access.
"""

from __future__ import annotations

import logging
from datetime import date, datetime, timedelta, timezone
from typing import Any, Dict, List, Optional
from uuid import UUID

from .baseline_service import BaselineService
from .classifier_service import ClassifierService
from .congruence_analyzer import CongruenceAnalyzer
from .congruence_checker import CongruenceChecker
from .coverage_analyzer import CoverageAnalyzer
from .diagnostic_engine import DiagnosticEngine
from .fatigue_detector import FatigueDetector
from .helpers import get_active_ad_ids, validate_org_brand, _safe_numeric
from ..video_analysis_service import VideoAnalysisService
from .models import (
    AccountAnalysisResult,
    AnalysisRun,
    FiredRule,
    Recommendation,
    RecommendationStatus,
    RunConfig,
)
from .recommendation_service import RecommendationService

logger = logging.getLogger(__name__)


class AdIntelligenceService:
    """Orchestration facade for ad intelligence analysis.

    Coordinates the 4-layer pipeline:
    1. Classification (awareness level + format)
    2. Baselines (cohort percentile benchmarks)
    3. Diagnostics (rules-based health assessment)
    4. Recommendations (actionable suggestions)

    Plus standalone analyses: fatigue, coverage, congruence.
    """

    def __init__(self, supabase_client, gemini_service=None, meta_ads_service=None):
        """Initialize all sub-services.

        Args:
            supabase_client: Supabase client instance.
            gemini_service: Optional GeminiService instance with configured
                rate limiting and usage tracking. Passed through to
                ClassifierService for Gemini API calls.
            meta_ads_service: Optional MetaAdsService instance for fetching
                video source URLs. Passed through to ClassifierService for
                video classification.
        """
        self.supabase = supabase_client

        # Create video analysis service for deep video analysis with hooks
        video_analysis_service = VideoAnalysisService(supabase_client)

        # Create congruence analyzer for per-dimension congruence evaluation
        congruence_analyzer = CongruenceAnalyzer(gemini_service)

        self.classifier = ClassifierService(
            supabase_client,
            gemini_service=gemini_service,
            meta_ads_service=meta_ads_service,
            video_analysis_service=video_analysis_service,
            congruence_analyzer=congruence_analyzer,
        )
        self.baselines = BaselineService(supabase_client)
        self.diagnostics = DiagnosticEngine(supabase_client)
        self.recommendations = RecommendationService(supabase_client)
        self.fatigue = FatigueDetector(supabase_client)
        self.coverage = CoverageAnalyzer(supabase_client)
        self.congruence = CongruenceChecker(supabase_client)

        logger.info("AdIntelligenceService initialized")

    async def create_run(
        self,
        brand_id: UUID,
        org_id: UUID,
        config: Optional[RunConfig] = None,
        goal: Optional[str] = None,
        triggered_by: Optional[UUID] = None,
    ) -> AnalysisRun:
        """Create a new analysis run.

        Validates org/brand relationship first. All downstream operations
        inherit the validated pair.

        Args:
            brand_id: Brand UUID.
            org_id: Organization UUID.
            config: Run configuration (defaults provided).
            goal: Analysis goal (lower_cpa, scale, stability, etc.).
            triggered_by: User UUID who triggered the run.

        Returns:
            AnalysisRun model with populated ID.

        Raises:
            ValueError: If brand doesn't belong to org.
        """
        # Validate org/brand relationship
        await validate_org_brand(self.supabase, org_id, brand_id)

        if config is None:
            config = RunConfig()

        now = datetime.now(timezone.utc)
        date_range_end = now.date()
        date_range_start = date_range_end - timedelta(days=config.days_back)

        record = {
            "organization_id": str(org_id),
            "brand_id": str(brand_id),
            "date_range_start": date_range_start.isoformat(),
            "date_range_end": date_range_end.isoformat(),
            "goal": goal,
            "triggered_by": str(triggered_by) if triggered_by else None,
            "config": config.model_dump(),
            "status": "running",
        }

        result = self.supabase.table("ad_intelligence_runs").insert(record).execute()

        if not result.data:
            raise RuntimeError("Failed to create analysis run")

        run_data = result.data[0]
        run = AnalysisRun(
            id=UUID(run_data["id"]),
            organization_id=org_id,
            brand_id=brand_id,
            date_range_start=date_range_start,
            date_range_end=date_range_end,
            goal=goal,
            triggered_by=triggered_by,
            config=config,
            status="running",
            created_at=run_data.get("created_at"),
        )

        logger.info(f"Created analysis run {run.id} for brand {brand_id}")
        return run

    async def full_analysis(
        self,
        brand_id: UUID,
        org_id: UUID,
        config: Optional[RunConfig] = None,
        goal: Optional[str] = None,
        triggered_by: Optional[UUID] = None,
    ) -> AccountAnalysisResult:
        """Run the complete 4-layer analysis pipeline.

        Creates run → filters active ads → classifies → computes baselines
        → diagnoses → generates recommendations → completes run.

        Args:
            brand_id: Brand UUID.
            org_id: Organization UUID.
            config: Run configuration.
            goal: Analysis goal.
            triggered_by: User UUID.

        Returns:
            AccountAnalysisResult with full analysis summary.
        """
        if config is None:
            config = RunConfig()

        run = await self.create_run(brand_id, org_id, config, goal, triggered_by)

        try:
            # Store date range in config thresholds for downstream access
            config.thresholds["date_range_start"] = run.date_range_start
            config.thresholds["date_range_end"] = run.date_range_end

            # 1. Get active ads (narrow window first, fallback to full analysis window)
            active_ids = await get_active_ad_ids(
                self.supabase,
                brand_id,
                run.date_range_end,
                config.active_window_days,
            )

            if not active_ids and config.active_window_days < config.days_back:
                logger.info(
                    f"No active ads in {config.active_window_days}-day window, "
                    f"falling back to full {config.days_back}-day analysis window"
                )
                active_ids = await get_active_ad_ids(
                    self.supabase,
                    brand_id,
                    run.date_range_end,
                    config.days_back,
                )

            if not active_ids:
                await self._complete_run(run.id, "completed", {
                    "total_ads": 0, "active_ads": 0,
                    "classified": 0, "diagnosed": 0,
                    "recs_generated": 0,
                })
                brand_name = await self._get_brand_name(brand_id)
                return AccountAnalysisResult(
                    run_id=run.id,
                    brand_name=brand_name,
                    date_range=f"Last {config.days_back} days",
                    total_ads=0,
                    active_ads=0,
                    total_spend=0,
                )

            # 2. Classify active ads
            classifications = await self.classifier.classify_batch(
                brand_id, org_id, run.id, active_ids,
                max_new=config.max_classifications_per_run,
                max_video=config.max_video_classifications_per_run,
            )

            # 3. Compute baselines
            baselines = await self.baselines.compute_baselines(
                brand_id, config,
                run.date_range_start, run.date_range_end,
                org_id=org_id, run_id=run.id,
            )

            # 4. Diagnose all ads
            diagnostics_list = await self.diagnostics.diagnose_account(
                brand_id, org_id, run.id,
                datetime.fromisoformat(run.created_at) if isinstance(run.created_at, str) else run.created_at or datetime.now(timezone.utc),
                active_ids, baselines, config,
            )

            # 5. Generate recommendations
            recs = await self.recommendations.generate_recommendations(
                brand_id, org_id, run.id, diagnostics_list,
            )

            # 6. Build result
            brand_name = await self._get_brand_name(brand_id)
            total_spend = await self._get_total_spend(
                brand_id, run.date_range_start, run.date_range_end
            )

            # Compute distributions
            awareness_dist: Dict[str, int] = {}
            format_dist: Dict[str, int] = {}
            for cls in classifications:
                level = cls.creative_awareness_level
                if level:
                    lvl_val = level.value if hasattr(level, "value") else level
                    awareness_dist[lvl_val] = awareness_dist.get(lvl_val, 0) + 1
                fmt = cls.creative_format
                if fmt:
                    fmt_val = fmt.value if hasattr(fmt, "value") else fmt
                    format_dist[fmt_val] = format_dist.get(fmt_val, 0) + 1

            health_dist: Dict[str, int] = {}
            healthy_ad_ids: List[str] = []
            for diag in diagnostics_list:
                health = diag.overall_health.value if hasattr(diag.overall_health, "value") else diag.overall_health
                health_dist[health] = health_dist.get(health, 0) + 1
                if health == "healthy":
                    healthy_ad_ids.append(diag.meta_ad_id)

            # Top issues (non-skipped, deduplicated by rule_id, with affected ad IDs)
            rule_ad_map: Dict[str, List[str]] = {}  # rule_id -> list of meta_ad_ids
            rule_samples: Dict[str, FiredRule] = {}  # rule_id -> sample FiredRule
            for diag in diagnostics_list:
                for rule in diag.fired_rules:
                    if not rule.skipped:
                        if rule.rule_id not in rule_samples:
                            rule_samples[rule.rule_id] = rule
                            rule_ad_map[rule.rule_id] = []
                        rule_ad_map[rule.rule_id].append(diag.meta_ad_id)

            all_rules: List[FiredRule] = []
            for rule_id, sample_rule in rule_samples.items():
                enriched = sample_rule.model_copy(
                    update={"affected_ad_ids": rule_ad_map[rule_id]}
                )
                all_rules.append(enriched)

            top_issues = sorted(
                all_rules,
                key=lambda r: {"critical": 3, "warning": 2, "info": 1}.get(r.severity, 0),
                reverse=True,
            )[:5]

            pending_recs = sum(1 for r in recs if r.status == RecommendationStatus.PENDING or r.status == "pending")
            critical_recs = sum(1 for r in recs if r.priority == "critical")

            # Extract baseline metrics by awareness level (format="all" cohorts)
            awareness_baselines: Dict[str, Dict[str, Optional[float]]] = {}
            for baseline in baselines:
                if baseline.creative_format == "all" and baseline.awareness_level != "all":
                    awareness_baselines[baseline.awareness_level] = {
                        "cpm": baseline.median_cpm,
                        "ctr": baseline.median_ctr,
                        "cpa": baseline.median_cost_per_purchase,
                        "cost_per_atc": baseline.median_cost_per_add_to_cart,
                    }

            # Compute aggregate metrics by awareness level
            awareness_aggregates = await self._compute_awareness_aggregates(
                brand_id, run.date_range_start, run.date_range_end, classifications
            )

            # Compute aggregate metrics by (awareness, format)
            format_aggregates = await self._compute_format_aggregates(
                brand_id, run.date_range_start, run.date_range_end, classifications
            )

            # Extract format-level baseline CPAs from baselines
            format_baselines: Dict[str, float] = {}
            for baseline in baselines:
                if baseline.creative_format != "all" and baseline.awareness_level != "all":
                    key = f"{baseline.awareness_level}|{baseline.creative_format}"
                    if baseline.median_cost_per_purchase is not None:
                        format_baselines[key] = baseline.median_cost_per_purchase

            # Generate creative strategy insights
            creative_insights = self._generate_creative_insights(
                awareness_aggregates, awareness_baselines, format_aggregates, format_baselines
            )

            # Complete run
            summary = {
                "total_ads": len(active_ids),
                "active_ads": len(active_ids),
                "classified": len(classifications),
                "diagnosed": len(diagnostics_list),
                "recs_generated": len(recs),
            }
            await self._complete_run(run.id, "completed", summary)

            return AccountAnalysisResult(
                run_id=run.id,
                brand_name=brand_name,
                date_range=f"Last {config.days_back} days",
                total_ads=len(active_ids),
                active_ads=len(active_ids),
                total_spend=total_spend,
                awareness_distribution=awareness_dist,
                format_distribution=format_dist,
                health_distribution=health_dist,
                healthy_ad_ids=healthy_ad_ids,
                top_issues=top_issues,
                pending_recommendations=pending_recs,
                critical_recommendations=critical_recs,
                recommendations=recs,
                awareness_baselines=awareness_baselines,
                awareness_aggregates=awareness_aggregates,
                format_aggregates=format_aggregates,
                creative_insights=creative_insights,
            )

        except Exception as e:
            logger.error(f"Full analysis failed for brand {brand_id}: {e}")
            await self._complete_run(run.id, "failed", error_message=str(e))
            raise

    async def get_recommendation_inbox(
        self,
        brand_id: UUID,
        run_id: Optional[UUID] = None,
        **filters,
    ) -> List[Recommendation]:
        """Get recommendation inbox for a brand.

        Args:
            brand_id: Brand UUID.
            run_id: Optional specific run UUID.
            **filters: Additional filters (status, category, priority, limit).

        Returns:
            List of Recommendation models.
        """
        return await self.recommendations.get_inbox(
            brand_id, run_id=run_id, **filters
        )

    async def get_latest_run(
        self,
        brand_id: UUID,
    ) -> Optional[AnalysisRun]:
        """Get the latest analysis run for a brand.

        Args:
            brand_id: Brand UUID.

        Returns:
            AnalysisRun or None.
        """
        try:
            result = self.supabase.table("ad_intelligence_runs").select("*").eq(
                "brand_id", str(brand_id)
            ).order(
                "created_at", desc=True
            ).limit(1).execute()

            if result.data:
                row = result.data[0]
                return AnalysisRun(
                    id=UUID(row["id"]),
                    organization_id=UUID(row["organization_id"]),
                    brand_id=UUID(row["brand_id"]),
                    date_range_start=row.get("date_range_start", date.today()),
                    date_range_end=row.get("date_range_end", date.today()),
                    goal=row.get("goal"),
                    triggered_by=UUID(row["triggered_by"]) if row.get("triggered_by") else None,
                    config=RunConfig(**row["config"]) if row.get("config") else RunConfig(),
                    status=row.get("status", "running"),
                    summary=row.get("summary"),
                    error_message=row.get("error_message"),
                    created_at=row.get("created_at"),
                    completed_at=row.get("completed_at"),
                )
        except Exception as e:
            logger.warning(f"Error fetching latest run: {e}")
        return None

    async def handle_rec_done(
        self,
        rec_id: UUID,
        user_id: Optional[UUID] = None,
    ) -> Recommendation:
        """Mark a recommendation as acted on.

        Args:
            rec_id: Recommendation UUID.
            user_id: Acting user UUID.

        Returns:
            Updated Recommendation.
        """
        return await self.recommendations.update_status(
            rec_id, RecommendationStatus.ACTED_ON, user_id=user_id
        )

    async def handle_rec_ignore(
        self,
        rec_id: UUID,
        user_id: Optional[UUID] = None,
    ) -> Recommendation:
        """Mark a recommendation as ignored.

        Args:
            rec_id: Recommendation UUID.
            user_id: Acting user UUID.

        Returns:
            Updated Recommendation.
        """
        return await self.recommendations.update_status(
            rec_id, RecommendationStatus.IGNORED, user_id=user_id
        )

    async def handle_rec_note(
        self,
        rec_id: UUID,
        note: str,
        user_id: Optional[UUID] = None,
    ) -> Recommendation:
        """Add a note to a recommendation.

        Args:
            rec_id: Recommendation UUID.
            note: User note text.
            user_id: Acting user UUID.

        Returns:
            Updated Recommendation.
        """
        return await self.recommendations.update_status(
            rec_id, RecommendationStatus.ACKNOWLEDGED, note=note, user_id=user_id
        )

    async def search_brands(self, query: str) -> list:
        """Search brands by name (case-insensitive partial match).

        Args:
            query: Brand name or partial name.

        Returns:
            List of dicts with id, name, organization_id.
        """
        try:
            result = self.supabase.table("brands").select(
                "id, name, organization_id"
            ).ilike(
                "name", f"%{query}%"
            ).limit(10).execute()
            return result.data or []
        except Exception as e:
            logger.warning(f"Error searching brands: {e}")
            return []

    # =========================================================================
    # Private Helpers
    # =========================================================================

    async def _complete_run(
        self,
        run_id: UUID,
        status: str,
        summary: Optional[Dict[str, Any]] = None,
        error_message: Optional[str] = None,
    ) -> None:
        """Update run status to completed or failed.

        Args:
            run_id: Run UUID.
            status: New status ("completed" or "failed").
            summary: Run summary dict.
            error_message: Error message if failed.
        """
        try:
            update = {
                "status": status,
                "completed_at": datetime.now(timezone.utc).isoformat(),
            }
            if summary:
                update["summary"] = summary
            if error_message:
                update["error_message"] = error_message

            self.supabase.table("ad_intelligence_runs").update(update).eq(
                "id", str(run_id)
            ).execute()
        except Exception as e:
            logger.error(f"Error completing run {run_id}: {e}")

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

    async def _get_total_spend(
        self,
        brand_id: UUID,
        date_range_start: date,
        date_range_end: date,
    ) -> float:
        """Get total spend for a brand in a date range.

        Uses pagination to ensure all rows are counted (Supabase default limit is 1000).

        Args:
            brand_id: Brand UUID.
            date_range_start: Start date.
            date_range_end: End date.

        Returns:
            Total spend as float.
        """
        try:
            total = 0.0
            offset = 0
            page_size = 1000

            while True:
                result = self.supabase.table("meta_ads_performance").select(
                    "spend"
                ).eq(
                    "brand_id", str(brand_id)
                ).gte(
                    "date", date_range_start.isoformat()
                ).lte(
                    "date", date_range_end.isoformat()
                ).range(offset, offset + page_size - 1).execute()

                if not result.data:
                    break

                for row in result.data:
                    spend = _safe_numeric(row.get("spend"))
                    if spend:
                        total += spend

                if len(result.data) < page_size:
                    break

                offset += page_size

            return round(total, 2)
        except Exception as e:
            logger.warning(f"Error fetching total spend: {e}")
            return 0.0

    async def _compute_awareness_aggregates(
        self,
        brand_id: UUID,
        date_range_start: date,
        date_range_end: date,
        classifications: List[CreativeClassification],
    ) -> Dict[str, Dict[str, Optional[float]]]:
        """Compute aggregate metrics (totals) by awareness level.

        Uses pagination to ensure all rows are counted (Supabase default limit is 1000).

        Args:
            brand_id: Brand UUID.
            date_range_start: Start date.
            date_range_end: End date.
            classifications: List of classifications to get awareness levels from.

        Returns:
            Dict mapping awareness level to {spend, purchases, clicks, conversion_rate}.
        """
        # Build map of ad_id -> awareness_level from classifications
        ad_awareness: Dict[str, str] = {}
        for clf in classifications:
            if clf.creative_awareness_level:
                level = clf.creative_awareness_level.value if hasattr(
                    clf.creative_awareness_level, "value"
                ) else clf.creative_awareness_level
                ad_awareness[clf.meta_ad_id] = level

        if not ad_awareness:
            return {}

        # Query performance data for these ads with pagination
        try:
            agg: Dict[str, Dict[str, float]] = {}
            ad_ids = list(ad_awareness.keys())
            offset = 0
            page_size = 1000

            while True:
                result = self.supabase.table("meta_ads_performance").select(
                    "meta_ad_id, spend, purchases, link_clicks"
                ).eq(
                    "brand_id", str(brand_id)
                ).gte(
                    "date", date_range_start.isoformat()
                ).lte(
                    "date", date_range_end.isoformat()
                ).in_(
                    "meta_ad_id", ad_ids
                ).range(offset, offset + page_size - 1).execute()

                if not result.data:
                    break

                # Aggregate by awareness level
                for row in result.data:
                    ad_id = row.get("meta_ad_id")
                    level = ad_awareness.get(ad_id)
                    if not level:
                        continue

                    if level not in agg:
                        agg[level] = {"spend": 0.0, "purchases": 0, "clicks": 0}

                    spend = _safe_numeric(row.get("spend"))
                    purchases = _safe_numeric(row.get("purchases"))
                    clicks = _safe_numeric(row.get("link_clicks"))

                    if spend:
                        agg[level]["spend"] += spend
                    if purchases:
                        agg[level]["purchases"] += purchases
                    if clicks:
                        agg[level]["clicks"] += clicks

                if len(result.data) < page_size:
                    break

                offset += page_size

            # Compute conversion rate, CPA, and format results
            result_dict: Dict[str, Dict[str, Optional[float]]] = {}
            for level, metrics in agg.items():
                clicks = metrics["clicks"]
                purchases = metrics["purchases"]
                spend = metrics["spend"]
                conv_rate = (purchases / clicks * 100) if clicks > 0 else None
                cpa = (spend / purchases) if purchases > 0 else None
                result_dict[level] = {
                    "spend": round(spend, 2),
                    "purchases": int(purchases),
                    "clicks": int(clicks),
                    "conversion_rate": round(conv_rate, 2) if conv_rate else None,
                    "cpa": round(cpa, 2) if cpa else None,
                }

            return result_dict

        except Exception as e:
            logger.warning(f"Error computing awareness aggregates: {e}")
            return {}

    async def _compute_format_aggregates(
        self,
        brand_id: UUID,
        date_range_start: date,
        date_range_end: date,
        classifications: List[CreativeClassification],
    ) -> Dict[str, Dict[str, Any]]:
        """Compute aggregate metrics by (awareness level, creative format).

        Groups performance data by awareness level and creative format to enable
        format-level CPA comparisons within each awareness level.

        Args:
            brand_id: Brand UUID.
            date_range_start: Start date.
            date_range_end: End date.
            classifications: List of classifications with awareness and format.

        Returns:
            Dict mapping "awareness|format" keys to {spend, purchases, clicks, cpa}.
        """
        # Build map of ad_id -> (awareness_level, format)
        ad_classification: Dict[str, tuple] = {}
        for clf in classifications:
            if clf.creative_awareness_level and clf.creative_format:
                awareness = clf.creative_awareness_level.value if hasattr(
                    clf.creative_awareness_level, "value"
                ) else clf.creative_awareness_level
                fmt = clf.creative_format.value if hasattr(
                    clf.creative_format, "value"
                ) else clf.creative_format
                ad_classification[clf.meta_ad_id] = (awareness, fmt)

        if not ad_classification:
            return {}

        # Query performance data with pagination
        try:
            agg: Dict[str, Dict[str, float]] = {}
            ad_ids = list(ad_classification.keys())
            offset = 0
            page_size = 1000

            while True:
                result = self.supabase.table("meta_ads_performance").select(
                    "meta_ad_id, spend, purchases, link_clicks"
                ).eq(
                    "brand_id", str(brand_id)
                ).gte(
                    "date", date_range_start.isoformat()
                ).lte(
                    "date", date_range_end.isoformat()
                ).in_(
                    "meta_ad_id", ad_ids
                ).range(offset, offset + page_size - 1).execute()

                if not result.data:
                    break

                for row in result.data:
                    ad_id = row.get("meta_ad_id")
                    classification = ad_classification.get(ad_id)
                    if not classification:
                        continue

                    awareness, fmt = classification
                    key = f"{awareness}|{fmt}"

                    if key not in agg:
                        agg[key] = {"spend": 0.0, "purchases": 0, "clicks": 0}

                    spend = _safe_numeric(row.get("spend"))
                    purchases = _safe_numeric(row.get("purchases"))
                    clicks = _safe_numeric(row.get("link_clicks"))

                    if spend:
                        agg[key]["spend"] += spend
                    if purchases:
                        agg[key]["purchases"] += purchases
                    if clicks:
                        agg[key]["clicks"] += clicks

                if len(result.data) < page_size:
                    break

                offset += page_size

            # Compute CPA and format results
            result_dict: Dict[str, Dict[str, Any]] = {}
            for key, metrics in agg.items():
                purchases = metrics["purchases"]
                spend = metrics["spend"]
                cpa = (spend / purchases) if purchases > 0 else None
                result_dict[key] = {
                    "spend": round(spend, 2),
                    "purchases": int(purchases),
                    "clicks": int(metrics["clicks"]),
                    "cpa": round(cpa, 2) if cpa else None,
                }

            return result_dict

        except Exception as e:
            logger.warning(f"Error computing format aggregates: {e}")
            return {}

    def _generate_creative_insights(
        self,
        awareness_aggregates: Dict[str, Dict[str, Any]],
        awareness_baselines: Dict[str, Dict[str, Optional[float]]],
        format_aggregates: Dict[str, Dict[str, Any]],
        format_baselines: Dict[str, float],
    ) -> List[str]:
        """Generate creative strategy insights by comparing aggregate vs median CPA.

        Identifies:
        - High CPA gaps (aggregate >> median) → outlier ads dragging up costs
        - Format performance differences within awareness levels
        - Low-data areas needing more testing

        Args:
            awareness_aggregates: Aggregate metrics by awareness level.
            awareness_baselines: Baseline (median) metrics by awareness level.
            format_aggregates: Aggregate metrics by "awareness|format" key.
            format_baselines: Baseline CPA by "awareness|format" key.

        Returns:
            List of insight strings for display.
        """
        insights: List[str] = []

        # 1. High CPA gap analysis by awareness level
        for level, agg in awareness_aggregates.items():
            agg_cpa = agg.get("cpa")
            baseline = awareness_baselines.get(level, {})
            median_cpa = baseline.get("cpa")

            if agg_cpa is not None and median_cpa is not None and median_cpa > 0:
                gap = agg_cpa - median_cpa
                gap_pct = (gap / median_cpa) * 100

                if gap_pct > 50:
                    level_display = level.replace("_", " ").title()
                    insights.append(
                        f"High CPA gap at {level_display}: +${gap:.2f} vs median "
                        f"(${agg_cpa:.2f} actual vs ${median_cpa:.2f} median, +{gap_pct:.0f}%). "
                        f"Outlier ads may be dragging up costs."
                    )
                elif gap_pct > 30:
                    level_display = level.replace("_", " ").title()
                    insights.append(
                        f"Moderate CPA gap at {level_display}: +${gap:.2f} vs median "
                        f"(${agg_cpa:.2f} actual vs ${median_cpa:.2f} median). "
                        f"Consider pausing low performers."
                    )

        # 2. Format comparison within awareness levels
        # Group format_aggregates by awareness level
        awareness_formats: Dict[str, List[tuple]] = {}
        for key, metrics in format_aggregates.items():
            parts = key.split("|")
            if len(parts) == 2:
                awareness, fmt = parts
                if awareness not in awareness_formats:
                    awareness_formats[awareness] = []
                cpa = metrics.get("cpa")
                purchases = metrics.get("purchases", 0)
                if cpa is not None and purchases >= 3:  # Min threshold
                    awareness_formats[awareness].append((fmt, cpa, purchases))

        for awareness, formats in awareness_formats.items():
            if len(formats) < 2:
                continue

            # Sort by CPA ascending (best first)
            formats_sorted = sorted(formats, key=lambda x: x[1])
            best_fmt, best_cpa, best_purchases = formats_sorted[0]
            worst_fmt, worst_cpa, worst_purchases = formats_sorted[-1]

            # Only report if significant difference (>30%)
            if worst_cpa > best_cpa * 1.3:
                awareness_display = awareness.replace("_", " ").title()
                best_display = best_fmt.replace("_", " ").title()
                worst_display = worst_fmt.replace("_", " ").title()
                insights.append(
                    f"Format opportunity at {awareness_display}: {best_display} "
                    f"(${best_cpa:.2f} CPA) outperforming {worst_display} "
                    f"(${worst_cpa:.2f} CPA). Consider shifting budget."
                )

        # 3. Low-data areas needing more testing
        for level, agg in awareness_aggregates.items():
            purchases = agg.get("purchases", 0)
            baseline = awareness_baselines.get(level, {})
            median_cpa = baseline.get("cpa")

            if purchases < 5 and purchases > 0:
                level_display = level.replace("_", " ").title()
                if median_cpa is None:
                    insights.append(
                        f"Low data at {level_display}: Only {purchases} purchases. "
                        f"No baseline established - need more testing."
                    )
                else:
                    insights.append(
                        f"Low data at {level_display}: Only {purchases} purchases. "
                        f"Results may not be statistically significant."
                    )

        return insights