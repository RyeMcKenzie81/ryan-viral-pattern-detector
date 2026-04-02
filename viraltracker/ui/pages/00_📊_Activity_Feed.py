"""
Activity Feed - Operating console for ViralTracker.

Shows a reverse-chronological timeline of everything the system has done:
- Browser tab unread badge
- Brand health summary cards
- Attention strip (errors, retrying jobs) with dismiss/acknowledge
- In-progress jobs
- "While you were away" summary
- Searchable, filterable timeline of all events
"""

import streamlit as st
from datetime import datetime, timedelta
from typing import List, Dict, Optional
import pytz


# ============================================================================
# Browser Tab Badge — must run before set_page_config
# ============================================================================

def _get_unread_error_count(user_id: Optional[str]) -> int:
    """Count error events since user's last_seen_at (for tab badge)."""
    if not user_id:
        return 0
    try:
        from viraltracker.core.database import get_supabase_client
        db = get_supabase_client()
        state = db.table("user_feed_state").select("last_seen_at").eq(
            "user_id", user_id
        ).limit(1).execute()
        if not state.data or not state.data[0].get("last_seen_at"):
            return 0
        last_seen = state.data[0]["last_seen_at"]
        result = db.table("activity_events").select(
            "id", count="exact"
        ).eq("severity", "error").gte("created_at", last_seen).execute()
        return result.count or 0
    except Exception:
        return 0


# Get user ID early for badge count
try:
    from viraltracker.ui.auth import get_current_user_id
    _badge_user_id = get_current_user_id()
except Exception:
    _badge_user_id = None

_unread_count = _get_unread_error_count(_badge_user_id)
_page_title = f"({_unread_count}) Activity Feed" if _unread_count > 0 else "Activity Feed"

# Page config (must be first Streamlit call)
st.set_page_config(
    page_title=_page_title,
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
    search_query: Optional[str] = None,
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

        if search_query:
            query = query.ilike("title", f"%{search_query}%")

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
    """Get unacknowledged error and retrying events from last 24h for the attention strip."""
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
        ).is_(
            "acknowledged_at", "null"
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


def get_brand_health(org_id: Optional[str], brand_id: Optional[str] = None) -> List[Dict]:
    """Get per-brand health stats for the last 24h."""
    try:
        db = get_supabase_client()
        cutoff = (datetime.now(PST) - timedelta(hours=24)).isoformat()
        query = db.table("activity_events").select("brand_id, severity")
        if org_id and org_id != "all":
            query = query.eq("organization_id", org_id)
        if brand_id:
            query = query.eq("brand_id", brand_id)
        query = query.gte("created_at", cutoff).neq("event_type", "job_started")
        result = query.execute()
        events = result.data or []

        # Aggregate per brand
        brand_stats: Dict[str, Dict] = {}
        for e in events:
            bid = e.get("brand_id")
            if not bid:
                continue
            if bid not in brand_stats:
                brand_stats[bid] = {"successes": 0, "failures": 0, "warnings": 0, "total": 0}
            brand_stats[bid]["total"] += 1
            sev = e.get("severity", "info")
            if sev == "success":
                brand_stats[bid]["successes"] += 1
            elif sev == "error":
                brand_stats[bid]["failures"] += 1
            elif sev == "warning":
                brand_stats[bid]["warnings"] += 1

        return [{"brand_id": bid, **stats} for bid, stats in brand_stats.items()]
    except Exception:
        return []


def acknowledge_event(event_id: str):
    """Mark an event as acknowledged."""
    try:
        db = get_supabase_client()
        db.table("activity_events").update({
            "acknowledged_at": datetime.now(PST).isoformat(),
        }).eq("id", event_id).execute()
        return True
    except Exception:
        return False


def acknowledge_all_errors(org_id: Optional[str], brand_id: Optional[str] = None):
    """Acknowledge all unacknowledged error events from last 24h."""
    try:
        db = get_supabase_client()
        cutoff = (datetime.now(PST) - timedelta(hours=24)).isoformat()
        query = db.table("activity_events").select("id").eq(
            "severity", "error"
        ).gte("created_at", cutoff).is_("acknowledged_at", "null")
        if org_id and org_id != "all":
            query = query.eq("organization_id", org_id)
        if brand_id:
            query = query.eq("brand_id", brand_id)
        result = query.execute()

        if result.data:
            now = datetime.now(PST).isoformat()
            for event in result.data:
                db.table("activity_events").update({
                    "acknowledged_at": now,
                }).eq("id", event["id"]).execute()
        return True
    except Exception:
        return False


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

# Map page slugs to actual page files
PAGE_SLUG_MAP = {
    "ad_scheduler": "pages/24_📅_Ad_Scheduler.py",
    "scheduled_tasks": "pages/61_📅_Scheduled_Tasks.py",
    "ad_history": "pages/22_📊_Ad_History.py",
    "ad_performance": "pages/30_📈_Ad_Performance.py",
    "template_queue": "pages/28_📋_Template_Queue.py",
    "congruence_insights": "pages/34_🔗_Congruence_Insights.py",
    "hook_analysis": "pages/35_🎣_Hook_Analysis.py",
    "competitor_research": "pages/12_🔍_Competitor_Research.py",
    "reddit_research": "pages/15_🔍_Reddit_Research.py",
    "seo_dashboard": "pages/48_🔍_SEO_Dashboard.py",
    "experiments": "pages/36_🧪_Experiments.py",
    "iteration_lab": "pages/38_🔬_Iteration_Lab.py",
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


def render_brand_health_cards(health: List[Dict], brand_names: Dict[str, str]):
    """Render per-brand health summary cards."""
    if not health:
        return

    # Sort: brands with failures first, then by total events descending
    health.sort(key=lambda h: (-h["failures"], -h["total"]))

    # Show up to 6 brands
    visible = health[:6]
    cols = st.columns(min(len(visible), 3))

    for i, h in enumerate(visible):
        bid = h["brand_id"]
        name = brand_names.get(bid, "Unknown")
        total = h["total"]
        failures = h["failures"]
        successes = h["successes"]

        with cols[i % 3]:
            if failures > 0:
                color = "🔴"
                rate = f"{int((successes / total) * 100)}%" if total > 0 else "—"
            elif total > 0:
                color = "🟢"
                rate = f"{int((successes / total) * 100)}%" if total > 0 else "—"
            else:
                color = "⚪"
                rate = "—"

            st.markdown(f"{color} **{name}**")
            st.caption(f"{rate} success · {failures} failures · {total} events (24h)")


def render_attention_strip(events: List[Dict], brand_names: Dict[str, str], org_id: Optional[str], brand_id: Optional[str]):
    """Render the attention strip for errors/warnings with dismiss."""
    if not events:
        return

    errors = [e for e in events if e.get("severity") == "error"]
    warnings = [e for e in events if e.get("severity") == "warning"]

    if errors:
        with st.container():
            header_cols = st.columns([6, 1])
            with header_cols[0]:
                st.markdown(
                    f"**🔴 {len(errors)} failure{'s' if len(errors) != 1 else ''} need attention**"
                )
            with header_cols[1]:
                if st.button("Dismiss all", key="dismiss_all_errors", type="secondary"):
                    acknowledge_all_errors(org_id, brand_id)
                    st.rerun()

            for event in errors[:5]:
                ecols = st.columns([6, 1])
                with ecols[0]:
                    brand_name = brand_names.get(event.get("brand_id", ""), "")
                    brand_prefix = f"**{brand_name}** — " if brand_name else ""
                    st.markdown(
                        f"  {brand_prefix}{event.get('title', 'Unknown error')}"
                        f"  · {format_time_ago(event.get('created_at', ''))}"
                    )
                with ecols[1]:
                    if st.button("✕", key=f"ack_{event.get('id', '')}", help="Acknowledge"):
                        acknowledge_event(event["id"])
                        st.rerun()

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


def _get_thumbnail_public_url(bucket: str, path: str) -> str:
    """Construct a public URL for a Supabase Storage thumbnail."""
    try:
        db = get_supabase_client()
        return db.storage.from_(bucket).get_public_url(path)
    except Exception:
        return ""


def render_media_grid(thumbnail_urls: list, total_count: int):
    """Render a media grid for event cards with thumbnail previews.

    Args:
        thumbnail_urls: List of {"bucket": str, "path": str} tuples
        total_count: Total number of items (for +N overflow badge)
    """
    if not thumbnail_urls:
        return

    # Resolve tuples to public URLs
    urls = []
    for t in thumbnail_urls[:5]:
        if isinstance(t, dict) and t.get("bucket") and t.get("path"):
            url = _get_thumbnail_public_url(t["bucket"], t["path"])
            if url:
                urls.append(url)
        elif isinstance(t, str) and t:
            # Legacy support: plain URL string
            urls.append(t)

    if not urls:
        return

    overflow = max(0, total_count - len(urls))

    if len(urls) <= 2:
        # Simple row layout for 1-2 images
        cols = st.columns(len(urls))
        for i, url in enumerate(urls):
            with cols[i]:
                st.image(url, use_container_width=True)
        if overflow > 0:
            st.caption(f"+{overflow} more")
    else:
        # CSS grid: hero (left, 2 rows) + thumbnails (right column)
        hero_url = urls[0]
        thumb_urls = urls[1:]
        grid_id = f"media-grid-{hash(hero_url) % 100000}"

        # Build thumbnail HTML
        thumb_html_parts = []
        for i, url in enumerate(thumb_urls):
            is_last = (i == len(thumb_urls) - 1) and overflow > 0
            if is_last:
                thumb_html_parts.append(
                    f'<div style="position:relative;overflow:hidden;border-radius:4px;">'
                    f'<img src="{url}" loading="lazy" alt="Thumbnail {i+2}" '
                    f'style="width:100%;height:100%;object-fit:cover;display:block;" '
                    f'onerror="this.parentElement.style.display=\'none\'" />'
                    f'<div style="position:absolute;inset:0;background:rgba(0,0,0,0.55);'
                    f'display:flex;align-items:center;justify-content:center;'
                    f'color:white;font-size:16px;font-weight:600;">+{overflow}</div>'
                    f'</div>'
                )
            else:
                thumb_html_parts.append(
                    f'<div style="overflow:hidden;border-radius:4px;">'
                    f'<img src="{url}" loading="lazy" alt="Thumbnail {i+2}" '
                    f'style="width:100%;height:100%;object-fit:cover;display:block;" '
                    f'onerror="this.parentElement.style.display=\'none\'" />'
                    f'</div>'
                )

        thumbs_html = "\n".join(thumb_html_parts)
        num_thumb_rows = len(thumb_urls)

        grid_html = f'''<div id="{grid_id}" style="display:grid;grid-template-columns:1fr 1fr;grid-template-rows:repeat({num_thumb_rows}, 80px);gap:4px;margin:8px 0;">
  <div style="grid-row:1 / span {num_thumb_rows};overflow:hidden;border-radius:4px;">
    <img src="{hero_url}" loading="lazy" alt="Hero thumbnail"
         style="width:100%;height:100%;object-fit:cover;display:block;"
         onerror="this.parentElement.style.display='none'" />
  </div>
  {thumbs_html}
</div>'''

        st.markdown(grid_html, unsafe_allow_html=True)


def render_event_card(event: Dict, brand_names: Dict[str, str], key_prefix: str = ""):
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
            if val is not None and key not in ("job_id", "run_id", "job_name", "thumbnail_urls", "thumbnail_count"):
                meta_parts.append(f"{key.replace('_', ' ')}: {val}")
        if meta_parts:
            st.caption(" · ".join(meta_parts[:4]))

    # Rich media grid (Phase 3) — thumbnail previews for visual events
    thumbnail_urls = details.get("thumbnail_urls", [])
    thumbnail_count = details.get("thumbnail_count", 0)
    if thumbnail_urls:
        render_media_grid(thumbnail_urls, thumbnail_count)

    # Action buttons
    job_id = details.get("job_id")
    event_id = event.get("id", "")
    cols = st.columns([1, 1, 6])
    if severity == "error" and job_id:
        retry_key = f"{key_prefix}retry_{event_id}"
        retried_key = f"{key_prefix}retried_{event_id}"
        with cols[0]:
            if st.session_state.get(retried_key):
                st.markdown("✅ *Retry scheduled*")
            elif st.button("🔄 Retry", key=retry_key, type="secondary"):
                if retry_job(job_id):
                    st.session_state[retried_key] = True
                    st.rerun()

    link_page = event.get("link_page")
    if link_page:
        page_file = PAGE_SLUG_MAP.get(link_page)
        if page_file:
            with cols[1]:
                if st.button("📋 View", key=f"{key_prefix}view_{event_id}"):
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
col1, col2, col3, col4 = st.columns([3, 2, 2, 1])

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
    search_query = st.text_input("Search events", placeholder="Filter by title...", key="activity_search")

with col4:
    st.markdown("<br>", unsafe_allow_html=True)
    if st.button("🔄 Refresh"):
        st.rerun()

# Compute time filter
time_map = {"24h": timedelta(hours=24), "7d": timedelta(days=7), "30d": timedelta(days=30)}
since = datetime.now(PST) - time_map.get(time_range, timedelta(hours=24))

st.divider()

# Get brand names for display
brand_names = get_brand_name_map(org_id)

# ---- Brand Health Cards ----
brand_health = get_brand_health(org_id, brand_id)
render_brand_health_cards(brand_health, brand_names)

# ---- Attention Strip ----
attention_events = get_attention_events(org_id, brand_id)
render_attention_strip(attention_events, brand_names, org_id, brand_id)

# ---- In Progress ----
in_progress = get_in_progress_runs(org_id, brand_id)
render_in_progress(in_progress)

# ---- While You Were Away ----
if last_seen_at:
    summary = get_while_you_were_away_summary(org_id, brand_id, last_seen_at)
    render_while_you_were_away(summary, last_seen_at)

# ---- Filter Tabs ----
tab_all, tab_failures, tab_success = st.tabs(["All", "Failures", "Success"])

PAGE_SIZE = 50
search_q = search_query.strip() if search_query else None

with tab_all:
    events = get_activity_events(org_id, brand_id, severity_filter=None, since=since, limit=PAGE_SIZE, search_query=search_q)
    if events:
        for event in events:
            render_event_card(event, brand_names, key_prefix="all_")
            st.markdown("---")
        if len(events) >= PAGE_SIZE:
            if st.button("Show more", key="more_all"):
                more = get_activity_events(
                    org_id, brand_id, severity_filter=None, since=since,
                    limit=PAGE_SIZE, offset=PAGE_SIZE, search_query=search_q,
                )
                for event in more:
                    render_event_card(event, brand_names, key_prefix="all2_")
                    st.markdown("---")
    else:
        if search_q:
            st.info(f"No events matching \"{search_q}\".")
        else:
            st.info("No activity events yet. Events will appear here as jobs run.")

with tab_failures:
    events = get_activity_events(org_id, brand_id, severity_filter="errors", since=since, limit=PAGE_SIZE, search_query=search_q)
    if events:
        for event in events:
            render_event_card(event, brand_names, key_prefix="fail_")
            st.markdown("---")
    else:
        st.success("No failures. All systems operational.")

with tab_success:
    events = get_activity_events(org_id, brand_id, severity_filter="success", since=since, limit=PAGE_SIZE, search_query=search_q)
    if events:
        for event in events:
            render_event_card(event, brand_names, key_prefix="ok_")
            st.markdown("---")
    else:
        st.info("No completed events in this time range.")

# Update last_seen_at AFTER rendering (so while-you-were-away works correctly)
if user_id:
    update_feed_state(user_id)
