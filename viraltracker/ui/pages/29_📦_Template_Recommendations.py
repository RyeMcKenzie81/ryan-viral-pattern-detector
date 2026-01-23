"""
Template Recommendations Page

AI-powered template recommendations for products.
- Generate recommendations using AI matching or diversity
- Review and select recommended templates
- Manage saved recommendations
- Integration with Ad Creator/Scheduler via filters
"""

import asyncio
import streamlit as st
from typing import Dict, List, Optional, Set
from uuid import UUID

# Page config must be first
st.set_page_config(
    page_title="Template Recommendations",
    page_icon="📦",
    layout="wide"
)

# Auth
from viraltracker.ui.auth import require_auth
require_auth()

# Imports
from viraltracker.core.database import get_supabase_client
from viraltracker.ui.utils import render_brand_selector, get_products_for_brand


# =============================================================================
# Session State Initialization
# =============================================================================

if 'recommendation_candidates' not in st.session_state:
    st.session_state.recommendation_candidates = []  # List of candidate dicts

if 'selected_candidate_ids' not in st.session_state:
    st.session_state.selected_candidate_ids = set()  # Set of template_id strings

if 'generation_in_progress' not in st.session_state:
    st.session_state.generation_in_progress = False

if 'last_methodology' not in st.session_state:
    st.session_state.last_methodology = None


# =============================================================================
# Helper Functions
# =============================================================================

@st.cache_resource
def get_recommendation_service():
    """Get TemplateRecommendationService instance."""
    from viraltracker.services.template_recommendation_service import TemplateRecommendationService
    return TemplateRecommendationService()


def get_offer_variants(product_id: str) -> List[Dict]:
    """Get offer variants for a product."""
    db = get_supabase_client()
    result = db.table("product_offer_variants").select(
        "id, name"
    ).eq("product_id", product_id).eq("is_active", True).order("display_order").execute()
    return result.data or []


def get_asset_url(storage_path: str) -> str:
    """Get public URL for template asset."""
    if not storage_path:
        return ""
    try:
        db = get_supabase_client()
        if "/" in storage_path:
            parts = storage_path.split("/", 1)
            bucket = parts[0]
            path = parts[1]
        else:
            bucket = "scraped-templates"
            path = storage_path
        return db.storage.from_(bucket).get_public_url(path)
    except Exception:
        return ""


def toggle_candidate_selection(template_id: str):
    """Toggle a candidate's selection status."""
    if template_id in st.session_state.selected_candidate_ids:
        st.session_state.selected_candidate_ids.discard(template_id)
    else:
        st.session_state.selected_candidate_ids.add(template_id)


def clear_candidate_selections():
    """Clear all candidate selections."""
    st.session_state.selected_candidate_ids = set()


def select_all_candidates():
    """Select all candidates."""
    st.session_state.selected_candidate_ids = {
        str(c.template_id) for c in st.session_state.recommendation_candidates
    }


# =============================================================================
# Main Page Content
# =============================================================================

st.title("📦 Template Recommendations")
st.caption("Generate AI-powered template recommendations for your products")

# Brand and Product Selection
col1, col2, col3 = st.columns([2, 2, 2])

with col1:
    brand_id = render_brand_selector(key="rec_brand_selector")
    if not brand_id:
        st.stop()

with col2:
    products = get_products_for_brand(brand_id)
    if not products:
        st.warning("No products found for this brand. Create a product first.")
        st.stop()

    product_options = {p["name"]: p["id"] for p in products}
    selected_product_name = st.selectbox(
        "Select Product",
        options=list(product_options.keys()),
        key="rec_product_selector"
    )
    selected_product_id = product_options[selected_product_name]

with col3:
    # Optional offer variant selector
    offer_variants = get_offer_variants(selected_product_id)
    if offer_variants:
        ov_options = {"Base Product": None}
        ov_options.update({ov["name"]: ov["id"] for ov in offer_variants})
        selected_ov_name = st.selectbox(
            "Offer Variant (optional)",
            options=list(ov_options.keys()),
            key="rec_ov_selector",
            help="Select an offer variant to use its pain points and benefits for matching"
        )
        selected_ov_id = ov_options[selected_ov_name]
    else:
        selected_ov_id = None
        st.caption("No offer variants defined")

st.divider()

# Methodology Selection and Generate Button
col1, col2, col3 = st.columns([2, 2, 2])

with col1:
    methodology = st.selectbox(
        "Recommendation Methodology",
        options=["AI Match", "Diversity", "Longevity"],
        key="rec_methodology",
        help="AI Match: Score templates based on product fit. Diversity: Select variety across categories. Longevity: Recommend longest-running ads."
    )
    methodology_map = {
        "AI Match": "ai_match",
        "Diversity": "diversity",
        "Longevity": "longevity"
    }
    methodology_value = methodology_map[methodology]

with col2:
    limit = st.slider(
        "Max Recommendations",
        min_value=5,
        max_value=50,
        value=20,
        step=5,
        key="rec_limit"
    )

with col3:
    st.write("")  # Spacer
    st.write("")  # Spacer
    generate_clicked = st.button(
        "🔮 Generate Recommendations",
        type="primary",
        use_container_width=True,
        disabled=st.session_state.generation_in_progress
    )

# Handle Generate button
if generate_clicked:
    st.session_state.generation_in_progress = True
    st.session_state.recommendation_candidates = []
    st.session_state.selected_candidate_ids = set()
    st.session_state.last_methodology = methodology_value

    # Run async generation
    async def run_generation():
        from viraltracker.services.template_recommendation_service import TemplateRecommendationService
        from viraltracker.services.models import GenerateRecommendationsRequest, RecommendationMethodology

        service = TemplateRecommendationService()
        request = GenerateRecommendationsRequest(
            product_id=UUID(selected_product_id),
            offer_variant_id=UUID(selected_ov_id) if selected_ov_id else None,
            methodology=RecommendationMethodology(methodology_value),
            limit=limit,
        )
        return await service.generate_recommendations(request)

    with st.spinner(f"Analyzing {limit} templates using {methodology}..."):
        try:
            result = asyncio.run(run_generation())
            st.session_state.recommendation_candidates = result.candidates
            st.session_state.generation_in_progress = False
            st.success(
                f"Generated {len(result.candidates)} recommendations from "
                f"{result.total_templates_analyzed} templates in {result.generation_time_ms}ms"
            )
            st.rerun()
        except Exception as e:
            st.session_state.generation_in_progress = False
            st.error(f"Generation failed: {e}")

st.divider()

# Tabs for Candidates and Saved Recommendations
tab1, tab2 = st.tabs(["✨ Generated Candidates", "📋 Saved Recommendations"])

# =============================================================================
# Tab 1: Generated Candidates
# =============================================================================

with tab1:
    candidates = st.session_state.recommendation_candidates

    if not candidates:
        st.info(
            "No candidates generated yet. Select a product and click "
            "'Generate Recommendations' to get AI-scored template suggestions."
        )
    else:
        # Selection controls
        col1, col2, col3, col4 = st.columns([2, 2, 2, 4])
        with col1:
            if st.button("Select All", key="select_all_btn"):
                select_all_candidates()
                st.rerun()
        with col2:
            if st.button("Clear Selection", key="clear_sel_btn"):
                clear_candidate_selections()
                st.rerun()
        with col3:
            selected_count = len(st.session_state.selected_candidate_ids)
            st.metric("Selected", selected_count)

        st.divider()

        # Render candidates in grid
        cols_per_row = 4
        for i in range(0, len(candidates), cols_per_row):
            cols = st.columns(cols_per_row)
            for j, col in enumerate(cols):
                if i + j >= len(candidates):
                    break

                candidate = candidates[i + j]
                template_id_str = str(candidate.template_id)
                is_selected = template_id_str in st.session_state.selected_candidate_ids

                with col:
                    with st.container(border=True):
                        # Image
                        url = get_asset_url(candidate.storage_path)
                        if url:
                            st.image(url, use_container_width=True)
                        else:
                            st.caption("No preview")

                        # Checkbox for selection - show different label for longevity
                        if st.session_state.last_methodology == "longevity":
                            # Extract days from reasoning (format: "Running for X days ...")
                            reasoning = candidate.reasoning or ""
                            if reasoning.startswith("Running for "):
                                days_part = reasoning.split(" days")[0].replace("Running for ", "")
                                label = f"**{days_part} days** - {candidate.template_name[:18]}"
                            else:
                                label = f"**{candidate.template_name[:25]}**"
                        else:
                            label = f"**{int(candidate.score * 100)}%** - {candidate.template_name[:20]}"

                        checked = st.checkbox(
                            label,
                            value=is_selected,
                            key=f"cand_cb_{template_id_str}"
                        )

                        # Update selection on change
                        if checked and not is_selected:
                            st.session_state.selected_candidate_ids.add(template_id_str)
                        elif not checked and is_selected:
                            st.session_state.selected_candidate_ids.discard(template_id_str)

                        # Score breakdown - different display for longevity
                        breakdown = candidate.score_breakdown
                        if st.session_state.last_methodology == "longevity":
                            # Show active status instead of scores
                            is_active = "(still active)" in (candidate.reasoning or "")
                            status = "🟢 Active" if is_active else "⚪ Inactive"
                            st.caption(status)
                        else:
                            st.caption(
                                f"Niche: {int(breakdown.niche_match * 100)}% | "
                                f"Aware: {int(breakdown.awareness_match * 100)}%"
                            )

                        # Metadata badges
                        badges = []
                        if candidate.industry_niche:
                            badges.append(candidate.industry_niche)
                        if candidate.awareness_level:
                            badges.append(f"L{candidate.awareness_level}")
                        if candidate.target_sex:
                            badges.append(candidate.target_sex[:1].upper())
                        st.caption(" | ".join(badges) if badges else "")

                        # Reasoning tooltip
                        if candidate.reasoning:
                            with st.expander("Why?", expanded=False):
                                st.caption(candidate.reasoning)

        st.divider()

        # Save button
        if selected_count > 0:
            if st.button(
                f"💾 Save {selected_count} Selected Recommendations",
                type="primary",
                use_container_width=True
            ):
                from viraltracker.services.models import RecommendationMethodology

                service = get_recommendation_service()

                # Build scores dict
                scores = {}
                for c in candidates:
                    tid = str(c.template_id)
                    if tid in st.session_state.selected_candidate_ids:
                        scores[tid] = {
                            "score": c.score,
                            "breakdown": c.score_breakdown.model_dump(),
                            "reasoning": c.reasoning,
                        }

                # Save
                saved = service.save_recommendations(
                    product_id=UUID(selected_product_id),
                    template_ids=[UUID(tid) for tid in st.session_state.selected_candidate_ids],
                    methodology=RecommendationMethodology(methodology_value),
                    scores=scores,
                    offer_variant_id=UUID(selected_ov_id) if selected_ov_id else None,
                    recommended_by="streamlit_user",
                )

                st.success(f"Saved {saved} recommendations!")
                st.session_state.recommendation_candidates = []
                st.session_state.selected_candidate_ids = set()
                st.rerun()
        else:
            st.info("Select candidates using the checkboxes, then click Save.")


# =============================================================================
# Tab 2: Saved Recommendations
# =============================================================================

with tab2:
    service = get_recommendation_service()
    saved_recs = service.get_recommendations(UUID(selected_product_id), unused_only=False)

    if not saved_recs:
        st.info(
            f"No saved recommendations for **{selected_product_name}** yet. "
            "Generate and save some recommendations to see them here."
        )
    else:
        # Stats
        counts = service.get_recommendation_count(UUID(selected_product_id))
        col1, col2, col3 = st.columns(3)
        col1.metric("Total", counts["total"])
        col2.metric("Used", counts["used"])
        col3.metric("Unused", counts["unused"])

        st.divider()

        # List saved recommendations
        for rec in saved_recs:
            template = rec.get("scraped_templates", {})
            template_name = template.get("name", "Unknown")
            template_category = template.get("category", "other")
            storage_path = template.get("storage_path", "")

            with st.container(border=True):
                col1, col2, col3, col4 = st.columns([1, 3, 1, 1])

                with col1:
                    url = get_asset_url(storage_path)
                    if url:
                        st.image(url, width=80)

                with col2:
                    st.markdown(f"**{template_name}**")
                    st.caption(f"{template_category} | Score: {int(rec['score'] * 100)}%")

                    # Usage status
                    if rec.get("used"):
                        times = rec.get("times_used", 1)
                        st.caption(f"✅ Used {times}x")
                    else:
                        st.caption("🆕 Not yet used")

                with col3:
                    # Show reasoning if available
                    reasoning = rec.get("reasoning", "")
                    if reasoning:
                        with st.expander("Why?"):
                            st.caption(reasoning)

                with col4:
                    if st.button("✗ Remove", key=f"remove_{rec['id']}"):
                        service.remove_recommendation(UUID(rec["id"]))
                        st.rerun()

        st.divider()

        # Clear all button
        if st.button(
            f"🗑️ Clear All Recommendations for {selected_product_name}",
            type="secondary"
        ):
            count = service.remove_all_recommendations(UUID(selected_product_id))
            st.success(f"Removed {count} recommendations")
            st.rerun()


# =============================================================================
# Sidebar Info
# =============================================================================

with st.sidebar:
    st.subheader("About Template Recommendations")
    st.markdown("""
    **How it works:**

    1. **Select a Product** - Choose which product needs templates

    2. **Choose Methodology**
       - *AI Match*: Scores templates based on niche, awareness level, audience, and format fit
       - *Diversity*: Selects variety across template categories
       - *Longevity*: Recommends templates from the longest-running ads (ads that run longer likely perform well)

    3. **Generate & Review** - AI analyzes templates and ranks them by fit

    4. **Save Favorites** - Selected templates are saved as recommendations

    5. **Use in Ad Creator** - Filter templates by "Recommended" or "Unused Recommended"
    """)

    st.divider()

    st.caption("Scoring Dimensions:")
    st.markdown("""
    - **Niche Match**: Template industry vs product category
    - **Awareness Match**: Template awareness level appropriateness
    - **Audience Match**: Target audience alignment
    - **Format Fit**: Visual format suitability
    """)
