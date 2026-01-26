"""
Competitive Analysis - Compare your brand vs competitors.

This page allows users to:
- Compare brand personas vs competitor personas
- Identify messaging gaps and opportunities
- Generate competitive positioning insights
- Find untapped angles and differentiators
"""

import streamlit as st
import asyncio
import json
from datetime import datetime
from uuid import UUID
from typing import Optional, Dict, Any, List

# Page config
st.set_page_config(
    page_title="Competitive Analysis",
    page_icon="📊",
    layout="wide"
)

# Authentication
from viraltracker.ui.auth import require_auth
require_auth()

# Initialize session state
if 'competitive_analysis' not in st.session_state:
    st.session_state.competitive_analysis = None
if 'analysis_running' not in st.session_state:
    st.session_state.analysis_running = False


def get_supabase_client():
    """Get Supabase client."""
    from viraltracker.core.database import get_supabase_client
    return get_supabase_client()


def get_competitor_service():
    """Get CompetitorService instance with tracking enabled."""
    from viraltracker.services.competitor_service import CompetitorService
    from viraltracker.ui.utils import setup_tracking_context
    service = CompetitorService()
    setup_tracking_context(service)
    return service


def get_brands():
    """Fetch all brands."""
    try:
        db = get_supabase_client()
        result = db.table("brands").select("id, name").order("name").execute()
        return result.data or []
    except Exception as e:
        st.error(f"Failed to fetch brands: {e}")
        return []


def get_brand_personas(brand_id: str) -> List[Dict]:
    """Get personas for a brand (own-brand personas)."""
    try:
        db = get_supabase_client()
        result = db.table("personas_4d").select("*").eq(
            "brand_id", brand_id
        ).in_("persona_type", ["own_brand", "product_specific"]).execute()
        return result.data or []
    except Exception as e:
        st.error(f"Failed to fetch brand personas: {e}")
        return []


def get_competitor_personas(brand_id: str) -> List[Dict]:
    """Get competitor personas for a brand."""
    try:
        db = get_supabase_client()
        result = db.table("personas_4d").select(
            "*, competitors(name)"
        ).eq("brand_id", brand_id).eq("persona_type", "competitor").execute()
        return result.data or []
    except Exception as e:
        st.error(f"Failed to fetch competitor personas: {e}")
        return []


def get_competitors_for_brand(brand_id: str) -> List[Dict]:
    """Get all competitors for a brand with their stats."""
    service = get_competitor_service()
    return service.get_competitors_for_brand(UUID(brand_id))


def run_competitive_analysis_sync(
    brand_name: str,
    brand_personas: List[Dict],
    competitor_personas: List[Dict],
    competitor_amazon_analyses: List[Dict]
) -> Dict:
    """Run AI-powered competitive analysis."""
    from viraltracker.core.config import Config
    from pydantic_ai import Agent
    from viraltracker.core.database import reset_supabase_client
    reset_supabase_client()

    # Prepare brand persona summary
    brand_summary = []
    for p in brand_personas:
        brand_summary.append({
            "name": p.get("name"),
            "snapshot": p.get("snapshot"),
            "demographics": p.get("demographics", {}),
            "pain_points": p.get("pain_points", {}),
            "desires": p.get("desires", {}),
            "transformation_map": p.get("transformation_map", {}),
            "self_narratives": p.get("self_narratives", []),
            "buying_objections": p.get("buying_objections", {}),
            "activation_events": p.get("activation_events", [])
        })

    # Prepare competitor persona summary
    competitor_summary = []
    for p in competitor_personas:
        competitor_name = p.get("competitors", {}).get("name", "Unknown")
        competitor_summary.append({
            "competitor_name": competitor_name,
            "persona_name": p.get("name"),
            "snapshot": p.get("snapshot"),
            "demographics": p.get("demographics", {}),
            "pain_points": p.get("pain_points", {}),
            "desires": p.get("desires", {}),
            "transformation_map": p.get("transformation_map", {}),
            "messaging_patterns": p.get("messaging_patterns", []),
            "hooks": p.get("hooks", [])
        })

    # Include Amazon review insights
    amazon_insights = []
    for analysis in competitor_amazon_analyses:
        amazon_insights.append({
            "competitor_name": analysis.get("competitor_name"),
            "pain_points": analysis.get("pain_points", {}),
            "desires": analysis.get("desires", {}),
            "language_patterns": analysis.get("language_patterns", {}),
            "top_positive_quotes": analysis.get("top_positive_quotes", [])[:5],
            "top_negative_quotes": analysis.get("top_negative_quotes", [])[:5]
        })

    prompt = f"""You are a competitive marketing analyst. Analyze the following data to identify competitive opportunities for {brand_name}.

## YOUR BRAND'S PERSONAS:
{json.dumps(brand_summary, indent=2)}

## COMPETITOR PERSONAS (extracted from their ads):
{json.dumps(competitor_summary, indent=2)}

## COMPETITOR AMAZON REVIEW INSIGHTS:
{json.dumps(amazon_insights, indent=2)}

Based on this analysis, provide a comprehensive competitive analysis in the following JSON format:

{{
    "executive_summary": "2-3 sentence overview of competitive position and biggest opportunities",

    "persona_overlap": {{
        "shared_demographics": ["demographics both target"],
        "shared_pain_points": ["pain points both address"],
        "shared_desires": ["desires both appeal to"],
        "overlap_percentage": 0-100
    }},

    "your_advantages": [
        {{
            "advantage": "what you do better",
            "evidence": "specific evidence from persona data",
            "messaging_angle": "how to leverage this in ads"
        }}
    ],

    "competitor_advantages": [
        {{
            "competitor": "competitor name",
            "advantage": "what they do better",
            "evidence": "specific evidence",
            "counter_strategy": "how to compete against this"
        }}
    ],

    "untapped_angles": [
        {{
            "angle": "messaging angle competitors aren't using",
            "target_pain_point": "which pain point it addresses",
            "why_untapped": "why competitors might be missing this",
            "suggested_hooks": ["3 hook variations to test"]
        }}
    ],

    "customer_language_gaps": {{
        "phrases_competitors_use": ["phrases from competitor ads/reviews you're not using"],
        "pain_language_to_adopt": ["how customers describe their problems"],
        "desire_language_to_adopt": ["how customers describe desired outcomes"]
    }},

    "positioning_recommendations": [
        {{
            "recommendation": "strategic positioning recommendation",
            "rationale": "why this would work",
            "implementation": "how to implement in messaging"
        }}
    ],

    "objection_opportunities": [
        {{
            "objection": "customer objection competitors struggle with",
            "competitor_response": "how competitors handle it (or don't)",
            "your_opportunity": "how you can address it better"
        }}
    ],

    "creative_test_ideas": [
        {{
            "concept": "ad creative concept to test",
            "target_segment": "which persona segment",
            "differentiation": "how it differs from competitor approach"
        }}
    ]
}}

Return ONLY valid JSON, no markdown formatting."""

    # Pydantic AI Agent (Complex Model for deep analysis)
    agent = Agent(
        model=Config.get_model("complex"),
        system_prompt="You are a competitive marketing analyst. Return ONLY valid JSON."
    )

    try:
        # Run sync for Streamlit
        result = agent.run_sync(prompt)
        response_text = result.output.strip()

        # Clean up response
        if response_text.startswith("```"):
            response_text = response_text.split("```")[1]
            if response_text.startswith("json"):
                response_text = response_text[4:]
            response_text = response_text.strip()

        return json.loads(response_text)
    except Exception as e:
        raise Exception(f"Analysis failed: {e}")


# =============================================================================
# UI Components
# =============================================================================

def render_data_status(brand_id: str, brand_personas: List, competitors: List):
    """Render data status overview."""
    st.subheader("📋 Data Status")

    col1, col2, col3, col4 = st.columns(4)

    with col1:
        st.metric("Your Personas", len(brand_personas))
        if not brand_personas:
            st.caption("⚠️ Run Brand Research first")

    with col2:
        st.metric("Competitors", len(competitors))
        if not competitors:
            st.caption("⚠️ Add competitors first")

    # Count competitor personas
    competitor_personas = get_competitor_personas(brand_id)
    with col3:
        st.metric("Competitor Personas", len(competitor_personas))
        if competitors and not competitor_personas:
            st.caption("⚠️ Run Competitor Research")

    # Count Amazon analyses
    service = get_competitor_service()
    amazon_count = 0
    for comp in competitors:
        stats = service.get_competitor_amazon_stats(UUID(comp['id']))
        if stats.get('has_analysis'):
            amazon_count += 1

    with col4:
        st.metric("Amazon Analyses", amazon_count)
        if competitors and amazon_count == 0:
            st.caption("📝 Optional but valuable")


def render_analysis_section(
    brand_name: str,
    brand_id: str,
    brand_personas: List,
    competitors: List
):
    """Render the analysis trigger section."""
    st.subheader("🔬 Generate Competitive Analysis")

    # Get competitor data
    competitor_personas = get_competitor_personas(brand_id)
    service = get_competitor_service()

    # Get Amazon analyses
    amazon_analyses = []
    for comp in competitors:
        analysis = service.get_competitor_amazon_analysis(UUID(comp['id']))
        if analysis:
            analysis['competitor_name'] = comp['name']
            amazon_analyses.append(analysis)

    # Check readiness
    ready = len(brand_personas) > 0 and len(competitor_personas) > 0

    if not ready:
        st.warning(
            "You need at least one brand persona and one competitor persona to run analysis. "
            "Complete Brand Research and Competitor Research first."
        )
        return

    st.success(
        f"Ready to analyze! {len(brand_personas)} brand persona(s), "
        f"{len(competitor_personas)} competitor persona(s), "
        f"{len(amazon_analyses)} Amazon analysis(es)"
    )

    if st.button(
        "Generate Competitive Analysis",
        type="primary",
        disabled=st.session_state.analysis_running
    ):
        st.session_state.analysis_running = True

        with st.spinner("Analyzing competitive landscape (30-60 seconds)..."):
            try:
                result = run_competitive_analysis_sync(
                    brand_name=brand_name,
                    brand_personas=brand_personas,
                    competitor_personas=competitor_personas,
                    competitor_amazon_analyses=amazon_analyses
                )
                st.session_state.competitive_analysis = result
                st.success("Analysis complete!")
            except Exception as e:
                st.error(f"Analysis failed: {e}")

        st.session_state.analysis_running = False
        st.rerun()


def render_analysis_results(analysis: Dict):
    """Render the competitive analysis results."""
    st.divider()
    st.header("📊 Competitive Analysis Results")

    # Executive Summary
    st.subheader("Executive Summary")
    st.info(analysis.get('executive_summary', 'No summary available'))

    # Tabs for different sections
    tabs = st.tabs([
        "Overlap",
        "Advantages",
        "Untapped Angles",
        "Language",
        "Positioning",
        "Creative Ideas"
    ])

    with tabs[0]:
        st.markdown("### Persona Overlap Analysis")
        overlap = analysis.get('persona_overlap', {})

        col1, col2 = st.columns([1, 3])
        with col1:
            st.metric("Overlap", f"{overlap.get('overlap_percentage', 0)}%")

        with col2:
            if overlap.get('shared_demographics'):
                st.markdown("**Shared Demographics:**")
                for item in overlap['shared_demographics'][:5]:
                    st.markdown(f"- {item}")

            if overlap.get('shared_pain_points'):
                st.markdown("**Shared Pain Points:**")
                for item in overlap['shared_pain_points'][:5]:
                    st.markdown(f"- {item}")

            if overlap.get('shared_desires'):
                st.markdown("**Shared Desires:**")
                for item in overlap['shared_desires'][:5]:
                    st.markdown(f"- {item}")

    with tabs[1]:
        col1, col2 = st.columns(2)

        with col1:
            st.markdown("### Your Advantages ✅")
            for adv in analysis.get('your_advantages', []):
                with st.expander(adv.get('advantage', 'Unknown')):
                    st.markdown(f"**Evidence:** {adv.get('evidence', 'N/A')}")
                    st.markdown(f"**Messaging Angle:** {adv.get('messaging_angle', 'N/A')}")

        with col2:
            st.markdown("### Competitor Advantages ⚠️")
            for adv in analysis.get('competitor_advantages', []):
                with st.expander(f"{adv.get('competitor', 'Unknown')}: {adv.get('advantage', '')}"):
                    st.markdown(f"**Evidence:** {adv.get('evidence', 'N/A')}")
                    st.markdown(f"**Counter Strategy:** {adv.get('counter_strategy', 'N/A')}")

    with tabs[2]:
        st.markdown("### Untapped Messaging Angles 🎯")
        st.caption("Angles your competitors aren't leveraging that you could test")

        for angle in analysis.get('untapped_angles', []):
            with st.expander(angle.get('angle', 'Unknown')):
                st.markdown(f"**Target Pain Point:** {angle.get('target_pain_point', 'N/A')}")
                st.markdown(f"**Why Untapped:** {angle.get('why_untapped', 'N/A')}")

                if angle.get('suggested_hooks'):
                    st.markdown("**Suggested Hooks to Test:**")
                    for hook in angle['suggested_hooks']:
                        st.markdown(f"- \"{hook}\"")

    with tabs[3]:
        st.markdown("### Customer Language Gaps")
        gaps = analysis.get('customer_language_gaps', {})

        if gaps.get('phrases_competitors_use'):
            st.markdown("**Phrases Competitors Use (that you might not be):**")
            for phrase in gaps['phrases_competitors_use'][:10]:
                st.markdown(f"- \"{phrase}\"")

        if gaps.get('pain_language_to_adopt'):
            st.markdown("**Pain Language to Adopt:**")
            for phrase in gaps['pain_language_to_adopt'][:10]:
                st.markdown(f"- \"{phrase}\"")

        if gaps.get('desire_language_to_adopt'):
            st.markdown("**Desire Language to Adopt:**")
            for phrase in gaps['desire_language_to_adopt'][:10]:
                st.markdown(f"- \"{phrase}\"")

    with tabs[4]:
        col1, col2 = st.columns(2)

        with col1:
            st.markdown("### Positioning Recommendations")
            for rec in analysis.get('positioning_recommendations', []):
                with st.expander(rec.get('recommendation', 'Unknown')):
                    st.markdown(f"**Rationale:** {rec.get('rationale', 'N/A')}")
                    st.markdown(f"**Implementation:** {rec.get('implementation', 'N/A')}")

        with col2:
            st.markdown("### Objection Opportunities")
            for opp in analysis.get('objection_opportunities', []):
                with st.expander(opp.get('objection', 'Unknown')):
                    st.markdown(f"**How Competitors Handle It:** {opp.get('competitor_response', 'N/A')}")
                    st.markdown(f"**Your Opportunity:** {opp.get('your_opportunity', 'N/A')}")

    with tabs[5]:
        st.markdown("### Creative Test Ideas")
        st.caption("Ad creative concepts to test based on competitive gaps")

        for i, idea in enumerate(analysis.get('creative_test_ideas', []), 1):
            with st.expander(f"Idea {i}: {idea.get('concept', 'Unknown')[:50]}..."):
                st.markdown(f"**Full Concept:** {idea.get('concept', 'N/A')}")
                st.markdown(f"**Target Segment:** {idea.get('target_segment', 'N/A')}")
                st.markdown(f"**Differentiation:** {idea.get('differentiation', 'N/A')}")

    # Export option
    st.divider()
    col1, col2 = st.columns(2)
    with col1:
        if st.button("📥 Export Analysis JSON"):
            st.download_button(
                label="Download JSON",
                data=json.dumps(analysis, indent=2),
                file_name="competitive_analysis.json",
                mime="application/json"
            )
    with col2:
        if st.button("🔄 Run New Analysis"):
            st.session_state.competitive_analysis = None
            st.rerun()


# =============================================================================
# Product-Level Ad Analysis Comparison
# =============================================================================

def get_brand_products(brand_id: str) -> List[Dict]:
    """Get products for a brand."""
    try:
        db = get_supabase_client()
        result = db.table("products").select("id, name").eq("brand_id", brand_id).execute()
        return result.data or []
    except Exception as e:
        st.error(f"Failed to fetch products: {e}")
        return []


def get_competitor_products(competitor_id: str) -> List[Dict]:
    """Get products for a competitor."""
    service = get_competitor_service()
    return service.get_competitor_products(UUID(competitor_id))


def render_product_comparison_section(brand_id: str, competitors: List[Dict]):
    """Render product-level ad analysis comparison."""
    st.subheader("🎯 Product-Level Ad Comparison")
    st.caption("Compare advertising strategies at the product level using AI-extracted ad analysis data")

    # Check if we have the new advertising_structure fields
    st.info("💡 This compares `advertising_structure` data extracted from ad analyses. Re-analyze ads to populate this data for existing ads.")

    # Product selectors
    col1, col2 = st.columns(2)

    with col1:
        st.markdown("**Your Product**")
        brand_products = get_brand_products(brand_id)
        if not brand_products:
            st.warning("No products found. Add products in Brand Manager.")
            return

        brand_product_options = {p['name']: p['id'] for p in brand_products}
        selected_brand_product = st.selectbox(
            "Select your product",
            options=list(brand_product_options.keys()),
            key="brand_product_select"
        )
        brand_product_id = brand_product_options.get(selected_brand_product) if selected_brand_product else None

    with col2:
        st.markdown("**Competitor Product**")
        if not competitors:
            st.warning("No competitors found.")
            return

        competitor_options = {c['name']: c['id'] for c in competitors}
        selected_competitor = st.selectbox(
            "Select competitor",
            options=list(competitor_options.keys()),
            key="competitor_select"
        )
        competitor_id = competitor_options.get(selected_competitor) if selected_competitor else None

        if competitor_id:
            competitor_products = get_competitor_products(competitor_id)
            if competitor_products:
                comp_product_options = {p['name']: p['id'] for p in competitor_products}
                selected_comp_product = st.selectbox(
                    "Select their product",
                    options=list(comp_product_options.keys()),
                    key="comp_product_select"
                )
                comp_product_id = comp_product_options.get(selected_comp_product) if selected_comp_product else None
            else:
                st.caption("No products mapped for this competitor")
                comp_product_id = None
        else:
            comp_product_id = None

    # Compare button
    if brand_product_id and comp_product_id:
        if st.button("🔍 Compare Products", type="primary"):
            with st.spinner("Building comparison..."):
                try:
                    comparison = build_comparison(brand_product_id, comp_product_id)
                    if comparison:
                        st.session_state.product_comparison = comparison
                        st.rerun()
                except Exception as e:
                    st.error(f"Comparison failed: {e}")

    # Show comparison results
    if 'product_comparison' in st.session_state and st.session_state.product_comparison:
        render_comparison_results(st.session_state.product_comparison)


def build_comparison(brand_product_id: str, competitor_product_id: str) -> Optional[Dict]:
    """Build product comparison using comparison_utils."""
    from viraltracker.services.comparison_utils import build_product_comparison, calculate_gaps

    service = get_competitor_service()

    # Get analyses for both products
    brand_analyses = service.get_brand_analyses_by_product(UUID(brand_product_id))
    competitor_analyses = service.get_competitor_analyses_by_product(UUID(competitor_product_id))

    if not brand_analyses and not competitor_analyses:
        st.warning("No ad analyses found for either product. Run ad analysis first.")
        return None

    comparison = build_product_comparison(brand_analyses, competitor_analyses)
    comparison["gaps"] = calculate_gaps(comparison)

    return comparison


def render_comparison_results(comparison: Dict):
    """Render the comparison results."""
    st.divider()
    st.markdown("### 📊 Comparison Results")

    brand = comparison["brand"]
    competitor = comparison["competitor"]

    # Overview metrics
    col1, col2, col3, col4 = st.columns(4)
    with col1:
        st.metric("Your Analyses", brand["total_analyses"])
        st.caption(f"{brand['with_ad_structure']} with ad structure")
    with col2:
        st.metric("Their Analyses", competitor["total_analyses"])
        st.caption(f"{competitor['with_ad_structure']} with ad structure")
    with col3:
        st.metric("Your Ad Angles", len(brand["advertising_angles"]))
    with col4:
        st.metric("Their Ad Angles", len(competitor["advertising_angles"]))

    # Tabs for different comparisons
    tab1, tab2, tab3, tab4, tab5 = st.tabs([
        "Awareness Levels", "Ad Angles", "Emotional Drivers", "Objections", "Gaps & Insights"
    ])

    with tab1:
        render_awareness_comparison(brand, competitor)

    with tab2:
        render_angles_comparison(brand, competitor)

    with tab3:
        render_emotional_drivers_comparison(brand, competitor)

    with tab4:
        render_objections_comparison(brand, competitor)

    with tab5:
        render_gaps_insights(comparison.get("gaps", {}))


def render_awareness_comparison(brand: Dict, competitor: Dict):
    """Render awareness level comparison."""
    st.markdown("#### Awareness Level Distribution")
    st.caption("Which awareness stages are being targeted (Schwartz spectrum)")

    levels = ["unaware", "problem_aware", "solution_aware", "product_aware", "most_aware"]

    col1, col2 = st.columns(2)

    with col1:
        st.markdown("**Your Product**")
        for level in levels:
            count = brand["awareness_levels"].get(level, 0)
            if count > 0:
                st.write(f"• {level.replace('_', ' ').title()}: **{count}**")

    with col2:
        st.markdown("**Competitor**")
        for level in levels:
            count = competitor["awareness_levels"].get(level, 0)
            if count > 0:
                st.write(f"• {level.replace('_', ' ').title()}: **{count}**")


def render_angles_comparison(brand: Dict, competitor: Dict):
    """Render advertising angles comparison."""
    st.markdown("#### Advertising Angles Used")

    all_angles = set(brand["advertising_angles"].keys()) | set(competitor["advertising_angles"].keys())

    if not all_angles:
        st.info("No advertising angle data available. Re-analyze ads to extract this.")
        return

    # Build comparison table
    data = []
    for angle in sorted(all_angles):
        brand_count = brand["advertising_angles"].get(angle, 0)
        comp_count = competitor["advertising_angles"].get(angle, 0)
        diff = brand_count - comp_count

        if diff > 0:
            note = "✅ Your strength"
        elif diff < 0:
            note = "⚠️ They use more"
        else:
            note = "—"

        data.append({
            "Angle": angle.replace("_", " ").title(),
            "You": brand_count,
            "Them": comp_count,
            "Note": note
        })

    st.table(data)


def render_emotional_drivers_comparison(brand: Dict, competitor: Dict):
    """Render emotional drivers comparison."""
    st.markdown("#### Emotional Drivers")
    st.caption("What emotions are being leveraged in messaging")

    all_drivers = set(brand["emotional_drivers"].keys()) | set(competitor["emotional_drivers"].keys())

    if not all_drivers:
        st.info("No emotional driver data available.")
        return

    col1, col2 = st.columns(2)

    with col1:
        st.markdown("**Your Product**")
        for driver, count in sorted(brand["emotional_drivers"].items(), key=lambda x: -x[1]):
            st.write(f"• {driver.title()}: **{count}**")

    with col2:
        st.markdown("**Competitor**")
        for driver, count in sorted(competitor["emotional_drivers"].items(), key=lambda x: -x[1]):
            st.write(f"• {driver.title()}: **{count}**")


def render_objections_comparison(brand: Dict, competitor: Dict):
    """Render objections addressed comparison."""
    st.markdown("#### Objections Addressed")
    st.caption("What concerns are being preemptively handled in ads")

    all_objections = set(brand["objections"].keys()) | set(competitor["objections"].keys())

    if not all_objections:
        st.info("No objection data available.")
        return

    for objection in sorted(all_objections):
        brand_data = brand["objections"].get(objection, {"count": 0})
        comp_data = competitor["objections"].get(objection, {"count": 0})

        brand_check = "✅" if brand_data["count"] > 0 else "❌"
        comp_check = "✅" if comp_data["count"] > 0 else "❌"

        st.write(f"**{objection}** — You: {brand_check} ({brand_data['count']}) | Them: {comp_check} ({comp_data['count']})")


def render_gaps_insights(gaps: Dict):
    """Render gaps and insights."""
    st.markdown("#### 💡 Gaps & Opportunities")

    has_gaps = False

    if gaps.get("awareness_gaps"):
        has_gaps = True
        st.markdown("**Awareness Level Gaps**")
        for gap in gaps["awareness_gaps"]:
            st.warning(f"📊 {gap['insight']} (You: {gap['brand_count']}, Them: {gap['competitor_count']})")

    if gaps.get("angle_gaps"):
        has_gaps = True
        st.markdown("**Advertising Angle Gaps**")
        for gap in gaps["angle_gaps"]:
            st.warning(f"🎯 {gap['insight']}")

    if gaps.get("benefit_gaps"):
        has_gaps = True
        st.markdown("**Benefit Gaps**")
        for gap in gaps["benefit_gaps"]:
            st.warning(f"✨ {gap['insight']}")

    if gaps.get("objection_gaps"):
        has_gaps = True
        st.markdown("**Objection Handling Gaps**")
        for gap in gaps["objection_gaps"]:
            st.warning(f"🛡️ {gap['insight']}")

    if gaps.get("emotional_driver_gaps"):
        has_gaps = True
        st.markdown("**Emotional Driver Gaps**")
        for gap in gaps["emotional_driver_gaps"]:
            st.warning(f"❤️ {gap['insight']}")

    if not has_gaps:
        st.success("No significant gaps detected! Your coverage is similar to competitor.")


# =============================================================================
# Main Page
# =============================================================================

st.title("📊 Competitive Analysis")
st.caption("Compare your brand vs competitors to find gaps and opportunities")

# Brand selector (uses shared utility for cross-page persistence)
from viraltracker.ui.utils import render_brand_selector
brand_id = render_brand_selector(key="competitive_analysis_brand_selector")

if not brand_id:
    st.stop()

# Get brand name for analysis
brands = get_brands()
brand_name = next((b['name'] for b in brands if b['id'] == brand_id), "Unknown Brand")

st.divider()

# Get data
brand_personas = get_brand_personas(brand_id)
competitors = get_competitors_for_brand(brand_id)

# Render sections
render_data_status(brand_id, brand_personas, competitors)
st.divider()

render_analysis_section(brand_name, brand_id, brand_personas, competitors)

# Show results if available
if st.session_state.competitive_analysis:
    render_analysis_results(st.session_state.competitive_analysis)

# Product-level ad comparison section
st.divider()
render_product_comparison_section(brand_id, competitors)

# Help section
with st.expander("ℹ️ How Competitive Analysis Works"):
    st.markdown("""
    ### What This Tool Does

    The Competitive Analysis tool uses AI to compare your brand's positioning against competitors,
    identifying gaps, opportunities, and actionable insights.

    ### Prerequisites

    1. **Brand Personas**: Run Brand Research to generate personas for your brand
    2. **Competitor Personas**: Add competitors and run Competitor Research to generate their personas
    3. **Amazon Reviews** (optional): Scrape and analyze competitor Amazon reviews for deeper insights

    ### Analysis Components

    - **Persona Overlap**: How much do you and competitors target the same audience?
    - **Advantages**: Where you win vs where competitors win
    - **Untapped Angles**: Messaging opportunities competitors aren't using
    - **Language Gaps**: Customer language you should adopt
    - **Positioning**: Strategic recommendations for differentiation
    - **Creative Ideas**: Ad concepts to test based on competitive gaps

    ### Best Practices

    - Run analysis after completing research on 2-3 key competitors
    - Include Amazon review analysis for richer customer language data
    - Re-run analysis periodically as you gather more competitor data
    - Use the "Untapped Angles" section to generate new ad variations
    """)
