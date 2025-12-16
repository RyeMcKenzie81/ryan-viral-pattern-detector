"""
Plan List - View and manage belief-first ad plans.

This page shows all created plans and allows users to:
- View plan details
- See plan status
- Delete plans
"""

import streamlit as st
from datetime import datetime
from uuid import UUID

st.set_page_config(
    page_title="Plan List",
    page_icon="📊",
    layout="wide"
)

# ============================================
# SERVICE INITIALIZATION
# ============================================

def get_planning_service():
    """Get PlanningService instance."""
    from viraltracker.services.planning_service import PlanningService
    return PlanningService()

def get_supabase_client():
    """Get Supabase client."""
    from viraltracker.core.database import get_supabase_client
    return get_supabase_client()


# ============================================
# SESSION STATE
# ============================================

if 'plan_list_filter' not in st.session_state:
    st.session_state.plan_list_filter = "all"
if 'selected_plan_id' not in st.session_state:
    st.session_state.selected_plan_id = None
if 'confirm_delete' not in st.session_state:
    st.session_state.confirm_delete = None


# ============================================
# DATA FETCHING
# ============================================

@st.cache_data(ttl=30)
def fetch_plans():
    """Fetch all plans with related data."""
    db = get_supabase_client()
    try:
        result = db.table("belief_plans").select(
            "*, brands(name), products(name), personas_4d(name), belief_jtbd_framed(name)"
        ).order("created_at", desc=True).execute()
        return result.data or []
    except Exception as e:
        st.error(f"Failed to fetch plans: {e}")
        return []


def get_plan_angle_count(plan_id: str) -> int:
    """Get count of angles for a plan."""
    db = get_supabase_client()
    try:
        result = db.table("belief_plan_angles").select("angle_id", count="exact").eq("plan_id", plan_id).execute()
        return result.count or 0
    except Exception:
        return 0


def get_plan_template_count(plan_id: str) -> int:
    """Get count of templates for a plan."""
    db = get_supabase_client()
    try:
        result = db.table("belief_plan_templates").select("template_id", count="exact").eq("plan_id", plan_id).execute()
        return result.count or 0
    except Exception:
        return 0


def delete_plan(plan_id: str) -> bool:
    """Delete a plan and its associations."""
    db = get_supabase_client()
    try:
        # Delete plan (cascades to angles and templates)
        db.table("belief_plans").delete().eq("id", plan_id).execute()
        return True
    except Exception as e:
        st.error(f"Failed to delete plan: {e}")
        return False


# ============================================
# UI COMPONENTS
# ============================================

def render_plan_card(plan: dict):
    """Render a single plan card."""
    plan_id = plan.get("id")
    name = plan.get("name", "Unnamed Plan")
    status = plan.get("status", "draft")
    created_at = plan.get("created_at", "")

    # Get related names
    brand_name = plan.get("brands", {}).get("name", "Unknown") if plan.get("brands") else "Unknown"
    product_name = plan.get("products", {}).get("name", "Unknown") if plan.get("products") else "Unknown"
    persona_name = plan.get("personas_4d", {}).get("name", "Unknown") if plan.get("personas_4d") else "Unknown"
    jtbd_name = plan.get("belief_jtbd_framed", {}).get("name", "Unknown") if plan.get("belief_jtbd_framed") else "Unknown"

    # Get counts
    angle_count = get_plan_angle_count(plan_id)
    template_count = get_plan_template_count(plan_id)
    ads_per_angle = plan.get("ads_per_angle", 3)
    total_ads = angle_count * ads_per_angle

    # Status badge color
    status_colors = {
        "draft": "gray",
        "ready": "blue",
        "running": "orange",
        "completed": "green"
    }

    # Format date
    try:
        dt = datetime.fromisoformat(created_at.replace("Z", "+00:00"))
        date_str = dt.strftime("%Y-%m-%d %H:%M")
    except Exception:
        date_str = created_at[:19] if created_at else "Unknown"

    # Card layout
    with st.container():
        col1, col2, col3 = st.columns([3, 2, 1])

        with col1:
            st.markdown(f"### {name}")
            st.caption(f"Created: {date_str}")
            st.write(f"**Brand:** {brand_name} | **Product:** {product_name}")
            st.write(f"**Persona:** {persona_name}")
            st.write(f"**JTBD:** {jtbd_name[:50]}..." if len(jtbd_name) > 50 else f"**JTBD:** {jtbd_name}")

        with col2:
            st.markdown("**Testing Config**")
            st.write(f"Phase: {plan.get('phase_id', 1)} | Strategy: {plan.get('template_strategy', 'fixed')}")
            st.write(f"Angles: {angle_count} | Templates: {template_count}")
            st.write(f"Ads per Angle: {ads_per_angle}")
            st.write(f"**Total Ads: {total_ads}**")

        with col3:
            # Status badge
            st.markdown(f"**Status:** :{status_colors.get(status, 'gray')}[{status.upper()}]")

            # View details button
            if st.button("View Details", key=f"view_{plan_id}"):
                st.session_state.selected_plan_id = plan_id

            # Delete button
            if st.session_state.confirm_delete == plan_id:
                st.warning("Confirm delete?")
                col_yes, col_no = st.columns(2)
                with col_yes:
                    if st.button("Yes", key=f"confirm_yes_{plan_id}"):
                        if delete_plan(plan_id):
                            st.session_state.confirm_delete = None
                            st.cache_data.clear()
                            st.rerun()
                with col_no:
                    if st.button("No", key=f"confirm_no_{plan_id}"):
                        st.session_state.confirm_delete = None
                        st.rerun()
            else:
                if st.button("Delete", key=f"delete_{plan_id}"):
                    st.session_state.confirm_delete = plan_id
                    st.rerun()

        st.divider()


def render_plan_details(plan_id: str):
    """Render detailed view of a plan."""
    service = get_planning_service()
    db = get_supabase_client()

    # Fetch plan
    result = db.table("belief_plans").select(
        "*, brands(name), products(name), personas_4d(name, snapshot), belief_jtbd_framed(name, progress_statement)"
    ).eq("id", plan_id).execute()

    if not result.data:
        st.error("Plan not found")
        return

    plan = result.data[0]

    # Back button
    if st.button("← Back to List"):
        st.session_state.selected_plan_id = None
        st.rerun()

    st.header(plan.get("name", "Plan Details"))

    # Plan info
    col1, col2 = st.columns(2)
    with col1:
        st.subheader("Plan Info")
        st.write(f"**ID:** `{plan_id}`")
        st.write(f"**Status:** {plan.get('status', 'draft')}")
        st.write(f"**Phase:** {plan.get('phase_id', 1)}")
        st.write(f"**Template Strategy:** {plan.get('template_strategy', 'fixed')}")
        st.write(f"**Ads per Angle:** {plan.get('ads_per_angle', 3)}")

    with col2:
        st.subheader("Context")
        brand = plan.get("brands", {})
        product = plan.get("products", {})
        persona = plan.get("personas_4d", {})
        jtbd = plan.get("belief_jtbd_framed", {})

        st.write(f"**Brand:** {brand.get('name', 'Unknown') if brand else 'Unknown'}")
        st.write(f"**Product:** {product.get('name', 'Unknown') if product else 'Unknown'}")
        st.write(f"**Persona:** {persona.get('name', 'Unknown') if persona else 'Unknown'}")
        st.write(f"**JTBD:** {jtbd.get('name', 'Unknown') if jtbd else 'Unknown'}")
        if jtbd and jtbd.get('progress_statement'):
            st.caption(f"*{jtbd['progress_statement']}*")

    # Angles
    st.subheader("Angles")
    angles_result = db.table("belief_plan_angles").select(
        "display_order, belief_angles(id, name, belief_statement, status)"
    ).eq("plan_id", plan_id).order("display_order").execute()

    if angles_result.data:
        for row in angles_result.data:
            angle = row.get("belief_angles", {})
            if angle:
                with st.expander(f"{angle.get('name', 'Unnamed Angle')} ({angle.get('status', 'untested')})"):
                    st.write(f"**Belief:** {angle.get('belief_statement', 'No statement')}")
    else:
        st.info("No angles linked to this plan")

    # Templates
    st.subheader("Templates")
    templates_result = db.table("belief_plan_templates").select(
        "display_order, template_id, template_source"
    ).eq("plan_id", plan_id).order("display_order").execute()

    if templates_result.data:
        for row in templates_result.data:
            template_id = row.get("template_id")
            source = row.get("template_source", "ad_brief_templates")

            # Fetch template name from appropriate table
            if source == "scraped_templates":
                t_result = db.table("scraped_templates").select("name").eq("id", template_id).execute()
            else:
                t_result = db.table("ad_brief_templates").select("name").eq("id", template_id).execute()

            template_name = t_result.data[0].get("name", "Unknown") if t_result.data else "Unknown"
            st.write(f"• {template_name} ({source})")
    else:
        st.info("No templates linked to this plan")


# ============================================
# MAIN PAGE
# ============================================

st.title("📊 Plan List")
st.write("View and manage your belief-first ad testing plans.")

# Check if viewing a specific plan
if st.session_state.selected_plan_id:
    render_plan_details(st.session_state.selected_plan_id)
else:
    # Filter options
    col1, col2 = st.columns([1, 3])
    with col1:
        filter_options = ["all", "draft", "ready", "running", "completed"]
        st.session_state.plan_list_filter = st.selectbox(
            "Filter by Status",
            options=filter_options,
            index=filter_options.index(st.session_state.plan_list_filter)
        )
    with col2:
        if st.button("Refresh"):
            st.cache_data.clear()
            st.rerun()

    # Fetch and display plans
    plans = fetch_plans()

    # Apply filter
    if st.session_state.plan_list_filter != "all":
        plans = [p for p in plans if p.get("status") == st.session_state.plan_list_filter]

    if plans:
        st.write(f"**{len(plans)} plan(s) found**")
        st.divider()
        for plan in plans:
            render_plan_card(plan)
    else:
        st.info("No plans found. Create a new plan using the Ad Planning page.")
        if st.button("Go to Ad Planning"):
            st.switch_page("pages/32_📋_Ad_Planning.py")
