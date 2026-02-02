"""Layer 4: RecommendationService — Actionable recommendations with feedback.

Generates recommendations from diagnostic results, manages human feedback
(done/ignore/note), and provides outcome tracking seam.
"""

from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional
from uuid import UUID

from .helpers import _safe_numeric
from .models import (
    AdDiagnostic,
    AffectedAd,
    EvidencePoint,
    FiredRule,
    HealthStatus,
    Recommendation,
    RecommendationCategory,
    RecommendationStatus,
)

logger = logging.getLogger(__name__)


class RecommendationService:
    """Generates and manages actionable recommendations.

    Recommendation categories:
    - kill: Pause underperforming ads
    - scale: Increase budget on winners
    - iterate: Create variations of working ads
    - test: Launch new tests for gaps
    - refresh: Update fatigued creatives
    - coverage_gap: Fill funnel gaps
    - congruence_fix: Fix awareness level misalignment
    - budget_realloc: Redistribute budget
    - creative_test: Test new creative approaches
    """

    def __init__(self, supabase_client):
        """Initialize with Supabase client.

        Args:
            supabase_client: Supabase client instance.
        """
        self.supabase = supabase_client

    async def generate_recommendations(
        self,
        brand_id: UUID,
        org_id: UUID,
        run_id: UUID,
        diagnostics: List[AdDiagnostic],
    ) -> List[Recommendation]:
        """Generate recommendations from diagnostic results.

        Groups diagnostics by pattern and generates actionable recs
        with evidence, affected ads, and suggested actions.

        Args:
            brand_id: Brand UUID.
            org_id: Organization UUID.
            run_id: Analysis run UUID.
            diagnostics: List of AdDiagnostic results.

        Returns:
            List of Recommendation models (stored in DB).
        """
        recommendations: List[Recommendation] = []

        # Categorize diagnostics
        kill_ads = [d for d in diagnostics if d.kill_recommendation]
        critical_ads = [d for d in diagnostics if d.overall_health == HealthStatus.CRITICAL and not d.kill_recommendation]
        warning_ads = [d for d in diagnostics if d.overall_health == HealthStatus.WARNING]
        healthy_ads = [d for d in diagnostics if d.overall_health == HealthStatus.HEALTHY]

        # Generate kill recommendations
        for diag in kill_ads:
            rec = self._generate_kill_rec(diag, brand_id, org_id, run_id)
            if rec:
                recommendations.append(rec)

        # Group critical issues by rule category
        critical_by_rule = self._group_by_top_rule(critical_ads)
        for rule_id, diags in critical_by_rule.items():
            rec = self._generate_issue_rec(
                diags, rule_id, brand_id, org_id, run_id, priority="high"
            )
            if rec:
                recommendations.append(rec)

        # Group warning issues by rule category
        warning_by_rule = self._group_by_top_rule(warning_ads)
        for rule_id, diags in warning_by_rule.items():
            rec = self._generate_issue_rec(
                diags, rule_id, brand_id, org_id, run_id, priority="medium"
            )
            if rec:
                recommendations.append(rec)

        # Scale recommendation for healthy top-performers
        if healthy_ads:
            scale_rec = self._generate_scale_rec(healthy_ads, brand_id, org_id, run_id)
            if scale_rec:
                recommendations.append(scale_rec)

        # Store all recommendations
        for rec in recommendations:
            await self._store_recommendation(rec)

        logger.info(f"Generated {len(recommendations)} recommendations for run {run_id}")
        return recommendations

    async def get_inbox(
        self,
        brand_id: UUID,
        run_id: Optional[UUID] = None,
        status: Optional[List[str]] = None,
        category: Optional[str] = None,
        priority: Optional[str] = None,
        limit: int = 50,
    ) -> List[Recommendation]:
        """Get recommendation inbox for a brand.

        If run_id is None, defaults to the latest completed run.

        Args:
            brand_id: Brand UUID.
            run_id: Specific run UUID (optional).
            status: Filter by status list (e.g., ["pending"]).
            category: Filter by category.
            priority: Filter by priority.
            limit: Max results.

        Returns:
            List of Recommendation models.
        """
        # Default to latest completed run
        if not run_id:
            run_id = await self._get_latest_run_id(brand_id)
            if not run_id:
                return []

        query = self.supabase.table("ad_intelligence_recommendations").select(
            "*"
        ).eq(
            "brand_id", str(brand_id)
        ).eq(
            "run_id", str(run_id)
        )

        if status:
            query = query.in_("status", status)
        if category:
            query = query.eq("category", category)
        if priority:
            query = query.eq("priority", priority)

        result = query.order("created_at", desc=True).limit(limit).execute()

        return [self._row_to_model(r) for r in result.data or []]

    async def update_status(
        self,
        rec_id: UUID,
        status: RecommendationStatus,
        note: Optional[str] = None,
        user_id: Optional[UUID] = None,
    ) -> Recommendation:
        """Update recommendation status and optional note.

        Args:
            rec_id: Recommendation UUID.
            status: New status.
            note: Optional user note.
            user_id: UUID of the acting user.

        Returns:
            Updated Recommendation model.
        """
        update = {
            "status": status.value if isinstance(status, RecommendationStatus) else status,
            "acted_at": datetime.now(timezone.utc).isoformat(),
        }
        if note:
            update["user_note"] = note
        if user_id:
            update["acted_by"] = str(user_id)

        result = self.supabase.table("ad_intelligence_recommendations").update(
            update
        ).eq(
            "id", str(rec_id)
        ).execute()

        if result.data:
            return self._row_to_model(result.data[0])

        logger.error(f"Failed to update recommendation {rec_id}")
        return Recommendation(
            id=rec_id,
            brand_id=UUID(int=0),
            run_id=UUID(int=0),
            title="Unknown",
            category=RecommendationCategory.KILL,
            priority="medium",
            confidence=0,
            summary="Update failed",
            action_description="",
            action_type="no_action",
            status=status if isinstance(status, RecommendationStatus) else RecommendationStatus(status),
        )

    async def record_outcome(
        self,
        rec_id: UUID,
        outcome_data: Dict[str, Any],
    ) -> None:
        """Record outcome measurement for a recommendation.

        Args:
            rec_id: Recommendation UUID.
            outcome_data: Outcome measurement dict.
        """
        try:
            self.supabase.table("ad_intelligence_recommendations").update({
                "outcome_measured_at": datetime.now(timezone.utc).isoformat(),
                "outcome_data": outcome_data,
            }).eq(
                "id", str(rec_id)
            ).execute()
        except Exception as e:
            logger.error(f"Error recording outcome for {rec_id}: {e}")

    # =========================================================================
    # Recommendation Generators
    # =========================================================================

    def _generate_kill_rec(
        self,
        diag: AdDiagnostic,
        brand_id: UUID,
        org_id: UUID,
        run_id: UUID,
    ) -> Optional[Recommendation]:
        """Generate a kill recommendation for an ad.

        Args:
            diag: AdDiagnostic with kill_recommendation=True.
            brand_id: Brand UUID.
            org_id: Organization UUID.
            run_id: Run UUID.

        Returns:
            Kill recommendation or None.
        """
        reason_map = {
            "test_failure": "Failed creative test — performance critically below baselines",
            "fatigue": "Ad fatigue detected — frequency too high with declining engagement",
            "inefficient": "Spending without conversions — inefficient ad",
        }

        title = f"Kill: {diag.meta_ad_id}"
        summary = reason_map.get(diag.kill_reason, "Ad should be paused")

        # Build evidence from fired rules
        evidence = []
        for rule in diag.fired_rules:
            if not rule.skipped and rule.severity in ("critical", "warning"):
                evidence.append(EvidencePoint(
                    metric=rule.metric_name,
                    observation=rule.explanation,
                    data={
                        "current": rule.actual_value,
                        "baseline": rule.baseline_value,
                    },
                ))

        return Recommendation(
            brand_id=brand_id,
            organization_id=org_id,
            run_id=run_id,
            title=title,
            category=RecommendationCategory.KILL,
            priority="critical",
            confidence=max((r.confidence for r in diag.fired_rules if not r.skipped), default=0.5),
            summary=summary,
            evidence=evidence[:5],
            affected_ads=[AffectedAd(ad_id=diag.meta_ad_id, reason=diag.kill_reason)],
            affected_ad_ids=[diag.meta_ad_id],
            action_description="Pause this ad immediately",
            action_type="pause_ad",
            diagnostic_id=diag.id,
        )

    def _generate_issue_rec(
        self,
        diags: List[AdDiagnostic],
        rule_id: str,
        brand_id: UUID,
        org_id: UUID,
        run_id: UUID,
        priority: str = "medium",
    ) -> Optional[Recommendation]:
        """Generate a recommendation for a group of ads with the same top issue.

        Args:
            diags: Diagnostics grouped by top rule.
            rule_id: The common rule ID.
            brand_id: Brand UUID.
            org_id: Organization UUID.
            run_id: Run UUID.
            priority: Recommendation priority.

        Returns:
            Recommendation or None.
        """
        if not diags:
            return None

        # Get rule info from first diagnostic's fired rules
        sample_rule = None
        for d in diags:
            for r in d.fired_rules:
                if r.rule_id == rule_id and not r.skipped:
                    sample_rule = r
                    break
            if sample_rule:
                break

        if not sample_rule:
            return None

        # Determine category and action based on rule
        category, action_type, action_desc = self._rule_to_action(rule_id, sample_rule)

        # Build affected ads
        affected = [
            AffectedAd(ad_id=d.meta_ad_id, reason=sample_rule.rule_name)
            for d in diags
        ]
        affected_ids = [d.meta_ad_id for d in diags]

        evidence = [EvidencePoint(
            metric=sample_rule.metric_name,
            observation=f"{len(diags)} ads affected: {sample_rule.explanation}",
            data={
                "current": sample_rule.actual_value,
                "baseline": sample_rule.baseline_value,
                "affected_count": len(diags),
            },
        )]

        return Recommendation(
            brand_id=brand_id,
            organization_id=org_id,
            run_id=run_id,
            title=f"{sample_rule.rule_name} ({len(diags)} ads)",
            category=category,
            priority=priority,
            confidence=sample_rule.confidence,
            summary=f"{len(diags)} ads have {sample_rule.rule_name.lower()}",
            evidence=evidence,
            affected_ads=affected[:20],
            affected_ad_ids=affected_ids[:20],
            action_description=action_desc,
            action_type=action_type,
        )

    def _generate_scale_rec(
        self,
        healthy_ads: List[AdDiagnostic],
        brand_id: UUID,
        org_id: UUID,
        run_id: UUID,
    ) -> Optional[Recommendation]:
        """Generate scale recommendation for healthy performers.

        Args:
            healthy_ads: Diagnostics with HEALTHY status.
            brand_id: Brand UUID.
            org_id: Organization UUID.
            run_id: Run UUID.

        Returns:
            Scale recommendation or None.
        """
        if len(healthy_ads) < 2:
            return None

        affected = [
            AffectedAd(ad_id=d.meta_ad_id, reason="Healthy performer")
            for d in healthy_ads[:10]
        ]
        affected_ids = [d.meta_ad_id for d in healthy_ads[:10]]

        return Recommendation(
            brand_id=brand_id,
            organization_id=org_id,
            run_id=run_id,
            title=f"Scale {len(healthy_ads)} Healthy Ads",
            category=RecommendationCategory.SCALE,
            priority="medium",
            confidence=0.7,
            summary=f"{len(healthy_ads)} ads are performing well — consider increasing budgets",
            evidence=[EvidencePoint(
                metric="health_status",
                observation=f"{len(healthy_ads)} ads passing all diagnostic rules",
                data={"healthy_count": len(healthy_ads)},
            )],
            affected_ads=affected,
            affected_ad_ids=affected_ids,
            action_description="Consider increasing budget on these healthy performers",
            action_type="increase_budget",
        )

    # =========================================================================
    # Helpers
    # =========================================================================

    def _group_by_top_rule(
        self, diagnostics: List[AdDiagnostic]
    ) -> Dict[str, List[AdDiagnostic]]:
        """Group diagnostics by their top (highest severity) fired rule.

        Args:
            diagnostics: List of AdDiagnostic.

        Returns:
            Dict mapping rule_id → list of diagnostics.
        """
        severity_order = {"critical": 3, "warning": 2, "info": 1}
        grouped: Dict[str, List[AdDiagnostic]] = {}

        for diag in diagnostics:
            top_rule = None
            top_severity = 0
            for r in diag.fired_rules:
                if r.skipped:
                    continue
                sev = severity_order.get(r.severity, 0)
                if sev > top_severity:
                    top_severity = sev
                    top_rule = r

            if top_rule:
                if top_rule.rule_id not in grouped:
                    grouped[top_rule.rule_id] = []
                grouped[top_rule.rule_id].append(diag)

        return grouped

    def _rule_to_action(
        self, rule_id: str, rule: FiredRule
    ) -> tuple:
        """Map a diagnostic rule to recommendation category and action.

        Args:
            rule_id: Rule identifier.
            rule: FiredRule instance.

        Returns:
            Tuple of (category, action_type, action_description).
        """
        mapping = {
            "ctr_below_p25": (
                RecommendationCategory.ITERATE,
                "update_creative",
                "Test new creative variations with stronger hooks",
            ),
            "ctr_below_p10": (
                RecommendationCategory.KILL,
                "pause_ad",
                "Pause and replace with new creative",
            ),
            "cpc_above_p75": (
                RecommendationCategory.ITERATE,
                "change_audience",
                "Review targeting — high CPC may indicate audience mismatch",
            ),
            "roas_below_p25": (
                RecommendationCategory.ITERATE,
                "update_creative",
                "Optimize for conversions or pause if ROAS stays low",
            ),
            "frequency_above_threshold": (
                RecommendationCategory.REFRESH,
                "update_creative",
                "Refresh creative to combat audience fatigue",
            ),
            "frequency_trend_rising": (
                RecommendationCategory.REFRESH,
                "update_creative",
                "Create new creative variations before frequency gets critical",
            ),
            "ctr_declining_7d": (
                RecommendationCategory.REFRESH,
                "update_creative",
                "CTR declining — test new angles or refresh creative",
            ),
            "spend_no_conversions": (
                RecommendationCategory.KILL,
                "pause_ad",
                "Spending without conversions — pause and investigate",
            ),
            "hook_rate_below_p25": (
                RecommendationCategory.CREATIVE_TEST,
                "update_creative",
                "Test stronger hooks — current creative isn't stopping thumbs",
            ),
            "hold_rate_below_p25": (
                RecommendationCategory.CREATIVE_TEST,
                "update_creative",
                "Improve mid-video retention — viewers are dropping off early",
            ),
            "congruence_below_threshold": (
                RecommendationCategory.CONGRUENCE_FIX,
                "update_creative",
                "Align creative, copy, and landing page awareness levels",
            ),
            "impression_starvation": (
                RecommendationCategory.BUDGET_REALLOC,
                "increase_budget",
                "Ad receiving very few impressions — increase budget or broaden audience",
            ),
        }

        default = (
            RecommendationCategory.ITERATE,
            "monitor",
            f"Monitor {rule.rule_name.lower()} and consider adjustments",
        )

        return mapping.get(rule_id, default)

    async def _get_latest_run_id(self, brand_id: UUID) -> Optional[UUID]:
        """Get the latest completed run ID for a brand.

        Args:
            brand_id: Brand UUID.

        Returns:
            Run UUID or None.
        """
        try:
            result = self.supabase.table("ad_intelligence_runs").select("id").eq(
                "brand_id", str(brand_id)
            ).eq(
                "status", "completed"
            ).order(
                "created_at", desc=True
            ).limit(1).execute()

            if result.data:
                return UUID(result.data[0]["id"])
        except Exception as e:
            logger.warning(f"Error fetching latest run: {e}")
        return None

    async def _store_recommendation(self, rec: Recommendation) -> None:
        """Store a recommendation in the database.

        Args:
            rec: Recommendation to store.
        """
        try:
            record = {
                "organization_id": str(rec.organization_id) if rec.organization_id else None,
                "brand_id": str(rec.brand_id),
                "run_id": str(rec.run_id),
                "title": rec.title,
                "category": rec.category.value if isinstance(rec.category, RecommendationCategory) else rec.category,
                "priority": rec.priority,
                "confidence": rec.confidence,
                "summary": rec.summary,
                "evidence": [e.model_dump() for e in rec.evidence],
                "affected_ad_ids": rec.affected_ad_ids,
                "affected_campaign_ids": rec.affected_campaign_ids,
                "affected_ads": [a.model_dump() for a in rec.affected_ads],
                "action_description": rec.action_description,
                "action_type": rec.action_type,
                "status": rec.status.value if isinstance(rec.status, RecommendationStatus) else rec.status,
                "diagnostic_id": str(rec.diagnostic_id) if rec.diagnostic_id else None,
            }

            result = self.supabase.table("ad_intelligence_recommendations").insert(
                record
            ).execute()

            if result.data:
                rec.id = UUID(result.data[0]["id"])

        except Exception as e:
            logger.error(f"Error storing recommendation: {e}")

    def _row_to_model(self, row: Dict) -> Recommendation:
        """Convert a DB row to a Recommendation model.

        Args:
            row: Database row dict.

        Returns:
            Recommendation model.
        """
        # Parse evidence
        evidence = []
        for e in row.get("evidence", []):
            if isinstance(e, dict):
                evidence.append(EvidencePoint(**e))

        # Parse affected ads
        affected_ads = []
        for a in row.get("affected_ads", []):
            if isinstance(a, dict):
                affected_ads.append(AffectedAd(**a))

        return Recommendation(
            id=row.get("id"),
            brand_id=UUID(row["brand_id"]) if row.get("brand_id") else UUID(int=0),
            organization_id=UUID(row["organization_id"]) if row.get("organization_id") else None,
            run_id=UUID(row["run_id"]) if row.get("run_id") else UUID(int=0),
            title=row.get("title", ""),
            category=row.get("category", "iterate"),
            priority=row.get("priority", "medium"),
            confidence=_safe_numeric(row.get("confidence")) or 0,
            summary=row.get("summary", ""),
            evidence=evidence,
            affected_ads=affected_ads,
            affected_ad_ids=row.get("affected_ad_ids", []),
            affected_campaign_ids=row.get("affected_campaign_ids", []),
            action_description=row.get("action_description", ""),
            action_type=row.get("action_type", "no_action"),
            status=row.get("status", "pending"),
            user_note=row.get("user_note"),
            acted_at=row.get("acted_at"),
            acted_by=UUID(row["acted_by"]) if row.get("acted_by") else None,
            diagnostic_id=UUID(row["diagnostic_id"]) if row.get("diagnostic_id") else None,
            created_at=row.get("created_at"),
            expires_at=row.get("expires_at"),
        )
