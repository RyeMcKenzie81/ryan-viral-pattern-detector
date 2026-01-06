"""
Research Insights - Unified Angle Pipeline UI.

Phase 7 of Angle Pipeline: View and manage angle candidates from all research sources.

Features:
- Frequency-ranked candidate display
- Filter by source, confidence, status
- Evidence drill-down viewer
- "Promote to Angle" workflow with JTBD selection
- Reject candidate functionality
- Recently promoted section
"""

import streamlit as st
from datetime import datetime
from typing import Optional, List, Dict, Any
from uuid import UUID

st.set_page_config(
    page_title="Research Insights",
    page_icon="💡",
    layout="wide"
)

# ============================================
# SERVICE INITIALIZATION
# ============================================


def get_angle_candidate_service():
    """Get AngleCandidateService instance."""
    from viraltracker.services.angle_candidate_service import AngleCandidateService
    return AngleCandidateService()


def get_planning_service():
    """Get PlanningService instance."""
    from viraltracker.services.planning_service import PlanningService
    return PlanningService()


def get_supabase_client():
    """Get Supabase client."""
    from viraltracker.core.database import get_supabase_client
    return get_supabase_client()


# ============================================
# SESSION STATE
# ============================================

if 'ri_status_filter' not in st.session_state:
    st.session_state.ri_status_filter = "candidate"
if 'ri_source_filter' not in st.session_state:
    st.session_state.ri_source_filter = "all"
if 'ri_confidence_filter' not in st.session_state:
    st.session_state.ri_confidence_filter = "all"
if 'ri_selected_candidate_id' not in st.session_state:
    st.session_state.ri_selected_candidate_id = None
if 'ri_promote_candidate_id' not in st.session_state:
    st.session_state.ri_promote_candidate_id = None
if 'ri_confirm_reject' not in st.session_state:
    st.session_state.ri_confirm_reject = None


# ============================================
# CONSTANTS
# ============================================

SOURCE_LABELS = {
    "belief_reverse_engineer": "Belief RE",
    "reddit_research": "Reddit",
    "ad_performance": "Ad Performance",
    "competitor_research": "Competitor",
    "brand_research": "Brand",
}

SOURCE_ICONS = {
    "belief_reverse_engineer": "🧠",
    "reddit_research": "🔍",
    "ad_performance": "📈",
    "competitor_research": "🎯",
    "brand_research": "🔬",
}

CONFIDENCE_BADGES = {
    "HIGH": ("🔴", "red"),
    "MEDIUM": ("🟡", "orange"),
    "LOW": ("🟢", "green"),
}

TYPE_LABELS = {
    "pain_signal": "Pain Signal",
    "jtbd": "Job to Be Done",
    "pattern": "Pattern",
    "ad_hypothesis": "Ad Hypothesis",
    "quote": "Quote",
    "ump": "Unique Mechanism (Problem)",
    "ums": "Unique Mechanism (Solution)",
}


# ============================================
# DATA FETCHING
# ============================================

@st.cache_data(ttl=30)
def fetch_candidates(
    product_id: str,
    status: Optional[str] = "candidate",
    source_type: Optional[str] = None,
    limit: int = 100
) -> List[Dict]:
    """Fetch candidates for a product with filters."""
    service = get_angle_candidate_service()
    candidates = service.get_candidates_for_product(
        product_id=UUID(product_id),
        status=status if status != "all" else None,
        source_type=source_type if source_type != "all" else None,
        limit=limit,
    )
    # Convert to dicts for caching
    return [c.model_dump() for c in candidates]


def fetch_candidate_with_evidence(candidate_id: str) -> Optional[Dict]:
    """Fetch a single candidate with its evidence."""
    service = get_angle_candidate_service()
    candidate = service.get_candidate(UUID(candidate_id))
    if candidate:
        data = candidate.model_dump()
        # Fetch evidence separately if not populated
        if not candidate.evidence:
            evidence_list = service.get_evidence_for_candidate(UUID(candidate_id))
            data['evidence'] = [e.model_dump() for e in evidence_list]
        return data
    return None


@st.cache_data(ttl=60)
def fetch_recently_promoted(product_id: str, limit: int = 5) -> List[Dict]:
    """Fetch recently promoted candidates."""
    db = get_supabase_client()
    result = db.table("angle_candidates").select(
        "id, name, belief_statement, reviewed_at, promoted_angle_id"
    ).eq("product_id", product_id).eq(
        "status", "approved"
    ).not_.is_(
        "promoted_angle_id", "null"
    ).order("reviewed_at", desc=True).limit(limit).execute()
    return result.data or []


@st.cache_data(ttl=60)
def fetch_personas_for_product(product_id: str) -> List[Dict]:
    """Fetch personas linked to a product."""
    db = get_supabase_client()
    # Get product to find brand
    prod_result = db.table("products").select("brand_id").eq("id", product_id).execute()
    if not prod_result.data:
        return []

    brand_id = prod_result.data[0].get("brand_id")
    if not brand_id:
        return []

    result = db.table("personas_4d").select("id, name").eq("brand_id", brand_id).execute()
    return result.data or []


@st.cache_data(ttl=60)
def fetch_jtbds_for_persona_product(persona_id: str, product_id: str) -> List[Dict]:
    """Fetch JTBDs for a persona-product combination."""
    service = get_planning_service()
    jtbds = service.get_jtbd_for_persona_product(UUID(persona_id), UUID(product_id))
    return [{"id": str(j.id), "name": j.name, "progress_statement": j.progress_statement} for j in jtbds]


# ============================================
# UI COMPONENTS
# ============================================

def render_stats_section(product_id: str):
    """Render statistics overview."""
    service = get_angle_candidate_service()
    stats = service.get_candidate_stats(UUID(product_id))

    st.subheader("📊 Overview")

    col1, col2, col3, col4 = st.columns(4)

    with col1:
        st.metric("Total Candidates", stats.get("total", 0))

    with col2:
        by_status = stats.get("by_status", {})
        pending = by_status.get("candidate", 0)
        st.metric("Pending Review", pending)

    with col3:
        by_confidence = stats.get("by_confidence", {})
        high = by_confidence.get("HIGH", 0)
        st.metric("HIGH Confidence", high, help="5+ evidence items")

    with col4:
        approved = by_status.get("approved", 0)
        st.metric("Promoted", approved)

    # Source breakdown
    by_source = stats.get("by_source", {})
    if by_source:
        source_str = " | ".join([
            f"{SOURCE_ICONS.get(k, '📝')} {SOURCE_LABELS.get(k, k)}: {v}"
            for k, v in by_source.items()
        ])
        st.caption(f"By Source: {source_str}")


def render_filters_section():
    """Render filter controls."""
    col1, col2, col3, col4 = st.columns([2, 2, 2, 1])

    with col1:
        status_options = ["candidate", "approved", "rejected", "merged", "all"]
        st.session_state.ri_status_filter = st.selectbox(
            "Status",
            options=status_options,
            index=status_options.index(st.session_state.ri_status_filter),
            key="filter_status"
        )

    with col2:
        source_options = ["all"] + list(SOURCE_LABELS.keys())
        source_labels = ["All Sources"] + [SOURCE_LABELS[k] for k in SOURCE_LABELS.keys()]
        current_idx = 0
        if st.session_state.ri_source_filter in source_options:
            current_idx = source_options.index(st.session_state.ri_source_filter)

        selected_label = st.selectbox(
            "Source",
            options=source_labels,
            index=current_idx,
            key="filter_source"
        )
        # Convert label back to key
        if selected_label == "All Sources":
            st.session_state.ri_source_filter = "all"
        else:
            for k, v in SOURCE_LABELS.items():
                if v == selected_label:
                    st.session_state.ri_source_filter = k
                    break

    with col3:
        confidence_options = ["all", "HIGH", "MEDIUM", "LOW"]
        confidence_labels = ["All Confidence", "🔴 HIGH (5+)", "🟡 MEDIUM (2-4)", "🟢 LOW (1)"]
        conf_idx = confidence_options.index(st.session_state.ri_confidence_filter)

        selected_conf = st.selectbox(
            "Confidence",
            options=confidence_labels,
            index=conf_idx,
            key="filter_confidence"
        )
        # Convert back to value
        st.session_state.ri_confidence_filter = confidence_options[confidence_labels.index(selected_conf)]

    with col4:
        st.write("")  # Spacer
        if st.button("🔄 Refresh"):
            st.cache_data.clear()
            st.rerun()


def render_candidate_card(candidate: Dict, show_actions: bool = True):
    """Render a single candidate card."""
    candidate_id = candidate.get("id")
    name = candidate.get("name", "Unnamed")
    belief = candidate.get("belief_statement", "")
    freq = candidate.get("frequency_score", 1)
    confidence = candidate.get("confidence", "LOW")
    source_type = candidate.get("source_type", "unknown")
    candidate_type = candidate.get("candidate_type", "unknown")
    status = candidate.get("status", "candidate")
    created_at = candidate.get("created_at", "")

    # Confidence badge
    badge_emoji, badge_color = CONFIDENCE_BADGES.get(confidence, ("⚪", "gray"))

    # Format date
    try:
        if isinstance(created_at, str):
            dt = datetime.fromisoformat(created_at.replace("Z", "+00:00"))
        else:
            dt = created_at
        date_str = dt.strftime("%Y-%m-%d")
    except Exception:
        date_str = str(created_at)[:10] if created_at else ""

    # Card layout
    with st.container():
        col1, col2, col3 = st.columns([4, 2, 2])

        with col1:
            # Header with confidence badge
            st.markdown(f"### {badge_emoji} {name[:60]}{'...' if len(name) > 60 else ''}")

            # Belief statement
            st.markdown(f"*\"{belief[:200]}{'...' if len(belief) > 200 else ''}\"*")

            # Meta info
            source_icon = SOURCE_ICONS.get(source_type, "📝")
            source_label = SOURCE_LABELS.get(source_type, source_type)
            type_label = TYPE_LABELS.get(candidate_type, candidate_type)

            st.caption(
                f"{source_icon} {source_label} | {type_label} | "
                f"Evidence: {freq} | {date_str}"
            )

        with col2:
            # Confidence and status
            st.markdown(f"**Confidence:** :{badge_color}[{confidence}]")
            st.markdown(f"**Status:** {status}")

            # Tags if present
            tags = candidate.get("tags", [])
            if tags:
                tag_str = " ".join([f"`{t}`" for t in tags[:3]])
                st.markdown(f"Tags: {tag_str}")

        with col3:
            if show_actions and status == "candidate":
                # View Evidence button
                if st.button("👁️ Evidence", key=f"view_{candidate_id}"):
                    st.session_state.ri_selected_candidate_id = candidate_id
                    st.rerun()

                # Promote button
                if st.button("⬆️ Promote", key=f"promote_{candidate_id}"):
                    st.session_state.ri_promote_candidate_id = candidate_id
                    st.rerun()

                # Reject button with confirmation
                if st.session_state.ri_confirm_reject == candidate_id:
                    st.warning("Confirm reject?")
                    c1, c2 = st.columns(2)
                    with c1:
                        if st.button("Yes", key=f"yes_{candidate_id}"):
                            service = get_angle_candidate_service()
                            service.reject_candidate(UUID(candidate_id))
                            st.session_state.ri_confirm_reject = None
                            st.cache_data.clear()
                            st.rerun()
                    with c2:
                        if st.button("No", key=f"no_{candidate_id}"):
                            st.session_state.ri_confirm_reject = None
                            st.rerun()
                else:
                    if st.button("❌ Reject", key=f"reject_{candidate_id}"):
                        st.session_state.ri_confirm_reject = candidate_id
                        st.rerun()
            elif status == "approved":
                angle_id = candidate.get("promoted_angle_id")
                if angle_id:
                    st.success(f"✅ Promoted")
                    st.caption(f"Angle: {str(angle_id)[:8]}...")

        st.divider()


def render_evidence_viewer(candidate_id: str):
    """Render evidence detail view for a candidate."""
    candidate = fetch_candidate_with_evidence(candidate_id)

    if not candidate:
        st.error("Candidate not found")
        return

    # Back button
    if st.button("← Back to List"):
        st.session_state.ri_selected_candidate_id = None
        st.rerun()

    st.header(f"Evidence for: {candidate.get('name', 'Unknown')}")

    # Candidate summary
    col1, col2 = st.columns(2)
    with col1:
        st.markdown(f"**Belief Statement:**")
        st.info(candidate.get("belief_statement", ""))

        st.markdown(f"**Type:** {TYPE_LABELS.get(candidate.get('candidate_type'), candidate.get('candidate_type'))}")
        st.markdown(f"**Source:** {SOURCE_LABELS.get(candidate.get('source_type'), candidate.get('source_type'))}")

    with col2:
        st.metric("Frequency Score", candidate.get("frequency_score", 1))
        st.metric("Confidence", candidate.get("confidence", "LOW"))

    st.divider()

    # Evidence list
    evidence_list = candidate.get("evidence", [])
    st.subheader(f"📋 Evidence Items ({len(evidence_list)})")

    if not evidence_list:
        st.info("No evidence items found for this candidate.")
        return

    for i, evidence in enumerate(evidence_list, 1):
        with st.expander(
            f"#{i} - {evidence.get('evidence_type', 'unknown')} "
            f"from {SOURCE_LABELS.get(evidence.get('source_type'), evidence.get('source_type'))}",
            expanded=(i <= 3)
        ):
            st.markdown(f"**Evidence Text:**")
            st.markdown(f"> {evidence.get('evidence_text', '')}")

            col1, col2 = st.columns(2)
            with col1:
                if evidence.get("source_url"):
                    st.markdown(f"**Source URL:** [{evidence['source_url'][:50]}...]({evidence['source_url']})")
                if evidence.get("source_post_id"):
                    st.caption(f"Post ID: {evidence['source_post_id']}")
            with col2:
                if evidence.get("confidence_score"):
                    st.caption(f"LLM Confidence: {evidence['confidence_score']:.2f}")
                if evidence.get("engagement_score"):
                    st.caption(f"Engagement: {evidence['engagement_score']}")

            try:
                created = evidence.get("created_at", "")
                if isinstance(created, str):
                    dt = datetime.fromisoformat(created.replace("Z", "+00:00"))
                    st.caption(f"Added: {dt.strftime('%Y-%m-%d %H:%M')}")
            except Exception:
                pass


def render_promote_workflow(candidate_id: str, product_id: str):
    """Render the promote to angle workflow."""
    candidate = fetch_candidate_with_evidence(candidate_id)

    if not candidate:
        st.error("Candidate not found")
        return

    # Back button
    if st.button("← Cancel"):
        st.session_state.ri_promote_candidate_id = None
        st.rerun()

    st.header("⬆️ Promote to Angle")

    # Candidate preview
    st.markdown(f"**Candidate:** {candidate.get('name', 'Unknown')}")
    st.info(f"*\"{candidate.get('belief_statement', '')}\"*")

    st.divider()

    # Step 1: Select Persona
    st.subheader("Step 1: Select Persona")
    personas = fetch_personas_for_product(product_id)

    if not personas:
        st.warning("No personas found for this product's brand. Create a persona first.")
        return

    persona_options = {p["name"]: p["id"] for p in personas}
    selected_persona_name = st.selectbox(
        "Persona",
        options=list(persona_options.keys()),
        key="promote_persona"
    )
    selected_persona_id = persona_options[selected_persona_name]

    # Step 2: Select or Create JTBD
    st.subheader("Step 2: Select JTBD")
    jtbds = fetch_jtbds_for_persona_product(selected_persona_id, product_id)

    if not jtbds:
        st.warning(
            f"No JTBDs found for {selected_persona_name} + this product. "
            "Create a JTBD first in Ad Planning, or select a different persona."
        )
        return

    jtbd_options = {j["name"]: j["id"] for j in jtbds}
    selected_jtbd_name = st.selectbox(
        "Job to Be Done",
        options=list(jtbd_options.keys()),
        key="promote_jtbd"
    )
    selected_jtbd_id = jtbd_options[selected_jtbd_name]

    # Show JTBD progress statement
    selected_jtbd = next((j for j in jtbds if j["id"] == selected_jtbd_id), None)
    if selected_jtbd and selected_jtbd.get("progress_statement"):
        st.caption(f"*{selected_jtbd['progress_statement']}*")

    st.divider()

    # Promote button
    st.markdown("**Ready to create angle?**")
    st.caption(
        f"This will create a new angle in `belief_angles` linked to "
        f"the JTBD \"{selected_jtbd_name}\" and mark this candidate as approved."
    )

    if st.button("✅ Create Angle", type="primary"):
        service = get_angle_candidate_service()
        try:
            angle = service.promote_to_angle(
                candidate_id=UUID(candidate_id),
                jtbd_framed_id=UUID(selected_jtbd_id)
            )
            if angle:
                st.success(f"Angle created! ID: {angle.id}")
                st.session_state.ri_promote_candidate_id = None
                st.cache_data.clear()
                st.balloons()
                st.rerun()
            else:
                st.error("Failed to create angle. Check logs for details.")
        except Exception as e:
            st.error(f"Error promoting candidate: {e}")


def render_recently_promoted(product_id: str):
    """Render recently promoted candidates section."""
    promoted = fetch_recently_promoted(product_id)

    if not promoted:
        return

    st.subheader("✅ Recently Promoted")

    for item in promoted:
        name = item.get("name", "Unknown")[:40]
        reviewed_at = item.get("reviewed_at", "")

        try:
            if reviewed_at:
                dt = datetime.fromisoformat(reviewed_at.replace("Z", "+00:00"))
                date_str = dt.strftime("%Y-%m-%d")
            else:
                date_str = ""
        except Exception:
            date_str = ""

        angle_id = item.get("promoted_angle_id", "")
        angle_short = str(angle_id)[:8] if angle_id else ""

        st.caption(f"• \"{name}...\" → Angle #{angle_short} ({date_str})")


def render_candidate_list(candidates: List[Dict]):
    """Render the main candidate list."""
    if not candidates:
        st.info(
            "No candidates found with current filters. "
            "Try changing filters or extract candidates from research pages."
        )
        return

    # Group by confidence
    high = [c for c in candidates if c.get("confidence") == "HIGH"]
    medium = [c for c in candidates if c.get("confidence") == "MEDIUM"]
    low = [c for c in candidates if c.get("confidence") == "LOW"]

    # Render HIGH confidence first
    if high:
        st.subheader(f"🔴 HIGH Confidence ({len(high)})")
        st.caption("Recommended for promotion - 5+ evidence items")
        for c in high:
            render_candidate_card(c)

    if medium:
        st.subheader(f"🟡 MEDIUM Confidence ({len(medium)})")
        st.caption("Growing evidence - 2-4 evidence items")
        for c in medium:
            render_candidate_card(c)

    if low:
        st.subheader(f"🟢 LOW Confidence ({len(low)})")
        st.caption("New candidates - 1 evidence item")
        for c in low:
            render_candidate_card(c)


# ============================================
# MAIN PAGE
# ============================================

st.title("💡 Research Insights")
st.write("View and manage angle candidates from all research sources.")

# Brand/Product selector
from viraltracker.ui.utils import render_brand_selector

brand_id, product_id = render_brand_selector(
    key="ri_brand_selector",
    include_product=True,
    product_label="Select Product",
    product_key="ri_product_selector"
)

if not product_id:
    st.warning("Please select a product to view research insights.")
    st.stop()

st.divider()

# Check if viewing evidence for specific candidate
if st.session_state.ri_selected_candidate_id:
    render_evidence_viewer(st.session_state.ri_selected_candidate_id)

# Check if in promote workflow
elif st.session_state.ri_promote_candidate_id:
    render_promote_workflow(st.session_state.ri_promote_candidate_id, product_id)

# Main view
else:
    # Stats overview
    render_stats_section(product_id)

    st.divider()

    # Recently promoted (sidebar-style)
    col_main, col_side = st.columns([3, 1])

    with col_side:
        render_recently_promoted(product_id)

    with col_main:
        # Filters
        render_filters_section()

        st.divider()

        # Fetch candidates
        candidates = fetch_candidates(
            product_id=product_id,
            status=st.session_state.ri_status_filter,
            source_type=st.session_state.ri_source_filter
        )

        # Apply confidence filter (post-fetch since not in service)
        if st.session_state.ri_confidence_filter != "all":
            candidates = [
                c for c in candidates
                if c.get("confidence") == st.session_state.ri_confidence_filter
            ]

        # Render list
        st.subheader(f"📋 Candidates ({len(candidates)})")
        render_candidate_list(candidates)
