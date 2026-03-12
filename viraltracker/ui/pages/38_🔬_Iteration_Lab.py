"""
Iteration Lab - Find mixed-signal ads and analyze winner DNA.

Tab 1: Find Opportunities - Scan for ads with exploitable mixed signals
Tab 2: Analyze Winners - Decompose what makes winning ads work
"""

import asyncio
import json
import streamlit as st
from typing import Dict, List, Optional

st.set_page_config(
    page_title="Iteration Lab",
    page_icon="🔬",
    layout="wide"
)

from viraltracker.ui.auth import require_auth
require_auth()
from viraltracker.ui.utils import require_feature
require_feature("iteration_lab", "Iteration Lab")


# ============================================
# SERVICE INITIALIZATION
# ============================================

def get_supabase_client():
    """Get Supabase client."""
    from viraltracker.core.database import get_supabase_client
    return get_supabase_client()


def get_detector():
    """Get IterationOpportunityDetector."""
    from viraltracker.services.iteration_opportunity_detector import IterationOpportunityDetector
    return IterationOpportunityDetector(get_supabase_client())


def get_dna_analyzer():
    """Get WinnerDNAAnalyzer with Gemini service."""
    from viraltracker.services.winner_dna_analyzer import WinnerDNAAnalyzer
    gemini = _get_gemini_service()
    return WinnerDNAAnalyzer(get_supabase_client(), gemini)


def _get_gemini_service():
    """Get GeminiService with usage tracking."""
    try:
        from viraltracker.services.gemini_service import GeminiService
        from viraltracker.ui.utils import setup_tracking_context
        service = GeminiService()
        setup_tracking_context(service)
        return service
    except Exception as e:
        import logging
        logging.getLogger(__name__).warning(f"GeminiService not available: {e}")
        return None


def get_products_for_brand(brand_id: str) -> List[Dict]:
    """Get products for a brand."""
    try:
        result = get_supabase_client().table("products").select("id, name").eq("brand_id", brand_id).execute()
        return result.data or []
    except Exception as e:
        import logging
        logging.getLogger(__name__).warning(f"Failed to load products for brand {brand_id}: {e}")
        return []


# ============================================
# SESSION STATE
# ============================================

if "iter_opportunities" not in st.session_state:
    st.session_state.iter_opportunities = None
if "iter_scan_done" not in st.session_state:
    st.session_state.iter_scan_done = False
if "iter_category_filter" not in st.session_state:
    st.session_state.iter_category_filter = None
if "iter_cross_winner_result" not in st.session_state:
    st.session_state.iter_cross_winner_result = None
if "iter_per_winner_result" not in st.session_state:
    st.session_state.iter_per_winner_result = None
if "iter_action_confirm" not in st.session_state:
    st.session_state.iter_action_confirm = None


# ============================================
# CONSTANTS
# ============================================

CONFIDENCE_LABELS = {
    (0.7, 1.0): ("Strong Signal", "green"),
    (0.5, 0.7): ("Good Signal", "orange"),
    (0.0, 0.5): ("Moderate Signal", "gray"),
}

CATEGORY_ICONS = {
    "visual": "🎨",
    "messaging": "💬",
    "pacing": "⏱️",
    "budget": "💰",
    "cross_size": "📐",
    "anti_fatigue": "🔄",
}

METRIC_LABELS = {
    "roas": "ROAS",
    "ctr": "CTR",
    "cpc": "CPC",
    "hook_rate": "Hook Rate",
    "hold_rate": "Hold Rate",
    "impressions": "Impressions",
    "reward_score": "Reward Score",
    "canvas_sizes_tested": "Sizes Tested",
    "first_half_ctr": "Early CTR",
    "ctr_decline_pct": "CTR Decline",
}


def _confidence_label(conf: float) -> tuple:
    """Get human-readable confidence label and color."""
    for (lo, hi), (label, color) in CONFIDENCE_LABELS.items():
        if lo <= conf <= hi:
            return label, color
    return "Moderate Signal", "gray"


def _format_metric(metric: str, value: float) -> str:
    """Format a metric value for display."""
    if metric in ("roas",):
        return f"{value:.1f}x"
    elif metric in ("ctr", "hook_rate", "hold_rate", "conversion_rate"):
        return f"{value:.2f}%"
    elif metric in ("cpc", "cpa"):
        return f"${value:.2f}"
    elif metric in ("impressions",):
        return f"{value:,.0f}"
    elif metric in ("ctr_decline_pct",):
        return f"-{value:.0%}"
    else:
        return f"{value:.3f}"


def _is_video_ad(classification: dict) -> bool:
    """Check if an ad is a video based on classification."""
    fmt = classification.get("creative_format", "")
    return fmt.startswith("video_") if fmt else False


# ============================================
# TAB 1: FIND OPPORTUNITIES
# ============================================

def render_opportunities_tab(brand_id: str, product_id: Optional[str], org_id: str):
    """Render the Find Opportunities tab."""

    # Track record (conditional)
    detector = get_detector()
    track_record = detector.get_iteration_track_record(brand_id, org_id)
    if track_record.get("matured", 0) > 0:
        with st.container():
            matured = track_record["matured"]
            outperformed = track_record["outperformed"]
            avg_imp = track_record["avg_improvement"]
            st.markdown(
                f"**Iteration Track Record**: Last {matured} iterations: "
                f"**{outperformed}/{matured}** outperformed parent. "
                f"Avg improvement: **{avg_imp:+.0%}**"
            )
        st.divider()

    # Scan controls
    col1, col2 = st.columns([3, 1])
    with col1:
        if st.button("🔍 Scan for Opportunities", use_container_width=True, key="iter_scan_btn"):
            _run_scan(brand_id, org_id)
    with col2:
        days_back = st.selectbox(
            "Days back", [14, 30, 60, 90], index=1, key="iter_days_back"
        )

    # Show results
    opportunities = st.session_state.iter_opportunities
    if opportunities is None and not st.session_state.iter_scan_done:
        # Load from DB
        stored = detector.get_opportunities(brand_id, org_id)
        if stored:
            opportunities = stored
            st.session_state.iter_opportunities = stored
            st.session_state.iter_scan_done = True

    if not opportunities:
        if st.session_state.iter_scan_done:
            st.info("No opportunities found. Ads need at least 7 days of data and 1,000+ impressions.")
        else:
            st.info(
                "Iteration Lab finds ads that are *almost* great and helps you make them better. "
                "Click **Scan** to find ads with strong metrics in one area but weak in another."
            )
        return

    # Category pills (only show non-zero categories)
    categories = {}
    for opp in opportunities:
        cat = opp.get("strategy_category", opp.strategy_category if hasattr(opp, "strategy_category") else "")
        categories[cat] = categories.get(cat, 0) + 1

    if len(categories) > 1:
        pills = st.columns(min(len(categories) + 1, 7))
        with pills[0]:
            if st.button(f"All ({len(opportunities)})", key="iter_cat_all",
                         type="primary" if st.session_state.iter_category_filter is None else "secondary"):
                st.session_state.iter_category_filter = None
                st.rerun()
        for i, (cat, count) in enumerate(sorted(categories.items(), key=lambda x: -x[1])):
            with pills[i + 1]:
                icon = CATEGORY_ICONS.get(cat, "")
                label = f"{icon} {cat.replace('_', ' ').title()} ({count})"
                if st.button(label, key=f"iter_cat_{cat}",
                             type="primary" if st.session_state.iter_category_filter == cat else "secondary"):
                    st.session_state.iter_category_filter = cat
                    st.rerun()

    st.markdown(f"**{len(opportunities)} opportunities found**")

    # Filter by category
    filtered = opportunities
    if st.session_state.iter_category_filter:
        filtered = [o for o in opportunities if _get_field(o, "strategy_category") == st.session_state.iter_category_filter]

    # Render opportunity cards
    for idx, opp in enumerate(filtered):
        _render_opportunity_card(opp, idx, brand_id, product_id, org_id)

    # Dismissed section
    dismissed = detector.get_opportunities(brand_id, org_id, status="dismissed")
    if dismissed:
        with st.expander(f"Dismissed ({len(dismissed)})"):
            for d_opp in dismissed:
                col1, col2 = st.columns([5, 1])
                with col1:
                    st.text(f"{_get_field(d_opp, 'pattern_label')} — {_get_field(d_opp, 'meta_ad_id')}")
                with col2:
                    if st.button("Restore", key=f"iter_restore_{_get_field(d_opp, 'id')}"):
                        detector.restore_opportunity(_get_field(d_opp, "id"))
                        st.rerun()


def _run_scan(brand_id: str, org_id: str):
    """Run opportunity detection scan."""
    detector = get_detector()
    days_back = st.session_state.get("iter_days_back", 30)

    with st.spinner("Scanning for opportunities..."):
        phases = ["Loading ads (1/4)", "Comparing to baselines (2/4)",
                  "Detecting patterns (3/4)", "Ranking results (4/4)"]

        try:
            opps = asyncio.run(
                detector.detect_opportunities(brand_id, org_id, days_back=days_back)
            )

            # Convert dataclass list to dict list for session state serialization
            result = []
            for o in opps:
                if hasattr(o, "__dict__"):
                    result.append(o.__dict__)
                elif isinstance(o, dict):
                    result.append(o)
                else:
                    result.append({"meta_ad_id": str(o)})

            st.session_state.iter_opportunities = result
            st.session_state.iter_scan_done = True
            st.rerun()
        except Exception as e:
            st.error(f"Scan failed: {e}")


def _render_opportunity_card(opp: dict, idx: int, brand_id: str, product_id: Optional[str], org_id: str):
    """Render a single opportunity card with two-level design."""
    meta_ad_id = _get_field(opp, "meta_ad_id")
    pattern_label = _get_field(opp, "pattern_label")
    confidence = float(_get_field(opp, "confidence", 0))
    strong_metric = _get_field(opp, "strong_metric")
    strong_value = float(_get_field(opp, "strong_value", 0))
    strong_pct = _get_field(opp, "strong_percentile")
    weak_metric = _get_field(opp, "weak_metric")
    weak_value = float(_get_field(opp, "weak_value", 0))
    weak_pct = _get_field(opp, "weak_percentile")
    category = _get_field(opp, "strategy_category")
    evolution_mode = _get_field(opp, "evolution_mode")
    opp_id = _get_field(opp, "id")
    creative_format = _get_field(opp, "creative_format", "")

    conf_label, conf_color = _confidence_label(confidence)
    is_video = creative_format.startswith("video_") if creative_format else False
    format_badge = "🎬 VIDEO" if is_video else "🖼️ IMAGE"

    strong_label = METRIC_LABELS.get(strong_metric, strong_metric)
    weak_label = METRIC_LABELS.get(weak_metric, weak_metric)

    thumbnail_url = _get_field(opp, "thumbnail_url", "")
    ad_name = _get_field(opp, "ad_name", "")

    # Level 1: Collapsed summary
    with st.container(border=True):
        cols = st.columns([1, 4, 2])
        with cols[0]:
            if thumbnail_url:
                st.image(thumbnail_url, width=100)
            else:
                st.markdown(f"**{format_badge}**")
        with cols[1]:
            st.markdown(
                f"**{pattern_label}** &nbsp; "
                f":{conf_color}[{conf_label}]"
            )
            if ad_name:
                st.caption(f"**{ad_name}**")
            st.caption(
                f"{strong_label} {_format_metric(strong_metric, strong_value)} ({strong_pct}) "
                f"but {weak_label} only {_format_metric(weak_metric, weak_value)} ({weak_pct})"
            )
        with cols[2]:
            if is_video:
                # Video ads get brief instead of iterate
                pass  # Action brief shown in details
            elif evolution_mode:
                if st.button("🔬 Iterate", key=f"iter_act_{idx}", use_container_width=True):
                    st.session_state.iter_action_confirm = idx
            elif category == "budget":
                st.caption("Budget recommendation")

        # Level 2: Expandable details
        with st.expander("Details", expanded=(st.session_state.iter_action_confirm == idx)):
            strategy_desc = _get_field(opp, "strategy_description")
            strategy_actions = _get_field(opp, "strategy_actions")
            if isinstance(strategy_actions, str):
                try:
                    strategy_actions = json.loads(strategy_actions)
                except (json.JSONDecodeError, TypeError):
                    strategy_actions = []

            col_detail, col_strategy = st.columns([1, 2])

            with col_detail:
                st.markdown(f"**Ad**: `{meta_ad_id}`")
                st.markdown(f"**Category**: {CATEGORY_ICONS.get(category, '')} {category.replace('_', ' ').title()}")
                st.markdown(f"**Confidence**: {confidence:.2f}")

                spend = float(_get_field(opp, "spend", 0))
                impressions = int(float(_get_field(opp, "impressions", 0)))
                if spend > 0:
                    st.markdown(f"**Spend**: ${spend:,.0f} | **Impressions**: {impressions:,}")

            with col_strategy:
                st.markdown(f"**Strategy**: {strategy_desc}")
                if strategy_actions:
                    for action in strategy_actions:
                        st.markdown(f"- {action}")

            # Action: Iterate confirmation (image ads)
            if st.session_state.iter_action_confirm == idx and evolution_mode and not is_video:
                st.divider()
                _render_iterate_confirmation(opp, brand_id, product_id, org_id, idx)

            # Action: Video brief
            if is_video:
                st.divider()
                _render_video_brief(opp, brand_id, org_id)

            # Dismiss button
            if _get_field(opp, "status", "detected") == "detected":
                if st.button("Dismiss", key=f"iter_dismiss_{idx}"):
                    get_detector().dismiss_opportunity(opp_id)
                    st.rerun()


def _render_iterate_confirmation(opp: dict, brand_id: str, product_id: Optional[str], org_id: str, idx: int):
    """Render pre-filled iteration confirmation card."""
    evolution_mode = _get_field(opp, "evolution_mode")
    strategy_desc = _get_field(opp, "strategy_description")
    strategy_actions = _get_field(opp, "strategy_actions")
    if isinstance(strategy_actions, str):
        try:
            strategy_actions = json.loads(strategy_actions)
        except (json.JSONDecodeError, TypeError):
            strategy_actions = []

    st.markdown("**Confirm Iteration**")

    st.markdown(f"**Mode**: {evolution_mode.replace('_', ' ').title()}")

    # Product selector (if not already set)
    if not product_id:
        products = get_products_for_brand(brand_id)
        if products:
            product_id = st.selectbox(
                "Product",
                options=[p["id"] for p in products],
                format_func=lambda pid: next((p["name"] for p in products if p["id"] == pid), pid),
                key=f"iter_product_{idx}"
            )
        else:
            st.warning("No products found for this brand.")
            return

    # Pre-filled instructions (editable)
    default_instructions = f"Strategy: {strategy_desc}. "
    if strategy_actions:
        default_instructions += " ".join(f"({i+1}) {a}" for i, a in enumerate(strategy_actions[:4]))

    instructions = st.text_area(
        "Additional instructions (pre-filled, editable)",
        value=default_instructions,
        height=100,
        key=f"iter_instructions_{idx}"
    )

    col1, col2 = st.columns(2)
    with col1:
        if st.button("Confirm & Launch", key=f"iter_launch_{idx}", type="primary"):
            _execute_iteration(opp, brand_id, product_id, org_id)
    with col2:
        if st.button("Cancel", key=f"iter_cancel_{idx}"):
            st.session_state.iter_action_confirm = None
            st.rerun()


def _execute_iteration(opp: dict, brand_id: str, product_id: str, org_id: str):
    """Execute the iteration via action_opportunity."""
    detector = get_detector()
    opp_id = _get_field(opp, "id")

    with st.spinner("Launching iteration..."):
        try:
            result = asyncio.run(
                detector.action_opportunity(opp_id, brand_id, product_id, org_id)
            )
            if result.get("success"):
                child_id = result.get("child_ad_id", "")
                st.success(f"Iteration launched! Child ad: {child_id}")
                st.session_state.iter_action_confirm = None
                st.rerun()
            else:
                st.error(f"Iteration failed: {result.get('error', 'Unknown error')}")
        except Exception as e:
            st.error(f"Iteration failed: {e}")


def _render_video_brief(opp: dict, brand_id: str, org_id: str):
    """Render video ad action brief."""
    st.markdown("**Action Brief**")

    strategy_actions = _get_field(opp, "strategy_actions")
    if isinstance(strategy_actions, str):
        try:
            strategy_actions = json.loads(strategy_actions)
        except (json.JSONDecodeError, TypeError):
            strategy_actions = []

    if strategy_actions:
        for action in strategy_actions:
            st.markdown(f"- {action}")

    st.caption("Video iteration coming soon. Use this brief to guide your editor.")

    brief_text = _get_field(opp, "strategy_description", "") + "\n"
    if strategy_actions:
        brief_text += "\n".join(f"- {a}" for a in strategy_actions)

    st.code(brief_text, language=None)


# ============================================
# TAB 2: ANALYZE WINNERS
# ============================================

def render_winners_tab(brand_id: str, org_id: str):
    """Render the Analyze Winners tab."""

    view_mode = st.radio(
        "View",
        ["Winner Blueprint", "Deep Dive"],
        horizontal=True,
        key="iter_winner_view_mode",
    )

    if view_mode == "Winner Blueprint":
        _render_cross_winner(brand_id, org_id)
    else:
        _render_per_winner(brand_id, org_id)


def _render_cross_winner(brand_id: str, org_id: str):
    """Render cross-winner blueprint view."""
    col1, col2 = st.columns([1, 3])
    with col1:
        top_n = st.selectbox("Top N", [5, 10, 15, 20], index=1, key="iter_top_n")
    with col2:
        if st.button("🧬 Analyze Winners", use_container_width=True, key="iter_cross_btn"):
            _run_cross_winner_analysis(brand_id, org_id, top_n)

    analysis = st.session_state.iter_cross_winner_result
    if not analysis:
        st.info("Understand what your best ads have in common. Click **Analyze Winners** to generate a blueprint.")
        return

    winner_count = analysis.get("winner_count", 0) if isinstance(analysis, dict) else getattr(analysis, "winner_count", 0)

    # Winning formula card
    with st.container(border=True):
        st.markdown(f"### Your Winning Formula (based on top {winner_count} ads)")

        # DO THIS
        st.markdown("**DO THIS:**")
        common_elements = _safe_get(analysis, "common_elements")
        common_visuals = _safe_get(analysis, "common_visual_traits")

        if common_elements:
            for key, elem in (common_elements.items() if isinstance(common_elements, dict) else []):
                display = elem.get("display_name", elem.get("element", key))
                val = elem.get("value", "")
                count = elem.get("count", 0)
                total = elem.get("total", winner_count)
                st.markdown(f"- **{display}**: {val} ({count}/{total} winners)")

        if common_visuals:
            for field, trait in (common_visuals.items() if isinstance(common_visuals, dict) else []):
                label = field.replace("_", " ").title()
                val = trait.get("value", "")
                count = trait.get("count", 0)
                total = trait.get("total", winner_count)
                st.markdown(f"- **{label}**: {val} ({count}/{total} winners)")

        if not common_elements and not common_visuals:
            st.caption("No strong common patterns found. Winners are diverse in this brand.")

        # AVOID THIS
        anti_patterns = _safe_get(analysis, "anti_patterns")
        if anti_patterns:
            st.markdown("")
            st.markdown("**AVOID THIS:**")
            for ap in (anti_patterns if isinstance(anti_patterns, list) else []):
                elem = ap.get("element", "")
                val = ap.get("value", "")
                loser_count = ap.get("loser_count", 0)
                total_losers = ap.get("total_losers", 0)
                winner_count_ap = ap.get("winner_count", 0)
                st.markdown(f"- {elem}: \"{val}\" ({winner_count_ap}/{winner_count} winners, {loser_count}/{total_losers} losers)")

    # Full breakdown expander
    iteration_directions = _safe_get(analysis, "iteration_directions")
    if iteration_directions:
        with st.expander("Full element & visual breakdown"):
            for direction in (iteration_directions if isinstance(iteration_directions, list) else []):
                conf = direction.get("confidence", 0)
                label = direction.get("direction", "")
                rationale = direction.get("rationale", "")
                source = direction.get("source", "")
                st.markdown(f"- **{label}** ({conf:.0%}) — {rationale} [{source}]")


def _run_cross_winner_analysis(brand_id: str, org_id: str, top_n: int):
    """Run cross-winner analysis."""
    analyzer = get_dna_analyzer()

    with st.spinner(f"Analyzing top {top_n} winners..."):
        try:
            result = asyncio.run(
                analyzer.analyze_cross_winners(brand_id, org_id, top_n=top_n)
            )
            if result:
                # Serialize for session state
                st.session_state.iter_cross_winner_result = {
                    "winner_count": result.winner_count,
                    "common_elements": result.common_elements,
                    "common_visual_traits": result.common_visual_traits,
                    "anti_patterns": result.anti_patterns,
                    "iteration_directions": result.iteration_directions,
                    "replication_blueprint": result.replication_blueprint,
                }
                st.rerun()
            else:
                st.warning("Not enough winning ads found. Need at least 3 ads with 7+ days of data and strong performance.")
        except Exception as e:
            st.error(f"Analysis failed: {e}")


def _render_per_winner(brand_id: str, org_id: str):
    """Render per-winner deep dive view."""
    # Winner selector
    from viraltracker.services.ad_performance_query_service import AdPerformanceQueryService
    perf_service = AdPerformanceQueryService(get_supabase_client())

    top_result = perf_service.get_top_ads(
        brand_id=brand_id, sort_by="roas", days_back=30, limit=20, min_spend=10.0
    )
    top_ads = top_result.get("ads", [])

    if not top_ads:
        st.info("No ads with enough performance data found. Ads need at least 7 days and $10+ spend.")
        return

    # Build selector options
    options = []
    for ad in top_ads:
        roas = ad.get("roas", 0)
        name = ad.get("ad_name", ad.get("meta_ad_id", ""))[:40]
        options.append(f"{name} — ROAS {roas:.1f}x")

    selected_idx = st.selectbox(
        "Select a winner to analyze",
        range(len(options)),
        format_func=lambda i: options[i],
        key="iter_winner_select"
    )

    selected_ad = top_ads[selected_idx]
    meta_ad_id = selected_ad["meta_ad_id"]

    if st.button("🧬 Analyze", key="iter_per_winner_btn"):
        _run_per_winner_analysis(meta_ad_id, brand_id, org_id)

    dna = st.session_state.iter_per_winner_result
    if not dna:
        return

    # Display DNA results
    dna_id = dna.get("meta_ad_id", "")
    metrics = dna.get("metrics", {})

    with st.container(border=True):
        st.markdown(f"### Why This Ad Wins: `{dna_id}`")

        # Performance header
        perf_parts = []
        if metrics.get("roas"):
            perf_parts.append(f"ROAS: {metrics['roas']:.1f}x")
        if metrics.get("ctr"):
            perf_parts.append(f"CTR: {metrics['ctr']:.2f}%")
        if metrics.get("cpa"):
            perf_parts.append(f"CPA: ${metrics['cpa']:.2f}")
        if perf_parts:
            st.markdown(" | ".join(perf_parts))

        # Narrative summary
        top_elements = dna.get("top_elements", [])
        synergies = dna.get("active_synergies", [])

        if top_elements:
            from viraltracker.services.winner_dna_analyzer import ELEMENT_DISPLAY_NAMES
            parts = []
            for elem in top_elements[:3]:
                name = ELEMENT_DISPLAY_NAMES.get(elem.get("element", ""), elem.get("element", ""))
                pct = elem.get("percentile_rank", "")
                parts.append(f"{name.lower()} ({pct})")
            narrative = f"This ad's strongest assets are: {', '.join(parts)}."
            if synergies:
                syn = synergies[0]
                narrative += f" Known synergy: {syn.get('pair', '')} (+{syn.get('effect', 0):.0%} lift)."
            st.markdown(f"*{narrative}*")

        # Visual properties
        visual = dna.get("visual_properties")
        if visual:
            col1, col2 = st.columns(2)
            with col1:
                st.markdown("**Visual Properties**")
                props = [
                    f"Contrast: {visual.get('contrast_level', 'n/a')}",
                    f"Palette: {visual.get('color_palette_type', 'n/a')}",
                    f"Text: {visual.get('text_density', 'n/a')} ({visual.get('headline_word_count', 0)} words)",
                    f"Hierarchy: {visual.get('visual_hierarchy', 'n/a')}",
                ]
                for p in props:
                    st.markdown(f"- {p}")
            with col2:
                st.markdown("**Face & Product**")
                face = "Yes" if visual.get("face_presence") else "No"
                product = "Yes" if visual.get("product_visible") else "No"
                props2 = [
                    f"Face: {face} ({visual.get('person_framing', 'n/a')})",
                    f"Emotion: {visual.get('face_emotion', 'n/a')}",
                    f"Product: {product} ({visual.get('product_prominence', 'n/a')})",
                    f"Thumb-stop: {visual.get('thumb_stop_prediction', 0):.0%}",
                ]
                for p in props2:
                    st.markdown(f"- {p}")

        # Element breakdown expander
        element_scores = dna.get("element_scores", [])
        if element_scores:
            with st.expander("Full Element Breakdown"):
                for score in element_scores:
                    name = score.get("display_name", score.get("element", ""))
                    val = score.get("value", "")
                    reward = score.get("mean_reward", 0)
                    pct = score.get("percentile_rank", "")
                    obs = score.get("observations", 0)
                    st.markdown(f"- **{name}**: {val} — reward {reward:.3f} ({pct}, {obs:.0f} obs)")

        # Cohort comparison expander
        cohort = dna.get("cohort_comparison", {})
        if cohort:
            with st.expander("Cohort Comparison"):
                for metric, comp in cohort.items():
                    verdict = comp.get("verdict", "")
                    val = comp.get("value", 0)
                    p25 = comp.get("p25", 0)
                    median = comp.get("median", 0)
                    p75 = comp.get("p75", 0)
                    verdict_icon = {"excellent": "🟢", "above_average": "🟡", "below_average": "🟠", "poor": "🔴"}.get(verdict, "⚪")
                    val = val if val is not None else 0
                    p25 = p25 if p25 is not None else 0
                    median = median if median is not None else 0
                    p75 = p75 if p75 is not None else 0
                    st.markdown(
                        f"- **{METRIC_LABELS.get(metric, metric)}**: {val:.4f} "
                        f"(p25: {p25:.4f} | median: {median:.4f} | p75: {p75:.4f}) {verdict_icon} {verdict}"
                    )

        # Synergies/conflicts expander
        if synergies or dna.get("active_conflicts"):
            with st.expander("Synergy Effects"):
                if synergies:
                    st.markdown("**Synergies:**")
                    for s in synergies:
                        st.markdown(f"- {s.get('pair', '')} (+{s.get('effect', 0):.0%}, n={s.get('sample_size', 0)})")
                conflicts = dna.get("active_conflicts", [])
                if conflicts:
                    st.markdown("**Conflicts:**")
                    for c in conflicts:
                        st.markdown(f"- {c.get('pair', '')} ({c.get('effect', 0):.0%}, n={c.get('sample_size', 0)})")


def _run_per_winner_analysis(meta_ad_id: str, brand_id: str, org_id: str):
    """Run per-winner DNA analysis."""
    analyzer = get_dna_analyzer()

    with st.spinner(f"Analyzing {meta_ad_id}..."):
        try:
            dna = asyncio.run(
                analyzer.analyze_winner(meta_ad_id, brand_id, org_id)
            )
            if dna:
                # Serialize for session state
                st.session_state.iter_per_winner_result = {
                    "meta_ad_id": dna.meta_ad_id,
                    "metrics": dna.metrics,
                    "element_scores": dna.element_scores,
                    "top_elements": dna.top_elements,
                    "weak_elements": dna.weak_elements,
                    "visual_properties": dna.visual_properties,
                    "messaging": dna.messaging,
                    "cohort_comparison": dna.cohort_comparison,
                    "active_synergies": dna.active_synergies,
                    "active_conflicts": dna.active_conflicts,
                }
                st.rerun()
            else:
                st.warning("Could not analyze this ad. Insufficient data.")
        except Exception as e:
            st.error(f"Analysis failed: {e}")


# ============================================
# HELPERS
# ============================================

def _get_field(obj, field: str, default=None):
    """Get a field from dict or dataclass."""
    if isinstance(obj, dict):
        return obj.get(field, default)
    return getattr(obj, field, default)


def _safe_get(obj, field: str):
    """Safely get a field that might be JSON string or dict."""
    val = _get_field(obj, field)
    if isinstance(val, str):
        try:
            return json.loads(val)
        except (json.JSONDecodeError, TypeError):
            return val
    return val


# ============================================
# MAIN
# ============================================

st.title("🔬 Iteration Lab")

from viraltracker.ui.utils import render_brand_selector
brand_id, product_id = render_brand_selector(
    key="iter_lab_brand",
    include_product=True,
    product_key="iter_lab_product",
)
if not brand_id:
    st.stop()

# Get org_id
from viraltracker.ui.utils import get_current_organization_id
org_id = get_current_organization_id() or "all"

# Tabs
tab1, tab2 = st.tabs([
    "💡 Find Opportunities",
    "🧬 Analyze Winners",
])

with tab1:
    st.caption("Find ads that are almost great and make them better.")
    render_opportunities_tab(brand_id, product_id, org_id)
    st.divider()
    st.caption("Want to understand why your winners work? See **Analyze Winners** tab.")

with tab2:
    st.caption("Understand what your best ads have in common.")
    render_winners_tab(brand_id, org_id)
    st.divider()
    st.caption("Ready to iterate? See **Find Opportunities** tab.")
