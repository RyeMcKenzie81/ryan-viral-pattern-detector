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
                        s1, s2, s3, s4, s5, s6 = st.columns(6)
                        with s1:
                            st.metric("Composite", f"{scores.get('composite', 0):.3f}")
                        with s2:
                            st.metric("Asset", f"{scores.get('asset_match', 0):.2f}")
                        with s3:
                            st.metric("Unused", f"{scores.get('unused_bonus', 0):.2f}")
                        with s4:
                            st.metric("Category", f"{scores.get('category_match', 0):.2f}")
                        with s5:
                            st.metric("Awareness", f"{scores.get('awareness_align', 0):.2f}")
                        with s6:
                            st.metric("Audience", f"{scores.get('audience_match', 0):.2f}")
                    st.caption(f"Category: {tmpl.get('category', 'N/A')} | "
                               f"Used: {tmpl.get('times_used', 0)}x")


def _run_template_preview(mode, count, category, asset_strictness):
    """Run template scoring preview. Returns result dict."""
    try:
        import asyncio
        from viraltracker.services.template_scoring_service import (
            fetch_template_candidates, prefetch_product_asset_tags,
            select_templates_with_fallback, SelectionContext,
            fetch_brand_min_asset_score,
            ROLL_THE_DICE_WEIGHTS, SMART_SELECT_WEIGHTS,
            PHASE_8_SCORERS,
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

        # Extract persona target_sex for AudienceMatchScorer
        persona_target_sex = None
        persona_id = st.session_state.get('v2_persona_id')
        if persona_id:
            try:
                from viraltracker.services.persona_service import PersonaService
                persona_service = PersonaService()
                persona_data = persona_service.export_for_ad_generation(UUID(persona_id))
                if persona_data:
                    demographics = persona_data.get("demographics") or {}
                    gender = (demographics.get("gender") or "").lower().strip()
                    if gender in ("male", "female"):
                        persona_target_sex = gender
                    elif gender in ("any", "all", "both"):
                        persona_target_sex = "unisex"
            except Exception as e:
                logger.warning(f"Failed to load persona for scoring preview: {e}")

        context = SelectionContext(
            product_id=UUID(product_id),
            brand_id=UUID(brand_id) if brand_id else UUID(product_id),
            product_asset_tags=asset_tags,
            requested_category=category,
            target_sex=persona_target_sex,
        )

        if mode == 'roll_the_dice':
            weights = ROLL_THE_DICE_WEIGHTS
        else:
            # Phase 8B: use learned weights for smart_select preview
            try:
                from viraltracker.services.scorer_weight_learning_service import ScorerWeightLearningService
                learning_service = ScorerWeightLearningService()
                weights = learning_service.get_learned_weights(
                    UUID(brand_id) if brand_id else UUID(product_id),
                    mode="smart_select",
                )
            except Exception:
                weights = SMART_SELECT_WEIGHTS

        min_asset_score = 0.0
        if asset_strictness == 'growth':
            min_asset_score = 0.3
        elif asset_strictness == 'premium':
            min_asset_score = 0.8
        elif asset_strictness == 'default' and brand_id:
            min_asset_score = fetch_brand_min_asset_score(brand_id)

        result = select_templates_with_fallback(
            candidates=candidates,
            context=context,
            weights=weights,
            count=count,
            min_asset_score=min_asset_score,
            scorers=PHASE_8_SCORERS,
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

        num_variations = st.slider(
            "Variations (hooks) per template",
            min_value=1, max_value=50, value=5,
            key="v2_num_variations",
        )

    with col2:
        image_resolution = st.selectbox(
            "Image resolution",
            options=["1K", "2K", "4K"],
            index=1,
            key="v2_image_resolution",
        )

    # Phase 2: Multi-size + multi-color controls
    st.markdown("**Output Variants**")
    size_col, color_col = st.columns(2)

    with size_col:
        canvas_sizes = st.multiselect(
            "Canvas sizes",
            options=["1080x1080px", "1080x1350px", "1080x1920px", "1200x628px"],
            default=["1080x1080px"],
            format_func=lambda x: {
                "1080x1080px": "1:1 (1080x1080) - Feed",
                "1080x1350px": "4:5 (1080x1350) - Feed optimal",
                "1080x1920px": "9:16 (1080x1920) - Stories/Reels",
                "1200x628px": "16:9 (1200x628) - Landscape",
            }[x],
            key="v2_canvas_sizes",
        )
        if not canvas_sizes:
            st.warning("Select at least one canvas size.")

    with color_col:
        color_modes = st.multiselect(
            "Color modes",
            options=["original", "complementary", "brand"],
            default=["original"],
            format_func=lambda x: {
                "original": "Original - match template colors",
                "complementary": "Complementary - fresh palette",
                "brand": "Brand - use brand colors",
            }[x],
            key="v2_color_modes",
        )
        if not color_modes:
            st.warning("Select at least one color mode.")

    # Optional settings
    with st.expander("Advanced Settings"):
        col1, col2 = st.columns(2)

        with col1:
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
    """Show batch estimate with cost projection and tiered guardrails."""
    from viraltracker.pipelines.ad_creation_v2.services.cost_estimation import (
        estimate_run_cost, MAX_VARIATIONS_PER_RUN,
    )

    st.subheader("3. Batch Estimate")

    mode = st.session_state.v2_template_mode
    num_variations = st.session_state.get('v2_num_variations', 5)
    size_count = len(st.session_state.get('v2_canvas_sizes', ['1080x1080px']))
    color_count = len(st.session_state.get('v2_color_modes', ['original']))

    if mode == "manual":
        template_count = len(st.session_state.v2_selected_scraped_templates)
    else:
        template_count = st.session_state.get('v2_template_count', 3)

    size_color_combos = size_count * color_count
    total_attempts = template_count * num_variations * size_color_combos

    # Cost estimation using configurable pricing
    cost = estimate_run_cost(
        num_variations=num_variations,
        num_canvas_sizes=size_count,
        num_color_modes=color_count,
        auto_retry=False,
    )

    col1, col2, col3, col4 = st.columns(4)
    with col1:
        st.metric("Templates", template_count)
    with col2:
        st.metric("Variations", num_variations)
    with col3:
        st.metric("Size x Color", size_color_combos)
    with col4:
        st.metric("Total Attempts", total_attempts)

    st.caption(f"Est. cost: **${cost['total_cost']:.2f}** "
               f"(${cost['per_ad_cost']:.3f}/ad × {cost['total_ads']} ads + fixed)")

    # Tiered guardrails
    if num_variations > MAX_VARIATIONS_PER_RUN:
        num_jobs = -(-num_variations // MAX_VARIATIONS_PER_RUN)  # ceil division
        per_job = -(-num_variations // num_jobs)
        st.error(
            f"Variations ({num_variations}) exceeds the per-run limit of "
            f"{MAX_VARIATIONS_PER_RUN}. "
            f"Reduce to {MAX_VARIATIONS_PER_RUN} or fewer."
        )
        st.info(
            f"Tip: Auto-split into {num_jobs} sequential jobs of "
            f"~{per_job} variations each."
        )
        st.session_state['v2_submit_blocked'] = True
    elif num_variations > 30:
        st.warning(
            f"Large batch ({num_variations} variations). "
            f"Estimated cost: **${cost['total_cost']:.2f}**."
        )
        confirmed = st.checkbox(
            "I confirm this large batch run",
            key="v2_large_batch_confirm",
        )
        st.session_state['v2_submit_blocked'] = not confirmed
    elif num_variations > 10:
        st.info(f"Estimated cost: **${cost['total_cost']:.2f}**")
        st.session_state['v2_submit_blocked'] = False
    else:
        st.session_state['v2_submit_blocked'] = False

    if total_attempts > MAX_VARIATIONS_PER_RUN and num_variations <= MAX_VARIATIONS_PER_RUN:
        st.warning(
            f"Total attempts ({total_attempts}) across all templates exceeds "
            f"{MAX_VARIATIONS_PER_RUN}. The worker will process templates sequentially."
        )


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

    # Phase 5: Block if guardrails not satisfied
    if st.session_state.get('v2_submit_blocked', False):
        st.error("Resolve batch size warnings before submitting.")
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
        'canvas_sizes': st.session_state.get('v2_canvas_sizes', ['1080x1080px']),
        'color_modes': st.session_state.get('v2_color_modes', ['original']),
        'num_variations': st.session_state.get('v2_num_variations', 5),
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
# Results View — Phase 4: structured scores, defect/congruence, overrides
# ============================================================================

def _get_override_service():
    """Lazy import override service."""
    from viraltracker.services.ad_review_override_service import AdReviewOverrideService
    return AdReviewOverrideService()


def _get_signed_url(storage_path: str) -> str:
    """Get signed URL for image display."""
    if not storage_path:
        return ""
    db = get_supabase_client()
    parts = storage_path.split("/", 1)
    bucket = parts[0]
    path = parts[1] if len(parts) > 1 else storage_path
    try:
        result = db.storage.from_(bucket).create_signed_url(path, 3600)
        return result.get("signedURL", "")
    except Exception:
        return ""


def _score_color(score: float) -> str:
    """Return CSS color for a 0-10 rubric score."""
    if score >= 8.0:
        return "#2ecc71"  # green
    if score >= 6.0:
        return "#f39c12"  # amber
    return "#e74c3c"  # red


def _status_badge(status: str, override_status: str = None) -> str:
    """Return a styled badge string for ad status."""
    badge_map = {
        "approved": ("Approved", "#2ecc71"),
        "rejected": ("Rejected", "#e74c3c"),
        "flagged": ("Flagged", "#f39c12"),
        "review_failed": ("Review Failed", "#95a5a6"),
        "generation_failed": ("Gen Failed", "#95a5a6"),
    }
    override_map = {
        "override_approved": ("Override Approved", "#27ae60"),
        "override_rejected": ("Override Rejected", "#c0392b"),
        "confirmed": ("Confirmed", "#2980b9"),
    }
    if override_status and override_status in override_map:
        label, color = override_map[override_status]
    elif status in badge_map:
        label, color = badge_map[status]
    else:
        label, color = status, "#95a5a6"
    return f'<span style="background:{color};color:white;padding:2px 8px;border-radius:4px;font-size:0.85em;">{label}</span>'


def _render_rubric_scores(scores: dict):
    """Render the 15-check rubric scores as colored bars."""
    if not scores:
        st.caption("No structured review scores")
        return

    visual_checks = [f"V{i}" for i in range(1, 10)]
    content_checks = [f"C{i}" for i in range(1, 5)]
    congruence_checks = ["G1", "G2"]

    for group_name, checks in [
        ("Visual", visual_checks),
        ("Content", content_checks),
        ("Congruence", congruence_checks),
    ]:
        cols = st.columns(len(checks) + 1)
        with cols[0]:
            st.caption(f"**{group_name}**")
        for idx, check in enumerate(checks):
            with cols[idx + 1]:
                val = scores.get(check, 5.0)
                color = _score_color(val)
                st.markdown(
                    f'<div style="text-align:center">'
                    f'<div style="font-size:0.7em;color:#888">{check}</div>'
                    f'<div style="font-size:1.1em;font-weight:bold;color:{color}">{val:.1f}</div>'
                    f'</div>',
                    unsafe_allow_html=True,
                )


def _render_defect_result(defect_result: dict):
    """Render defect scan result."""
    if not defect_result:
        return
    passed = defect_result.get("passed", True)
    defects = defect_result.get("defects", [])
    model = defect_result.get("model", "?")
    latency = defect_result.get("latency_ms", 0)

    if passed:
        st.caption(f"Defect Scan: Passed ({model}, {latency}ms)")
    else:
        st.caption(f"Defect Scan: **FAILED** ({model}, {latency}ms)")
        for d in defects:
            st.markdown(f"- **{d.get('type', '?')}**: {d.get('description', '')}")


def _render_ad_card(ad: dict, run_key: str, org_id: str, user_id: str):
    """Render a single generated ad card with review data and override controls."""
    ad_id = ad.get("id", "")
    status = ad.get("final_status", "unknown")
    override_status = ad.get("override_status")
    scores = ad.get("review_check_scores")
    defect_result = ad.get("defect_scan_result")
    congruence = ad.get("congruence_score")
    storage_path = ad.get("storage_path")
    hook_text = ad.get("hook_text", "")

    # Header: index + status badge
    st.markdown(
        f"**#{ad.get('prompt_index', '?')}** "
        f"{_status_badge(status, override_status)} "
        f"{'— ' + hook_text[:60] + '...' if len(hook_text) > 60 else '— ' + hook_text if hook_text else ''}",
        unsafe_allow_html=True,
    )

    # Image + details side by side
    img_col, detail_col = st.columns([1, 2])

    with img_col:
        if storage_path:
            url = _get_signed_url(storage_path)
            if url:
                st.image(url, width=200)
            else:
                st.caption("Image unavailable")
        else:
            st.caption("No image")

    with detail_col:
        # Congruence score
        if congruence is not None:
            cong_color = "#2ecc71" if congruence >= 0.6 else "#f39c12" if congruence >= 0.4 else "#e74c3c"
            st.markdown(
                f'Congruence: <span style="color:{cong_color};font-weight:bold">{congruence:.3f}</span>',
                unsafe_allow_html=True,
            )

        # Defect scan
        _render_defect_result(defect_result)

        # Structured review scores
        if scores:
            with st.expander("Review Scores", expanded=False):
                _render_rubric_scores(scores)

    # Override controls
    if status not in ("generation_failed", "review_failed") and ad_id:
        override_key = f"override_{run_key}_{ad_id}"

        ocol1, ocol2, ocol3, ocol4 = st.columns([1, 1, 1, 2])
        with ocol1:
            if st.button("Override Approve", key=f"{override_key}_approve", type="primary"):
                _apply_override(ad_id, org_id, user_id, "override_approve", override_key)
        with ocol2:
            if st.button("Override Reject", key=f"{override_key}_reject"):
                _apply_override(ad_id, org_id, user_id, "override_reject", override_key)
        with ocol3:
            if st.button("Confirm", key=f"{override_key}_confirm"):
                _apply_override(ad_id, org_id, user_id, "confirm", override_key)
        with ocol4:
            st.text_input(
                "Reason (optional)",
                key=f"{override_key}_reason",
                label_visibility="collapsed",
                placeholder="Override reason...",
            )

        # Phase 8A: Mark as Exemplar button
        _render_exemplar_button(ad, run_key)


def _apply_override(ad_id: str, org_id: str, user_id: str, action: str, override_key: str):
    """Apply override via service and refresh."""
    reason = st.session_state.get(f"{override_key}_reason", "").strip() or None
    try:
        svc = _get_override_service()
        svc.create_override(
            generated_ad_id=ad_id,
            org_id=org_id,
            user_id=user_id,
            action=action,
            reason=reason,
        )
        st.success(f"Override applied: {action}")
        st.rerun()
    except Exception as e:
        st.error(f"Override failed: {e}")


def _render_exemplar_button(ad: dict, run_key: str):
    """Render Phase 8A 'Mark as Exemplar' dropdown for reviewed ads."""
    ad_id = ad.get("id", "")
    status = ad.get("final_status", "")

    # Only show for reviewed ads (not generation_failed/review_failed)
    if status in ("generation_failed", "review_failed") or not ad_id:
        return

    # Check if already an exemplar
    exemplar_key = f"exemplar_{run_key}_{ad_id}"

    ecol1, ecol2 = st.columns([2, 3])
    with ecol1:
        category = st.selectbox(
            "Exemplar Category",
            options=["gold_approve", "gold_reject", "edge_case"],
            key=f"{exemplar_key}_category",
            label_visibility="collapsed",
        )
    with ecol2:
        if st.button("Mark as Exemplar", key=f"{exemplar_key}_btn"):
            try:
                import asyncio
                from viraltracker.pipelines.ad_creation_v2.services.exemplar_service import ExemplarService
                from viraltracker.ui.auth import get_current_user_id
                from viraltracker.ui.utils import get_current_organization_id
                from uuid import UUID

                svc = ExemplarService()
                user_id = get_current_user_id()

                # Get brand_id: try session state first, then look up via ad_run → product → brand
                brand_id = ad.get("brand_id") or st.session_state.get("v2_brand_id")
                if not brand_id:
                    from viraltracker.core.database import get_supabase_client
                    db = get_supabase_client()
                    ad_run_id = ad.get("ad_run_id")
                    if ad_run_id:
                        run_result = db.table("ad_runs").select(
                            "product_id, products(brand_id)"
                        ).eq("id", ad_run_id).limit(1).execute()
                        if run_result.data:
                            products_data = run_result.data[0].get("products", {})
                            brand_id = products_data.get("brand_id") if products_data else None

                if not brand_id:
                    st.error("Could not determine brand for this ad.")
                    return

                loop = asyncio.new_event_loop()
                result = loop.run_until_complete(
                    svc.mark_as_exemplar(
                        brand_id=UUID(brand_id),
                        generated_ad_id=UUID(ad_id),
                        category=category,
                        created_by=UUID(user_id) if user_id else None,
                    )
                )
                loop.close()
                st.success(f"Marked as {category} exemplar")
            except Exception as e:
                st.error(f"Failed to mark as exemplar: {e}")


def render_results():
    """Render V2 job results view with dashboard, filters, and bulk actions."""
    from viraltracker.ui.auth import get_current_user_id
    from viraltracker.ui.utils import get_current_organization_id

    st.title("V2 Ad Creation Results")

    if st.button("Back to Create", key="v2_back_to_create"):
        st.session_state.v2_view = 'create'
        st.rerun()

    org_id = get_current_organization_id() or ""
    user_id = get_current_user_id() or ""

    if not org_id:
        st.warning("No organization context. Please log in.")
        return

    svc = _get_override_service()
    product_id = st.session_state.get("v2_product_id")

    # ── Summary Stats Bar ──
    _render_summary_stats(svc, org_id, product_id=product_id)

    st.divider()

    # ── Filter Controls ──
    filters = _render_filter_controls()

    st.divider()

    # ── Filtered Ad Results ──
    _render_filtered_ads(svc, org_id, user_id, filters)


def _render_summary_stats(svc, org_id: str, product_id: str = None):
    """Render aggregate stats bar at top of results view."""
    try:
        stats = svc.get_summary_stats(org_id, product_id=product_id)
        if stats["total"] == 0:
            st.info("No ads generated yet.")
            return

        cols = st.columns(6)
        with cols[0]:
            st.metric("Total Ads", stats["total"])
        with cols[1]:
            st.metric("Approved", stats["approved"])
        with cols[2]:
            st.metric("Rejected", stats["rejected"])
        with cols[3]:
            st.metric("Flagged", stats["flagged"])
        with cols[4]:
            st.metric("Review Failed", stats["review_failed"])
        with cols[5]:
            st.metric("Override Rate", f"{stats['override_rate']}%")

    except Exception as e:
        logger.warning(f"Could not load summary stats: {e}")


def _render_filter_controls() -> dict:
    """Render filter bar and return active filter dict."""
    with st.expander("Filters", expanded=False):
        fcol1, fcol2, fcol3 = st.columns(3)

        with fcol1:
            status_options = [
                "approved", "rejected", "flagged",
                "review_failed", "generation_failed",
            ]
            status_filter = st.multiselect(
                "Status",
                options=status_options,
                key="v2_results_status_filter",
            )

        with fcol2:
            from datetime import date, timedelta as td
            default_from = date.today() - td(days=7)
            date_from = st.date_input(
                "From", value=default_from, key="v2_results_date_from"
            )
            date_to = st.date_input(
                "To", value=date.today(), key="v2_results_date_to"
            )

        with fcol3:
            ad_run_id = st.text_input(
                "Ad Run ID", key="v2_results_ad_run_id",
                placeholder="Optional: paste ad_run UUID"
            )
            sort_by = st.selectbox(
                "Sort",
                options=["Newest First", "Oldest First"],
                key="v2_results_sort",
            )

    return {
        "status_filter": status_filter or None,
        "date_from": str(date_from) if date_from else None,
        "date_to": str(date_to) if date_to else None,
        "ad_run_id": ad_run_id.strip() or None,
        "sort_by": "oldest" if sort_by == "Oldest First" else "newest",
    }


def _render_filtered_ads(svc, org_id: str, user_id: str, filters: dict):
    """Render filtered ad list grouped by template with bulk actions."""
    # Pagination
    page_size = 20
    if "v2_results_offset" not in st.session_state:
        st.session_state.v2_results_offset = 0

    product_id = st.session_state.get("v2_product_id")

    try:
        ads = svc.get_ads_filtered(
            org_id,
            status_filter=filters["status_filter"],
            date_from=filters["date_from"],
            date_to=filters["date_to"],
            product_id=product_id,
            ad_run_id=filters["ad_run_id"],
            sort_by=filters["sort_by"],
            limit=page_size,
            offset=st.session_state.v2_results_offset,
        )
    except Exception as e:
        st.warning(f"Could not load ads: {e}")
        return

    if not ads:
        st.info("No ads match the current filters.")
        return

    # Group by template
    template_groups: dict = {}
    for ad in ads:
        run_data = ad.get("ad_runs") or {}
        tpl_id = run_data.get("source_scraped_template_id", "unknown")
        tpl_name = ad.get("template_name") or "Unknown Template"
        key = (tpl_id, tpl_name)
        template_groups.setdefault(key, []).append(ad)

    for (tpl_id, tpl_name), group_ads in template_groups.items():
        with st.expander(
            f"Template: {tpl_name} ({len(group_ads)} ads)",
            expanded=True,
        ):
            # Bulk actions for this template group
            bcol1, bcol2 = st.columns([1, 3])
            with bcol1:
                # Collect overrideable ad IDs
                overrideable_ids = [
                    a["id"] for a in group_ads
                    if a.get("final_status") not in ("generation_failed", "review_failed")
                    and a.get("id")
                ]
                if overrideable_ids:
                    ba_col1, ba_col2 = st.columns(2)
                    with ba_col1:
                        if st.button(
                            "Approve All",
                            key=f"bulk_approve_{tpl_id}",
                            type="primary",
                        ):
                            result = svc.bulk_override(
                                overrideable_ids, org_id, user_id,
                                "override_approve", reason="Bulk approve"
                            )
                            st.success(f"Approved {result['success']} ads")
                            st.rerun()
                    with ba_col2:
                        if st.button(
                            "Reject All",
                            key=f"bulk_reject_{tpl_id}",
                        ):
                            result = svc.bulk_override(
                                overrideable_ids, org_id, user_id,
                                "override_reject", reason="Bulk reject"
                            )
                            st.success(f"Rejected {result['success']} ads")
                            st.rerun()

            # Render individual ad cards
            for ad in group_ads:
                run_key = f"filtered_{tpl_id}_{ad.get('id', '')}"
                _render_ad_card(ad, run_key, org_id, user_id)
                st.divider()

    # Pagination controls
    pcol1, pcol2, pcol3 = st.columns([1, 1, 2])
    with pcol1:
        if st.session_state.v2_results_offset > 0:
            if st.button("Previous Page", key="v2_results_prev"):
                st.session_state.v2_results_offset = max(
                    0, st.session_state.v2_results_offset - page_size
                )
                st.rerun()
    with pcol2:
        if len(ads) == page_size:
            if st.button("Next Page", key="v2_results_next"):
                st.session_state.v2_results_offset += page_size
                st.rerun()
    with pcol3:
        page_num = (st.session_state.v2_results_offset // page_size) + 1
        st.caption(f"Page {page_num} ({len(ads)} ads shown)")


def render_results_legacy():
    """Legacy results view — renders V2 job runs (kept for backward compat)."""
    from viraltracker.ui.auth import get_current_user_id
    from viraltracker.ui.utils import get_current_organization_id

    org_id = get_current_organization_id() or ""
    user_id = get_current_user_id() or ""

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
            for run_idx, run in enumerate(runs):
                metadata = run.get('metadata') or {}
                run_status = run.get('status', 'unknown')
                run_key = f"job_{job['id']}_run_{run_idx}"

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

                # Phase 4: Show individual ad cards with review detail
                ad_run_ids = run.get('ad_run_ids') or []
                if ad_run_ids and run_status in ('completed', 'running'):
                    with st.expander("Ad Details", expanded=False):
                        try:
                            svc = _get_override_service()
                            for ad_run_id in ad_run_ids:
                                ads = svc.get_ads_for_run(ad_run_id)
                                for ad in ads:
                                    _render_ad_card(ad, run_key, org_id, user_id)
                                    st.divider()
                        except Exception as e:
                            st.warning(f"Could not load ad details: {e}")

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
