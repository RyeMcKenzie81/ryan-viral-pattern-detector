"""
Usage Limit Service - Per-Organization Usage Enforcement.

Provides CRUD for usage limits and enforcement checks.
Limits can be configured per org for monthly cost, monthly tokens,
daily requests, and daily ads.

Usage:
    from viraltracker.services.usage_limit_service import UsageLimitService, UsageLimitExceeded
    from viraltracker.core.database import get_supabase_client

    service = UsageLimitService(get_supabase_client())
    service.enforce_limit(org_id, "monthly_cost")  # Raises UsageLimitExceeded if over
"""

from typing import Optional, List
from datetime import datetime
from decimal import Decimal
import logging

from supabase import Client

logger = logging.getLogger(__name__)


class LimitType:
    """Usage limit type constants."""
    MONTHLY_TOKENS = "monthly_tokens"
    MONTHLY_COST = "monthly_cost"
    DAILY_ADS = "daily_ads"
    DAILY_REQUESTS = "daily_requests"


class UsageLimitExceeded(Exception):
    """Raised when an organization exceeds a configured usage limit."""

    def __init__(self, limit_type: str, limit_value: float, current_usage: float):
        self.limit_type = limit_type
        self.limit_value = limit_value
        self.current_usage = current_usage
        display = limit_type.replace("_", " ").title()
        super().__init__(
            f"{display} limit exceeded: {current_usage:.2f} / {limit_value:.2f}"
        )


class UsageLimitService:
    """
    Service for managing and enforcing per-organization usage limits.

    All enforcement checks are designed to fail open - if the limits table
    doesn't exist or a query fails, the operation proceeds.
    """

    def __init__(self, supabase_client: Client):
        """
        Initialize UsageLimitService.

        Args:
            supabase_client: Supabase client instance
        """
        self.client = supabase_client

    # =========================================================================
    # CRUD
    # =========================================================================

    def get_limits(self, org_id: str) -> List[dict]:
        """
        Get all configured limits for an organization.

        Args:
            org_id: Organization ID

        Returns:
            List of limit dicts with id, limit_type, limit_value, period,
            alert_threshold, enabled, created_at, updated_at
        """
        result = self.client.table("usage_limits").select("*").eq(
            "organization_id", org_id
        ).execute()
        return result.data or []

    def get_limit(self, org_id: str, limit_type: str) -> Optional[dict]:
        """
        Get a specific limit for an organization.

        Args:
            org_id: Organization ID
            limit_type: Limit type (use LimitType constants)

        Returns:
            Limit dict or None if not configured
        """
        try:
            result = self.client.table("usage_limits").select("*").eq(
                "organization_id", org_id
            ).eq("limit_type", limit_type).single().execute()
            return result.data
        except Exception:
            return None

    def set_limit(
        self,
        org_id: str,
        limit_type: str,
        limit_value: float,
        period: str = "monthly",
        alert_threshold: float = 0.8,
        enabled: bool = True,
    ) -> dict:
        """
        Create or update a usage limit.

        Args:
            org_id: Organization ID
            limit_type: Limit type (use LimitType constants)
            limit_value: Maximum allowed value
            period: 'daily' or 'monthly'
            alert_threshold: Warning threshold as fraction (0-1, default 0.8)
            enabled: Whether this limit is enforced

        Returns:
            Upserted limit dict
        """
        result = self.client.table("usage_limits").upsert(
            {
                "organization_id": org_id,
                "limit_type": limit_type,
                "limit_value": limit_value,
                "period": period,
                "alert_threshold": alert_threshold,
                "enabled": enabled,
                "updated_at": "now()",
            },
            on_conflict="organization_id,limit_type",
        ).execute()
        logger.info(
            f"Set limit {limit_type}={limit_value} (period={period}) for org {org_id}"
        )
        return result.data[0] if result.data else {}

    def delete_limit(self, org_id: str, limit_type: str) -> bool:
        """
        Delete a usage limit.

        Args:
            org_id: Organization ID
            limit_type: Limit type to delete

        Returns:
            True if deleted
        """
        self.client.table("usage_limits").delete().eq(
            "organization_id", org_id
        ).eq("limit_type", limit_type).execute()
        logger.info(f"Deleted limit {limit_type} for org {org_id}")
        return True

    # =========================================================================
    # Usage Checking
    # =========================================================================

    def get_current_period_usage(self, org_id: str, limit_type: str) -> dict:
        """
        Get current usage against a limit for the current period.

        Args:
            org_id: Organization ID
            limit_type: Limit type to check

        Returns:
            Dict with:
            - limit_type: str
            - limit_value: float or None (None = no limit)
            - current_usage: float
            - usage_pct: float (0-1)
            - is_exceeded: bool
            - is_warning: bool (above alert_threshold)
            - alert_threshold: float
            - enabled: bool
        """
        # Get the limit config
        limit = self.get_limit(org_id, limit_type)
        limit_value = float(limit["limit_value"]) if limit else None
        alert_threshold = float(limit.get("alert_threshold", 0.8)) if limit else 0.8
        enabled = limit.get("enabled", True) if limit else False

        # Determine period start
        now = datetime.now()
        if limit and limit.get("period") == "daily":
            period_start = now.replace(hour=0, minute=0, second=0, microsecond=0)
        else:
            period_start = now.replace(day=1, hour=0, minute=0, second=0, microsecond=0)

        # Get current usage based on type
        current_usage = self._get_usage_value(org_id, limit_type, period_start)

        # Calculate percentage
        usage_pct = (current_usage / limit_value) if limit_value and limit_value > 0 else 0.0

        return {
            "limit_type": limit_type,
            "limit_value": limit_value,
            "current_usage": current_usage,
            "usage_pct": usage_pct,
            "is_exceeded": usage_pct >= 1.0 if limit_value else False,
            "is_warning": usage_pct >= alert_threshold if limit_value else False,
            "alert_threshold": alert_threshold,
            "enabled": enabled,
        }

    def check_all_limits(self, org_id: str) -> List[dict]:
        """
        Check all configured limits for an organization.

        Args:
            org_id: Organization ID

        Returns:
            List of usage status dicts (same format as get_current_period_usage)
        """
        limits = self.get_limits(org_id)
        results = []
        for limit in limits:
            status = self.get_current_period_usage(org_id, limit["limit_type"])
            results.append(status)
        return results

    # =========================================================================
    # Enforcement
    # =========================================================================

    def enforce_limit(self, org_id: str, limit_type: str) -> None:
        """
        Enforce a usage limit. Raises UsageLimitExceeded if over limit.

        Designed to fail open: if org_id is "all", no limit is configured,
        or the limit is disabled, this returns silently.

        Args:
            org_id: Organization ID
            limit_type: Limit type to enforce

        Raises:
            UsageLimitExceeded: If usage exceeds the configured limit
        """
        # Superuser mode - never enforce
        if not org_id or org_id == "all":
            return

        try:
            status = self.get_current_period_usage(org_id, limit_type)

            # No limit configured or disabled - pass through
            if status["limit_value"] is None or not status["enabled"]:
                return

            if status["is_exceeded"]:
                raise UsageLimitExceeded(
                    limit_type=limit_type,
                    limit_value=status["limit_value"],
                    current_usage=status["current_usage"],
                )

        except UsageLimitExceeded:
            raise
        except Exception as e:
            # Fail open - don't block operations due to limit check errors
            logger.warning(f"Usage limit check failed (non-fatal): {e}")

    # =========================================================================
    # Internal helpers
    # =========================================================================

    def _get_usage_value(
        self, org_id: str, limit_type: str, period_start: datetime
    ) -> float:
        """
        Query the actual usage value for a limit type.

        Args:
            org_id: Organization ID
            limit_type: Which metric to sum
            period_start: Start of the current period

        Returns:
            Current usage value as float
        """
        try:
            if limit_type == LimitType.MONTHLY_COST:
                result = self.client.rpc(
                    "sum_token_usage",
                    {"p_org_id": org_id, "p_column": "cost_usd", "p_start_date": period_start.isoformat()}
                ).execute()
                return float(result.data) if result.data else 0.0

            elif limit_type == LimitType.MONTHLY_TOKENS:
                result = self.client.rpc(
                    "sum_token_usage",
                    {"p_org_id": org_id, "p_column": "total_tokens", "p_start_date": period_start.isoformat()}
                ).execute()
                return float(result.data) if result.data else 0.0

            elif limit_type == LimitType.DAILY_REQUESTS:
                result = self.client.table("token_usage").select(
                    "id", count="exact"
                ).eq(
                    "organization_id", org_id
                ).gte(
                    "created_at", period_start.isoformat()
                ).execute()
                return float(result.count) if result.count else 0.0

            elif limit_type == LimitType.DAILY_ADS:
                result = self.client.table("token_usage").select(
                    "id", count="exact"
                ).eq(
                    "organization_id", org_id
                ).gte(
                    "created_at", period_start.isoformat()
                ).like(
                    "tool_name", "%ad%"
                ).execute()
                return float(result.count) if result.count else 0.0

            return 0.0

        except Exception as e:
            logger.warning(f"Failed to query usage for {limit_type}: {e}")
            return 0.0
