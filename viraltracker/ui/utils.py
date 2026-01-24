"""Shared UI utilities for Streamlit pages."""

import streamlit as st
from typing import Optional, Tuple


# ============================================================================
# ORGANIZATION UTILITIES
# ============================================================================

def get_current_organization_id() -> Optional[str]:
    """
    Get current organization ID from session state.

    Returns:
        Organization ID string or None if not set.
        Returns "all" for superuser mode (see all organizations).
    """
    return st.session_state.get("current_organization_id")


def set_current_organization_id(org_id: str) -> None:
    """
    Set current organization ID in session state.

    Args:
        org_id: Organization ID to set, or "all" for superuser mode
    """
    st.session_state["current_organization_id"] = org_id


def is_superuser(user_id: str) -> bool:
    """
    Check if user is a superuser.

    Superusers can see data from all organizations.

    Args:
        user_id: User ID to check

    Returns:
        True if user is a superuser, False otherwise
    """
    from viraltracker.core.database import get_supabase_client

    try:
        result = get_supabase_client().table("user_profiles").select(
            "is_superuser"
        ).eq("user_id", user_id).single().execute()
        return result.data.get("is_superuser", False) if result.data else False
    except Exception:
        return False


def render_organization_selector(key: str = "org_selector") -> Optional[str]:
    """
    Render organization selector in sidebar.

    Auto-selects if user has only one organization. Shows dropdown if multiple.
    Superusers get an "All Organizations" option to see all data.

    Args:
        key: Unique key for the selectbox widget

    Returns:
        Selected organization ID, "all" for superuser mode, or None if not authenticated
    """
    from viraltracker.ui.auth import get_current_user_id
    from viraltracker.services.organization_service import OrganizationService
    from viraltracker.core.database import get_supabase_client

    user_id = get_current_user_id()
    if not user_id:
        return None

    service = OrganizationService(get_supabase_client())
    orgs = service.get_user_organizations(user_id)

    if not orgs:
        st.sidebar.warning("No organizations found")
        return None

    # Build options dict
    org_options = {o["organization"]["name"]: o["organization"]["id"] for o in orgs}

    # Superusers get "All Organizations" option
    user_is_superuser = is_superuser(user_id)
    if user_is_superuser:
        org_options = {"All Organizations": "all", **org_options}

    # Single org (non-superuser) - auto-select
    if len(org_options) == 1:
        org_id = list(org_options.values())[0]
        set_current_organization_id(org_id)
        return org_id

    # Multiple orgs or superuser - show selector
    # Get current selection or default to first
    current_org_id = get_current_organization_id()
    current_name = next(
        (name for name, oid in org_options.items() if oid == current_org_id),
        list(org_options.keys())[0]
    )

    selected_name = st.sidebar.selectbox(
        "Workspace",
        list(org_options.keys()),
        index=list(org_options.keys()).index(current_name),
        key=key
    )

    selected_id = org_options[selected_name]
    set_current_organization_id(selected_id)
    return selected_id


# ============================================================================
# FEATURE ACCESS UTILITIES
# ============================================================================

def has_feature(feature_key: str, organization_id: Optional[str] = None) -> bool:
    """
    Check if current organization has a feature enabled.

    Args:
        feature_key: Feature to check (use FeatureKey constants)
        organization_id: Org ID to check, or None to use current session org

    Returns:
        True if feature is enabled
    """
    from viraltracker.services.feature_service import FeatureService
    from viraltracker.core.database import get_supabase_client

    if organization_id is None:
        organization_id = get_current_organization_id()

    if not organization_id:
        return False

    service = FeatureService(get_supabase_client())
    return service.has_feature(organization_id, feature_key)


def require_feature(feature_key: str, feature_name: str = None) -> bool:
    """
    Require a feature to be enabled for the current organization.

    Call this at the top of a page (after require_auth) to gate access.
    Shows an error message and stops page execution if feature is disabled.

    Args:
        feature_key: Feature to require (use FeatureKey constants)
        feature_name: Human-readable name for error message (optional)

    Returns:
        True if feature is enabled (page can continue)

    Usage:
        from viraltracker.ui.utils import require_feature
        from viraltracker.services.feature_service import FeatureKey

        require_feature(FeatureKey.VEO_AVATARS, "Veo Avatars")
    """
    org_id = get_current_organization_id()

    if not org_id:
        st.error("Please select an organization first.")
        st.stop()
        return False

    if has_feature(feature_key, org_id):
        return True

    # Feature not enabled - show error
    display_name = feature_name or feature_key.replace("_", " ").title()
    st.error(f"**{display_name}** is not enabled for your organization.")
    st.info("Contact your administrator to enable this feature.")
    st.stop()
    return False


# ============================================================================
# BRAND UTILITIES
# ============================================================================

def get_brands(organization_id: Optional[str] = None):
    """
    Fetch brands from database, filtered by organization.

    Args:
        organization_id: Organization ID to filter by.
            - If None, uses current org from session state
            - If "all", returns all brands (superuser mode)
            - Otherwise filters to specific org

    Returns:
        List of brand dicts with id and name
    """
    from viraltracker.core.database import get_supabase_client

    # Use current org from session if not provided
    if organization_id is None:
        organization_id = get_current_organization_id()

    db = get_supabase_client()
    query = db.table("brands").select("id, name, organization_id")

    # Filter by org unless "all" (superuser mode)
    if organization_id and organization_id != "all":
        query = query.eq("organization_id", organization_id)

    result = query.order("name").execute()
    return result.data or []


def get_products_for_brand(brand_id: str):
    """Fetch products for a brand."""
    from viraltracker.core.database import get_supabase_client
    db = get_supabase_client()
    result = db.table("products").select("id, name").eq(
        "brand_id", brand_id
    ).order("name").execute()
    return result.data or []


def render_brand_selector(
    key: str = "brand_selector",
    show_label: bool = True,
    label: str = "Select Brand",
    include_product: bool = False,
    product_label: str = "Filter by Product (optional)",
    product_key: str = "product_selector"
) -> Optional[str] | Tuple[Optional[str], Optional[str]]:
    """
    Render a brand selector that persists across pages.

    Automatically renders organization selector in sidebar first.
    Uses st.session_state.selected_brand_id to maintain selection
    when switching between pages in the same browser session.

    Args:
        key: Unique key for the brand selectbox widget
        show_label: Whether to show the label
        label: Label text for the selectbox
        include_product: If True, also render product selector and return tuple
        product_label: Label for product selector
        product_key: Unique key for product selectbox widget

    Returns:
        If include_product=False: Selected brand ID as string, or None
        If include_product=True: Tuple of (brand_id, product_id) or (None, None)
    """
    # Render org selector in sidebar (handles superuser "All Organizations" option)
    org_id = render_organization_selector()
    if not org_id:
        if include_product:
            return None, None
        return None

    # Get brands filtered by organization
    brands = get_brands(org_id)

    if not brands:
        st.warning("No brands found. Create a brand first.")
        if include_product:
            return None, None
        return None

    # Build options
    brand_options = {b['name']: b['id'] for b in brands}
    brand_names = list(brand_options.keys())

    # Find current index based on session state
    current_index = 0
    if st.session_state.get('selected_brand_id'):
        current_id = st.session_state.selected_brand_id
        for i, name in enumerate(brand_names):
            if brand_options[name] == current_id:
                current_index = i
                break

    # Render brand selector (with optional product in columns)
    if include_product:
        col1, col2 = st.columns(2)
        with col1:
            selected_name = st.selectbox(
                label if show_label else "",
                options=brand_names,
                index=current_index,
                key=key,
                label_visibility="visible" if show_label else "collapsed"
            )
    else:
        selected_name = st.selectbox(
            label if show_label else "",
            options=brand_names,
            index=current_index,
            key=key,
            label_visibility="visible" if show_label else "collapsed"
        )

    # Update session state
    selected_id = brand_options[selected_name]
    st.session_state.selected_brand_id = selected_id

    if not include_product:
        return selected_id

    # Product selector
    with col2:
        products = get_products_for_brand(selected_id)
        if products:
            product_options = {"All Products (Brand-level)": None}
            product_options.update({p["name"]: p["id"] for p in products})

            # Find current product index
            product_index = 0
            if st.session_state.get('selected_product_id'):
                current_prod = st.session_state.selected_product_id
                for i, (name, pid) in enumerate(product_options.items()):
                    if pid == current_prod:
                        product_index = i
                        break

            selected_product_name = st.selectbox(
                product_label,
                options=list(product_options.keys()),
                index=product_index,
                key=product_key,
                help="Select a product to filter analyses"
            )
            selected_product_id = product_options[selected_product_name]
            st.session_state.selected_product_id = selected_product_id
        else:
            st.info("No products defined yet")
            selected_product_id = None
            st.session_state.selected_product_id = None

    return selected_id, selected_product_id


# ============================================================================
# BELIEF-FIRST ANALYSIS UI COMPONENTS
# ============================================================================

def render_belief_first_analysis(analysis: dict, show_recommendations: bool = True, nested: bool = False):
    """
    Render the 13-layer belief-first analysis with grouped expanders.

    Args:
        analysis: The belief-first analysis dict from the service
        show_recommendations: Whether to show copy recommendations
        nested: If True, use flat layout (no expanders) to avoid nested expander errors
    """
    if not analysis:
        st.info("No belief-first analysis available. Run the analysis to see results.")
        return

    layers = analysis.get("layers", {})
    summary = analysis.get("summary", {})

    # Summary metrics row
    col1, col2, col3, col4, col5 = st.columns(5)
    with col1:
        st.metric("Score", f"{summary.get('overall_score', 0)}/10")
    with col2:
        st.metric("Clear", summary.get("clear", 0))
    with col3:
        st.metric("Weak", summary.get("weak", 0))
    with col4:
        st.metric("Missing", summary.get("missing", 0))
    with col5:
        st.metric("Conflicting", summary.get("conflicting", 0))

    # Key insight callout
    if summary.get("key_insight"):
        st.info(f"**Key Insight:** {summary['key_insight']}")

    st.divider()

    # Layer groupings for better organization
    layer_groups = {
        "Market & Brand Foundation": ["market_context", "brand", "product_offer"],
        "Audience Understanding": ["persona", "jobs_to_be_done", "persona_sublayers"],
        "Messaging Strategy": ["angle", "unique_mechanism", "problem_pain_symptoms"],
        "Value Communication": ["benefits", "features", "proof_risk_reversal", "expression"]
    }

    # Status emoji mapping
    status_emoji = {
        "clear": "✅",
        "weak": "⚠️",
        "missing": "❌",
        "conflicting": "🔄"
    }

    # Display name mapping
    display_names = {
        "market_context": "Market Context & Awareness",
        "brand": "Brand",
        "product_offer": "Product/Offer",
        "persona": "Persona",
        "jobs_to_be_done": "Jobs to Be Done",
        "persona_sublayers": "Persona Sub-layers",
        "angle": "Angle (Core Explanation)",
        "unique_mechanism": "Unique Mechanism",
        "problem_pain_symptoms": "Problem → Pain → Symptoms",
        "benefits": "Benefits",
        "features": "Features",
        "proof_risk_reversal": "Proof & Risk Reversal",
        "expression": "Expression (Language & Structure)"
    }

    for group_name, layer_names in layer_groups.items():
        st.subheader(group_name)

        for layer_name in layer_names:
            layer_data = layers.get(layer_name, {})
            status = layer_data.get("status", "missing")
            emoji = status_emoji.get(status, "❓")
            display_name = display_names.get(layer_name, layer_name.replace("_", " ").title())

            # Helper function to render layer content
            def render_layer_content(layer_data, layer_name, status, show_recommendations):
                # Explanation
                explanation = layer_data.get("explanation", "No analysis available")
                st.markdown(f"**Analysis:** {explanation}")

                # Examples
                examples = layer_data.get("examples", [])
                if examples:
                    st.markdown("**Evidence from page:**")
                    for ex in examples[:5]:
                        quote = ex.get("quote", "") if isinstance(ex, dict) else str(ex)
                        location = ex.get("location", "") if isinstance(ex, dict) else ""
                        loc_str = f" *({location})*" if location else ""
                        st.markdown(f'> "{quote}"{loc_str}')

                # Context
                context = layer_data.get("context", "")
                if context:
                    st.markdown(f"**Impact:** {context}")

                # Layer-specific fields
                if layer_name == "market_context":
                    awareness = layer_data.get("awareness_level", "unknown")
                    st.caption(f"Awareness Level: {awareness}")

                elif layer_name == "problem_pain_symptoms":
                    problem = layer_data.get("problem", "")
                    pain = layer_data.get("pain", "")
                    symptoms = layer_data.get("symptoms", [])
                    if problem:
                        st.markdown(f"**Problem:** {problem}")
                    if pain:
                        st.markdown(f"**Pain:** {pain}")
                    if symptoms:
                        st.markdown(f"**Symptoms:** {', '.join(symptoms)}")

                elif layer_name == "proof_risk_reversal":
                    proof_types = layer_data.get("proof_types", [])
                    risk_reversal = layer_data.get("risk_reversal")
                    if proof_types:
                        st.markdown(f"**Proof Types:** {', '.join(proof_types)}")
                    if risk_reversal:
                        st.markdown(f"**Risk Reversal:** {risk_reversal}")

                elif layer_name == "expression":
                    lang_patterns = layer_data.get("language_patterns", {})
                    structure = layer_data.get("structure", {})
                    if lang_patterns.get("tone"):
                        st.markdown(f"**Tone:** {lang_patterns.get('tone')}")
                    if lang_patterns.get("power_words"):
                        st.markdown(f"**Power Words:** {', '.join(lang_patterns.get('power_words', []))}")
                    if structure.get("flow"):
                        st.markdown(f"**Flow:** {structure.get('flow')}")

                # Recommendations (only show if not clear and enabled)
                if show_recommendations and status != "clear":
                    recommendations = layer_data.get("recommendations", [])
                    if recommendations:
                        st.markdown("---")
                        st.markdown("**Recommendations:**")
                        for rec in recommendations:
                            st.markdown(f"- {rec}")

            if nested:
                # Flat layout - use markdown header instead of expander
                st.markdown(f"**{emoji} {display_name} — {status.upper()}**")
                render_layer_content(layer_data, layer_name, status, show_recommendations)
                st.markdown("---")
            else:
                # Use expanders (default)
                with st.expander(f"{emoji} {display_name} — {status.upper()}", expanded=(status != "clear")):
                    render_layer_content(layer_data, layer_name, status, show_recommendations)


def render_belief_first_aggregation(aggregation: dict, entity_name: str = "Brand"):
    """
    Render aggregated belief-first analysis across multiple pages.

    Args:
        aggregation: Aggregation dict with layer_summary, problem_pages, overall
        entity_name: Name to display (e.g., brand name or competitor name)
    """
    import pandas as pd

    if not aggregation or not aggregation.get("layer_summary"):
        st.info("No aggregated analysis available yet. Analyze landing pages first.")
        return

    overall = aggregation.get("overall", {})
    layer_summary = aggregation.get("layer_summary", {})
    problem_pages = aggregation.get("problem_pages", [])

    st.subheader(f"Belief-First Analysis Summary: {entity_name}")

    # Overall metrics
    col1, col2, col3 = st.columns(3)
    with col1:
        st.metric("Pages Analyzed", overall.get("total_pages", 0))
    with col2:
        avg_score = overall.get("average_score", 0)
        st.metric("Average Score", f"{avg_score}/10" if avg_score else "N/A")
    with col3:
        st.metric("Problem Pages", len(problem_pages))

    # Most common issues
    most_common = overall.get("most_common_issues", [])
    if most_common:
        formatted = [name.replace("_", " ").title() for name in most_common]
        st.warning(f"**Most Common Issues:** {', '.join(formatted)}")

    # Strongest layers
    strongest = overall.get("strongest_layers", [])
    if strongest:
        formatted = [name.replace("_", " ").title() for name in strongest]
        st.success(f"**Strongest Layers:** {', '.join(formatted)}")

    st.divider()

    # Layer-by-layer summary table
    st.subheader("Layer Performance Across Pages")

    # Build table data
    layer_rows = []
    for layer_name, counts in layer_summary.items():
        display_name = layer_name.replace("_", " ").title()
        total = sum(counts.values())
        clear_pct = (counts.get("clear", 0) / total * 100) if total > 0 else 0
        layer_rows.append({
            "Layer": display_name,
            "Clear": counts.get("clear", 0),
            "Weak": counts.get("weak", 0),
            "Missing": counts.get("missing", 0),
            "Conflicting": counts.get("conflicting", 0),
            "Clear %": f"{clear_pct:.0f}%"
        })

    df = pd.DataFrame(layer_rows)
    st.dataframe(df, use_container_width=True, hide_index=True)

    # Problem pages list
    if problem_pages:
        st.divider()
        st.subheader("Problem Pages (Ranked by Issues)")

        for i, page in enumerate(problem_pages[:10], 1):
            url = page.get("url", "Unknown URL")
            issue_count = page.get("issue_count", 0)
            score = page.get("score", 0)

            # Truncate long URLs
            display_url = url[:60] + "..." if len(url) > 60 else url

            with st.expander(f"{i}. {display_url} — {issue_count} issues (Score: {score}/10)"):
                st.markdown(f"**Full URL:** {url}")
                top_issues = page.get("top_issues", [])
                if top_issues:
                    st.markdown("**Top Issues:**")
                    for issue in top_issues:
                        layer = issue.get("layer", "").replace("_", " ").title()
                        status = issue.get("status", "")
                        priority = issue.get("priority", "medium")
                        st.markdown(f"- **{layer}**: {status} (Priority: {priority})")
