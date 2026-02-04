"""
Hook Analysis Dashboard - Analyze which hooks drive the best performance.

This page provides:
- Overview of hook performance across video ads
- Quadrant analysis (Hook Rate vs ROAS) for actionable insights
- Breakdown by hook type and visual type
- Hooks grouped by landing page
- Head-to-head hook comparison
"""

import streamlit as st
from datetime import datetime
from typing import Optional, List, Dict, Any
from uuid import UUID

# Page config (must be first)
st.set_page_config(
    page_title="Hook Analysis",
    page_icon="🎣",
    layout="wide"
)

# Authentication
from viraltracker.ui.auth import require_auth
require_auth()


# =============================================================================
# Helper Functions
# =============================================================================

def get_supabase_client():
    """Get Supabase client."""
    from viraltracker.core.database import get_supabase_client
    return get_supabase_client()


@st.cache_resource
def get_hook_service():
    """Get HookAnalysisService instance."""
    from viraltracker.services.ad_intelligence.hook_analysis_service import HookAnalysisService
    db = get_supabase_client()
    return HookAnalysisService(db)


def format_currency(value: float) -> str:
    """Format a value as currency."""
    if value is None:
        return "N/A"
    return f"${value:,.2f}"


def format_percent(value: float, decimals: int = 1) -> str:
    """Format a value as percentage."""
    if value is None:
        return "N/A"
    return f"{value * 100:.{decimals}f}%"


def format_roas(value: float) -> str:
    """Format ROAS value."""
    if value is None:
        return "N/A"
    return f"{value:.2f}x"


def truncate_text(text: str, max_length: int = 50) -> str:
    """Truncate text with ellipsis."""
    if not text:
        return ""
    if len(text) <= max_length:
        return text
    return text[:max_length] + "..."


# =============================================================================
# Render Functions - Overview Tab
# =============================================================================

def render_overview_metrics(hooks: List[Dict], insights: Dict):
    """Render top-level metrics cards."""
    col1, col2, col3, col4 = st.columns(4)

    total_hooks = len(hooks)
    total_spend = sum(h.get("total_spend", 0) for h in hooks)

    # Find best ROAS hook
    best_roas_hook = max(hooks, key=lambda h: h.get("avg_roas", 0)) if hooks else None
    best_roas = best_roas_hook.get("avg_roas", 0) if best_roas_hook else 0

    # Find best hook rate hook
    best_hr_hook = max(hooks, key=lambda h: h.get("avg_hook_rate", 0)) if hooks else None
    best_hr = best_hr_hook.get("avg_hook_rate", 0) if best_hr_hook else 0

    with col1:
        st.metric(
            label="Total Hooks Analyzed",
            value=total_hooks,
            help="Unique hooks with sufficient spend in the date range"
        )

    with col2:
        st.metric(
            label="Total Spend",
            value=format_currency(total_spend),
            help="Total spend on video ads with analyzed hooks"
        )

    with col3:
        st.metric(
            label="Best ROAS Hook",
            value=format_roas(best_roas),
            help=f"Type: {best_roas_hook.get('hook_type', 'N/A')}" if best_roas_hook else "N/A"
        )

    with col4:
        st.metric(
            label="Best Hook Rate",
            value=format_percent(best_hr),
            help=f"Type: {best_hr_hook.get('hook_type', 'N/A')}" if best_hr_hook else "N/A"
        )


def render_top_hooks_table(hooks: List[Dict], sort_by: str):
    """Render sortable table of top hooks."""
    import pandas as pd

    if not hooks:
        st.info("No hooks found with the current filters.")
        return

    # Prepare data for DataFrame
    data = []
    for hook in hooks[:20]:  # Limit to top 20
        data.append({
            "Type": hook.get("hook_type", "N/A"),
            "Visual": hook.get("hook_visual_type", "N/A"),
            "Spoken": truncate_text(hook.get("hook_transcript_spoken", ""), 60),
            "Ads": hook.get("ad_count", 0),
            "Spend": hook.get("total_spend", 0),
            "ROAS": hook.get("avg_roas", 0),
            "Hook Rate": hook.get("avg_hook_rate", 0),
            "CTR": hook.get("avg_ctr", 0),
            "Fingerprint": hook.get("hook_fingerprint", "")[:16] + "...",
        })

    df = pd.DataFrame(data)

    # Format columns for display
    df_display = df.copy()
    df_display["Spend"] = df_display["Spend"].apply(lambda x: f"${x:,.0f}")
    df_display["ROAS"] = df_display["ROAS"].apply(lambda x: f"{x:.2f}x")
    df_display["Hook Rate"] = df_display["Hook Rate"].apply(lambda x: f"{x*100:.1f}%")
    df_display["CTR"] = df_display["CTR"].apply(lambda x: f"{x*100:.2f}%")

    st.subheader("Top Performing Hooks")
    st.dataframe(df_display, use_container_width=True, hide_index=True)


def render_insights_cards(insights: Dict):
    """Render insight recommendation cards."""
    recommendations = insights.get("recommendations", [])

    if not recommendations:
        st.info("Not enough data to generate insights. Run more video ads to see recommendations.")
        return

    st.subheader("Actionable Insights")

    for i, rec in enumerate(recommendations[:5]):
        # Determine card type based on content
        if rec.startswith("SCALE"):
            st.success(rec)
        elif rec.startswith("FIX") or rec.startswith("KILL"):
            st.warning(rec)
        else:
            st.info(rec)


# =============================================================================
# Render Functions - Quadrant Tab
# =============================================================================

def render_quadrant_analysis(brand_id: str, date_range_days: int, min_spend: float):
    """Render quadrant analysis (Hook Rate vs ROAS)."""
    import pandas as pd

    service = get_hook_service()

    # Threshold sliders
    col1, col2 = st.columns(2)
    with col1:
        hook_rate_threshold = st.slider(
            "Hook Rate Threshold (%)",
            min_value=10,
            max_value=50,
            value=25,
            step=5,
            help="Hooks above this are considered 'high engagement'"
        ) / 100
    with col2:
        roas_threshold = st.slider(
            "ROAS Threshold",
            min_value=0.5,
            max_value=3.0,
            value=1.0,
            step=0.1,
            help="Hooks above this are considered 'profitable'"
        )

    # Get quadrant data
    quadrants = service.get_hooks_by_quadrant(
        brand_id=UUID(brand_id),
        date_range_days=date_range_days,
        min_spend=min_spend,
        hook_rate_threshold=hook_rate_threshold,
        roas_threshold=roas_threshold
    )

    # Quadrant summary metrics
    col1, col2, col3, col4 = st.columns(4)
    with col1:
        st.metric("Winners", len(quadrants.get("winners", [])), help="High hook rate + High ROAS")
    with col2:
        st.metric("Hidden Gems", len(quadrants.get("hidden_gems", [])), help="Low hook rate + High ROAS")
    with col3:
        st.metric("Engaging, Not Converting", len(quadrants.get("engaging_not_converting", [])), help="High hook rate + Low ROAS")
    with col4:
        st.metric("Losers", len(quadrants.get("losers", [])), help="Low hook rate + Low ROAS")

    st.divider()

    # Render each quadrant
    _render_quadrant_section(
        "Winners",
        quadrants.get("winners", []),
        "#28a745",
        "SCALE - These hooks have both high engagement and high conversion. Increase budget on these."
    )

    _render_quadrant_section(
        "Hidden Gems",
        quadrants.get("hidden_gems", []),
        "#007bff",
        "INVESTIGATE - Good ROAS but low engagement. Why aren't more people watching? Consider hook placement or targeting."
    )

    _render_quadrant_section(
        "Engaging but Not Converting",
        quadrants.get("engaging_not_converting", []),
        "#ffc107",
        "FIX DOWNSTREAM - The hook is working, but something after the hook is broken. Check landing page, offer, or video body."
    )

    _render_quadrant_section(
        "Losers",
        quadrants.get("losers", []),
        "#dc3545",
        "KILL - Low engagement and low conversion. Consider pausing these ads and replacing with new creative."
    )


def _render_quadrant_section(title: str, hooks: List[Dict], color: str, description: str):
    """Render a single quadrant section."""
    import pandas as pd

    # Emoji mapping
    emoji_map = {
        "Winners": "🎯",
        "Hidden Gems": "🔍",
        "Engaging but Not Converting": "⚠️",
        "Losers": "💀"
    }

    with st.expander(f"{emoji_map.get(title, '')} **{title}** ({len(hooks)} hooks)", expanded=title == "Winners"):
        st.caption(description)

        if not hooks:
            st.info(f"No hooks in this quadrant.")
            return

        # Show table
        data = []
        for hook in hooks[:10]:
            data.append({
                "Type": hook.get("hook_type", "N/A"),
                "Visual": hook.get("hook_visual_type", "N/A"),
                "Spoken": truncate_text(hook.get("hook_transcript_spoken", ""), 50),
                "Spend": f"${hook.get('total_spend', 0):,.0f}",
                "ROAS": f"{hook.get('avg_roas', 0):.2f}x",
                "Hook Rate": f"{hook.get('avg_hook_rate', 0)*100:.1f}%",
                "Ads": hook.get("ad_count", 0),
            })

        df = pd.DataFrame(data)
        st.dataframe(df, use_container_width=True, hide_index=True)


# =============================================================================
# Render Functions - By Type Tab
# =============================================================================

def render_by_type_analysis(brand_id: str, date_range_days: int):
    """Render performance breakdown by hook type."""
    import pandas as pd

    service = get_hook_service()
    type_data = service.get_hooks_by_type(UUID(brand_id), date_range_days=date_range_days)

    if not type_data:
        st.info("No hook type data available. Run video analysis on more ads.")
        return

    st.subheader("Performance by Hook Type")

    # Prepare data for chart
    chart_data = []
    for t in type_data:
        chart_data.append({
            "Hook Type": t.get("hook_type", "N/A"),
            "Avg ROAS": t.get("avg_roas", 0),
            "Avg Hook Rate": t.get("avg_hook_rate", 0) * 100,  # Convert to percentage
            "Total Spend": t.get("total_spend", 0),
        })

    df = pd.DataFrame(chart_data)
    df = df.set_index("Hook Type")

    # Show ROAS by type
    st.write("**Average ROAS by Hook Type**")
    st.bar_chart(df[["Avg ROAS"]], color=["#007bff"])

    # Show hook rate by type
    st.write("**Average Hook Rate (%) by Hook Type**")
    st.bar_chart(df[["Avg Hook Rate"]], color=["#28a745"])

    # Detailed table
    st.write("**Detailed Metrics**")
    table_data = []
    for t in type_data:
        table_data.append({
            "Hook Type": t.get("hook_type", "N/A"),
            "Ad Count": t.get("ad_count", 0),
            "Total Spend": f"${t.get('total_spend', 0):,.0f}",
            "Avg Spend/Ad": f"${t.get('avg_spend_per_ad', 0):,.0f}",
            "Avg ROAS": f"{t.get('avg_roas', 0):.2f}x",
            "Avg Hook Rate": f"{t.get('avg_hook_rate', 0)*100:.1f}%",
            "Avg CTR": f"{t.get('avg_ctr', 0)*100:.2f}%",
        })

    st.dataframe(pd.DataFrame(table_data), use_container_width=True, hide_index=True)


# =============================================================================
# Render Functions - By Visual Tab
# =============================================================================

def render_by_visual_analysis(brand_id: str, date_range_days: int):
    """Render performance breakdown by visual hook type."""
    import pandas as pd

    service = get_hook_service()
    visual_data = service.get_hooks_by_visual_type(UUID(brand_id), date_range_days=date_range_days)

    if not visual_data:
        st.info("No visual type data available. Run video analysis on more ads.")
        return

    st.subheader("Performance by Visual Hook Type")

    # Prepare chart data
    chart_data = []
    for v in visual_data:
        chart_data.append({
            "Visual Type": v.get("hook_visual_type", "N/A"),
            "Avg ROAS": v.get("avg_roas", 0),
            "Avg Hook Rate": v.get("avg_hook_rate", 0) * 100,
        })

    df = pd.DataFrame(chart_data)
    df = df.set_index("Visual Type")

    # Show ROAS by visual type
    st.write("**Average ROAS by Visual Type**")
    st.bar_chart(df[["Avg ROAS"]], color=["#007bff"])

    # Detailed table
    st.write("**Detailed Metrics**")
    table_data = []
    for v in visual_data:
        elements = v.get("common_visual_elements", [])
        elements_str = ", ".join(elements[:3]) if elements else "N/A"

        table_data.append({
            "Visual Type": v.get("hook_visual_type", "N/A"),
            "Ad Count": v.get("ad_count", 0),
            "Total Spend": f"${v.get('total_spend', 0):,.0f}",
            "Avg ROAS": f"{v.get('avg_roas', 0):.2f}x",
            "Avg Hook Rate": f"{v.get('avg_hook_rate', 0)*100:.1f}%",
            "Common Elements": elements_str,
        })

    st.dataframe(pd.DataFrame(table_data), use_container_width=True, hide_index=True)

    # Visual elements breakdown
    st.subheader("Most Common Visual Elements")
    all_elements: Dict[str, int] = {}
    for v in visual_data:
        for elem in v.get("common_visual_elements", []):
            all_elements[elem] = all_elements.get(elem, 0) + 1

    if all_elements:
        sorted_elements = sorted(all_elements.items(), key=lambda x: x[1], reverse=True)
        for elem, count in sorted_elements[:10]:
            st.write(f"- **{elem}**: {count} visual types")
    else:
        st.info("No visual elements data available.")


# =============================================================================
# Render Functions - By Landing Page Tab
# =============================================================================

def render_by_landing_page(brand_id: str, date_range_days: int):
    """Render hooks grouped by landing page."""
    import pandas as pd

    service = get_hook_service()
    lp_data = service.get_hooks_by_landing_page(
        UUID(brand_id),
        date_range_days=date_range_days,
        limit=20
    )

    if not lp_data:
        st.info("No landing page data available. Ensure ads have classified landing pages.")
        return

    st.subheader("Hooks by Landing Page")

    # LP selector
    lp_options = ["All Landing Pages"] + [
        f"{lp.get('landing_page_title', 'Untitled')[:40]} ({lp.get('hook_count', 0)} hooks)"
        for lp in lp_data
    ]
    selected_lp_idx = st.selectbox(
        "Filter by Landing Page",
        range(len(lp_options)),
        format_func=lambda i: lp_options[i],
        key="lp_selector"
    )

    # Filter data if specific LP selected
    if selected_lp_idx > 0:
        lp_data = [lp_data[selected_lp_idx - 1]]

    # Summary table
    table_data = []
    for lp in lp_data:
        table_data.append({
            "Landing Page": truncate_text(lp.get("landing_page_title") or lp.get("landing_page_url", "N/A"), 40),
            "Hook Count": lp.get("hook_count", 0),
            "Total Spend": f"${lp.get('total_spend', 0):,.0f}",
            "Avg ROAS": f"{lp.get('avg_roas', 0):.2f}x",
            "Best Hook": truncate_text(lp.get("best_hook_fingerprint", "")[:12], 12),
        })

    st.dataframe(pd.DataFrame(table_data), use_container_width=True, hide_index=True)

    # Expandable details for each LP
    st.subheader("Landing Page Details")
    for lp in lp_data[:10]:
        lp_title = lp.get("landing_page_title") or lp.get("landing_page_url", "Unknown")
        with st.expander(f"**{truncate_text(lp_title, 50)}** - {lp.get('hook_count', 0)} hooks, ${lp.get('total_spend', 0):,.0f} spend"):
            st.write(f"**URL:** {lp.get('landing_page_url', 'N/A')}")
            st.write(f"**Total Spend:** {format_currency(lp.get('total_spend', 0))}")
            st.write(f"**Avg ROAS:** {format_roas(lp.get('avg_roas', 0))}")

            hooks = lp.get("hooks", [])
            if hooks:
                st.write("**Hooks used with this LP:**")
                hook_data = []
                for h in hooks[:10]:
                    hook_data.append({
                        "Type": h.get("type", "N/A"),
                        "Visual": h.get("visual_type", "N/A"),
                        "Spend": f"${h.get('spend', 0):,.0f}",
                        "ROAS": f"{h.get('roas', 0):.2f}x",
                    })
                st.dataframe(pd.DataFrame(hook_data), use_container_width=True, hide_index=True)

            # Highlight best/worst if LP has multiple hooks
            if lp.get("best_hook_fingerprint") and len(hooks) > 1:
                st.success(f"Best performing hook: {lp.get('best_hook_fingerprint', '')[:16]}...")
            if lp.get("worst_hook_fingerprint") and len(hooks) > 1:
                st.warning(f"Worst performing hook: {lp.get('worst_hook_fingerprint', '')[:16]}...")


# =============================================================================
# Render Functions - Compare Tab
# =============================================================================

def render_hook_comparison(brand_id: str, hooks: List[Dict]):
    """Render head-to-head hook comparison."""
    import pandas as pd

    service = get_hook_service()

    if len(hooks) < 2:
        st.info("Need at least 2 hooks to compare. Adjust filters to include more hooks.")
        return

    st.subheader("Compare Two Hooks")

    # Create dropdown options
    hook_options = [
        f"{h.get('hook_type', 'N/A')} - {truncate_text(h.get('hook_transcript_spoken', ''), 40)} (${h.get('total_spend', 0):,.0f})"
        for h in hooks
    ]

    col1, col2 = st.columns(2)
    with col1:
        hook_a_idx = st.selectbox(
            "Select Hook A",
            range(len(hook_options)),
            format_func=lambda i: hook_options[i],
            key="hook_a_selector"
        )
    with col2:
        # Default to second hook if available
        default_b = 1 if len(hooks) > 1 else 0
        hook_b_idx = st.selectbox(
            "Select Hook B",
            range(len(hook_options)),
            index=default_b,
            format_func=lambda i: hook_options[i],
            key="hook_b_selector"
        )

    if hook_a_idx == hook_b_idx:
        st.warning("Please select two different hooks to compare.")
        return

    hook_a = hooks[hook_a_idx]
    hook_b = hooks[hook_b_idx]

    # Get comparison data
    comparison = service.get_hook_comparison(
        brand_id=UUID(brand_id),
        fingerprint_a=hook_a["hook_fingerprint"],
        fingerprint_b=hook_b["hook_fingerprint"]
    )

    if comparison.get("error"):
        st.error(f"Comparison error: {comparison.get('error')}")
        return

    # Side-by-side display
    col1, col2 = st.columns(2)

    with col1:
        st.subheader("Hook A")
        _render_hook_card(comparison.get("hook_a", {}), "A", comparison.get("winner_by", {}))

    with col2:
        st.subheader("Hook B")
        _render_hook_card(comparison.get("hook_b", {}), "B", comparison.get("winner_by", {}))

    # Statistical confidence
    confidence = comparison.get("statistical_confidence", "low")
    if confidence == "high":
        st.success(f"**Statistical Confidence:** High - Results are reliable")
    elif confidence == "medium":
        st.info(f"**Statistical Confidence:** Medium - Results are reasonably reliable")
    else:
        st.warning(f"**Statistical Confidence:** Low - Need more data for reliable comparison")

    # Recommendation
    if comparison.get("recommendation"):
        st.info(f"**Recommendation:** {comparison.get('recommendation')}")


def _render_hook_card(hook_data: Dict, label: str, winners: Dict):
    """Render a single hook card for comparison."""
    metrics = hook_data.get("metrics", {})

    # Hook details
    st.write(f"**Type:** {hook_data.get('type', 'N/A')}")
    st.write(f"**Visual Type:** {hook_data.get('visual_type', 'N/A')}")

    spoken = hook_data.get("transcript_spoken", "")
    if spoken:
        st.write(f"**Spoken:** \"{truncate_text(spoken, 100)}\"")

    st.write(f"**Ad Count:** {hook_data.get('ad_count', 0)}")
    st.write(f"**Consistency:** {hook_data.get('consistency', 'N/A')}")

    st.divider()

    # Metrics with winner badges
    spend = metrics.get("total_spend", 0)
    roas = metrics.get("avg_roas", 0)
    hook_rate = metrics.get("avg_hook_rate", 0)

    # Spend
    spend_winner = winners.get("spend") == label
    spend_text = format_currency(spend)
    if spend_winner:
        st.success(f"**Spend:** {spend_text} (Winner)")
    else:
        st.write(f"**Spend:** {spend_text}")

    # ROAS
    roas_winner = winners.get("roas") == label
    roas_text = format_roas(roas)
    if roas_winner:
        st.success(f"**ROAS:** {roas_text} (Winner)")
    else:
        st.write(f"**ROAS:** {roas_text}")

    # Hook Rate
    hr_winner = winners.get("hook_rate") == label
    hr_text = format_percent(hook_rate)
    if hr_winner:
        st.success(f"**Hook Rate:** {hr_text} (Winner)")
    else:
        st.write(f"**Hook Rate:** {hr_text}")


# =============================================================================
# Main Page
# =============================================================================

st.title("Hook Analysis")
st.markdown("Analyze which hooks drive the best performance across your video ads.")

# Brand selector
from viraltracker.ui.utils import render_brand_selector
brand_id = render_brand_selector(key="hook_analysis_brand_selector")

if not brand_id:
    st.stop()

# Global filters row
st.subheader("Filters")
col1, col2, col3 = st.columns(3)

with col1:
    date_range = st.selectbox(
        "Date Range",
        [7, 14, 30, 90],
        index=2,
        format_func=lambda x: f"Last {x} days",
        key="hook_date_range"
    )

with col2:
    min_spend = st.number_input(
        "Min Spend ($)",
        value=0,
        min_value=0,
        step=10,
        help="Only include hooks with at least this much total spend",
        key="hook_min_spend"
    )

with col3:
    sort_by = st.selectbox(
        "Sort By",
        ["roas", "hook_rate", "spend", "ctr"],
        format_func=lambda x: {
            "roas": "ROAS",
            "hook_rate": "Hook Rate",
            "spend": "Spend",
            "ctr": "CTR"
        }.get(x, x),
        key="hook_sort_by"
    )

# Get hook data
service = get_hook_service()

# Fetch top hooks (used by multiple tabs)
hooks = service.get_top_hooks_by_fingerprint(
    brand_id=UUID(brand_id),
    limit=50,
    min_spend=float(min_spend),
    date_range_days=date_range,
    sort_by=sort_by
)

# Check if we have data
if not hooks:
    st.warning(
        "No hook data available for this brand with the current filters. "
        "Try reducing the minimum spend or expanding the date range."
    )
    st.info(
        "Hook analysis requires:\n"
        "1. Video ads analyzed with deep video classification\n"
        "2. Hook fingerprints extracted from video analysis\n"
        "3. Performance data from Meta Ads"
    )
    st.stop()

# Get insights
insights = service.get_hook_insights(
    brand_id=UUID(brand_id),
    date_range_days=date_range
)

# Tabs
tab1, tab2, tab3, tab4, tab5, tab6 = st.tabs([
    "Overview",
    "Quadrant",
    "By Type",
    "By Visual",
    "By Landing Page",
    "Compare"
])

with tab1:
    render_overview_metrics(hooks, insights)
    st.divider()
    render_top_hooks_table(hooks, sort_by)
    st.divider()
    render_insights_cards(insights)

with tab2:
    render_quadrant_analysis(brand_id, date_range, float(min_spend))

with tab3:
    render_by_type_analysis(brand_id, date_range)

with tab4:
    render_by_visual_analysis(brand_id, date_range)

with tab5:
    render_by_landing_page(brand_id, date_range)

with tab6:
    render_hook_comparison(brand_id, hooks)
