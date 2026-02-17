"""
Experiments — Structured A/B testing with Bayesian analysis.

Phase 7B: Three tabs:
1. Active Experiments — running/analyzing experiments with P(best) bars
2. Completed — concluded experiments with causal knowledge base
3. Create New — 6-step wizard for experiment creation
"""

import streamlit as st
import asyncio
from datetime import datetime
from uuid import UUID
from typing import Optional, List, Dict, Any

# Page config (must be first)
st.set_page_config(
    page_title="Experiments",
    page_icon="🧪",
    layout="wide"
)

# Auth
from viraltracker.ui.auth import require_auth
require_auth()
from viraltracker.ui.utils import require_feature
require_feature("experiments", "Experiments")

# ============================================
# SESSION STATE
# ============================================

def init_session_state():
    """Initialize all session state variables."""
    defaults = {
        # Wizard state
        "exp_wizard_step": 1,
        "exp_name": "",
        "exp_hypothesis": "",
        "exp_test_variable": None,
        "exp_product_id": None,
        "exp_arms": [],
        "exp_protocol": {},
        "exp_created_id": None,
        "exp_power_result": None,
        "exp_checklist": None,
        # Linking state
        "exp_campaign_id": "",
        "exp_campaign_name": "",
    }
    for key, val in defaults.items():
        if key not in st.session_state:
            st.session_state[key] = val

init_session_state()


# ============================================
# SERVICES
# ============================================

def get_supabase():
    """Get Supabase client."""
    from viraltracker.core.database import get_supabase_client
    return get_supabase_client()

def get_experiment_service():
    """Get ExperimentService instance."""
    from viraltracker.services.experiment_service import ExperimentService
    return ExperimentService()

def get_brands():
    """Fetch brands filtered by current organization."""
    from viraltracker.ui.utils import get_brands as get_org_brands
    return get_org_brands()

def get_products_for_brand(brand_id: str):
    """Fetch products for a brand."""
    db = get_supabase()
    result = db.table("products").select(
        "id, name, category"
    ).eq("brand_id", brand_id).order("name").execute()
    return result.data or []


# ============================================
# MAIN PAGE
# ============================================

st.title("🧪 Experiments")

# Brand selector
from viraltracker.ui.utils import render_brand_selector
brand_id = render_brand_selector(key="experiments_brand_selector")
if not brand_id:
    st.stop()

# Non-Meta guard
svc = get_experiment_service()
if not asyncio.run(svc.has_meta_account(UUID(brand_id))):
    st.warning(
        "Experiments require a Meta ad account connection. "
        "Link a Meta account in Brand Manager to use this feature."
    )
    st.stop()

# ============================================
# TABS
# ============================================

tab_active, tab_completed, tab_create = st.tabs([
    "📊 Active Experiments",
    "✅ Completed",
    "➕ Create New",
])


# ============================================
# TAB 1: ACTIVE EXPERIMENTS
# ============================================

with tab_active:
    render_active_experiments_needed = True

def render_active_experiments(brand_id: str):
    """Render active experiments with P(best) bars."""
    svc = get_experiment_service()

    running = asyncio.run(svc.list_experiments(UUID(brand_id), status="running"))
    analyzing = asyncio.run(svc.list_experiments(UUID(brand_id), status="analyzing"))
    deploying = asyncio.run(svc.list_experiments(UUID(brand_id), status="deploying"))
    active = running + analyzing + deploying

    if not active:
        st.info("No active experiments. Create one in the 'Create New' tab.")
        return

    for exp in active:
        exp_id = exp["id"]
        full_exp = asyncio.run(svc.get_experiment(UUID(exp_id)))
        arms = full_exp.get("arms", [])
        latest = full_exp.get("latest_analysis")
        protocol = full_exp.get("protocol") or {}

        with st.container(border=True):
            # Header
            cols = st.columns([3, 1, 1])
            with cols[0]:
                st.subheader(exp["name"])
                st.caption(exp.get("hypothesis", ""))
            with cols[1]:
                status_colors = {
                    "running": "🟢", "analyzing": "🟡", "deploying": "🔵"
                }
                st.markdown(f"{status_colors.get(exp['status'], '⚪')} **{exp['status'].upper()}**")
            with cols[2]:
                if latest:
                    grade = latest.get("quality_grade", "observational")
                    grade_colors = {"causal": "🟢", "quasi": "🟡", "observational": "⚪"}
                    st.markdown(f"{grade_colors.get(grade, '⚪')} {grade}")

            # P(best) bars
            if latest and latest.get("arm_results"):
                st.markdown("**P(best) per arm:**")
                arm_results = latest["arm_results"]
                for ar in arm_results:
                    p_best = ar.get("p_best", 0)
                    label = f"{ar.get('arm_name', 'Unknown')} ({ar.get('variable_value', '')})"
                    impressions = ar.get("impressions", 0)
                    ctr = ar.get("ctr", 0)
                    st.progress(min(p_best, 1.0), text=f"{label}: P(best)={p_best:.1%} | {impressions:,} impr | CTR={ctr:.4%}")

                # Decision
                decision = latest.get("decision", "unknown")
                days = latest.get("days_running", 0)
                st.markdown(f"**Decision:** {decision} | **Days running:** {days}")

            # Arm performance table
            if arms:
                st.markdown("**Arm Details:**")
                arm_data = []
                for arm in arms:
                    row = {
                        "Name": arm["name"],
                        "Variable Value": arm["variable_value"],
                        "Control": "Yes" if arm.get("is_control") else "",
                        "Ad Set ID": arm.get("meta_adset_id", "Not linked"),
                    }
                    # Add performance from latest analysis
                    if latest and latest.get("arm_results"):
                        matching = [ar for ar in latest["arm_results"] if ar.get("arm_id") == arm["id"]]
                        if matching:
                            m = matching[0]
                            row["Impressions"] = f"{m.get('impressions', 0):,}"
                            row["Clicks"] = m.get("clicks", 0)
                            row["CTR"] = f"{m.get('ctr', 0):.4%}"
                            row["P(best)"] = f"{m.get('p_best', 0):.1%}"
                    arm_data.append(row)
                st.dataframe(arm_data, use_container_width=True, hide_index=True)

            # Actions
            action_cols = st.columns(4)
            with action_cols[0]:
                if exp["status"] in ("running", "analyzing"):
                    if st.button("Analyze Now", key=f"analyze_{exp_id}"):
                        with st.spinner("Running analysis..."):
                            result = asyncio.run(svc.run_analysis(UUID(exp_id)))
                            st.success(f"Analysis complete: {result.get('decision', 'unknown')}")
                            st.rerun()

            with action_cols[1]:
                if exp["status"] == "analyzing" and latest and latest.get("decision") == "winner":
                    if st.button("Declare Winner", key=f"declare_{exp_id}"):
                        with st.spinner("Declaring winner..."):
                            result = asyncio.run(svc.declare_winner(UUID(exp_id)))
                            st.success(f"Winner: {result.get('winner_arm_name')} (P(best)={result.get('winner_p_best', 0):.1%})")
                            st.rerun()

            with action_cols[2]:
                if exp["status"] == "analyzing" and latest and latest.get("decision") in ("futility", "inconclusive"):
                    if st.button("Mark Inconclusive", key=f"inconclusive_{exp_id}"):
                        with st.spinner("Marking inconclusive..."):
                            asyncio.run(svc.mark_inconclusive(UUID(exp_id)))
                            st.success("Experiment marked as inconclusive")
                            st.rerun()

            with action_cols[3]:
                if exp["status"] not in ("concluded", "cancelled"):
                    if st.button("Cancel", key=f"cancel_{exp_id}"):
                        asyncio.run(svc.transition_status(UUID(exp_id), "cancelled"))
                        st.info("Experiment cancelled")
                        st.rerun()


with tab_active:
    render_active_experiments(brand_id)


# ============================================
# TAB 2: COMPLETED EXPERIMENTS
# ============================================

def render_completed_experiments(brand_id: str):
    """Render completed experiments and causal knowledge base."""
    svc = get_experiment_service()
    concluded = asyncio.run(svc.list_experiments(UUID(brand_id), status="concluded"))

    if concluded:
        st.subheader("Concluded Experiments")
        for exp in concluded:
            exp_id = exp["id"]
            full_exp = asyncio.run(svc.get_experiment(UUID(exp_id)))
            latest = full_exp.get("latest_analysis")

            with st.container(border=True):
                cols = st.columns([3, 1, 1])
                with cols[0]:
                    st.markdown(f"**{exp['name']}**")
                    st.caption(exp.get("hypothesis", ""))
                with cols[1]:
                    if latest:
                        decision = latest.get("decision", "unknown")
                        if decision == "winner":
                            winner_name = ""
                            for ar in (latest.get("arm_results") or []):
                                if ar.get("arm_id") == latest.get("winner_arm_id"):
                                    winner_name = ar.get("arm_name", "")
                            st.success(f"Winner: {winner_name}")
                        else:
                            st.warning(decision.capitalize())
                with cols[2]:
                    if latest:
                        grade = latest.get("quality_grade", "observational")
                        st.markdown(f"Grade: **{grade}**")

                if latest and latest.get("arm_results"):
                    for ar in latest["arm_results"]:
                        p_best = ar.get("p_best", 0)
                        label = f"{ar.get('arm_name', '')} ({ar.get('variable_value', '')})"
                        st.progress(min(p_best, 1.0), text=f"{label}: P(best)={p_best:.1%}")

    # Causal Knowledge Base
    st.subheader("Causal Knowledge Base")

    # Optional product filter
    products = get_products_for_brand(brand_id)
    product_filter = st.selectbox(
        "Filter by product",
        options=[None] + [p["id"] for p in products],
        format_func=lambda x: "All Products" if x is None else next(
            (p["name"] for p in products if p["id"] == x), x
        ),
        key="causal_kb_product_filter",
    )

    # Optional variable filter
    from viraltracker.services.creative_genome_service import TRACKED_ELEMENTS
    variable_filter = st.selectbox(
        "Filter by variable",
        options=[None] + list(TRACKED_ELEMENTS),
        format_func=lambda x: "All Variables" if x is None else x,
        key="causal_kb_variable_filter",
    )

    effects = asyncio.run(svc.get_causal_knowledge_base(
        UUID(brand_id),
        product_id=UUID(product_filter) if product_filter else None,
        test_variable=variable_filter,
    ))

    if effects:
        effect_rows = []
        for e in effects:
            effect_rows.append({
                "Variable": e.get("test_variable", ""),
                "Control": e.get("control_value", ""),
                "Treatment": e.get("treatment_value", ""),
                "ATE (rel.)": f"{(e.get('ate_relative') or 0):.1%}",
                "CI": f"[{(e.get('ci_lower') or 0):.6f}, {(e.get('ci_upper') or 0):.6f}]",
                "Grade": e.get("quality_grade", ""),
                "Impressions (ctrl/treat)": f"{e.get('control_impressions', 0):,} / {e.get('treatment_impressions', 0):,}",
            })
        st.dataframe(effect_rows, use_container_width=True, hide_index=True)
    else:
        st.info("No causal effects recorded yet. Complete experiments to build the knowledge base.")


with tab_completed:
    render_completed_experiments(brand_id)


# ============================================
# TAB 3: CREATE NEW EXPERIMENT (6-step wizard)
# ============================================

def render_create_wizard(brand_id: str):
    """Render 6-step experiment creation wizard."""
    svc = get_experiment_service()
    step = st.session_state.exp_wizard_step

    # Progress indicator
    steps = ["Hypothesis", "Arms", "Protocol", "Power Analysis", "Deploy Checklist", "Link Meta IDs"]
    progress_cols = st.columns(len(steps))
    for i, (col, name) in enumerate(zip(progress_cols, steps), 1):
        with col:
            if i < step:
                st.markdown(f"~~{i}. {name}~~")
            elif i == step:
                st.markdown(f"**{i}. {name}**")
            else:
                st.markdown(f"{i}. {name}")

    st.divider()

    # ---- Step 1: Hypothesis ----
    if step == 1:
        st.subheader("Step 1: Define Hypothesis")

        st.session_state.exp_name = st.text_input(
            "Experiment name",
            value=st.session_state.exp_name,
            placeholder="e.g., Hook Type A/B Test",
        )
        st.session_state.exp_hypothesis = st.text_area(
            "Hypothesis",
            value=st.session_state.exp_hypothesis,
            placeholder="e.g., Curiosity hooks will outperform fear hooks by 15%+ CTR",
        )

        from viraltracker.services.creative_genome_service import TRACKED_ELEMENTS
        variable_options = list(TRACKED_ELEMENTS)
        current_idx = variable_options.index(st.session_state.exp_test_variable) if st.session_state.exp_test_variable in variable_options else 0
        st.session_state.exp_test_variable = st.selectbox(
            "Test variable",
            options=variable_options,
            index=current_idx,
            help="The creative element to test across arms",
        )

        # Optional product
        products = get_products_for_brand(brand_id)
        product_options = [None] + [p["id"] for p in products]
        st.session_state.exp_product_id = st.selectbox(
            "Product (optional)",
            options=product_options,
            format_func=lambda x: "All Products" if x is None else next(
                (p["name"] for p in products if p["id"] == x), x
            ),
            key="exp_product_select",
        )

        if st.button("Next: Define Arms", disabled=not (st.session_state.exp_name and st.session_state.exp_hypothesis)):
            # Create the experiment
            try:
                exp = asyncio.run(svc.create_experiment(
                    brand_id=UUID(brand_id),
                    name=st.session_state.exp_name,
                    hypothesis=st.session_state.exp_hypothesis,
                    test_variable=st.session_state.exp_test_variable,
                    product_id=UUID(st.session_state.exp_product_id) if st.session_state.exp_product_id else None,
                ))
                st.session_state.exp_created_id = exp["id"]
                st.session_state.exp_wizard_step = 2
                st.rerun()
            except ValueError as e:
                st.error(str(e))

    # ---- Step 2: Arms ----
    elif step == 2:
        st.subheader("Step 2: Define Arms")
        exp_id = st.session_state.exp_created_id

        if not exp_id:
            st.error("No experiment created. Go back to step 1.")
            return

        # Show existing arms
        full_exp = asyncio.run(svc.get_experiment(UUID(exp_id)))
        arms = full_exp.get("arms", [])

        if arms:
            st.markdown("**Current Arms:**")
            for arm in arms:
                acol1, acol2, acol3 = st.columns([3, 1, 1])
                with acol1:
                    label = f"{'[Control] ' if arm.get('is_control') else ''}{arm['name']}: {arm['variable_value']}"
                    st.markdown(label)
                with acol3:
                    if st.button("Remove", key=f"remove_arm_{arm['id']}"):
                        asyncio.run(svc.remove_arm(UUID(arm["id"])))
                        st.rerun()

        # Add arm form
        if len(arms) < 4:
            st.markdown("---")
            st.markdown("**Add Arm:**")
            has_control = any(a.get("is_control") for a in arms)

            arm_name = st.text_input("Arm name", placeholder="e.g., Control, Treatment A")
            arm_value = st.text_input(
                f"Value of '{st.session_state.exp_test_variable}'",
                placeholder=f"e.g., curiosity, fear, social_proof",
            )
            arm_is_control = st.checkbox("This is the control arm", disabled=has_control and True)

            if st.button("Add Arm", disabled=not (arm_name and arm_value)):
                try:
                    asyncio.run(svc.add_arm(
                        experiment_id=UUID(exp_id),
                        name=arm_name,
                        variable_value=arm_value,
                        is_control=arm_is_control if not has_control else False,
                    ))
                    st.rerun()
                except ValueError as e:
                    st.error(str(e))

        nav_cols = st.columns(2)
        with nav_cols[0]:
            if st.button("Back"):
                st.session_state.exp_wizard_step = 1
                st.rerun()
        with nav_cols[1]:
            has_control = any(a.get("is_control") for a in arms)
            if st.button("Next: Protocol", disabled=len(arms) < 2 or not has_control):
                st.session_state.exp_wizard_step = 3
                st.rerun()

    # ---- Step 3: Protocol ----
    elif step == 3:
        st.subheader("Step 3: Experiment Protocol")
        exp_id = st.session_state.exp_created_id

        protocol = st.session_state.exp_protocol

        method_type = st.selectbox(
            "Method type",
            options=["strict_ab", "pragmatic_split", "observational"],
            index=["strict_ab", "pragmatic_split", "observational"].index(
                protocol.get("method_type", "pragmatic_split")
            ),
            help="strict_ab = causal grade, pragmatic_split = quasi, observational = lowest grade",
        )

        budget_strategy = st.selectbox(
            "Budget strategy",
            options=["equal", "weighted", "custom"],
            index=0,
        )

        randomization_unit = st.selectbox(
            "Randomization unit",
            options=["adset", "campaign", "user"],
            index=0,
        )

        audience_rules = st.text_input(
            "Audience rules",
            value=protocol.get("audience_rules", "Same audience for all ad sets"),
        )

        min_impressions = st.number_input(
            "Min impressions per arm",
            value=protocol.get("min_impressions_per_arm", 1000),
            min_value=100,
            step=100,
        )

        min_days = st.number_input(
            "Min days running",
            value=protocol.get("min_days_running", 7),
            min_value=1,
            max_value=90,
        )

        max_days = st.number_input(
            "Max days running",
            value=protocol.get("max_days_running", 14),
            min_value=min_days,
            max_value=90,
        )

        hold_constant = st.text_input(
            "Hold constant (comma-separated)",
            value=", ".join(protocol.get("hold_constant", [])),
            help="Elements that should NOT vary between arms",
        )

        notes = st.text_area(
            "Notes",
            value=protocol.get("notes", ""),
        )

        nav_cols = st.columns(2)
        with nav_cols[0]:
            if st.button("Back"):
                st.session_state.exp_wizard_step = 2
                st.rerun()
        with nav_cols[1]:
            if st.button("Next: Power Analysis"):
                updated_protocol = {
                    "method_type": method_type,
                    "budget_strategy": budget_strategy,
                    "randomization_unit": randomization_unit,
                    "audience_rules": audience_rules,
                    "min_impressions_per_arm": min_impressions,
                    "min_days_running": min_days,
                    "max_days_running": max_days,
                    "hold_constant": [x.strip() for x in hold_constant.split(",") if x.strip()],
                    "notes": notes,
                }
                st.session_state.exp_protocol = updated_protocol
                asyncio.run(svc.update_experiment(UUID(exp_id), {"protocol": updated_protocol}))
                st.session_state.exp_wizard_step = 4
                st.rerun()

    # ---- Step 4: Power Analysis ----
    elif step == 4:
        st.subheader("Step 4: Power Analysis")
        exp_id = st.session_state.exp_created_id

        st.markdown(
            "Compute the required sample size and budget per arm. "
            "This must pass before the experiment can be activated."
        )

        baseline_ctr = st.number_input(
            "Baseline CTR (leave 0 to use brand median)",
            value=0.0,
            min_value=0.0,
            max_value=1.0,
            step=0.001,
            format="%.4f",
        )

        min_detectable_effect = st.slider(
            "Minimum detectable effect (relative lift)",
            min_value=0.05,
            max_value=0.50,
            value=0.20,
            step=0.05,
            format="%.0f%%",
            help="e.g., 0.20 = detect a 20% relative lift in CTR",
        )

        power_val = st.slider(
            "Statistical power",
            min_value=0.70,
            max_value=0.95,
            value=0.80,
            step=0.05,
        )

        if st.button("Run Power Analysis"):
            with st.spinner("Computing..."):
                try:
                    result = asyncio.run(svc.compute_required_sample_size(
                        experiment_id=UUID(exp_id),
                        baseline_rate=baseline_ctr if baseline_ctr > 0 else None,
                        min_detectable_effect=min_detectable_effect,
                        power=power_val,
                    ))
                    st.session_state.exp_power_result = result
                    st.rerun()
                except ValueError as e:
                    st.error(str(e))

        # Show results
        if st.session_state.exp_power_result:
            result = st.session_state.exp_power_result
            st.success("Power analysis complete!")

            mcols = st.columns(3)
            with mcols[0]:
                st.metric("Required impressions/arm", f"{result['required_impressions_per_arm']:,}")
            with mcols[1]:
                budget = result.get("required_daily_budget_per_arm")
                st.metric("Est. daily budget/arm", f"${budget:.2f}" if budget else "Unknown")
            with mcols[2]:
                st.metric("Estimated days", result.get("estimated_days", "?"))

            st.info(
                f"Baseline CTR: {result.get('baseline_ctr', 0):.4%} | "
                f"Detectable effect: {result.get('detectable_effect', 0):.0%} | "
                f"Arms: {result.get('num_arms', 0)}"
            )

        nav_cols = st.columns(2)
        with nav_cols[0]:
            if st.button("Back"):
                st.session_state.exp_wizard_step = 3
                st.rerun()
        with nav_cols[1]:
            if st.button("Next: Deployment Checklist", disabled=not st.session_state.exp_power_result):
                st.session_state.exp_wizard_step = 5
                st.rerun()

    # ---- Step 5: Deployment Checklist ----
    elif step == 5:
        st.subheader("Step 5: Meta Deployment Checklist")
        exp_id = st.session_state.exp_created_id

        checklist = asyncio.run(svc.get_deployment_checklist(UUID(exp_id)))
        st.session_state.exp_checklist = checklist

        st.markdown(f"**Experiment:** {checklist['experiment_name']}")
        st.markdown(f"**Hypothesis:** {checklist['hypothesis']}")
        st.markdown(f"**Test Variable:** {checklist['test_variable']}")

        budget_info = checklist.get("budget", {})
        if budget_info.get("per_arm_daily"):
            st.info(
                f"Budget: ${budget_info['per_arm_daily']}/arm/day "
                f"(${budget_info.get('total_daily', 0)}/day total) "
                f"for ~{budget_info.get('estimated_days', '?')} days"
            )

        for step_item in checklist.get("steps", []):
            with st.expander(f"Step {step_item['step']}: {step_item['title']}", expanded=True):
                st.markdown(step_item["description"])
                if "arms" in step_item:
                    for arm in step_item["arms"]:
                        prefix = "[Control] " if arm.get("is_control") else ""
                        st.markdown(f"- {prefix}**{arm['name']}**: {arm['variable_value']}")

        # Mark as ready then deploying
        nav_cols = st.columns(2)
        with nav_cols[0]:
            if st.button("Back"):
                st.session_state.exp_wizard_step = 4
                st.rerun()
        with nav_cols[1]:
            if st.button("I've deployed — Link IDs"):
                try:
                    asyncio.run(svc.transition_status(UUID(exp_id), "ready"))
                    asyncio.run(svc.transition_status(UUID(exp_id), "deploying"))
                    st.session_state.exp_wizard_step = 6
                    st.rerun()
                except ValueError as e:
                    st.error(str(e))

    # ---- Step 6: Link Meta IDs ----
    elif step == 6:
        st.subheader("Step 6: Link Meta Campaign & Ad Set IDs")
        exp_id = st.session_state.exp_created_id

        full_exp = asyncio.run(svc.get_experiment(UUID(exp_id)))
        arms = full_exp.get("arms", [])

        # Campaign ID
        campaign_id = st.text_input(
            "Meta Campaign ID",
            value=st.session_state.exp_campaign_id,
            placeholder="e.g., 23851234567890",
        )
        campaign_name = st.text_input(
            "Campaign Name (optional)",
            value=st.session_state.exp_campaign_name,
        )

        if campaign_id and campaign_id != full_exp.get("meta_campaign_id"):
            if st.button("Link Campaign"):
                try:
                    asyncio.run(svc.link_campaign_to_experiment(
                        UUID(exp_id), campaign_id, campaign_name or None
                    ))
                    st.session_state.exp_campaign_id = campaign_id
                    st.success("Campaign linked!")
                    st.rerun()
                except ValueError as e:
                    st.error(str(e))

        # Per-arm ad set IDs
        st.markdown("---")
        st.markdown("**Link ad set IDs for each arm:**")

        all_linked = True
        for arm in arms:
            with st.container(border=True):
                prefix = "[Control] " if arm.get("is_control") else ""
                st.markdown(f"**{prefix}{arm['name']}**: {arm['variable_value']}")

                if arm.get("meta_adset_id"):
                    st.success(f"Linked: {arm['meta_adset_id']}")
                else:
                    all_linked = False
                    adset_id = st.text_input(
                        "Ad Set ID",
                        key=f"adset_{arm['id']}",
                        placeholder="e.g., 23851234567891",
                    )
                    ad_id = st.text_input(
                        "Ad ID (optional)",
                        key=f"ad_id_{arm['id']}",
                    )
                    if adset_id:
                        if st.button("Link", key=f"link_{arm['id']}"):
                            try:
                                asyncio.run(svc.link_arm_to_meta(
                                    UUID(arm["id"]),
                                    meta_adset_id=adset_id,
                                    meta_ad_id=ad_id or None,
                                ))
                                st.success(f"Linked {arm['name']} to ad set {adset_id}")
                                st.rerun()
                            except ValueError as e:
                                st.error(str(e))

        # Activate
        st.markdown("---")
        if all_linked and full_exp.get("meta_campaign_id"):
            if st.button("Validate & Activate Experiment", type="primary"):
                try:
                    asyncio.run(svc.transition_status(UUID(exp_id), "running"))
                    st.success("Experiment is now RUNNING! View it in the Active tab.")
                    # Reset wizard
                    st.session_state.exp_wizard_step = 1
                    st.session_state.exp_created_id = None
                    st.session_state.exp_power_result = None
                    st.session_state.exp_name = ""
                    st.session_state.exp_hypothesis = ""
                    st.session_state.exp_campaign_id = ""
                    st.session_state.exp_campaign_name = ""
                    st.rerun()
                except ValueError as e:
                    st.error(str(e))
        elif not all_linked:
            st.warning("Link all arm ad set IDs before activating.")
        elif not full_exp.get("meta_campaign_id"):
            st.warning("Link the campaign ID first.")

        if st.button("Back"):
            st.session_state.exp_wizard_step = 5
            st.rerun()


with tab_create:
    render_create_wizard(brand_id)
