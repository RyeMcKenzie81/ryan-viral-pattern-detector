"""
Plan Executor - Execute Phase 1-2 belief testing plans.

This page allows users to:
- Select a belief plan to execute
- Configure generation settings (variations per angle)
- Launch the execution pipeline
- Monitor progress and view results
"""

import asyncio
import streamlit as st
from datetime import datetime
from uuid import UUID

st.set_page_config(
    page_title="Plan Executor",
    page_icon="🎯",
    layout="wide"
)

# ============================================
# SERVICE INITIALIZATION
# ============================================

def get_supabase_client():
    """Get Supabase client."""
    from viraltracker.core.database import get_supabase_client
    return get_supabase_client()


def get_ad_creation_service():
    """Get AdCreationService instance."""
    from viraltracker.services.ad_creation_service import AdCreationService
    return AdCreationService()


# ============================================
# SESSION STATE
# ============================================

if 'executor_selected_product' not in st.session_state:
    st.session_state.executor_selected_product = None
if 'executor_selected_plan' not in st.session_state:
    st.session_state.executor_selected_plan = None
if 'executor_running' not in st.session_state:
    st.session_state.executor_running = False
if 'executor_current_run_id' not in st.session_state:
    st.session_state.executor_current_run_id = None
if 'executor_last_result' not in st.session_state:
    st.session_state.executor_last_result = None


# ============================================
# DATA FETCHING
# ============================================

@st.cache_data(ttl=30)
def fetch_brands():
    """Fetch all brands."""
    db = get_supabase_client()
    try:
        result = db.table("brands").select("id, name").order("name").execute()
        return result.data or []
    except Exception as e:
        st.error(f"Failed to fetch brands: {e}")
        return []


@st.cache_data(ttl=30)
def fetch_products_for_brand(brand_id: str):
    """Fetch products for a brand."""
    db = get_supabase_client()
    try:
        result = db.table("products").select("id, name").eq("brand_id", brand_id).order("name").execute()
        return result.data or []
    except Exception as e:
        st.error(f"Failed to fetch products: {e}")
        return []


@st.cache_data(ttl=30)
def fetch_plans_for_product(product_id: str):
    """Fetch Phase 1-2 belief plans for a product."""
    db = get_supabase_client()
    try:
        result = db.table("belief_plans").select(
            "id, name, phase_id, status, created_at"
        ).eq("product_id", product_id).in_("phase_id", [1, 2]).order("created_at", desc=True).execute()
        return result.data or []
    except Exception as e:
        st.error(f"Failed to fetch plans: {e}")
        return []


def get_plan_details(plan_id: str):
    """Get full plan details including angles and templates."""
    db = get_supabase_client()
    try:
        # Get plan
        plan_result = db.table("belief_plans").select(
            "*, brands(name), products(name), personas_4d(name, snapshot), belief_jtbd_framed(name, progress_statement)"
        ).eq("id", plan_id).execute()

        if not plan_result.data:
            return None

        plan = plan_result.data[0]

        # Get angles
        angles_result = db.table("belief_plan_angles").select(
            "display_order, belief_angles(id, name, belief_statement)"
        ).eq("plan_id", plan_id).order("display_order").execute()

        angles = []
        for row in angles_result.data or []:
            angle = row.get("belief_angles")
            if angle:
                angles.append(angle)

        # Get templates
        templates_result = db.table("belief_plan_templates").select(
            "display_order, template_id"
        ).eq("plan_id", plan_id).order("display_order").execute()

        templates = []
        for row in templates_result.data or []:
            template_id = row.get("template_id")
            # Try scraped_templates first
            t_result = db.table("scraped_templates").select(
                "id, name, storage_path, layout_analysis"
            ).eq("id", template_id).execute()

            if t_result.data:
                templates.append(t_result.data[0])
            else:
                # Try ad_brief_templates
                t_result = db.table("ad_brief_templates").select(
                    "id, name"
                ).eq("id", template_id).execute()
                if t_result.data:
                    templates.append(t_result.data[0])

        return {
            "plan": plan,
            "angles": angles,
            "templates": templates
        }
    except Exception as e:
        st.error(f"Failed to fetch plan details: {e}")
        return None


def get_pipeline_runs(plan_id: str):
    """Get execution runs for a plan."""
    db = get_supabase_client()
    try:
        result = db.table("pipeline_runs").select("*").eq(
            "pipeline_name", "belief_plan_execution"
        ).eq("belief_plan_id", plan_id).order("started_at", desc=True).execute()
        return result.data or []
    except Exception as e:
        st.error(f"Failed to fetch runs: {e}")
        return []


# ============================================
# EXECUTION
# ============================================

async def execute_plan(plan_id: str, variations: int, canvas_size: str):
    """Execute the belief plan pipeline."""
    from viraltracker.pipelines.belief_plan_execution import run_belief_plan_execution

    result = await run_belief_plan_execution(
        belief_plan_id=UUID(plan_id),
        variations_per_angle=variations,
        canvas_size=canvas_size
    )
    return result


def run_execution(plan_id: str, variations: int, canvas_size: str):
    """Wrapper to run async execution."""
    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)
    try:
        result = loop.run_until_complete(execute_plan(plan_id, variations, canvas_size))
        return result
    finally:
        loop.close()


def get_latest_run(plan_id: str):
    """Get the most recent pipeline run for a plan."""
    db = get_supabase_client()
    try:
        result = db.table("pipeline_runs").select("*").eq(
            "pipeline_name", "belief_plan_execution"
        ).eq("belief_plan_id", plan_id).order("started_at", desc=True).limit(1).execute()
        return result.data[0] if result.data else None
    except Exception:
        return None


def get_public_url(storage_path: str) -> str:
    """Get public URL for a storage path."""
    db = get_supabase_client()
    try:
        # Parse bucket and path from storage_path
        if storage_path.startswith("generated-ads/"):
            bucket = "generated-ads"
            path = storage_path.replace("generated-ads/", "")
        elif "/" in storage_path:
            parts = storage_path.split("/", 1)
            bucket = parts[0]
            path = parts[1]
        else:
            bucket = "generated-ads"
            path = storage_path

        result = db.storage.from_(bucket).get_public_url(path)
        return result
    except Exception:
        return ""


# ============================================
# UI COMPONENTS
# ============================================

def render_plan_summary(details: dict):
    """Render a summary of the selected plan."""
    plan = details["plan"]
    angles = details["angles"]
    templates = details["templates"]

    col1, col2 = st.columns(2)

    with col1:
        st.subheader("Plan Info")
        st.write(f"**Name:** {plan.get('name', 'Unnamed')}")
        st.write(f"**Phase:** {plan.get('phase_id', 1)}")
        st.write(f"**Status:** {plan.get('status', 'draft')}")

        brand = plan.get("brands", {})
        product = plan.get("products", {})
        st.write(f"**Brand:** {brand.get('name', 'Unknown') if brand else 'Unknown'}")
        st.write(f"**Product:** {product.get('name', 'Unknown') if product else 'Unknown'}")

    with col2:
        st.subheader("Context")
        persona = plan.get("personas_4d", {})
        jtbd = plan.get("belief_jtbd_framed", {})

        if persona:
            st.write(f"**Persona:** {persona.get('name', 'Unknown')}")
            if persona.get("snapshot"):
                st.caption(f"*{persona['snapshot'][:100]}...*" if len(persona.get('snapshot', '')) > 100 else f"*{persona.get('snapshot', '')}*")

        if jtbd:
            st.write(f"**JTBD:** {jtbd.get('name', 'Unknown')}")
            if jtbd.get("progress_statement"):
                st.caption(f"*{jtbd['progress_statement'][:100]}...*" if len(jtbd.get('progress_statement', '')) > 100 else f"*{jtbd.get('progress_statement', '')}*")

    st.divider()

    col1, col2 = st.columns(2)

    with col1:
        st.subheader(f"Angles ({len(angles)})")
        for angle in angles:
            with st.expander(angle.get("name", "Unnamed Angle")):
                st.write(f"**Belief:** {angle.get('belief_statement', 'No statement')}")

    with col2:
        st.subheader(f"Templates ({len(templates)})")
        for tmpl in templates:
            layout = tmpl.get("layout_analysis", {}) or {}
            anchor = layout.get("anchor_text", "None")
            st.write(f"- **{tmpl.get('name', 'Unknown')}**")
            st.caption(f"  Anchor text: \"{anchor}\"")


def render_execution_form(plan_id: str, num_angles: int, num_templates: int):
    """Render the execution configuration form."""
    st.subheader("Execution Settings")

    col1, col2, col3 = st.columns(3)

    with col1:
        variations = st.slider(
            "Variations per Angle×Template",
            min_value=1,
            max_value=5,
            value=3,
            help="How many variations to generate for each angle-template combination"
        )

    with col2:
        canvas_size = st.selectbox(
            "Canvas Size",
            options=["1080x1080px", "1080x1350px", "1200x628px"],
            index=0,
            help="Output image dimensions"
        )

    with col3:
        total_ads = num_angles * num_templates * variations
        st.metric("Total Ads to Generate", total_ads)

    st.info(f"**Generation Math:** {num_angles} angles × {num_templates} templates × {variations} variations = **{total_ads} ads**")

    col1, col2 = st.columns(2)
    with col1:
        if st.button("Execute Plan", type="primary", use_container_width=True):
            st.session_state.executor_running = True
            st.session_state.executor_last_result = None
            with st.spinner(f"Generating {total_ads} ads... This may take a while."):
                try:
                    result = run_execution(plan_id, variations, canvas_size)
                    st.session_state.executor_running = False
                    st.session_state.executor_last_result = result

                    if result.get("status") == "complete":
                        st.success(f"Execution complete! Generated {result.get('total_generated', 0)} ads.")
                        st.write(f"- Approved: {result.get('approved', 0)}")
                        st.write(f"- Rejected: {result.get('rejected', 0)}")
                        if result.get("ad_run_id"):
                            st.write(f"- Ad Run ID: `{result['ad_run_id']}`")
                        st.cache_data.clear()
                        st.rerun()
                    else:
                        st.error(f"Execution failed: {result.get('error', 'Unknown error')}")

                except Exception as e:
                    st.session_state.executor_running = False
                    st.error(f"Execution error: {e}")

    with col2:
        if st.session_state.executor_last_result:
            if st.button("Clear Results", use_container_width=True):
                st.session_state.executor_last_result = None
                st.rerun()

    # Show results if available
    if st.session_state.executor_last_result and st.session_state.executor_last_result.get("status") == "complete":
        st.divider()
        render_results_by_angle(st.session_state.executor_last_result)


def render_run_history(plan_id: str):
    """Render history of execution runs for this plan."""
    runs = get_pipeline_runs(plan_id)

    if not runs:
        st.info("No execution runs yet for this plan.")
        return

    st.subheader(f"Execution History ({len(runs)} runs)")

    for run in runs:
        status = run.get("status", "unknown")
        started = run.get("started_at", "")
        snapshot = run.get("state_snapshot", {}) or {}

        # Format date
        try:
            dt = datetime.fromisoformat(started.replace("Z", "+00:00"))
            date_str = dt.strftime("%Y-%m-%d %H:%M")
        except Exception:
            date_str = started[:19] if started else "Unknown"

        # Status color
        status_colors = {
            "running": "orange",
            "complete": "green",
            "failed": "red",
            "paused": "gray"
        }

        with st.expander(f"{date_str} - :{status_colors.get(status, 'gray')}[{status.upper()}]"):
            col1, col2, col3 = st.columns(3)
            with col1:
                st.write(f"**Step:** {snapshot.get('current_step', 'unknown')}")
            with col2:
                st.write(f"**Generated:** {snapshot.get('ads_generated', 0)}/{snapshot.get('total_ads_planned', 0)}")
            with col3:
                st.write(f"**Approved:** {snapshot.get('approved_count', 0)}")

            if run.get("error_message"):
                st.error(f"Error: {run['error_message']}")


def render_results_by_angle(result: dict):
    """Render generated ads grouped by angle with their copy scaffolds."""
    ads_by_angle = result.get("ads_by_angle", {})

    if not ads_by_angle:
        st.info("No results to display.")
        return

    st.subheader("Generated Ads by Angle")
    st.write("Review ads organized by the belief angle they test. Copy scaffolds shown for each ad.")

    for angle_id, angle_data in ads_by_angle.items():
        angle_name = angle_data.get("angle_name", "Unknown Angle")
        belief = angle_data.get("belief_statement", "")
        approved = angle_data.get("approved", 0)
        rejected = angle_data.get("rejected", 0)
        failed = angle_data.get("failed", 0)
        total = len(angle_data.get("ads", []))

        # Status indicator
        if approved == total and total > 0:
            status_emoji = "✅"
        elif approved > 0:
            status_emoji = "🟡"
        else:
            status_emoji = "❌"

        with st.expander(f"{status_emoji} **{angle_name}** - {approved}/{total} approved"):
            if belief:
                st.caption(f"*Testing belief: {belief}*")

            # Stats row
            col1, col2, col3 = st.columns(3)
            with col1:
                st.metric("Approved", approved)
            with col2:
                st.metric("Rejected", rejected)
            with col3:
                st.metric("Failed", failed)

            st.divider()

            # Display ads in a grid
            ads = angle_data.get("ads", [])
            if not ads:
                st.info("No ads generated for this angle.")
                continue

            # Group by 3 columns
            cols = st.columns(3)
            for i, ad in enumerate(ads):
                with cols[i % 3]:
                    storage_path = ad.get("storage_path")
                    if storage_path:
                        image_url = get_public_url(storage_path)
                        if image_url:
                            st.image(image_url, use_container_width=True)
                        else:
                            st.warning("Image not available")
                    else:
                        st.warning("No image")

                    # Status badge
                    status = ad.get("final_status", "pending")
                    if status == "approved":
                        st.success("Approved")
                    elif status == "rejected":
                        st.error("Rejected")
                    elif ad.get("error"):
                        st.error(f"Failed: {ad.get('error', '')[:50]}")
                    else:
                        st.info("Pending")

                    # Template info
                    st.caption(f"Template: {ad.get('template_name', 'Unknown')}")

                    # Copy scaffolds (shown directly - no nested expander)
                    headline = ad.get("meta_headline", "")
                    primary = ad.get("meta_primary_text", "")

                    if headline or primary:
                        st.markdown("**Meta Copy:**")
                        if headline:
                            st.text_area(
                                "Headline",
                                value=headline,
                                height=60,
                                key=f"headline_{ad.get('ad_id', i)}_{angle_id}",
                                disabled=True
                            )
                        if primary:
                            st.text_area(
                                "Primary",
                                value=primary,
                                height=80,
                                key=f"primary_{ad.get('ad_id', i)}_{angle_id}",
                                disabled=True
                            )


# ============================================
# MAIN PAGE
# ============================================

st.title("🎯 Plan Executor")
st.write("Execute Phase 1-2 belief testing plans to generate ads.")

# Brand selector (uses shared utility for cross-page persistence)
from viraltracker.ui.utils import render_brand_selector
selected_brand_id = render_brand_selector(key="executor_brand_selector")

if selected_brand_id:

    # Product selector
    products = fetch_products_for_brand(selected_brand_id)
    product_options = {p["id"]: p["name"] for p in products}

    selected_product_id = st.selectbox(
        "Select Product",
        options=[""] + list(product_options.keys()),
        format_func=lambda x: product_options.get(x, "Select a product...") if x else "Select a product...",
        key="executor_product_select"
    )

    if selected_product_id:
        st.session_state.executor_selected_product = selected_product_id

        # Plan selector
        plans = fetch_plans_for_product(selected_product_id)

        if not plans:
            st.warning("No Phase 1-2 plans found for this product. Create a plan in the Ad Planning page first.")
        else:
            plan_options = {p["id"]: f"{p['name']} (Phase {p['phase_id']})" for p in plans}

            selected_plan_id = st.selectbox(
                "Select Belief Plan",
                options=[""] + list(plan_options.keys()),
                format_func=lambda x: plan_options.get(x, "Select a plan...") if x else "Select a plan...",
                key="executor_plan_select"
            )

            if selected_plan_id:
                st.session_state.executor_selected_plan = selected_plan_id
                st.divider()

                # Load plan details
                details = get_plan_details(selected_plan_id)

                if details:
                    # Plan summary
                    render_plan_summary(details)

                    st.divider()

                    # Check if plan has angles and templates
                    if not details["angles"]:
                        st.error("This plan has no angles. Add angles in the Ad Planning page.")
                    elif not details["templates"]:
                        st.error("This plan has no templates. Add templates in the Ad Planning page.")
                    else:
                        # Execution form
                        render_execution_form(
                            selected_plan_id,
                            len(details["angles"]),
                            len(details["templates"])
                        )

                    st.divider()

                    # Run history
                    render_run_history(selected_plan_id)
                else:
                    st.error("Could not load plan details.")
