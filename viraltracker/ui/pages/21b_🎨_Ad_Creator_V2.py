"""
Ad Creator V2 - Template-scored ad generation with Pydantic prompts.

V2 runs in parallel with V1 (V1 is NOT modified). Key differences:
- Template selection via scoring pipeline (manual / roll the dice / smart select)
- Pydantic prompt construction with validation
- Jobs submitted to scheduler worker (not live execution)
- Pipeline version and prompt version tracked in output
"""

import streamlit as st
from datetime import datetime, timedelta
import pytz

# Page config
st.set_page_config(
    page_title="Ad Creator V2",
    page_icon="🎨",
    layout="wide"
)

# Authentication
from viraltracker.ui.auth import require_auth
require_auth()
from viraltracker.ui.utils import require_feature
require_feature("ad_creator", "Ad Creator V2")

PST = pytz.timezone('America/Los_Angeles')

import logging
logger = logging.getLogger(__name__)


# ============================================================================
# Session State
# ============================================================================

if 'v2_view' not in st.session_state:
    st.session_state.v2_view = 'create'  # 'create' or 'results'
if 'v2_template_mode' not in st.session_state:
    st.session_state.v2_template_mode = 'roll_the_dice'
if 'v2_selected_scraped_templates' not in st.session_state:
    st.session_state.v2_selected_scraped_templates = []
if 'v2_category' not in st.session_state:
    st.session_state.v2_category = 'all'
if 'v2_preview_result' not in st.session_state:
    st.session_state.v2_preview_result = None
if 'v2_templates_visible' not in st.session_state:
    st.session_state.v2_templates_visible = 30


# ============================================================================
# Database Helpers
# ============================================================================

def get_supabase_client():
    """Get Supabase client."""
    from viraltracker.core.database import get_supabase_client
    return get_supabase_client()


def get_products():
    """Fetch products filtered by current organization."""
    from viraltracker.ui.utils import get_current_organization_id

    try:
        db = get_supabase_client()
        org_id = get_current_organization_id()

        query = db.table("products").select(
            "id, name, brand_id, target_audience, brands(id, name, brand_colors, brand_fonts, organization_id)"
        )

        if not org_id:
            return []

        if org_id == "all":
            result = query.order("name").execute()
            return result.data or []

        brand_result = db.table("brands").select("id").eq("organization_id", org_id).execute()
        brand_ids = [b["id"] for b in (brand_result.data or [])]
        if not brand_ids:
            return []

        result = query.in_("brand_id", brand_ids).order("name").execute()
        return result.data or []
    except Exception as e:
        st.error(f"Failed to load products: {e}")
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


def get_scraped_templates(category=None, awareness_level=None, industry_niche=None, target_sex=None, limit=100):
    """Fetch active scraped templates with optional filters."""
    try:
        from viraltracker.services.template_queue_service import TemplateQueueService
        service = TemplateQueueService()
        return service.get_templates(
            category=category if category != "all" else None,
            awareness_level=awareness_level,
            industry_niche=industry_niche if industry_niche != "all" else None,
            target_sex=target_sex if target_sex != "all" else None,
            active_only=True,
            limit=limit,
        )
    except Exception as e:
        st.warning(f"Could not load templates: {e}")
        return []


def get_scraped_template_url(storage_path: str) -> str:
    """Get public URL for scraped template asset."""
    try:
        from viraltracker.services.template_queue_service import TemplateQueueService
        service = TemplateQueueService()
        return service.get_asset_preview_url(storage_path)
    except Exception:
        return ""


def get_personas_for_product(product_id: str):
    """Get personas linked to a product."""
    try:
        from viraltracker.services.ad_creation_service import AdCreationService
        from uuid import UUID
        service = AdCreationService()
        return service.get_personas_for_product(UUID(product_id))
    except Exception:
        return []


def create_scheduled_job(job_data: dict):
    """Create a scheduled job. Returns job ID."""
    try:
        db = get_supabase_client()
        result = db.table("scheduled_jobs").insert(job_data).execute()
        return result.data[0]['id'] if result.data else None
    except Exception as e:
        st.error(f"Failed to create job: {e}")
        return None


def get_v2_job_runs():
    """Get recent V2 job runs with results."""
    try:
        db = get_supabase_client()
        result = db.table("scheduled_jobs").select(
            "id, name, product_id, status, created_at, runs_completed, "
            "products(name, brands(name)), parameters, scraped_template_ids"
        ).eq("job_type", "ad_creation_v2").order("created_at", desc=True).limit(20).execute()
        return result.data or []
    except Exception:
        return []


def get_job_run_details(job_id: str):
    """Get run details for a V2 job."""
    try:
        db = get_supabase_client()
        result = db.table("scheduled_job_runs").select(
            "id, status, started_at, completed_at, metadata, logs, ad_run_ids, templates_used"
        ).eq("scheduled_job_id", job_id).order("started_at", desc=True).limit(5).execute()
        return result.data or []
    except Exception:
        return []


def is_template_selected(template_id: str) -> bool:
    """Check if a scraped template is currently selected."""
    return any(t['id'] == template_id for t in st.session_state.v2_selected_scraped_templates)


def toggle_template_selection(template_info: dict):
    """Toggle a template in the manual selection list."""
    current = st.session_state.v2_selected_scraped_templates
    existing_idx = next(
        (i for i, t in enumerate(current) if t['id'] == template_info['id']),
        None
    )
    if existing_idx is not None:
        current.pop(existing_idx)
    else:
        current.append(template_info)
    st.session_state.v2_selected_scraped_templates = current


# ============================================================================
# Template Selection Section
# ============================================================================

def render_template_selection():
    """Render template selection with 3 modes."""
    st.subheader("1. Template Selection")

    mode = st.radio(
        "How do you want to select templates?",
        options=["manual", "roll_the_dice", "smart_select"],
        index=["manual", "roll_the_dice", "smart_select"].index(st.session_state.v2_template_mode),
        format_func=lambda x: {
            "manual": "Choose templates manually",
            "roll_the_dice": "Roll the dice - weighted random (favors unused)",
            "smart_select": "Smart select - scored best-fit templates",
        }[x],
        horizontal=True,
        key="v2_template_mode_radio",
    )
    st.session_state.v2_template_mode = mode

    if mode == "manual":
        _render_manual_template_selection()
    elif mode == "roll_the_dice":
        _render_scored_template_selection(mode)
    else:
        _render_scored_template_selection(mode)


def _render_manual_template_selection():
    """Render manual template grid with filters and pagination."""
    # --- Filter row (4 columns) ---
    fc1, fc2, fc3, fc4 = st.columns(4)

    with fc1:
        categories = get_template_categories()
        category = st.selectbox(
            "Category",
            options=categories,
            index=categories.index(st.session_state.v2_category) if st.session_state.v2_category in categories else 0,
            format_func=lambda x: x.replace("_", " ").title() if x != "all" else "All",
            key="v2_filter_category",
        )

    with fc2:
        awareness_levels = get_awareness_levels()
        awareness_options = [None] + [a['value'] for a in awareness_levels]
        awareness_labels = {None: "All", **{a['value']: a['label'] for a in awareness_levels}}
        awareness_level = st.selectbox(
            "Awareness Level",
            options=awareness_options,
            format_func=lambda x: awareness_labels.get(x, str(x)),
            key="v2_filter_awareness",
        )

    with fc3:
        niches = get_industry_niches()
        niche_options = ["all"] + niches
        industry_niche = st.selectbox(
            "Industry / Niche",
            options=niche_options,
            format_func=lambda x: x.replace("_", " ").title() if x != "all" else "All",
            key="v2_filter_niche",
        )

    with fc4:
        sex_options = ["all", "male", "female", "unisex"]
        target_sex = st.selectbox(
            "Target Audience",
            options=sex_options,
            format_func=lambda x: x.title() if x != "all" else "All",
            key="v2_filter_sex",
        )

    # Reset pagination when any filter changes
    _current_filters = (category, awareness_level, industry_niche, target_sex)
    if st.session_state.get('_v2_prev_filters') != _current_filters:
        st.session_state.v2_templates_visible = 30
        st.session_state['_v2_prev_filters'] = _current_filters

    # Persist category for other sections
    st.session_state.v2_category = category

    # --- Header row ---
    selected_count = len(st.session_state.v2_selected_scraped_templates)
    hdr1, hdr2 = st.columns([3, 1])
    with hdr1:
        cat_label = category.replace("_", " ").title() if category != "all" else "All"
        st.markdown(f"**Showing templates in '{cat_label}'** | **{selected_count} selected**")
    with hdr2:
        if selected_count > 0 and st.button("Clear Selection", key="v2_clear_templates"):
            st.session_state.v2_selected_scraped_templates = []
            st.rerun()

    # --- Fetch templates with all filters ---
    templates = get_scraped_templates(
        category=category,
        awareness_level=awareness_level,
        industry_niche=industry_niche,
        target_sex=target_sex,
    )

    if not templates:
        st.info("No templates found for the selected filters.")
        return

    # --- Grid display (paginated) ---
    visible = st.session_state.v2_templates_visible
    cols = st.columns(5)
    for i, tmpl in enumerate(templates[:visible]):
        with cols[i % 5]:
            selected = is_template_selected(tmpl['id'])
            storage_path = tmpl.get('storage_path', '')

            # Show thumbnail
            thumb_url = get_scraped_template_url(storage_path) if storage_path else ""
            if thumb_url:
                border_style = "3px solid #00ff00" if selected else "1px solid #333"
                st.markdown(
                    f'<img src="{thumb_url}" style="width:100%;border:{border_style};border-radius:4px;">',
                    unsafe_allow_html=True,
                )
            else:
                st.caption("No preview")

            st.caption(f"**{tmpl.get('name', 'Template')[:35]}**")
            st.caption(f"{tmpl.get('category', '').replace('_', ' ').title()} | Used: {tmpl.get('times_used', 0)}x")

            if st.button(
                "Deselect" if selected else "Select",
                key=f"v2_tmpl_{tmpl['id']}",
                type="primary" if selected else "secondary",
            ):
                parts = storage_path.split('/', 1) if storage_path else ['scraped-assets', '']
                bucket = parts[0] if len(parts) == 2 else 'scraped-assets'
                path = parts[1] if len(parts) == 2 else storage_path

                toggle_template_selection({
                    'id': tmpl['id'],
                    'name': tmpl.get('name', 'Template'),
                    'storage_path': path,
                    'bucket': bucket,
                    'full_storage_path': storage_path,
                })
                st.rerun()

    # --- Load More pagination ---
    if visible < len(templates):
        remaining = len(templates) - visible
        if st.button(f"Load More ({remaining} remaining)", key="v2_load_more"):
            st.session_state.v2_templates_visible += 30
            st.rerun()


def _render_scored_template_selection(mode: str):
    """Render scored template selection (roll_the_dice or smart_select)."""
    col1, col2 = st.columns(2)

    with col1:
        template_count = st.slider(
            "Number of templates",
            min_value=1, max_value=10, value=3,
            key="v2_template_count",
        )

    with col2:
        categories = get_template_categories()
        category = st.selectbox(
            "Category filter",
            options=categories,
            index=categories.index(st.session_state.v2_category) if st.session_state.v2_category in categories else 0,
            format_func=lambda x: x.replace("_", " ").title() if x != "all" else "All",
            key="v2_scored_category",
        )
        st.session_state.v2_category = category

    # Smart select has asset strictness option
    asset_strictness = "default"
    if mode == "smart_select":
        asset_strictness = st.selectbox(
            "Asset strictness",
            options=["default", "growth", "premium"],
            format_func=lambda x: {
                "default": "Default - all templates eligible",
                "growth": "Growth - basic asset matching required",
                "premium": "Premium - strict asset + detection required",
            }[x],
            key="v2_asset_strictness",
        )

    # Preview button
    if st.button("Preview Selection", key="v2_preview_selection"):
        with st.spinner("Scoring templates..."):
            preview = _run_template_preview(
                mode=mode,
                count=template_count,
                category=category if category != "all" else None,
                asset_strictness=asset_strictness,
            )
            st.session_state.v2_preview_result = preview

    # Show preview results
    if st.session_state.v2_preview_result:
        preview = st.session_state.v2_preview_result
        if preview.get("error"):
            st.error(preview["error"])
        elif preview.get("empty"):
            st.warning(f"No templates selected: {preview.get('reason', 'Unknown')}")
        else:
            st.success(f"Selected {len(preview['templates'])} templates "
                       f"({preview['candidates_after_gate']}/{preview['candidates_before_gate']} passed gate)")

            for i, (tmpl, scores) in enumerate(zip(preview['templates'], preview['scores'])):
                with st.expander(f"#{i+1}: {tmpl.get('name', tmpl['id'][:8])}", expanded=i == 0):
                    img_col, scores_col = st.columns([1, 3])
                    with img_col:
                        storage_path = tmpl.get('storage_path', '')
                        thumb_url = get_scraped_template_url(storage_path) if storage_path else ""
                        if thumb_url:
                            st.image(thumb_url, width=150)
                        else:
                            st.caption("No preview")
                    with scores_col:
                        s1, s2, s3, s4 = st.columns(4)
                        with s1:
                            st.metric("Composite", f"{scores.get('composite', 0):.3f}")
                        with s2:
                            st.metric("Asset Match", f"{scores.get('asset_match', 0):.2f}")
                        with s3:
                            st.metric("Unused Bonus", f"{scores.get('unused_bonus', 0):.2f}")
                        with s4:
                            st.metric("Category", f"{scores.get('category_match', 0):.2f}")
                    st.caption(f"Category: {tmpl.get('category', 'N/A')} | "
                               f"Used: {tmpl.get('times_used', 0)}x")


def _run_template_preview(mode, count, category, asset_strictness):
    """Run template scoring preview. Returns result dict."""
    try:
        import asyncio
        from viraltracker.services.template_scoring_service import (
            fetch_template_candidates, prefetch_product_asset_tags,
            select_templates_with_fallback, SelectionContext,
            ROLL_THE_DICE_WEIGHTS, SMART_SELECT_WEIGHTS,
        )
        from uuid import UUID

        product_id = st.session_state.get('v2_product_id')
        brand_id = st.session_state.get('v2_brand_id')
        if not product_id:
            return {"error": "No product selected"}

        loop = asyncio.new_event_loop()

        # Prefetch
        asset_tags = loop.run_until_complete(prefetch_product_asset_tags(product_id))
        candidates = loop.run_until_complete(fetch_template_candidates(product_id))

        context = SelectionContext(
            product_id=UUID(product_id),
            brand_id=UUID(brand_id) if brand_id else UUID(product_id),
            product_asset_tags=asset_tags,
            requested_category=category,
        )

        weights = ROLL_THE_DICE_WEIGHTS if mode == 'roll_the_dice' else SMART_SELECT_WEIGHTS

        min_asset_score = 0.0
        if asset_strictness == 'growth':
            min_asset_score = 0.3
        elif asset_strictness == 'premium':
            min_asset_score = 0.8

        result = select_templates_with_fallback(
            candidates=candidates,
            context=context,
            weights=weights,
            count=count,
            min_asset_score=min_asset_score,
        )

        loop.close()

        return {
            "templates": result.templates,
            "scores": result.scores,
            "empty": result.empty,
            "reason": result.reason,
            "candidates_before_gate": result.candidates_before_gate,
            "candidates_after_gate": result.candidates_after_gate,
        }
    except Exception as e:
        return {"error": str(e)}


# ============================================================================
# Generation Config Section
# ============================================================================

def render_generation_config():
    """Render generation configuration controls."""
    st.subheader("2. Generation Config")

    col1, col2 = st.columns(2)

    with col1:
        content_source = st.selectbox(
            "Content source",
            options=["hooks", "recreate_template", "belief_first", "plan", "angles"],
            format_func=lambda x: {
                "hooks": "Hooks - headline from hook library",
                "recreate_template": "Recreate Template - benefits/USPs",
                "belief_first": "Belief First - angle-driven",
                "plan": "Plan - belief plan execution",
                "angles": "Angles - direct angle injection",
            }[x],
            key="v2_content_source",
        )

        color_mode = st.selectbox(
            "Color mode",
            options=["original", "complementary", "brand"],
            format_func=lambda x: {
                "original": "Original - match template colors",
                "complementary": "Complementary - fresh color scheme",
                "brand": "Brand - use brand colors",
            }[x],
            key="v2_color_mode",
        )

    with col2:
        num_variations = st.slider(
            "Variations per template",
            min_value=1, max_value=15, value=5,
            key="v2_num_variations",
        )

        image_resolution = st.selectbox(
            "Image resolution",
            options=["1K", "2K", "4K"],
            index=1,
            key="v2_image_resolution",
        )

    # Optional settings
    with st.expander("Advanced Settings"):
        col1, col2 = st.columns(2)

        with col1:
            canvas_size = st.selectbox(
                "Canvas size",
                options=["1080x1080px", "1080x1350px", "1080x1920px", "1200x628px"],
                key="v2_canvas_size",
            )

            product_id = st.session_state.get('v2_product_id')
            personas = get_personas_for_product(product_id) if product_id else []
            persona_options = [{"id": None, "name": "None (default)"}] + personas
            persona_id = st.selectbox(
                "Persona",
                options=[p['id'] for p in persona_options],
                format_func=lambda x: next((p['name'] for p in persona_options if p['id'] == x), "Unknown"),
                key="v2_persona_id",
            )

        with col2:
            additional_instructions = st.text_area(
                "Additional instructions",
                placeholder="Optional run-specific instructions...",
                key="v2_additional_instructions",
            )


# ============================================================================
# Batch Estimate Section
# ============================================================================

def render_batch_estimate():
    """Show batch estimate with cost projection."""
    st.subheader("3. Batch Estimate")

    mode = st.session_state.v2_template_mode
    num_variations = st.session_state.get('v2_num_variations', 5)

    if mode == "manual":
        template_count = len(st.session_state.v2_selected_scraped_templates)
    else:
        template_count = st.session_state.get('v2_template_count', 3)

    total_attempts = template_count * num_variations
    estimated_cost = total_attempts * 0.02  # ~$0.02/attempt

    col1, col2, col3 = st.columns(3)
    with col1:
        st.metric("Templates", template_count)
    with col2:
        st.metric("Total Attempts", total_attempts)
    with col3:
        st.metric("Est. Cost", f"${estimated_cost:.2f}")

    if total_attempts > 50:
        st.warning(f"Total attempts ({total_attempts}) exceeds the per-run limit of 50. "
                   f"The worker will stop after 50 attempts.")


# ============================================================================
# Submit Section
# ============================================================================

def render_submit():
    """Render submit button and create scheduled job."""
    col1, col2 = st.columns(2)

    with col1:
        if st.button("Submit V2 Job", type="primary", use_container_width=True, key="v2_submit"):
            _handle_submit()

    with col2:
        if st.button("View Results", use_container_width=True, key="v2_view_results"):
            st.session_state.v2_view = 'results'
            st.rerun()


def _handle_submit():
    """Validate and submit the V2 job."""
    product_id = st.session_state.get('v2_product_id')
    brand_id = st.session_state.get('v2_brand_id')
    product_name = st.session_state.get('v2_product_name', 'Product')

    if not product_id:
        st.error("Please select a product.")
        return

    mode = st.session_state.v2_template_mode

    # Validate manual mode has templates selected
    if mode == "manual":
        if not st.session_state.v2_selected_scraped_templates:
            st.error("Please select at least one template.")
            return

    # Build parameters
    parameters = {
        'template_selection_mode': mode,
        'template_count': st.session_state.get('v2_template_count', 3),
        'template_category': st.session_state.v2_category if st.session_state.v2_category != 'all' else None,
        'content_source': st.session_state.get('v2_content_source', 'hooks'),
        'color_mode': st.session_state.get('v2_color_mode', 'original'),
        'num_variations': st.session_state.get('v2_num_variations', 5),
        'canvas_size': st.session_state.get('v2_canvas_size', '1080x1080px'),
        'image_resolution': st.session_state.get('v2_image_resolution', '2K'),
        'persona_id': st.session_state.get('v2_persona_id'),
        'additional_instructions': st.session_state.get('v2_additional_instructions') or None,
    }

    if mode == "smart_select":
        parameters['asset_strictness'] = st.session_state.get('v2_asset_strictness', 'default')

    # Build job name
    job_name = f"V2 Ad Creation - {product_name} ({mode.replace('_', ' ').title()})"

    # Manual mode: include template IDs
    scraped_template_ids = None
    if mode == "manual":
        scraped_template_ids = [t['id'] for t in st.session_state.v2_selected_scraped_templates]

    # Submit as one-time job running in ~1 minute
    run_now_time = datetime.now(PST) + timedelta(minutes=1)

    job_data = {
        'job_type': 'ad_creation_v2',
        'product_id': product_id,
        'brand_id': brand_id,
        'name': job_name,
        'schedule_type': 'one_time',
        'cron_expression': None,
        'scheduled_at': run_now_time.isoformat(),
        'next_run_at': run_now_time.isoformat(),
        'max_runs': None,
        'template_source': 'scraped',
        'scraped_template_ids': scraped_template_ids,
        'parameters': parameters,
    }

    job_id = create_scheduled_job(job_data)
    if job_id:
        st.success(f"V2 job submitted! Will run in ~1 minute.")
        st.info(f"Job ID: {job_id}")
        st.caption("View progress in Scheduled Tasks page or click 'View Results' below.")
        # Clear preview
        st.session_state.v2_preview_result = None


# ============================================================================
# Results View
# ============================================================================

def render_results():
    """Render V2 job results view."""
    st.title("V2 Ad Creation Results")

    if st.button("Back to Create", key="v2_back_to_create"):
        st.session_state.v2_view = 'create'
        st.rerun()

    st.divider()

    jobs = get_v2_job_runs()

    if not jobs:
        st.info("No V2 jobs found. Submit a job from the Create tab.")
        return

    for job in jobs:
        product_info = job.get('products', {}) or {}
        brand_info = product_info.get('brands', {}) or {}
        params = job.get('parameters', {}) or {}
        status_emoji = {'active': 'Running', 'paused': 'Paused', 'completed': 'Done'}.get(
            job['status'], job['status']
        )

        with st.expander(
            f"{job['name']} | {status_emoji} | "
            f"{brand_info.get('name', '?')} > {product_info.get('name', '?')}",
            expanded=False,
        ):
            col1, col2, col3, col4 = st.columns(4)
            with col1:
                st.caption(f"Mode: {params.get('template_selection_mode', 'N/A')}")
            with col2:
                st.caption(f"Content: {params.get('content_source', 'N/A')}")
            with col3:
                st.caption(f"Variations: {params.get('num_variations', 'N/A')}")
            with col4:
                st.caption(f"Runs: {job.get('runs_completed', 0)}")

            # Show run details
            runs = get_job_run_details(job['id'])
            for run in runs:
                metadata = run.get('metadata') or {}
                run_status = run.get('status', 'unknown')

                status_icon = {'running': 'Running...', 'completed': 'Completed', 'failed': 'Failed'}.get(
                    run_status, run_status
                )

                st.markdown(f"**Run:** {status_icon}")

                if metadata:
                    mcol1, mcol2, mcol3 = st.columns(3)
                    with mcol1:
                        st.metric("Attempted", metadata.get('ads_attempted', 0))
                    with mcol2:
                        st.metric("Approved", metadata.get('ads_approved', 0))
                    with mcol3:
                        if metadata.get('ads_attempted', 0) > 0:
                            rate = metadata.get('ads_approved', 0) / metadata['ads_attempted'] * 100
                            st.metric("Approval Rate", f"{rate:.0f}%")

                    if metadata.get('template_progress'):
                        st.caption(f"Progress: {metadata['template_progress']}")

                # Show logs in collapsible
                if run.get('logs'):
                    with st.expander("Logs", expanded=False):
                        st.code(run['logs'], language="text")

                st.divider()


# ============================================================================
# Main Page
# ============================================================================

st.title("Ad Creator V2")
st.caption("Template-scored generation with Pydantic prompts | Pipeline v2")

if st.session_state.v2_view == 'results':
    render_results()
else:
    # Product selector
    from viraltracker.ui.utils import render_brand_selector
    brand_id, product_id = render_brand_selector(
        key="v2_brand_selector",
        include_product=True,
        product_key="v2_product_selector"
    )

    if not product_id:
        st.info("Select a product to get started.")
        st.stop()

    # Store in session state for other functions
    products = get_products()
    product = next((p for p in products if p['id'] == product_id), None)
    st.session_state.v2_product_id = product_id
    st.session_state.v2_brand_id = brand_id or (product.get('brand_id') if product else None)
    st.session_state.v2_product_name = product.get('name', 'Product') if product else 'Product'

    st.divider()

    # Render sections
    render_template_selection()
    st.divider()
    render_generation_config()
    st.divider()
    render_batch_estimate()
    st.divider()
    render_submit()
