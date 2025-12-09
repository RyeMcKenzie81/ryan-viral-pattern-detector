"""
Ad Scheduler - Schedule automated ad generation jobs.

This page allows users to:
- View all scheduled jobs with filtering by brand/product
- Create new scheduled jobs (one-time or recurring)
- View job details and run history
- Pause, resume, or delete scheduled jobs
"""

import streamlit as st
from datetime import datetime, timedelta, time
import pytz

# Page config
st.set_page_config(
    page_title="Ad Scheduler",
    page_icon="📅",
    layout="wide"
)

# Authentication
from viraltracker.ui.auth import require_auth
require_auth()

# PST timezone for all scheduling
PST = pytz.timezone('America/Los_Angeles')

# ============================================================================
# Session State Initialization
# ============================================================================

if 'scheduler_view' not in st.session_state:
    st.session_state.scheduler_view = 'list'  # 'list', 'create', 'detail'
if 'selected_job_id' not in st.session_state:
    st.session_state.selected_job_id = None
if 'edit_job_id' not in st.session_state:
    st.session_state.edit_job_id = None

# Form state
if 'sched_product_id' not in st.session_state:
    st.session_state.sched_product_id = None
if 'sched_template_mode' not in st.session_state:
    st.session_state.sched_template_mode = 'unused'
if 'sched_selected_templates' not in st.session_state:
    st.session_state.sched_selected_templates = []
if 'sched_templates_visible' not in st.session_state:
    st.session_state.sched_templates_visible = 30
if 'sched_uploaded_files' not in st.session_state:
    st.session_state.sched_uploaded_files = []


# ============================================================================
# Database Functions
# ============================================================================

def get_supabase_client():
    """Get Supabase client."""
    from viraltracker.core.database import get_supabase_client
    return get_supabase_client()


def get_brands():
    """Fetch all brands."""
    try:
        db = get_supabase_client()
        result = db.table("brands").select("id, name").order("name").execute()
        return result.data or []
    except Exception as e:
        st.error(f"Failed to fetch brands: {e}")
        return []


def get_products(brand_id: str = None):
    """Fetch products, optionally filtered by brand."""
    try:
        db = get_supabase_client()
        query = db.table("products").select(
            "id, name, brand_id, target_audience, brands(id, name, brand_colors)"
        )
        if brand_id:
            query = query.eq("brand_id", brand_id)
        result = query.order("name").execute()
        return result.data or []
    except Exception as e:
        st.error(f"Failed to fetch products: {e}")
        return []


def get_personas_for_product(product_id: str):
    """Get personas linked to a product for the persona selector."""
    try:
        from viraltracker.services.ad_creation_service import AdCreationService
        from uuid import UUID
        service = AdCreationService()
        return service.get_personas_for_product(UUID(product_id))
    except Exception as e:
        return []


def get_scheduled_jobs(brand_id: str = None, product_id: str = None, status: str = None):
    """Fetch scheduled jobs with optional filters."""
    try:
        db = get_supabase_client()
        query = db.table("scheduled_jobs").select(
            "*, products(name, brands(name))"
        )
        if brand_id:
            query = query.eq("brand_id", brand_id)
        if product_id:
            query = query.eq("product_id", product_id)
        if status:
            query = query.eq("status", status)
        result = query.order("created_at", desc=True).execute()
        return result.data or []
    except Exception as e:
        st.error(f"Failed to fetch scheduled jobs: {e}")
        return []


def get_scheduled_job(job_id: str):
    """Fetch a single scheduled job with details."""
    try:
        db = get_supabase_client()
        result = db.table("scheduled_jobs").select(
            "*, products(name, brand_id, brands(name, brand_colors))"
        ).eq("id", job_id).execute()
        return result.data[0] if result.data else None
    except Exception as e:
        st.error(f"Failed to fetch job: {e}")
        return None


def get_job_runs(job_id: str, limit: int = 10):
    """Fetch run history for a scheduled job."""
    try:
        db = get_supabase_client()
        result = db.table("scheduled_job_runs").select("*").eq(
            "scheduled_job_id", job_id
        ).order("started_at", desc=True).limit(limit).execute()
        return result.data or []
    except Exception as e:
        st.error(f"Failed to fetch job runs: {e}")
        return []


def get_existing_templates():
    """Get existing reference ad templates from storage."""
    try:
        db = get_supabase_client()
        result = db.storage.from_("reference-ads").list()

        seen_originals = {}
        for item in result:
            full_name = item.get('name', '')
            if not full_name.lower().endswith(('.jpg', '.jpeg', '.png', '.webp')):
                continue

            parts = full_name.split('_', 1)
            if len(parts) == 2 and len(parts[0]) == 36:
                original_name = parts[1]
            else:
                original_name = full_name

            if original_name not in seen_originals:
                seen_originals[original_name] = {
                    'name': original_name,
                    'storage_name': full_name,
                }

        return sorted(seen_originals.values(), key=lambda x: x['name'].lower())
    except Exception as e:
        st.warning(f"Could not load templates: {e}")
        return []


def get_used_templates(product_id: str):
    """Get templates already used for a product."""
    try:
        db = get_supabase_client()
        result = db.table("product_template_usage").select(
            "template_storage_name"
        ).eq("product_id", product_id).execute()
        return [r['template_storage_name'] for r in (result.data or [])]
    except Exception as e:
        return []


def get_signed_url(storage_path: str) -> str:
    """Get a signed URL for a storage path."""
    try:
        db = get_supabase_client()
        parts = storage_path.split('/', 1)
        if len(parts) == 2:
            bucket, path = parts
        else:
            bucket = "reference-ads"
            path = storage_path
        result = db.storage.from_(bucket).create_signed_url(path, 3600)
        return result.get('signedURL', '')
    except Exception as e:
        return ""


def upload_template_files(files: list) -> list:
    """Upload template files to reference-ads storage and return storage names."""
    import uuid
    db = get_supabase_client()
    storage_names = []

    for file in files:
        # Generate unique storage name: uuid_originalname
        storage_name = f"{uuid.uuid4()}_{file.name}"

        try:
            file_bytes = file.read()
            file.seek(0)  # Reset for potential re-read

            db.storage.from_("reference-ads").upload(
                storage_name,
                file_bytes,
                {"content-type": file.type, "upsert": "true"}
            )
            storage_names.append(storage_name)
        except Exception as e:
            st.error(f"Failed to upload {file.name}: {e}")

    return storage_names


def create_scheduled_job(job_data: dict) -> str:
    """Create a new scheduled job. Returns job ID."""
    try:
        db = get_supabase_client()
        result = db.table("scheduled_jobs").insert(job_data).execute()
        return result.data[0]['id'] if result.data else None
    except Exception as e:
        st.error(f"Failed to create job: {e}")
        return None


def update_scheduled_job(job_id: str, updates: dict):
    """Update a scheduled job."""
    try:
        db = get_supabase_client()
        db.table("scheduled_jobs").update(updates).eq("id", job_id).execute()
        return True
    except Exception as e:
        st.error(f"Failed to update job: {e}")
        return False


def delete_scheduled_job(job_id: str):
    """Delete a scheduled job."""
    try:
        db = get_supabase_client()
        db.table("scheduled_jobs").delete().eq("id", job_id).execute()
        return True
    except Exception as e:
        st.error(f"Failed to delete job: {e}")
        return False


# ============================================================================
# Helper Functions
# ============================================================================

def cron_to_description(cron: str, schedule_type: str) -> str:
    """Convert cron expression to human-readable description."""
    if schedule_type == 'one_time':
        return "One-time"

    if not cron:
        return "Not set"

    parts = cron.split()
    if len(parts) != 5:
        return cron

    minute, hour, day_of_month, month, day_of_week = parts

    days = {
        '0': 'Sunday', '1': 'Monday', '2': 'Tuesday', '3': 'Wednesday',
        '4': 'Thursday', '5': 'Friday', '6': 'Saturday', '7': 'Sunday'
    }

    time_str = f"{int(hour)}:{minute.zfill(2)} PST"

    if day_of_week != '*':
        return f"Weekly on {days.get(day_of_week, day_of_week)}s at {time_str}"
    elif day_of_month != '*':
        return f"Monthly on day {day_of_month} at {time_str}"
    else:
        return f"Daily at {time_str}"


def build_cron_expression(frequency: str, day_of_week: int, hour: int, minute: int = 0) -> str:
    """Build cron expression from UI selections."""
    if frequency == 'daily':
        return f"{minute} {hour} * * *"
    elif frequency == 'weekly':
        return f"{minute} {hour} * * {day_of_week}"
    elif frequency == 'monthly':
        return f"{minute} {hour} 1 * *"
    return None


def calculate_next_run(schedule_type: str, cron: str = None, scheduled_at: datetime = None) -> datetime:
    """Calculate the next run time."""
    now = datetime.now(PST)

    if schedule_type == 'one_time':
        return scheduled_at

    if not cron:
        return None

    parts = cron.split()
    if len(parts) != 5:
        return None

    minute, hour, day_of_month, month, day_of_week = parts
    hour = int(hour)

    # Simple calculation - just find next occurrence
    next_run = now.replace(hour=hour, minute=0, second=0, microsecond=0)

    if day_of_week != '*':
        # Weekly
        target_dow = int(day_of_week)
        days_ahead = target_dow - now.weekday()
        if days_ahead <= 0:
            days_ahead += 7
        if days_ahead == 0 and now.hour >= hour:
            days_ahead = 7
        next_run = next_run + timedelta(days=days_ahead)
    elif day_of_month != '*':
        # Monthly
        if now.day > 1 or (now.day == 1 and now.hour >= hour):
            if now.month == 12:
                next_run = next_run.replace(year=now.year + 1, month=1, day=1)
            else:
                next_run = next_run.replace(month=now.month + 1, day=1)
        else:
            next_run = next_run.replace(day=1)
    else:
        # Daily
        if now.hour >= hour:
            next_run = next_run + timedelta(days=1)

    return next_run


# ============================================================================
# View: Schedule List
# ============================================================================

def render_schedule_list():
    """Render the schedule list view."""
    st.title("📅 Ad Scheduler")
    st.markdown("**Automate ad generation with scheduled jobs**")

    # Action buttons
    col1, col2, col3 = st.columns([1, 1, 4])
    with col1:
        if st.button("➕ Create Schedule", type="primary", use_container_width=True):
            st.session_state.scheduler_view = 'create'
            st.session_state.edit_job_id = None
            st.rerun()
    with col2:
        if st.button("🔄 Refresh", use_container_width=True):
            st.rerun()

    st.divider()

    # Filters
    col1, col2, col3 = st.columns(3)

    brands = get_brands()
    brand_options = {"All Brands": None}
    brand_options.update({b['name']: b['id'] for b in brands})

    with col1:
        selected_brand = st.selectbox(
            "Filter by Brand",
            options=list(brand_options.keys()),
            key="filter_brand"
        )
        brand_filter = brand_options[selected_brand]

    products = get_products(brand_filter)
    product_options = {"All Products": None}
    product_options.update({p['name']: p['id'] for p in products})

    with col2:
        selected_product = st.selectbox(
            "Filter by Product",
            options=list(product_options.keys()),
            key="filter_product"
        )
        product_filter = product_options[selected_product]

    with col3:
        status_filter = st.selectbox(
            "Filter by Status",
            options=["All", "Active", "Paused", "Completed"],
            key="filter_status"
        )
        status_value = status_filter.lower() if status_filter != "All" else None

    st.divider()

    # Fetch and display jobs
    jobs = get_scheduled_jobs(brand_filter, product_filter, status_value)

    if not jobs:
        st.info("No scheduled jobs found. Click 'Create Schedule' to get started!")
        return

    # Display jobs as cards
    for job in jobs:
        product_info = job.get('products', {}) or {}
        brand_info = product_info.get('brands', {}) or {}

        with st.container():
            col1, col2, col3, col4 = st.columns([3, 2, 2, 1])

            with col1:
                status_emoji = {'active': '🟢', 'paused': '⏸️', 'completed': '✅'}.get(job['status'], '❓')
                st.markdown(f"### {status_emoji} {job['name']}")
                st.caption(f"{brand_info.get('name', 'Unknown')} → {product_info.get('name', 'Unknown')}")

            with col2:
                schedule_desc = cron_to_description(job.get('cron_expression'), job['schedule_type'])
                st.markdown(f"**Schedule:** {schedule_desc}")

                if job.get('next_run_at'):
                    next_run = datetime.fromisoformat(job['next_run_at'].replace('Z', '+00:00'))
                    st.caption(f"Next: {next_run.strftime('%b %d, %I:%M %p')}")

            with col3:
                runs = f"{job.get('runs_completed', 0)}"
                if job.get('max_runs'):
                    runs += f" / {job['max_runs']}"
                st.markdown(f"**Runs:** {runs}")

                template_mode = job.get('template_mode', 'unused')
                template_info = f"{job.get('template_count', '?')} templates" if template_mode == 'unused' else f"{len(job.get('template_ids', []))} templates"
                st.caption(f"Mode: {template_mode} ({template_info})")

            with col4:
                if st.button("View", key=f"view_{job['id']}", use_container_width=True):
                    st.session_state.selected_job_id = job['id']
                    st.session_state.scheduler_view = 'detail'
                    st.rerun()

            st.divider()


# ============================================================================
# View: Create/Edit Schedule
# ============================================================================

def render_create_schedule():
    """Render the create/edit schedule form."""
    is_edit = st.session_state.edit_job_id is not None

    st.title("📅 " + ("Edit Schedule" if is_edit else "Create Schedule"))

    # Back button
    if st.button("← Back to List"):
        st.session_state.scheduler_view = 'list'
        st.rerun()

    st.divider()

    # Load existing job data if editing
    existing_job = None
    if is_edit:
        existing_job = get_scheduled_job(st.session_state.edit_job_id)
        if not existing_job:
            st.error("Job not found")
            return

    # ========================================================================
    # Section 1: Product Selection
    # ========================================================================

    st.subheader("1. Select Product")

    products = get_products()
    if not products:
        st.error("No products found")
        return

    product_options = {p['name']: p['id'] for p in products}

    default_product = None
    if existing_job:
        for p in products:
            if p['id'] == existing_job['product_id']:
                default_product = p['name']
                break

    selected_product_name = st.selectbox(
        "Product",
        options=list(product_options.keys()),
        index=list(product_options.keys()).index(default_product) if default_product else 0,
        help="Select the product to create ads for"
    )
    selected_product_id = product_options[selected_product_name]
    selected_product = next((p for p in products if p['id'] == selected_product_id), None)

    if selected_product:
        brand_info = selected_product.get('brands', {})
        st.caption(f"Brand: {brand_info.get('name', 'Unknown')}")

    st.divider()

    # ========================================================================
    # Section 2: Job Name
    # ========================================================================

    st.subheader("2. Job Name")

    job_name = st.text_input(
        "Name for this schedule",
        value=existing_job.get('name', '') if existing_job else "",
        placeholder="e.g., Weekly Ad Refresh - Product X",
        help="A descriptive name to identify this scheduled job"
    )

    st.divider()

    # ========================================================================
    # Section 3: Schedule Configuration
    # ========================================================================

    st.subheader("3. Schedule")

    col1, col2 = st.columns(2)

    # Show current time for reference
    current_time = datetime.now(PST)
    st.info(f"🕐 Current time: **{current_time.strftime('%I:%M %p PST')}** ({current_time.strftime('%b %d, %Y')})")

    with col1:
        schedule_type = st.radio(
            "Schedule Type",
            options=['recurring', 'one_time'],
            index=0 if not existing_job or existing_job['schedule_type'] == 'recurring' else 1,
            format_func=lambda x: "🔄 Recurring" if x == 'recurring' else "1️⃣ One-time",
            horizontal=True
        )

    if schedule_type == 'recurring':
        col1, col2, col3 = st.columns(3)

        with col1:
            frequency = st.selectbox(
                "Frequency",
                options=['daily', 'weekly', 'monthly'],
                index=1,  # Default to weekly
                format_func=lambda x: x.capitalize()
            )

        with col2:
            if frequency == 'weekly':
                day_of_week = st.selectbox(
                    "Day of Week",
                    options=[0, 1, 2, 3, 4, 5, 6],
                    index=0,  # Monday
                    format_func=lambda x: ['Monday', 'Tuesday', 'Wednesday', 'Thursday', 'Friday', 'Saturday', 'Sunday'][x]
                )
            else:
                day_of_week = 0

        with col3:
            st.markdown("**Time (PST)**")
            time_col1, time_col2, time_col3 = st.columns(3)

            with time_col1:
                run_hour_12 = st.selectbox(
                    "Hour",
                    options=list(range(1, 13)),
                    index=8,  # 9
                    key="recurring_hour"
                )

            with time_col2:
                run_minute = st.number_input(
                    "Minute",
                    min_value=0,
                    max_value=59,
                    value=0,
                    key="recurring_minute"
                )

            with time_col3:
                run_ampm = st.selectbox(
                    "AM/PM",
                    options=["AM", "PM"],
                    index=0,  # AM
                    key="recurring_ampm"
                )

            # Convert to 24-hour format
            if run_ampm == "AM":
                run_hour = run_hour_12 if run_hour_12 != 12 else 0
            else:
                run_hour = run_hour_12 + 12 if run_hour_12 != 12 else 12

        cron_expression = build_cron_expression(frequency, day_of_week, run_hour, run_minute)
        st.caption(f"{run_hour_12}:{run_minute:02d} {run_ampm} PST")

        scheduled_at = None

    else:
        # One-time schedule
        col1, col2 = st.columns(2)

        with col1:
            run_date = st.date_input(
                "Date",
                value=datetime.now(PST).date() + timedelta(days=1),
                min_value=datetime.now(PST).date()
            )

        with col2:
            st.markdown("**Time (PST)**")
            time_col1, time_col2, time_col3 = st.columns(3)

            with time_col1:
                onetime_hour_12 = st.selectbox(
                    "Hour",
                    options=list(range(1, 13)),
                    index=8,  # 9
                    key="onetime_hour"
                )

            with time_col2:
                onetime_minute = st.number_input(
                    "Minute",
                    min_value=0,
                    max_value=59,
                    value=0,
                    key="onetime_minute"
                )

            with time_col3:
                onetime_ampm = st.selectbox(
                    "AM/PM",
                    options=["AM", "PM"],
                    index=0,  # AM
                    key="onetime_ampm"
                )

            # Convert to 24-hour format
            if onetime_ampm == "AM":
                onetime_hour = onetime_hour_12 if onetime_hour_12 != 12 else 0
            else:
                onetime_hour = onetime_hour_12 + 12 if onetime_hour_12 != 12 else 12

            run_time = time(onetime_hour, onetime_minute)

        scheduled_at = PST.localize(datetime.combine(run_date, run_time))
        cron_expression = None
        st.caption(f"Scheduled: {run_date.strftime('%b %d, %Y')} at {onetime_hour_12}:{onetime_minute:02d} {onetime_ampm} PST")

    # Run limits (only for recurring schedules)
    max_runs = None
    if schedule_type == 'recurring':
        st.markdown("**Run Limits**")
        col1, col2 = st.columns(2)

        with col1:
            limit_runs = st.checkbox(
                "Limit number of runs",
                value=existing_job.get('max_runs') is not None if existing_job else False
            )

        with col2:
            if limit_runs:
                max_runs = st.number_input(
                    "Maximum runs",
                    min_value=1,
                    max_value=100,
                    value=existing_job.get('max_runs', 4) if existing_job else 4
                )

    st.divider()

    # ========================================================================
    # Section 4: Template Configuration
    # ========================================================================

    st.subheader("4. Templates")

    # Determine default index for template mode
    mode_options = ['unused', 'specific', 'upload']
    if existing_job:
        existing_mode = existing_job.get('template_mode', 'unused')
        default_index = mode_options.index(existing_mode) if existing_mode in mode_options else 0
    else:
        default_index = 0

    template_mode = st.radio(
        "Template Selection Mode",
        options=mode_options,
        index=default_index,
        format_func=lambda x: {
            'unused': '🔄 Use Unused Templates - Auto-select templates not yet used for this product',
            'specific': '📋 Specific Templates - Choose from existing templates',
            'upload': '📤 Upload New - Upload reference ads for this run'
        }.get(x, x),
        horizontal=False
    )
    st.session_state.sched_template_mode = template_mode

    if template_mode == 'unused':
        # Show count of unused templates
        all_templates = get_existing_templates()
        used_templates = get_used_templates(selected_product_id)
        unused_count = len([t for t in all_templates if t['storage_name'] not in used_templates])

        st.info(f"📊 {unused_count} unused templates available for this product")

        template_count = st.slider(
            "Templates per run",
            min_value=1,
            max_value=min(20, unused_count) if unused_count > 0 else 1,
            value=min(5, unused_count) if unused_count > 0 else 1,
            help="Number of templates to use in each scheduled run"
        )
        template_ids = None

    elif template_mode == 'specific':
        # Specific template selection
        templates = get_existing_templates()

        if templates:
            st.markdown("**Select templates to use:**")

            # Initialize selection from existing job
            if existing_job and existing_job.get('template_ids'):
                if not st.session_state.sched_selected_templates:
                    st.session_state.sched_selected_templates = existing_job['template_ids']

            visible_count = min(st.session_state.sched_templates_visible, len(templates))
            visible_templates = templates[:visible_count]

            cols = st.columns(5)
            for idx, template in enumerate(visible_templates):
                with cols[idx % 5]:
                    storage_name = template['storage_name']
                    is_selected = storage_name in st.session_state.sched_selected_templates

                    thumb_url = get_signed_url(f"reference-ads/{storage_name}")
                    if thumb_url:
                        border = "3px solid #00ff00" if is_selected else "1px solid #333"
                        st.markdown(
                            f'<div style="border:{border};border-radius:4px;padding:2px;margin-bottom:4px;">'
                            f'<img src="{thumb_url}" style="width:100%;border-radius:2px;"/></div>',
                            unsafe_allow_html=True
                        )

                    if st.checkbox(
                        "✓" if is_selected else "Select",
                        value=is_selected,
                        key=f"tpl_select_{idx}"
                    ):
                        if storage_name not in st.session_state.sched_selected_templates:
                            st.session_state.sched_selected_templates.append(storage_name)
                    else:
                        if storage_name in st.session_state.sched_selected_templates:
                            st.session_state.sched_selected_templates.remove(storage_name)

            if visible_count < len(templates):
                if st.button(f"Load More ({len(templates) - visible_count} more)"):
                    st.session_state.sched_templates_visible += 30
                    st.rerun()

            st.markdown(f"**Selected:** {len(st.session_state.sched_selected_templates)} templates")
            template_ids = st.session_state.sched_selected_templates
            template_count = len(template_ids)
        else:
            st.warning("No templates available")
            template_ids = []
            template_count = 0

    elif template_mode == 'upload':
        # Upload new templates mode
        st.markdown("**Upload reference ad templates:**")

        uploaded_files = st.file_uploader(
            "Upload reference ad images",
            type=['jpg', 'jpeg', 'png', 'webp'],
            accept_multiple_files=True,
            help="Upload one or more reference ads to use for this scheduled run",
            key="sched_file_uploader"
        )

        if uploaded_files:
            # Preview uploaded files in grid
            num_cols = min(5, len(uploaded_files))
            cols = st.columns(num_cols)
            for idx, file in enumerate(uploaded_files):
                with cols[idx % num_cols]:
                    st.image(file, use_container_width=True)
                    st.caption(file.name[:20] + "..." if len(file.name) > 20 else file.name)

            st.success(f"📤 {len(uploaded_files)} template(s) ready to upload")

            # Store files in session state for upload on save
            st.session_state.sched_uploaded_files = uploaded_files
            template_count = len(uploaded_files)
            template_ids = None  # Will be populated on save after upload
        else:
            st.info("Upload one or more reference ad images to use for this scheduled run")
            st.session_state.sched_uploaded_files = []
            template_count = 0
            template_ids = None

    st.divider()

    # ========================================================================
    # Section 5: Ad Creation Parameters
    # ========================================================================

    st.subheader("5. Ad Creation Parameters")

    existing_params = existing_job.get('parameters', {}) if existing_job else {}

    col1, col2 = st.columns(2)

    with col1:
        num_variations = st.slider(
            "Variations per template",
            min_value=1,
            max_value=15,
            value=existing_params.get('num_variations', 5),
            help="Number of ad variations to generate for each template"
        )

        content_source = st.radio(
            "Content Source",
            options=['hooks', 'recreate_template'],
            index=0 if existing_params.get('content_source', 'hooks') == 'hooks' else 1,
            format_func=lambda x: {
                'hooks': '🎣 Hooks - Use persuasive hooks from database',
                'recreate_template': '🔄 Recreate - Vary by product benefits'
            }.get(x, x)
        )

    with col2:
        color_mode = st.radio(
            "Color Scheme",
            options=['original', 'complementary', 'brand'],
            index=['original', 'complementary', 'brand'].index(existing_params.get('color_mode', 'original')),
            format_func=lambda x: {
                'original': '🎨 Original - Use template colors',
                'complementary': '🌈 Complementary - Fresh color scheme',
                'brand': '🏷️ Brand - Use brand colors'
            }.get(x, x)
        )

        image_selection_mode = st.radio(
            "Image Selection",
            options=['auto', 'manual'],
            index=0 if existing_params.get('image_selection_mode', 'auto') == 'auto' else 1,
            format_func=lambda x: {
                'auto': '🤖 Auto - AI selects best 1-2 images',
                'manual': '🖼️ Manual - (Selected in Ad Creator)'
            }.get(x, x),
            help="Auto mode picks up to 2 diverse images (e.g., packaging + contents)"
        )

    st.divider()

    # ========================================================================
    # Section 5.5: Target Persona (Optional)
    # ========================================================================

    st.subheader("Target Persona (Optional)")

    # Fetch personas for selected product
    personas = get_personas_for_product(selected_product_id) if selected_product_id else []

    persona_id = None
    if personas:
        # Build persona options - "None" + all personas
        persona_options = {"None - Use product defaults": None}
        for p in personas:
            snapshot = p.get('snapshot', '')[:50] if p.get('snapshot') else ''
            label = f"{p['name']}"
            if snapshot:
                label += f" ({snapshot}...)"
            if p.get('is_primary'):
                label += " ⭐"
            persona_options[label] = p['id']

        # Get existing persona_id from job params
        existing_persona_id = existing_params.get('persona_id')

        # Get current selection label
        current_persona_label = "None - Use product defaults"
        if existing_persona_id:
            for label, pid in persona_options.items():
                if pid == existing_persona_id:
                    current_persona_label = label
                    break

        selected_persona_label = st.selectbox(
            "Select a 4D Persona to target",
            options=list(persona_options.keys()),
            index=list(persona_options.keys()).index(current_persona_label) if current_persona_label in persona_options else 0,
            help="Persona data will inform hook selection and copy generation with emotional triggers and customer voice"
        )
        persona_id = persona_options[selected_persona_label]

        # Show persona preview if selected
        if persona_id:
            selected_persona = next((p for p in personas if p['id'] == persona_id), None)
            if selected_persona:
                with st.expander("Persona Preview", expanded=False):
                    st.markdown(f"**{selected_persona['name']}**")
                    if selected_persona.get('snapshot'):
                        st.write(selected_persona['snapshot'])
                    st.caption("Persona data will be used to select hooks and generate copy that resonates with this audience.")
    else:
        st.info("No personas available for this product. Create personas in Brand Research to enable persona-targeted ad creation.")

    st.divider()

    # ========================================================================
    # Section 6: Export Destination
    # ========================================================================

    st.subheader("6. Export Destination")

    export_destination = st.radio(
        "Where should we send generated ads?",
        options=['none', 'email', 'slack', 'both'],
        index=['none', 'email', 'slack', 'both'].index(existing_params.get('export_destination', 'none')),
        format_func=lambda x: {
            'none': '📁 None - View in browser only',
            'email': '📧 Email - Send via email',
            'slack': '💬 Slack - Post to Slack',
            'both': '📧💬 Both'
        }.get(x, x),
        horizontal=True
    )

    export_email = ""
    if export_destination in ['email', 'both']:
        export_email = st.text_input(
            "Email address",
            value=existing_params.get('export_email', ''),
            placeholder="marketing@company.com"
        )

    st.divider()

    # ========================================================================
    # Submit
    # ========================================================================

    col1, col2, col3 = st.columns([2, 2, 4])

    with col1:
        if st.button("💾 Save Schedule", type="primary", use_container_width=True):
            # Validation
            errors = []
            if not job_name:
                errors.append("Job name is required")
            if template_mode == 'specific' and not template_ids:
                errors.append("Select at least one template")
            if template_mode == 'upload' and not st.session_state.sched_uploaded_files:
                errors.append("Upload at least one template image")
            if export_destination in ['email', 'both'] and not export_email:
                errors.append("Email address is required")

            if errors:
                for error in errors:
                    st.error(error)
            else:
                # Handle upload mode - upload files first
                if template_mode == 'upload':
                    with st.spinner("Uploading templates..."):
                        uploaded_storage_names = upload_template_files(st.session_state.sched_uploaded_files)

                    if not uploaded_storage_names:
                        st.error("Failed to upload templates")
                        st.stop()

                    template_ids = uploaded_storage_names
                    template_count = len(uploaded_storage_names)
                    st.success(f"✅ Uploaded {template_count} template(s)")
                # Build job data
                parameters = {
                    'num_variations': num_variations,
                    'content_source': content_source,
                    'color_mode': color_mode,
                    'image_selection_mode': image_selection_mode,
                    'export_destination': export_destination,
                    'export_email': export_email if export_destination in ['email', 'both'] else None,
                    'persona_id': persona_id
                }

                next_run = calculate_next_run(schedule_type, cron_expression, scheduled_at)

                job_data = {
                    'product_id': selected_product_id,
                    'brand_id': selected_product.get('brand_id') or selected_product.get('brands', {}).get('id'),
                    'name': job_name,
                    'schedule_type': schedule_type,
                    'cron_expression': cron_expression,
                    'scheduled_at': scheduled_at.isoformat() if scheduled_at else None,
                    'next_run_at': next_run.isoformat() if next_run else None,
                    'max_runs': max_runs,
                    'template_mode': template_mode,
                    'template_count': template_count if template_mode == 'unused' else None,
                    # Both 'specific' and 'upload' modes use template_ids
                    'template_ids': template_ids if template_mode in ['specific', 'upload'] else None,
                    'parameters': parameters
                }

                if is_edit:
                    if update_scheduled_job(st.session_state.edit_job_id, job_data):
                        st.success("Schedule updated!")
                        st.session_state.scheduler_view = 'list'
                        st.session_state.sched_selected_templates = []
                        st.session_state.sched_uploaded_files = []
                        st.rerun()
                else:
                    job_id = create_scheduled_job(job_data)
                    if job_id:
                        st.success("Schedule created!")
                        st.session_state.scheduler_view = 'list'
                        st.session_state.sched_selected_templates = []
                        st.session_state.sched_uploaded_files = []
                        st.rerun()

    with col2:
        if st.button("Cancel", use_container_width=True):
            st.session_state.scheduler_view = 'list'
            st.session_state.sched_selected_templates = []
            st.session_state.sched_uploaded_files = []
            st.rerun()


# ============================================================================
# View: Schedule Detail
# ============================================================================

def render_schedule_detail():
    """Render the schedule detail view."""
    job_id = st.session_state.selected_job_id
    job = get_scheduled_job(job_id)

    if not job:
        st.error("Job not found")
        if st.button("← Back to List"):
            st.session_state.scheduler_view = 'list'
            st.rerun()
        return

    product_info = job.get('products', {}) or {}
    brand_info = product_info.get('brands', {}) or {}

    # Header
    col1, col2 = st.columns([4, 2])

    with col1:
        status_emoji = {'active': '🟢', 'paused': '⏸️', 'completed': '✅'}.get(job['status'], '❓')
        st.title(f"{status_emoji} {job['name']}")
        st.caption(f"{brand_info.get('name', 'Unknown')} → {product_info.get('name', 'Unknown')}")

    with col2:
        if st.button("← Back to List"):
            st.session_state.scheduler_view = 'list'
            st.rerun()

    st.divider()

    # Action buttons
    col1, col2, col3, col4 = st.columns(4)

    with col1:
        if job['status'] == 'active':
            if st.button("⏸️ Pause", use_container_width=True):
                update_scheduled_job(job_id, {'status': 'paused'})
                st.rerun()
        elif job['status'] == 'paused':
            if st.button("▶️ Resume", use_container_width=True):
                update_scheduled_job(job_id, {'status': 'active'})
                st.rerun()

    with col2:
        if st.button("✏️ Edit", use_container_width=True):
            st.session_state.edit_job_id = job_id
            st.session_state.scheduler_view = 'create'
            st.rerun()

    with col3:
        if st.button("🗑️ Delete", use_container_width=True):
            st.session_state.confirm_delete = True

    if st.session_state.get('confirm_delete'):
        st.warning("Are you sure you want to delete this schedule?")
        col1, col2 = st.columns(2)
        with col1:
            if st.button("Yes, Delete", type="primary"):
                delete_scheduled_job(job_id)
                st.session_state.scheduler_view = 'list'
                st.session_state.confirm_delete = False
                st.rerun()
        with col2:
            if st.button("Cancel"):
                st.session_state.confirm_delete = False
                st.rerun()

    st.divider()

    # Job details
    col1, col2 = st.columns(2)

    with col1:
        st.markdown("### Schedule")
        schedule_desc = cron_to_description(job.get('cron_expression'), job['schedule_type'])
        st.markdown(f"**Type:** {schedule_desc}")

        if job.get('next_run_at'):
            next_run = datetime.fromisoformat(job['next_run_at'].replace('Z', '+00:00'))
            st.markdown(f"**Next Run:** {next_run.strftime('%B %d, %Y at %I:%M %p PST')}")

        runs_text = f"{job.get('runs_completed', 0)}"
        if job.get('max_runs'):
            runs_text += f" / {job['max_runs']}"
        st.markdown(f"**Runs Completed:** {runs_text}")

    with col2:
        st.markdown("### Templates")
        st.markdown(f"**Mode:** {job.get('template_mode', 'unused').capitalize()}")

        if job['template_mode'] == 'unused':
            st.markdown(f"**Per Run:** {job.get('template_count', 'N/A')} templates")
        else:
            template_ids = job.get('template_ids', [])
            st.markdown(f"**Selected:** {len(template_ids)} templates")

    st.divider()

    # Parameters
    st.markdown("### Ad Creation Parameters")
    params = job.get('parameters', {})

    col1, col2, col3, col4 = st.columns(4)
    with col1:
        st.markdown(f"**Variations:** {params.get('num_variations', 'N/A')}")
        st.markdown(f"**Content:** {params.get('content_source', 'N/A')}")
    with col2:
        st.markdown(f"**Colors:** {params.get('color_mode', 'N/A')}")
        st.markdown(f"**Images:** {params.get('image_selection_mode', 'N/A')}")
    with col3:
        st.markdown(f"**Export:** {params.get('export_destination', 'none')}")
        if params.get('export_email'):
            st.caption(params['export_email'])
    with col4:
        persona_id = params.get('persona_id')
        if persona_id:
            # Try to get persona name
            personas = get_personas_for_product(job['product_id'])
            persona = next((p for p in personas if p['id'] == persona_id), None)
            persona_name = persona['name'] if persona else persona_id[:8]
            st.markdown(f"**Persona:** {persona_name}")
        else:
            st.markdown("**Persona:** None")

    st.divider()

    # Run history
    st.markdown("### Run History")

    runs = get_job_runs(job_id)

    if not runs:
        st.info("No runs yet. The first run will execute at the scheduled time.")
    else:
        for run in runs:
            status_emoji = {
                'pending': '⏳',
                'running': '🔄',
                'completed': '✅',
                'failed': '❌'
            }.get(run['status'], '❓')

            started = run.get('started_at', '')
            if started:
                started = datetime.fromisoformat(started.replace('Z', '+00:00')).strftime('%b %d, %I:%M %p')

            with st.expander(f"{status_emoji} Run - {started or 'Pending'}"):
                col1, col2 = st.columns(2)
                with col1:
                    st.markdown(f"**Status:** {run['status']}")
                    if run.get('completed_at'):
                        completed = datetime.fromisoformat(run['completed_at'].replace('Z', '+00:00'))
                        st.markdown(f"**Completed:** {completed.strftime('%b %d, %I:%M %p')}")

                with col2:
                    ad_runs = run.get('ad_run_ids', [])
                    st.markdown(f"**Ads Generated:** {len(ad_runs) if ad_runs else 0}")
                    templates = run.get('templates_used', [])
                    st.markdown(f"**Templates Used:** {len(templates) if templates else 0}")

                if run.get('error_message'):
                    st.error(f"Error: {run['error_message']}")

                if run.get('logs'):
                    st.text_area("Logs", run['logs'], height=100)


# ============================================================================
# Main Router
# ============================================================================

# Initialize confirm_delete state
if 'confirm_delete' not in st.session_state:
    st.session_state.confirm_delete = False

# Route to appropriate view
if st.session_state.scheduler_view == 'list':
    render_schedule_list()
elif st.session_state.scheduler_view == 'create':
    render_create_schedule()
elif st.session_state.scheduler_view == 'detail':
    render_schedule_detail()
else:
    st.session_state.scheduler_view = 'list'
    render_schedule_list()
