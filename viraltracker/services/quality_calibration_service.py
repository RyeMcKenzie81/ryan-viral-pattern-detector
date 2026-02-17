"""
Quality Calibration Service — Adaptive threshold calibration from human override data.

Phase 8A: Analyzes false positive/negative rates from ad_review_overrides,
proposes new quality_scoring_config (pass_threshold, check_weights, borderline_range),
with safety rails (min sample size, bounded deltas), operator approval flow.
"""

import logging
from datetime import date, datetime, timedelta, timezone
from typing import Dict, List, Optional, Any
from uuid import UUID

logger = logging.getLogger(__name__)

# Valid rubric check IDs
VALID_CHECK_IDS = [
    "V1", "V2", "V3", "V4", "V5", "V6", "V7", "V8", "V9",
    "C1", "C2", "C3", "C4",
    "G1", "G2",
]

# Safety rail defaults
MIN_SAMPLE_SIZE = 30
MAX_THRESHOLD_DELTA = 1.0
MAX_WEIGHT_DELTA = 0.5


class QualityCalibrationService:
    """Adaptive threshold calibration from human override data."""

    async def analyze_overrides(
        self,
        organization_id: Optional[UUID] = None,
        window_days: int = 30,
    ) -> Dict[str, Any]:
        """Analyze override patterns for false positive/negative rates.

        Args:
            organization_id: Optional org UUID. None = global.
            window_days: Number of days to look back.

        Returns:
            Dict with total_overrides, false_positive_rate, false_negative_rate,
            per_check_rates: {V1: {fp: .., fn: ..}, ...}
        """
        from viraltracker.core.database import get_supabase_client

        db = get_supabase_client()
        cutoff = (datetime.now(timezone.utc) - timedelta(days=window_days)).isoformat()

        # Get latest overrides (superseded_by IS NULL) with ad review data
        query = db.table("ad_review_overrides").select(
            "id, generated_ad_id, override_action, check_overrides, "
            "generated_ads!inner(id, final_status, review_check_scores, weighted_score)"
        ).is_(
            "superseded_by", "null"
        ).gte("created_at", cutoff)

        if organization_id:
            query = query.eq("organization_id", str(organization_id))

        result = query.execute()
        overrides = result.data or []

        if not overrides:
            return {
                "total_overrides": 0,
                "false_positive_rate": None,
                "false_negative_rate": None,
                "per_check_rates": {},
                "window_start": cutoff,
                "window_end": datetime.now(timezone.utc).isoformat(),
            }

        # Count false positives (AI approved, human rejected) and
        # false negatives (AI rejected, human approved)
        total_approved_by_ai = 0
        total_rejected_by_ai = 0
        false_positives = 0  # AI said approve, human override_reject
        false_negatives = 0  # AI said reject, human override_approve

        # Per-check tracking
        per_check_fp = {c: 0 for c in VALID_CHECK_IDS}
        per_check_fn = {c: 0 for c in VALID_CHECK_IDS}
        per_check_total = {c: 0 for c in VALID_CHECK_IDS}

        for override in overrides:
            action = override.get("override_action")
            ad_data = override.get("generated_ads", {})
            ai_status = ad_data.get("final_status", "")
            scores = ad_data.get("review_check_scores") or {}

            if ai_status == "approved":
                total_approved_by_ai += 1
                if action == "override_reject":
                    false_positives += 1
                    # Track which checks contributed to the false positive
                    for check, score in scores.items():
                        if check in per_check_fp and score is not None:
                            per_check_total[check] += 1
                            if float(score) >= 7.0:  # AI thought it was good
                                per_check_fp[check] += 1
            elif ai_status in ("rejected", "flagged"):
                total_rejected_by_ai += 1
                if action == "override_approve":
                    false_negatives += 1
                    for check, score in scores.items():
                        if check in per_check_fn and score is not None:
                            per_check_total[check] += 1
                            if float(score) < 7.0:  # AI thought it was bad
                                per_check_fn[check] += 1

        fp_rate = false_positives / total_approved_by_ai if total_approved_by_ai > 0 else 0.0
        fn_rate = false_negatives / total_rejected_by_ai if total_rejected_by_ai > 0 else 0.0

        per_check_rates = {}
        for check in VALID_CHECK_IDS:
            total = per_check_total.get(check, 0)
            if total > 0:
                per_check_rates[check] = {
                    "fp": per_check_fp[check] / total,
                    "fn": per_check_fn[check] / total,
                    "total": total,
                }

        return {
            "total_overrides": len(overrides),
            "false_positive_rate": round(fp_rate, 4),
            "false_negative_rate": round(fn_rate, 4),
            "false_positives": false_positives,
            "false_negatives": false_negatives,
            "total_approved_by_ai": total_approved_by_ai,
            "total_rejected_by_ai": total_rejected_by_ai,
            "per_check_rates": per_check_rates,
            "window_start": cutoff,
            "window_end": datetime.now(timezone.utc).isoformat(),
        }

    async def propose_calibration(
        self,
        organization_id: Optional[UUID] = None,
        window_days: int = 30,
        job_run_id: Optional[UUID] = None,
    ) -> Dict[str, Any]:
        """Generate a calibration proposal based on override analysis.

        Safety rails:
        - Min 30 overrides in analysis window
        - Max +/-1.0 change from current pass_threshold
        - Per-check weight changes bounded +/-0.5

        Validation (applied before storing):
        - All 15 rubric checks present in check_weights
        - All weights >= 0
        - borderline_range.low < borderline_range.high, both in [0, 10]
        - auto_reject_checks subset of valid check IDs
        - pass_threshold in [1.0, 10.0]

        Args:
            organization_id: Optional org UUID.
            window_days: Analysis window in days.
            job_run_id: Optional scheduled_job_runs.id for provenance.

        Returns:
            {proposal_id, current_config, proposed_config, metrics,
             status: "proposed" | "insufficient_evidence"}
        """
        from viraltracker.core.database import get_supabase_client
        from viraltracker.pipelines.ad_creation_v2.services.review_service import (
            load_quality_config, DEFAULT_QUALITY_CONFIG,
        )

        db = get_supabase_client()

        # Analyze overrides
        analysis = await self.analyze_overrides(organization_id, window_days)

        # Load current config
        org_str = str(organization_id) if organization_id else None
        current_config = await load_quality_config(org_str)
        current_config_id = current_config.get("id")

        current_threshold = float(current_config.get(
            "pass_threshold", DEFAULT_QUALITY_CONFIG["pass_threshold"]
        ))
        current_weights = current_config.get(
            "check_weights", DEFAULT_QUALITY_CONFIG["check_weights"]
        )
        current_borderline = current_config.get(
            "borderline_range", DEFAULT_QUALITY_CONFIG["borderline_range"]
        )
        current_auto_reject = current_config.get(
            "auto_reject_checks", DEFAULT_QUALITY_CONFIG["auto_reject_checks"]
        )

        # Check min sample size
        total_overrides = analysis["total_overrides"]
        meets_min_sample = total_overrides >= MIN_SAMPLE_SIZE

        if not meets_min_sample:
            # Insufficient evidence — persist for auditability but don't propose
            proposal_row = self._build_proposal_row(
                organization_id=organization_id,
                current_config_id=current_config_id,
                proposed_threshold=current_threshold,
                proposed_weights=current_weights,
                proposed_borderline=current_borderline,
                proposed_auto_reject=current_auto_reject,
                analysis=analysis,
                window_days=window_days,
                meets_min_sample=False,
                within_delta=True,
                status="insufficient_evidence",
                job_run_id=job_run_id,
                notes=f"Only {total_overrides} overrides (need {MIN_SAMPLE_SIZE})",
            )
            result = db.table("calibration_proposals").insert(proposal_row).execute()
            proposal_id = result.data[0]["id"] if result.data else None

            return {
                "proposal_id": proposal_id,
                "status": "insufficient_evidence",
                "reason": f"Only {total_overrides} overrides (minimum {MIN_SAMPLE_SIZE})",
                "metrics": analysis,
            }

        # Compute proposed adjustments
        fp_rate = analysis.get("false_positive_rate", 0.0)
        fn_rate = analysis.get("false_negative_rate", 0.0)

        # Threshold adjustment: lower if too many false negatives, raise if too many false positives
        threshold_delta = 0.0
        if fn_rate > 0.15:  # More than 15% false negatives → threshold too strict
            threshold_delta = -min(fn_rate * 2.0, MAX_THRESHOLD_DELTA)
        elif fp_rate > 0.15:  # More than 15% false positives → threshold too lenient
            threshold_delta = min(fp_rate * 2.0, MAX_THRESHOLD_DELTA)

        proposed_threshold = round(current_threshold + threshold_delta, 2)

        # Weight adjustments: proportional to per-check false rates
        proposed_weights = dict(current_weights)
        per_check = analysis.get("per_check_rates", {})
        for check in VALID_CHECK_IDS:
            check_data = per_check.get(check, {})
            check_fp = check_data.get("fp", 0.0)
            check_fn = check_data.get("fn", 0.0)

            # If high FP rate for this check → increase weight (be stricter)
            # If high FN rate → decrease weight (be more lenient)
            weight_delta = (check_fp - check_fn) * MAX_WEIGHT_DELTA
            weight_delta = max(-MAX_WEIGHT_DELTA, min(MAX_WEIGHT_DELTA, weight_delta))

            new_weight = float(proposed_weights.get(check, 1.0)) + weight_delta
            proposed_weights[check] = round(max(0.0, new_weight), 2)

        # Borderline range adjustment
        proposed_borderline = dict(current_borderline)
        if fn_rate > fp_rate and fn_rate > 0.1:
            # Too strict → widen borderline range down
            new_low = max(0.0, float(proposed_borderline.get("low", 5.0)) - 0.5)
            proposed_borderline["low"] = round(new_low, 1)
        elif fp_rate > fn_rate and fp_rate > 0.1:
            # Too lenient → raise borderline range
            new_high = min(10.0, float(proposed_borderline.get("high", 7.0)) + 0.5)
            proposed_borderline["high"] = round(new_high, 1)

        # Keep auto_reject_checks unchanged in 8A
        proposed_auto_reject = list(current_auto_reject)

        # Validate proposal
        validation_errors = self._validate_proposal(
            proposed_threshold, proposed_weights, proposed_borderline, proposed_auto_reject
        )

        within_delta = abs(proposed_threshold - current_threshold) <= MAX_THRESHOLD_DELTA

        if validation_errors:
            # Persist for auditability but mark as insufficient_evidence
            proposal_row = self._build_proposal_row(
                organization_id=organization_id,
                current_config_id=current_config_id,
                proposed_threshold=proposed_threshold,
                proposed_weights=proposed_weights,
                proposed_borderline=proposed_borderline,
                proposed_auto_reject=proposed_auto_reject,
                analysis=analysis,
                window_days=window_days,
                meets_min_sample=meets_min_sample,
                within_delta=within_delta,
                status="insufficient_evidence",
                job_run_id=job_run_id,
                notes=f"Validation failed: {'; '.join(validation_errors)}",
            )
            result = db.table("calibration_proposals").insert(proposal_row).execute()
            proposal_id = result.data[0]["id"] if result.data else None

            logger.warning(f"Calibration proposal validation failed: {validation_errors}")
            return {
                "proposal_id": proposal_id,
                "status": "insufficient_evidence",
                "reason": f"Validation failed: {'; '.join(validation_errors)}",
                "metrics": analysis,
            }

        # Estimate approval rate change
        approval_rate_change = -threshold_delta * 0.05  # rough estimate

        # Store proposal
        proposal_row = self._build_proposal_row(
            organization_id=organization_id,
            current_config_id=current_config_id,
            proposed_threshold=proposed_threshold,
            proposed_weights=proposed_weights,
            proposed_borderline=proposed_borderline,
            proposed_auto_reject=proposed_auto_reject,
            analysis=analysis,
            window_days=window_days,
            meets_min_sample=meets_min_sample,
            within_delta=within_delta,
            status="proposed",
            job_run_id=job_run_id,
            notes=None,
            approval_rate_change=approval_rate_change,
        )

        result = db.table("calibration_proposals").insert(proposal_row).execute()
        proposal_id = result.data[0]["id"] if result.data else None

        logger.info(
            f"Calibration proposal created: id={proposal_id}, "
            f"threshold={current_threshold}->{proposed_threshold}, "
            f"fp_rate={fp_rate}, fn_rate={fn_rate}"
        )

        return {
            "proposal_id": proposal_id,
            "status": "proposed",
            "current_config": {
                "pass_threshold": current_threshold,
                "check_weights": current_weights,
                "borderline_range": current_borderline,
            },
            "proposed_config": {
                "pass_threshold": proposed_threshold,
                "check_weights": proposed_weights,
                "borderline_range": proposed_borderline,
                "auto_reject_checks": proposed_auto_reject,
            },
            "metrics": analysis,
        }

    async def activate_proposal(
        self, proposal_id: UUID, activated_by: UUID
    ) -> Dict[str, Any]:
        """Activate a calibration proposal. Creates new quality_scoring_config version.

        Deactivates current config, activates new one.

        Args:
            proposal_id: Proposal UUID.
            activated_by: User UUID.

        Returns:
            Dict with new_config_id and status.
        """
        from viraltracker.core.database import get_supabase_client

        db = get_supabase_client()

        # Get proposal
        proposal_result = db.table("calibration_proposals").select(
            "*"
        ).eq("id", str(proposal_id)).single().execute()

        proposal = proposal_result.data
        if not proposal:
            raise ValueError(f"Proposal {proposal_id} not found")

        if proposal["status"] != "proposed":
            raise ValueError(f"Proposal {proposal_id} is not in 'proposed' status")

        org_id = proposal.get("organization_id")
        current_config_id = proposal.get("current_config_id")

        # Deactivate current config
        if current_config_id:
            db.table("quality_scoring_config").update(
                {"is_active": False}
            ).eq("id", current_config_id).execute()

        # Get next version number
        version_query = db.table("quality_scoring_config").select(
            "version"
        ).order("version", desc=True).limit(1)
        if org_id:
            version_query = version_query.eq("organization_id", org_id)
        else:
            version_query = version_query.is_("organization_id", "null")

        version_result = version_query.execute()
        next_version = (version_result.data[0]["version"] + 1) if version_result.data else 1

        # Create new config
        new_config = {
            "organization_id": org_id,
            "version": next_version,
            "is_active": True,
            "pass_threshold": float(proposal["proposed_pass_threshold"]),
            "check_weights": proposal["proposed_check_weights"],
            "borderline_range": proposal["proposed_borderline_range"],
            "auto_reject_checks": proposal["proposed_auto_reject_checks"],
            "created_by": str(activated_by),
            "notes": f"Auto-calibrated from proposal {proposal_id}",
        }

        config_result = db.table("quality_scoring_config").insert(
            new_config
        ).execute()

        new_config_id = config_result.data[0]["id"] if config_result.data else None

        # Update proposal status
        db.table("calibration_proposals").update({
            "status": "activated",
            "activated_by": str(activated_by),
            "activated_at": datetime.now(timezone.utc).isoformat(),
            "activated_config_id": new_config_id,
        }).eq("id", str(proposal_id)).execute()

        logger.info(f"Calibration proposal {proposal_id} activated → config {new_config_id}")

        return {
            "new_config_id": new_config_id,
            "status": "activated",
            "version": next_version,
        }

    async def dismiss_proposal(
        self, proposal_id: UUID, dismissed_by: UUID, reason: str
    ) -> None:
        """Dismiss a calibration proposal with reason.

        Args:
            proposal_id: Proposal UUID.
            dismissed_by: User UUID.
            reason: Dismissal reason.
        """
        from viraltracker.core.database import get_supabase_client

        db = get_supabase_client()
        db.table("calibration_proposals").update({
            "status": "dismissed",
            "dismissed_by": str(dismissed_by),
            "dismissed_at": datetime.now(timezone.utc).isoformat(),
            "dismissed_reason": reason,
        }).eq("id", str(proposal_id)).execute()

        logger.info(f"Calibration proposal {proposal_id} dismissed: {reason}")

    async def get_pending_proposals(
        self, organization_id: Optional[UUID] = None
    ) -> List[Dict[str, Any]]:
        """Get all pending (proposed) calibration proposals.

        Args:
            organization_id: Optional org filter.

        Returns:
            List of proposal dicts.
        """
        from viraltracker.core.database import get_supabase_client

        db = get_supabase_client()
        query = db.table("calibration_proposals").select("*").eq(
            "status", "proposed"
        ).order("proposed_at", desc=True)

        if organization_id:
            query = query.eq("organization_id", str(organization_id))

        result = query.execute()
        return result.data or []

    async def get_proposal_history(
        self, organization_id: Optional[UUID] = None
    ) -> List[Dict[str, Any]]:
        """Get full history of calibration proposals.

        Args:
            organization_id: Optional org filter.

        Returns:
            List of proposal dicts ordered by date.
        """
        from viraltracker.core.database import get_supabase_client

        db = get_supabase_client()
        query = db.table("calibration_proposals").select("*").order(
            "proposed_at", desc=True
        ).limit(50)

        if organization_id:
            query = query.eq("organization_id", str(organization_id))

        result = query.execute()
        return result.data or []

    # ========================================================================
    # Internal helpers
    # ========================================================================

    def _validate_proposal(
        self,
        threshold: float,
        weights: Dict[str, float],
        borderline: Dict[str, float],
        auto_reject: list,
    ) -> List[str]:
        """Validate a proposed config. Returns list of error strings (empty = valid)."""
        errors = []

        # pass_threshold in [1.0, 10.0]
        if not (1.0 <= threshold <= 10.0):
            errors.append(f"pass_threshold {threshold} not in [1.0, 10.0]")

        # All 15 rubric checks present in weights
        for check in VALID_CHECK_IDS:
            if check not in weights:
                errors.append(f"Missing check '{check}' in check_weights")

        # All weights non-negative
        for check, w in weights.items():
            if w < 0:
                errors.append(f"Negative weight for '{check}': {w}")

        # borderline_range.low < borderline_range.high
        bl_low = borderline.get("low", 5.0)
        bl_high = borderline.get("high", 7.0)
        if bl_low >= bl_high:
            errors.append(f"borderline_range.low ({bl_low}) >= high ({bl_high})")

        # borderline values in [0, 10]
        if not (0 <= bl_low <= 10):
            errors.append(f"borderline_range.low ({bl_low}) not in [0, 10]")
        if not (0 <= bl_high <= 10):
            errors.append(f"borderline_range.high ({bl_high}) not in [0, 10]")

        # auto_reject_checks subset of valid check IDs
        for check in auto_reject:
            if check not in VALID_CHECK_IDS:
                errors.append(f"Invalid auto_reject check: '{check}'")

        return errors

    def _build_proposal_row(
        self,
        organization_id: Optional[UUID],
        current_config_id: Optional[str],
        proposed_threshold: float,
        proposed_weights: Dict[str, float],
        proposed_borderline: Dict[str, float],
        proposed_auto_reject: list,
        analysis: Dict[str, Any],
        window_days: int,
        meets_min_sample: bool,
        within_delta: bool,
        status: str,
        job_run_id: Optional[UUID],
        notes: Optional[str],
        approval_rate_change: float = 0.0,
    ) -> Dict[str, Any]:
        """Build a calibration_proposals row dict."""
        now = datetime.now(timezone.utc)
        window_end = now.date()
        window_start = window_end - timedelta(days=window_days)

        return {
            "organization_id": str(organization_id) if organization_id else None,
            "current_config_id": current_config_id,
            "proposed_pass_threshold": proposed_threshold,
            "proposed_check_weights": proposed_weights,
            "proposed_borderline_range": proposed_borderline,
            "proposed_auto_reject_checks": proposed_auto_reject,
            "analysis_window_start": str(window_start),
            "analysis_window_end": str(window_end),
            "total_overrides_analyzed": analysis.get("total_overrides", 0),
            "false_positive_rate": analysis.get("false_positive_rate"),
            "false_negative_rate": analysis.get("false_negative_rate"),
            "expected_approval_rate_change": approval_rate_change,
            "meets_min_sample_size": meets_min_sample,
            "within_delta_bounds": within_delta,
            "min_sample_size_required": MIN_SAMPLE_SIZE,
            "max_threshold_delta": MAX_THRESHOLD_DELTA,
            "status": status,
            "proposed_by_job_id": str(job_run_id) if job_run_id else None,
            "notes": notes,
        }
