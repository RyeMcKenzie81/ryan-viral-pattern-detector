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

# Belief-first scheduling state
if 'sched_content_source' not in st.session_state:
    st.session_state.sched_content_source = 'hooks'
if 'sched_selected_plan_id' not in st.session_state:
    st.session_state.sched_selected_plan_id = None
if 'sched_selected_persona_id' not in st.session_state:
    st.session_state.sched_selected_persona_id = None
if 'sched_selected_jtbd_id' not in st.session_state:
    st.session_state.sched_selected_jtbd_id = None
if 'sched_selected_angle_ids' not in st.session_state:
    st.session_state.sched_selected_angle_ids = []

# Offer variant state
if 'sched_selected_offer_variant_id' not in st.session_state:
    st.session_state.sched_selected_offer_variant_id = None

# Scraped template library state
if 'sched_template_source' not in st.session_state:
    st.session_state.sched_template_source = 'uploaded'  # 'uploaded' or 'scraped'
if 'sched_selected_scraped_templates' not in st.session_state:
    st.session_state.sched_selected_scraped_templates = []  # List of {id, name, storage_path, bucket}
if 'sched_scraped_category' not in st.session_state:
    st.session_state.sched_scraped_category = 'all'
if 'sched_scraped_rec_filter' not in st.session_state:
    st.session_state.sched_scraped_rec_filter = 'all'  # all, recommended, unused_recommended


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


def get_variants_for_product(product_id: str):
    """Get variants for a product for the variant selector."""
    try:
        db = get_supabase_client()
        result = db.table("product_variants").select(
            "id, name, slug, variant_type, description, is_default, is_active"
        ).eq("product_id", product_id).eq("is_active", True).order("display_order").execute()
        return result.data or []
    except Exception as e:
        return []


def get_offer_variants_for_product(product_id: str):
    """Get offer variants (landing pages) for a product."""
    try:
        db = get_supabase_client()
        result = db.table("product_offer_variants").select(
            "id, name, slug, landing_page_url, pain_points, desires_goals, benefits, "
            "target_audience, is_default, is_active"
        ).eq("product_id", product_id).eq("is_active", True).order("display_order").execute()
        return result.data or []
    except Exception as e:
        return []


def get_belief_plans_for_product(product_id: str):
    """Get belief plans for a product (for belief-first scheduling)."""
    try:
        db = get_supabase_client()
        result = db.table("belief_plans").select(
            "id, name, status, phase_id, ads_per_angle, persona_id, jtbd_framed_id"
        ).eq("product_id", product_id).in_("status", ["ready", "draft"]).order("created_at", desc=True).execute()
        return result.data or []
    except Exception as e:
        return []


def get_jtbd_for_persona_product(persona_id: str, product_id: str):
    """Get JTBDs for a persona-product combination."""
    try:
        db = get_supabase_client()
        result = db.table("belief_jtbd_framed").select(
            "id, name, description, progress_statement"
        ).eq("persona_id", persona_id).eq("product_id", product_id).order("created_at", desc=True).execute()
        return result.data or []
    except Exception as e:
        return []


def get_angles_for_jtbd(jtbd_id: str):
    """Get belief angles for a JTBD."""
    try:
        db = get_supabase_client()
        result = db.table("belief_angles").select(
            "id, name, belief_statement, status"
        ).eq("jtbd_framed_id", jtbd_id).order("created_at", desc=True).execute()
        return result.data or []
    except Exception as e:
        return []


def get_plan_details(plan_id: str):
    """Get full plan details including angles and templates."""
    try:
        from viraltracker.services.planning_service import PlanningService
        from uuid import UUID
        service = PlanningService()
        return service.get_plan(UUID(plan_id))
    except Exception as e:
        return None


def get_scheduled_jobs(brand_id: str = None, product_id: str = None, status: str = None):
    """Fetch scheduled jobs with optional filters."""
    try:
        db = get_supabase_client()
        # Get jobs with products join
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
        jobs = result.data or []

        # For jobs without products (meta_sync, scorecard), fetch brand name separately
        brand_ids_needed = set()
        for job in jobs:
            if not job.get('products') and job.get('brand_id'):
                brand_ids_needed.add(job['brand_id'])

        if brand_ids_needed:
            brands_result = db.table("brands").select("id, name").in_("id", list(brand_ids_needed)).execute()
            brand_map = {b['id']: b for b in (brands_result.data or [])}
            for job in jobs:
                if not job.get('products') and job.get('brand_id'):
                    job['brands'] = brand_map.get(job['brand_id'], {})

        return jobs
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


# ============================================================================
# Scraped Template Library Functions
# ============================================================================

def get_scraped_templates(
    category: str = None,
    awareness_level: int = None,
    industry_niche: str = None,
    target_sex: str = None,
    limit: int = 100
):
    """Get approved scraped templates from database.

    Args:
        category: Optional category filter (testimonial, quote_card, etc.)
        awareness_level: Optional awareness level (1-5)
        industry_niche: Optional industry/niche filter
        target_sex: Optional target sex filter (male/female/unisex)
        limit: Maximum templates to return

    Returns:
        List of template records with storage paths
    """
    try:
        from viraltracker.services.template_queue_service import TemplateQueueService
        service = TemplateQueueService()
        return service.get_templates(
            category=category if category != "all" else None,
            awareness_level=awareness_level,
            industry_niche=industry_niche if industry_niche != "all" else None,
            target_sex=target_sex if target_sex != "all" else None,
            active_only=True,
            limit=limit
        )
    except Exception as e:
        st.warning(f"Could not load scraped templates: {e}")
        return []


def get_template_categories():
    """Get list of template categories."""
    try:
        from viraltracker.services.template_queue_service import TemplateQueueService
        service = TemplateQueueService()
        return ["all"] + service.get_template_categories()
    except Exception:
        return ["all", "testimonial", "quote_card", "before_after", "product_showcase",
                "ugc_style", "meme", "carousel_frame", "story_format", "other"]


def get_awareness_levels():
    """Get awareness level filter options."""
    try:
        from viraltracker.services.template_queue_service import TemplateQueueService
        return TemplateQueueService().get_awareness_levels()
    except Exception:
        return []


def get_industry_niches():
    """Get industry niche filter options."""
    try:
        from viraltracker.services.template_queue_service import TemplateQueueService
        return TemplateQueueService().get_industry_niches()
    except Exception:
        return []


def get_scraped_template_url(storage_path: str) -> str:
    """Get public URL for scraped template asset."""
    try:
        from viraltracker.services.template_queue_service import TemplateQueueService
        service = TemplateQueueService()
        return service.get_asset_preview_url(storage_path)
    except Exception:
        return ""


def get_template_asset_match(template_id: str, product_id: str) -> dict:
    """Get asset match info for a template.

    Args:
        template_id: UUID string of the template
        product_id: UUID string of the product

    Returns:
        Dict with asset_match_score, missing_assets, warnings, detection_status
    """
    try:
        from viraltracker.services.template_element_service import TemplateElementService
        from uuid import UUID
        service = TemplateElementService()
        return service.match_assets_to_template(UUID(template_id), UUID(product_id))
    except Exception:
        return {"asset_match_score": 1.0, "detection_status": "error"}


def get_asset_badge_html(score: float, detection_status: str = "analyzed") -> str:
    """Generate HTML badge for asset match score.

    Args:
        score: Asset match score 0.0-1.0
        detection_status: Status of element detection

    Returns:
        HTML string for badge
    """
    if detection_status == "not_analyzed":
        return ""  # No badge if not analyzed

    if score >= 1.0:
        return '<span style="background:#28a745;color:white;padding:1px 4px;border-radius:3px;font-size:9px;">All assets</span>'
    elif score >= 0.5:
        pct = int(score * 100)
        return f'<span style="background:#ffc107;color:black;padding:1px 4px;border-radius:3px;font-size:9px;">{pct}% assets</span>'
    else:
        return '<span style="background:#dc3545;color:white;padding:1px 4px;border-radius:3px;font-size:9px;">Missing assets</span>'


def toggle_scraped_template_selection(template_info: dict):
    """Toggle a scraped template in the selection list.

    Args:
        template_info: Dict with {id, name, storage_path, bucket}
    """
    current_selections = st.session_state.sched_selected_scraped_templates

    # Check if already selected by id
    existing_idx = next(
        (i for i, t in enumerate(current_selections) if t['id'] == template_info['id']),
        None
    )

    if existing_idx is not None:
        # Remove from selection
        current_selections.pop(existing_idx)
    else:
        # Add to selection
        current_selections.append(template_info)

    st.session_state.sched_selected_scraped_templates = current_selections


def is_scraped_template_selected(template_id: str) -> bool:
    """Check if a scraped template is currently selected."""
    return any(t['id'] == template_id for t in st.session_state.sched_selected_scraped_templates)


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
        # Get brand info - from products join for ad_creation, direct join for others
        brand_info = product_info.get('brands', {}) or job.get('brands', {}) or {}
        job_type = job.get('job_type', 'ad_creation')

        with st.container():
            col1, col2, col3, col4 = st.columns([3, 2, 2, 1])

            with col1:
                status_emoji = {'active': '🟢', 'paused': '⏸️', 'completed': '✅'}.get(job['status'], '❓')
                # Add job type indicator for non-ad jobs
                type_badge = ""
                if job_type == 'meta_sync':
                    type_badge = "🔄 "
                elif job_type == 'scorecard':
                    type_badge = "📊 "
                st.markdown(f"### {status_emoji} {type_badge}{job['name']}")

                # Show brand → product for ad_creation, just brand for others
                if job_type == 'ad_creation':
                    st.caption(f"{brand_info.get('name', 'Unknown')} → {product_info.get('name', 'Unknown')}")
                else:
                    st.caption(f"{brand_info.get('name', 'Unknown')}")

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

                # Show template info for ad_creation jobs, parameters for others
                if job_type == 'ad_creation':
                    template_source = job.get('template_source', 'uploaded')
                    if template_source == 'scraped':
                        scraped_ids = job.get('scraped_template_ids') or []
                        st.caption(f"Source: Scraped Library ({len(scraped_ids)} templates)")
                    else:
                        template_mode = job.get('template_mode', 'unused')
                        if template_mode == 'unused':
                            template_info = f"{job.get('template_count', '?')} templates"
                        else:
                            template_ids = job.get('template_ids') or []
                            template_info = f"{len(template_ids)} templates"
                        st.caption(f"Mode: {template_mode} ({template_info})")
                elif job_type == 'meta_sync':
                    params = job.get('parameters', {}) or {}
                    st.caption(f"Syncs last {params.get('days_back', 7)} days")
                elif job_type == 'scorecard':
                    params = job.get('parameters', {}) or {}
                    st.caption(f"Analyzes last {params.get('days_back', 7)} days")

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

    # Template source toggle
    existing_template_source = 'uploaded'
    if existing_job:
        existing_template_source = existing_job.get('template_source', 'uploaded')

    template_source = st.radio(
        "Template Source",
        options=['uploaded', 'scraped'],
        index=0 if existing_template_source == 'uploaded' else 1,
        format_func=lambda x: {
            'uploaded': '📤 Uploaded Templates - Use templates from reference-ads storage',
            'scraped': '📚 Scraped Template Library - Use curated templates with recommendations'
        }.get(x, x),
        horizontal=True,
        key="template_source_radio"
    )
    st.session_state.sched_template_source = template_source

    st.divider()

    # Initialize template variables
    template_mode = None
    template_count = 0
    template_ids = None
    scraped_template_ids = []

    if template_source == 'uploaded':
        # Original uploaded template UI
        # Determine default index for template mode
        mode_options = ['unused', 'specific', 'upload']
        if existing_job and existing_job.get('template_source', 'uploaded') == 'uploaded':
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

    else:
        # Scraped Template Library
        from uuid import UUID

        # Recommendation filter row
        rec_filter_col1, rec_filter_col2 = st.columns([2, 1])

        with rec_filter_col1:
            rec_filter = st.selectbox(
                "Show Templates",
                options=["All Templates", "Recommended", "Unused Recommended"],
                index={"all": 0, "recommended": 1, "unused_recommended": 2}.get(
                    st.session_state.sched_scraped_rec_filter, 0
                ),
                key="sched_rec_filter_select",
                help="Filter to show only templates recommended for this product"
            )
            st.session_state.sched_scraped_rec_filter = {
                "All Templates": "all",
                "Recommended": "recommended",
                "Unused Recommended": "unused_recommended"
            }.get(rec_filter, "all")

        with rec_filter_col2:
            # Show recommendation counts if product is selected
            if selected_product_id and st.session_state.sched_scraped_rec_filter != "all":
                try:
                    from viraltracker.services.template_recommendation_service import TemplateRecommendationService
                    rec_service = TemplateRecommendationService()
                    counts = rec_service.get_recommendation_count(UUID(selected_product_id))
                    if st.session_state.sched_scraped_rec_filter == "recommended":
                        st.caption(f"{counts['total']} recommended templates")
                    else:
                        st.caption(f"{counts['unused']} unused recommendations")
                except Exception:
                    pass

        # Filter row - 4 columns
        filter_cols = st.columns(4)

        # Category filter
        with filter_cols[0]:
            categories = get_template_categories()
            selected_category = st.selectbox(
                "Category",
                options=categories,
                index=categories.index(st.session_state.sched_scraped_category) if st.session_state.sched_scraped_category in categories else 0,
                format_func=lambda x: x.replace("_", " ").title() if x != "all" else "All",
                key="sched_filter_category"
            )
            st.session_state.sched_scraped_category = selected_category

        # Awareness Level filter
        with filter_cols[1]:
            awareness_opts = [{"value": None, "label": "All"}] + get_awareness_levels()
            selected_awareness = st.selectbox(
                "Awareness Level",
                options=[a["value"] for a in awareness_opts],
                format_func=lambda x: next((a["label"] for a in awareness_opts if a["value"] == x), "All"),
                key="sched_filter_awareness"
            )

        # Industry/Niche filter
        with filter_cols[2]:
            niches = ["all"] + get_industry_niches()
            selected_niche = st.selectbox(
                "Industry/Niche",
                options=niches,
                format_func=lambda x: x.replace("_", " ").title() if x != "all" else "All",
                key="sched_filter_niche"
            )

        # Target Sex filter
        with filter_cols[3]:
            sex_options = ["all", "male", "female", "unisex"]
            selected_sex = st.selectbox(
                "Target Audience",
                options=sex_options,
                format_func=lambda x: x.title() if x != "all" else "All",
                key="sched_filter_sex"
            )

        # Get scraped templates with all filters
        scraped_templates_list = get_scraped_templates(
            category=selected_category if selected_category != "all" else None,
            awareness_level=selected_awareness,
            industry_niche=selected_niche if selected_niche != "all" else None,
            target_sex=selected_sex if selected_sex != "all" else None,
            limit=100  # Fetch more since we may filter
        )

        # Apply recommendation filter
        if st.session_state.sched_scraped_rec_filter != "all" and selected_product_id:
            try:
                from viraltracker.services.template_recommendation_service import TemplateRecommendationService
                rec_service = TemplateRecommendationService()
                unused_only = st.session_state.sched_scraped_rec_filter == "unused_recommended"
                recommended_ids = rec_service.get_recommended_template_ids(
                    UUID(selected_product_id), unused_only=unused_only
                )
                recommended_id_strs = {str(rid) for rid in recommended_ids}
                scraped_templates_list = [
                    t for t in scraped_templates_list
                    if t.get('id') in recommended_id_strs
                ]
            except Exception:
                pass

        # Initialize selection from existing job
        if existing_job and existing_job.get('scraped_template_ids'):
            if not st.session_state.sched_selected_scraped_templates:
                # Fetch template details for display
                existing_ids = existing_job['scraped_template_ids']
                st.session_state.sched_selected_scraped_templates = [
                    {'id': tid, 'name': 'Template', 'storage_path': '', 'bucket': 'scraped-assets'}
                    for tid in existing_ids
                ]

        if scraped_templates_list:
            # Selection count and clear button
            selected_count = len(st.session_state.sched_selected_scraped_templates)
            header_cols = st.columns([3, 1])
            with header_cols[0]:
                category_label = f" in '{selected_category.replace('_', ' ').title()}'" if selected_category != "all" else ""
                st.caption(f"Showing {len(scraped_templates_list)} templates{category_label} | **{selected_count} selected**")
            with header_cols[1]:
                if selected_count > 0:
                    if st.button("Clear Selection", key="sched_clear_scraped_selection", use_container_width=True):
                        st.session_state.sched_selected_scraped_templates = []
                        st.rerun()

            # Thumbnail grid - 5 columns with checkboxes
            cols = st.columns(5)
            for idx, template in enumerate(scraped_templates_list):
                with cols[idx % 5]:
                    template_id = template.get('id', '')
                    template_name = template.get('name', 'Unnamed')
                    storage_path = template.get('storage_path', '')
                    category = template.get('category', 'other')
                    times_used = template.get('times_used', 0) or 0

                    is_selected = is_scraped_template_selected(template_id)

                    # Get preview URL
                    thumb_url = get_scraped_template_url(storage_path) if storage_path else ""

                    # Show thumbnail with selection border
                    if thumb_url:
                        border_style = "3px solid #00ff00" if is_selected else "1px solid #333"
                        st.markdown(
                            f'<div style="border:{border_style};border-radius:4px;padding:2px;margin-bottom:4px;">'
                            f'<img src="{thumb_url}" style="width:100%;border-radius:2px;" title="{template_name}"/>'
                            f'</div>',
                            unsafe_allow_html=True
                        )
                    else:
                        st.markdown(
                            f'<div style="height:80px;background:#333;border-radius:4px;'
                            f'display:flex;align-items:center;justify-content:center;font-size:10px;">'
                            f'{template_name[:10]}...</div>',
                            unsafe_allow_html=True
                        )

                    # Show template info
                    st.caption(f"📁 {category.replace('_', ' ').title()}")
                    if times_used > 0:
                        st.caption(f"Used {times_used}x")

                    # Show asset match badge if product is selected
                    if selected_product_id:
                        asset_match = get_template_asset_match(template_id, selected_product_id)
                        badge_html = get_asset_badge_html(
                            asset_match.get("asset_match_score", 1.0),
                            asset_match.get("detection_status", "unknown")
                        )
                        if badge_html:
                            st.markdown(badge_html, unsafe_allow_html=True)

                    # Parse bucket and path for storage
                    parts = storage_path.split("/", 1) if storage_path else ["", ""]
                    bucket = parts[0] if len(parts) == 2 else "scraped-assets"
                    path = parts[1] if len(parts) == 2 else storage_path

                    # Checkbox for multi-select
                    if st.checkbox(
                        template_name[:15] + "..." if len(template_name) > 15 else template_name,
                        value=is_selected,
                        key=f"sched_scraped_tpl_cb_{idx}",
                        help=template_name
                    ):
                        if not is_selected:
                            # Add to selection
                            toggle_scraped_template_selection({
                                'id': template_id,
                                'name': template_name,
                                'storage_path': path,
                                'bucket': bucket
                            })
                            st.rerun()
                    else:
                        if is_selected:
                            # Remove from selection
                            toggle_scraped_template_selection({
                                'id': template_id,
                                'name': template_name,
                                'storage_path': path,
                                'bucket': bucket
                            })
                            st.rerun()

            # Set scraped_template_ids from selection
            scraped_template_ids = [t['id'] for t in st.session_state.sched_selected_scraped_templates]
            template_count = len(scraped_template_ids)
        else:
            st.info("No scraped templates found. Use the Template Queue to approve templates from competitor ads.")
            scraped_template_ids = []
            template_count = 0

    st.divider()

    # ========================================================================
    # Section 5: Ad Creation Parameters
    # ========================================================================

    st.subheader("5. Ad Creation Parameters")

    existing_params = existing_job.get('parameters', {}) if existing_job else {}

    # Content Source selection - determines how ad content is generated
    st.markdown("**Content Source**")
    st.caption("Choose how the ad variations will be generated")

    # Get existing content source
    existing_content_source = existing_params.get('content_source', 'hooks')
    content_source_options = ['hooks', 'recreate_template', 'plan', 'angles']
    try:
        content_source_index = content_source_options.index(existing_content_source)
    except ValueError:
        content_source_index = 0

    content_source = st.radio(
        "Content Generation Mode",
        options=content_source_options,
        index=content_source_index,
        format_func=lambda x: {
            'hooks': '🎣 Hooks - Use persuasive hooks from database',
            'recreate_template': '🔄 Recreate - Vary by product benefits',
            'plan': '📋 Belief Plan - Use a pre-configured belief-first plan',
            'angles': '🎯 Direct Angles - Select specific angles to test'
        }.get(x, x),
        horizontal=False,
        key="content_source_radio"
    )

    # Initialize belief-first selection variables
    selected_plan_id = None
    selected_angle_ids = []
    belief_persona_id = None
    belief_jtbd_id = None

    # Show belief-first UI based on content_source selection
    if content_source == 'plan':
        st.divider()
        st.markdown("##### 📋 Select Belief Plan")

        # Get available plans for this product
        plans = get_belief_plans_for_product(selected_product_id) if selected_product_id else []

        if not plans:
            st.warning("No belief plans found for this product. Create a plan in Ad Planning first.")
        else:
            # Build plan options
            plan_options = {"Select a plan...": None}
            for p in plans:
                status_emoji = "✅" if p['status'] == 'ready' else "📝"
                label = f"{status_emoji} {p['name']} (Phase {p['phase_id']})"
                plan_options[label] = p['id']

            # Get existing plan_id
            existing_plan_id = existing_params.get('plan_id')
            current_plan_label = "Select a plan..."
            if existing_plan_id:
                for label, pid in plan_options.items():
                    if pid == existing_plan_id:
                        current_plan_label = label
                        break

            selected_plan_label = st.selectbox(
                "Belief Plan",
                options=list(plan_options.keys()),
                index=list(plan_options.keys()).index(current_plan_label) if current_plan_label in plan_options else 0,
                help="Select a belief plan to use for scheduled ad generation"
            )
            selected_plan_id = plan_options[selected_plan_label]

            # Show plan preview if selected
            if selected_plan_id:
                plan = get_plan_details(selected_plan_id)
                if plan:
                    with st.expander("Plan Preview", expanded=True):
                        col_a, col_b = st.columns(2)
                        with col_a:
                            st.markdown(f"**Angles:** {len(plan.angles)}")
                            for a in plan.angles[:5]:
                                st.caption(f"• {a.name}")
                            if len(plan.angles) > 5:
                                st.caption(f"... and {len(plan.angles) - 5} more")
                        with col_b:
                            st.markdown(f"**Templates:** {len(plan.templates)}")
                            st.markdown(f"**Ads per angle:** {plan.ads_per_angle}")

                    # Calculate estimated ads
                    estimated_ads = len(plan.angles) * len(plan.templates) * plan.ads_per_angle
                    if estimated_ads > 50:
                        st.warning(f"⚠️ This plan would generate ~{estimated_ads} ads. Max per run is 50.")
                    else:
                        st.info(f"📊 Estimated ads per run: ~{estimated_ads}")

    elif content_source == 'angles':
        st.divider()
        st.markdown("##### 🎯 Select Angles Directly")

        # Step 1: Select Persona
        personas = get_personas_for_product(selected_product_id) if selected_product_id else []

        if not personas:
            st.warning("No personas found for this product. Create personas in Brand Research first.")
        else:
            # Build persona options
            persona_options_angles = {"Select a persona...": None}
            for p in personas:
                label = p['name']
                if p.get('is_primary'):
                    label += " ⭐"
                persona_options_angles[label] = p['id']

            # Get existing selection
            existing_belief_persona = existing_params.get('belief_persona_id')
            current_persona_label_angles = "Select a persona..."
            if existing_belief_persona:
                for label, pid in persona_options_angles.items():
                    if pid == existing_belief_persona:
                        current_persona_label_angles = label
                        break

            selected_persona_label_angles = st.selectbox(
                "1️⃣ Select Persona",
                options=list(persona_options_angles.keys()),
                index=list(persona_options_angles.keys()).index(current_persona_label_angles) if current_persona_label_angles in persona_options_angles else 0,
                key="belief_persona_select"
            )
            belief_persona_id = persona_options_angles[selected_persona_label_angles]

            # Step 2: Select JTBD (if persona selected)
            if belief_persona_id:
                jtbds = get_jtbd_for_persona_product(belief_persona_id, selected_product_id)

                if not jtbds:
                    st.info("No JTBDs found for this persona+product. Create JTBDs in Ad Planning.")
                else:
                    # Build JTBD options
                    jtbd_options = {"Select a JTBD...": None}
                    for j in jtbds:
                        label = j['name']
                        if j.get('progress_statement'):
                            label += f" - {j['progress_statement'][:40]}..."
                        jtbd_options[label] = j['id']

                    # Get existing selection
                    existing_belief_jtbd = existing_params.get('belief_jtbd_id')
                    current_jtbd_label = "Select a JTBD..."
                    if existing_belief_jtbd:
                        for label, jid in jtbd_options.items():
                            if jid == existing_belief_jtbd:
                                current_jtbd_label = label
                                break

                    selected_jtbd_label = st.selectbox(
                        "2️⃣ Select Job-to-be-Done",
                        options=list(jtbd_options.keys()),
                        index=list(jtbd_options.keys()).index(current_jtbd_label) if current_jtbd_label in jtbd_options else 0,
                        key="belief_jtbd_select"
                    )
                    belief_jtbd_id = jtbd_options[selected_jtbd_label]

                    # Step 3: Select Angles (if JTBD selected)
                    if belief_jtbd_id:
                        angles = get_angles_for_jtbd(belief_jtbd_id)

                        if not angles:
                            st.info("No angles found for this JTBD. Create angles in Ad Planning.")
                        else:
                            st.markdown("3️⃣ **Select Angles to Test**")

                            # Get existing angle selections
                            existing_angle_ids = existing_params.get('angle_ids', [])

                            # Multi-select angles with checkboxes
                            for angle in angles:
                                is_selected = angle['id'] in existing_angle_ids or angle['id'] in st.session_state.sched_selected_angle_ids
                                status_emoji = {'winner': '🏆', 'loser': '❌', 'testing': '🧪'}.get(angle.get('status'), '⚪')

                                col_check, col_info = st.columns([1, 5])
                                with col_check:
                                    if st.checkbox(
                                        f"{status_emoji}",
                                        value=is_selected,
                                        key=f"angle_check_{angle['id']}"
                                    ):
                                        if angle['id'] not in selected_angle_ids:
                                            selected_angle_ids.append(angle['id'])
                                    else:
                                        if angle['id'] in selected_angle_ids:
                                            selected_angle_ids.remove(angle['id'])

                                with col_info:
                                    st.markdown(f"**{angle['name']}**")
                                    st.caption(angle.get('belief_statement', '')[:80] + '...' if len(angle.get('belief_statement', '')) > 80 else angle.get('belief_statement', ''))

                            # Update session state
                            st.session_state.sched_selected_angle_ids = selected_angle_ids

                            if selected_angle_ids:
                                st.success(f"✅ {len(selected_angle_ids)} angle(s) selected")
                            else:
                                st.warning("Please select at least one angle")

    st.divider()

    # Other ad parameters
    col1, col2 = st.columns(2)

    with col1:
        num_variations = st.slider(
            "Variations per template",
            min_value=1,
            max_value=15,
            value=existing_params.get('num_variations', 5),
            help="Number of ad variations to generate for each template"
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
    # Section 5.6: Product Variant (Optional)
    # ========================================================================

    st.subheader("Product Variant (Optional)")

    # Fetch variants for selected product
    variants = get_variants_for_product(selected_product_id) if selected_product_id else []

    variant_id = None
    if variants:
        # Build variant options - "Default" + all variants
        variant_options = {"Use default variant": None}
        for v in variants:
            label = f"{v['name']}"
            if v.get('is_default'):
                label += " (default)"
            if v.get('description'):
                label += f" - {v['description'][:40]}..."
            variant_options[label] = v['id']

        # Get existing variant_id from job params
        existing_variant_id = existing_params.get('variant_id')

        # Get current selection label
        current_variant_label = "Use default variant"
        if existing_variant_id:
            for label, vid in variant_options.items():
                if vid == existing_variant_id:
                    current_variant_label = label
                    break

        selected_variant_label = st.selectbox(
            "Select a product variant",
            options=list(variant_options.keys()),
            index=list(variant_options.keys()).index(current_variant_label) if current_variant_label in variant_options else 0,
            help="Choose a specific flavor, size, or variant to feature in ads"
        )
        variant_id = variant_options[selected_variant_label]

        # Show variant preview if selected
        if variant_id:
            selected_variant = next((v for v in variants if v['id'] == variant_id), None)
            if selected_variant and selected_variant.get('description'):
                st.caption(f"📦 {selected_variant['description']}")
    else:
        st.info("No variants available for this product. Add variants in Brand Manager if needed.")

    st.divider()

    # ========================================================================
    # Section 5.7: Offer Variant / Landing Page (REQUIRED if variants exist)
    # ========================================================================

    st.subheader("Offer Variant / Landing Page")

    # Fetch offer variants for selected product
    offer_variants = get_offer_variants_for_product(selected_product_id) if selected_product_id else []

    offer_variant_id = None
    destination_url = None
    has_offer_variants = len(offer_variants) > 0

    if offer_variants:
        st.markdown("🎯 **Select Landing Page & Messaging Context**")
        st.caption("This product has multiple landing pages targeting different pain points. Selection is **required**.")

        # Build offer variant options
        offer_variant_options = {"Select an offer variant...": None}
        for ov in offer_variants:
            label = f"{ov['name']}"
            if ov.get('is_default'):
                label += " ⭐"
            # Show URL preview
            url_preview = ov['landing_page_url'][:40] + '...' if len(ov['landing_page_url']) > 40 else ov['landing_page_url']
            label += f" ({url_preview})"
            offer_variant_options[label] = ov['id']

        # Get existing offer_variant_id from job params
        existing_offer_variant_id = existing_params.get('offer_variant_id')

        # Get current selection label
        current_offer_variant_label = "Select an offer variant..."
        if existing_offer_variant_id:
            for label, ovid in offer_variant_options.items():
                if ovid == existing_offer_variant_id:
                    current_offer_variant_label = label
                    break

        selected_offer_variant_label = st.selectbox(
            "Select Offer Variant",
            options=list(offer_variant_options.keys()),
            index=list(offer_variant_options.keys()).index(current_offer_variant_label) if current_offer_variant_label in offer_variant_options else 0,
            help="Choose which landing page and messaging context to use for generated ads"
        )
        offer_variant_id = offer_variant_options[selected_offer_variant_label]

        # Show variant preview if selected
        if offer_variant_id:
            selected_offer_variant = next((ov for ov in offer_variants if ov['id'] == offer_variant_id), None)
            if selected_offer_variant:
                destination_url = selected_offer_variant['landing_page_url']

                with st.expander("Offer Variant Details", expanded=True):
                    st.markdown(f"**🔗 Landing Page:** `{destination_url}`")

                    col_a, col_b = st.columns(2)
                    with col_a:
                        pain_points = selected_offer_variant.get('pain_points') or []
                        if pain_points:
                            st.markdown("**Pain Points:**")
                            for pp in pain_points[:5]:
                                st.caption(f"• {pp}")

                    with col_b:
                        desires = selected_offer_variant.get('desires_goals') or []
                        if desires:
                            st.markdown("**Desires/Goals:**")
                            for d in desires[:5]:
                                st.caption(f"• {d}")

                    benefits = selected_offer_variant.get('benefits') or []
                    if benefits:
                        st.markdown("**Benefits:**")
                        st.caption(", ".join(benefits[:5]))

                st.success("✅ Ads will target this landing page with matching messaging")
        else:
            st.warning("⚠️ Please select an offer variant. This is required for products with multiple landing pages.")
    else:
        st.info("No offer variants configured. Ads will use the product's default URL.")

    st.divider()

    # ========================================================================
    # Section 5.8: Additional Instructions (Optional)
    # ========================================================================

    st.subheader("Additional Instructions (Optional)")

    # Get brand's default ad creation notes
    brand_ad_notes = ""
    if selected_product and selected_product.get('brands'):
        brand_ad_notes = selected_product['brands'].get('ad_creation_notes') or ""

    # Show brand defaults if they exist
    if brand_ad_notes:
        st.caption(f"📋 **Brand defaults:** {brand_ad_notes[:100]}{'...' if len(brand_ad_notes) > 100 else ''}")

    additional_instructions = st.text_area(
        "Additional instructions for scheduled runs",
        value=existing_params.get('additional_instructions', ''),
        placeholder="Add any specific instructions for this scheduled job...\n\nExamples:\n- Feature the Brown Sugar flavor prominently\n- Use a summer/outdoor theme\n- Include '20% OFF' badge",
        height=100,
        help="These instructions will be combined with the brand's default ad creation notes for every run"
    )

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

            # Template validation based on source
            if template_source == 'uploaded':
                if template_mode == 'specific' and not template_ids:
                    errors.append("Select at least one template")
                if template_mode == 'upload' and not st.session_state.sched_uploaded_files:
                    errors.append("Upload at least one template image")
            else:
                # Scraped template source
                if not scraped_template_ids:
                    errors.append("Select at least one scraped template")

            if export_destination in ['email', 'both'] and not export_email:
                errors.append("Email address is required")

            # Belief-first validations
            if content_source == 'plan' and not selected_plan_id:
                errors.append("Select a belief plan for plan-based scheduling")
            if content_source == 'angles' and not selected_angle_ids:
                errors.append("Select at least one angle for angle-based scheduling")

            # Offer variant validation - REQUIRED when product has offer variants
            if has_offer_variants and not offer_variant_id:
                errors.append("Offer variant selection is required. This product has multiple landing pages.")

            if errors:
                for error in errors:
                    st.error(error)
            else:
                # Handle upload mode - upload files first (only for uploaded template source)
                if template_source == 'uploaded' and template_mode == 'upload':
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
                    'persona_id': persona_id,
                    'variant_id': variant_id,
                    'offer_variant_id': offer_variant_id,
                    'destination_url': destination_url,
                    'additional_instructions': additional_instructions if additional_instructions else None
                }

                # Add belief-first parameters based on content_source
                if content_source == 'plan':
                    parameters['plan_id'] = selected_plan_id
                elif content_source == 'angles':
                    parameters['angle_ids'] = selected_angle_ids
                    parameters['belief_persona_id'] = belief_persona_id
                    parameters['belief_jtbd_id'] = belief_jtbd_id

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
                    # Template source indicator
                    'template_source': template_source,
                    # For uploaded templates
                    'template_mode': template_mode if template_source == 'uploaded' else None,
                    'template_count': template_count if template_source == 'uploaded' and template_mode == 'unused' else None,
                    'template_ids': template_ids if template_source == 'uploaded' and template_mode in ['specific', 'upload'] else None,
                    # For scraped templates
                    'scraped_template_ids': scraped_template_ids if template_source == 'scraped' else None,
                    'parameters': parameters
                }

                if is_edit:
                    if update_scheduled_job(st.session_state.edit_job_id, job_data):
                        st.success("Schedule updated!")
                        st.session_state.scheduler_view = 'list'
                        st.session_state.sched_selected_templates = []
                        st.session_state.sched_uploaded_files = []
                        st.session_state.sched_selected_angle_ids = []
                        st.session_state.sched_selected_scraped_templates = []
                        st.rerun()
                else:
                    job_id = create_scheduled_job(job_data)
                    if job_id:
                        st.success("Schedule created!")
                        st.session_state.scheduler_view = 'list'
                        st.session_state.sched_selected_templates = []
                        st.session_state.sched_uploaded_files = []
                        st.session_state.sched_selected_angle_ids = []
                        st.session_state.sched_selected_scraped_templates = []
                        st.rerun()

    with col2:
        if st.button("Cancel", use_container_width=True):
            st.session_state.scheduler_view = 'list'
            st.session_state.sched_selected_templates = []
            st.session_state.sched_uploaded_files = []
            st.session_state.sched_selected_angle_ids = []
            st.session_state.sched_selected_scraped_templates = []
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
    brand_info = product_info.get('brands', {}) or job.get('brands', {}) or {}
    job_type = job.get('job_type', 'ad_creation')

    # Header
    col1, col2 = st.columns([4, 2])

    with col1:
        status_emoji = {'active': '🟢', 'paused': '⏸️', 'completed': '✅'}.get(job['status'], '❓')
        type_badge = ""
        if job_type == 'meta_sync':
            type_badge = "🔄 "
        elif job_type == 'scorecard':
            type_badge = "📊 "
        st.title(f"{status_emoji} {type_badge}{job['name']}")
        if job_type == 'ad_creation':
            st.caption(f"{brand_info.get('name', 'Unknown')} → {product_info.get('name', 'Unknown')}")
        else:
            st.caption(f"{brand_info.get('name', 'Unknown')}")

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
        if job_type == 'ad_creation':
            st.markdown("### Templates")
            template_source = job.get('template_source', 'uploaded')
            st.markdown(f"**Source:** {'Scraped Library' if template_source == 'scraped' else 'Uploaded'}")

            if template_source == 'scraped':
                scraped_ids = job.get('scraped_template_ids') or []
                st.markdown(f"**Selected:** {len(scraped_ids)} templates")
            else:
                template_mode = job.get('template_mode') or 'unused'
                st.markdown(f"**Mode:** {template_mode.capitalize()}")

                if template_mode == 'unused':
                    st.markdown(f"**Per Run:** {job.get('template_count', 'N/A')} templates")
                else:
                    template_ids = job.get('template_ids') or []
                    st.markdown(f"**Selected:** {len(template_ids)} templates")
        elif job_type == 'meta_sync':
            st.markdown("### Sync Settings")
            params = job.get('parameters', {}) or {}
            st.markdown(f"**Days Back:** {params.get('days_back', 7)}")
        elif job_type == 'scorecard':
            st.markdown("### Scorecard Settings")
            params = job.get('parameters', {}) or {}
            st.markdown(f"**Days Back:** {params.get('days_back', 7)}")
            st.markdown(f"**Min Spend:** ${params.get('min_spend', 10.0)}")
            if params.get('export_email'):
                st.markdown(f"**Email:** {params['export_email']}")

    st.divider()

    # Parameters - only show for ad_creation jobs
    if job_type == 'ad_creation':
        st.markdown("### Ad Creation Parameters")
        params = job.get('parameters', {}) or {}

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

            # Display variant if set
            variant_id = params.get('variant_id')
            if variant_id:
                # Try to get variant name
                variants = get_variants_for_product(job['product_id'])
                variant = next((v for v in variants if v['id'] == variant_id), None)
                variant_name = variant['name'] if variant else variant_id[:8]
                st.markdown(f"**Variant:** {variant_name}")
            else:
                st.markdown("**Variant:** Default")

        # Display offer variant / landing page if set
        offer_variant_id = params.get('offer_variant_id')
        destination_url = params.get('destination_url')
        if offer_variant_id or destination_url:
            st.markdown("### Landing Page / Offer Variant")
            if offer_variant_id:
                offer_variants = get_offer_variants_for_product(job['product_id'])
                ov = next((v for v in offer_variants if v['id'] == offer_variant_id), None)
                if ov:
                    st.markdown(f"**Offer:** {ov['name']}")
                    st.markdown(f"**URL:** `{ov['landing_page_url']}`")
                    pain_points = ov.get('pain_points') or []
                    if pain_points:
                        st.caption(f"Pain points: {', '.join(pain_points[:3])}")
                else:
                    st.markdown(f"**Offer ID:** {offer_variant_id[:8]}...")
            elif destination_url:
                st.markdown(f"**URL:** `{destination_url}`")
            st.divider()

        # Display additional instructions if set
        add_instructions = params.get('additional_instructions')
        if add_instructions:
            st.markdown("**Additional Instructions:**")
            st.caption(add_instructions[:200] + ('...' if len(add_instructions) > 200 else ''))

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
                    st.text_area("Logs", run['logs'], height=100, key=f"logs_{run['id']}")


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
