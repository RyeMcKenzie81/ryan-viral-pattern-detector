"""
Usage Tracker Service - Track AI/API usage for billing and analytics.

This service records all AI API calls to enable:
- Per-organization billing
- Usage limits and rate limiting
- Cost visibility and analytics
- Identifying expensive operations

Usage:
    from viraltracker.services.usage_tracker import UsageTracker, UsageRecord
    from viraltracker.core.database import get_supabase_client

    tracker = UsageTracker(get_supabase_client())
    tracker.track(
        user_id="...",
        organization_id="...",
        record=UsageRecord(
            provider="google",
            model="gemini-2.0-flash",
            tool_name="gemini_service",
            operation="analyze_image",
            input_tokens=1500,
            output_tokens=500,
        )
    )
"""

from typing import Optional, List
from datetime import datetime
from decimal import Decimal
from dataclasses import dataclass
import logging

from supabase import Client

from viraltracker.core.config import Config

logger = logging.getLogger(__name__)


@dataclass
class UsageRecord:
    """
    Single AI/API usage event for tracking.

    For token-based APIs (LLMs), use input_tokens/output_tokens.
    For unit-based APIs (images, video, audio), use units/unit_type.
    """
    provider: str                           # 'anthropic', 'openai', 'google', 'elevenlabs'
    model: str                              # 'claude-opus-4-5', 'gpt-4o', 'gemini-2.0-flash'
    tool_name: Optional[str] = None         # 'ad_creator', 'gemini_service'
    operation: Optional[str] = None         # 'generate_image', 'analyze_text'
    input_tokens: int = 0
    output_tokens: int = 0
    units: Optional[float] = None           # For non-token APIs (1 image, 30 seconds)
    unit_type: Optional[str] = None         # 'images', 'video_seconds', 'characters'
    cost_usd: Optional[Decimal] = None      # Pre-calculated cost (optional)
    request_metadata: Optional[dict] = None # Additional context
    duration_ms: Optional[int] = None       # API call duration


@dataclass
class UsageSummary:
    """Aggregated usage summary for a time period."""
    organization_id: str
    period_start: datetime
    period_end: datetime
    total_requests: int
    total_input_tokens: int
    total_output_tokens: int
    total_cost_usd: Decimal
    by_provider: dict  # {provider: {tokens, cost}}
    by_tool: dict      # {tool_name: {tokens, cost}}


class UsageTracker:
    """
    Service for tracking AI/API usage.

    All tracking operations are wrapped in try/except to ensure they never
    fail the main operation. If tracking fails, it logs a warning and continues.
    """

    def __init__(self, supabase_client: Client):
        """
        Initialize UsageTracker.

        Args:
            supabase_client: Supabase client instance
        """
        self.client = supabase_client

    def track(
        self,
        user_id: Optional[str],
        organization_id: str,
        record: UsageRecord
    ) -> None:
        """
        Record a usage event.

        This method is fire-and-forget - it will never raise an exception.
        If tracking fails, it logs a warning and returns silently.

        Args:
            user_id: User who triggered the usage (optional for system ops)
            organization_id: Organization to bill
            record: Usage details
        """
        # Skip tracking for superuser "all" mode
        if organization_id == "all":
            logger.debug("Skipping usage tracking for superuser 'all' mode")
            return

        try:
            # Calculate cost if not provided
            cost = record.cost_usd
            if cost is None:
                cost = self._calculate_cost(record)

            # Insert record
            self.client.table("token_usage").insert({
                "user_id": user_id,
                "organization_id": organization_id,
                "provider": record.provider,
                "model": record.model,
                "tool_name": record.tool_name,
                "operation": record.operation,
                "input_tokens": record.input_tokens,
                "output_tokens": record.output_tokens,
                "units": float(record.units) if record.units else None,
                "unit_type": record.unit_type,
                "cost_usd": float(cost) if cost else None,
                "request_metadata": record.request_metadata,
                "duration_ms": record.duration_ms,
            }).execute()

            logger.debug(
                f"Tracked usage: {record.provider}/{record.model} "
                f"tokens={record.input_tokens}+{record.output_tokens} "
                f"cost=${cost}"
            )

        except Exception as e:
            # Never fail the main operation - just log and continue
            logger.warning(f"Usage tracking failed (non-fatal): {e}")

    def _calculate_cost(self, record: UsageRecord) -> Optional[Decimal]:
        """
        Calculate cost based on usage and configured rates.

        Args:
            record: Usage record

        Returns:
            Calculated cost in USD or None if unable to calculate
        """
        # Token-based cost (LLMs)
        if record.input_tokens > 0 or record.output_tokens > 0:
            input_rate, output_rate = Config.get_token_cost(record.model)
            if input_rate > 0 or output_rate > 0:
                input_cost = (record.input_tokens / 1_000_000) * input_rate
                output_cost = (record.output_tokens / 1_000_000) * output_rate
                return Decimal(str(round(input_cost + output_cost, 6)))

        # Unit-based cost (images, video, audio)
        if record.units and record.unit_type:
            unit_key = f"{record.provider}_{record.unit_type}"
            unit_rate = Config.get_unit_cost(unit_key)
            if unit_rate > 0:
                return Decimal(str(round(record.units * unit_rate, 6)))

        return None

    def get_usage_summary(
        self,
        organization_id: str,
        start_date: datetime,
        end_date: datetime
    ) -> UsageSummary:
        """
        Get aggregated usage summary for an organization.

        Args:
            organization_id: Organization ID
            start_date: Period start (inclusive)
            end_date: Period end (inclusive)

        Returns:
            UsageSummary with aggregated data
        """
        result = self.client.table("token_usage").select("*").eq(
            "organization_id", organization_id
        ).gte("created_at", start_date.isoformat()).lte(
            "created_at", end_date.isoformat()
        ).execute()

        records = result.data or []

        # Aggregate totals
        total_input = sum(r.get("input_tokens", 0) or 0 for r in records)
        total_output = sum(r.get("output_tokens", 0) or 0 for r in records)
        total_cost = sum(Decimal(str(r.get("cost_usd", 0) or 0)) for r in records)

        # Aggregate by provider
        by_provider = {}
        for r in records:
            provider = r.get("provider", "unknown")
            if provider not in by_provider:
                by_provider[provider] = {"tokens": 0, "cost": Decimal("0")}
            by_provider[provider]["tokens"] += (r.get("input_tokens", 0) or 0) + (r.get("output_tokens", 0) or 0)
            by_provider[provider]["cost"] += Decimal(str(r.get("cost_usd", 0) or 0))

        # Aggregate by tool
        by_tool = {}
        for r in records:
            tool = r.get("tool_name") or "unknown"
            if tool not in by_tool:
                by_tool[tool] = {"tokens": 0, "cost": Decimal("0")}
            by_tool[tool]["tokens"] += (r.get("input_tokens", 0) or 0) + (r.get("output_tokens", 0) or 0)
            by_tool[tool]["cost"] += Decimal(str(r.get("cost_usd", 0) or 0))

        return UsageSummary(
            organization_id=organization_id,
            period_start=start_date,
            period_end=end_date,
            total_requests=len(records),
            total_input_tokens=total_input,
            total_output_tokens=total_output,
            total_cost_usd=total_cost,
            by_provider=by_provider,
            by_tool=by_tool,
        )

    def get_current_month_usage(self, organization_id: str) -> UsageSummary:
        """
        Get usage summary for current calendar month.

        Args:
            organization_id: Organization ID

        Returns:
            UsageSummary for current month
        """
        now = datetime.now()
        start_of_month = now.replace(day=1, hour=0, minute=0, second=0, microsecond=0)
        return self.get_usage_summary(organization_id, start_of_month, now)

    def get_recent_usage(
        self,
        organization_id: str,
        limit: int = 50
    ) -> List[dict]:
        """
        Get recent usage records for an organization.

        Args:
            organization_id: Organization ID
            limit: Maximum records to return

        Returns:
            List of usage records, most recent first
        """
        result = self.client.table("token_usage").select("*").eq(
            "organization_id", organization_id
        ).order("created_at", desc=True).limit(limit).execute()

        return result.data or []
