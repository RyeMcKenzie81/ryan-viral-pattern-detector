"""
Pipeline Manager - Centralized data pipeline health, scheduling, and monitoring.

Tabs:
1. Health Overview - Dataset freshness per brand with color-coded status
2. Schedules - Brand-scoped scheduling with cadence presets
3. Active Jobs - All scheduled jobs across brands
4. Run History - Recent job runs with logs
5. Freshness Matrix - Brand x dataset grid view
"""

import streamlit as st
from datetime import datetime, timedelta, timezone
from typing import Dict, List, Optional
import pytz

# Page config (must be first)
st.set_page_config(
    page_title="Pipeline Manager",
    page_icon="🔧",
    layout="wide"
)

# Authentication
from viraltracker.ui.auth import require_auth
require_auth()

PST = pytz.timezone("America/Los_Angeles")

# Known job types and their display info
JOB_TYPE_INFO = {
    "meta_sync": {"emoji": "🔄", "label": "Meta Sync", "default_params": {"days_back": 7}},
    "template_scrape": {"emoji": "📥", "label": "Template Scrape", "default_params": {"max_ads": 50}},
    "ad_classification": {"emoji": "🏷️", "label": "Ad Classification", "default_params": {"max_new": 200}},
    "asset_download": {"emoji": "📦", "label": "Asset Download", "default_params": {"max_videos": 20, "max_images": 40}},
    "scorecard": {"emoji": "📊", "label": "Scorecard", "default_params": {"days_back": 7}},
    "template_approval": {"emoji": "✅", "label": "Template Approval", "default_params": {"max_templates": 50}},
    "congruence_reanalysis": {"emoji": "🔍", "label": "Congruence Reanalysis", "default_params": {}},
    "competitor_scrape": {"emoji": "🕵️", "label": "Competitor Scrape", "default_params": {"max_ads": 500}},
    "reddit_scrape": {"emoji": "🔍", "label": "Reddit Scrape", "default_params": {"max_posts": 500}},
    "amazon_review_scrape": {"emoji": "📦", "label": "Amazon Review Scrape", "default_params": {}},
    "ad_creation": {"emoji": "🎨", "label": "Ad Creation", "default_params": {}},
}

CADENCE_PRESETS = {
    "On-demand only": None,
    "Twice daily": "0 6,18 * * *",
    "Daily": "0 6 * * *",
    "Weekly": "0 6 * * 1",
    "Monthly": "0 6 1 * *",
}

# Platform-level jobs (no brand_id)
PLATFORM_JOB_TYPES = ["template_approval", "template_scrape"]

# Brand-scoped schedulable types (exclude platform jobs and ad_creation which has its own scheduler)
BRAND_SCHEDULABLE_TYPES = [
    "meta_sync", "ad_classification", "asset_download",
    "scorecard", "congruence_reanalysis",
]

# Dataset keys and their labels
DATASET_LABELS = {
    "meta_ads_performance": "Ad Performance",
    "ad_thumbnails": "Thumbnails",
    "ad_assets": "Ad Assets",
    "ad_classifications": "Classifications",
    "templates_scraped": "Templates Scraped",
    "templates_evaluated": "Templates Evaluated",
    "competitor_ads": "Competitor Ads",
    "reddit_data": "Reddit Data",
    "amazon_reviews": "Amazon Reviews",
    "landing_pages": "Landing Pages",
}


# ============================================================================
# Database Helpers
# ============================================================================

def get_supabase_client():
    from viraltracker.core.database import get_supabase_client
    return get_supabase_client()


def get_brands() -> List[Dict]:
    """Fetch all brands."""
    try:
        db = get_supabase_client()
        result = db.table("brands").select("id, name").order("name").execute()
        return result.data or []
    except Exception as e:
        st.error(f"Failed to fetch brands: {e}")
        return []


def get_dataset_statuses(brand_id: Optional[str] = None) -> List[Dict]:
    """Fetch dataset_status rows, optionally filtered by brand."""
    try:
        db = get_supabase_client()
        query = db.table("dataset_status").select("*")
        if brand_id:
            query = query.eq("brand_id", brand_id)
        result = query.order("dataset_key").execute()
        return result.data or []
    except Exception:
        return []


def get_scheduled_jobs_all(status_filter: Optional[str] = None) -> List[Dict]:
    """Fetch scheduled jobs with brand info."""
    try:
        db = get_supabase_client()
        query = db.table("scheduled_jobs").select(
            "*, products(name, brands(name))"
        )
        if status_filter:
            query = query.eq("status", status_filter)
        else:
            query = query.in_("status", ["active", "paused", "completed"])

        result = query.order("created_at", desc=True).execute()
        jobs = result.data or []

        # Fetch brand names for jobs without products
        brand_ids_needed = set()
        for job in jobs:
            if not job.get("products") and job.get("brand_id"):
                brand_ids_needed.add(job["brand_id"])

        brand_map = {}
        if brand_ids_needed:
            brands_result = db.table("brands").select("id, name").in_(
                "id", list(brand_ids_needed)
            ).execute()
            brand_map = {b["id"]: b["name"] for b in (brands_result.data or [])}

        for job in jobs:
            if not job.get("products") and job.get("brand_id"):
                job["_brand_name"] = brand_map.get(job["brand_id"], "Unknown")
            elif job.get("products"):
                brand_info = job["products"].get("brands", {}) or {}
                job["_brand_name"] = brand_info.get("name", "Unknown")
            else:
                job["_brand_name"] = "Platform"

        return jobs
    except Exception as e:
        st.error(f"Failed to fetch jobs: {e}")
        return []


def get_job_runs(
    limit: int = 50,
    brand_id: Optional[str] = None,
    job_type: Optional[str] = None,
    status: Optional[str] = None,
) -> List[Dict]:
    """Fetch recent job runs with job details."""
    try:
        db = get_supabase_client()
        query = db.table("scheduled_job_runs").select(
            "id, scheduled_job_id, status, started_at, completed_at, "
            "error_message, logs, "
            "scheduled_jobs(name, job_type, brand_id)"
        )
        if status:
            query = query.eq("status", status)
        result = query.order("started_at", desc=True).limit(limit).execute()
        runs = result.data or []

        # Apply brand/job_type filters (post-query since they're on joined table)
        if brand_id:
            runs = [r for r in runs if (r.get("scheduled_jobs") or {}).get("brand_id") == brand_id]
        if job_type:
            runs = [r for r in runs if (r.get("scheduled_jobs") or {}).get("job_type") == job_type]

        return runs
    except Exception:
        return []


# ============================================================================
# Formatting Helpers
# ============================================================================

def format_age(dt_str: Optional[str]) -> str:
    """Format a datetime string as a human-readable age."""
    if not dt_str:
        return "never"
    try:
        dt = datetime.fromisoformat(dt_str)
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        age = datetime.now(timezone.utc) - dt
        hours = age.total_seconds() / 3600
        if hours < 1:
            return f"{int(hours * 60)}m ago"
        elif hours < 48:
            return f"{hours:.0f}h ago"
        else:
            return f"{hours / 24:.0f}d ago"
    except (ValueError, TypeError):
        return "unknown"


def freshness_color(dt_str: Optional[str], max_age_hours: float = 24) -> str:
    """Return a status color based on freshness."""
    if not dt_str:
        return "🔴"
    try:
        dt = datetime.fromisoformat(dt_str)
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        hours = (datetime.now(timezone.utc) - dt).total_seconds() / 3600
        if hours <= max_age_hours:
            return "🟢"
        elif hours <= max_age_hours * 2:
            return "🟡"
        else:
            return "🔴"
    except (ValueError, TypeError):
        return "🔴"


def format_datetime_pst(dt_str: Optional[str]) -> str:
    """Format datetime string to PST display."""
    if not dt_str:
        return "—"
    try:
        dt = datetime.fromisoformat(dt_str.replace("Z", "+00:00"))
        if dt.tzinfo is None:
            dt = PST.localize(dt)
        else:
            dt = dt.astimezone(PST)
        return dt.strftime("%b %d, %I:%M %p")
    except (ValueError, TypeError):
        return dt_str


# ============================================================================
# Tab 1: Health Overview
# ============================================================================

def render_health_overview():
    """Show dataset freshness per brand with color-coded status."""
    st.subheader("Dataset Health by Brand")

    brands = get_brands()
    if not brands:
        st.info("No brands found.")
        return

    brand_filter = st.selectbox(
        "Select Brand",
        options=["All Brands"] + [b["name"] for b in brands],
        key="health_brand_filter",
    )

    if brand_filter == "All Brands":
        selected_brands = brands
    else:
        selected_brands = [b for b in brands if b["name"] == brand_filter]

    for brand in selected_brands:
        statuses = get_dataset_statuses(brand["id"])
        status_map = {s["dataset_key"]: s for s in statuses}

        with st.expander(f"**{brand['name']}**", expanded=(len(selected_brands) == 1)):
            if not statuses:
                st.caption("No dataset status records yet. Run a sync to populate.")
                # Show Run Now for meta_sync
                if st.button("🔄 Run Meta Sync", key=f"run_meta_{brand['id']}"):
                    from viraltracker.services.pipeline_helpers import queue_one_time_job
                    job_id = queue_one_time_job(brand["id"], "meta_sync", parameters={"days_back": 7})
                    if job_id:
                        st.success("Meta sync queued!")
                    else:
                        st.error("Failed to queue job.")
                continue

            cols = st.columns(min(len(statuses), 4))
            for i, (dk, label) in enumerate(DATASET_LABELS.items()):
                status = status_map.get(dk)
                col = cols[i % len(cols)]
                with col:
                    if status:
                        color = freshness_color(status.get("last_success_at"))
                        last_success = format_age(status.get("last_success_at"))
                        st.markdown(f"{color} **{label}**")
                        st.caption(f"Last success: {last_success}")

                        if status.get("last_status") == "running":
                            st.caption("⏳ Currently running")
                        elif status.get("last_status") == "failed":
                            err = status.get("error_message", "")
                            st.caption(f"❌ Last attempt failed")
                            if err:
                                st.caption(f"Error: {err[:100]}")

                        if status.get("records_affected"):
                            st.caption(f"Records: {status['records_affected']}")
                    else:
                        st.markdown(f"⚪ **{label}**")
                        st.caption("No data")

            # Run Now buttons
            st.markdown("---")
            health_run_types = ["meta_sync", "ad_classification", "asset_download"]
            run_cols = st.columns(len(health_run_types))
            for i, jt in enumerate(health_run_types):
                info = JOB_TYPE_INFO.get(jt, {})
                with run_cols[i]:
                    if st.button(
                        f"{info.get('emoji', '▶️')} Run {info.get('label', jt)}",
                        key=f"run_{jt}_{brand['id']}",
                    ):
                        from viraltracker.services.pipeline_helpers import queue_one_time_job
                        job_id = queue_one_time_job(
                            brand["id"], jt, parameters=info.get("default_params", {})
                        )
                        if job_id:
                            st.success(f"{info.get('label', jt)} queued!")
                        else:
                            st.error("Failed to queue job.")


# ============================================================================
# Tab 2: Schedules
# ============================================================================

def render_schedules():
    """Brand-scoped scheduling with cadence presets."""
    st.subheader("Recurring Schedules")

    from viraltracker.ui.utils import render_brand_selector
    brand_id = render_brand_selector(key="pipeline_schedules_brand")
    if not brand_id:
        st.info("Select a brand to manage schedules.")
        return

    # Fetch existing recurring jobs for this brand
    try:
        db = get_supabase_client()
        result = db.table("scheduled_jobs").select("*").eq(
            "brand_id", brand_id
        ).eq("schedule_type", "recurring").in_(
            "status", ["active", "paused"]
        ).execute()
        existing_jobs = {j["job_type"]: j for j in (result.data or [])}
    except Exception:
        existing_jobs = {}

    for jt in BRAND_SCHEDULABLE_TYPES:
        info = JOB_TYPE_INFO.get(jt, {"emoji": "❓", "label": jt, "default_params": {}})
        existing = existing_jobs.get(jt)

        with st.expander(
            f"{info['emoji']} **{info['label']}** — "
            f"{'🟢 Active' if existing and existing.get('status') == 'active' else '⏸️ Paused' if existing else '⚪ Not configured'}",
            expanded=False,
        ):
            col1, col2 = st.columns([2, 1])

            with col1:
                # Cadence selector
                current_cron = existing.get("cron_expression", "") if existing else ""
                # Determine current preset
                current_preset = "On-demand only"
                for preset_name, preset_cron in CADENCE_PRESETS.items():
                    if preset_cron and preset_cron == current_cron:
                        current_preset = preset_name
                        break
                else:
                    if current_cron and existing:
                        current_preset = "Advanced"

                preset_options = list(CADENCE_PRESETS.keys()) + ["Advanced"]
                preset_idx = preset_options.index(current_preset) if current_preset in preset_options else 0

                cadence = st.selectbox(
                    "Cadence",
                    options=preset_options,
                    index=preset_idx,
                    key=f"cadence_{jt}",
                )

                if cadence == "Advanced":
                    cron_expr = st.text_input(
                        "Cron Expression",
                        value=current_cron,
                        key=f"cron_{jt}",
                        help="Standard cron format: minute hour day-of-month month day-of-week",
                    )
                else:
                    cron_expr = CADENCE_PRESETS.get(cadence)

                # Show next run preview
                if cron_expr:
                    try:
                        from viraltracker.worker.scheduler_worker import calculate_next_run
                        next_run = calculate_next_run(cron_expr)
                        if next_run:
                            st.caption(f"Next run: {next_run.strftime('%b %d at %I:%M %p PST')}")
                        else:
                            st.warning("Invalid cron expression")
                    except Exception:
                        st.caption("Could not preview next run")

            with col2:
                # Status toggle
                enabled = st.checkbox(
                    "Enabled",
                    value=existing.get("status") == "active" if existing else False,
                    key=f"enabled_{jt}",
                )

                # Parameters
                params = existing.get("parameters", info["default_params"]) if existing else info["default_params"]
                if params:
                    st.markdown("**Parameters:**")
                    for pk, pv in params.items():
                        st.caption(f"{pk}: {pv}")

            # Action buttons
            btn_col1, btn_col2 = st.columns(2)
            with btn_col1:
                if st.button("💾 Save Schedule", key=f"save_{jt}"):
                    if cadence == "On-demand only":
                        # Pause or don't create
                        if existing:
                            db = get_supabase_client()
                            db.table("scheduled_jobs").update(
                                {"status": "paused"}
                            ).eq("id", existing["id"]).execute()
                            st.success(f"{info['label']} paused.")
                            st.rerun()
                        else:
                            st.info("No schedule to save (on-demand only).")
                    elif cron_expr:
                        from viraltracker.services.pipeline_helpers import ensure_recurring_job
                        job_id = ensure_recurring_job(
                            brand_id=brand_id,
                            job_type=jt,
                            cron_expression=cron_expr,
                            parameters=params,
                            enabled=enabled,
                        )
                        if job_id:
                            st.success(f"{info['label']} schedule saved!")
                            st.rerun()
                        else:
                            st.error("Failed to save schedule.")
                    else:
                        st.warning("Select a cadence first.")

            with btn_col2:
                if st.button("▶️ Run Now", key=f"runnow_{jt}"):
                    from viraltracker.services.pipeline_helpers import queue_one_time_job
                    job_id = queue_one_time_job(
                        brand_id=brand_id,
                        job_type=jt,
                        parameters=params,
                    )
                    if job_id:
                        st.success(f"{info['label']} queued for immediate run!")
                    else:
                        st.error("Failed to queue job.")


def _get_last_run_info(job_id: str) -> Optional[Dict]:
    """Get the most recent run status/time for a scheduled job."""
    try:
        db = get_supabase_client()
        result = db.table("scheduled_job_runs").select(
            "status, started_at, completed_at, error_message"
        ).eq("scheduled_job_id", job_id).order(
            "started_at", desc=True
        ).limit(1).execute()
        return result.data[0] if result.data else None
    except Exception:
        return None


def render_platform_schedules():
    """Platform-level scheduling for jobs that aren't brand-scoped."""
    st.subheader("Platform Schedules")
    st.caption("These jobs run across all brands and don't require a brand selector.")

    # Fetch existing recurring platform jobs (brand_id IS NULL)
    try:
        db = get_supabase_client()
        result = db.table("scheduled_jobs").select("*").is_(
            "brand_id", "null"
        ).eq("schedule_type", "recurring").in_(
            "status", ["active", "paused"]
        ).execute()
        existing_jobs = {j["job_type"]: j for j in (result.data or [])}
    except Exception:
        existing_jobs = {}

    for jt in PLATFORM_JOB_TYPES:
        info = JOB_TYPE_INFO.get(jt, {"emoji": "❓", "label": jt, "default_params": {}})
        existing = existing_jobs.get(jt)

        with st.expander(
            f"{info['emoji']} **{info['label']}** — "
            f"{'🟢 Active' if existing and existing.get('status') == 'active' else '⏸️ Paused' if existing else '⚪ Not configured'}",
            expanded=False,
        ):
            # Show last run info
            if existing:
                last_run = _get_last_run_info(existing["id"])
                if last_run:
                    run_status = last_run.get("status", "unknown")
                    run_emoji = {"completed": "✅", "failed": "❌", "running": "⏳"}.get(run_status, "❓")
                    st.caption(f"Last run: {run_emoji} {run_status} — {format_age(last_run.get('started_at'))}")
                    if last_run.get("error_message"):
                        st.caption(f"Error: {last_run['error_message'][:100]}")

            col1, col2 = st.columns([2, 1])

            with col1:
                # Cadence selector
                current_cron = existing.get("cron_expression", "") if existing else ""
                current_preset = "On-demand only"
                for preset_name, preset_cron in CADENCE_PRESETS.items():
                    if preset_cron and preset_cron == current_cron:
                        current_preset = preset_name
                        break
                else:
                    if current_cron and existing:
                        current_preset = "Advanced"

                preset_options = list(CADENCE_PRESETS.keys()) + ["Advanced"]
                preset_idx = preset_options.index(current_preset) if current_preset in preset_options else 0

                cadence = st.selectbox(
                    "Cadence",
                    options=preset_options,
                    index=preset_idx,
                    key=f"platform_cadence_{jt}",
                )

                if cadence == "Advanced":
                    cron_expr = st.text_input(
                        "Cron Expression",
                        value=current_cron,
                        key=f"platform_cron_{jt}",
                        help="Standard cron format: minute hour day-of-month month day-of-week",
                    )
                else:
                    cron_expr = CADENCE_PRESETS.get(cadence)

                # Show next run preview
                if cron_expr:
                    try:
                        from viraltracker.worker.scheduler_worker import calculate_next_run
                        next_run = calculate_next_run(cron_expr)
                        if next_run:
                            st.caption(f"Next run: {next_run.strftime('%b %d at %I:%M %p PST')}")
                        else:
                            st.warning("Invalid cron expression")
                    except Exception:
                        st.caption("Could not preview next run")

            with col2:
                # Status toggle
                enabled = st.checkbox(
                    "Enabled",
                    value=existing.get("status") == "active" if existing else False,
                    key=f"platform_enabled_{jt}",
                )

                # Parameters (editable for platform jobs)
                params = existing.get("parameters", info["default_params"]) if existing else info["default_params"]
                params = dict(params) if params else {}

                if jt == "template_scrape":
                    st.markdown("**Parameters:**")
                    params["search_url"] = st.text_input(
                        "Search URL",
                        value=params.get("search_url", ""),
                        key=f"platform_param_search_url_{jt}",
                        help="Facebook Ad Library search URL to scrape",
                    )
                    params["max_ads"] = st.number_input(
                        "Max Ads",
                        value=int(params.get("max_ads", 50)),
                        min_value=1, max_value=500,
                        key=f"platform_param_max_ads_{jt}",
                    )
                elif params:
                    st.markdown("**Parameters:**")
                    for pk, pv in params.items():
                        st.caption(f"{pk}: {pv}")

            # Action buttons
            btn_col1, btn_col2 = st.columns(2)
            with btn_col1:
                if st.button("💾 Save Schedule", key=f"platform_save_{jt}"):
                    if cadence == "On-demand only":
                        if existing:
                            db = get_supabase_client()
                            db.table("scheduled_jobs").update(
                                {"status": "paused"}
                            ).eq("id", existing["id"]).execute()
                            st.success(f"{info['label']} paused.")
                            st.rerun()
                        else:
                            st.info("No schedule to save (on-demand only).")
                    elif cron_expr:
                        from viraltracker.services.pipeline_helpers import ensure_recurring_job
                        job_id = ensure_recurring_job(
                            brand_id=None,
                            job_type=jt,
                            cron_expression=cron_expr,
                            parameters=params,
                            enabled=enabled,
                        )
                        if job_id:
                            st.success(f"{info['label']} schedule saved!")
                            st.rerun()
                        else:
                            st.error("Failed to save schedule.")
                    else:
                        st.warning("Select a cadence first.")

            with btn_col2:
                if st.button("▶️ Run Now", key=f"platform_runnow_{jt}"):
                    from viraltracker.services.pipeline_helpers import queue_one_time_job
                    job_id = queue_one_time_job(
                        brand_id=None,
                        job_type=jt,
                        parameters=params,
                    )
                    if job_id:
                        st.success(f"{info['label']} queued for immediate run!")
                    else:
                        st.error("Failed to queue job.")


# ============================================================================
# Tab 3: Active Jobs
# ============================================================================

def render_active_jobs():
    """Show all scheduled jobs across brands."""
    st.subheader("Active & Paused Jobs")

    col1, col2 = st.columns(2)
    with col1:
        status_options = ["All Active", "Active", "Paused", "Completed"]
        status_sel = st.selectbox("Status", options=status_options, key="jobs_status_filter")
    with col2:
        type_options = ["All Types"] + list(JOB_TYPE_INFO.keys())
        type_sel = st.selectbox(
            "Job Type",
            options=type_options,
            format_func=lambda x: JOB_TYPE_INFO.get(x, {}).get("label", x) if x != "All Types" else x,
            key="jobs_type_filter",
        )

    status_val = None
    if status_sel == "Active":
        status_val = "active"
    elif status_sel == "Paused":
        status_val = "paused"
    elif status_sel == "Completed":
        status_val = "completed"

    jobs = get_scheduled_jobs_all(status_filter=status_val)

    if type_sel != "All Types":
        jobs = [j for j in jobs if j.get("job_type") == type_sel]

    if not jobs:
        st.info("No jobs found for the selected filters.")
        return

    st.markdown(f"**{len(jobs)} job(s)**")

    for job in jobs:
        jt = job.get("job_type", "ad_creation")
        info = JOB_TYPE_INFO.get(jt, {"emoji": "❓", "label": jt})
        status = job.get("status", "active")
        status_emoji = {"active": "🟢", "paused": "⏸️", "completed": "✅"}.get(status, "❓")
        brand_name = job.get("_brand_name", "Unknown")

        with st.container():
            col1, col2, col3, col4 = st.columns([3, 2, 2, 1])

            with col1:
                st.markdown(f"{status_emoji} {info['emoji']} **{job['name']}**")
                st.caption(f"{brand_name} · {info['label']}")

            with col2:
                if job.get("next_run_at"):
                    st.markdown(f"Next: **{format_datetime_pst(job['next_run_at'])}**")
                else:
                    st.markdown("Next: **—**")
                if job.get("cron_expression"):
                    st.caption(f"Cron: {job['cron_expression']}")
                st.caption(f"Created: {format_datetime_pst(job.get('created_at'))}")

            with col3:
                runs = f"{job.get('runs_completed', 0)}"
                if job.get("max_runs"):
                    runs += f"/{job['max_runs']}"
                st.markdown(f"Runs: **{runs}**")
                last_run = _get_last_run_info(job["id"])
                if last_run:
                    run_emoji = {"completed": "✅", "failed": "❌", "running": "⏳"}.get(last_run.get("status", ""), "")
                    st.caption(f"Last: {run_emoji} {format_datetime_pst(last_run.get('started_at'))}")
                if job.get("last_error"):
                    st.caption(f"⚠️ {job['last_error'][:60]}")

            with col4:
                if status == "active":
                    if st.button("⏸️", key=f"pause_{job['id']}", help="Pause"):
                        db = get_supabase_client()
                        db.table("scheduled_jobs").update(
                            {"status": "paused"}
                        ).eq("id", job["id"]).execute()
                        st.rerun()
                elif status == "paused":
                    if st.button("▶️", key=f"resume_{job['id']}", help="Resume"):
                        db = get_supabase_client()
                        from viraltracker.worker.scheduler_worker import calculate_next_run
                        updates = {"status": "active"}
                        if job.get("cron_expression"):
                            next_run = calculate_next_run(job["cron_expression"])
                            if next_run:
                                updates["next_run_at"] = next_run.isoformat()
                        db.table("scheduled_jobs").update(updates).eq("id", job["id"]).execute()
                        st.rerun()

            st.divider()


# ============================================================================
# Tab 4: Run History
# ============================================================================

def render_run_history():
    """Show recent job runs with expandable logs."""
    st.subheader("Recent Job Runs")

    col1, col2, col3 = st.columns(3)
    with col1:
        brands = get_brands()
        brand_options = {"All": None}
        brand_options.update({b["name"]: b["id"] for b in brands})
        brand_sel = st.selectbox("Brand", options=list(brand_options.keys()), key="runs_brand")
        brand_val = brand_options[brand_sel]

    with col2:
        type_options = {"All Types": None}
        type_options.update({v["label"]: k for k, v in JOB_TYPE_INFO.items()})
        type_sel = st.selectbox("Job Type", options=list(type_options.keys()), key="runs_type")
        type_val = type_options[type_sel]

    with col3:
        status_options = {"All": None, "Completed": "completed", "Failed": "failed", "Running": "running"}
        status_sel = st.selectbox("Status", options=list(status_options.keys()), key="runs_status")
        status_val = status_options[status_sel]

    runs = get_job_runs(
        limit=50,
        brand_id=brand_val,
        job_type=type_val,
        status=status_val,
    )

    if not runs:
        st.info("No runs found for the selected filters.")
        return

    st.markdown(f"**{len(runs)} run(s)**")

    for run in runs:
        job_info = run.get("scheduled_jobs") or {}
        job_name = job_info.get("name", "Unknown")
        jt = job_info.get("job_type", "ad_creation")
        info = JOB_TYPE_INFO.get(jt, {"emoji": "❓", "label": jt})

        run_status = run.get("status", "unknown")
        status_emoji = {
            "completed": "✅",
            "failed": "❌",
            "running": "⏳",
            "pending": "⏱️",
        }.get(run_status, "❓")

        started = format_datetime_pst(run.get("started_at"))
        completed = format_datetime_pst(run.get("completed_at"))

        # Calculate duration
        duration_str = ""
        if run.get("started_at") and run.get("completed_at"):
            try:
                s = datetime.fromisoformat(run["started_at"].replace("Z", "+00:00"))
                c = datetime.fromisoformat(run["completed_at"].replace("Z", "+00:00"))
                dur = (c - s).total_seconds()
                if dur < 60:
                    duration_str = f"{dur:.0f}s"
                else:
                    duration_str = f"{dur / 60:.1f}m"
            except (ValueError, TypeError):
                pass

        with st.container():
            col1, col2, col3 = st.columns([3, 2, 1])

            with col1:
                st.markdown(f"{status_emoji} {info['emoji']} **{job_name}**")
                st.caption(f"Started: {started}")

            with col2:
                if completed != "—":
                    st.caption(f"Completed: {completed}")
                if duration_str:
                    st.caption(f"Duration: {duration_str}")

            with col3:
                if run.get("error_message"):
                    st.caption(f"❌ {run['error_message'][:60]}")

            # Expandable logs
            if run.get("logs"):
                with st.expander("📋 Logs", expanded=False):
                    st.code(run["logs"], language="text")

            st.divider()


# ============================================================================
# Tab 5: Freshness Matrix
# ============================================================================

def render_freshness_matrix():
    """Brand x dataset grid view of freshness."""
    st.subheader("Dataset Freshness Matrix")

    brands = get_brands()
    if not brands:
        st.info("No brands found.")
        return

    all_statuses = get_dataset_statuses()

    # Build matrix: brand_id -> dataset_key -> status
    matrix = {}
    for s in all_statuses:
        bid = s["brand_id"]
        if bid not in matrix:
            matrix[bid] = {}
        matrix[bid][s["dataset_key"]] = s

    # Determine which dataset keys exist
    all_keys = sorted(set(s["dataset_key"] for s in all_statuses))
    if not all_keys:
        st.info("No dataset status records yet. Run some sync jobs to populate.")
        return

    # Header row
    header_cols = st.columns([2] + [1] * len(all_keys))
    with header_cols[0]:
        st.markdown("**Brand**")
    for i, dk in enumerate(all_keys):
        with header_cols[i + 1]:
            label = DATASET_LABELS.get(dk, dk.replace("_", " ").title())
            st.markdown(f"**{label}**")

    st.divider()

    # Data rows
    for brand in brands:
        brand_statuses = matrix.get(brand["id"], {})
        if not brand_statuses:
            continue

        row_cols = st.columns([2] + [1] * len(all_keys))
        with row_cols[0]:
            st.markdown(brand["name"])

        for i, dk in enumerate(all_keys):
            with row_cols[i + 1]:
                status = brand_statuses.get(dk)
                if status:
                    color = freshness_color(status.get("last_success_at"))
                    age = format_age(status.get("last_success_at"))
                    last_status = status.get("last_status", "")

                    if last_status == "running":
                        st.markdown(f"⏳ {age}")
                    elif last_status == "failed":
                        st.markdown(f"{color} {age} ❌")
                    else:
                        st.markdown(f"{color} {age}")
                else:
                    st.markdown("⚪ —")


# ============================================================================
# Tab 6: Amazon Reviews
# ============================================================================

def render_amazon_reviews():
    """Scrape and analyze Amazon reviews per product."""
    st.subheader("Amazon Review Scraping & Analysis")
    st.markdown("Re-scrape Amazon reviews to pick up new reviews, then re-analyze.")

    from viraltracker.ui.utils import render_brand_selector
    brand_id = render_brand_selector(key="amazon_reviews_brand")
    if not brand_id:
        st.info("Select a brand to manage Amazon reviews.")
        return

    # Fetch products with Amazon URLs for this brand
    try:
        db = get_supabase_client()
        url_result = db.table("amazon_product_urls").select(
            "id, product_id, amazon_url, asin, total_reviews_scraped, last_scraped_at, "
            "products(name)"
        ).eq("brand_id", brand_id).execute()
    except Exception as e:
        st.error(f"Failed to fetch Amazon URLs: {e}")
        return

    if not url_result.data:
        st.info("No Amazon product URLs configured for this brand. Add URLs in Brand Manager or URL Mapping.")
        return

    # Group by product
    products = {}
    for row in url_result.data:
        pid = row["product_id"]
        if pid not in products:
            product_info = row.get("products") or {}
            products[pid] = {
                "name": product_info.get("name", "Unknown Product"),
                "urls": [],
            }
        products[pid]["urls"].append(row)

    # Initialize session state for running status
    if "amazon_scrape_running" not in st.session_state:
        st.session_state.amazon_scrape_running = False

    for pid, product_data in products.items():
        product_name = product_data["name"]
        urls = product_data["urls"]
        total_scraped = sum((u.get("total_reviews_scraped") or 0) for u in urls)
        asins = ", ".join(u.get("asin", "?") for u in urls)

        # Last scraped date
        scrape_dates = [u.get("last_scraped_at") for u in urls if u.get("last_scraped_at")]
        last_scraped = max(scrape_dates) if scrape_dates else None

        with st.expander(f"**{product_name}** — {total_scraped} reviews | ASIN: {asins}", expanded=True):
            col1, col2, col3 = st.columns([2, 1, 1])

            with col1:
                st.caption(f"Last scraped: {format_age(last_scraped) if last_scraped else 'never'}")
                for u in urls:
                    st.caption(f"ASIN {u.get('asin', '?')}: {u.get('total_reviews_scraped', 0) or 0} reviews")

                # Check for analysis
                try:
                    analysis = db.table("amazon_review_analysis").select(
                        "analyzed_at, total_reviews_analyzed"
                    ).eq("product_id", pid).execute()
                    if analysis.data:
                        a = analysis.data[0]
                        st.caption(f"Analysis: {a.get('total_reviews_analyzed', 0)} reviews analyzed ({format_age(a.get('analyzed_at'))})")
                    else:
                        st.caption("Analysis: not yet run")
                except Exception:
                    pass

            with col2:
                if st.button(
                    "Re-scrape Reviews",
                    key=f"pm_scrape_{pid}",
                    disabled=st.session_state.amazon_scrape_running,
                ):
                    st.session_state.amazon_scrape_running = True
                    with st.spinner(f"Scraping reviews for {product_name} (2-5 min)..."):
                        try:
                            from viraltracker.services.amazon_review_service import AmazonReviewService
                            from uuid import UUID
                            service = AmazonReviewService()
                            total_saved = 0
                            for url_row in urls:
                                result = service.scrape_reviews_for_product(
                                    product_id=UUID(pid),
                                    amazon_url=url_row["amazon_url"],
                                )
                                total_saved += result.reviews_saved
                            st.success(f"Scrape complete! {total_saved} reviews saved.")
                        except Exception as e:
                            st.error(f"Scrape failed: {e}")
                    st.session_state.amazon_scrape_running = False
                    st.rerun()

            with col3:
                if st.button(
                    "Analyze Reviews",
                    key=f"pm_analyze_{pid}",
                    disabled=st.session_state.amazon_scrape_running,
                    type="primary",
                ):
                    st.session_state.amazon_scrape_running = True
                    with st.spinner(f"Analyzing reviews for {product_name} (30-60s)..."):
                        try:
                            from viraltracker.services.amazon_review_service import AmazonReviewService
                            from viraltracker.ui.utils import setup_tracking_context
                            from uuid import UUID
                            import asyncio
                            service = AmazonReviewService()
                            setup_tracking_context(service)

                            result = asyncio.run(
                                service.analyze_reviews_for_product(UUID(pid))
                            )

                            if result:
                                st.success("Analysis complete!")
                            else:
                                st.warning("No reviews found to analyze. Scrape first.")
                        except Exception as e:
                            st.error(f"Analysis failed: {e}")
                    st.session_state.amazon_scrape_running = False
                    st.rerun()


# ============================================================================
# Main Page
# ============================================================================

st.title("🔧 Pipeline Manager")
st.markdown("Centralized data pipeline health, scheduling, and monitoring.")

tab1, tab2, tab3, tab4, tab5, tab6 = st.tabs([
    "🏥 Health Overview",
    "📅 Schedules",
    "📋 Active Jobs",
    "📜 Run History",
    "📊 Freshness Matrix",
    "📦 Amazon Reviews",
])

with tab1:
    render_health_overview()

with tab2:
    sub_brand, sub_platform = st.tabs(["🏢 Brand Schedules", "🌐 Platform Schedules"])
    with sub_brand:
        render_schedules()
    with sub_platform:
        render_platform_schedules()

with tab3:
    render_active_jobs()

with tab4:
    render_run_history()

with tab5:
    render_freshness_matrix()

with tab6:
    render_amazon_reviews()
