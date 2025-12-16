"""
Belief-First Ad Planning - Create test plans for discovering winning beliefs.

This page implements an 8-step wizard:
1. Select Brand
2. Select Product
3. Define/Select Offer (optional)
4. Select/Create Persona
5. Define/Select JTBD
6. Define Angles (5-7)
7. Select Templates
8. Review & Compile

Uses direct service calls (not pydantic-graph) because:
- User-driven wizard flow
- Interactive with user review at each step
"""

import streamlit as st
import asyncio
import json
from datetime import datetime
from uuid import UUID
from typing import Optional, List, Dict, Any

# Page config
st.set_page_config(
    page_title="Ad Planning",
    page_icon="📋",
    layout="wide"
)

# Authentication
from viraltracker.ui.auth import require_auth
require_auth()


# ============================================
# SESSION STATE INITIALIZATION
# ============================================

def init_session_state():
    """Initialize all session state variables."""
    defaults = {
        # Wizard navigation
        "planning_step": 1,

        # Step 1: Brand
        "selected_brand_id": None,

        # Step 2: Product
        "selected_product_id": None,
        "selected_product": None,

        # Step 3: Offer
        "selected_offer_id": None,
        "new_offer_name": "",
        "new_offer_description": "",
        "new_offer_drivers": "",
        "offer_suggestions": [],

        # Step 4: Persona
        "selected_persona_id": None,
        "selected_persona": None,

        # Step 5: JTBD
        "selected_jtbd_id": None,
        "new_jtbd_name": "",
        "new_jtbd_progress": "",
        "new_jtbd_description": "",
        "jtbd_suggestions": [],
        "extracted_jtbds": [],

        # Step 6: Angles
        "angles": [],  # List of {name, belief_statement, explanation}
        "new_angle_name": "",
        "new_angle_belief": "",
        "new_angle_explanation": "",
        "angle_suggestions": [],

        # Step 7: Templates
        "selected_template_ids": [],
        "template_strategy": "fixed",
        "ads_per_angle": 3,

        # Step 8: Review
        "plan_name": "",
        "compilation_result": None,
        "validation_warnings": [],

        # AI generation state
        "generating": False,
    }

    for key, default in defaults.items():
        if key not in st.session_state:
            st.session_state[key] = default


init_session_state()


# ============================================
# SERVICE HELPERS
# ============================================

def get_planning_service():
    """Get PlanningService instance (fresh for each call)."""
    from viraltracker.services.planning_service import PlanningService
    return PlanningService()


def get_supabase_client():
    """Get Supabase client."""
    from viraltracker.core.database import get_supabase_client
    return get_supabase_client()


# ============================================
# WIZARD NAVIGATION
# ============================================

def render_progress_bar():
    """Render wizard progress indicator."""
    steps = [
        "Brand", "Product", "Offer", "Persona",
        "JTBD", "Angles", "Templates", "Review"
    ]
    current = st.session_state.planning_step

    cols = st.columns(len(steps))
    for i, (col, step_name) in enumerate(zip(cols, steps), 1):
        with col:
            if i < current:
                st.markdown(f"**:white_check_mark: {step_name}**")
            elif i == current:
                st.markdown(f"**:arrow_right: {step_name}**")
            else:
                st.markdown(f":grey[{step_name}]")


def can_proceed_to_step(step: int) -> bool:
    """Check if we can proceed to a given step."""
    if step == 2:
        return st.session_state.selected_brand_id is not None
    elif step == 3:
        return st.session_state.selected_product_id is not None
    elif step == 4:
        return True  # Offer is optional
    elif step == 5:
        return st.session_state.selected_persona_id is not None
    elif step == 6:
        return st.session_state.selected_jtbd_id is not None
    elif step == 7:
        return len(st.session_state.angles) >= 1
    elif step == 8:
        return len(st.session_state.selected_template_ids) >= 1
    return True


def next_step():
    """Go to next wizard step."""
    if can_proceed_to_step(st.session_state.planning_step + 1):
        st.session_state.planning_step += 1
        st.rerun()


def prev_step():
    """Go to previous wizard step."""
    if st.session_state.planning_step > 1:
        st.session_state.planning_step -= 1
        st.rerun()


# ============================================
# STEP 1: SELECT BRAND
# ============================================

def render_step_1_brand():
    """Step 1: Select Brand."""
    st.header("Step 1: Select Brand")
    st.write("Choose the brand for this ad test plan.")

    service = get_planning_service()
    brands = service.get_brands()

    if not brands:
        st.warning("No brands found. Please create a brand first.")
        return

    # Brand dropdown
    brand_options = {b["name"]: b["id"] for b in brands}
    selected_name = st.selectbox(
        "Brand",
        options=["Select a brand..."] + list(brand_options.keys()),
        key="brand_selector"
    )

    if selected_name and selected_name != "Select a brand...":
        st.session_state.selected_brand_id = brand_options[selected_name]
        st.success(f"Selected: **{selected_name}**")

    # Navigation
    st.divider()
    col1, col2 = st.columns([1, 1])
    with col2:
        if st.button("Next: Select Product →", disabled=not can_proceed_to_step(2)):
            next_step()


# ============================================
# STEP 2: SELECT PRODUCT
# ============================================

def render_step_2_product():
    """Step 2: Select Product."""
    st.header("Step 2: Select Product")
    st.write("Choose the product to test.")

    if not st.session_state.selected_brand_id:
        st.warning("Please select a brand first.")
        return

    service = get_planning_service()
    products = service.get_products_for_brand(UUID(st.session_state.selected_brand_id))

    if not products:
        st.warning("No products found for this brand.")
        return

    # Product dropdown
    product_options = {p["name"]: p for p in products}
    selected_name = st.selectbox(
        "Product",
        options=["Select a product..."] + list(product_options.keys()),
        key="product_selector"
    )

    if selected_name and selected_name != "Select a product...":
        product = product_options[selected_name]
        st.session_state.selected_product_id = product["id"]
        st.session_state.selected_product = product

        # Show product details
        with st.expander("Product Details", expanded=True):
            if product.get("target_audience"):
                st.write(f"**Target Audience:** {product['target_audience']}")
            if product.get("benefits"):
                st.write(f"**Benefits:** {', '.join(product['benefits'][:5])}")
            if product.get("current_offer"):
                st.write(f"**Current Offer:** {product['current_offer']}")

    # Navigation
    st.divider()
    col1, col2 = st.columns([1, 1])
    with col1:
        if st.button("← Back to Brand"):
            prev_step()
    with col2:
        if st.button("Next: Define Offer →", disabled=not can_proceed_to_step(3)):
            next_step()


# ============================================
# STEP 3: DEFINE OFFER (OPTIONAL)
# ============================================

def render_step_3_offer():
    """Step 3: Define/Select Offer (Optional)."""
    st.header("Step 3: Define Offer (Optional)")
    st.write("Create or select an offer. This step is optional.")

    if not st.session_state.selected_product_id:
        st.warning("Please select a product first.")
        return

    service = get_planning_service()
    product_id = UUID(st.session_state.selected_product_id)

    # Existing offers
    offers = service.get_offers_for_product(product_id)

    tab1, tab2, tab3 = st.tabs(["Select Existing", "Create New", "AI Suggestions"])

    with tab1:
        if offers:
            offer_options = {"None (skip offer)": None}
            offer_options.update({o.name: str(o.id) for o in offers})

            selected = st.radio(
                "Existing Offers",
                options=list(offer_options.keys()),
                key="offer_radio"
            )
            st.session_state.selected_offer_id = offer_options.get(selected)
        else:
            st.info("No existing offers. Create one or skip this step.")

    with tab2:
        st.subheader("Create New Offer")
        st.session_state.new_offer_name = st.text_input(
            "Offer Name",
            value=st.session_state.new_offer_name,
            placeholder="e.g., Holiday Bundle Special"
        )
        st.session_state.new_offer_description = st.text_area(
            "Description",
            value=st.session_state.new_offer_description,
            placeholder="Describe the offer..."
        )
        st.session_state.new_offer_drivers = st.text_input(
            "Urgency Drivers (comma-separated)",
            value=st.session_state.new_offer_drivers,
            placeholder="e.g., limited time, bonus gift, free shipping"
        )

        if st.button("Create Offer", key="create_offer_btn"):
            if st.session_state.new_offer_name:
                drivers = [d.strip() for d in st.session_state.new_offer_drivers.split(",") if d.strip()]
                offer = service.create_offer(
                    product_id=product_id,
                    name=st.session_state.new_offer_name,
                    description=st.session_state.new_offer_description,
                    urgency_drivers=drivers
                )
                st.session_state.selected_offer_id = str(offer.id)
                st.success(f"Created offer: {offer.name}")
                st.rerun()

    with tab3:
        st.subheader("AI Offer Suggestions")
        if st.button("Generate Suggestions", key="suggest_offers_btn"):
            st.session_state.generating = True

        if st.session_state.generating and not st.session_state.offer_suggestions:
            with st.spinner("Generating offer suggestions..."):
                suggestions = asyncio.run(service.suggest_offers(product_id))
                st.session_state.offer_suggestions = suggestions
                st.session_state.generating = False
                st.rerun()

        for i, sug in enumerate(st.session_state.offer_suggestions):
            with st.container():
                st.markdown(f"**{sug.get('name', 'Suggestion')}**")
                st.write(sug.get('description', ''))
                if sug.get('urgency_drivers'):
                    st.write(f"Drivers: {', '.join(sug['urgency_drivers'])}")
                if st.button(f"Use This Offer", key=f"use_offer_{i}"):
                    st.session_state.new_offer_name = sug.get('name', '')
                    st.session_state.new_offer_description = sug.get('description', '')
                    st.session_state.new_offer_drivers = ', '.join(sug.get('urgency_drivers', []))
                    st.rerun()
                st.divider()

    # Navigation
    st.divider()
    col1, col2 = st.columns([1, 1])
    with col1:
        if st.button("← Back to Product"):
            prev_step()
    with col2:
        if st.button("Next: Select Persona →"):
            next_step()


# ============================================
# STEP 4: SELECT PERSONA
# ============================================

def render_step_4_persona():
    """Step 4: Select/Create Persona."""
    st.header("Step 4: Select Persona")
    st.write("Choose a persona linked to this product.")

    if not st.session_state.selected_product_id:
        st.warning("Please select a product first.")
        return

    service = get_planning_service()
    personas = service.get_personas_for_product(UUID(st.session_state.selected_product_id))

    if not personas:
        st.warning("No personas linked to this product. Please create one in the Personas page first.")
        return

    # Persona cards
    for persona in personas:
        with st.container():
            col1, col2 = st.columns([3, 1])
            with col1:
                primary_badge = " (Primary)" if persona.get("is_primary") else ""
                st.markdown(f"**{persona['name']}**{primary_badge}")
                if persona.get("snapshot"):
                    st.write(persona["snapshot"][:200] + "..." if len(persona.get("snapshot", "")) > 200 else persona.get("snapshot", ""))
            with col2:
                selected = st.session_state.selected_persona_id == persona["id"]
                if st.button(
                    "Selected" if selected else "Select",
                    key=f"select_persona_{persona['id']}",
                    disabled=selected
                ):
                    st.session_state.selected_persona_id = persona["id"]
                    st.session_state.selected_persona = persona
                    st.rerun()
            st.divider()

    # Navigation
    st.divider()
    col1, col2 = st.columns([1, 1])
    with col1:
        if st.button("← Back to Offer"):
            prev_step()
    with col2:
        if st.button("Next: Define JTBD →", disabled=not can_proceed_to_step(5)):
            next_step()


# ============================================
# STEP 5: DEFINE JTBD
# ============================================

def render_step_5_jtbd():
    """Step 5: Define/Select JTBD."""
    st.header("Step 5: Define Job-to-be-Done")
    st.write("Define the persona-framed JTBD this product fulfills.")

    if not st.session_state.selected_persona_id or not st.session_state.selected_product_id:
        st.warning("Please select a persona first.")
        return

    service = get_planning_service()
    persona_id = UUID(st.session_state.selected_persona_id)
    product_id = UUID(st.session_state.selected_product_id)

    # Get existing JTBDs
    existing_jtbds = service.get_jtbd_for_persona_product(persona_id, product_id)

    # Extract JTBDs from persona
    if not st.session_state.extracted_jtbds:
        st.session_state.extracted_jtbds = service.extract_jtbd_from_persona(persona_id)

    tab1, tab2, tab3 = st.tabs(["Select Existing", "Create New", "AI Suggestions"])

    with tab1:
        if existing_jtbds:
            for jtbd in existing_jtbds:
                with st.container():
                    st.markdown(f"**{jtbd.name}**")
                    if jtbd.progress_statement:
                        st.write(f"*{jtbd.progress_statement}*")
                    selected = st.session_state.selected_jtbd_id == str(jtbd.id)
                    if st.button("Selected" if selected else "Select", key=f"select_jtbd_{jtbd.id}", disabled=selected):
                        st.session_state.selected_jtbd_id = str(jtbd.id)
                        st.rerun()
                    st.divider()
        else:
            st.info("No JTBDs created yet. Create one or use AI suggestions.")

        # Show extracted JTBDs from persona
        if st.session_state.extracted_jtbds:
            st.subheader("JTBDs from Persona Data")
            for i, jtbd in enumerate(st.session_state.extracted_jtbds[:5]):
                jtbd_text = jtbd if isinstance(jtbd, str) else str(jtbd)
                st.write(f"• {jtbd_text}")

    with tab2:
        st.subheader("Create New JTBD")
        st.session_state.new_jtbd_name = st.text_input(
            "JTBD Name",
            value=st.session_state.new_jtbd_name,
            placeholder="e.g., Slow decline without medication"
        )
        st.session_state.new_jtbd_progress = st.text_area(
            "Progress Statement",
            value=st.session_state.new_jtbd_progress,
            placeholder="When I [situation], I want to [motivation], so I can [outcome]..."
        )
        st.session_state.new_jtbd_description = st.text_area(
            "Description",
            value=st.session_state.new_jtbd_description,
            placeholder="Detailed description..."
        )

        if st.button("Create JTBD", key="create_jtbd_btn"):
            if st.session_state.new_jtbd_name:
                jtbd = service.create_jtbd_framed(
                    persona_id=persona_id,
                    product_id=product_id,
                    name=st.session_state.new_jtbd_name,
                    progress_statement=st.session_state.new_jtbd_progress,
                    description=st.session_state.new_jtbd_description,
                    source="manual"
                )
                st.session_state.selected_jtbd_id = str(jtbd.id)
                st.success(f"Created JTBD: {jtbd.name}")
                st.rerun()

    with tab3:
        st.subheader("AI JTBD Suggestions")
        if st.button("Generate Suggestions", key="suggest_jtbd_btn"):
            with st.spinner("Generating JTBD suggestions..."):
                suggestions = asyncio.run(service.suggest_jtbd(persona_id, product_id))
                st.session_state.jtbd_suggestions = suggestions
                st.rerun()

        for i, sug in enumerate(st.session_state.jtbd_suggestions):
            with st.container():
                st.markdown(f"**{sug.get('name', 'Suggestion')}**")
                st.write(f"*{sug.get('progress_statement', '')}*")
                if st.button(f"Use This JTBD", key=f"use_jtbd_{i}"):
                    st.session_state.new_jtbd_name = sug.get('name', '')
                    st.session_state.new_jtbd_progress = sug.get('progress_statement', '')
                    st.session_state.new_jtbd_description = sug.get('description', '')
                    st.rerun()
                st.divider()

    # Navigation
    st.divider()
    col1, col2 = st.columns([1, 1])
    with col1:
        if st.button("← Back to Persona"):
            prev_step()
    with col2:
        if st.button("Next: Define Angles →", disabled=not can_proceed_to_step(6)):
            next_step()


# ============================================
# STEP 6: DEFINE ANGLES
# ============================================

def render_step_6_angles():
    """Step 6: Define Angles (5-7)."""
    st.header("Step 6: Define Angles (5-7)")
    st.write("Create 5-7 angles to test. Each angle is a belief/explanation for why the job exists and why your solution works.")

    if not st.session_state.selected_jtbd_id:
        st.warning("Please select a JTBD first.")
        return

    service = get_planning_service()
    jtbd_id = UUID(st.session_state.selected_jtbd_id)

    # Current angles
    st.subheader(f"Current Angles ({len(st.session_state.angles)})")

    if st.session_state.angles:
        for i, angle in enumerate(st.session_state.angles):
            with st.container():
                col1, col2 = st.columns([4, 1])
                with col1:
                    st.markdown(f"**{i+1}. {angle['name']}**")
                    st.write(angle['belief_statement'])
                with col2:
                    if st.button("Remove", key=f"remove_angle_{i}"):
                        st.session_state.angles.pop(i)
                        st.rerun()
                st.divider()
    else:
        st.info("No angles added yet. Create or generate some below.")

    # Show warning if count is off
    angle_count = len(st.session_state.angles)
    if angle_count > 0 and (angle_count < 5 or angle_count > 7):
        st.warning(f"Phase 1 recommends 5-7 angles. You have {angle_count}.")

    # Add angle form
    tab1, tab2 = st.tabs(["Create Manually", "AI Suggestions"])

    with tab1:
        st.subheader("Add New Angle")
        st.session_state.new_angle_name = st.text_input(
            "Angle Name",
            value=st.session_state.new_angle_name,
            placeholder="e.g., The Inflammation Angle"
        )
        st.session_state.new_angle_belief = st.text_area(
            "Belief Statement",
            value=st.session_state.new_angle_belief,
            placeholder="The core belief this angle represents..."
        )
        st.session_state.new_angle_explanation = st.text_area(
            "Explanation",
            value=st.session_state.new_angle_explanation,
            placeholder="Why this angle might resonate..."
        )

        if st.button("Add Angle", key="add_angle_btn"):
            if st.session_state.new_angle_name and st.session_state.new_angle_belief:
                st.session_state.angles.append({
                    "name": st.session_state.new_angle_name,
                    "belief_statement": st.session_state.new_angle_belief,
                    "explanation": st.session_state.new_angle_explanation
                })
                # Clear form
                st.session_state.new_angle_name = ""
                st.session_state.new_angle_belief = ""
                st.session_state.new_angle_explanation = ""
                st.rerun()

    with tab2:
        st.subheader("AI Angle Suggestions")
        col1, col2 = st.columns([1, 1])
        with col1:
            count = st.number_input("Number of angles to suggest", min_value=3, max_value=10, value=5)
        with col2:
            if st.button("Generate Suggestions", key="suggest_angles_btn"):
                with st.spinner("Generating angle suggestions..."):
                    suggestions = asyncio.run(service.suggest_angles(jtbd_id, count=count))
                    st.session_state.angle_suggestions = suggestions
                    st.rerun()

        for i, sug in enumerate(st.session_state.angle_suggestions):
            with st.container():
                st.markdown(f"**{sug.get('name', 'Suggestion')}**")
                st.write(sug.get('belief_statement', ''))
                st.caption(sug.get('explanation', ''))
                if st.button(f"Add This Angle", key=f"add_suggested_angle_{i}"):
                    st.session_state.angles.append({
                        "name": sug.get('name', ''),
                        "belief_statement": sug.get('belief_statement', ''),
                        "explanation": sug.get('explanation', '')
                    })
                    st.rerun()
                st.divider()

    # Navigation
    st.divider()
    col1, col2 = st.columns([1, 1])
    with col1:
        if st.button("← Back to JTBD"):
            prev_step()
    with col2:
        if st.button("Next: Select Templates →", disabled=not can_proceed_to_step(7)):
            next_step()


# ============================================
# STEP 7: SELECT TEMPLATES
# ============================================

def render_step_7_templates():
    """Step 7: Select Templates."""
    st.header("Step 7: Select Templates")
    st.write("Choose templates for ad generation.")

    if not st.session_state.selected_brand_id:
        st.warning("Please select a brand first.")
        return

    service = get_planning_service()
    templates = service.get_templates_for_brand(UUID(st.session_state.selected_brand_id))

    if not templates:
        st.warning("No templates found. Please create templates first.")
        return

    # Template selection
    st.subheader("Available Templates")
    for template in templates:
        col1, col2 = st.columns([4, 1])
        with col1:
            st.markdown(f"**{template.get('name', 'Unnamed')}**")
            if template.get('instructions'):
                st.caption(template['instructions'][:100] + "..." if len(template.get('instructions', '')) > 100 else template.get('instructions', ''))
        with col2:
            template_id = template.get('id')
            is_selected = template_id in st.session_state.selected_template_ids
            if st.checkbox("Select", value=is_selected, key=f"template_{template_id}"):
                if template_id not in st.session_state.selected_template_ids:
                    st.session_state.selected_template_ids.append(template_id)
            else:
                if template_id in st.session_state.selected_template_ids:
                    st.session_state.selected_template_ids.remove(template_id)
        st.divider()

    # Template settings
    st.subheader("Template Settings")
    col1, col2 = st.columns([1, 1])
    with col1:
        st.session_state.template_strategy = st.radio(
            "Template Strategy",
            options=["fixed", "random"],
            index=0 if st.session_state.template_strategy == "fixed" else 1,
            help="Fixed: same templates for all angles. Random: random template per ad."
        )
    with col2:
        st.session_state.ads_per_angle = st.number_input(
            "Ads per Angle",
            min_value=1,
            max_value=10,
            value=st.session_state.ads_per_angle
        )

    st.info(f"Selected {len(st.session_state.selected_template_ids)} template(s)")

    # Navigation
    st.divider()
    col1, col2 = st.columns([1, 1])
    with col1:
        if st.button("← Back to Angles"):
            prev_step()
    with col2:
        if st.button("Next: Review & Compile →", disabled=not can_proceed_to_step(8)):
            next_step()


# ============================================
# STEP 8: REVIEW & COMPILE
# ============================================

def render_step_8_review():
    """Step 8: Review & Compile."""
    st.header("Step 8: Review & Compile")
    st.write("Review your plan and compile for the ad creator.")

    service = get_planning_service()

    # Plan name
    st.session_state.plan_name = st.text_input(
        "Plan Name",
        value=st.session_state.plan_name or f"Plan_{datetime.now().strftime('%Y%m%d_%H%M')}",
        placeholder="Enter a name for this plan"
    )

    # Summary
    st.subheader("Plan Summary")

    col1, col2 = st.columns(2)

    with col1:
        st.markdown("**Brand & Product**")
        if st.session_state.selected_product:
            st.write(f"Product: {st.session_state.selected_product.get('name', 'N/A')}")
        if st.session_state.selected_offer_id:
            st.write(f"Offer: Selected")
        else:
            st.write("Offer: None")

        st.markdown("**Persona**")
        if st.session_state.selected_persona:
            st.write(f"Persona: {st.session_state.selected_persona.get('name', 'N/A')}")

    with col2:
        st.markdown("**Testing Config**")
        st.write(f"Phase: 1 (Discovery)")
        st.write(f"Angles: {len(st.session_state.angles)}")
        st.write(f"Templates: {len(st.session_state.selected_template_ids)}")
        st.write(f"Template Strategy: {st.session_state.template_strategy}")
        st.write(f"Ads per Angle: {st.session_state.ads_per_angle}")
        total_ads = len(st.session_state.angles) * st.session_state.ads_per_angle
        st.write(f"**Total Ads to Generate: {total_ads}**")

    # Angles summary
    st.subheader("Angles")
    for i, angle in enumerate(st.session_state.angles, 1):
        st.write(f"{i}. **{angle['name']}**: {angle['belief_statement'][:100]}...")

    # Validation warnings
    if st.session_state.validation_warnings:
        st.subheader("Warnings")
        for warning in st.session_state.validation_warnings:
            st.warning(warning)

    # Validate button
    if st.button("Validate Plan"):
        warnings = []
        if len(st.session_state.angles) < 5:
            warnings.append(f"Phase 1 recommends 5-7 angles. You have {len(st.session_state.angles)}.")
        if len(st.session_state.angles) > 7:
            warnings.append(f"Phase 1 recommends 5-7 angles. You have {len(st.session_state.angles)}.")
        st.session_state.validation_warnings = warnings
        if not warnings:
            st.success("Plan is valid!")
        st.rerun()

    # Compile button
    st.divider()
    if st.button("Compile & Save Plan", type="primary"):
        try:
            with st.spinner("Creating plan..."):
                # First create the angles in the database
                jtbd_id = UUID(st.session_state.selected_jtbd_id)
                created_angle_ids = []
                for angle_data in st.session_state.angles:
                    angle = service.create_angle(
                        jtbd_framed_id=jtbd_id,
                        name=angle_data["name"],
                        belief_statement=angle_data["belief_statement"],
                        explanation=angle_data.get("explanation")
                    )
                    created_angle_ids.append(angle.id)

                # Create the plan
                plan = service.create_plan(
                    name=st.session_state.plan_name,
                    brand_id=UUID(st.session_state.selected_brand_id),
                    product_id=UUID(st.session_state.selected_product_id),
                    persona_id=UUID(st.session_state.selected_persona_id),
                    jtbd_framed_id=jtbd_id,
                    angle_ids=created_angle_ids,
                    template_ids=[UUID(t) for t in st.session_state.selected_template_ids],
                    offer_id=UUID(st.session_state.selected_offer_id) if st.session_state.selected_offer_id else None,
                    phase_id=1,
                    template_strategy=st.session_state.template_strategy,
                    ads_per_angle=st.session_state.ads_per_angle
                )

                # Compile the plan
                compiled = service.compile_plan(plan.id)
                st.session_state.compilation_result = compiled

                st.success(f"Plan created and compiled! Plan ID: {plan.id}")

                # Show compiled payload
                with st.expander("Compiled Payload (JSON)", expanded=False):
                    st.json(compiled.model_dump(mode="json"))

        except Exception as e:
            st.error(f"Failed to create plan: {e}")

    # Navigation
    st.divider()
    col1, col2 = st.columns([1, 1])
    with col1:
        if st.button("← Back to Templates"):
            prev_step()
    with col2:
        if st.session_state.compilation_result:
            if st.button("Start New Plan"):
                # Reset all state
                for key in list(st.session_state.keys()):
                    if key.startswith("planning_") or key.startswith("selected_") or key.startswith("new_"):
                        del st.session_state[key]
                st.session_state.planning_step = 1
                st.rerun()


# ============================================
# MAIN PAGE
# ============================================

def main():
    """Main page render."""
    st.title("📋 Belief-First Ad Planning")
    st.write("Create test plans for discovering winning belief sequences.")

    # Progress bar
    render_progress_bar()
    st.divider()

    # Render current step
    step = st.session_state.planning_step

    if step == 1:
        render_step_1_brand()
    elif step == 2:
        render_step_2_product()
    elif step == 3:
        render_step_3_offer()
    elif step == 4:
        render_step_4_persona()
    elif step == 5:
        render_step_5_jtbd()
    elif step == 6:
        render_step_6_angles()
    elif step == 7:
        render_step_7_templates()
    elif step == 8:
        render_step_8_review()


if __name__ == "__main__":
    main()
