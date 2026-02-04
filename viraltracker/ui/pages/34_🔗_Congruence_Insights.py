"""
Congruence Insights Dashboard - Analyze ad-to-landing-page alignment.

This page provides:
- Overview of congruence health across all dimensions
- Drill-down by specific dimension to find weak/missing alignment
- Weekly trend tracking for congruence scores
- Visibility into ads eligible for re-analysis
"""

import streamlit as st
from datetime import datetime
from typing import Optional, List, Dict, Any
from uuid import UUID

# Page config (must be first)
st.set_page_config(
    page_title="Congruence Insights",
    page_icon="🔗",
    layout="wide"
)

# Authentication
from viraltracker.ui.auth import require_auth
require_auth()

# Session state
if "congruence_active_tab" not in st.session_state:
    st.session_state.congruence_active_tab = "Overview"


# =============================================================================
# Helper Functions
# =============================================================================

def get_supabase_client():
    """Get Supabase client."""
    from viraltracker.core.database import get_supabase_client
    return get_supabase_client()


def get_congruence_insights_service():
    """Get CongruenceInsightsService instance."""
    from viraltracker.services.ad_intelligence.congruence_insights_service import CongruenceInsightsService
    db = get_supabase_client()
    return CongruenceInsightsService(db)


# Dimension display names
DIMENSION_LABELS = {
    "awareness_alignment": "Awareness Alignment",
    "hook_headline": "Hook ↔ Headline",
    "benefits_match": "Benefits Match",
    "messaging_angle": "Messaging Angle",
    "claims_consistency": "Claims Consistency",
}

# Assessment colors
ASSESSMENT_COLORS = {
    "aligned": "#28a745",  # Green
    "weak": "#ffc107",     # Yellow
    "missing": "#dc3545",  # Red
    "unevaluated": "#6c757d",  # Gray
}


# =============================================================================
# Render Functions
# =============================================================================

def render_overview_metrics(summary: Dict[str, Any]):
    """Render top-level metrics cards."""
    col1, col2, col3, col4 = st.columns(4)

    with col1:
        st.metric(
            label="Total Analyzed",
            value=summary.get("total_analyzed", 0),
            help="Ads with congruence analysis in the last 30 days"
        )

    with col2:
        health = summary.get("overall_health")
        if health is not None:
            health_pct = f"{health * 100:.1f}%"
            # Color based on health
            if health >= 0.8:
                st.metric(label="Overall Health", value=health_pct, delta="Good")
            elif health >= 0.6:
                st.metric(label="Overall Health", value=health_pct, delta="Fair", delta_color="off")
            else:
                st.metric(label="Overall Health", value=health_pct, delta="Needs Work", delta_color="inverse")
        else:
            st.metric(label="Overall Health", value="N/A")

    with col3:
        # Find weakest dimension
        dimensions = summary.get("dimensions", {})
        weakest_dim = None
        weakest_score = float('inf')
        for dim, counts in dimensions.items():
            total = counts.get("aligned", 0) + counts.get("weak", 0) + counts.get("missing", 0)
            if total > 0:
                dim_score = counts.get("aligned", 0) / total
                if dim_score < weakest_score:
                    weakest_score = dim_score
                    weakest_dim = dim

        if weakest_dim:
            st.metric(
                label="Weakest Area",
                value=DIMENSION_LABELS.get(weakest_dim, weakest_dim),
                help=f"Dimension with lowest alignment rate ({weakest_score*100:.0f}%)"
            )
        else:
            st.metric(label="Weakest Area", value="N/A")

    with col4:
        total = summary.get("total_analyzed", 0)
        aligned = summary.get("fully_aligned_count", 0)
        if total > 0:
            aligned_pct = aligned / total * 100
            st.metric(
                label="Fully Aligned",
                value=f"{aligned_pct:.1f}%",
                help=f"{aligned} of {total} ads have all dimensions aligned"
            )
        else:
            st.metric(label="Fully Aligned", value="N/A")


def render_dimension_chart(summary: Dict[str, Any]):
    """Render stacked bar chart for dimension breakdown."""
    import pandas as pd

    dimensions = summary.get("dimensions", {})
    if not dimensions:
        st.info("No dimension data available.")
        return

    # Prepare data for pandas DataFrame
    data = []
    for dim in DIMENSION_LABELS.keys():
        if dim in dimensions:
            counts = dimensions[dim]
            data.append({
                "Dimension": DIMENSION_LABELS[dim],
                "Aligned": counts.get("aligned", 0),
                "Weak": counts.get("weak", 0),
                "Missing": counts.get("missing", 0),
            })

    if not data:
        st.info("No dimension data to display.")
        return

    df = pd.DataFrame(data)
    df = df.set_index("Dimension")

    # Display using Streamlit's native bar chart
    st.subheader("Congruence by Dimension")
    st.bar_chart(df, color=["#28a745", "#ffc107", "#dc3545"])

    # Also show as table for exact numbers
    with st.expander("View exact counts"):
        st.dataframe(df, use_container_width=True)


def render_improvement_suggestions(brand_id: str):
    """Render aggregated improvement suggestions."""
    st.subheader("Top Improvement Suggestions")

    service = get_congruence_insights_service()
    suggestions = service.get_improvement_suggestions(UUID(brand_id), limit=10)

    if not suggestions:
        st.info("No improvement suggestions available yet. Run congruence analysis on more ads.")
        return

    for i, item in enumerate(suggestions, 1):
        with st.expander(f"**{i}. {item['suggestion'][:100]}{'...' if len(item['suggestion']) > 100 else ''}** ({item['frequency']} ads)"):
            st.write(f"**Full Suggestion:** {item['suggestion']}")
            st.write(f"**Dimensions:** {', '.join(DIMENSION_LABELS.get(d, d) for d in item.get('dimensions', []))}")
            st.write(f"**Sample Ads:** {', '.join(item.get('sample_ad_ids', [])[:3])}")


def render_by_dimension_tab(brand_id: str):
    """Render the By Dimension tab with drill-down."""
    st.subheader("Drill Down by Dimension")

    # Dimension selector
    dimension_options = list(DIMENSION_LABELS.keys())
    dimension_labels = list(DIMENSION_LABELS.values())

    selected_idx = st.selectbox(
        "Select Dimension",
        range(len(dimension_options)),
        format_func=lambda i: dimension_labels[i],
        key="dimension_selector"
    )
    selected_dimension = dimension_options[selected_idx]

    # Get weak ads
    service = get_congruence_insights_service()
    weak_ads = service.get_weak_ads_by_dimension(
        UUID(brand_id),
        dimension=selected_dimension,
        limit=20
    )

    if not weak_ads:
        st.success(f"No weak or missing alignment found for {DIMENSION_LABELS[selected_dimension]}!")
        return

    st.write(f"Found **{len(weak_ads)}** ads with weak/missing {DIMENSION_LABELS[selected_dimension]}")

    # Display table
    import pandas as pd

    df_data = []
    for ad in weak_ads:
        df_data.append({
            "Ad ID": ad.get("meta_ad_id", "")[:20] + "...",
            "Assessment": ad.get("assessment", "").title(),
            "Issue": ad.get("explanation", "")[:80] + ("..." if len(ad.get("explanation", "")) > 80 else ""),
            "Score": ad.get("congruence_score"),
        })

    df = pd.DataFrame(df_data)
    st.dataframe(df, use_container_width=True, hide_index=True)

    # Show detailed suggestions
    st.subheader("Suggestions for Selected Ads")
    for ad in weak_ads[:5]:
        suggestion = ad.get("suggestion")
        if suggestion:
            with st.expander(f"Ad: {ad.get('meta_ad_id', '')[:30]}..."):
                st.write(f"**Assessment:** {ad.get('assessment', '').title()}")
                st.write(f"**Issue:** {ad.get('explanation', '')}")
                st.write(f"**Suggestion:** {suggestion}")


def render_trends_tab(brand_id: str):
    """Render weekly trend chart."""
    st.subheader("Congruence Score Trends")

    service = get_congruence_insights_service()
    trends = service.get_congruence_trends(UUID(brand_id), lookback_weeks=8)

    if not trends:
        st.info("Not enough historical data for trends. Check back after running more analysis.")
        return

    import pandas as pd

    # Prepare data
    df = pd.DataFrame(trends)
    df = df.rename(columns={
        "week_start": "Week",
        "avg_score": "Avg Score",
        "ad_count": "Ads Analyzed",
        "aligned_pct": "% Fully Aligned"
    })
    df = df.set_index("Week")

    # Show line chart for score trend
    st.write("**Average Congruence Score**")
    st.line_chart(df[["Avg Score"]], color=["#007bff"])

    # Show bar chart for aligned percentage
    st.write("**% Fully Aligned**")
    st.bar_chart(df[["% Fully Aligned"]], color=["#28a745"])

    # Show summary table
    st.write("**Weekly Summary**")
    df_display = df.reset_index()
    st.dataframe(df_display, use_container_width=True, hide_index=True)


def render_reanalysis_tab(brand_id: str):
    """Render re-analysis eligibility and info."""
    st.subheader("Re-Analysis Status")

    service = get_congruence_insights_service()
    eligible = service.get_eligible_for_reanalysis(UUID(brand_id), limit=10)

    col1, col2 = st.columns(2)

    with col1:
        st.metric(
            label="Ads Eligible for Re-Analysis",
            value=len(eligible),
            help="Ads with video analysis + LP data but missing congruence components"
        )

    with col2:
        st.info(
            "Re-analysis runs automatically via the **Weekly Congruence Re-analysis** "
            "scheduled job, or you can trigger it manually from the Scheduler page."
        )

    if eligible:
        st.write("**Sample Eligible Ads:**")

        import pandas as pd
        df_data = []
        for ad in eligible[:10]:
            df_data.append({
                "Ad ID": ad.get("meta_ad_id", "")[:30] + "...",
                "Classified": ad.get("classified_at", "")[:10] if ad.get("classified_at") else "N/A",
                "Has Video Analysis": "Yes" if ad.get("video_analysis_id") else "No",
                "Has LP": "Yes" if ad.get("landing_page_id") else "No",
            })

        df = pd.DataFrame(df_data)
        st.dataframe(df, use_container_width=True, hide_index=True)

    # Show scheduled job info
    st.subheader("Scheduled Re-Analysis Job")
    st.markdown("""
    To set up automatic re-analysis, create a scheduled job with:

    ```sql
    INSERT INTO scheduled_jobs (
        name, job_type, brand_id, schedule_type,
        cron_expression, status, parameters, next_run_at
    ) VALUES (
        'Weekly Congruence Re-analysis',
        'congruence_reanalysis',
        NULL,  -- all brands, or specify a brand_id
        'recurring',
        '0 3 * * 0',  -- Sunday 3am
        'active',
        '{"batch_size": 100, "max_gemini_calls": 50}',
        NOW()
    );
    ```

    **Parameters:**
    - `batch_size`: Max ads to process per run (default: 50)
    - `max_gemini_calls`: Max Gemini API calls per run (default: 20)
    - `brand_id`: Optional specific brand to process
    """)


# =============================================================================
# Main Page
# =============================================================================

st.title("Congruence Insights")
st.markdown("Analyze alignment between your ad creatives, copy, and landing pages across 5 dimensions.")

# Brand selector
from viraltracker.ui.utils import render_brand_selector
brand_id = render_brand_selector(key="congruence_insights_brand_selector")

if not brand_id:
    st.stop()

# Get summary data
service = get_congruence_insights_service()
summary = service.get_dimension_summary(UUID(brand_id), date_range_days=30)

# Check if we have data
if summary.get("total_analyzed", 0) == 0:
    st.warning(
        "No congruence data available for this brand. "
        "Run ad classification with video analysis and landing page data to populate this dashboard."
    )
    st.info(
        "Congruence analysis requires:\n"
        "1. Video analysis (deep video classification)\n"
        "2. Landing page data (scraped LP)\n"
        "3. Classification run with congruence analyzer enabled"
    )
    st.stop()

# Tabs
tab1, tab2, tab3, tab4 = st.tabs(["Overview", "By Dimension", "Trends", "Re-Analysis"])

with tab1:
    render_overview_metrics(summary)
    st.divider()
    render_dimension_chart(summary)
    st.divider()
    render_improvement_suggestions(brand_id)

with tab2:
    render_by_dimension_tab(brand_id)

with tab3:
    render_trends_tab(brand_id)

with tab4:
    render_reanalysis_tab(brand_id)
