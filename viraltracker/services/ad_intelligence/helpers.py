"""Shared helpers for the Ad Intelligence service layer.

Cross-cutting utilities used by classifier, baseline, diagnostic, fatigue,
and coverage services. Includes:
- Active ad query (anchored to run's date_range_end, NOT today)
- Org/brand validation
- Conversion extraction from Meta JSONB action arrays
"""

from __future__ import annotations

import logging
from datetime import date, timedelta
from typing import Any, Dict, List, Optional
from uuid import UUID

logger = logging.getLogger(__name__)


# =============================================================================
# Safe Numeric Coercion
# =============================================================================

def _safe_numeric(value: Any) -> Optional[float]:
    """Coerce str/int/float to float. Returns None on failure (no exceptions).

    Handles Meta API values that may be strings, ints, or floats:
    - "12" -> 12.0
    - 12 -> 12.0
    - 12.0 -> 12.0
    - "abc", None, [], {} -> None
    """
    if value is None:
        return None
    try:
        return float(value)
    except (ValueError, TypeError):
        return None


# =============================================================================
# Conversion Extraction Helpers
# =============================================================================

def extract_conversions(perf_row: Dict, conversion_event: str) -> Optional[int]:
    """Extract conversion count for the given event from Meta action arrays.

    Searches perf_row['raw_actions'] for action_type matching conversion_event.
    Returns None if not found (distinct from 0).

    Also falls back to pre-extracted columns for common events:
    - "purchase" -> perf_row["purchases"]
    - "add_to_cart" -> perf_row["add_to_carts"]

    Args:
        perf_row: A meta_ads_performance row dict.
        conversion_event: Meta action_type string (e.g., "purchase", "lead").

    Returns:
        Integer count or None if event not found.
    """
    # Try raw_actions JSONB array first (most flexible)
    actions = perf_row.get("raw_actions")
    if isinstance(actions, list):
        for action in actions:
            if not isinstance(action, dict):
                continue
            if action.get("action_type") == conversion_event:
                val = _safe_numeric(action.get("value"))
                if val is not None:
                    return int(val)

    # Fallback to pre-extracted columns for common events
    if conversion_event == "purchase":
        val = _safe_numeric(perf_row.get("purchases"))
        if val is not None:
            return int(val)
    elif conversion_event == "add_to_cart":
        val = _safe_numeric(perf_row.get("add_to_carts"))
        if val is not None:
            return int(val)

    return None


def extract_conversion_value(perf_row: Dict, value_field: str) -> Optional[float]:
    """Extract conversion value for ROAS computation.

    Searches perf_row['raw_actions'] action_values or falls back to
    pre-extracted columns for common fields.

    Args:
        perf_row: A meta_ads_performance row dict.
        value_field: Value field name (e.g., "purchase_value").

    Returns:
        Float value or None if not found.
    """
    # Try pre-extracted column first (e.g., "purchase_value" column)
    val = _safe_numeric(perf_row.get(value_field))
    if val is not None:
        return val

    # Try raw_actions for the action_type matching the value_field
    # Meta stores action values in action_values array
    # value_field like "purchase_value" maps to action_type "purchase"
    action_type = value_field.replace("_value", "")
    actions = perf_row.get("raw_actions")
    if isinstance(actions, list):
        for action in actions:
            if not isinstance(action, dict):
                continue
            if action.get("action_type") == action_type:
                val = _safe_numeric(action.get("value"))
                if val is not None:
                    return val

    return None


def extract_cost_per_conversion(perf_row: Dict, conversion_event: str) -> Optional[float]:
    """Extract cost-per-action for the given event from Meta cost arrays.

    Searches perf_row['raw_costs'] for action_type matching conversion_event.

    Args:
        perf_row: A meta_ads_performance row dict.
        conversion_event: Meta action_type string (e.g., "purchase", "lead").

    Returns:
        Float cost or None if not found.
    """
    # Try raw_costs JSONB array
    costs = perf_row.get("raw_costs")
    if isinstance(costs, list):
        for cost in costs:
            if not isinstance(cost, dict):
                continue
            if cost.get("action_type") == conversion_event:
                val = _safe_numeric(cost.get("value"))
                if val is not None:
                    return val

    # Fallback to pre-extracted columns for common events
    if conversion_event == "add_to_cart":
        return _safe_numeric(perf_row.get("cost_per_add_to_cart"))

    return None


def compute_roas(perf_row: Dict, value_field: str) -> Optional[float]:
    """Compute ROAS = conversion_value / spend.

    Returns None if spend=0 or value missing.

    Args:
        perf_row: A meta_ads_performance row dict.
        value_field: Value field name (e.g., "purchase_value").

    Returns:
        Float ROAS or None.
    """
    # Try pre-extracted roas first (for purchase)
    if value_field == "purchase_value":
        roas = _safe_numeric(perf_row.get("roas"))
        if roas is not None:
            return roas

    spend = _safe_numeric(perf_row.get("spend"))
    if spend is None or spend == 0:
        return None

    value = extract_conversion_value(perf_row, value_field)
    if value is None:
        return None

    return value / spend


# =============================================================================
# Active Ad Query
# =============================================================================

async def get_active_ad_ids(
    supabase,
    brand_id: UUID,
    date_range_end: date,
    active_window_days: int = 7,
) -> List[str]:
    """Return meta_ad_ids that had any impressions or spend within the window.

    Aggregates across all daily rows for each ad.
    Window is relative to date_range_end, NOT today, for reproducibility.

    An ad is "active" if it accumulated any impressions OR spend within the window:
    - date > (date_range_end - active_window_days)
    - date <= date_range_end
    - SUM(impressions) > 0 OR SUM(spend) > 0

    Args:
        supabase: Supabase client instance.
        brand_id: Brand UUID to filter by.
        date_range_end: End of analysis window (anchor date).
        active_window_days: Number of days to look back from date_range_end.

    Returns:
        List of meta_ad_id strings. Empty list if no active ads found.
    """
    window_start = date_range_end - timedelta(days=active_window_days)

    try:
        logger.info(
            f"Querying active ads for brand {brand_id}: "
            f"date > {window_start.isoformat()} AND date <= {date_range_end.isoformat()}"
        )

        result = supabase.table("meta_ads_performance").select(
            "meta_ad_id, impressions, spend, ad_status, date"
        ).eq(
            "brand_id", str(brand_id)
        ).gt(
            "date", window_start.isoformat()
        ).lte(
            "date", date_range_end.isoformat()
        ).execute()

        row_count = len(result.data) if result.data else 0
        logger.info(f"Active ad query returned {row_count} rows")

        if not result.data:
            return []

        # Aggregate per meta_ad_id in Python, track latest status
        ad_totals: Dict[str, Dict[str, float]] = {}
        ad_latest_status: Dict[str, tuple] = {}  # ad_id -> (date, status)
        for row in result.data:
            ad_id = row.get("meta_ad_id")
            if not ad_id:
                continue
            if ad_id not in ad_totals:
                ad_totals[ad_id] = {"impressions": 0.0, "spend": 0.0}

            impr = _safe_numeric(row.get("impressions"))
            if impr is not None:
                ad_totals[ad_id]["impressions"] += impr

            spend = _safe_numeric(row.get("spend"))
            if spend is not None:
                ad_totals[ad_id]["spend"] += spend

            # Track the most recent ad_status per ad
            row_date = row.get("date", "")
            row_status = row.get("ad_status")
            if row_status and (ad_id not in ad_latest_status or row_date > ad_latest_status[ad_id][0]):
                ad_latest_status[ad_id] = (row_date, row_status)

        # Filter: SUM(impressions) > 0 OR SUM(spend) > 0
        # Also exclude ads where the latest status is not ACTIVE
        excluded_statuses = {"PAUSED", "DELETED", "ARCHIVED", "DISAPPROVED"}
        active_ids = []
        excluded_count = 0
        for ad_id, totals in ad_totals.items():
            if totals["impressions"] <= 0 and totals["spend"] <= 0:
                continue
            latest = ad_latest_status.get(ad_id)
            if latest and latest[1] in excluded_statuses:
                excluded_count += 1
                continue
            active_ids.append(ad_id)

        if excluded_count > 0:
            logger.info(f"Excluded {excluded_count} paused/deleted ads from active set")

        logger.info(
            f"Found {len(active_ids)} active ads for brand {brand_id} "
            f"in window ({window_start}, {date_range_end}]"
        )
        return active_ids

    except Exception as e:
        logger.error(f"Error fetching active ad IDs for brand {brand_id}: {e}")
        return []


# =============================================================================
# Org / Brand Validation
# =============================================================================

async def validate_org_brand(supabase, org_id: UUID, brand_id: UUID) -> None:
    """Validate that a brand belongs to an organization.

    Called once at run creation. All downstream operations inherit the
    validated run's org_id/brand_id pair.

    Args:
        supabase: Supabase client instance.
        org_id: Organization UUID.
        brand_id: Brand UUID.

    Raises:
        ValueError: If brand does not belong to org.
    """
    try:
        result = supabase.table("brands").select("id").eq(
            "id", str(brand_id)
        ).eq(
            "organization_id", str(org_id)
        ).execute()

        if not result.data or len(result.data) == 0:
            raise ValueError(
                f"Brand {brand_id} does not belong to organization {org_id}"
            )
    except ValueError:
        raise
    except Exception as e:
        logger.error(f"Error validating org/brand relationship: {e}")
        raise ValueError(
            f"Could not validate brand {brand_id} for org {org_id}: {e}"
        )
