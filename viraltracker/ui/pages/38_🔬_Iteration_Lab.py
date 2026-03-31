"""
Iteration Lab - Find mixed-signal ads, analyze winner DNA, and find strategic leverage.

Tab 1: Find Opportunities - Scan for ads with exploitable mixed signals
Tab 2: Analyze Winners - Decompose what makes winning ads work
Tab 3: Awareness Coverage - Funnel gap visualization
Tab 4: Strategic Leverage - Cross-dimensional account analysis with ranked moves
Tab 5: Creative Intelligence - Hook leaderboard (thumb-stop rate) + correlation dashboard
"""

import asyncio
import json
import logging
import streamlit as st
from typing import Dict, List, Optional

logger = logging.getLogger(__name__)

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


def get_leverage_service():
    """Get AccountLeverageService."""
    from viraltracker.services.account_leverage_service import AccountLeverageService
    return AccountLeverageService(get_supabase_client())


def get_correlation_service():
    """Get CreativeCorrelationService."""
    from viraltracker.services.creative_correlation_service import CreativeCorrelationService
    return CreativeCorrelationService(get_supabase_client())


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
if "iter_format_filter" not in st.session_state:
    st.session_state.iter_format_filter = "All"
if "iter_cross_winner_result" not in st.session_state:
    st.session_state.iter_cross_winner_result = None
if "iter_per_winner_result" not in st.session_state:
    st.session_state.iter_per_winner_result = None
if "iter_action_confirm" not in st.session_state:
    st.session_state.iter_action_confirm = None
if "iter_awareness_breakdown" not in st.session_state:
    st.session_state.iter_awareness_breakdown = None
if "iter_awareness_expanded" not in st.session_state:
    st.session_state.iter_awareness_expanded = None
if "iter_cache_key" not in st.session_state:
    st.session_state.iter_cache_key = None
if "iter_awareness_filter" not in st.session_state:
    st.session_state.iter_awareness_filter = None
if "iter_leverage_data" not in st.session_state:
    st.session_state.iter_leverage_data = None
if "iter_leverage_timestamp" not in st.session_state:
    st.session_state.iter_leverage_timestamp = None
if "iter_leverage_acted" not in st.session_state:
    st.session_state.iter_leverage_acted = set()


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
    "scale": "🚀",
}

# Strategy options for batch iterate
STRATEGY_OPTIONS = {
    "improve_hook": {
        "label": "Improve Hook",
        "evolution_mode": "winner_iteration",
        "variable_override": "hook_type",
        "description": "Change the opening hook to improve stopping power",
    },
    "new_layout": {
        "label": "New Layout",
        "evolution_mode": "winner_iteration",
        "variable_override": "template_category",
        "description": "Try a different visual layout/structure",
    },
    "auto_improve": {
        "label": "Auto-Improve",
        "evolution_mode": "winner_iteration",
        "variable_override": None,
        "description": "System picks the best variable to change",
    },
    "new_sizes": {
        "label": "New Sizes",
        "evolution_mode": "cross_size_expansion",
        "variable_override": None,
        "description": "Generate in untested canvas sizes (1080x1080, 1350, 1920)",
    },
    "fresh_creative": {
        "label": "Fresh Creative",
        "evolution_mode": "anti_fatigue_refresh",
        "variable_override": None,
        "description": "Same psychology, completely fresh visual execution",
    },
}

# Auto-recommend strategy per pattern type
PATTERN_DEFAULT_STRATEGY = {
    "high_converter_low_stopper": "improve_hook",
    "high_cvr_low_ctr": "improve_hook",
    "good_hook_bad_close": "auto_improve",
    "thumb_stopper_quick_dropper": "auto_improve",
    "proven_winner": "auto_improve",
    "size_limited_winner": "new_sizes",
    "fatiguing_winner": "fresh_creative",
    "efficient_but_starved": None,  # budget recommendation, no evolution
}

# Default variation count per strategy (Auto-Improve and New Sizes always 1)
STRATEGY_DEFAULT_VARIATIONS = {
    "improve_hook": 3,
    "new_layout": 3,
    "auto_improve": 1,
    "new_sizes": 1,
    "fresh_creative": 3,
}

# Strategies that support user-chosen variation counts
VARIABLE_VARIATION_STRATEGIES = {"improve_hook", "new_layout", "fresh_creative"}

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


def _backfill_thumbnails(ad_ids: list, results: list) -> list:
    """Fetch missing thumbnails from Meta Creative API and update DB + results.

    Only fetches for ads in ad_ids. Updates meta_ads_performance rows
    and patches the in-memory results list so thumbnails display immediately.
    """
    try:
        from viraltracker.services.meta_ads_service import MetaAdsService
        service = MetaAdsService()
        thumbnails = asyncio.run(service.fetch_ad_thumbnails(ad_ids))
        if not thumbnails:
            return results

        # Update DB rows
        from viraltracker.core.database import get_supabase_client
        supabase = get_supabase_client()
        for ad_id, meta in thumbnails.items():
            url = meta.get("thumbnail_url")
            if not url:
                continue
            try:
                supabase.table("meta_ads_performance").update(
                    {"thumbnail_url": url}
                ).eq("meta_ad_id", ad_id).execute()
            except Exception:
                pass

        # Patch in-memory results
        for r in results:
            mid = r.get("meta_ad_id")
            if mid in thumbnails and thumbnails[mid].get("thumbnail_url"):
                r["thumbnail_url"] = thumbnails[mid]["thumbnail_url"]

        logger.info(f"Backfilled {len(thumbnails)} thumbnails for Iteration Lab")
    except Exception as e:
        logger.warning(f"Thumbnail backfill failed (non-fatal): {e}")
    return results


def _format_metric(metric: str, value: float, from_decimal: bool = False) -> str:
    """Format a metric value for display.

    Args:
        metric: Metric name (roas, ctr, cpc, etc.)
        value: Metric value.
        from_decimal: True if rate metrics (ctr, conversion_rate) are stored as
            decimals (0.015) rather than percentages (1.5). The detector uses
            decimals; winner_dna_analyzer and ad_performance_query_service use
            percentages.
    """
    if value is None:
        return "n/a"
    if metric in ("roas",):
        return f"{value:.1f}x"
    elif metric in ("ctr", "hook_rate", "hold_rate", "conversion_rate"):
        display = value * 100 if from_decimal else value
        return f"{display:.1f}%"
    elif metric in ("cpc", "cpa"):
        return f"${value:.2f}"
    elif metric in ("impressions",):
        return f"{value:,.0f}"
    elif metric in ("spend",):
        return f"${value:,.0f}"
    elif metric in ("ctr_decline_pct",):
        return f"-{abs(value) * 100:.0f}%" if value < 1 else f"-{value:.0f}%"
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
    col1, col2, col3, col4 = st.columns([3, 1, 1, 1])
    with col1:
        if st.button("🔍 Scan for Opportunities", use_container_width=True, key="iter_scan_btn"):
            _run_scan(brand_id, org_id, product_id=product_id)
    with col2:
        days_back = st.selectbox(
            "Days back", [14, 30, 60, 90], index=1, key="iter_days_back"
        )
    with col3:
        st.selectbox(
            "Min spend", [0, 20, 50, 100, 250, 500], index=2,
            format_func=lambda x: f"${x}" if x > 0 else "No min",
            key="iter_min_spend"
        )
    with col4:
        st.selectbox(
            "Format", ["All", "Image", "Video"], key="iter_format_filter"
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
        max_pills = len(categories) + 1  # +1 for "All"
        pills = st.columns(max_pills)
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

    # Awareness filter (from Tab 3 link)
    awareness_filter = st.session_state.get("iter_awareness_filter")
    if awareness_filter:
        level_label = awareness_filter.replace("_", " ").title()
        col_af1, col_af2 = st.columns([5, 1])
        with col_af1:
            st.info(f"Showing opportunities for **{level_label}** ads")
        with col_af2:
            if st.button("Clear filter", key="iter_clear_awareness_filter"):
                st.session_state.iter_awareness_filter = None
                st.rerun()

    # Filter by category, format, min spend, and awareness
    filtered = opportunities
    if st.session_state.iter_category_filter:
        filtered = [o for o in filtered if _get_field(o, "strategy_category") == st.session_state.iter_category_filter]
    fmt_filter = st.session_state.get("iter_format_filter", "All")
    if fmt_filter == "Image":
        filtered = [o for o in filtered if not _get_field(o, "creative_format", "").startswith("video_")]
    elif fmt_filter == "Video":
        filtered = [o for o in filtered if _get_field(o, "creative_format", "").startswith("video_")]
    min_spend = st.session_state.get("iter_min_spend", 50)
    if min_spend > 0:
        filtered = [o for o in filtered if float(_get_field(o, "spend", 0)) >= min_spend]
    if awareness_filter:
        filtered = [o for o in filtered if _get_field(o, "awareness_level", "") == awareness_filter]

    if len(filtered) < len(opportunities):
        st.markdown(f"**{len(filtered)} opportunities shown** ({len(opportunities)} found, {len(opportunities) - len(filtered)} filtered out)")
    else:
        st.markdown(f"**{len(opportunities)} opportunities found**")

    # Render opportunity cards
    for idx, opp in enumerate(filtered):
        _render_opportunity_card(opp, idx, brand_id, product_id, org_id)

    # Batch queue bar
    _render_batch_queue_bar(filtered, brand_id, product_id, org_id)

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


def _run_scan(brand_id: str, org_id: str, product_id: Optional[str] = None):
    """Run opportunity detection scan."""
    detector = get_detector()
    days_back = st.session_state.get("iter_days_back", 30)

    with st.spinner("Scanning for opportunities..."):
        phases = ["Loading ads (1/4)", "Comparing to baselines (2/4)",
                  "Detecting patterns (3/4)", "Ranking results (4/4)"]

        try:
            opps = asyncio.run(
                detector.detect_opportunities(brand_id, org_id, days_back=days_back, product_id=product_id)
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

            # Auto-fetch missing thumbnails for opportunity ads
            missing_thumb_ids = [
                r["meta_ad_id"] for r in result
                if r.get("meta_ad_id") and not r.get("thumbnail_url")
            ]
            if missing_thumb_ids:
                result = _backfill_thumbnails(missing_thumb_ids, result)

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
    explanation_headline = _get_field(opp, "explanation_headline", "")
    explanation_projection = _get_field(opp, "explanation_projection", "")

    # Level 1: Collapsed summary
    pattern_type = _get_field(opp, "pattern_type", "")
    with st.container(border=True):
        # Image ads with evolution_mode get a checkbox; video ads and budget-only do not
        can_batch = not is_video and bool(evolution_mode)
        if can_batch:
            cols = st.columns([0.4, 0.8, 3.5, 2.3])
        else:
            cols = st.columns([1, 4, 2])

        col_offset = 0
        if can_batch:
            with cols[0]:
                st.checkbox(
                    "Select", key=f"iter_select_{opp_id}",
                    label_visibility="collapsed",
                )
            col_offset = 1

        with cols[col_offset]:
            if thumbnail_url:
                st.image(thumbnail_url, width=100)
            else:
                st.markdown(f"**{format_badge}**")
        with cols[col_offset + 1]:
            st.markdown(
                f"**{pattern_label}** &nbsp; "
                f":{conf_color}[{conf_label}]"
            )
            if ad_name:
                st.caption(f"**{ad_name}**")
            if explanation_headline:
                st.caption(explanation_headline)
            else:
                st.caption(
                    f"{strong_label} {_format_metric(strong_metric, strong_value, from_decimal=True)} ({strong_pct}) "
                    f"but {weak_label} only {_format_metric(weak_metric, weak_value, from_decimal=True)} ({weak_pct})"
                )
        with cols[col_offset + 2]:
            if is_video:
                # Video ads get brief instead of iterate
                pass  # Action brief shown in details
            elif evolution_mode:
                # Strategy dropdown
                default_strategy = PATTERN_DEFAULT_STRATEGY.get(pattern_type, "auto_improve")
                strategy_keys = list(STRATEGY_OPTIONS.keys())
                default_idx = strategy_keys.index(default_strategy) if default_strategy in strategy_keys else 2

                st.selectbox(
                    "Strategy",
                    options=strategy_keys,
                    index=default_idx,
                    format_func=lambda s, d=default_strategy: (
                        STRATEGY_OPTIONS[s]["label"] + (" ★" if s == d else "")
                    ),
                    key=f"iter_strategy_{opp_id}",
                    label_visibility="collapsed",
                )
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
                cvr = float(_get_field(opp, "conversion_rate", 0))
                if spend > 0:
                    st.markdown(f"**Spend**: ${spend:,.0f} | **Impressions**: {impressions:,} | **CVR**: {cvr*100:.1f}%")

            with col_strategy:
                if explanation_projection:
                    st.markdown(f"*{explanation_projection}*")
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


def _render_batch_queue_bar(
    filtered: list, brand_id: str, product_id: Optional[str], org_id: str
):
    """Render batch queue bar below opportunity list when items are selected."""
    selected_opps = [
        opp for opp in filtered
        if st.session_state.get(f"iter_select_{_get_field(opp, 'id')}")
    ]

    if not selected_opps:
        return

    st.divider()
    cols = st.columns([2, 1.5, 1, 1.5])
    with cols[0]:
        st.markdown(f"**{len(selected_opps)} selected**")
    with cols[1]:
        bulk_strategy = st.selectbox(
            "Bulk strategy",
            options=["keep_individual", *STRATEGY_OPTIONS.keys()],
            format_func=lambda s: (
                "Keep Individual" if s == "keep_individual"
                else STRATEGY_OPTIONS[s]["label"]
            ),
            key="iter_bulk_strategy",
            label_visibility="collapsed",
        )
    with cols[2]:
        # Show variations dropdown — only meaningful for variable strategies
        effective_strategy = bulk_strategy if bulk_strategy != "keep_individual" else None
        can_vary = effective_strategy in VARIABLE_VARIATION_STRATEGIES if effective_strategy else True
        if can_vary:
            num_variations = st.selectbox(
                "Variations",
                options=[1, 3, 5],
                index=1,  # default 3
                key="iter_num_variations",
            )
        else:
            num_variations = 1
            st.markdown("**1** variation")
    with cols[3]:
        if not product_id:
            st.warning("Select a product first")
        elif st.button(
            f"Queue {len(selected_opps)} Iterations",
            type="primary",
            key="iter_batch_queue_btn",
        ):
            _batch_queue(selected_opps, brand_id, product_id, org_id, bulk_strategy, num_variations)


def _batch_queue(
    opps: list, brand_id: str, product_id: str, org_id: str, bulk_strategy: str,
    num_variations: int = 3,
):
    """Import needed ads and create scheduled_jobs for batch iteration."""
    detector = get_detector()

    # Build strategy overrides from individual dropdowns
    overrides = {}
    for opp in opps:
        opp_id = _get_field(opp, "id")
        strategy_key = st.session_state.get(f"iter_strategy_{opp_id}", "auto_improve")
        if bulk_strategy != "keep_individual":
            strategy_key = bulk_strategy
        strategy = STRATEGY_OPTIONS[strategy_key]
        overrides[opp_id] = {
            "evolution_mode": strategy["evolution_mode"],
            "variable_override": strategy.get("variable_override"),
        }

    with st.spinner(f"Queueing {len(opps)} iterations..."):
        result = asyncio.run(
            detector.batch_queue_iterations(
                opportunity_ids=[_get_field(o, "id") for o in opps],
                brand_id=brand_id,
                product_id=product_id,
                org_id=org_id,
                strategy_overrides=overrides,
                num_variations=num_variations,
            )
        )

    queued = result.get("queued", 0)
    imported = result.get("imported", 0)
    errors = result.get("errors", [])

    if queued > 0:
        msg = f"Queued {queued} iterations"
        if imported:
            msg += f" (imported {imported} ads)"
        st.success(msg)
        # Clear checkbox + strategy state after successful queue
        for opp in opps:
            opp_id = _get_field(opp, "id")
            st.session_state.pop(f"iter_select_{opp_id}", None)
            st.session_state.pop(f"iter_strategy_{opp_id}", None)
        # Re-fetch opportunities to reflect "queued" status
        st.session_state.iter_opportunities = None
        st.session_state.iter_scan_done = False
        st.rerun()
    if errors:
        for err in errors:
            st.warning(err)


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

def render_winners_tab(brand_id: str, product_id: Optional[str], org_id: str):
    """Render the Analyze Winners tab."""

    col_mode, col_days, col_spend, col_fmt = st.columns([3, 1, 1, 1])
    with col_mode:
        view_mode = st.radio(
            "View",
            ["Winner Blueprint", "Deep Dive"],
            horizontal=True,
            key="iter_winner_view_mode",
        )
    with col_days:
        winner_days_back = st.selectbox(
            "Days back", [14, 30, 60, 90], index=1, key="iter_winner_days_back"
        )
    with col_spend:
        st.selectbox(
            "Min spend", [0, 20, 50, 100, 250, 500], index=2,
            format_func=lambda x: f"${x}" if x > 0 else "No min",
            key="iter_winner_min_spend"
        )
    with col_fmt:
        st.selectbox(
            "Format", ["All", "Image", "Video"], key="iter_winner_format_filter"
        )

    if view_mode == "Winner Blueprint":
        _render_cross_winner(brand_id, org_id, winner_days_back, product_id=product_id)
    else:
        _render_per_winner(brand_id, org_id, winner_days_back, product_id=product_id)


def _render_cross_winner(brand_id: str, org_id: str, days_back: int = 30, product_id: Optional[str] = None):
    """Render cross-winner blueprint view."""
    col1, col2 = st.columns([1, 3])
    with col1:
        top_n = st.selectbox("Top N", [5, 10, 15, 20], index=1, key="iter_top_n")
    with col2:
        if st.button("🧬 Analyze Winners", use_container_width=True, key="iter_cross_btn"):
            _run_cross_winner_analysis(brand_id, org_id, top_n, days_back, product_id=product_id)

    analysis = st.session_state.iter_cross_winner_result
    if not analysis:
        st.info("Understand what your best ads have in common. Click **Analyze Winners** to generate a blueprint.")
        return

    winner_count = analysis.get("winner_count", 0) if isinstance(analysis, dict) else getattr(analysis, "winner_count", 0)

    # --- Cohort Performance Summary ---
    cohort_summary = _safe_get(analysis, "cohort_summary")
    if cohort_summary and isinstance(cohort_summary, dict):
        m1, m2, m3, m4, m5 = st.columns(5)
        with m1:
            st.metric("Avg ROAS", f"{cohort_summary.get('avg_roas', 0):.1f}x")
        with m2:
            ctr_range = cohort_summary.get("ctr_range", [0, 0])
            st.metric("CTR Range", f"{ctr_range[0]:.1f}% - {ctr_range[1]:.1f}%")
        with m3:
            st.metric("Avg CVR", f"{cohort_summary.get('avg_conversion_rate', 0):.1f}%")
        with m4:
            st.metric("Total Spend", f"${cohort_summary.get('total_spend', 0):,.0f}")
        with m5:
            st.metric("Avg CPA", f"${cohort_summary.get('avg_cpa', 0):,.2f}")

    # --- Winner Thumbnail Gallery ---
    winner_thumbnails = _safe_get(analysis, "winner_thumbnails") or []
    # Backfill missing thumbnails from Meta Creative API
    if winner_thumbnails and isinstance(winner_thumbnails, list):
        missing_ids = [t["meta_ad_id"] for t in winner_thumbnails if not t.get("thumbnail_url")]
        if missing_ids:
            winner_thumbnails = _backfill_thumbnails(missing_ids, winner_thumbnails)
    if winner_thumbnails and isinstance(winner_thumbnails, list):
        thumb_cols = st.columns(min(len(winner_thumbnails), 6))
        for i, thumb in enumerate(winner_thumbnails[:6]):
            with thumb_cols[i]:
                if thumb.get("thumbnail_url"):
                    st.image(thumb["thumbnail_url"], width=80)
                else:
                    st.markdown("🖼️")
                st.caption(f"{thumb.get('roas', 0):.1f}x | {thumb.get('conversion_rate', 0):.1f}% CVR")

    # --- Winning Formula Card ---
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

        # ALSO NOTABLE (sub-threshold trends 25-49%)
        notable_elements = _safe_get(analysis, "notable_elements")
        notable_visuals = _safe_get(analysis, "notable_visual_traits")
        has_notable = (notable_elements and isinstance(notable_elements, dict)) or \
                      (notable_visuals and isinstance(notable_visuals, dict))

        if has_notable:
            st.markdown("")
            st.markdown("**ALSO NOTABLE** *(25-49% of winners)*")
            if notable_elements and isinstance(notable_elements, dict):
                for key, elem in notable_elements.items():
                    display = elem.get("display_name", elem.get("element", key))
                    val = elem.get("value", "")
                    count = elem.get("count", 0)
                    total = elem.get("total", winner_count)
                    st.markdown(f"- {display}: {val} ({count}/{total} winners)")
            if notable_visuals and isinstance(notable_visuals, dict):
                for field, trait in notable_visuals.items():
                    label = field.replace("_", " ").title()
                    val = trait.get("value", "")
                    count = trait.get("count", 0)
                    total = trait.get("total", winner_count)
                    st.markdown(f"- {label}: {val} ({count}/{total} winners)")

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

    # Winner Awareness Mix
    awareness_dist = _safe_get(analysis, "awareness_distribution")
    if awareness_dist and isinstance(awareness_dist, dict):
        level_labels = {
            "unaware": "Unaware", "problem_aware": "Problem Aware",
            "solution_aware": "Solution Aware", "product_aware": "Product Aware",
            "most_aware": "Most Aware",
        }
        parts = [f"{level_labels.get(k, k)} ({v})" for k, v in sorted(awareness_dist.items(), key=lambda x: -x[1])]
        st.markdown(f"**Winner Awareness Mix**: {' | '.join(parts)}")
        # Check if all winners are mid-to-bottom funnel
        upper_funnel = awareness_dist.get("unaware", 0) + awareness_dist.get("problem_aware", 0)
        if upper_funnel == 0 and sum(awareness_dist.values()) > 0:
            st.caption(
                "All winners are mid-to-bottom funnel. Testing upper-funnel creative "
                "with these winning elements could expand reach."
            )

    # Full breakdown expander
    iteration_directions = _safe_get(analysis, "iteration_directions")
    if iteration_directions:
        with st.expander("Full element & visual breakdown"):
            for direction in (iteration_directions if isinstance(iteration_directions, list) else []):
                conf = direction.get("confidence", 0)
                label = direction.get("direction", "")
                rationale = direction.get("rationale", "")
                source = direction.get("source", "")
                st.markdown(f"- **{label}** ({conf:.0%}) -- {rationale} [{source}]")

    # --- Replicate Winner DNA Button ---
    _render_replicate_button(analysis, brand_id, org_id, winner_thumbnails)


def _blueprint_to_instructions(blueprint: dict) -> str:
    """Convert a replication blueprint to human-readable instructions."""
    from viraltracker.services.winner_dna_analyzer import ELEMENT_DISPLAY_NAMES

    lines = ["WINNER DNA REPLICATION BRIEF:"]
    element_combo = blueprint.get("element_combo", {})
    visual = blueprint.get("visual_directives", {})
    messaging = blueprint.get("messaging_directives", {})

    if element_combo:
        lines.append("Creative elements to use:")
        for k, v in element_combo.items():
            label = ELEMENT_DISPLAY_NAMES.get(k, k.replace('_', ' ').title())
            lines.append(f"  - {label}: {v}")

    if visual:
        lines.append("Visual directives:")
        for k, v in visual.items():
            lines.append(f"  - {k.replace('_', ' ').title()}: {v}")

    if messaging:
        lines.append("Messaging directives:")
        for k, v in messaging.items():
            label = ELEMENT_DISPLAY_NAMES.get(k, k.replace('_', ' ').title())
            lines.append(f"  - {label}: {v}")

    return "\n".join(lines)


def _render_replicate_button(analysis: dict, brand_id: str, org_id: str, winner_thumbnails: list):
    """Render the 'Replicate Winner DNA' button below the Blueprint card."""
    blueprint = _safe_get(analysis, "replication_blueprint")
    if not blueprint:
        return

    st.divider()

    if st.button("Replicate Winner DNA", key="iter_replicate_btn", type="primary", use_container_width=True):
        st.session_state.iter_replicate_expand = True

    if not st.session_state.get("iter_replicate_expand"):
        return

    with st.container(border=True):
        st.markdown("### Replicate Winner DNA")
        st.caption("Create new ads based on the winning formula above.")

        # Winner selector (pick which winner to use as template)
        if winner_thumbnails:
            winner_options = [
                f"{t.get('ad_name', t.get('meta_ad_id', ''))[:30]} ({t.get('roas', 0):.1f}x)"
                for t in winner_thumbnails
            ]
            selected_winner_idx = st.selectbox(
                "Base winner (template)", range(len(winner_options)),
                format_func=lambda i: winner_options[i],
                key="iter_replicate_winner",
            )
            selected_winner = winner_thumbnails[selected_winner_idx]
        else:
            st.warning("No winner ads available to use as template.")
            return

        # Product selector
        products = get_products_for_brand(brand_id)
        if not products:
            st.warning("No products found for this brand.")
            return

        product_id = st.selectbox(
            "Product",
            options=[p["id"] for p in products],
            format_func=lambda pid: next((p["name"] for p in products if p["id"] == pid), pid),
            key="iter_replicate_product",
        )

        # Pre-filled instructions
        default_instructions = _blueprint_to_instructions(blueprint)
        instructions = st.text_area(
            "Instructions (pre-filled from blueprint, editable)",
            value=default_instructions,
            height=150,
            key="iter_replicate_instructions",
        )

        # Number of variations
        num_variations = st.selectbox("Variations", [3, 5, 10], index=1, key="iter_replicate_num")

        col_go, col_cancel = st.columns(2)
        with col_go:
            if st.button("Generate", key="iter_replicate_go", type="primary"):
                _execute_replication(
                    selected_winner, brand_id, product_id, org_id,
                    instructions, num_variations,
                )
        with col_cancel:
            if st.button("Cancel", key="iter_replicate_cancel"):
                st.session_state.iter_replicate_expand = False
                st.rerun()


def _execute_replication(
    selected_winner: dict, brand_id: str, product_id: str, org_id: str,
    instructions: str, num_variations: int,
):
    """Execute the replication by creating a one-time scheduled job."""
    from datetime import datetime, timedelta
    from uuid import UUID

    meta_ad_id = selected_winner.get("meta_ad_id", "")

    with st.spinner("Setting up replication job..."):
        try:
            # Step 1: Find or import the winning ad as a template
            detector = get_detector()
            generated_ad_id = detector._find_generated_ad(meta_ad_id, brand_id)

            if not generated_ad_id:
                from viraltracker.services.meta_winner_import_service import MetaWinnerImportService
                import_service = MetaWinnerImportService()
                meta_ad_account_id = detector._get_account_id(meta_ad_id)
                if not meta_ad_account_id:
                    st.error("Could not determine Meta ad account ID for this winner.")
                    return

                import_result = asyncio.run(
                    import_service.import_meta_winner(
                        brand_id=UUID(brand_id),
                        meta_ad_id=meta_ad_id,
                        product_id=UUID(product_id),
                        meta_ad_account_id=meta_ad_account_id,
                        extract_element_tags=True,
                    )
                )
                generated_ad_id = import_result.get("generated_ad_id")
                if not generated_ad_id:
                    st.error(f"Failed to import winner ad: {import_result.get('status', 'unknown')}")
                    return

            # Step 2: Get brand name for job label
            brand_name = brand_id[:8]
            try:
                brand_result = get_supabase_client().table("brands").select("name").eq("id", brand_id).limit(1).execute()
                if brand_result.data:
                    brand_name = brand_result.data[0].get("name", brand_name)
            except Exception as e:
                logger.debug(f"Failed to fetch brand name: {e}")

            # Step 3: Create one-time V2 job
            job_row = {
                "name": f"Blueprint Replication - {brand_name}",
                "job_type": "ad_creation_v2",
                "brand_id": brand_id,
                "product_id": product_id,
                "schedule_type": "one_time",
                "next_run_at": (datetime.utcnow() + timedelta(minutes=1)).isoformat(),
                "is_active": True,
                "scraped_template_ids": [generated_ad_id],
                "parameters": json.dumps({
                    "content_source": "recreate_template",
                    "template_selection_mode": "manual",
                    "num_variations": num_variations,
                    "canvas_sizes": ["1080x1080px"],
                    "color_modes": ["original"],
                    "additional_instructions": instructions,
                }),
            }
            get_supabase_client().table("scheduled_jobs").insert(job_row).execute()

            st.success(
                f"Replication job created! {num_variations} variations will be generated in ~1 minute. "
                f"Check the **Scheduled Tasks** page for progress."
            )
            st.session_state.iter_replicate_expand = False

        except Exception as e:
            st.error(f"Replication failed: {e}")


def _run_cross_winner_analysis(brand_id: str, org_id: str, top_n: int, days_back: int = 30, product_id: Optional[str] = None):
    """Run cross-winner analysis."""
    analyzer = get_dna_analyzer()

    with st.spinner(f"Analyzing top {top_n} winners..."):
        try:
            result = asyncio.run(
                analyzer.analyze_cross_winners(brand_id, org_id, top_n=top_n, days_back=days_back, product_id=product_id)
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
                    "notable_elements": result.notable_elements,
                    "notable_visual_traits": result.notable_visual_traits,
                    "cohort_summary": result.cohort_summary,
                    "winner_thumbnails": result.winner_thumbnails,
                    "awareness_distribution": result.awareness_distribution,
                }
                st.rerun()
            else:
                st.warning("Not enough winning ads found. Need at least 3 ads with 7+ days of data and strong performance.")
        except Exception as e:
            st.error(f"Analysis failed: {e}")


def _render_per_winner(brand_id: str, org_id: str, days_back: int = 30, product_id: Optional[str] = None):
    """Render per-winner deep dive view."""
    # Winner selector
    from viraltracker.services.ad_performance_query_service import AdPerformanceQueryService
    perf_service = AdPerformanceQueryService(get_supabase_client())

    winner_min_spend = float(st.session_state.get("iter_winner_min_spend", 50))
    top_result = perf_service.get_top_ads(
        brand_id=brand_id, sort_by="roas", days_back=days_back, limit=40,
        min_spend=max(winner_min_spend, 10.0), product_id=product_id,
    )
    top_ads = top_result.get("ads", [])

    # Apply format filter
    fmt_filter = st.session_state.get("iter_winner_format_filter", "All")
    if fmt_filter == "Image":
        top_ads = [a for a in top_ads if not (a.get("creative_format") or "").startswith("video_")]
    elif fmt_filter == "Video":
        top_ads = [a for a in top_ads if (a.get("creative_format") or "").startswith("video_")]

    if not top_ads:
        st.info(f"No ads found with ${winner_min_spend:.0f}+ spend in the last {days_back} days.")
        return

    # Backfill missing thumbnails
    missing_thumb_ids = [a["meta_ad_id"] for a in top_ads if not a.get("thumbnail_url")]
    if missing_thumb_ids:
        top_ads = _backfill_thumbnails(missing_thumb_ids, top_ads)

    # Visual card selector
    st.markdown("**Select a winner to analyze:**")
    for i, ad in enumerate(top_ads[:10]):
        with st.container(border=True):
            col_thumb, col_info, col_btn = st.columns([1, 4, 1])
            with col_thumb:
                if ad.get("thumbnail_url"):
                    st.image(ad["thumbnail_url"], width=60)
                else:
                    st.markdown("🖼️")
            with col_info:
                st.markdown(f"**{ad.get('ad_name', '')[:40]}**")
                roas = ad.get('roas', 0)
                ctr = ad.get('ctr', 0)
                cvr = ad.get('conversion_rate', 0)
                st.caption(f"ROAS {roas:.1f}x | CTR {ctr:.1f}% | CVR {cvr:.1f}% | ${ad.get('spend', 0):,.0f}")
            with col_btn:
                if st.button("Analyze", key=f"iter_analyze_{i}"):
                    _run_per_winner_analysis(ad["meta_ad_id"], brand_id, org_id)

    dna = st.session_state.iter_per_winner_result
    if not dna:
        return

    # Display DNA results
    dna_id = dna.get("meta_ad_id", "")
    dna_thumbnail = dna.get("thumbnail_url", "")
    metrics = dna.get("metrics", {})

    with st.container(border=True):
        # Header with thumbnail
        if dna_thumbnail:
            col_dna_thumb, col_dna_title = st.columns([1, 5])
            with col_dna_thumb:
                st.image(dna_thumbnail, width=80)
            with col_dna_title:
                st.markdown(f"### Why This Ad Wins: `{dna_id}`")
        else:
            st.markdown(f"### Why This Ad Wins: `{dna_id}`")

        # Performance header
        perf_parts = []
        if metrics.get("roas"):
            perf_parts.append(f"ROAS: {metrics['roas']:.1f}x")
        if metrics.get("ctr"):
            perf_parts.append(f"CTR: {metrics['ctr']:.1f}%")
        if metrics.get("conversion_rate"):
            perf_parts.append(f"CVR: {metrics['conversion_rate']:.1f}%")
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
                        f"- **{METRIC_LABELS.get(metric, metric)}**: {_format_metric(metric, val)} "
                        f"(p25: {_format_metric(metric, p25)} | median: {_format_metric(metric, median)} "
                        f"| p75: {_format_metric(metric, p75)}) {verdict_icon} {verdict}"
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
                # Fetch thumbnail_url from meta_ads_performance
                thumbnail_url = ""
                try:
                    thumb_result = (
                        get_supabase_client().table("meta_ads_performance")
                        .select("thumbnail_url")
                        .eq("meta_ad_id", meta_ad_id)
                        .eq("brand_id", brand_id)
                        .not_.is_("thumbnail_url", "null")
                        .order("date", desc=True)
                        .limit(1)
                        .execute()
                    )
                    if thumb_result.data:
                        thumbnail_url = thumb_result.data[0].get("thumbnail_url", "")
                except Exception as e:
                    logger.debug(f"Failed to fetch thumbnail: {e}")

                # Serialize for session state
                st.session_state.iter_per_winner_result = {
                    "meta_ad_id": dna.meta_ad_id,
                    "thumbnail_url": thumbnail_url,
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
# TAB 3: AWARENESS COVERAGE
# ============================================

AWARENESS_GAP_MESSAGES = {
    "unaware": (
        "Top-of-funnel ads build your retargeting audience. Without them, "
        "BOFU audiences will shrink and CPAs will rise over time."
    ),
    "problem_aware": (
        "Problem-aware ads educate prospects on the pain point. "
        "They prime audiences to be receptive to your solution."
    ),
    "solution_aware": (
        "Solution-aware ads position your approach vs alternatives. "
        "Missing this stage means you're competing only on price."
    ),
    "product_aware": (
        "Product-aware ads are your conversion drivers. "
        "Without them, warm audiences have no clear path to purchase."
    ),
    "most_aware": (
        "Most-aware ads target repeat buyers and loyalists. "
        "They have the highest ROAS and lowest CPA."
    ),
}

AWARENESS_LEVEL_ICONS = {
    "unaware": "🔴",
    "problem_aware": "🟡",
    "solution_aware": "🟡",
    "product_aware": "🟢",
    "most_aware": "🟢",
}


def _get_awareness_health_icon(spend_share: float, ad_count: int) -> str:
    """Get health icon based on spend share."""
    if ad_count == 0:
        return "🔴"
    if spend_share >= 0.10:
        return "🟢"
    if spend_share >= 0.01:
        return "🟡"
    return "🔴"


def render_awareness_tab(brand_id: str, product_id: Optional[str], org_id: str):
    """Render the Awareness Coverage tab."""
    from viraltracker.services.ad_performance_query_service import AdPerformanceQueryService

    col1, col2, col3 = st.columns([1, 1, 1])
    with col1:
        awareness_days_back = st.selectbox(
            "Days back", [14, 30, 60, 90], index=1, key="iter_awareness_days_back"
        )
    with col2:
        awareness_min_spend = st.selectbox(
            "Min spend", [0, 20, 50, 100, 250, 500], index=1,
            format_func=lambda x: f"${x}" if x > 0 else "No min",
            key="iter_awareness_min_spend"
        )
    with col3:
        awareness_format = st.selectbox(
            "Format", ["All", "Image", "Video"], key="iter_awareness_format"
        )

    # Load or use cached breakdown
    if st.button("📊 Analyze Awareness", use_container_width=True, key="iter_awareness_btn"):
        perf_service = AdPerformanceQueryService(get_supabase_client())
        with st.spinner("Analyzing awareness coverage..."):
            try:
                fmt_map = {"All": None, "Image": "image", "Video": "video"}
                breakdown = perf_service.get_breakdown_by_awareness(
                    brand_id=brand_id,
                    days_back=awareness_days_back,
                    product_id=product_id,
                    min_spend=float(awareness_min_spend),
                    format_filter=fmt_map.get(awareness_format),
                )
                st.session_state.iter_awareness_breakdown = breakdown
                st.session_state.iter_awareness_expanded = None
                st.rerun()
            except Exception as e:
                st.error(f"Analysis failed: {e}")
                return

    breakdown = st.session_state.iter_awareness_breakdown
    if not breakdown:
        st.info(
            "See how your ad spend distributes across awareness levels "
            "(Unaware → Problem Aware → Solution Aware → Product Aware → Most Aware). "
            "Click **Analyze Awareness** to get started."
        )
        return

    levels = breakdown.get("levels", [])
    gaps = breakdown.get("gaps", [])
    total_classified = breakdown.get("total_classified", 0)
    total_unclassified = breakdown.get("total_unclassified", 0)
    total_spend = breakdown.get("total_spend", 0)

    if total_classified == 0:
        st.warning(
            f"No classified ads found. {total_unclassified} ads are unclassified. "
            "Run Ad Intelligence classification first to see awareness breakdown."
        )
        return

    # Classification coverage
    st.markdown(
        f"**{total_classified}** classified ads | "
        f"**{total_unclassified}** unclassified | "
        f"${total_spend:,.0f} total classified spend"
    )

    # Spend allocation bar
    if total_spend > 0:
        bar_parts = []
        colors = {
            "unaware": "#ef4444", "problem_aware": "#f59e0b",
            "solution_aware": "#3b82f6", "product_aware": "#22c55e",
            "most_aware": "#8b5cf6",
        }
        for level in levels:
            share = level["spend_share"]
            if share > 0.02:  # Only show segments > 2%
                color = colors.get(level["awareness_level"], "#6b7280")
                bar_parts.append(
                    f'<div style="background:{color};width:{share*100:.1f}%;height:28px;'
                    f'display:inline-block;text-align:center;color:white;font-size:11px;'
                    f'line-height:28px;overflow:hidden;">'
                    f'{level["label"]} {share*100:.0f}%</div>'
                )
        if bar_parts:
            st.markdown(
                f'<div style="display:flex;border-radius:6px;overflow:hidden;margin:8px 0 16px 0;">{"".join(bar_parts)}</div>',
                unsafe_allow_html=True,
            )

    # Table
    col_widths = [2.2, 0.6, 1.0, 0.7, 0.7, 0.7, 0.7, 0.8, 0.8, 0.8, 0.7]
    headers = ["Awareness Level", "Active/Total", "Spend", "CTR", "ATC%", "CVR", "ROAS", "Agg CPA", "Mean CPA", "Top 75% CPA", "Share"]
    header_cols = st.columns(col_widths)
    for col, h in zip(header_cols, headers):
        with col:
            st.markdown(f"**{h}**")

    for level in levels:
        awareness_level = level["awareness_level"]
        health = _get_awareness_health_icon(level["spend_share"], level["ad_count"])
        is_expanded = st.session_state.iter_awareness_expanded == awareness_level
        has_data = level["ad_count"] > 0
        has_purchases = level.get("purchases", 0) > 0

        row_cols = st.columns(col_widths)
        with row_cols[0]:
            if has_data:
                if st.button(
                    f"{health} {level['label']}",
                    key=f"iter_aw_{awareness_level}",
                    use_container_width=True,
                ):
                    if is_expanded:
                        st.session_state.iter_awareness_expanded = None
                    else:
                        st.session_state.iter_awareness_expanded = awareness_level
                    st.rerun()
            else:
                st.markdown(f"{health} {level['label']}")
        with row_cols[1]:
            active = level.get("active_count", 0)
            total = level["ad_count"]
            st.markdown(f"{active}/{total}" if total > 0 else "0")
        with row_cols[2]:
            st.markdown(f"${level['spend']:,.0f}" if level["spend"] > 0 else "-")
        with row_cols[3]:
            st.markdown(f"{level['ctr']:.1f}%" if has_data else "-")
        with row_cols[4]:
            st.markdown(f"{level.get('atc_rate', 0):.1f}%" if has_data and level.get("atc_rate", 0) > 0 else "-")
        with row_cols[5]:
            st.markdown(f"{level['cvr']:.1f}%" if has_data else "-")
        with row_cols[6]:
            st.markdown(f"{level['roas']:.1f}x" if has_data else "-")
        with row_cols[7]:
            st.markdown(f"${level['cpa']:,.0f}" if has_purchases else "-")
        with row_cols[8]:
            st.markdown(f"${level.get('mean_cpa', 0):,.0f}" if level.get("mean_cpa", 0) > 0 else "-")
        with row_cols[9]:
            st.markdown(f"${level.get('top75_cpa', 0):,.0f}" if level.get("top75_cpa", 0) > 0 else "-")
        with row_cols[10]:
            st.markdown(f"{level['spend_share']*100:.0f}%" if has_data else "0%")

        # Drilldown: top ads for expanded level
        if is_expanded and has_data:
            _render_awareness_drilldown(brand_id, awareness_level, awareness_days_back, product_id, float(awareness_min_spend))

    # Unclassified row
    if total_unclassified > 0:
        row_cols = st.columns(col_widths)
        with row_cols[0]:
            st.markdown(f"⚪ Unclassified")
        with row_cols[1]:
            st.markdown(str(total_unclassified))
        for col in row_cols[2:]:
            with col:
                st.markdown("-")

    # Gap messages
    if gaps:
        st.divider()
        for gap in gaps:
            msg = AWARENESS_GAP_MESSAGES.get(gap, "")
            level_labels = {
                "unaware": "UNAWARE", "problem_aware": "PROBLEM AWARE",
                "solution_aware": "SOLUTION AWARE", "product_aware": "PRODUCT AWARE",
                "most_aware": "MOST AWARE",
            }
            st.warning(f"**Gap: No {level_labels.get(gap, gap)} ads running.** {msg}")

    # Concentration warning
    for level in levels:
        if level["spend_share"] > 0.60 and level["ad_count"] > 0:
            st.warning(
                f"**{level['spend_share']*100:.0f}% of spend on {level['label']}.** "
                "Consider diversifying across awareness levels. "
                "The 60/40 rule suggests ~40% on conversion, ~60% on awareness + consideration."
            )


def _render_awareness_drilldown(
    brand_id: str, awareness_level: str, days_back: int,
    product_id: Optional[str], min_spend: float,
):
    """Render top ads drilldown for a specific awareness level."""
    from viraltracker.services.ad_performance_query_service import AdPerformanceQueryService
    perf_service = AdPerformanceQueryService(get_supabase_client())

    result = perf_service.get_top_ads_by_awareness(
        brand_id=brand_id,
        awareness_level=awareness_level,
        days_back=days_back,
        limit=5,
        product_id=product_id,
        min_spend=min_spend,
    )
    ads = result.get("ads", [])

    if not ads:
        st.caption("No ads found for this awareness level with current filters.")
        return

    # Backfill missing thumbnails
    missing_thumb_ids = [a["meta_ad_id"] for a in ads if not a.get("thumbnail_url")]
    if missing_thumb_ids:
        ads = _backfill_thumbnails(missing_thumb_ids, ads)

    for ad in ads:
        with st.container(border=True):
            col_thumb, col_info = st.columns([1, 5])
            with col_thumb:
                if ad.get("thumbnail_url"):
                    st.image(ad["thumbnail_url"], width=60)
                else:
                    st.markdown("🖼️")
            with col_info:
                name = ad.get("ad_name", "")[:50]
                st.markdown(f"**{name}**" if name else f"`{ad['meta_ad_id']}`")
                st.caption(
                    f"ROAS {ad.get('roas', 0):.1f}x | "
                    f"CTR {ad.get('ctr', 0):.1f}% | "
                    f"CVR {ad.get('cvr', 0):.1f}% | "
                    f"${ad.get('spend', 0):,.0f}"
                )

    # Link to Find Opportunities tab filtered by this awareness level
    level_label = awareness_level.replace("_", " ").title()
    if st.button(
        f"View iteration opportunities for {level_label} ads",
        key=f"iter_awareness_opps_{awareness_level}",
    ):
        st.session_state.iter_awareness_filter = awareness_level
        st.toast(f"Switch to the **Find Opportunities** tab to see {level_label} ads")


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
# TAB 4: STRATEGIC LEVERAGE
# ============================================

CATEGORY_STYLES = {
    "Quick Win": {"icon": "🏆", "color": "green"},
    "Strategic Bet": {"icon": "🔬", "color": "blue"},
    "Explore": {"icon": "💡", "color": "violet"},
}


def render_leverage_tab(brand_id: str, product_id: Optional[str], org_id: str):
    """Render the Strategic Leverage tab — auto-analyzes the account and shows ranked moves."""
    from datetime import datetime, timedelta

    # Auto-run: check if cache is stale (> 30 min) or missing
    cache_ts = st.session_state.iter_leverage_timestamp
    cache_stale = cache_ts is None or (datetime.now() - cache_ts) > timedelta(minutes=30)

    if cache_stale and st.session_state.iter_leverage_data is None:
        _run_leverage_analysis(brand_id, org_id, product_id)

    data = st.session_state.iter_leverage_data

    if data is None:
        st.info("Click **Analyze Account** to find your highest-leverage moves.")
        if st.button("Analyze Account", key="leverage_analyze_btn"):
            _run_leverage_analysis(brand_id, org_id, product_id)
            st.rerun()
        return

    # Header with stats and refresh
    dq = data.get("data_quality", {})
    col_info, col_refresh = st.columns([4, 1])
    with col_info:
        ts = st.session_state.iter_leverage_timestamp
        if ts:
            age = datetime.now() - ts
            age_str = f"{int(age.total_seconds() // 60)} min ago" if age.total_seconds() > 60 else "just now"
        else:
            age_str = "unknown"
        st.markdown(
            f"**Account analyzed** · {dq.get('total_ads', 0)} ads over "
            f"{dq.get('days_of_data', 0)} days · Last run: {age_str}"
        )
    with col_refresh:
        if st.button("🔄 Refresh", key="leverage_refresh_btn"):
            _run_leverage_analysis(brand_id, org_id, product_id)
            st.rerun()

    # Warnings
    for warning in data.get("warnings", []):
        st.warning(warning)

    st.divider()

    # -- Leverage Moves --
    moves = data.get("leverage_moves", [])
    if not moves:
        st.info("No leverage moves found. This can happen if the account has very few ads or data.")
        return

    st.subheader("Your Top Moves")

    acted_set = st.session_state.iter_leverage_acted

    # Split into active and acted-on
    active_moves = [(i, m) for i, m in enumerate(moves) if i not in acted_set]
    acted_moves = [(i, m) for i, m in enumerate(moves) if i in acted_set]

    # Render active moves
    for rank, (idx, move) in enumerate(active_moves, 1):
        style = CATEGORY_STYLES.get(move.move_category, {"icon": "📌", "color": "gray"})
        with st.container():
            st.markdown(
                f"**{style['icon']} {move.move_category.upper()}** · #{rank}"
            )
            st.markdown(f"### {move.title}")

            col_body, col_action = st.columns([3, 1])

            with col_body:
                st.markdown(f"**WHY:** {move.why}")
                st.markdown(f"**EXPECTED RESULT:** {move.expected_outcome}")
                st.markdown(f"**NEXT STEP:** {move.next_step}")

            with col_action:
                confidence_pct = f"{move.confidence:.0%}"
                st.metric("Confidence", confidence_pct)
                st.caption(f"{move.effort} ads recommended")

                if st.button(
                    "Create These Ads →",
                    key=f"leverage_create_{idx}",
                    type="primary",
                ):
                    # Mark as acted on
                    st.session_state.iter_leverage_acted.add(idx)
                    # Set prefill for Ad Creator V2 (Smart Select)
                    st.session_state.prefill_ad_creator_v2 = {
                        "move_title": move.title,
                        "product_id": product_id,
                        "brand_id": brand_id,
                        **move.recommended_action,
                    }
                    # Pre-set brand/product so V2 page picks them up
                    st.session_state.selected_brand_id = brand_id
                    st.switch_page("pages/21b_🎨_Ad_Creator_V2.py")

            st.divider()

    # Render acted-on moves (dimmed)
    if acted_moves:
        st.markdown("---")
        st.caption("Previously acted on")
        for idx, move in acted_moves:
            st.markdown(
                f"~~✅ {move.title}~~ — "
                f"{move.move_category} · {move.effort} ads"
            )

    # -- Account Health Scorecard --
    st.divider()
    st.subheader("Account Health")

    scores = data.get("dimension_scores", {})
    account_score = data.get("account_score", 0)

    score_col1, score_col2, score_col3, score_col4, score_col5 = st.columns(5)
    with score_col1:
        st.metric("Overall", f"{account_score}/100")
    with score_col2:
        st.metric("Awareness", f"{scores.get('awareness_coverage', 0)}")
    with score_col3:
        st.metric("Elements", f"{scores.get('element_diversity', 0)}")
    with score_col4:
        st.metric("Angles", f"{scores.get('angle_coverage', 0)}")
    with score_col5:
        st.metric("Formats", f"{scores.get('format_coverage', 0)}")

    # -- Element Heatmap (only if genome coverage >= 50%) --
    coverage_pct = dq.get("coverage_pct", 0)
    if coverage_pct >= 0.5:
        st.divider()
        st.subheader("Element Performance")
        _render_element_heatmap(data)


def _run_leverage_analysis(brand_id: str, org_id: str, product_id: Optional[str]):
    """Run the leverage analysis and cache results."""
    from datetime import datetime

    service = get_leverage_service()
    with st.spinner("Analyzing your account for leverage opportunities..."):
        try:
            result = service.analyze_account(
                brand_id=brand_id,
                org_id=org_id,
                days_back=30,
                product_id=product_id,
            )
            st.session_state.iter_leverage_data = result
            st.session_state.iter_leverage_timestamp = datetime.now()
        except Exception as e:
            logger.error(f"Leverage analysis failed: {e}", exc_info=True)
            st.error(f"Analysis failed: {e}")


def _render_element_heatmap(data: Dict):
    """Render a simple element performance overview."""
    # This shows top-performing element values across dimensions
    moves = data.get("leverage_moves", [])
    element_moves = [m for m in moves if m.leverage_type in ("element_opportunity", "whitespace")]

    if not element_moves:
        st.caption("Element analysis found no standout patterns yet.")
        return

    for move in element_moves[:5]:
        evidence = move.evidence
        elem_a = evidence.get("element_a", evidence.get("element_name", ""))
        elem_b = evidence.get("element_b", "")
        reward = evidence.get("mean_reward", evidence.get("predicted_potential", 0))

        label = elem_a
        if elem_b:
            label = f"{elem_a} + {elem_b}"

        col1, col2 = st.columns([3, 1])
        with col1:
            st.markdown(f"**{label}**")
            st.caption(move.title)
        with col2:
            st.markdown(f"Score: **{reward:.2f}**")


# ============================================
# TAB 5: CREATIVE INTELLIGENCE
# ============================================

def _render_type_breakdown(hooks_list, label, field_key, pd, st):
    """Render a type/theme breakdown table for a list of hooks."""
    groups = {}
    for h in hooks_list:
        val = h.get(field_key) or h.get("hook_type") or "unknown"
        if isinstance(val, str):
            val = val.replace("_", " ").title()
        else:
            val = "Unknown"
        if val not in groups:
            groups[val] = {"ctrs": [], "count": 0, "total_imp": 0, "total_sales": 0, "total_revenue": 0}
        groups[val]["ctrs"].append(h["ctr"])
        groups[val]["count"] += 1
        groups[val]["total_imp"] += h["impressions"]
        groups[val]["total_sales"] += h.get("purchases", 0)
        groups[val]["total_revenue"] += h.get("purchase_value", 0)

    rows = []
    for val, data in groups.items():
        if data["count"] >= 2:
            avg = sum(data["ctrs"]) / len(data["ctrs"])
            rows.append({
                label: val,
                "Ads": data["count"],
                "Avg CTR": avg,
                "Total Impressions": data["total_imp"],
                "Total Sales": data["total_sales"],
                "Total Revenue": data["total_revenue"],
            })
    rows.sort(key=lambda x: x["Avg CTR"], reverse=True)

    if rows:
        st.markdown(f"**{label} Performance**")
        st.dataframe(
            pd.DataFrame(rows),
            column_config={
                "Avg CTR": st.column_config.NumberColumn("Avg CTR", format="%.3f%%"),
                "Total Impressions": st.column_config.NumberColumn("Total Impressions", format="%d"),
                "Total Sales": st.column_config.NumberColumn("Total Sales", format="%d"),
                "Total Revenue": st.column_config.NumberColumn("Total Revenue", format="$%.2f"),
            },
            use_container_width=True,
            hide_index=True,
        )


def render_creative_intelligence_tab(brand_id: str, org_id: str, product_id: str = None):
    """Render the Creative Intelligence tab — hook leaderboard + correlation dashboard."""
    import pandas as pd

    service = get_correlation_service()

    # Check analysis coverage
    try:
        image_count = service.supabase.table("ad_image_analysis").select(
            "id", count="exact"
        ).eq("brand_id", brand_id).eq("status", "ok").execute()
        video_count = service.supabase.table("ad_video_analysis").select(
            "id", count="exact"
        ).eq("brand_id", brand_id).eq("status", "ok").execute()
        n_images = image_count.count or 0
        n_videos = video_count.count or 0
    except Exception:
        n_images = 0
        n_videos = 0

    st.markdown(
        f"**{n_images} image ads** and **{n_videos} video ads** deep-analyzed"
    )

    if n_images == 0 and n_videos == 0:
        st.info(
            "No ads have been deep-analyzed yet. Schedule a **Creative Deep Analysis** "
            "job in the Ad Scheduler to get started."
        )
        return

    # ── Global filters ──
    filter_col1, filter_col2 = st.columns(2)
    with filter_col1:
        source_options = {"All": None, "🖼️ Images Only": "image", "🎬 Videos Only": "video"}
        source_choice = st.selectbox(
            "Format",
            list(source_options.keys()),
            key="ci_global_source_filter",
        )
        source_filter = source_options[source_choice]

    with filter_col2:
        if product_id:
            # Show which product is filtering
            try:
                prod = service.supabase.table("products").select("name").eq(
                    "id", product_id
                ).limit(1).execute()
                prod_name = prod.data[0]["name"] if prod.data else "Selected product"
            except Exception:
                prod_name = "Selected product"
            st.info(f"Filtered to product: **{prod_name}**")
        else:
            st.caption("Select a product above to filter by product.")

    # Cache hooks in session state for 30 min (keyed by filters)
    cache_key = f"ci_hooks_{brand_id}_{product_id}_{source_filter}"
    cache_ts_key = f"ci_hooks_ts_{brand_id}_{product_id}_{source_filter}"
    from datetime import datetime, timedelta

    hooks_stale = (
        cache_key not in st.session_state
        or cache_ts_key not in st.session_state
        or (datetime.now() - st.session_state[cache_ts_key]) > timedelta(minutes=30)
    )

    if hooks_stale:
        with st.spinner("Loading creative performance..."):
            hooks = service.get_hook_performance(
                brand_id, days_back=60, min_impressions=500,
                product_id=product_id, source_filter=source_filter,
            )
            st.session_state[cache_key] = hooks
            st.session_state[cache_ts_key] = datetime.now()
    else:
        hooks = st.session_state[cache_key]

    # ── Shared Filters ──
    if hooks:
        fcol1, fcol2, fcol3 = st.columns(3)
        with fcol1:
            min_imp = st.number_input(
                "Min impressions",
                min_value=0,
                value=500,
                step=500,
                key="ci_min_impressions",
            )
        with fcol2:
            min_sales = st.number_input(
                "Min sales",
                min_value=0,
                value=0,
                step=1,
                key="ci_min_sales",
            )
        with fcol3:
            sort_by = st.selectbox(
                "Sort by",
                ["CTR", "Impressions", "Sales", "Revenue", "ROAS"],
                key="ci_sort_by",
            )

        all_filtered = [
            h for h in hooks
            if h["impressions"] >= min_imp
            and h.get("purchases", 0) >= min_sales
        ]

        sort_keys = {
            "CTR": lambda h: h["ctr"],
            "Impressions": lambda h: h["impressions"],
            "Sales": lambda h: h.get("purchases", 0),
            "Revenue": lambda h: h.get("purchase_value", 0),
            "ROAS": lambda h: h.get("roas", 0),
        }
        all_filtered.sort(key=sort_keys[sort_by], reverse=True)

        video_hooks = [h for h in all_filtered if h["source"] == "video"]
        image_hooks = [h for h in all_filtered if h["source"] == "image"]

        # Shared column config for both tables
        base_col_config = {
            "CTR": st.column_config.NumberColumn("CTR", format="%.3f%%"),
            "Impressions": st.column_config.NumberColumn("Impressions", format="%d"),
            "Sales": st.column_config.NumberColumn("Sales", format="%d"),
            "Revenue": st.column_config.NumberColumn("Revenue", format="$%.2f"),
            "ROAS": st.column_config.NumberColumn("ROAS", format="%.2fx"),
        }

        # ── Video Hook Leaderboard ──
        if video_hooks and source_filter != "image":
            st.subheader("🎬 Video Hook Leaderboard")
            st.caption("Which video hooks grab the most attention? Ranked by thumb-stop rate.")

            best_v = video_hooks[0]
            avg_ctr_v = sum(h["ctr"] for h in video_hooks) / len(video_hooks)
            if avg_ctr_v > 0:
                mult = best_v["ctr"] / avg_ctr_v
                st.success(
                    f"**Top hook:** \"{best_v['hook_text'][:80]}\" — "
                    f"**{best_v['ctr']:.2%} CTR** ({mult:.1f}x your average)"
                )

            vid_rows = []
            for h in video_hooks:
                ad_name = h.get("ad_name") or h["meta_ad_id"][:12]
                adset = h.get("adset_name") or ""
                campaign = h.get("campaign_name") or ""
                context = " / ".join(p for p in [adset, campaign] if p)
                vid_rows.append({
                    "Ad Name": ad_name,
                    "Ad Set / Campaign": context,
                    "Hook": h["hook_text"][:120] + ("..." if len(h["hook_text"]) > 120 else ""),
                    "Hook Type": (h.get("hook_type") or "unknown").replace("_", " ").title(),
                    "CTR": h["ctr"],
                    "Hook Rate": h.get("hook_rate", 0),
                    "Hold Rate": h.get("hold_rate", 0),
                    "Impressions": h["impressions"],
                    "Sales": h.get("purchases", 0),
                    "Revenue": h.get("purchase_value", 0),
                    "ROAS": h.get("roas", 0),
                })

            vid_config = {
                **base_col_config,
                "Hook Rate": st.column_config.NumberColumn(
                    "Hook Rate", format="%.1f%%",
                    help="% of viewers who watched past 3 seconds",
                ),
                "Hold Rate": st.column_config.NumberColumn(
                    "Hold Rate", format="%.1f%%",
                    help="% of viewers who watched to completion",
                ),
            }
            st.dataframe(
                pd.DataFrame(vid_rows),
                column_config=vid_config,
                use_container_width=True,
                hide_index=True,
            )
            st.caption(f"Showing {len(vid_rows)} video hooks")

            # Hook type breakdown for videos
            _render_type_breakdown(video_hooks, "Hook Type", "hook_type", pd, st)
            st.divider()

        # ── Image Messaging Leaderboard ──
        if image_hooks and source_filter != "video":
            st.subheader("🖼️ Image Messaging Leaderboard")
            st.caption("Which headlines and messaging themes drive the most clicks on your image ads?")

            best_i = image_hooks[0]
            avg_ctr_i = sum(h["ctr"] for h in image_hooks) / len(image_hooks)
            if avg_ctr_i > 0:
                mult = best_i["ctr"] / avg_ctr_i
                st.success(
                    f"**Top headline:** \"{best_i['hook_text'][:80]}\" — "
                    f"**{best_i['ctr']:.2%} CTR** ({mult:.1f}x your average)"
                )

            img_rows = []
            for h in image_hooks:
                ad_name = h.get("ad_name") or h["meta_ad_id"][:12]
                adset = h.get("adset_name") or ""
                campaign = h.get("campaign_name") or ""
                context = " / ".join(p for p in [adset, campaign] if p)
                theme = (h.get("messaging_theme") or "").replace("_", " ").title()
                img_rows.append({
                    "Ad Name": ad_name,
                    "Ad Set / Campaign": context,
                    "Headline": h["hook_text"][:120] + ("..." if len(h["hook_text"]) > 120 else ""),
                    "Messaging Theme": theme,
                    "CTR": h["ctr"],
                    "Impressions": h["impressions"],
                    "Sales": h.get("purchases", 0),
                    "Revenue": h.get("purchase_value", 0),
                    "ROAS": h.get("roas", 0),
                    "Awareness": (h.get("awareness_level") or "").replace("_", " ").title(),
                    "Tone": ", ".join(h.get("emotional_tone", [])[:2]),
                })

            st.dataframe(
                pd.DataFrame(img_rows),
                column_config=base_col_config,
                use_container_width=True,
                hide_index=True,
            )
            st.caption(f"Showing {len(img_rows)} image ads")

            # Messaging theme breakdown for images
            _render_type_breakdown(image_hooks, "Messaging Theme", "messaging_theme", pd, st)
            st.divider()

        if not video_hooks and not image_hooks:
            st.info("No ads match the current filters.")
            st.divider()
    else:
        st.info("No ads found with sufficient impressions. Run Creative Deep Analysis on more ads.")
        st.divider()

    # ── Correlation Dashboard ──
    st.subheader("📊 Performance Correlations")
    st.caption(
        "Which creative elements drive the best results? "
        "Sorted by performance vs account average."
    )

    # Cache correlations (keyed by filters)
    corr_key = f"ci_correlations_{brand_id}_{source_filter}"
    corr_ts_key = f"ci_correlations_ts_{brand_id}_{source_filter}"

    corr_stale = (
        corr_key not in st.session_state
        or corr_ts_key not in st.session_state
        or (datetime.now() - st.session_state[corr_ts_key]) > timedelta(minutes=30)
    )

    if corr_stale:
        with st.spinner("Loading correlations..."):
            correlations = service.get_top_correlations(
                brand_id, min_confidence=0.2, limit=50,
                source_filter=source_filter,
            )
            st.session_state[corr_key] = correlations
            st.session_state[corr_ts_key] = datetime.now()
    else:
        correlations = st.session_state[corr_key]

    if correlations:
        # Field filter
        all_fields = sorted(set(c["analysis_field"] for c in correlations))
        field_labels = {f: f.replace("_", " ").replace("visual ", "").title() for f in all_fields}

        selected_field = st.selectbox(
            "Filter by dimension",
            ["All"] + all_fields,
            format_func=lambda x: "All Dimensions" if x == "All" else field_labels.get(x, x),
            key="ci_corr_field_filter",
        )

        filtered = correlations
        if selected_field != "All":
            filtered = [c for c in correlations if c["analysis_field"] == selected_field]

        corr_rows = []
        for c in filtered:
            vs_avg = c.get("vs_account_avg", 1.0)
            # Color indicator
            if vs_avg >= 1.5:
                indicator = "🟢"
            elif vs_avg >= 1.0:
                indicator = "🟡"
            else:
                indicator = "🔴"

            corr_rows.append({
                "": indicator,
                "Dimension": c["analysis_field"].replace("_", " ").replace("visual ", "").title(),
                "Value": c["field_value"].replace("_", " ").title(),
                "Ads": c["ad_count"],
                "Avg CTR": c.get("mean_ctr", 0),
                "Avg ROAS": c.get("mean_roas", 0),
                "vs Account": vs_avg,
                "Confidence": c.get("confidence", 0),
                "Source": "🖼️" if "image" in c.get("source_table", "") else "🎬",
            })

        if corr_rows:
            st.dataframe(
                pd.DataFrame(corr_rows),
                column_config={
                    "Avg CTR": st.column_config.NumberColumn("Avg CTR", format="%.3f%%"),
                    "Avg ROAS": st.column_config.NumberColumn("Avg ROAS", format="%.2fx"),
                    "vs Account": st.column_config.NumberColumn(
                        "vs Account Avg", format="%.2fx"
                    ),
                    "Confidence": st.column_config.ProgressColumn(
                        "Confidence", min_value=0, max_value=1, format="%.0%%"
                    ),
                },
                use_container_width=True,
                hide_index=True,
            )

            # Summary insight
            top_performers = [c for c in filtered if c.get("vs_account_avg", 0) >= 1.5]
            if top_performers:
                st.markdown("**Key Insights:**")
                for c in top_performers[:5]:
                    field = c["analysis_field"].replace("_", " ").title()
                    value = c["field_value"].replace("_", " ").title()
                    vs = c.get("vs_account_avg", 1.0)
                    n = c["ad_count"]
                    st.markdown(
                        f"- **{value}** ({field}) performs **{vs:.1f}x** better "
                        f"than average across {n} ads"
                    )
        else:
            st.info("No correlations found for this filter.")
    else:
        st.info(
            "No correlations computed yet. Run a **Creative Deep Analysis** job "
            "to analyze ads and compute performance correlations."
        )

    # ── Performance Heatmap ──
    if correlations:
        st.divider()
        st.subheader("🗺️ Performance Heatmap")
        st.caption("Visual overview of how each creative element performs vs account average.")

        try:
            import plotly.graph_objects as go

            # Group correlations by dimension
            dimensions = {}
            for c in correlations:
                dim = c["analysis_field"].replace("_", " ").replace("visual ", "").title()
                if dim not in dimensions:
                    dimensions[dim] = []
                dimensions[dim].append(c)

            # Build heatmap data — one row per field value, columns = CTR vs avg, ROAS vs avg
            heatmap_values = []
            heatmap_labels = []
            heatmap_dimensions = []
            acct_ctr = None
            acct_roas = None

            # Compute account averages from correlation data for reference
            for dim_name, dim_corrs in sorted(dimensions.items()):
                for c in sorted(dim_corrs, key=lambda x: x.get("vs_account_avg", 1), reverse=True):
                    label = c["field_value"].replace("_", " ").title()
                    vs = c.get("vs_account_avg", 1.0)
                    n = c.get("ad_count", 0)
                    heatmap_labels.append(f"{label} ({n})")
                    heatmap_dimensions.append(dim_name)
                    heatmap_values.append(vs)

            if heatmap_labels:
                # Color scale: red (underperform) → white (average) → green (outperform)
                fig = go.Figure(data=go.Heatmap(
                    z=[heatmap_values],
                    x=heatmap_labels,
                    y=["vs Account Avg"],
                    colorscale=[
                        [0, "#ef4444"],
                        [0.5, "#fafafa"],
                        [1, "#22c55e"],
                    ],
                    zmid=1.0,
                    text=[[f"{v:.2f}x" for v in heatmap_values]],
                    texttemplate="%{text}",
                    textfont={"size": 11},
                    hovertemplate="%{x}<br>%{z:.2f}x vs avg<extra></extra>",
                    colorbar=dict(title="vs Avg", ticksuffix="x"),
                ))
                fig.update_layout(
                    height=150,
                    margin=dict(l=20, r=20, t=10, b=80),
                    xaxis=dict(tickangle=-45, tickfont=dict(size=10)),
                )
                st.plotly_chart(fig, use_container_width=True)

                # Dimension-grouped detail heatmap
                if len(dimensions) > 1:
                    for dim_name, dim_corrs in sorted(dimensions.items()):
                        if len(dim_corrs) < 2:
                            continue
                        sorted_corrs = sorted(dim_corrs, key=lambda x: x.get("vs_account_avg", 1), reverse=True)
                        labels = [c["field_value"].replace("_", " ").title() for c in sorted_corrs]
                        vals = [c.get("vs_account_avg", 1.0) for c in sorted_corrs]
                        counts = [c.get("ad_count", 0) for c in sorted_corrs]

                        fig2 = go.Figure(data=go.Bar(
                            x=labels,
                            y=vals,
                            text=[f"{v:.2f}x ({n})" for v, n in zip(vals, counts)],
                            textposition="auto",
                            marker_color=[
                                "#22c55e" if v >= 1.5 else "#eab308" if v >= 1.0 else "#ef4444"
                                for v in vals
                            ],
                        ))
                        fig2.update_layout(
                            title=dict(text=dim_name, font=dict(size=14)),
                            height=250,
                            margin=dict(l=20, r=20, t=40, b=40),
                            yaxis=dict(title="vs Account Avg"),
                            showlegend=False,
                        )
                        # Add baseline at 1.0x
                        fig2.add_hline(y=1.0, line_dash="dash", line_color="gray", opacity=0.5)
                        st.plotly_chart(fig2, use_container_width=True)

        except ImportError:
            st.warning("Install plotly for heatmap visualization: `pip install plotly`")

    # ── Combination Analysis + Winning Recipes ──
    st.divider()
    st.subheader("🧪 Creative Combinations")
    st.caption(
        "Which combinations of creative elements work best together? "
        "Finds synergistic pairs that outperform their individual components."
    )

    combo_key = f"ci_combos_{brand_id}_{product_id}_{source_filter}"
    combo_ts_key = f"ci_combos_ts_{brand_id}_{product_id}_{source_filter}"

    combo_stale = (
        combo_key not in st.session_state
        or combo_ts_key not in st.session_state
        or (datetime.now() - st.session_state[combo_ts_key]) > timedelta(minutes=30)
    )

    if combo_stale:
        with st.spinner("Analyzing creative combinations..."):
            combo_result = service.get_combination_performance(
                brand_id, days_back=60, min_ads=3,
                product_id=product_id, source_filter=source_filter,
            )
            st.session_state[combo_key] = combo_result
            st.session_state[combo_ts_key] = datetime.now()
    else:
        combo_result = st.session_state[combo_key]

    combos = combo_result.get("combinations", [])
    recipes = combo_result.get("recipes", [])

    # Winning Recipes callout
    if recipes:
        st.markdown("#### 🏆 Winning Recipes")
        st.caption("Your top-performing creative combinations — use these as a starting point for new ads.")
        for i, r in enumerate(recipes, 1):
            fa = r["field_a"].replace("_", " ").title()
            va = r["value_a"].replace("_", " ").title()
            fb = r["field_b"].replace("_", " ").title()
            vb = r["value_b"].replace("_", " ").title()
            fmt = "🖼️" if r["source"] == "image" else "🎬"
            st.success(
                f"**Recipe #{i}** {fmt}: **{va}** ({fa}) + **{vb}** ({fb}) — "
                f"**{r['vs_avg']:.1f}x** vs account avg "
                f"({r['ad_count']} ads, {r['total_impressions']:,} impressions)"
            )
        st.markdown("")

    # Full combination table
    if combos:
        combo_rows = []
        for c in combos:
            vs = c["vs_avg"]
            if vs >= 1.5:
                indicator = "🟢"
            elif vs >= 1.0:
                indicator = "🟡"
            else:
                indicator = "🔴"

            combo_rows.append({
                "": indicator,
                "Element 1": f"{c['value_a'].replace('_', ' ').title()} ({c['field_a'].replace('_', ' ').title()})",
                "Element 2": f"{c['value_b'].replace('_', ' ').title()} ({c['field_b'].replace('_', ' ').title()})",
                "Ads": c["ad_count"],
                "Avg CTR": c["mean_ctr"],
                "Avg ROAS": c["mean_roas"],
                "vs Account": c["vs_avg"],
                "Confidence": c["confidence"],
                "Format": "🖼️" if c["source"] == "image" else "🎬",
            })

        st.dataframe(
            pd.DataFrame(combo_rows),
            column_config={
                "Avg CTR": st.column_config.NumberColumn("Avg CTR", format="%.3f%%"),
                "Avg ROAS": st.column_config.NumberColumn("Avg ROAS", format="%.2fx"),
                "vs Account": st.column_config.NumberColumn("vs Account Avg", format="%.2fx"),
                "Confidence": st.column_config.ProgressColumn(
                    "Confidence", min_value=0, max_value=1, format="%.0%%"
                ),
            },
            use_container_width=True,
            hide_index=True,
        )
        st.caption(f"Showing {len(combo_rows)} combinations with 3+ ads")
    else:
        st.info("Not enough data for combination analysis. Need at least 3 ads sharing element pairs.")

    # Refresh button
    st.divider()
    if st.button("🔄 Recompute Correlations", key="ci_recompute_btn"):
        with st.spinner("Recomputing correlations (this may take a minute)..."):
            try:
                result = service.compute_correlations(
                    brand_id, org_id, days_back=60,
                    source_filter=source_filter,
                )
                st.success(
                    f"Computed {result.get('correlations', 0)} correlations from "
                    f"{result.get('image_ads_analyzed', 0)} images and "
                    f"{result.get('video_ads_analyzed', 0)} videos"
                )
                # Clear all CI caches to reload
                keys_to_clear = [k for k in st.session_state if k.startswith("ci_")]
                for k in keys_to_clear:
                    st.session_state.pop(k, None)
                st.rerun()
            except Exception as e:
                st.error(f"Correlation computation failed: {e}")


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

# Session state invalidation on brand/product change
cache_key = f"{brand_id}:{product_id}"
if st.session_state.get("iter_cache_key") != cache_key:
    st.session_state.iter_opportunities = None
    st.session_state.iter_cross_winner_result = None
    st.session_state.iter_awareness_breakdown = None
    st.session_state.iter_awareness_expanded = None
    st.session_state.iter_per_winner_result = None
    st.session_state.iter_scan_done = False
    st.session_state.iter_awareness_filter = None
    st.session_state.iter_leverage_data = None
    st.session_state.iter_leverage_timestamp = None
    st.session_state.iter_leverage_acted = set()
    st.session_state.iter_cache_key = cache_key

# Tabs
tab1, tab2, tab3, tab4, tab5 = st.tabs([
    "💡 Find Opportunities",
    "🧬 Analyze Winners",
    "📊 Awareness Coverage",
    "🎯 Strategic Leverage",
    "🔍 Creative Intelligence",
])

with tab1:
    st.caption("Find ads that are almost great and make them better.")
    render_opportunities_tab(brand_id, product_id, org_id)
    st.divider()
    st.caption("Want to understand why your winners work? See **Analyze Winners** tab.")

with tab2:
    st.caption("Understand what your best ads have in common.")
    render_winners_tab(brand_id, product_id, org_id)
    st.divider()
    st.caption("Ready to iterate? See **Find Opportunities** tab.")

with tab3:
    st.caption("See how your ad spend and performance distribute across consumer awareness levels.")
    render_awareness_tab(brand_id, product_id, org_id)

with tab4:
    st.caption("Find the highest-leverage moves to improve your ad account.")
    render_leverage_tab(brand_id, product_id, org_id)

with tab5:
    st.caption("See which hooks, tones, and creative elements drive the best performance.")
    render_creative_intelligence_tab(brand_id, org_id, product_id)
