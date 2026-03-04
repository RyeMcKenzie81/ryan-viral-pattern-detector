"""
Ad Review Override Service — human override operations for Phase 4 review pipeline.

Provides atomic create_override (via Postgres RPC), latest-override lookup,
aggregate override stats, filtered ad queries, and bulk override for an organization.
"""

import logging
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List, Optional
from uuid import UUID

from viraltracker.core.database import get_supabase_client

logger = logging.getLogger(__name__)

VALID_ACTIONS = ("override_approve", "override_reject", "confirm")


class AdReviewOverrideService:
    """Service for human review overrides on generated ads."""

    def __init__(self):
        self._db = get_supabase_client()

    def create_override(
        self,
        generated_ad_id: str,
        org_id: str,
        user_id: str,
        action: str,
        reason: Optional[str] = None,
        check_overrides: Optional[Dict[str, Any]] = None,
    ) -> Dict[str, Any]:
        """
        Apply a human override to a generated ad (atomic via Postgres RPC).

        Args:
            generated_ad_id: UUID of the generated ad.
            org_id: Organization UUID.
            user_id: User UUID performing the override.
            action: One of 'override_approve', 'override_reject', 'confirm'.
            reason: Optional human-written reason.
            check_overrides: Optional per-check overrides, e.g.
                {"V1": {"ai_score": 6.0, "human_override": "pass"}}.

        Returns:
            Dict with override result from RPC.

        Raises:
            ValueError: If action is invalid.
            Exception: If RPC call fails.
        """
        if action not in VALID_ACTIONS:
            raise ValueError(f"Invalid action '{action}'. Must be one of {VALID_ACTIONS}")

        result = self._db.rpc(
            "apply_ad_override",
            {
                "p_generated_ad_id": generated_ad_id,
                "p_org_id": org_id,
                "p_user_id": user_id,
                "p_action": action,
                "p_reason": reason,
                "p_check_overrides": check_overrides,
            },
        ).execute()

        logger.info(
            f"Override applied: ad={generated_ad_id} action={action} "
            f"by user={user_id}"
        )
        return result.data

    def get_latest_override(self, generated_ad_id: str) -> Optional[Dict[str, Any]]:
        """
        Get the latest (non-superseded) override for a generated ad.

        Args:
            generated_ad_id: UUID of the generated ad.

        Returns:
            Override dict or None if no override exists.
        """
        result = (
            self._db.table("ad_review_overrides")
            .select("*")
            .eq("generated_ad_id", generated_ad_id)
            .is_("superseded_by", "null")
            .order("created_at", desc=True)
            .limit(1)
            .execute()
        )
        return result.data[0] if result.data else None

    def get_override_stats(
        self,
        org_id: str,
        days: int = 30,
    ) -> Dict[str, int]:
        """
        Get aggregate override statistics for an organization.

        Args:
            org_id: Organization UUID.
            days: Lookback window in days (default 30).

        Returns:
            Dict with keys: total, override_approve, override_reject, confirm.
        """
        since = (datetime.now(timezone.utc) - timedelta(days=days)).isoformat()

        result = (
            self._db.table("ad_review_overrides")
            .select("override_action")
            .eq("organization_id", org_id)
            .gte("created_at", since)
            .is_("superseded_by", "null")
            .execute()
        )

        rows = result.data or []
        stats = {
            "total": len(rows),
            "override_approve": 0,
            "override_reject": 0,
            "confirm": 0,
        }
        for row in rows:
            action = row.get("override_action")
            if action in stats:
                stats[action] += 1

        return stats

    def get_ads_for_run(self, ad_run_id: str) -> List[Dict[str, Any]]:
        """
        Fetch generated ads for a specific ad run, including Phase 4 columns.

        Args:
            ad_run_id: UUID of the ad_runs row.

        Returns:
            List of generated ad dicts with review/defect/override data.
        """
        result = (
            self._db.table("generated_ads")
            .select(
                "id, ad_run_id, prompt_index, storage_path, final_status, "
                "claude_review, gemini_review, "
                "review_check_scores, defect_scan_result, congruence_score, "
                "override_status, hook_text, created_at"
            )
            .eq("ad_run_id", ad_run_id)
            .order("prompt_index")
            .execute()
        )
        return result.data or []

    def get_ads_filtered(
        self,
        org_id: str,
        *,
        status_filter: Optional[List[str]] = None,
        date_from: Optional[str] = None,
        date_to: Optional[str] = None,
        brand_id: Optional[str] = None,
        product_id: Optional[str] = None,
        ad_run_id: Optional[str] = None,
        template_id: Optional[str] = None,
        sort_by: str = "newest",
        limit: int = 50,
        offset: int = 0,
    ) -> List[Dict[str, Any]]:
        """Fetch generated ads with filters for the results dashboard.

        Joins generated_ads with ad_runs to get product context and template ref.
        Org scoping is done via product_id (UI pre-filters products by org).
        ad_runs does NOT have organization_id or pipeline_version columns.

        Args:
            org_id: Organization UUID (used for product scoping at UI level).
            status_filter: List of final_status values to include.
            date_from: ISO datetime string for start of range.
            date_to: ISO datetime string for end of range.
            brand_id: Filter by brand UUID.
            product_id: Filter by product UUID.
            ad_run_id: Filter by specific ad_run UUID.
            template_id: Filter by template UUID.
            sort_by: One of 'newest', 'oldest'.
            limit: Max results (default 50).
            offset: Pagination offset (default 0).

        Returns:
            List of generated ad dicts with joined ad_run data.
        """
        query = (
            self._db.table("generated_ads")
            .select(
                "id, ad_run_id, prompt_index, storage_path, final_status, "
                "review_check_scores, defect_scan_result, congruence_score, "
                "override_status, hook_text, prompt_version, template_name, "
                "created_at, "
                "ad_runs!inner(id, product_id, source_scraped_template_id)"
            )
        )

        if status_filter:
            query = query.in_("final_status", status_filter)
        if date_from:
            query = query.gte("created_at", date_from)
        if date_to:
            query = query.lte("created_at", date_to)
        if product_id:
            query = query.eq("ad_runs.product_id", product_id)
        if ad_run_id:
            query = query.eq("ad_run_id", ad_run_id)
        if template_id:
            query = query.eq("ad_runs.source_scraped_template_id", template_id)

        desc = sort_by != "oldest"
        query = query.order("created_at", desc=desc)
        query = query.range(offset, offset + limit - 1)

        result = query.execute()
        return result.data or []

    def get_summary_stats(
        self,
        org_id: str,
        *,
        date_from: Optional[str] = None,
        date_to: Optional[str] = None,
        brand_id: Optional[str] = None,
        product_id: Optional[str] = None,
    ) -> Dict[str, Any]:
        """Get aggregate ad stats for the results dashboard.

        Args:
            org_id: Organization UUID.
            date_from: ISO datetime string for start of range.
            date_to: ISO datetime string for end of range.
            brand_id: Filter by brand UUID (unused for now, reserved).
            product_id: Filter by product UUID.

        Returns:
            Dict with total, approved, rejected, flagged, review_failed,
            generation_failed, override_rate.
        """
        query = (
            self._db.table("generated_ads")
            .select(
                "final_status, override_status, "
                "ad_runs!inner(product_id)"
            )
        )

        if date_from:
            query = query.gte("created_at", date_from)
        if date_to:
            query = query.lte("created_at", date_to)
        if product_id:
            query = query.eq("ad_runs.product_id", product_id)

        result = query.execute()
        rows = result.data or []

        stats: Dict[str, Any] = {
            "total": len(rows),
            "approved": 0,
            "rejected": 0,
            "flagged": 0,
            "review_failed": 0,
            "generation_failed": 0,
            "overridden": 0,
        }

        for row in rows:
            status = row.get("final_status", "")
            override = row.get("override_status")
            if status in stats:
                stats[status] += 1
            if override:
                stats["overridden"] += 1

        stats["override_rate"] = (
            round(stats["overridden"] / stats["total"] * 100, 1)
            if stats["total"] > 0
            else 0.0
        )

        return stats

    def bulk_override(
        self,
        generated_ad_ids: List[str],
        org_id: str,
        user_id: str,
        action: str,
        reason: Optional[str] = None,
    ) -> Dict[str, int]:
        """Apply override to multiple ads at once.

        Args:
            generated_ad_ids: List of generated ad UUIDs.
            org_id: Organization UUID.
            user_id: User UUID performing the override.
            action: One of 'override_approve', 'override_reject', 'confirm'.
            reason: Optional reason applied to all.

        Returns:
            Dict with success and failed counts.
        """
        if action not in VALID_ACTIONS:
            raise ValueError(f"Invalid action '{action}'. Must be one of {VALID_ACTIONS}")

        if not generated_ad_ids:
            return {"success": 0, "failed": 0}

        success = 0
        failed = 0

        for ad_id in generated_ad_ids:
            try:
                self.create_override(
                    generated_ad_id=ad_id,
                    org_id=org_id,
                    user_id=user_id,
                    action=action,
                    reason=reason,
                )
                success += 1
            except Exception as e:
                logger.warning(f"Bulk override failed for ad {ad_id}: {e}")
                failed += 1

        logger.info(
            f"Bulk override {action}: {success} succeeded, {failed} failed "
            f"out of {len(generated_ad_ids)} ads"
        )
        return {"success": success, "failed": failed}
