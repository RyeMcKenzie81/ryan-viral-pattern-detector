"""
Scheduled Tasks Dashboard - View all upcoming scheduled jobs.

A read-only dashboard showing what's coming up across all scheduled jobs:
- Ad Creation jobs
- Meta Sync jobs
- Scorecard jobs
- Template Scrape jobs

Shows jobs grouped by day (Today, Tomorrow, This Week, Later) in PST timezone.
"""

import streamlit as st
from datetime import datetime, timedelta
from typing import List, Dict, Optional
import pytz

# Page config (must be first)
st.set_page_config(
    page_title="Scheduled Tasks",
    page_icon="📅",
    layout="wide"
)

# Authentication
from viraltracker.ui.auth import require_auth
require_auth()

# PST timezone
PST = pytz.timezone('America/Los_Angeles')

# Auto-refresh interval in seconds
AUTO_REFRESH_SECONDS = 60


# ============================================================================
# Database Functions
# ============================================================================

def get_supabase_client():
    """Get Supabase client."""
    from viraltracker.core.database import get_supabase_client
    return get_supabase_client()


def get_all_scheduled_jobs(include_completed_last_24h: bool = True) -> List[Dict]:
    """Fetch all scheduled jobs across all types."""
    try:
        db = get_supabase_client()

        # Fetch active jobs (without direct brands join - no FK relationship)
        result = db.table("scheduled_jobs").select(
            "id, name, job_type, brand_id, product_id, status, next_run_at, "
            "runs_completed, max_runs, schedule_type, cron_expression, parameters, "
            "products(name, brands(name))"
        ).in_("status", ["active", "paused"]).order("next_run_at").execute()

        jobs = result.data or []

        # Collect brand_ids for jobs without products to fetch brand names separately
        brand_ids_needed = set()
        for job in jobs:
            if not job.get('products') and job.get('brand_id'):
                brand_ids_needed.add(job['brand_id'])

        # Fetch brand names for jobs without products
        brand_map = {}
        if brand_ids_needed:
            brands_result = db.table("brands").select("id, name").in_("id", list(brand_ids_needed)).execute()
            brand_map = {b['id']: b['name'] for b in (brands_result.data or [])}

        # Set display names for each job
        for job in jobs:
            if job.get('products'):
                brand_info = job['products'].get('brands', {}) or {}
                job['_brand_name'] = brand_info.get('name', 'Unknown')
                job['_product_name'] = job['products'].get('name', 'Unknown')
            else:
                job['_brand_name'] = brand_map.get(job.get('brand_id'), 'Unknown')
                job['_product_name'] = None

        return jobs
    except Exception as e:
        st.error(f"Failed to fetch scheduled jobs: {e}")
        return []


def get_recent_completed_runs(limit: int = 10) -> List[Dict]:
    """Fetch recently completed job runs (last 24 hours)."""
    try:
        db = get_supabase_client()
        cutoff = (datetime.now(PST) - timedelta(hours=24)).isoformat()

        result = db.table("scheduled_job_runs").select(
            "id, scheduled_job_id, status, started_at, completed_at, "
            "scheduled_jobs(name, job_type, brand_id)"
        ).gte("completed_at", cutoff).order("completed_at", desc=True).limit(limit).execute()

        return result.data or []
    except Exception as e:
        return []


# ============================================================================
# Helper Functions
# ============================================================================

def categorize_by_timeframe(jobs: List[Dict]) -> Dict[str, List[Dict]]:
    """Group jobs by timeframe (Today, Tomorrow, This Week, Later)."""
    now = datetime.now(PST)
    today = now.date()
    tomorrow = today + timedelta(days=1)
    end_of_week = today + timedelta(days=(6 - today.weekday()))  # Sunday

    categories = {
        "today": [],
        "tomorrow": [],
        "this_week": [],
        "later": [],
        "no_next_run": []
    }

    for job in jobs:
        next_run_at = job.get('next_run_at')
        if not next_run_at:
            categories["no_next_run"].append(job)
            continue

        try:
            next_run = datetime.fromisoformat(next_run_at.replace('Z', '+00:00'))
            if next_run.tzinfo is None:
                next_run = PST.localize(next_run)
            else:
                next_run = next_run.astimezone(PST)
            next_run_date = next_run.date()
        except:
            categories["no_next_run"].append(job)
            continue

        if next_run_date == today:
            categories["today"].append(job)
        elif next_run_date == tomorrow:
            categories["tomorrow"].append(job)
        elif next_run_date <= end_of_week:
            categories["this_week"].append(job)
        else:
            categories["later"].append(job)

    return categories


def job_type_badge(job_type: str) -> str:
    """Get emoji and label for job type."""
    badges = {
        'ad_creation': ('🎨', 'Ad Creation'),
        'ad_creation_v2': ('🎨', 'Ad Creation V2'),
        'meta_sync': ('🔄', 'Meta Sync'),
        'scorecard': ('📊', 'Scorecard'),
        'template_scrape': ('📥', 'Template Scrape'),
        'template_approval': ('✅', 'Template Approval'),
        'congruence_reanalysis': ('🔗', 'Congruence Reanalysis'),
        'ad_classification': ('🔬', 'Ad Classification'),
        'asset_download': ('📦', 'Asset Download'),
        'competitor_scrape': ('🕵️', 'Competitor Scrape'),
        'reddit_scrape': ('💬', 'Reddit Scrape'),
        'amazon_review_scrape': ('⭐', 'Amazon Reviews'),
        'ad_intelligence_analysis': ('🧠', 'Ad Intelligence Analysis'),
    }
    return badges.get(job_type, ('❓', job_type))


def format_time_pst(dt_str: str) -> str:
    """Format datetime string to PST time."""
    if not dt_str:
        return "Not scheduled"
    try:
        dt = datetime.fromisoformat(dt_str.replace('Z', '+00:00'))
        if dt.tzinfo is None:
            dt = PST.localize(dt)
        else:
            dt = dt.astimezone(PST)
        return dt.strftime('%I:%M %p')
    except:
        return dt_str


def format_datetime_pst(dt_str: str) -> str:
    """Format datetime string to full PST datetime."""
    if not dt_str:
        return "Not scheduled"
    try:
        dt = datetime.fromisoformat(dt_str.replace('Z', '+00:00'))
        if dt.tzinfo is None:
            dt = PST.localize(dt)
        else:
            dt = dt.astimezone(PST)
        return dt.strftime('%b %d, %I:%M %p PST')
    except:
        return dt_str


def get_job_description(job: Dict) -> str:
    """Get brief description of job parameters."""
    job_type = job.get('job_type', 'ad_creation')
    params = job.get('parameters', {}) or {}

    if job_type == 'ad_creation':
        content = params.get('content_source', 'hooks')
        return f"Content: {content}"
    elif job_type == 'meta_sync':
        days = params.get('days_back', 7)
        return f"Syncs last {days} days"
    elif job_type == 'scorecard':
        days = params.get('days_back', 7)
        return f"Analyzes last {days} days"
    elif job_type == 'template_scrape':
        max_ads = params.get('max_ads', 50)
        return f"Up to {max_ads} ads"
    return ""


# ============================================================================
# UI Components
# ============================================================================

def render_job_card(job: Dict):
    """Render a single job card."""
    job_type = job.get('job_type', 'ad_creation')
    emoji, type_label = job_type_badge(job_type)
    status = job.get('status', 'active')
    status_emoji = '🟢' if status == 'active' else '⏸️'

    brand_name = job.get('_brand_name', 'Unknown')
    product_name = job.get('_product_name')

    # Build subtitle
    if product_name:
        subtitle = f"{brand_name} → {product_name}"
    else:
        subtitle = brand_name

    col1, col2, col3 = st.columns([3, 2, 1])

    with col1:
        st.markdown(f"**{status_emoji} {emoji} {job['name']}**")
        st.caption(subtitle)

    with col2:
        next_run = format_time_pst(job.get('next_run_at'))
        st.markdown(f"**{next_run}**")
        st.caption(get_job_description(job))

    with col3:
        runs = f"{job.get('runs_completed', 0)}"
        if job.get('max_runs'):
            runs += f"/{job['max_runs']}"
        st.markdown(f"Runs: **{runs}**")


def render_job_section(title: str, jobs: List[Dict], expanded: bool = True):
    """Render a section of jobs."""
    if not jobs:
        return

    with st.expander(f"**{title}** ({len(jobs)})", expanded=expanded):
        for job in jobs:
            render_job_card(job)
            st.divider()


def render_recent_runs(runs: List[Dict]):
    """Render recent completed runs."""
    if not runs:
        return

    st.markdown("### Recent Completed Runs (Last 24h)")

    for run in runs:
        job_info = run.get('scheduled_jobs', {}) or {}
        job_name = job_info.get('name', 'Unknown')
        job_type = job_info.get('job_type', 'ad_creation')
        emoji, _ = job_type_badge(job_type)

        status = run.get('status', 'unknown')
        status_emoji = {'completed': '✅', 'failed': '❌'}.get(status, '❓')

        completed_at = format_datetime_pst(run.get('completed_at'))

        st.caption(f"{status_emoji} {emoji} **{job_name}** - {completed_at}")


# ============================================================================
# Main Page
# ============================================================================

st.title("📅 Scheduled Tasks")

# Current time display
now = datetime.now(PST)
st.markdown(f"**Current Time:** {now.strftime('%I:%M %p PST')} ({now.strftime('%A, %B %d, %Y')})")

# Refresh button
col1, col2 = st.columns([6, 1])
with col2:
    if st.button("🔄 Refresh"):
        st.rerun()

st.divider()

# Fetch all scheduled jobs
jobs = get_all_scheduled_jobs()

if not jobs:
    st.info("No scheduled jobs found. Go to the Ad Scheduler page to create one.")
else:
    # Filter options
    col1, col2 = st.columns(2)

    with col1:
        # Job type filter
        job_types = ['All'] + sorted(set(j.get('job_type', 'ad_creation') for j in jobs))
        type_labels = {
            'All': 'All Types',
            'ad_creation': '🎨 Ad Creation',
            'meta_sync': '🔄 Meta Sync',
            'scorecard': '📊 Scorecard',
            'template_scrape': '📥 Template Scrape'
        }
        selected_type = st.selectbox(
            "Filter by Type",
            options=job_types,
            format_func=lambda x: type_labels.get(x, x),
            key="filter_type"
        )

    with col2:
        # Brand filter
        brands = ['All'] + sorted(set(j.get('_brand_name', 'Unknown') for j in jobs))
        selected_brand = st.selectbox(
            "Filter by Brand",
            options=brands,
            key="filter_brand"
        )

    # Apply filters
    filtered_jobs = jobs
    if selected_type != 'All':
        filtered_jobs = [j for j in filtered_jobs if j.get('job_type', 'ad_creation') == selected_type]
    if selected_brand != 'All':
        filtered_jobs = [j for j in filtered_jobs if j.get('_brand_name') == selected_brand]

    st.divider()

    # Categorize by timeframe
    categories = categorize_by_timeframe(filtered_jobs)

    # Summary metrics
    col1, col2, col3, col4 = st.columns(4)
    col1.metric("Today", len(categories["today"]))
    col2.metric("Tomorrow", len(categories["tomorrow"]))
    col3.metric("This Week", len(categories["this_week"]))
    col4.metric("Later", len(categories["later"]))

    st.divider()

    # Render each section
    render_job_section("🔴 Today", categories["today"], expanded=True)
    render_job_section("🟡 Tomorrow", categories["tomorrow"], expanded=True)
    render_job_section("🟢 This Week", categories["this_week"], expanded=False)
    render_job_section("📆 Later", categories["later"], expanded=False)

    if categories["no_next_run"]:
        render_job_section("⏸️ Paused / No Next Run", categories["no_next_run"], expanded=False)

    st.divider()

    # Recent completed runs
    recent_runs = get_recent_completed_runs(limit=5)
    if recent_runs:
        render_recent_runs(recent_runs)
