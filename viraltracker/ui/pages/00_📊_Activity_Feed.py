"""
Activity Feed - Operating console for ViralTracker.

Shows a reverse-chronological timeline of everything the system has done:
- Attention strip (errors, retrying jobs)
- In-progress jobs
- "While you were away" summary
- Filterable timeline of all events
"""

import streamlit as st
from datetime import datetime, timedelta
from typing import List, Dict, Optional
import pytz

# Page config (must be first)
st.set_page_config(
    page_title="Activity Feed",
    page_icon="📊",
    layout="wide"
)

# Authentication
from viraltracker.ui.auth import require_auth, get_current_user_id
require_auth()

from viraltracker.ui.utils import (
    get_current_organization_id,
    render_brand_selector,
    job_type_badge,
)

# PST timezone
PST = pytz.timezone('America/Los_Angeles')


# ============================================================================
# Database Functions
# ============================================================================

def get_supabase_client():
    from viraltracker.core.database import get_supabase_client
    return get_supabase_client()


def get_feed_state(user_id: str) -> Optional[Dict]:
    """Get user's feed state (last_seen_at, filter_preferences)."""
    try:
        db = get_supabase_client()
        result = db.table("user_feed_state").select("*").eq(
            "user_id", user_id
        ).limit(1).execute()
        return result.data[0] if result.data else None
    except Exception:
        return None


def update_feed_state(user_id: str):
    """Upsert last_seen_at for the current user."""
    try:
        db = get_supabase_client()
        db.table("user_feed_state").upsert({
            "user_id": user_id,
            "last_seen_at": datetime.now(PST).isoformat(),
        }).execute()
    except Exception:
        pass


def get_activity_events(
    org_id: Optional[str],
    brand_id: Optional[str] = None,
    severity_filter: Optional[str] = None,
    since: Optional[datetime] = None,
    limit: int = 50,
    offset: int = 0,
) -> List[Dict]:
    """Fetch activity events with filters."""
    try:
        db = get_supabase_client()
        query = db.table("activity_events").select("*")

        # Multi-tenant filtering
        if org_id and org_id != "all":
            query = query.eq("organization_id", org_id)

        if brand_id:
            query = query.eq("brand_id", brand_id)

        if severity_filter == "errors":
            query = query.eq("severity", "error")
        elif severity_filter == "success":
            query = query.eq("severity", "success")

        if since:
            query = query.gte("created_at", since.isoformat())

        # Exclude job_started events from timeline (they're noise)
        query = query.neq("event_type", "job_started")

        result = query.order(
            "created_at", desc=True
        ).range(offset, offset + limit - 1).execute()

        return result.data or []
    except Exception as e:
        st.error(f"Failed to load activity events: {e}")
        return []


def get_attention_events(org_id: Optional[str], brand_id: Optional[str] = None) -> List[Dict]:
    """Get error and retrying events from last 24h for the attention strip."""
    try:
        db = get_supabase_client()
        cutoff = (datetime.now(PST) - timedelta(hours=24)).isoformat()
        query = db.table("activity_events").select("*")

        if org_id and org_id != "all":
            query = query.eq("organization_id", org_id)
        if brand_id:
            query = query.eq("brand_id", brand_id)

        result = query.in_(
            "severity", ["error", "warning"]
        ).gte(
            "created_at", cutoff
        ).order("created_at", desc=True).limit(10).execute()

        return result.data or []
    except Exception:
        return []


def get_in_progress_runs(org_id: Optional[str], brand_id: Optional[str] = None) -> List[Dict]:
    """Get currently running job runs."""
    try:
        db = get_supabase_client()
        query = db.table("scheduled_job_runs").select(
            "id, scheduled_job_id, started_at, "
            "scheduled_jobs(name, job_type, brand_id)"
        ).eq("status", "running")

        result = query.order("started_at", desc=True).limit(20).execute()

        runs = result.data or []

        # Filter by org/brand in Python (no direct org_id on runs table)
        if (org_id and org_id != "all") or brand_id:
            filtered = []
            for run in runs:
                job_info = run.get("scheduled_jobs") or {}
                run_brand_id = job_info.get("brand_id")
                if brand_id and run_brand_id != brand_id:
                    continue
                # For org filtering, we'd need brand->org lookup. Skip for now.
                filtered.append(run)
            runs = filtered

        return runs
    except Exception:
        return []


def get_while_you_were_away_summary(
    org_id: Optional[str],
    brand_id: Optional[str],
    last_seen_at: datetime,
) -> Dict:
    """Compute summary of events since last_seen_at."""
    try:
        db = get_supabase_client()
        # Cap at 7 days
        cap = datetime.now(PST) - timedelta(days=7)
        since = max(last_seen_at, cap)

        query = db.table("activity_events").select("severity, event_type, details")
        if org_id and org_id != "all":
            query = query.eq("organization_id", org_id)
        if brand_id:
            query = query.eq("brand_id", brand_id)

        result = query.gte("created_at", since.isoformat()).execute()
        events = result.data or []

        failures = sum(1 for e in events if e.get("severity") == "error")
        successes = sum(1 for e in events if e.get("severity") == "success")
        warnings = sum(1 for e in events if e.get("severity") == "warning")
        total = len(events)

        return {
            "failures": failures,
            "successes": successes,
            "warnings": warnings,
            "total": total,
            "since": since,
        }
    except Exception:
        return {"failures": 0, "successes": 0, "warnings": 0, "total": 0, "since": last_seen_at}


def get_brand_name_map(org_id: Optional[str]) -> Dict[str, str]:
    """Get brand_id -> brand_name mapping for display."""
    try:
        db = get_supabase_client()
        query = db.table("brands").select("id, name")
        if org_id and org_id != "all":
            query = query.eq("organization_id", org_id)
        result = query.execute()
        return {b["id"]: b["name"] for b in (result.data or [])}
    except Exception:
        return {}


# ============================================================================
# Retry Logic
# ============================================================================

def retry_job(job_id: str):
    """Create a one-time retry job that runs in ~1 minute (Run Now pattern)."""
    try:
        db = get_supabase_client()
        retry_at = (datetime.now(PST) + timedelta(minutes=1)).isoformat()
        db.table("scheduled_jobs").update({
            "next_run_at": retry_at,
            "status": "active",
            "last_error": None,
        }).eq("id", job_id).execute()
        return True
    except Exception as e:
        st.error(f"Failed to schedule retry: {e}")
        return False


# ============================================================================
# Rendering Helpers
# ============================================================================

SEVERITY_ICONS = {
    "error": "🔴",
    "warning": "🟡",
    "success": "🟢",
    "info": "🔵",
}


def format_time_ago(dt_str: str) -> str:
    """Format a datetime string as relative time (e.g. '2h ago')."""
    try:
        dt = datetime.fromisoformat(dt_str.replace('Z', '+00:00'))
        if dt.tzinfo is None:
            dt = PST.localize(dt)
        else:
            dt = dt.astimezone(PST)
        now = datetime.now(PST)
        delta = now - dt
        if delta.total_seconds() < 60:
            return "just now"
        elif delta.total_seconds() < 3600:
            return f"{int(delta.total_seconds() / 60)}m ago"
        elif delta.total_seconds() < 86400:
            return f"{int(delta.total_seconds() / 3600)}h ago"
        else:
            return dt.strftime("%b %d, %I:%M %p")
    except Exception:
        return dt_str


def format_time_pst(dt_str: str) -> str:
    """Format datetime to PST time display."""
    try:
        dt = datetime.fromisoformat(dt_str.replace('Z', '+00:00'))
        if dt.tzinfo is None:
            dt = PST.localize(dt)
        else:
            dt = dt.astimezone(PST)
        return dt.strftime("%I:%M %p")
    except Exception:
        return dt_str


def format_duration(ms: Optional[int]) -> str:
    """Format duration_ms to human-readable string."""
    if ms is None:
        return ""
    if ms < 1000:
        return f"{ms}ms"
    secs = ms / 1000
    if secs < 60:
        return f"{secs:.1f}s"
    mins = secs / 60
    if mins < 60:
        return f"{mins:.0f}m {int(secs % 60)}s"
    hours = mins / 60
    return f"{hours:.0f}h {int(mins % 60)}m"


def render_attention_strip(events: List[Dict], brand_names: Dict[str, str]):
    """Render the attention strip for errors/warnings."""
    if not events:
        return

    errors = [e for e in events if e.get("severity") == "error"]
    warnings = [e for e in events if e.get("severity") == "warning"]

    if errors:
        with st.container():
            st.markdown(
                f"**🔴 {len(errors)} failure{'s' if len(errors) != 1 else ''} need attention**"
            )
            for event in errors[:5]:
                brand_name = brand_names.get(event.get("brand_id", ""), "")
                brand_prefix = f"**{brand_name}** — " if brand_name else ""
                st.markdown(
                    f"  {brand_prefix}{event.get('title', 'Unknown error')}"
                    f"  · {format_time_ago(event.get('created_at', ''))}"
                )

    if warnings:
        with st.container():
            st.markdown(
                f"**🟡 {len(warnings)} job{'s' if len(warnings) != 1 else ''} retrying**"
            )


def render_in_progress(runs: List[Dict]):
    """Render in-progress job runs."""
    if not runs:
        return

    with st.expander(f"**⏳ {len(runs)} job{'s' if len(runs) != 1 else ''} in progress**", expanded=True):
        for run in runs:
            job_info = run.get("scheduled_jobs") or {}
            job_name = job_info.get("name", "Unknown")
            job_type = job_info.get("job_type", "")
            emoji, _ = job_type_badge(job_type)
            started = format_time_ago(run.get("started_at", ""))
            st.markdown(f"{emoji} **{job_name}** — started {started}")


def render_while_you_were_away(summary: Dict, last_seen_at: datetime):
    """Render the while-you-were-away summary."""
    now = datetime.now(PST)
    # Hide if last seen less than 1 hour ago
    if (now - last_seen_at).total_seconds() < 3600:
        return

    since_str = last_seen_at.strftime("%b %d, %I:%M %p")
    total = summary.get("total", 0)
    if total == 0:
        return

    with st.container():
        st.markdown(f"### While you were away")
        st.caption(f"Since {since_str}")

        parts = []
        failures = summary.get("failures", 0)
        successes = summary.get("successes", 0)
        warnings = summary.get("warnings", 0)

        if failures:
            parts.append(f"🔴 **{failures}** failure{'s' if failures != 1 else ''}")
        if successes:
            parts.append(f"🟢 **{successes}** completed successfully")
        if warnings:
            parts.append(f"🟡 **{warnings}** retried/recovered")

        for part in parts:
            st.markdown(f"- {part}")

        st.divider()


def render_event_card(event: Dict, brand_names: Dict[str, str]):
    """Render a single event in the timeline."""
    severity = event.get("severity", "info")
    icon = SEVERITY_ICONS.get(severity, "🔵")
    title = event.get("title", "Unknown event")
    created_at = event.get("created_at", "")
    details = event.get("details") or {}
    brand_id = event.get("brand_id")
    brand_name = brand_names.get(brand_id, "") if brand_id else ""
    duration_ms = event.get("duration_ms")
    event_type = event.get("event_type", "")

    # Build the event line
    time_str = format_time_pst(created_at)
    time_ago = format_time_ago(created_at)
    brand_prefix = f"**{brand_name}** — " if brand_name else ""
    duration_suffix = f" ({format_duration(duration_ms)})" if duration_ms else ""

    st.markdown(f"{icon} `{time_str}` {brand_prefix}{title}{duration_suffix}")

    # Error details
    error_msg = details.get("error") or details.get("error_message")
    if error_msg and severity == "error":
        st.caption(f"> {error_msg[:200]}")

    # Retry info for retrying events
    if event_type == "job_retrying":
        next_at = details.get("next_attempt_at")
        if next_at:
            st.caption(f"Next attempt: {format_time_pst(next_at)}")

    # Rich details for specific event types
    if event_type == "ads_generated":
        parts = []
        if details.get("content_source"):
            parts.append(f"source: {details['content_source']}")
        if details.get("templates_used"):
            parts.append(f"templates: {len(details['templates_used'])}")
        if parts:
            st.caption(" · ".join(parts))
    elif event_type == "templates_scraped":
        parts = []
        if details.get("queued"):
            parts.append(f"queued for review: {details['queued']}")
        if details.get("max_ads"):
            parts.append(f"limit: {details['max_ads']}")
        if parts:
            st.caption(" · ".join(parts))
    elif event_type == "sync_completed":
        days = details.get("days_back")
        if days:
            st.caption(f"synced last {days} days")

    # Metadata for completed jobs
    elif details.get("metadata") and isinstance(details["metadata"], dict):
        meta_parts = []
        for key, val in details["metadata"].items():
            if val is not None and key not in ("job_id", "run_id", "job_name"):
                meta_parts.append(f"{key.replace('_', ' ')}: {val}")
        if meta_parts:
            st.caption(" · ".join(meta_parts[:4]))

    # Action buttons
    job_id = details.get("job_id")
    cols = st.columns([1, 1, 6])
    if severity == "error" and job_id:
        retry_key = f"retry_{event.get('id', '')}"
        retried_key = f"retried_{event.get('id', '')}"
        with cols[0]:
            if st.session_state.get(retried_key):
                st.markdown("✅ *Retry scheduled*")
            elif st.button("🔄 Retry", key=retry_key, type="secondary"):
                if retry_job(job_id):
                    st.session_state[retried_key] = True
                    st.rerun()

    link_page = event.get("link_page")
    if link_page and job_id:
        with cols[1]:
            if st.button("📋 View", key=f"view_{event.get('id', '')}"):
                st.query_params["job_id"] = job_id
                # Map page slugs to actual page files
                page_map = {
                    "ad_scheduler": "pages/24_📅_Ad_Scheduler.py",
                    "scheduled_tasks": "pages/61_📅_Scheduled_Tasks.py",
                }
                page_file = page_map.get(link_page, f"pages/{link_page}")
                try:
                    st.switch_page(page_file)
                except Exception:
                    pass


# ============================================================================
# Main Page
# ============================================================================

st.title("📊 Activity Feed")

# Get user context
user_id = get_current_user_id()
org_id = get_current_organization_id()

# Read last_seen_at BEFORE updating it (for while-you-were-away)
feed_state = get_feed_state(user_id) if user_id else None
last_seen_at = None
if feed_state and feed_state.get("last_seen_at"):
    try:
        last_seen_at = datetime.fromisoformat(
            feed_state["last_seen_at"].replace('Z', '+00:00')
        )
        if last_seen_at.tzinfo is None:
            last_seen_at = PST.localize(last_seen_at)
        else:
            last_seen_at = last_seen_at.astimezone(PST)
    except Exception:
        last_seen_at = None

# Filters
col1, col2, col3 = st.columns([3, 2, 1])

with col1:
    brand_id = render_brand_selector(key="activity_feed_brand")

with col2:
    time_range = st.selectbox(
        "Time range",
        options=["24h", "7d", "30d"],
        format_func=lambda x: {"24h": "Last 24 hours", "7d": "Last 7 days", "30d": "Last 30 days"}[x],
        key="activity_time_range",
    )

with col3:
    if st.button("🔄 Refresh"):
        st.rerun()

# Compute time filter
time_map = {"24h": timedelta(hours=24), "7d": timedelta(days=7), "30d": timedelta(days=30)}
since = datetime.now(PST) - time_map.get(time_range, timedelta(hours=24))

st.divider()

# Get brand names for display
brand_names = get_brand_name_map(org_id)

# ---- Attention Strip ----
attention_events = get_attention_events(org_id, brand_id)
render_attention_strip(attention_events, brand_names)

# ---- In Progress ----
in_progress = get_in_progress_runs(org_id, brand_id)
render_in_progress(in_progress)

# ---- While You Were Away ----
if last_seen_at:
    summary = get_while_you_were_away_summary(org_id, brand_id, last_seen_at)
    render_while_you_were_away(summary, last_seen_at)

# ---- Filter Tabs ----
tab_all, tab_failures, tab_success = st.tabs(["All", "Failures", "Success"])

# Pagination state
if "feed_page" not in st.session_state:
    st.session_state.feed_page = 0

PAGE_SIZE = 50

with tab_all:
    events = get_activity_events(org_id, brand_id, severity_filter=None, since=since, limit=PAGE_SIZE)
    if events:
        for event in events:
            render_event_card(event, brand_names)
            st.markdown("---")
        if len(events) >= PAGE_SIZE:
            if st.button("Show more", key="more_all"):
                more = get_activity_events(
                    org_id, brand_id, severity_filter=None, since=since,
                    limit=PAGE_SIZE, offset=PAGE_SIZE,
                )
                for event in more:
                    render_event_card(event, brand_names)
                    st.markdown("---")
    else:
        st.info("No activity events yet. Events will appear here as jobs run.")

with tab_failures:
    events = get_activity_events(org_id, brand_id, severity_filter="errors", since=since, limit=PAGE_SIZE)
    if events:
        for event in events:
            render_event_card(event, brand_names)
            st.markdown("---")
    else:
        st.success("No failures. All systems operational.")

with tab_success:
    events = get_activity_events(org_id, brand_id, severity_filter="success", since=since, limit=PAGE_SIZE)
    if events:
        for event in events:
            render_event_card(event, brand_names)
            st.markdown("---")
    else:
        st.info("No completed events in this time range.")

# Update last_seen_at AFTER rendering (so while-you-were-away works correctly)
if user_id:
    update_feed_state(user_id)
