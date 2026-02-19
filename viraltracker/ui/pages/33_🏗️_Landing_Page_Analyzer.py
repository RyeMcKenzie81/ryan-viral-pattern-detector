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

import logging
import streamlit as st
import asyncio
from datetime import datetime
from typing import Optional

logger = logging.getLogger(__name__)

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
# Gap filler state
if "lpa_gap_suggestions" not in st.session_state:
    st.session_state.lpa_gap_suggestions = {}
if "lpa_gap_sources" not in st.session_state:
    st.session_state.lpa_gap_sources = {}
if "lpa_gaps_saved" not in st.session_state:
    st.session_state.lpa_gaps_saved = set()
if "lpa_gap_dismissed" not in st.session_state:
    st.session_state.lpa_gap_dismissed = set()
if "lpa_gap_overwrite_confirmed" not in st.session_state:
    st.session_state.lpa_gap_overwrite_confirmed = set()
# Mockup cache state
if "lpa_mockup_analysis_ids" not in st.session_state:
    st.session_state.lpa_mockup_analysis_ids = []
if "lpa_mockup_blueprint_ids" not in st.session_state:
    st.session_state.lpa_mockup_blueprint_ids = []


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


def get_gap_filler_service():
    """Lazy-load ContentGapFillerService."""
    from viraltracker.services.landing_page_analysis import ContentGapFillerService
    return ContentGapFillerService(get_supabase_client())


def _awareness_badge(level: str) -> str:
    badges = {
        "unaware": "⬜ Unaware",
        "problem_aware": "🟨 Problem-Aware",
        "solution_aware": "🟦 Solution-Aware",
        "product_aware": "🟩 Product-Aware",
        "most_aware": "🟪 Most-Aware",
    }
    return badges.get(level, level or "Unknown")


def get_mockup_service():
    """Lazy-load MockupService."""
    from viraltracker.services.landing_page_analysis import MockupService
    return MockupService()


def _cache_mockup(cache_type: str, item_id: str, html_str: str):
    """Cache a mockup in session state with FIFO eviction (max 10 per type)."""
    ids_key = f"lpa_mockup_{cache_type}_ids"
    data_key = f"lpa_mockup_{cache_type}_{item_id}"

    # Add to cache
    st.session_state[data_key] = html_str

    # Track order for FIFO
    ids = st.session_state.get(ids_key, [])
    if item_id not in ids:
        ids.append(item_id)
    # Evict oldest if over 10
    while len(ids) > 10:
        old_id = ids.pop(0)
        old_key = f"lpa_mockup_{cache_type}_{old_id}"
        st.session_state.pop(old_key, None)
    st.session_state[ids_key] = ids


def _get_cached_mockup(cache_type: str, item_id: str) -> Optional[str]:
    """Retrieve a cached mockup from session state."""
    return st.session_state.get(f"lpa_mockup_{cache_type}_{item_id}")


def _render_mockup_preview(html_str: str, key_suffix: str):
    """Render mockup thumbnail, download button, and open-in-new-tab link."""
    import base64
    import streamlit.components.v1 as components

    # Thumbnail preview (scaled down via CSS transform)
    thumbnail_html = f"""
    <div style="width:100%; height:400px; overflow:hidden; border:1px solid #e2e8f0;
                border-radius:8px; background:#fff; position:relative;">
      <div style="transform:scale(0.35); transform-origin:top left;
                  width:286%; height:286%; pointer-events:none;">
        {html_str}
      </div>
    </div>
    """
    components.html(thumbnail_html, height=410, scrolling=False)

    # Download + Open in New Tab
    col1, col2 = st.columns(2)
    with col1:
        st.download_button(
            "Download HTML Mockup",
            data=html_str,
            file_name=f"mockup_{key_suffix}.html",
            mime="text/html",
            key=f"lpa_mockup_dl_{key_suffix}",
        )
    with col2:
        # Best-effort: open in new tab via Blob URL
        html_b64 = base64.b64encode(html_str.encode("utf-8")).decode("ascii")
        uid = key_suffix.replace("-", "")[:16]
        open_script = f"""
        <span id="mb64-{uid}" style="display:none">{html_b64}</span>
        <button onclick="(function(){{
          var b=document.getElementById('mb64-{uid}').textContent;
          var bytes=Uint8Array.from(atob(b),function(c){{return c.charCodeAt(0)}});
          var html=new TextDecoder('utf-8').decode(bytes);
          var blob=new Blob([html],{{type:'text/html;charset=utf-8'}});
          var url=URL.createObjectURL(blob);
          window.open(url,'_blank');
          setTimeout(function(){{URL.revokeObjectURL(url)}},5000);
        }})()" style="padding:8px 20px;border:1px solid #d1d5db;border-radius:6px;
        background:#fff;cursor:pointer;font-size:14px;color:#374151;">
        Open in New Tab
        </button>
        """
        components.html(open_script, height=45)


# ---------------------------------------------------------------------------
# Gap Fixer UI
# ---------------------------------------------------------------------------

def _render_gap_fixer(
    result: dict,
    brand_id: str,
    product_id: str,
    offer_variant_id,
    org_id: str,
    key_suffix: str = "latest",
):
    """Render the content gap fixer inline below blueprint results.

    Shows fillable gaps with manual entry controls, conflict resolution,
    Not Applicable dismissal, and a Needs Setup section.
    """
    from viraltracker.services.landing_page_analysis import (
        GAP_FIELD_REGISTRY, resolve_gap_key,
    )

    gaps = result.get("brand_profile_gaps", [])
    if not gaps:
        return

    service = get_gap_filler_service()
    service._user_id = st.session_state.get("user_id")
    service._org_id = org_id

    blueprint_id = result.get("id") or result.get("blueprint_id")

    # Resolve gap dicts to GapFieldSpec keys
    resolved_gaps = []
    needs_setup_gaps = []
    for gap in gaps:
        gap_key = resolve_gap_key(gap)
        if not gap_key or gap_key not in GAP_FIELD_REGISTRY:
            continue
        spec = GAP_FIELD_REGISTRY[gap_key]
        if spec.needs_setup:
            needs_setup_gaps.append((gap, spec))
        else:
            resolved_gaps.append((gap, spec))

    # Check dismissed state from session (faster than DB each render)
    active_gaps = []
    for gap, spec in resolved_gaps:
        dismiss_key = f"{key_suffix}:{spec.key}"
        if dismiss_key in st.session_state.lpa_gap_dismissed:
            continue
        # Also check DB for persisted dismissals
        entity_id = service._resolve_entity_id(spec, brand_id, product_id, offer_variant_id)
        if entity_id and blueprint_id and service.is_gap_dismissed(spec.key, blueprint_id, entity_id):
            st.session_state.lpa_gap_dismissed.add(dismiss_key)
            continue
        active_gaps.append((gap, spec))

    # Check available sources (cached in session state per key_suffix)
    source_cache_key = f"lpa_gap_sources_loaded:{key_suffix}"
    if source_cache_key not in st.session_state:
        source_results = service.check_available_sources(
            gaps=gaps,
            brand_id=brand_id,
            product_id=product_id,
            offer_variant_id=offer_variant_id,
        )
        for gap_key, cands in source_results.items():
            sk = f"{key_suffix}:{gap_key}"
            st.session_state.lpa_gap_sources[sk] = cands
        st.session_state[source_cache_key] = True

    filled_count = len(st.session_state.lpa_gaps_saved)
    total = len(resolved_gaps) + len(needs_setup_gaps)
    remaining = len(active_gaps) + len(needs_setup_gaps)

    st.markdown(f"### Fill Content Gaps ({remaining} of {total} remaining)")

    # "Fix All Auto-Fillable Gaps" button
    auto_fillable_active = [
        (g, s) for g, s in active_gaps if s.auto_fillable
    ]
    if auto_fillable_active:
        fix_all_col, fix_all_info = st.columns([2, 4])
        with fix_all_col:
            if st.button(
                f"Fix All Auto-Fillable ({len(auto_fillable_active)} gaps)",
                type="secondary",
                key=f"lpa_gap_fixall_{key_suffix}",
            ):
                _run_fix_all(
                    service=service,
                    gaps=[g for g, _ in active_gaps],
                    brand_id=brand_id,
                    product_id=product_id,
                    offer_variant_id=offer_variant_id,
                    org_id=org_id,
                    blueprint_id=blueprint_id,
                    key_suffix=key_suffix,
                )
        with fix_all_info:
            st.caption("Batched AI extraction (~2 calls). Review each before saving.")

    # "Apply & Regenerate" sticky CTA
    if filled_count > 0:
        st.success(
            f"{filled_count} field{'s' if filled_count != 1 else ''} saved. "
            "Blueprint may now produce better results."
        )
        if st.button(
            "Regenerate Blueprint with Updated Data",
            type="primary",
            key=f"lpa_gap_regenerate_{key_suffix}",
        ):
            # Reset gap state
            st.session_state.lpa_gaps_saved = set()
            st.session_state.lpa_gap_suggestions = {}
            st.session_state.lpa_gap_sources = {}
            st.session_state.lpa_gap_dismissed = set()
            st.session_state.lpa_gap_overwrite_confirmed = set()
            # Re-run blueprint with current selections.
            # Prefer session state, but fall back to the existing blueprint's
            # analysis_id (session state may be empty after a rerun).
            regen_analysis_id = (
                st.session_state.get("lpa_bp_analysis")
                or (st.session_state.get("lpa_latest_blueprint") or {}).get("analysis_id", "")
            )
            _run_blueprint_generation(
                analysis_id=regen_analysis_id,
                brand_id=brand_id,
                product_id=product_id,
                offer_variant_id=offer_variant_id,
                persona_id=st.session_state.get("lpa_bp_persona_id"),
                org_id=org_id,
            )
            st.rerun()

    # Render each active gap
    for gap, spec in active_gaps:
        _render_single_gap_control(
            gap=gap,
            spec=spec,
            brand_id=brand_id,
            product_id=product_id,
            offer_variant_id=offer_variant_id,
            org_id=org_id,
            blueprint_id=blueprint_id,
            key_suffix=key_suffix,
            service=service,
        )

    # Dismissed gaps — show undo option
    dismissed_for_this = [
        (gap, spec) for gap, spec in resolved_gaps
        if f"{key_suffix}:{spec.key}" in st.session_state.lpa_gap_dismissed
    ]
    if dismissed_for_this:
        with st.expander(f"Dismissed ({len(dismissed_for_this)})", expanded=False):
            for gap, spec in dismissed_for_this:
                col1, col2 = st.columns([4, 1])
                with col1:
                    st.caption(f"~~{spec.display_name}~~ — marked Not Applicable")
                with col2:
                    if st.button("Undo", key=f"lpa_gap_undo_{spec.key}_{key_suffix}"):
                        service.undo_not_applicable(
                            gap_key=spec.key,
                            brand_id=brand_id,
                            product_id=product_id,
                            offer_variant_id=offer_variant_id,
                            blueprint_id=blueprint_id,
                            org_id=org_id,
                        )
                        dismiss_key = f"{key_suffix}:{spec.key}"
                        st.session_state.lpa_gap_dismissed.discard(dismiss_key)
                        st.rerun()

    # "Needs Setup" collapsed section
    if needs_setup_gaps:
        with st.expander(f"Needs Setup ({len(needs_setup_gaps)} fields)", expanded=False):
            for gap, spec in needs_setup_gaps:
                st.markdown(
                    f"**{spec.display_name}** — "
                    f"Set up in [{spec.manual_entry_link}]({spec.manual_entry_link})"
                )


def _render_single_gap_control(
    gap: dict,
    spec,
    brand_id: str,
    product_id: str,
    offer_variant_id,
    org_id: str,
    blueprint_id,
    key_suffix: str,
    service,
):
    """Render a single gap field with manual entry and controls."""
    severity = gap.get("severity", "low")
    severity_icon = {"critical": "🔴", "moderate": "🟡", "low": "🟢"}.get(severity, "⚪")

    # Check if already saved this session
    save_key = f"{key_suffix}:{spec.key}"
    already_saved = save_key in st.session_state.lpa_gaps_saved

    header = f"{severity_icon} {spec.display_name} ({severity})"
    if already_saved:
        header = f"✅ {spec.display_name} — saved"

    with st.expander(header, expanded=(not already_saved and severity in ("critical", "moderate"))):
        # Target entity warning for offer_variant fields
        if spec.entity == "offer_variant" and not offer_variant_id:
            entity_id = service._resolve_entity_id(spec, brand_id, product_id, None)
            if not entity_id:
                st.warning("No offer variant found. Create one in Brand Manager first.")
                st.markdown(f"[Go to Brand Manager]({spec.manual_entry_link})")
                return

        current_value = service._get_current_value(spec, brand_id, product_id, offer_variant_id)

        # Show current value if exists
        if current_value and not service._is_empty(current_value):
            st.caption("**Current value:**")
            _display_current_value(spec, current_value)

        # Source candidates (populated from session state)
        source_key = f"{key_suffix}:{spec.key}"
        sources = st.session_state.lpa_gap_sources.get(source_key, [])
        if sources:
            _render_source_snippets(sources, spec, key_suffix)

        # Fresh scrape option (for fields that support it)
        if "fresh_scrape" in spec.sources and spec.auto_fillable:
            _render_fresh_scrape_option(
                service=service,
                spec=spec,
                brand_id=brand_id,
                product_id=product_id,
                offer_variant_id=offer_variant_id,
                org_id=org_id,
                key_suffix=key_suffix,
            )

        # AI suggestion (if available)
        suggestion_key = f"{key_suffix}:{spec.key}"
        existing_suggestion = st.session_state.lpa_gap_suggestions.get(suggestion_key)
        if existing_suggestion:
            _render_suggestion_evidence(existing_suggestion, spec)
            # If suggestion exists but value is empty, show a note
            if not existing_suggestion.get("value"):
                reasoning = existing_suggestion.get("reasoning", "")
                if reasoning:
                    st.info(
                        "AI could not extract an explicit value but provided analysis above. "
                        "You can use the reasoning to compose a value manually."
                    )

        # "Generate Suggestion" button for auto-fillable fields
        if spec.auto_fillable and not existing_suggestion:
            if st.button(
                f"Generate AI Suggestion",
                key=f"lpa_gap_suggest_{spec.key}_{key_suffix}",
            ):
                _run_per_gap_suggestion(
                    service=service,
                    spec=spec,
                    brand_id=brand_id,
                    product_id=product_id,
                    offer_variant_id=offer_variant_id,
                    org_id=org_id,
                    key_suffix=key_suffix,
                )

        # Manual entry input — check for "Use This" / AI suggestion prefill
        widget_key = f"lpa_gap_input_{spec.key}_{key_suffix}"
        usethis_key = f"lpa_gap_usethis_{spec.key}_{key_suffix}"
        prefill = st.session_state.get(usethis_key, "")

        # Streamlit keyed widgets ignore the `value` param after first render —
        # they always read from st.session_state[widget_key]. So when we have a
        # new prefill value, set it directly on the widget key and clear the
        # intermediate key to avoid overwriting future user edits.
        if prefill:
            st.session_state[widget_key] = prefill
            del st.session_state[usethis_key]

        if spec.value_type == "text":
            new_value = st.text_area(
                f"Enter {spec.display_name}",
                value=st.session_state.get(widget_key, ""),
                key=widget_key,
                height=100,
            )
        elif spec.value_type == "text_list":
            st.caption("Enter one item per line:")
            new_value = st.text_area(
                f"Enter {spec.display_name}",
                value=st.session_state.get(widget_key, ""),
                key=widget_key,
                height=150,
            )
        elif spec.value_type in ("qa_list", "timeline_list", "json_array", "json"):
            _render_structured_entry_help(spec)
            new_value = st.text_area(
                f"Enter {spec.display_name} (JSON)",
                value=st.session_state.get(widget_key, ""),
                key=widget_key,
                height=200,
            )
        elif spec.value_type == "quote_list":
            st.info(
                "Customer testimonials come from Amazon Review Analysis. "
                "Run an analysis to populate this field."
            )
            st.markdown(f"[Go to Brand Manager]({spec.manual_entry_link})")
            return
        else:
            st.markdown(f"[Set up in Brand Manager]({spec.manual_entry_link})")
            return

        # Action buttons row
        col_save, col_na, col_link = st.columns([2, 2, 2])

        with col_save:
            if new_value and new_value.strip():
                overwrite_key = f"{key_suffix}:{spec.key}"
                needs_confirm = (
                    not service._is_empty(current_value)
                    and spec.write_policy in ("allow_if_empty", "confirm_overwrite")
                    and overwrite_key not in st.session_state.lpa_gap_overwrite_confirmed
                )

                if needs_confirm:
                    btn_label = "Overwrite?"
                    btn_type = "secondary"
                else:
                    target_label = f"{spec.table}.{spec.column}" if spec.column else spec.table
                    btn_label = f"Save to {target_label}"
                    btn_type = "primary"

                if st.button(btn_label, type=btn_type, key=f"lpa_gap_save_{spec.key}_{key_suffix}"):
                    if needs_confirm:
                        st.session_state.lpa_gap_overwrite_confirmed.add(overwrite_key)
                        st.rerun()
                    else:
                        _execute_gap_save(
                            service=service,
                            spec=spec,
                            value=new_value,
                            brand_id=brand_id,
                            product_id=product_id,
                            offer_variant_id=offer_variant_id,
                            org_id=org_id,
                            blueprint_id=blueprint_id,
                            key_suffix=key_suffix,
                            force_overwrite=overwrite_key in st.session_state.lpa_gap_overwrite_confirmed,
                        )
            else:
                st.button(
                    "Save", disabled=True,
                    key=f"lpa_gap_save_disabled_{spec.key}_{key_suffix}",
                )

        with col_na:
            if st.button("Not Applicable", key=f"lpa_gap_na_{spec.key}_{key_suffix}"):
                service.mark_not_applicable(
                    gap_key=spec.key,
                    brand_id=brand_id,
                    product_id=product_id,
                    offer_variant_id=offer_variant_id,
                    blueprint_id=blueprint_id,
                    org_id=org_id,
                )
                dismiss_key = f"{key_suffix}:{spec.key}"
                st.session_state.lpa_gap_dismissed.add(dismiss_key)
                st.rerun()

        with col_link:
            st.markdown(f"[Edit in Brand Manager]({spec.manual_entry_link})")


def _display_current_value(spec, value):
    """Display the current value of a gap field."""
    if spec.value_type == "text":
        st.code(str(value), language=None)
    elif spec.value_type == "text_list":
        if isinstance(value, list):
            for item in value[:5]:
                st.markdown(f"- {item}")
            if len(value) > 5:
                st.caption(f"...and {len(value) - 5} more")
        else:
            st.code(str(value), language=None)
    elif spec.value_type in ("qa_list", "timeline_list", "json_array", "json"):
        import json as _json
        st.code(_json.dumps(value, indent=2, ensure_ascii=False)[:500], language="json")
    else:
        st.code(str(value)[:300], language=None)


def _render_structured_entry_help(spec):
    """Show format help for structured JSON fields."""
    if spec.value_type == "qa_list":
        st.caption('Format: [{"question": "...", "answer": "..."}]')
    elif spec.value_type == "timeline_list":
        st.caption('Format: [{"timeframe": "Week 1-2", "expected_result": "..."}]')
    elif spec.value_type == "json_array":
        if spec.key == "product.ingredients":
            st.caption('Format: [{"name": "...", "benefit": "...", "proof_point": "..."}]')
        else:
            st.caption("Format: JSON array of objects")


def _render_source_snippets(sources: list, spec, key_suffix: str):
    """Render source candidate snippets with 'Use This' buttons."""
    st.caption("**Available sources:**")
    for i, src in enumerate(sources):
        source_icon = {
            "brand_landing_pages": "📄", "amazon_review_analysis": "📊",
            "reddit_sentiment_quotes": "💬", "fresh_scrape": "🔄",
        }.get(src.source_type, "📋")

        conf_badge = {"high": "🟢", "medium": "🟡", "low": "🟠"}.get(src.confidence, "⚪")
        source_label = src.source_type.replace("_", " ").title()

        col_info, col_btn = st.columns([4, 1])
        with col_info:
            st.markdown(f"{source_icon} **{source_label}** {conf_badge} {src.confidence}")
            for snippet in src.snippets[:3]:
                display = f'"{snippet[:200]}..."' if len(snippet) > 200 else f'"{snippet}"'
                st.caption(f"> {display}")
            if src.url:
                st.caption(f"URL: {src.url}")
            if src.scraped_at:
                st.caption(f"Scraped: {str(src.scraped_at)[:19]}")

        with col_btn:
            if src.extracted_value is not None:
                use_key = f"lpa_gap_use_{spec.key}_{i}_{key_suffix}"
                if st.button("Use This", key=use_key):
                    # Store extracted value in session so text_area picks it up
                    _store_use_this_value(spec, src, key_suffix)
                    st.rerun()
            else:
                st.caption("(Needs AI)")


def _store_use_this_value(spec, src, key_suffix: str):
    """Store a 'Use This' value in session state for the text area to pick up."""
    import json as _json
    sess_key = f"lpa_gap_usethis_{spec.key}_{key_suffix}"
    sess_source_key = f"lpa_gap_usethis_source_{spec.key}_{key_suffix}"

    if spec.value_type == "text":
        st.session_state[sess_key] = str(src.extracted_value)
    elif spec.value_type == "text_list":
        if isinstance(src.extracted_value, list):
            st.session_state[sess_key] = "\n".join(str(v) for v in src.extracted_value)
        else:
            st.session_state[sess_key] = str(src.extracted_value)
    elif spec.value_type in ("qa_list", "timeline_list", "json_array", "json"):
        st.session_state[sess_key] = _json.dumps(src.extracted_value, indent=2, ensure_ascii=False)
    else:
        st.session_state[sess_key] = str(src.extracted_value)

    # Store source info for provenance
    st.session_state[sess_source_key] = {
        "source_type": src.source_type,
        "source_table": src.source_table,
        "source_id": src.source_id,
        "confidence": src.confidence,
        "url": src.url,
    }


def _execute_gap_save(
    service,
    spec,
    value,
    brand_id: str,
    product_id: str,
    offer_variant_id,
    org_id: str,
    blueprint_id,
    key_suffix: str,
    force_overwrite: bool = False,
    source_type_override: str = None,
    source_detail_override: dict = None,
):
    """Execute the save action for a gap field."""
    # Check if a "Use This" source was used
    usethis_source_key = f"lpa_gap_usethis_source_{spec.key}_{key_suffix}"
    source_info = st.session_state.get(usethis_source_key)

    if source_type_override:
        src_type = source_type_override
        src_detail = source_detail_override or {}
    elif source_info:
        src_type = "cached_source"
        src_detail = source_info
    else:
        src_type = "manual"
        src_detail = {"entered_via": "gap_fixer"}

    result = service.apply_value(
        gap_key=spec.key,
        value=value,
        brand_id=brand_id,
        product_id=product_id,
        offer_variant_id=offer_variant_id,
        source_type=src_type,
        source_detail=src_detail,
        blueprint_id=blueprint_id,
        force_overwrite=force_overwrite,
        org_id=org_id,
    )

    if result.success:
        if result.action == "no_change":
            st.info("No changes — value matches current data.")
        else:
            save_key = f"{key_suffix}:{spec.key}"
            st.session_state.lpa_gaps_saved.add(save_key)
            target_label = f"{spec.table}.{spec.column}" if spec.column else spec.table
            st.success(f"Saved to {target_label}")
            st.rerun()
    elif result.needs_confirmation:
        st.warning("Field already has a value. Click 'Overwrite?' to confirm.")
    else:
        st.error(f"Save failed: {result.new_value or 'Unknown error'}")


def _run_fix_all(
    service,
    gaps: list,
    brand_id: str,
    product_id: str,
    offer_variant_id,
    org_id: str,
    blueprint_id,
    key_suffix: str,
):
    """Run batched AI extraction for all auto-fillable gaps."""
    import asyncio as _asyncio

    # Set tracking context
    try:
        from viraltracker.services.usage_tracker import UsageTracker
        tracker = UsageTracker(get_supabase_client())
        user_id = st.session_state.get("user_id")
        service.set_tracking_context(tracker, user_id, org_id)
    except Exception:
        pass

    progress = st.progress(0, text="Generating AI suggestions...")
    try:
        suggestions = _asyncio.run(
            service.generate_all_suggestions(
                gaps=gaps,
                brand_id=brand_id,
                product_id=product_id,
                offer_variant_id=offer_variant_id,
            )
        )
        progress.progress(1.0, text=f"Generated {len(suggestions)} suggestions")

        # Store suggestions in session state for each gap
        for s in suggestions:
            field_key = s.get("field", "")
            sess_key = f"{key_suffix}:{field_key}"
            st.session_state.lpa_gap_suggestions[sess_key] = s

            # Also prefill the "Use This" value from the suggestion
            from viraltracker.services.landing_page_analysis import GAP_FIELD_REGISTRY
            spec = GAP_FIELD_REGISTRY.get(field_key)
            if spec and s.get("value"):
                _prefill_from_suggestion(spec, s, key_suffix)

        st.success(f"Generated {len(suggestions)} AI suggestions. Review each below before saving.")
        st.rerun()
    except Exception as e:
        st.error(f"Fix All failed: {e}")
        progress.empty()


def _run_per_gap_suggestion(
    service,
    spec,
    brand_id: str,
    product_id: str,
    offer_variant_id,
    org_id: str,
    key_suffix: str,
):
    """Generate a single AI suggestion for one gap."""
    import asyncio as _asyncio

    # Set tracking context
    try:
        from viraltracker.services.usage_tracker import UsageTracker
        tracker = UsageTracker(get_supabase_client())
        user_id = st.session_state.get("user_id")
        service.set_tracking_context(tracker, user_id, org_id)
    except Exception:
        pass

    with st.spinner(f"Generating suggestion for {spec.display_name}..."):
        try:
            suggestion = _asyncio.run(
                service.generate_suggestion(
                    gap_key=spec.key,
                    brand_id=brand_id,
                    product_id=product_id,
                    offer_variant_id=offer_variant_id,
                )
            )
            if suggestion:
                sess_key = f"{key_suffix}:{spec.key}"
                st.session_state.lpa_gap_suggestions[sess_key] = suggestion
                if suggestion.get("value"):
                    _prefill_from_suggestion(spec, suggestion, key_suffix)
                st.rerun()
            else:
                st.warning("No suggestion generated. Not enough source data.")
        except Exception as e:
            st.error(f"Suggestion failed: {e}")


def _prefill_from_suggestion(spec, suggestion: dict, key_suffix: str):
    """Prefill the text area from an AI suggestion."""
    import json as _json

    sess_key = f"lpa_gap_usethis_{spec.key}_{key_suffix}"
    value = suggestion.get("value")

    if spec.value_type == "text":
        st.session_state[sess_key] = str(value)
    elif spec.value_type == "text_list":
        if isinstance(value, list):
            # Handle list of dicts with "text" key (from AI schema)
            texts = []
            for v in value:
                if isinstance(v, dict) and "text" in v:
                    texts.append(v["text"])
                else:
                    texts.append(str(v))
            st.session_state[sess_key] = "\n".join(texts)
        else:
            st.session_state[sess_key] = str(value)
    elif spec.value_type in ("qa_list", "timeline_list", "json_array", "json"):
        st.session_state[sess_key] = _json.dumps(value, indent=2, ensure_ascii=False)
    else:
        st.session_state[sess_key] = str(value)

    # Store AI source provenance
    source_key = f"lpa_gap_usethis_source_{spec.key}_{key_suffix}"
    st.session_state[source_key] = {
        "source_type": "ai_suggestion",
        "confidence": suggestion.get("confidence", "medium"),
        "evidence": suggestion.get("evidence") or suggestion.get("evidence_map"),
        "reasoning": suggestion.get("reasoning", ""),
    }


def _render_fresh_scrape_option(
    service,
    spec,
    brand_id: str,
    product_id: str,
    offer_variant_id,
    org_id: str,
    key_suffix: str,
):
    """Render the fresh scrape option for a gap field."""
    cooldown = service._get_scrape_cooldown_info(brand_id)
    ranked_urls = service._rank_scrape_urls(product_id, offer_variant_id, brand_id)

    if not ranked_urls:
        return

    scrape_col1, scrape_col2 = st.columns([3, 3])
    with scrape_col1:
        if cooldown and cooldown.get("within_cooldown"):
            st.caption(
                f"Last scraped {cooldown['hours_ago']:.0f}h ago. "
                "Cached data available above."
            )
        # Always show URL selector so user can pick a different page to scrape
        url_options = {u["url"]: u["label"] for u in ranked_urls}
        # Add "Custom URL" sentinel option
        custom_sentinel = "__custom__"
        url_options[custom_sentinel] = "Enter a custom URL..."
        selected_url = st.selectbox(
            "Scrape URL",
            options=list(url_options.keys()),
            format_func=lambda x: url_options[x],
            key=f"lpa_gap_scrape_url_{spec.key}_{key_suffix}",
        )
        if selected_url == custom_sentinel:
            custom_url = st.text_input(
                "Custom URL (https)",
                placeholder="https://example.com/ingredients",
                key=f"lpa_gap_scrape_custom_url_{spec.key}_{key_suffix}",
            )

    with scrape_col2:
        force = cooldown and cooldown.get("within_cooldown")
        btn_label = "Scrape Fresh (1 FireCrawl credit)"
        if force:
            btn_label = "Force Scrape (1 FireCrawl credit)"

        if st.button(
            btn_label,
            key=f"lpa_gap_scrape_{spec.key}_{key_suffix}",
        ):
            if not ranked_urls:
                st.warning("No URLs available for scraping.")
                return

            scrape_url = st.session_state.get(
                f"lpa_gap_scrape_url_{spec.key}_{key_suffix}",
                ranked_urls[0]["url"],
            )
            # Handle custom URL selection
            if scrape_url == "__custom__":
                scrape_url = st.session_state.get(
                    f"lpa_gap_scrape_custom_url_{spec.key}_{key_suffix}", ""
                ).strip()
                if not scrape_url:
                    st.warning("Please enter a URL to scrape.")
                    return
            _run_fresh_scrape(
                service=service,
                url=scrape_url,
                spec=spec,
                brand_id=brand_id,
                product_id=product_id,
                offer_variant_id=offer_variant_id,
                org_id=org_id,
                key_suffix=key_suffix,
            )


def _run_fresh_scrape(
    service,
    url: str,
    spec,
    brand_id: str,
    product_id: str,
    offer_variant_id,
    org_id: str,
    key_suffix: str,
):
    """Execute a fresh scrape and extract values."""
    import asyncio as _asyncio

    # Set tracking context
    try:
        from viraltracker.services.usage_tracker import UsageTracker
        tracker = UsageTracker(get_supabase_client())
        user_id = st.session_state.get("user_id")
        service.set_tracking_context(tracker, user_id, org_id)
    except Exception:
        pass

    with st.spinner(f"Scraping {url[:60]}..."):
        try:
            extracted = _asyncio.run(
                service.scrape_and_extract_from_lp(
                    url=url,
                    target_fields=[spec.key],
                    brand_id=brand_id,
                    product_id=product_id,
                    offer_variant_id=offer_variant_id,
                )
            )

            suggestion = extracted.get(spec.key)
            if suggestion:
                # Check for keyword warning
                warning = suggestion.get("keyword_warning")
                if warning:
                    st.warning(warning)

                # Store as suggestion
                sess_key = f"{key_suffix}:{spec.key}"
                st.session_state.lpa_gap_suggestions[sess_key] = suggestion

                if suggestion.get("value"):
                    _prefill_from_suggestion(spec, suggestion, key_suffix)

                st.success("Scrape complete! Review the extracted value below.")
                st.rerun()
            else:
                st.warning("Scrape succeeded but no data could be extracted for this field.")
        except ValueError as e:
            st.error(f"URL validation failed: {e}")
        except Exception as e:
            st.error(f"Scrape failed: {e}")


def _render_suggestion_evidence(suggestion: dict, spec):
    """Render the evidence panel for an AI suggestion."""
    confidence = suggestion.get("confidence", "unknown")
    conf_icon = {"high": "🟢", "medium": "🟡", "low": "🟠"}.get(confidence, "⚪")
    st.caption(f"AI Confidence: {conf_icon} {confidence}")

    reasoning = suggestion.get("reasoning", "")
    if reasoning:
        st.caption(f"Reasoning: {reasoning}")

    # Evidence for scalar fields
    evidence = suggestion.get("evidence", [])
    if evidence and isinstance(evidence, list):
        with st.expander("Evidence", expanded=False):
            for ev in evidence:
                source = ev.get("source", "unknown")
                snippet = ev.get("snippet", "")
                url = ev.get("url")
                st.markdown(f"**{source}**: \"{snippet}\"")
                if url:
                    st.caption(f"URL: {url}")

    # Evidence map for list fields
    evidence_map = suggestion.get("evidence_map", {})
    if evidence_map and isinstance(evidence_map, dict):
        with st.expander("Evidence (per item)", expanded=False):
            for item_id, ev in evidence_map.items():
                source = ev.get("source", "unknown")
                snippet = ev.get("snippet", "")
                st.markdown(f"**{item_id}** ({source}): \"{snippet}\"")


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
        _render_analysis_row(analysis, service, org_id)


def _render_analysis_row(analysis: dict, service, org_id: str):
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

        # --- Mockup Generation ---
        analysis_id = full.get("id", "")
        if analysis_id:
            _render_analysis_mockup_section(full, analysis_id, org_id)


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
# Mockup helpers
# ---------------------------------------------------------------------------

def _render_analysis_mockup_section(analysis: dict, analysis_id: str, org_id: str):
    """Render mockup generation controls for an analysis."""
    st.markdown("---")
    st.markdown("**Visual Mockup**")

    cached = _get_cached_mockup("analysis", analysis_id)

    if cached:
        _render_mockup_preview(cached, f"analysis_{analysis_id}")
        return

    screenshot_path = analysis.get("screenshot_storage_path")
    screenshot_b64 = None

    if screenshot_path:
        try:
            service = get_analysis_service()
            screenshot_bytes = service._load_screenshot(screenshot_path)
            if screenshot_bytes:
                import base64
                screenshot_b64 = base64.b64encode(screenshot_bytes).decode()
        except Exception as e:
            logger.warning(f"Failed to load screenshot: {e}")

    if not screenshot_path and not analysis.get("page_markdown") and not analysis.get("elements"):
        st.info("No screenshot or page content available for mockup.")
        if st.button("Capture Screenshot", key=f"rescrape_{analysis_id}"):
            _rescrape_for_screenshot(analysis, analysis_id, org_id)
        return

    if st.button(
        "Generate Mockup",
        key=f"lpa_gen_mockup_analysis_{analysis_id}",
    ):
        svc = get_mockup_service()
        # Wire up usage tracking
        try:
            from viraltracker.services.usage_tracker import UsageTracker
            tracker = UsageTracker(get_supabase_client())
            user_id = st.session_state.get("user_id")
            svc.set_tracking_context(tracker, user_id, org_id)
        except Exception:
            pass

        spinner_text = "Generating page mockup..." if screenshot_b64 else "Rendering page content..."
        with st.spinner(spinner_text):
            try:
                html_str = svc.generate_analysis_mockup(
                    screenshot_b64=screenshot_b64,
                    element_detection=analysis.get("elements", {}),
                    classification=analysis.get("classification", {}),
                    page_markdown=analysis.get("page_markdown"),
                )
                _cache_mockup("analysis", analysis_id, html_str)
                st.rerun()
            except Exception as e:
                st.error(f"Mockup generation failed: {e}")


def _rescrape_for_screenshot(analysis: dict, analysis_id: str, org_id: str):
    """Re-scrape URL to capture screenshot only."""
    with st.spinner("Capturing page screenshot..."):
        try:
            service = get_analysis_service()
            page_data = service.scrape_landing_page(analysis.get("url", ""))
            ss_b64 = page_data.get("screenshot")
            if ss_b64:
                service._store_screenshot(analysis_id, org_id, ss_b64)
                st.rerun()
            else:
                st.error("Failed to capture screenshot.")
        except Exception as e:
            st.error(f"Re-scrape failed: {e}")


def _render_blueprint_mockup_section(
    result: dict,
    blueprint_id: str,
    brand_id: Optional[str] = None,
    product_id: Optional[str] = None,
    org_id: Optional[str] = None,
):
    """Render mockup generation controls for a blueprint."""
    cached = _get_cached_mockup("blueprint", blueprint_id)

    if cached:
        _render_mockup_preview(cached, f"blueprint_{blueprint_id}")
        if st.button(
            "Regenerate Mockup",
            key=f"lpa_regen_mockup_blueprint_{blueprint_id}",
        ):
            # Clear stale cache and force regeneration
            cache_key = f"lpa_mockup_blueprint_{blueprint_id}"
            st.session_state.pop(cache_key, None)
            # Also clear analysis cache so it's re-fetched fresh
            analysis_id = result.get("analysis_id")
            if analysis_id:
                analysis_cache_key = f"lpa_mockup_analysis_{analysis_id}"
                st.session_state.pop(analysis_cache_key, None)
            st.rerun()
        return
    elif st.button(
        "Render Mockup",
        key=f"lpa_gen_mockup_blueprint_{blueprint_id}",
    ):
        blueprint = result.get("blueprint", {})

        if not blueprint:
            st.warning("No blueprint data available.")
            return

        # Fetch classification from linked analysis if available
        classification = None
        analysis_id = result.get("analysis_id")
        if not analysis_id:
            st.warning(
                "This blueprint has no linked analysis. "
                "Go to the **Analyze** tab and run an analysis first."
            )
            return
        if analysis_id:
            try:
                analysis_svc = get_analysis_service()
                linked = analysis_svc.get_analysis(analysis_id)
                if linked:
                    classification = linked.get("classification", {})
            except Exception:
                pass

        # Fetch brand profile for AI rewrite
        brand_profile = None
        if brand_id and product_id:
            try:
                from viraltracker.services.landing_page_analysis import BrandProfileService
                bp_svc = BrandProfileService(get_supabase_client())
                brand_profile = bp_svc.get_brand_profile(brand_id, product_id)
                if brand_profile:
                    logger.info(f"Brand profile loaded for mockup rewrite (brand={brand_id})")
                else:
                    logger.warning(f"BrandProfileService returned None (brand={brand_id}, product={product_id})")
            except Exception as e:
                logger.warning(f"Failed to load brand profile: {e}")
        else:
            logger.warning(f"Missing brand_id={brand_id} or product_id={product_id} — cannot load brand profile")

        # Get cached analysis HTML
        analysis_html = _get_cached_mockup("analysis", analysis_id) if analysis_id else None

        # If not cached, try regenerating from stored screenshot or page_markdown
        if not analysis_html and analysis_id:
            analysis_svc = get_analysis_service()
            linked_record = analysis_svc.get_analysis(analysis_id) or {}
            screenshot_path = linked_record.get("screenshot_storage_path")
            page_markdown = linked_record.get("page_markdown")

            screenshot_b64 = None
            if screenshot_path:
                import base64
                screenshot_bytes = analysis_svc._load_screenshot(screenshot_path)
                if screenshot_bytes:
                    screenshot_b64 = base64.b64encode(screenshot_bytes).decode()
                else:
                    logger.warning(f"Screenshot download returned empty for {screenshot_path}")

            if screenshot_b64 or page_markdown:
                source = "screenshot (AI vision)" if screenshot_b64 else "page markdown"
                with st.spinner(f"Rebuilding analysis mockup from {source}..."):
                    try:
                        regen_svc = get_mockup_service()
                        if org_id:
                            try:
                                from viraltracker.services.usage_tracker import UsageTracker
                                tracker = UsageTracker(get_supabase_client())
                                user_id = st.session_state.get("user_id")
                                regen_svc.set_tracking_context(tracker, user_id, org_id)
                            except Exception:
                                pass
                        analysis_html = regen_svc.generate_analysis_mockup(
                            screenshot_b64=screenshot_b64,
                            classification=classification,
                            page_markdown=page_markdown,
                        )
                        if analysis_html:
                            _cache_mockup("analysis", analysis_id, analysis_html)
                    except Exception as e:
                        logger.error(f"Failed to regenerate analysis mockup: {e}")
                        st.error(f"Analysis mockup regeneration failed: {e}")
            else:
                logger.warning(
                    f"Analysis {analysis_id} has no screenshot "
                    f"(path={screenshot_path}) and no page_markdown"
                )
                st.warning(
                    "No screenshot or page content found for the linked analysis. "
                    "Go to the **Analyze** tab and re-analyze the URL to capture a screenshot."
                )

        # Create main mockup service with tracking
        mockup_svc = get_mockup_service()
        if org_id:
            try:
                from viraltracker.services.usage_tracker import UsageTracker
                tracker = UsageTracker(get_supabase_client())
                user_id = st.session_state.get("user_id")
                mockup_svc.set_tracking_context(tracker, user_id, org_id)
            except Exception:
                pass

        # Generate blueprint mockup
        try:
            with st.spinner("Rewriting page copy for your brand (AI)..."):
                html_str = mockup_svc.generate_blueprint_mockup(
                    blueprint,
                    analysis_mockup_html=analysis_html,
                    classification=classification,
                    brand_profile=brand_profile,
                )

            if html_str:
                _cache_mockup("blueprint", blueprint_id, html_str)
                st.rerun()
            else:
                st.warning(
                    "Could not generate visual mockup — no analysis page HTML is available. "
                    "To fix this: go to the **Analyze** tab, generate an analysis mockup "
                    "for the source page first, then return here to render the blueprint mockup."
                )
        except Exception as e:
            st.error(f"AI copy rewrite failed: {e}")
            logger.error(f"Blueprint mockup generation failed: {e}", exc_info=True)


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
        _render_blueprint(
            st.session_state.lpa_latest_blueprint,
            brand_id=brand_id,
            product_id=product_id,
            offer_variant_id=offer_variant_id,
            org_id=org_id,
        )

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


def _render_blueprint(
    result: dict,
    key_suffix: str = "latest",
    brand_id: Optional[str] = None,
    product_id: Optional[str] = None,
    offer_variant_id: Optional[str] = None,
    org_id: Optional[str] = None,
):
    """Render a generated blueprint with section accordion, gap fixer, and exports."""
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

    # --- Brand Profile Gaps (raw list) ---
    gaps = result.get("brand_profile_gaps", [])
    if gaps:
        with st.expander(f"Brand Profile Gaps ({len(gaps)} items)", expanded=False):
            for gap in gaps:
                severity = gap.get("severity", "low")
                icon = {"critical": "🔴", "moderate": "🟡", "low": "🟢"}.get(severity, "⚪")
                st.markdown(f"{icon} **{gap.get('field', '?')}** ({gap.get('section', '')}) — {gap.get('instruction', '')}")

    # --- Gap Fixer (inline fill controls) ---
    if gaps and brand_id and product_id and org_id:
        st.divider()
        _render_gap_fixer(
            result=result,
            brand_id=brand_id,
            product_id=product_id,
            offer_variant_id=offer_variant_id,
            org_id=org_id,
            key_suffix=key_suffix,
        )

    # --- Exports ---
    st.markdown("### Export")
    export_col1, export_col2, export_col3 = st.columns(3)
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
    with export_col3:
        blueprint_id = result.get("id", key_suffix)
        st.markdown("**Visual Mockup**")
        _render_blueprint_mockup_section(
            result,
            blueprint_id=blueprint_id,
            brand_id=brand_id,
            product_id=product_id,
            org_id=org_id,
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
                "id": bp["id"],
                "blueprint": full.get("blueprint", {}),
                "source_url": full.get("source_url", ""),
                "brand_profile_gaps": full.get("content_gaps", []),
                "sections_count": full.get("sections_count", 0),
                "elements_mapped": full.get("elements_mapped", 0),
                "content_needed_count": full.get("content_needed_count", 0),
            }
            _render_blueprint(
                result_like,
                key_suffix=bp["id"],
                brand_id=full.get("brand_id"),
                product_id=full.get("product_id"),
                offer_variant_id=full.get("offer_variant_id"),
                org_id=full.get("organization_id"),
            )


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
