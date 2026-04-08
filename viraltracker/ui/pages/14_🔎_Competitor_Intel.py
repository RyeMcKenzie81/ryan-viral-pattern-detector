"""
Competitor Ad Intelligence - Generate ingredient packs from competitor video ads.

Three tabs:
- Generate Pack: Score, analyze, and aggregate competitor video ads
- Video Details: Drill down into individual video extractions
- Remix & Save: Remix competitor structure into your own ad script, save to angle pipeline
"""

import streamlit as st
import asyncio
import json
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List, Optional

# Page config
st.set_page_config(
    page_title="Competitor Intel",
    page_icon="🔎",
    layout="wide"
)

# Authentication
from viraltracker.ui.auth import require_auth
require_auth()
from viraltracker.ui.utils import require_feature
require_feature("competitor_intel", "Competitor Intel")


# ============================================
# SESSION STATE
# ============================================

if "ci_selected_pack_id" not in st.session_state:
    st.session_state.ci_selected_pack_id = None
if "ci_selected_video_idx" not in st.session_state:
    st.session_state.ci_selected_video_idx = None


# ============================================
# HELPERS
# ============================================

def get_supabase_client():
    from viraltracker.core.database import get_supabase_client
    return get_supabase_client()


def get_competitor_intel_service():
    from viraltracker.services.competitor_intel_service import CompetitorIntelService
    return CompetitorIntelService()


def get_competitors_for_brand(brand_id: str) -> List[Dict]:
    try:
        from viraltracker.services.competitor_service import CompetitorService
        service = CompetitorService()
        from uuid import UUID
        return service.get_competitors_for_brand(UUID(brand_id))
    except Exception as e:
        st.error(f"Failed to fetch competitors: {e}")
        return []


def get_products_for_brand(brand_id: str) -> List[Dict]:
    try:
        db = get_supabase_client()
        result = db.table("products").select("id, name").eq("brand_id", brand_id).order("name").execute()
        return result.data or []
    except Exception:
        return []


def get_organization_id() -> str:
    from viraltracker.ui.auth import get_current_organization_id
    return get_current_organization_id()


def create_analysis_job(
    competitor_id: str,
    competitor_name: str,
    brand_id: str,
    organization_id: str,
    n_videos: int,
    product_id: Optional[str] = None,
) -> Optional[str]:
    """Create a one-time scheduled job for competitor intel analysis."""
    try:
        db = get_supabase_client()
        job_row = {
            "name": f"Competitor Intel - {competitor_name}",
            "job_type": "competitor_intel_analysis",
            "brand_id": brand_id,
            "schedule_type": "one_time",
            "next_run_at": (datetime.utcnow() + timedelta(minutes=1)).isoformat(),
            "is_active": True,
            "parameters": json.dumps({
                "competitor_id": competitor_id,
                "organization_id": organization_id,
                "n_videos": n_videos,
                "product_id": product_id,
            }),
        }
        result = db.table("scheduled_jobs").insert(job_row).execute()
        return result.data[0]["id"] if result.data else None
    except Exception as e:
        st.error(f"Failed to create job: {e}")
        return None


# ============================================
# TAB 1: GENERATE PACK
# ============================================

def render_generate_tab(brand_id: str, competitor_id: str, competitor_name: str):
    """Render the Generate Pack tab."""
    org_id = get_organization_id()
    service = get_competitor_intel_service()

    # Sidebar controls
    col_controls, col_main = st.columns([1, 2])

    with col_controls:
        st.markdown("### Settings")

        # Product selector (optional)
        products = get_products_for_brand(brand_id)
        product_options = {"None (explore only)": None}
        product_options.update({p["name"]: p["id"] for p in products})
        product_name = st.selectbox("Product (for pipeline save)", options=list(product_options.keys()), key="ci_product_selector")
        product_id = product_options[product_name]

        n_videos = st.slider("Videos to analyze", min_value=3, max_value=20, value=10, key="ci_n_videos")

        # Pre-flight check
        readiness = service.check_video_readiness(competitor_id)
        if readiness["ready"]:
            st.success(readiness["message"])
        elif readiness["total_video_ads"] > 0:
            st.warning(readiness["message"])
        else:
            st.info(readiness["message"])

        st.caption(f"~{n_videos * 45}s estimated ({n_videos} videos x ~45s each)")

        # Generate button
        if st.button("Generate Ingredient Pack", type="primary", key="ci_generate_btn", disabled=not readiness["ready"]):
            job_id = create_analysis_job(
                competitor_id=competitor_id,
                competitor_name=competitor_name,
                brand_id=brand_id,
                organization_id=org_id,
                n_videos=n_videos,
                product_id=product_id,
            )
            if job_id:
                st.success(f"Analysis job created! Check back in ~{n_videos}min for results.")
                st.info("The job will run in the background. Refresh this page to see progress.")

        st.divider()

        # Show existing packs
        st.markdown("### Previous Packs")
        packs = service.get_packs_for_competitor(competitor_id, org_id)
        if not packs:
            st.caption("No packs generated yet.")
        for pack in packs:
            status_emoji = {"complete": "✅", "partial": "⚠️", "failed": "❌", "processing": "⏳", "pending": "🔄"}.get(pack["status"], "❓")
            label = f"{status_emoji} {pack['created_at'][:16]} ({pack['video_count']} videos)"
            if st.button(label, key=f"ci_pack_{pack['id']}"):
                st.session_state.ci_selected_pack_id = pack["id"]
                st.rerun()

    with col_main:
        # Show selected pack or processing status
        selected_pack_id = st.session_state.ci_selected_pack_id

        # Auto-select latest complete pack if none selected
        if not selected_pack_id:
            packs = service.get_packs_for_competitor(competitor_id, org_id)
            for p in packs:
                if p["status"] in ("complete", "partial"):
                    selected_pack_id = p["id"]
                    st.session_state.ci_selected_pack_id = p["id"]
                    break

        if not selected_pack_id:
            # Check for processing packs
            for p in packs:
                if p["status"] in ("processing", "pending"):
                    st.info(f"Pack in progress: {p['videos_completed']}/{p['video_count']} videos completed...")
                    st.caption("Refresh the page to see updated progress.")
                    return
            st.info("Select a competitor and click **Generate Ingredient Pack** to get started.")
            return

        pack = service.get_pack(selected_pack_id)
        if not pack:
            st.error("Pack not found.")
            return

        if pack["status"] == "processing":
            st.info(f"Processing: {pack['videos_completed']}/{pack['video_count']} videos completed...")
            progress = pack["videos_completed"] / max(pack["video_count"], 1)
            st.progress(progress)
            remaining = pack["video_count"] - pack["videos_completed"]
            st.caption(f"{remaining} remaining, ~{remaining * 45}s left")
            return

        if pack["status"] == "failed":
            st.error(f"Pack generation failed. {pack.get('error_summary', '')}")
            return

        if pack["status"] == "partial":
            st.warning(f"Partial results: some videos failed during analysis.")

        render_pack_data(pack)


def render_pack_data(pack: Dict):
    """Render the aggregated ingredient pack data."""
    pack_data = pack.get("pack_data") or {}
    if not pack_data:
        st.info("No aggregated data available.")
        return

    st.markdown(f"### Ingredient Pack ({pack['video_count']} videos)")

    # Field coverage sidebar
    coverage = pack_data.get("field_coverage") or pack.get("field_coverage") or {}
    if coverage:
        with st.expander("Field Coverage", expanded=False):
            for field, stats in coverage.items():
                if isinstance(stats, dict):
                    pct = stats["populated"] / max(stats["total"], 1)
                    st.progress(pct, text=f"{field}: {stats['populated']}/{stats['total']}")

    # Hooks (expanded by default)
    hooks = pack_data.get("hooks", [])
    with st.expander(f"Hooks ({len(hooks)})", expanded=True):
        if not hooks:
            st.caption("No hooks extracted.")
        for i, hook in enumerate(hooks):
            col_score, col_text = st.columns([1, 4])
            with col_score:
                st.metric("Score", f"{hook.get('score', 0):.2f}")
            with col_text:
                st.markdown(f"**{hook.get('text', 'N/A')}**")
                st.caption(f"Type: {hook.get('type', 'unknown')} | Frequency: {hook.get('frequency', 1)}")

    # Personas
    personas = pack_data.get("personas", [])
    with st.expander(f"4D Personas ({len(personas)})"):
        if not personas:
            st.caption("No personas extracted.")
        for p in personas:
            st.markdown(f"**Demographics:** {p.get('demographics', 'N/A')}")
            st.markdown(f"**Psychographics:** {p.get('psychographics', 'N/A')}")
            if p.get("beliefs"):
                st.markdown("**Beliefs:** " + ", ".join(p["beliefs"]))
            if p.get("behaviors"):
                st.markdown("**Behaviors:** " + ", ".join(p["behaviors"]))
            st.caption(f"Frequency: {p.get('frequency', 1)} videos")
            st.divider()

    # Angles
    angles = pack_data.get("angles", [])
    with st.expander(f"Angles ({len(angles)})"):
        if not angles:
            st.caption("No angles extracted.")
        for a in angles:
            st.markdown(f"**{a.get('belief_statement', 'N/A')}**")
            st.caption(f"Evidence: {a.get('evidence', 'N/A')} | Frequency: {a.get('frequency', 1)}")

    # Benefits
    benefits = pack_data.get("benefits", [])
    with st.expander(f"Benefits ({len(benefits)})"):
        for b in benefits:
            text = b.get("text", b) if isinstance(b, dict) else str(b)
            freq = b.get("frequency", 1) if isinstance(b, dict) else 1
            st.markdown(f"- {text} (x{freq})")

    # Pain Points
    pains = pack_data.get("pain_points", [])
    with st.expander(f"Pain Points ({len(pains)})"):
        for p in pains:
            text = p.get("text", p) if isinstance(p, dict) else str(p)
            freq = p.get("frequency", 1) if isinstance(p, dict) else 1
            st.markdown(f"- {text} (x{freq})")

    # JTBDs
    jtbds = pack_data.get("jtbds", [])
    with st.expander(f"Jobs to Be Done ({len(jtbds)})"):
        for j in jtbds:
            text = j.get("text", j) if isinstance(j, dict) else str(j)
            st.markdown(f"- {text}")

    # Awareness
    awareness = pack_data.get("awareness_distribution", {})
    primary = pack_data.get("primary_awareness_level", "unknown")
    with st.expander(f"Awareness Levels (primary: {primary})"):
        if awareness:
            for level, pct in sorted(awareness.items(), key=lambda x: x[1], reverse=True):
                st.progress(float(pct), text=f"{level}: {pct:.0%}")
        else:
            st.caption("No awareness data.")

    # Objections
    objections = pack_data.get("objections", [])
    with st.expander(f"Objections Addressed ({len(objections)})"):
        for o in objections:
            text = o.get("text", o) if isinstance(o, dict) else str(o)
            st.markdown(f"- {text}")

    # Mechanisms
    for mech_key, label in [("unique_mechanisms", "Unique Mechanisms"), ("unique_problem_mechanisms", "UMPs"), ("unique_solution_mechanisms", "UMSs")]:
        mechs = pack_data.get(mech_key, [])
        with st.expander(f"{label} ({len(mechs)})"):
            if not mechs:
                st.caption(f"No {label.lower()} extracted.")
            for m in mechs:
                text = m.get("text", m) if isinstance(m, dict) else str(m)
                freq = m.get("frequency", 1) if isinstance(m, dict) else 1
                st.markdown(f"- {text} (x{freq})")

    # Emotional Triggers
    triggers = pack_data.get("emotional_triggers", [])
    with st.expander(f"Emotional Triggers ({len(triggers)})"):
        for t in triggers:
            text = t.get("text", t) if isinstance(t, dict) else str(t)
            st.markdown(f"- {text}")


# ============================================
# TAB 2: VIDEO DETAILS
# ============================================

def render_video_details_tab(competitor_id: str):
    """Render the Video Details drill-down tab."""
    org_id = get_organization_id()
    service = get_competitor_intel_service()

    pack_id = st.session_state.ci_selected_pack_id
    if not pack_id:
        packs = service.get_packs_for_competitor(competitor_id, org_id)
        for p in packs:
            if p["status"] in ("complete", "partial"):
                pack_id = p["id"]
                break

    if not pack_id:
        st.info("Generate an ingredient pack first to see individual video details.")
        return

    pack = service.get_pack(pack_id)
    if not pack:
        st.error("Pack not found.")
        return

    analyses = pack.get("video_analyses") or []
    if not analyses:
        st.info("No individual video analyses available.")
        return

    st.markdown(f"### Video Analyses ({len(analyses)} videos)")

    # Video selector
    video_labels = []
    for i, va in enumerate(analyses):
        score = va.get("composite_score", 0)
        ad_id = va.get("ad_id", "unknown")[:8]
        video_labels.append(f"Video {i+1} (score: {score:.2f}, ad: {ad_id}...)")

    selected_idx = st.selectbox("Select video", range(len(video_labels)), format_func=lambda i: video_labels[i], key="ci_video_select")

    if selected_idx is not None and selected_idx < len(analyses):
        render_single_extraction(analyses[selected_idx])


def render_single_extraction(video_analysis: Dict):
    """Render a single video's extraction data."""
    extraction = video_analysis.get("extraction", video_analysis)
    score = video_analysis.get("composite_score")
    ad_id = video_analysis.get("ad_id", "")

    if score:
        st.metric("Composite Score", f"{score:.3f}")
    if ad_id:
        st.caption(f"Ad ID: {ad_id}")

    # Transcription
    transcription = extraction.get("transcription", {})
    with st.expander("Transcription", expanded=True):
        if isinstance(transcription, dict):
            st.text(transcription.get("full_text", "No transcription."))
            timestamps = transcription.get("timestamps", [])
            if timestamps:
                for ts in timestamps:
                    if isinstance(ts, dict):
                        st.caption(f"{ts.get('time', '')}: {ts.get('text', '')}")
        elif isinstance(transcription, str):
            st.text(transcription)
        else:
            st.caption("No transcription available.")

    # Hook
    hook = extraction.get("hook", {})
    with st.expander("Hook"):
        if isinstance(hook, dict) and hook.get("text"):
            st.markdown(f"**{hook['text']}**")
            st.caption(f"Type: {hook.get('type', 'unknown')} | Timestamp: {hook.get('timestamp', 'N/A')}")
        else:
            st.caption("No hook extracted.")

    # Storyboard
    storyboard = extraction.get("storyboard", [])
    with st.expander(f"Storyboard ({len(storyboard)} frames)"):
        for frame in storyboard:
            if isinstance(frame, dict):
                st.markdown(f"**{frame.get('timestamp', '')}:** {frame.get('description', '')}")

    # Persona
    persona = extraction.get("persona_4d", {})
    with st.expander("4D Persona"):
        if isinstance(persona, dict) and persona:
            st.markdown(f"**Demographics:** {persona.get('demographics', 'N/A')}")
            st.markdown(f"**Psychographics:** {persona.get('psychographics', 'N/A')}")
            if persona.get("beliefs"):
                st.markdown("**Beliefs:** " + ", ".join(persona["beliefs"]))
            if persona.get("behaviors"):
                st.markdown("**Behaviors:** " + ", ".join(persona["behaviors"]))
        else:
            st.caption("No persona extracted.")

    # Awareness
    awareness = extraction.get("awareness_level")
    reasoning = extraction.get("awareness_reasoning", "")
    with st.expander("Awareness Level"):
        if awareness:
            st.markdown(f"**{awareness}**")
            if reasoning:
                st.caption(reasoning)
        else:
            st.caption("Not determined.")

    # Remaining fields in compact layout
    for field, label in [
        ("benefits", "Benefits"),
        ("pain_points", "Pain Points"),
        ("jtbds", "JTBDs"),
        ("objections_addressed", "Objections"),
        ("emotional_triggers", "Emotional Triggers"),
    ]:
        items = extraction.get(field, [])
        with st.expander(f"{label} ({len(items)})"):
            for item in items:
                if isinstance(item, str):
                    st.markdown(f"- {item}")
                elif isinstance(item, dict):
                    st.markdown(f"- {item.get('text', item.get('belief_statement', str(item)))}")

    # Angles
    angles = extraction.get("angles", [])
    with st.expander(f"Angles ({len(angles)})"):
        for a in angles:
            if isinstance(a, dict):
                st.markdown(f"**{a.get('belief_statement', 'N/A')}**")
                st.caption(f"Evidence: {a.get('evidence_in_video', a.get('evidence', 'N/A'))}")

    # Mechanisms
    for field, label in [
        ("unique_mechanism", "Unique Mechanism"),
        ("unique_problem_mechanism", "UMP"),
        ("unique_solution_mechanism", "UMS"),
    ]:
        val = extraction.get(field)
        with st.expander(label):
            if val and isinstance(val, str) and val.strip():
                st.markdown(val)
            else:
                st.caption("Not extracted.")

    # Messaging Sequence
    sequence = extraction.get("messaging_sequence", [])
    with st.expander(f"Messaging Sequence ({len(sequence)} stages)"):
        for stage in sequence:
            if isinstance(stage, dict):
                st.markdown(f"**{stage.get('stage', '?')}** ({stage.get('timestamp', '')}): {stage.get('content', '')}")

    # CTA
    cta = extraction.get("cta", {})
    with st.expander("CTA"):
        if isinstance(cta, dict) and cta.get("text"):
            st.markdown(f"**{cta['text']}** (type: {cta.get('type', 'unknown')})")
        else:
            st.caption("No CTA extracted.")

    # Format info
    col1, col2 = st.columns(2)
    with col1:
        st.caption(f"Ad format: {extraction.get('ad_format', 'unknown')}")
    with col2:
        st.caption(f"Production: {extraction.get('estimated_production_level', 'unknown')}")


# ============================================
# TAB 3: REMIX & SAVE
# ============================================

def render_remix_tab(brand_id: str, competitor_id: str):
    """Render the Remix & Save tab."""
    org_id = get_organization_id()
    service = get_competitor_intel_service()

    pack_id = st.session_state.ci_selected_pack_id
    if not pack_id:
        packs = service.get_packs_for_competitor(competitor_id, org_id)
        for p in packs:
            if p["status"] in ("complete", "partial"):
                pack_id = p["id"]
                break

    if not pack_id:
        st.info("Generate an ingredient pack first.")
        return

    pack = service.get_pack(pack_id)
    if not pack:
        st.error("Pack not found.")
        return

    col_remix, col_save = st.columns([2, 1])

    with col_remix:
        st.markdown("### Remix Competitor Video")

        analyses = pack.get("video_analyses") or []
        if not analyses:
            st.info("No video analyses available for remix.")
            return

        # Select source video
        video_labels = []
        for i, va in enumerate(analyses):
            score = va.get("composite_score", 0)
            hook = (va.get("extraction", {}).get("hook") or {})
            hook_text = hook.get("text", "")[:50] if isinstance(hook, dict) else ""
            video_labels.append(f"Video {i+1} (score: {score:.2f}) - {hook_text}")

        selected_idx = st.selectbox("Source video", range(len(video_labels)), format_func=lambda i: video_labels[i], key="ci_remix_video")

        if selected_idx is not None and selected_idx < len(analyses):
            extraction = analyses[selected_idx].get("extraction", {})

            # Show competitor structure preview
            with st.expander("Competitor video structure", expanded=False):
                hook = extraction.get("hook", {})
                if isinstance(hook, dict) and hook.get("text"):
                    st.markdown(f"**Hook:** {hook['text']}")
                sequence = extraction.get("messaging_sequence", [])
                for s in sequence:
                    if isinstance(s, dict):
                        st.caption(f"{s.get('stage', '?')}: {s.get('content', '')}")

            # Brand context inputs
            st.markdown("#### Your Brand Context")
            brand_context = st.text_area("Additional context about your brand/product", key="ci_remix_context", height=80)
            product_desc = st.text_input("Product description", key="ci_remix_product")
            target_audience = st.text_input("Target audience", key="ci_remix_audience")
            brand_guidelines = st.text_input("Brand guidelines / tone", key="ci_remix_guidelines")

            if st.button("Generate Ad Script", type="primary", key="ci_remix_btn"):
                with st.spinner("Generating script via Claude..."):
                    try:
                        result = asyncio.run(service.remix_video(
                            video_extraction=extraction,
                            brand_context=brand_context,
                            product_description=product_desc or None,
                            target_audience=target_audience or None,
                            brand_guidelines=brand_guidelines or None,
                        ))
                        st.session_state.ci_remix_result = result
                    except Exception as e:
                        st.error(f"Remix failed: {e}")

            # Show result
            if "ci_remix_result" in st.session_state and st.session_state.ci_remix_result:
                result = st.session_state.ci_remix_result
                st.markdown("---")
                st.markdown("### Generated Script")
                st.text_area("Script", value=result.get("script_text", ""), height=300, key="ci_script_output")

                stages = result.get("stages", [])
                if stages:
                    with st.expander("Scene Breakdown"):
                        for s in stages:
                            if isinstance(s, dict):
                                st.markdown(f"**{s.get('stage', '?')}:** {s.get('content', s.get('dialogue', ''))}")
                                if s.get("visuals"):
                                    st.caption(f"Visuals: {s['visuals']}")

                if result.get("estimated_duration"):
                    st.caption(f"Estimated duration: {result['estimated_duration']}")
                if result.get("production_notes"):
                    st.caption(f"Production notes: {result['production_notes']}")

    with col_save:
        st.markdown("### Save to Pipeline")

        products = get_products_for_brand(brand_id)
        if not products:
            st.warning("No products found. Add products to save to the angle pipeline.")
            return

        product_options = {p["name"]: p["id"] for p in products}
        save_product_name = st.selectbox("Product", options=list(product_options.keys()), key="ci_save_product")
        save_product_id = product_options[save_product_name]

        pack_data = pack.get("pack_data") or {}
        n_hooks = min(5, len(pack_data.get("hooks", [])))
        n_angles = min(5, len(pack_data.get("angles", [])))
        n_pains = min(5, len(pack_data.get("pain_points", [])))
        n_jtbds = min(5, len(pack_data.get("jtbds", [])))

        st.caption(f"Will save: {n_hooks} hooks, {n_angles} angles, {n_pains} pain points, {n_jtbds} JTBDs")

        if st.button("Save Pack to Angle Pipeline", type="primary", key="ci_save_btn"):
            try:
                counts = service.save_to_angle_pipeline(
                    pack_id=pack_id,
                    product_id=save_product_id,
                    organization_id=org_id,
                    brand_id=brand_id,
                )
                total = sum(counts.values())
                st.success(f"Saved {total} candidates to the angle pipeline!")
                st.json(counts)
            except Exception as e:
                st.error(f"Failed to save: {e}")


# ============================================
# MAIN PAGE
# ============================================

st.title("🔎 Competitor Intel")

# Brand selector
from viraltracker.ui.utils import render_brand_selector
brand_id = render_brand_selector(key="ci_brand_selector")
if not brand_id:
    st.stop()

# Competitor selector
competitors = get_competitors_for_brand(brand_id)
if not competitors:
    st.warning("No competitors found. Add competitors on the Competitors page first.")
    st.stop()

competitor_options = {c["name"]: c["id"] for c in competitors}
competitor_name = st.selectbox("Competitor", options=list(competitor_options.keys()), key="ci_competitor_selector")
competitor_id = competitor_options[competitor_name]

st.divider()

# Tabs
tab_generate, tab_videos, tab_remix = st.tabs(["Generate Pack", "Video Details", "Remix & Save"])

with tab_generate:
    render_generate_tab(brand_id, competitor_id, competitor_name)

with tab_videos:
    render_video_details_tab(competitor_id)

with tab_remix:
    render_remix_tab(brand_id, competitor_id)
