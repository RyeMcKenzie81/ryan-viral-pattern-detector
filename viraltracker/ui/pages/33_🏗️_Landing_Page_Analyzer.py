"""
Landing Page Analyzer — Analyze landing pages with a 4+1 skill AI pipeline.

Skills:
1. Page Classifier (awareness, sophistication, architecture)
2. Element Detector (34 elements across 6 sections)
3. Gap Analyzer (missing elements vs ideal set)
4. Copy Scorer (per-element quality scoring)
5. Reconstruction Blueprint (maps analysis to brand-specific creative brief)

Tab 1: Analyze — Input a URL or load from existing LPs, run analysis
Tab 2: Results — View past analyses with expandable detail
Tab 3: Blueprint — Generate brand-specific reconstruction blueprints
"""

import streamlit as st
import asyncio
from datetime import datetime

st.set_page_config(page_title="Landing Page Analyzer", page_icon="🏗️", layout="wide")

from viraltracker.ui.auth import require_auth
require_auth()

# Session state
if "lpa_analysis_running" not in st.session_state:
    st.session_state.lpa_analysis_running = False
if "lpa_latest_result" not in st.session_state:
    st.session_state.lpa_latest_result = None
if "lpa_latest_blueprint" not in st.session_state:
    st.session_state.lpa_latest_blueprint = None


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def get_supabase_client():
    from viraltracker.core.database import get_supabase_client
    return get_supabase_client()


def get_analysis_service():
    from viraltracker.services.landing_page_analysis import LandingPageAnalysisService
    return LandingPageAnalysisService(get_supabase_client())


def get_blueprint_service():
    from viraltracker.services.landing_page_analysis import ReconstructionBlueprintService
    return ReconstructionBlueprintService(get_supabase_client())


def _grade_color(grade: str) -> str:
    """Return a color for copy score grade badges."""
    if not grade:
        return "gray"
    g = grade.upper().rstrip("+")
    return {"A": "green", "B": "blue", "C": "orange", "D": "red", "F": "red"}.get(g, "gray")


def _risk_color(risk: str) -> str:
    return {"critical": "🔴", "moderate": "🟡", "low": "🟢"}.get(risk, "⚪")


def _awareness_badge(level: str) -> str:
    badges = {
        "unaware": "⬜ Unaware",
        "problem_aware": "🟨 Problem-Aware",
        "solution_aware": "🟦 Solution-Aware",
        "product_aware": "🟩 Product-Aware",
        "most_aware": "🟪 Most-Aware",
    }
    return badges.get(level, level or "Unknown")


# ---------------------------------------------------------------------------
# Tab 1: Analyze
# ---------------------------------------------------------------------------

def render_analyze_tab(brand_id: str, org_id: str):
    """Render the analysis input and execution UI."""
    st.subheader("Analyze a Landing Page")

    source = st.radio(
        "Content Source",
        ["Enter URL", "From Competitor LPs", "From Brand LPs"],
        horizontal=True,
        key="lpa_source",
    )

    service = get_analysis_service()
    page_data = None

    if source == "Enter URL":
        url = st.text_input("Landing Page URL", placeholder="https://example.com/landing-page", key="lpa_url")
        if url and st.button("Scrape & Analyze", type="primary", key="lpa_analyze_url"):
            page_data = _scrape_and_analyze(service, url, org_id)

    elif source == "From Competitor LPs":
        competitor_lps = service.get_competitor_lps(brand_id)
        if not competitor_lps:
            st.info("No competitor landing pages found. Scrape some via Competitor Research first.")
            return
        options = {
            lp["id"]: f"{lp.get('competitors', {}).get('name', 'Unknown')} — {lp['url'][:60]}"
            for lp in competitor_lps
        }
        selected = st.selectbox("Select Competitor LP", options.keys(), format_func=lambda x: options[x], key="lpa_comp_select")
        if selected and st.button("Analyze", type="primary", key="lpa_analyze_comp"):
            page_data = _load_and_analyze(service, "competitor_lp", selected, org_id)

    elif source == "From Brand LPs":
        brand_lps = service.get_brand_lps(brand_id)
        if not brand_lps:
            st.info("No brand landing pages found. Scrape some via Brand Research first.")
            return
        options = {lp["id"]: f"{lp.get('page_title', 'Untitled')} — {lp['url'][:60]}" for lp in brand_lps}
        selected = st.selectbox("Select Brand LP", options.keys(), format_func=lambda x: options[x], key="lpa_brand_select")
        if selected and st.button("Analyze", type="primary", key="lpa_analyze_brand"):
            page_data = _load_and_analyze(service, "brand_lp", selected, org_id)


def _scrape_and_analyze(service, url: str, org_id: str):
    """Scrape URL then run analysis with progress."""
    progress = st.progress(0, text="Scraping page...")
    try:
        page_data = service.scrape_landing_page(url)
        progress.progress(10, text="Page scraped. Starting analysis...")
        _run_analysis(service, page_data, org_id, progress)
    except Exception as e:
        st.error(f"Failed: {e}")


def _load_and_analyze(service, source_type: str, source_id: str, org_id: str):
    """Load from existing LP record then analyze."""
    progress = st.progress(0, text="Loading content...")
    try:
        if source_type == "competitor_lp":
            page_data = service.load_from_competitor_lp(source_id)
        else:
            page_data = service.load_from_brand_lp(source_id)
        progress.progress(10, text="Content loaded. Starting analysis...")
        _run_analysis(service, page_data, org_id, progress)
    except Exception as e:
        st.error(f"Failed: {e}")


def _run_analysis(service, page_data: dict, org_id: str, progress):
    """Execute the 4-skill pipeline with progress tracking."""
    step_progress = {1: 25, 2: 50, 3: 75, 4: 100}
    step_labels = {
        1: "Step 1/4: Classifying page...",
        2: "Step 2/4: Detecting elements...",
        3: "Step 3/4: Analyzing gaps & scoring copy...",
        4: "Analysis complete!",
    }

    def on_progress(step, msg):
        pct = step_progress.get(step, 0)
        label = step_labels.get(step, msg)
        progress.progress(pct / 100, text=label)

    # Set up tracking context
    try:
        from viraltracker.ui.utils import get_current_organization_id
        from viraltracker.services.usage_tracker import UsageTracker
        tracker = UsageTracker(get_supabase_client())
        user_id = st.session_state.get("user_id")
        service.set_tracking_context(tracker, user_id, org_id)
    except Exception:
        pass

    result = asyncio.run(
        service.run_full_analysis(
            page_content=page_data["markdown"],
            page_url=page_data["url"],
            org_id=org_id,
            screenshot_b64=page_data.get("screenshot"),
            source_type=page_data.get("source_type", "url"),
            source_id=page_data.get("source_id"),
            progress_callback=on_progress,
        )
    )

    st.session_state.lpa_latest_result = result
    progress.progress(1.0, text="Done!")

    # Show quick summary
    _render_quick_summary(result)


def _render_quick_summary(result: dict):
    """Show a quick summary card after analysis completes."""
    st.success(f"Analysis complete in {result.get('processing_time_ms', 0) / 1000:.1f}s")

    col1, col2, col3, col4 = st.columns(4)

    classification = result.get("classification", {})
    pc = classification.get("page_classifier", classification)
    al = pc.get("awareness_level", {})

    with col1:
        level = al.get("primary", "") if isinstance(al, dict) else al
        st.metric("Awareness", _awareness_badge(level))

    with col2:
        elements = result.get("elements", {})
        ed = elements.get("element_detection", elements) if elements else {}
        st.metric("Elements", ed.get("total_elements_detected", 0))

    gap = result.get("gap_analysis", {})
    ga = gap.get("gap_analysis", gap) if gap else {}
    with col3:
        st.metric("Completeness", f"{ga.get('overall_completeness_score', '—')}/100")

    scores = result.get("copy_scores", {})
    cs = scores.get("copy_score", scores) if scores else {}
    with col4:
        grade = cs.get("overall_grade", "—")
        score = cs.get("overall_score", "—")
        st.metric("Copy Grade", f"{grade} ({score}/100)")


# ---------------------------------------------------------------------------
# Tab 2: Results
# ---------------------------------------------------------------------------

def render_results_tab(org_id: str):
    """Render past analysis results."""
    st.subheader("Analysis History")

    service = get_analysis_service()
    analyses = service.list_analyses(org_id)

    if not analyses:
        st.info("No analyses yet. Use the Analyze tab to get started.")
        return

    for analysis in analyses:
        _render_analysis_row(analysis, service)


def _render_analysis_row(analysis: dict, service):
    """Render a single analysis as an expandable row."""
    url = analysis.get("url", "Unknown")
    grade = analysis.get("overall_grade", "—")
    score = analysis.get("overall_score")
    status = analysis.get("status", "unknown")
    created = analysis.get("created_at", "")
    awareness = analysis.get("awareness_level", "")
    completeness = analysis.get("completeness_score")

    # Format date
    if created:
        try:
            dt = datetime.fromisoformat(created.replace("Z", "+00:00"))
            created_str = dt.strftime("%b %d, %Y %I:%M %p")
        except Exception:
            created_str = created[:19]
    else:
        created_str = ""

    # Status badge
    status_icon = {"completed": "✅", "partial": "⚠️", "failed": "❌", "processing": "⏳"}.get(status, "❓")

    header = f"{status_icon} **{url[:70]}** — {_awareness_badge(awareness)} — Grade: **{grade}** — {created_str}"

    with st.expander(header, expanded=False):
        # Load full analysis on expand
        full = service.get_analysis(analysis["id"])
        if not full:
            st.error("Could not load analysis details.")
            return

        _render_analysis_detail(full)


def _render_analysis_detail(analysis: dict):
    """Render full analysis detail with sub-tabs."""
    detail_tabs = st.tabs(["Classification", "Elements", "Gaps", "Copy Scores"])

    # --- Classification ---
    with detail_tabs[0]:
        classification = analysis.get("classification", {})
        pc = classification.get("page_classifier", classification)

        if not pc:
            st.info("Classification not available.")
        else:
            col1, col2, col3 = st.columns(3)
            al = pc.get("awareness_level", {})
            ms = pc.get("market_sophistication", {})
            pa = pc.get("page_architecture", {})

            with col1:
                level = al.get("primary", "") if isinstance(al, dict) else al
                st.markdown(f"**Awareness Level:** {_awareness_badge(level)}")
                conf = al.get("confidence", "") if isinstance(al, dict) else ""
                if conf:
                    st.caption(f"Confidence: {conf}")
                evidence = al.get("evidence", []) if isinstance(al, dict) else []
                if evidence:
                    st.markdown("**Evidence:**")
                    for e in evidence:
                        st.markdown(f"- {e}")

            with col2:
                soph_level = ms.get("level", "?") if isinstance(ms, dict) else ms
                st.markdown(f"**Market Sophistication:** Level {soph_level}/5")
                ms_notes = ms.get("notes", "") if isinstance(ms, dict) else ""
                if ms_notes:
                    st.caption(ms_notes)

            with col3:
                arch_type = pa.get("type", "?") if isinstance(pa, dict) else pa
                st.markdown(f"**Architecture:** {arch_type}")
                word_count = pa.get("estimated_word_count", "") if isinstance(pa, dict) else ""
                if word_count:
                    st.caption(f"Word count: {word_count}")

            # Persona
            persona = pc.get("buyer_persona", {})
            if persona and persona.get("persona_name"):
                st.markdown("---")
                st.markdown(f"**Buyer Persona:** {persona.get('persona_name', '')}")
                st.caption(persona.get("core_identity", ""))

                pcol1, pcol2 = st.columns(2)
                with pcol1:
                    pains = persona.get("key_pain_points", [])
                    if pains:
                        st.markdown("**Pain Points:**")
                        for p in pains:
                            st.markdown(f"- {p}")
                with pcol2:
                    desires = persona.get("key_desires", [])
                    if desires:
                        st.markdown("**Desires:**")
                        for d in desires:
                            st.markdown(f"- {d}")

    # --- Elements ---
    with detail_tabs[1]:
        elements = analysis.get("elements", {})
        ed = elements.get("element_detection", elements) if elements else {}

        if not ed:
            st.info("Element detection not available.")
        else:
            st.metric("Total Elements Detected", ed.get("total_elements_detected", 0))

            counts = ed.get("element_count_by_section", {})
            if counts:
                cols = st.columns(len(counts))
                for i, (section, count) in enumerate(counts.items()):
                    with cols[i]:
                        label = section.replace("_", " ").title()
                        st.metric(label, count)

            sections = ed.get("sections", {})
            for section_name, section_data in sections.items():
                section_elements = section_data if isinstance(section_data, list) else section_data.get("elements_found", [])
                if section_elements:
                    st.markdown(f"**{section_name.replace('_', ' ').title()}**")
                    for elem in section_elements:
                        name = elem.get("element_name", "?")
                        etype = elem.get("element_type", "")
                        summary = elem.get("content_summary", "")
                        st.markdown(f"- **{name}** ({etype}): {summary}")

    # --- Gaps ---
    with detail_tabs[2]:
        gaps = analysis.get("gap_analysis", {})
        ga = gaps.get("gap_analysis", gaps) if gaps else {}

        if not ga:
            st.info("Gap analysis not available.")
        else:
            col1, col2 = st.columns(2)
            with col1:
                st.metric("Completeness Score", f"{ga.get('overall_completeness_score', '—')}/100")
            with col2:
                risk = ga.get("overall_risk_level", "")
                st.metric("Risk Level", f"{_risk_color(risk)} {risk.title()}")

            critical = ga.get("critical_gaps", [])
            if critical:
                st.markdown("### 🔴 Critical Gaps")
                for gap_item in critical:
                    st.markdown(f"**{gap_item.get('element_name', '?')}** — {gap_item.get('why_missing_matters', '')}")
                    st.caption(f"Recommendation: {gap_item.get('recommendation', '')}")

            moderate = ga.get("moderate_gaps", [])
            if moderate:
                st.markdown("### 🟡 Moderate Gaps")
                for gap_item in moderate:
                    st.markdown(f"**{gap_item.get('element_name', '?')}** — {gap_item.get('why_missing_matters', '')}")

            quick_wins = ga.get("quick_wins", [])
            if quick_wins:
                st.markdown("### 🟢 Quick Wins")
                for qw in quick_wins:
                    effort = qw.get("estimated_effort", "")
                    impact = qw.get("estimated_impact", "")
                    st.markdown(f"- **{qw.get('action', '')}** (effort: {effort}, impact: {impact})")

    # --- Copy Scores ---
    with detail_tabs[3]:
        scores = analysis.get("copy_scores", {})
        cs = scores.get("copy_score", scores) if scores else {}

        if not cs:
            st.info("Copy scoring not available.")
        else:
            col1, col2, col3 = st.columns(3)
            with col1:
                st.metric("Overall Score", f"{cs.get('overall_score', '—')}/100")
            with col2:
                st.metric("Grade", cs.get("overall_grade", "—"))
            with col3:
                st.metric("Strongest", cs.get("strongest_element", "—"))

            priorities = cs.get("top_3_rewrite_priorities", [])
            if priorities:
                st.markdown("**Top Rewrite Priorities:**")
                for i, p in enumerate(priorities, 1):
                    st.markdown(f"{i}. {p}")

            element_scores = cs.get("element_scores", {})
            if element_scores:
                st.markdown("---")
                st.markdown("**Element Scores:**")
                for elem_name, elem_data in element_scores.items():
                    score = elem_data.get("score", 0) if isinstance(elem_data, dict) else 0
                    label = elem_name.replace("_", " ").title()
                    st.progress(score / 10, text=f"{label}: {score}/10")

                    if isinstance(elem_data, dict):
                        current = elem_data.get("current_copy", "")
                        if current:
                            st.caption(f"Current: \"{current[:100]}...\"" if len(current) > 100 else f"Current: \"{current}\"")

                        rewrites = elem_data.get("rewrite_suggestions", [])
                        if rewrites:
                            with st.expander(f"Rewrite suggestions for {label}"):
                                for r in rewrites:
                                    st.markdown(f"- {r}")

            compliance = cs.get("compliance_flags", [])
            if compliance:
                st.markdown("---")
                st.markdown("**⚠️ Compliance Flags:**")
                for flag in compliance:
                    severity = flag.get("severity", "note")
                    icon = {"critical": "🔴", "warning": "🟡", "note": "🔵"}.get(severity, "⚪")
                    st.markdown(f"{icon} **{flag.get('issue', '')}** — {flag.get('location', '')}")
                    st.caption(flag.get("recommendation", ""))


# ---------------------------------------------------------------------------
# Tab 3: Blueprint
# ---------------------------------------------------------------------------

def _get_products_for_brand(brand_id: str):
    """Get products for brand dropdown."""
    from viraltracker.services.landing_page_analysis import BrandProfileService
    return BrandProfileService(get_supabase_client()).get_products_for_brand(brand_id)


def _get_offer_variants(product_id: str):
    """Get offer variants for product dropdown."""
    from viraltracker.services.landing_page_analysis import BrandProfileService
    return BrandProfileService(get_supabase_client()).get_offer_variants(product_id)


def _get_personas_for_product(product_id: str):
    """Get personas for product dropdown."""
    from viraltracker.services.landing_page_analysis import BrandProfileService
    return BrandProfileService(get_supabase_client()).get_personas_for_product(product_id)


def render_blueprint_tab(brand_id: str, org_id: str):
    """Render the blueprint generation and display UI."""
    st.subheader("Reconstruction Blueprint")
    st.caption(
        "Generate a brand-specific creative brief by mapping a competitor's page "
        "structure to your brand's assets, voice, and positioning."
    )

    # --- Selectors ---
    col1, col2 = st.columns(2)

    with col1:
        products = _get_products_for_brand(brand_id)
        if not products:
            st.warning("No products found for this brand. Add products in Brand Manager first.")
            return
        product_options = {p["id"]: p["name"] for p in products}
        product_id = st.selectbox(
            "Product",
            options=list(product_options.keys()),
            format_func=lambda x: product_options[x],
            key="lpa_bp_product",
        )

    with col2:
        offer_variants = _get_offer_variants(product_id) if product_id else []
        offer_variant_id = None
        if offer_variants:
            ov_options = {ov["id"]: f"{ov['name']}{' (default)' if ov.get('is_default') else ''}" for ov in offer_variants}
            offer_variant_id = st.selectbox(
                "Offer Variant",
                options=list(ov_options.keys()),
                format_func=lambda x: ov_options[x],
                key="lpa_bp_variant",
            )
        else:
            st.info("No offer variants — using product defaults.")

    # Persona selector (optional — target a specific persona)
    personas = _get_personas_for_product(product_id) if product_id else []
    persona_id = None
    if personas:
        persona_options = {"Auto (let AI choose)": None}
        for p in personas:
            label = p["name"]
            if p.get("snapshot"):
                label += f" — {p['snapshot'][:60]}"
            persona_options[label] = p["id"]
        selected_persona_label = st.selectbox(
            "Target Persona (optional)",
            options=list(persona_options.keys()),
            key="lpa_bp_persona",
        )
        persona_id = persona_options[selected_persona_label]

    # Analysis selector
    service = get_analysis_service()
    analyses = service.list_analyses(org_id)
    completed_analyses = [a for a in analyses if a.get("status") in ("completed", "partial")]

    if not completed_analyses:
        st.info("No completed analyses yet. Use the Analyze tab to analyze a landing page first.")
        return

    analysis_options = {}
    for a in completed_analyses:
        url = a.get("url", "Unknown")[:50]
        grade = a.get("overall_grade", "?")
        created = a.get("created_at", "")[:10]
        analysis_options[a["id"]] = f"{url} — Grade: {grade} — {created}"

    analysis_id = st.selectbox(
        "Source Analysis",
        options=list(analysis_options.keys()),
        format_func=lambda x: analysis_options[x],
        key="lpa_bp_analysis",
    )

    # Generate button
    if st.button("Generate Blueprint", type="primary", key="lpa_bp_generate"):
        _run_blueprint_generation(
            analysis_id=analysis_id,
            brand_id=brand_id,
            product_id=product_id,
            offer_variant_id=offer_variant_id,
            persona_id=persona_id,
            org_id=org_id,
        )

    # Show latest generated blueprint
    if st.session_state.lpa_latest_blueprint:
        st.divider()
        _render_blueprint(st.session_state.lpa_latest_blueprint)

    # Show past blueprints
    _render_blueprint_history(org_id, brand_id)


def _run_blueprint_generation(
    analysis_id: str,
    brand_id: str,
    product_id: str,
    offer_variant_id: str,
    org_id: str,
    persona_id: str = None,
):
    """Execute blueprint generation with progress tracking."""
    progress = st.progress(0, text="Starting blueprint generation...")
    step_progress = {1: 10, 2: 25, 3: 50, 4: 80, 5: 100}
    step_labels = {
        1: "Step 1/5: Loading analysis...",
        2: "Step 2/5: Aggregating brand profile...",
        3: "Step 3/5: Blueprint Part 1 (strategy + top sections)...",
        4: "Step 4/5: Blueprint Part 2 (remaining + summary)...",
        5: "Blueprint complete!",
    }

    def on_progress(step, msg):
        pct = step_progress.get(step, 0)
        label = step_labels.get(step, msg)
        progress.progress(pct / 100, text=label)

    bp_service = get_blueprint_service()

    # Set tracking context
    try:
        from viraltracker.services.usage_tracker import UsageTracker
        tracker = UsageTracker(get_supabase_client())
        user_id = st.session_state.get("user_id")
        bp_service.set_tracking_context(tracker, user_id, org_id)
    except Exception:
        pass

    try:
        result = asyncio.run(
            bp_service.generate_blueprint(
                analysis_id=analysis_id,
                brand_id=brand_id,
                product_id=product_id,
                org_id=org_id,
                offer_variant_id=offer_variant_id,
                persona_id=persona_id,
                progress_callback=on_progress,
            )
        )
        st.session_state.lpa_latest_blueprint = result
        progress.progress(1.0, text="Done!")
        st.success(
            f"Blueprint generated in {result.get('processing_time_ms', 0) / 1000:.1f}s — "
            f"{result.get('sections_count', 0)} sections, "
            f"{result.get('elements_mapped', 0)} mapped, "
            f"{result.get('content_needed_count', 0)} need content"
        )
    except Exception as e:
        st.error(f"Blueprint generation failed: {e}")


def _render_blueprint(result: dict, key_suffix: str = "latest"):
    """Render a generated blueprint with section accordion and exports."""
    blueprint = result.get("blueprint", {})
    rb = blueprint.get("reconstruction_blueprint", blueprint)

    # --- Strategy Summary ---
    strategy = rb.get("strategy_summary", {})
    if strategy:
        st.markdown("### Strategy Summary")
        col1, col2 = st.columns(2)
        with col1:
            st.markdown(f"**Awareness Adaptation:** {strategy.get('awareness_adaptation', '—')}")
            st.markdown(f"**Architecture:** {strategy.get('architecture_recommendation', '—')}")
        with col2:
            st.markdown(f"**Tone Direction:** {strategy.get('tone_direction', '—')}")
            st.markdown(f"**Target Persona:** {strategy.get('target_persona', '—')}")

        diffs = strategy.get("key_differentiators", [])
        if diffs:
            st.markdown("**Key Differentiators:**")
            for d in diffs:
                st.markdown(f"- {d}")

    # --- Sections ---
    sections = rb.get("sections", [])
    bonus = rb.get("bonus_sections", [])

    if sections:
        st.markdown("### Page Sections")
        for section in sections:
            _render_blueprint_section(section)

    if bonus:
        st.markdown("### Bonus Sections (from Gap Analysis)")
        for section in bonus:
            _render_blueprint_section(section, is_bonus=True)

    # --- Content Needed Summary ---
    content_needed = rb.get("content_needed_summary", [])
    if content_needed:
        st.markdown("### Content Needed")
        for item in content_needed:
            priority = item.get("priority", "medium")
            icon = {"high": "🔴", "medium": "🟡", "low": "🟢"}.get(priority, "⚪")
            st.markdown(
                f"{icon} **{item.get('element_type', '?')}** — "
                f"{item.get('what_to_create', '')}"
            )
            source = item.get("suggested_source", "")
            if source:
                st.caption(f"Source: {source}")

    # --- Brand Profile Gaps ---
    gaps = result.get("brand_profile_gaps", [])
    if gaps:
        with st.expander(f"Brand Profile Gaps ({len(gaps)} items)", expanded=False):
            for gap in gaps:
                severity = gap.get("severity", "low")
                icon = {"critical": "🔴", "moderate": "🟡", "low": "🟢"}.get(severity, "⚪")
                st.markdown(f"{icon} **{gap.get('field', '?')}** ({gap.get('section', '')}) — {gap.get('instruction', '')}")

    # --- Exports ---
    st.markdown("### Export")
    export_col1, export_col2 = st.columns(2)
    with export_col1:
        import json as _json
        json_str = _json.dumps(blueprint, indent=2, ensure_ascii=False)
        st.download_button(
            "Download JSON",
            data=json_str,
            file_name=f"blueprint_{result.get('source_url', 'unknown')[:30].replace('/', '_')}.json",
            mime="application/json",
            key=f"lpa_bp_export_json_{key_suffix}",
        )
    with export_col2:
        md_str = _blueprint_to_markdown(rb, result)
        st.download_button(
            "Download Markdown",
            data=md_str,
            file_name=f"blueprint_{result.get('source_url', 'unknown')[:30].replace('/', '_')}.md",
            mime="text/markdown",
            key=f"lpa_bp_export_md_{key_suffix}",
        )


def _render_blueprint_section(section: dict, is_bonus: bool = False):
    """Render a single blueprint section as an expander."""
    flow = section.get("flow_order", "?")
    etype = section.get("element_type", "Unknown")
    status = section.get("content_status", "populated")
    section_name = section.get("section_name", etype)

    status_icon = {
        "populated": "🟢",
        "partial": "🟡",
        "CONTENT_NEEDED": "🔴",
    }.get(status, "⚪")

    bonus_tag = " [BONUS]" if is_bonus else ""
    header = f"{status_icon} **{flow}.** {section_name.replace('_', ' ').title()} — {etype}{bonus_tag}"

    with st.expander(header, expanded=(status == "CONTENT_NEEDED")):
        # Competitor approach
        comp = section.get("competitor_approach", "")
        if comp:
            st.markdown(f"**Competitor:** {comp}")
            subtype = section.get("competitor_subtype", "")
            if subtype:
                st.caption(f"Subtype: {subtype}")

        # Gap note for bonus sections
        gap_note = section.get("gap_note", "")
        if gap_note:
            st.info(gap_note)

        # Brand mapping
        mapping = section.get("brand_mapping", {})
        if mapping:
            st.markdown("**Brand Mapping:**")
            for key, value in mapping.items():
                if isinstance(value, list):
                    st.markdown(f"- **{key.replace('_', ' ').title()}:** {', '.join(str(v) for v in value)}")
                else:
                    st.markdown(f"- **{key.replace('_', ' ').title()}:** {value}")

        # Copy direction
        copy_dir = section.get("copy_direction", "")
        if copy_dir:
            st.markdown(f"**Copy Direction:** {copy_dir}")

        # Gap improvement
        gap_imp = section.get("gap_improvement", "")
        if gap_imp:
            st.markdown(f"**Improvement:** {gap_imp}")

        # Compliance
        compliance = section.get("compliance_notes", "")
        if compliance:
            st.warning(f"Compliance: {compliance}")

        # Action items for CONTENT_NEEDED
        actions = section.get("action_items", [])
        if actions:
            st.markdown("**Action Items:**")
            for a in actions:
                st.markdown(f"- {a}")


def _blueprint_to_markdown(rb: dict, result: dict) -> str:
    """Convert blueprint to formatted markdown for export."""
    lines = []
    lines.append(f"# Reconstruction Blueprint")
    lines.append(f"**Source:** {result.get('source_url', 'Unknown')}")
    lines.append(f"**Generated:** {datetime.now().strftime('%Y-%m-%d %H:%M')}")
    lines.append("")

    strategy = rb.get("strategy_summary", {})
    if strategy:
        lines.append("## Strategy Summary")
        lines.append(f"- **Awareness Adaptation:** {strategy.get('awareness_adaptation', '—')}")
        lines.append(f"- **Tone Direction:** {strategy.get('tone_direction', '—')}")
        lines.append(f"- **Architecture:** {strategy.get('architecture_recommendation', '—')}")
        lines.append(f"- **Target Persona:** {strategy.get('target_persona', '—')}")
        diffs = strategy.get("key_differentiators", [])
        if diffs:
            lines.append("- **Key Differentiators:**")
            for d in diffs:
                lines.append(f"  - {d}")
        lines.append("")

    sections = rb.get("sections", [])
    if sections:
        lines.append("## Page Sections")
        lines.append("")
        for s in sections:
            _section_to_md(s, lines)

    bonus = rb.get("bonus_sections", [])
    if bonus:
        lines.append("## Bonus Sections (from Gap Analysis)")
        lines.append("")
        for s in bonus:
            _section_to_md(s, lines, is_bonus=True)

    content_needed = rb.get("content_needed_summary", [])
    if content_needed:
        lines.append("## Content Needed")
        lines.append("")
        for item in content_needed:
            priority = item.get("priority", "medium").upper()
            lines.append(f"- [{priority}] **{item.get('element_type', '?')}** — {item.get('what_to_create', '')}")
            source = item.get("suggested_source", "")
            if source:
                lines.append(f"  - Source: {source}")
        lines.append("")

    return "\n".join(lines)


def _section_to_md(section: dict, lines: list, is_bonus: bool = False):
    """Append a blueprint section as markdown."""
    flow = section.get("flow_order", "?")
    etype = section.get("element_type", "Unknown")
    status = section.get("content_status", "populated")
    section_name = section.get("section_name", etype)
    status_tag = {"populated": "[READY]", "partial": "[PARTIAL]", "CONTENT_NEEDED": "[CONTENT NEEDED]"}.get(status, "")
    bonus_tag = " [BONUS]" if is_bonus else ""

    lines.append(f"### {flow}. {section_name.replace('_', ' ').title()} — {etype} {status_tag}{bonus_tag}")
    lines.append("")

    comp = section.get("competitor_approach", "")
    if comp:
        lines.append(f"**Competitor:** {comp}")

    gap_note = section.get("gap_note", "")
    if gap_note:
        lines.append(f"> {gap_note}")

    mapping = section.get("brand_mapping", {})
    if mapping:
        lines.append("**Brand Mapping:**")
        for key, value in mapping.items():
            if isinstance(value, list):
                lines.append(f"- {key.replace('_', ' ').title()}: {', '.join(str(v) for v in value)}")
            else:
                lines.append(f"- {key.replace('_', ' ').title()}: {value}")

    copy_dir = section.get("copy_direction", "")
    if copy_dir:
        lines.append(f"**Copy Direction:** {copy_dir}")

    gap_imp = section.get("gap_improvement", "")
    if gap_imp:
        lines.append(f"**Improvement:** {gap_imp}")

    compliance = section.get("compliance_notes", "")
    if compliance:
        lines.append(f"**Compliance:** {compliance}")

    actions = section.get("action_items", [])
    if actions:
        lines.append("**Action Items:**")
        for a in actions:
            lines.append(f"- {a}")

    lines.append("")


def _render_blueprint_history(org_id: str, brand_id: str):
    """Show past blueprints in an expandable list."""
    bp_service = get_blueprint_service()
    blueprints = bp_service.list_blueprints(org_id, brand_id=brand_id)

    if not blueprints:
        return

    st.divider()
    st.markdown("### Past Blueprints")

    for bp in blueprints:
        url = bp.get("source_url", "Unknown")[:50]
        sections = bp.get("sections_count", 0)
        mapped = bp.get("elements_mapped", 0)
        needed = bp.get("content_needed_count", 0)
        status = bp.get("status", "unknown")
        created = bp.get("created_at", "")

        if created:
            try:
                dt = datetime.fromisoformat(created.replace("Z", "+00:00"))
                created_str = dt.strftime("%b %d, %Y %I:%M %p")
            except Exception:
                created_str = created[:19]
        else:
            created_str = ""

        status_icon = {"completed": "✅", "partial": "⚠️", "failed": "❌", "processing": "⏳"}.get(status, "❓")
        header = (
            f"{status_icon} **{url}** — "
            f"{sections} sections, {mapped} mapped, {needed} need content — "
            f"{created_str}"
        )

        with st.expander(header, expanded=False):
            full = bp_service.get_blueprint(bp["id"])
            if not full:
                st.error("Could not load blueprint details.")
                continue
            # Build a result-like dict for _render_blueprint
            result_like = {
                "blueprint": full.get("blueprint", {}),
                "source_url": full.get("source_url", ""),
                "brand_profile_gaps": full.get("content_gaps", []),
                "sections_count": full.get("sections_count", 0),
                "elements_mapped": full.get("elements_mapped", 0),
                "content_needed_count": full.get("content_needed_count", 0),
            }
            _render_blueprint(result_like, key_suffix=bp["id"])


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

st.title("🏗️ Landing Page Analyzer")

from viraltracker.ui.utils import render_brand_selector, get_current_organization_id

brand_id = render_brand_selector(key="lpa_brand_selector")
if not brand_id:
    st.stop()

org_id = get_current_organization_id()
if not org_id:
    st.warning("No organization selected.")
    st.stop()

# Superusers have org_id="all" — resolve to the brand's actual org for writes
if org_id == "all":
    try:
        _brand_row = get_supabase_client().table("brands").select("organization_id").eq("id", brand_id).single().execute()
        org_id = _brand_row.data["organization_id"]
    except Exception:
        st.warning("Could not determine organization for this brand.")
        st.stop()

tab_analyze, tab_results, tab_blueprint = st.tabs(["🔍 Analyze", "📊 Results", "📋 Blueprint"])

with tab_analyze:
    render_analyze_tab(brand_id, org_id)

with tab_results:
    render_results_tab(org_id)

with tab_blueprint:
    render_blueprint_tab(brand_id, org_id)
