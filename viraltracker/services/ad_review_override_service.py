"""
Ad Review Override Service — human override operations for Phase 4 review pipeline.

Provides atomic create_override (via Postgres RPC), latest-override lookup,
and aggregate override stats for an organization.
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
