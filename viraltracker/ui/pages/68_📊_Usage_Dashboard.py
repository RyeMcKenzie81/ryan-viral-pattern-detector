"""Usage Dashboard - View usage analytics per organization."""

import streamlit as st

st.set_page_config(page_title="Usage Dashboard", page_icon="📊", layout="wide")

from viraltracker.ui.auth import require_auth, get_current_user_id
require_auth()

import pandas as pd
from datetime import datetime, timedelta
from decimal import Decimal

from viraltracker.core.database import get_supabase_client
from viraltracker.services.usage_tracker import UsageTracker
from viraltracker.services.usage_limit_service import UsageLimitService, LimitType
from viraltracker.services.organization_service import OrganizationService
from viraltracker.ui.utils import (
    render_organization_selector,
    get_current_organization_id,
    is_superuser,
)


# ============================================================================
# Helper functions
# ============================================================================

def _get_tracker():
    return UsageTracker(get_supabase_client())


def _get_limit_service():
    return UsageLimitService(get_supabase_client())


def _get_org_service():
    return OrganizationService(get_supabase_client())


def _format_tokens(n: int) -> str:
    """Format token count for display."""
    if n >= 1_000_000:
        return f"{n / 1_000_000:.1f}M"
    if n >= 1_000:
        return f"{n / 1_000:.1f}K"
    return str(n)


def _format_cost(cost) -> str:
    """Format USD cost for display."""
    return f"${float(cost):.2f}"


# ============================================================================
# Render helpers
# ============================================================================

def render_summary_metrics(summary):
    """Render the 4 top-level metric cards."""
    col1, col2, col3, col4 = st.columns(4)
    with col1:
        st.metric("Total Cost", _format_cost(summary.total_cost_usd))
    with col2:
        total_tokens = summary.total_input_tokens + summary.total_output_tokens
        st.metric("Total Tokens", _format_tokens(total_tokens))
    with col3:
        st.metric("API Calls", f"{summary.total_requests:,}")
    with col4:
        st.metric(
            "In / Out Tokens",
            f"{_format_tokens(summary.total_input_tokens)} / {_format_tokens(summary.total_output_tokens)}",
        )


def render_limit_bars(limit_statuses):
    """Render progress bars for configured usage limits."""
    if not limit_statuses:
        return

    st.subheader("Usage Limits")

    for status in limit_statuses:
        if status["limit_value"] is None:
            continue

        lt = status["limit_type"]
        display = lt.replace("_", " ").title()
        pct = min(status["usage_pct"], 1.0)
        current = status["current_usage"]
        limit_val = status["limit_value"]

        # Format values based on type
        if "cost" in lt:
            current_str = f"${current:.2f}"
            limit_str = f"${limit_val:.2f}"
        elif "tokens" in lt:
            current_str = _format_tokens(int(current))
            limit_str = _format_tokens(int(limit_val))
        else:
            current_str = f"{int(current):,}"
            limit_str = f"{int(limit_val):,}"

        pct_display = f"{pct * 100:.0f}%"
        label = f"{display}: {pct_display} ({current_str} / {limit_str})"

        if not status["enabled"]:
            label += " (disabled)"

        st.progress(pct, text=label)

        if status["is_exceeded"]:
            st.error(f"{display} limit exceeded!")
        elif status["is_warning"]:
            st.warning(f"{display} approaching limit ({pct_display})")


def render_provider_breakdown(summary):
    """Render a table of usage by provider."""
    if not summary.by_provider:
        st.info("No usage data for this period.")
        return

    rows = []
    total_cost = float(summary.total_cost_usd) if summary.total_cost_usd else 0
    for provider, data in sorted(
        summary.by_provider.items(), key=lambda x: float(x[1]["cost"]), reverse=True
    ):
        cost = float(data["cost"])
        pct = (cost / total_cost * 100) if total_cost > 0 else 0
        rows.append({
            "Provider": provider.title(),
            "Tokens": f"{data['tokens']:,}",
            "Cost": f"${cost:.2f}",
            "% Total": f"{pct:.0f}%",
        })

    st.dataframe(pd.DataFrame(rows), use_container_width=True, hide_index=True)


def render_tool_breakdown(summary):
    """Render a table of usage by tool/service."""
    if not summary.by_tool:
        st.info("No usage data for this period.")
        return

    rows = []
    total_cost = float(summary.total_cost_usd) if summary.total_cost_usd else 0
    for tool, data in sorted(
        summary.by_tool.items(), key=lambda x: float(x[1]["cost"]), reverse=True
    ):
        cost = float(data["cost"])
        pct = (cost / total_cost * 100) if total_cost > 0 else 0
        rows.append({
            "Tool": tool.replace("_", " ").title(),
            "Tokens": f"{data['tokens']:,}",
            "Cost": f"${cost:.2f}",
            "% Total": f"{pct:.0f}%",
        })

    st.dataframe(pd.DataFrame(rows), use_container_width=True, hide_index=True)


def render_recent_activity(records):
    """Render a table of recent usage records."""
    if not records:
        st.info("No recent activity.")
        return

    rows = []
    for r in records:
        cost = r.get("cost_usd")
        cost_str = f"${float(cost):.4f}" if cost else "-"
        total = (r.get("input_tokens", 0) or 0) + (r.get("output_tokens", 0) or 0)
        rows.append({
            "Time": r.get("created_at", "")[:19].replace("T", " "),
            "Provider": (r.get("provider") or "").title(),
            "Model": r.get("model", ""),
            "Tool": (r.get("tool_name") or "").replace("_", " ").title(),
            "Operation": (r.get("operation") or "").replace("_", " ").title(),
            "Tokens": f"{total:,}" if total else "-",
            "Cost": cost_str,
        })

    st.dataframe(pd.DataFrame(rows), use_container_width=True, hide_index=True)


def render_cross_org_comparison():
    """Render cross-org usage comparison (superuser only)."""
    org_service = _get_org_service()
    tracker = _get_tracker()

    orgs = org_service.get_all_organizations()
    if not orgs:
        st.info("No organizations found.")
        return

    rows = []
    for org in orgs:
        try:
            summary = tracker.get_current_month_usage(org["id"])
            member_count = org_service.get_member_count(org["id"])
            rows.append({
                "Organization": org["name"],
                "Members": member_count,
                "API Calls": summary.total_requests,
                "Tokens": _format_tokens(summary.total_input_tokens + summary.total_output_tokens),
                "Cost": _format_cost(summary.total_cost_usd),
            })
        except Exception:
            rows.append({
                "Organization": org["name"],
                "Members": "-",
                "API Calls": "-",
                "Tokens": "-",
                "Cost": "-",
            })

    st.dataframe(pd.DataFrame(rows), use_container_width=True, hide_index=True)


# ============================================================================
# Main page
# ============================================================================

st.title("📊 Usage Dashboard")

# Organization selector
org_id = render_organization_selector(key="usage_dash_org_selector")
if not org_id:
    st.stop()

# Date range selector
col_date1, col_date2 = st.columns(2)
with col_date1:
    range_option = st.selectbox(
        "Time Period",
        ["Current Month", "Last 7 Days", "Last 30 Days", "Custom"],
        key="usage_dash_range",
    )

now = datetime.now()
if range_option == "Current Month":
    start_date = now.replace(day=1, hour=0, minute=0, second=0, microsecond=0)
    end_date = now
elif range_option == "Last 7 Days":
    start_date = now - timedelta(days=7)
    end_date = now
elif range_option == "Last 30 Days":
    start_date = now - timedelta(days=30)
    end_date = now
else:
    with col_date2:
        custom_start = st.date_input("Start Date", value=now.replace(day=1).date(), key="usage_dash_start")
        custom_end = st.date_input("End Date", value=now.date(), key="usage_dash_end")
        start_date = datetime.combine(custom_start, datetime.min.time())
        end_date = datetime.combine(custom_end, datetime.max.time())

st.divider()

# Get data
tracker = _get_tracker()

if org_id == "all":
    # Superuser: show cross-org comparison
    st.subheader("Cross-Organization Comparison (Current Month)")
    render_cross_org_comparison()
    st.divider()
    st.info("Select a specific organization above to view detailed usage.")
    st.stop()

# Org-specific view
summary = tracker.get_usage_summary(org_id, start_date, end_date)

# Summary metrics
render_summary_metrics(summary)

st.divider()

# Usage limits
limit_service = _get_limit_service()
try:
    limit_statuses = limit_service.check_all_limits(org_id)
    render_limit_bars(limit_statuses)
except Exception:
    pass  # Limits table may not exist yet

st.divider()

# Breakdown tabs
tab_provider, tab_tool, tab_recent = st.tabs(["By Provider", "By Tool", "Recent Activity"])

with tab_provider:
    render_provider_breakdown(summary)

with tab_tool:
    render_tool_breakdown(summary)

with tab_recent:
    recent = tracker.get_recent_usage(org_id, limit=100)
    render_recent_activity(recent)
