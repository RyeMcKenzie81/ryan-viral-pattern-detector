"""
Template Evaluation UI

Evaluate templates for Phase 1-2 belief testing eligibility:
- View all templates with evaluation status
- Run AI evaluation (D1-D6 rubric scoring)
- Filter by eligibility
- Batch evaluation for all templates
"""

import streamlit as st
from typing import Optional, List, Dict, Any
from uuid import UUID
from datetime import datetime

# Page config (must be first)
st.set_page_config(
    page_title="Template Evaluation",
    page_icon="🔍",
    layout="wide"
)

# Authentication
from viraltracker.ui.auth import require_auth
require_auth()

# Initialize session state
if 'eval_filter' not in st.session_state:
    st.session_state.eval_filter = "all"  # all, eligible, not_eligible, not_evaluated
if 'eval_source' not in st.session_state:
    st.session_state.eval_source = "all"  # all, manual, scraped
if 'eval_phase' not in st.session_state:
    st.session_state.eval_phase = 1
if 'batch_running' not in st.session_state:
    st.session_state.batch_running = False


def get_evaluation_service():
    """Get TemplateEvaluationService instance."""
    from viraltracker.services.template_evaluation_service import TemplateEvaluationService
    return TemplateEvaluationService()


def get_supabase_client():
    """Get Supabase client."""
    from viraltracker.core.database import get_supabase_client
    return get_supabase_client()


# ============================================================================
# Data Loading
# ============================================================================

@st.cache_data(ttl=30)
def get_evaluation_stats(phase_id: int) -> Dict[str, int]:
    """Get evaluation statistics."""
    service = get_evaluation_service()
    templates = service.get_all_templates_with_eligibility(phase_id=phase_id)

    stats = {
        "total": len(templates),
        "evaluated": sum(1 for t in templates if t.get("evaluated")),
        "eligible": sum(1 for t in templates if t.get("eligible")),
        "not_eligible": sum(1 for t in templates if t.get("evaluated") and not t.get("eligible")),
        "manual": sum(1 for t in templates if t.get("source") == "manual"),
        "scraped": sum(1 for t in templates if t.get("source") == "scraped"),
    }
    return stats


def get_templates_for_display(
    phase_id: int,
    filter_status: str = "all",
    filter_source: str = "all"
) -> List[Dict]:
    """Get templates filtered by status and source."""
    service = get_evaluation_service()
    templates = service.get_all_templates_with_eligibility(phase_id=phase_id)

    # Apply filters
    filtered = []
    for t in templates:
        # Source filter
        if filter_source != "all" and t.get("source") != filter_source:
            continue

        # Status filter
        if filter_status == "eligible" and not t.get("eligible"):
            continue
        if filter_status == "not_eligible" and (not t.get("evaluated") or t.get("eligible")):
            continue
        if filter_status == "not_evaluated" and t.get("evaluated"):
            continue

        filtered.append(t)

    # Sort: not evaluated first, then by score
    filtered.sort(key=lambda x: (x.get("evaluated", False), -(x.get("evaluation_score") or 0)))

    return filtered


# ============================================================================
# Actions
# ============================================================================

def evaluate_single_template(template_id: str, source: str, phase_id: int) -> bool:
    """Evaluate a single template."""
    service = get_evaluation_service()
    try:
        template_source = "ad_brief_templates" if source == "manual" else "scraped_templates"
        result = service.evaluate_template_for_phase(
            UUID(template_id),
            template_source,
            phase_id
        )
        if result:
            st.cache_data.clear()
            return True
        return False
    except Exception as e:
        st.error(f"Evaluation failed: {e}")
        return False


def batch_evaluate_templates(phase_id: int, source: Optional[str] = None) -> Dict:
    """Run batch evaluation."""
    service = get_evaluation_service()
    try:
        template_source = None
        if source == "manual":
            template_source = "ad_brief_templates"
        elif source == "scraped":
            template_source = "scraped_templates"

        result = service.batch_evaluate_templates(
            phase_id=phase_id,
            template_source=template_source
        )
        st.cache_data.clear()
        return result
    except Exception as e:
        return {"error": str(e), "evaluated": 0, "eligible": 0, "failed": 0}


# ============================================================================
# UI Components
# ============================================================================

def render_stats():
    """Render evaluation statistics."""
    stats = get_evaluation_stats(st.session_state.eval_phase)

    col1, col2, col3, col4, col5 = st.columns(5)
    col1.metric("Total", stats.get("total", 0))
    col2.metric("Evaluated", stats.get("evaluated", 0))
    col3.metric("Eligible", stats.get("eligible", 0),
                help="Phase 1-2 eligible (D6 pass, score >= 12, D2 >= 2)")
    col4.metric("Manual", stats.get("manual", 0))
    col5.metric("Scraped", stats.get("scraped", 0))


def render_filters():
    """Render filter controls."""
    col1, col2, col3 = st.columns(3)

    with col1:
        phase = st.selectbox(
            "Phase",
            options=[1, 2, 3, 4, 5, 6],
            index=st.session_state.eval_phase - 1,
            key="phase_select",
            help="Evaluate for this phase's eligibility"
        )
        if phase != st.session_state.eval_phase:
            st.session_state.eval_phase = phase
            st.rerun()

    with col2:
        status_filter = st.selectbox(
            "Status",
            options=["all", "eligible", "not_eligible", "not_evaluated"],
            format_func=lambda x: {
                "all": "All Templates",
                "eligible": "Phase 1-2 Eligible",
                "not_eligible": "Not Eligible",
                "not_evaluated": "Not Evaluated Yet"
            }.get(x, x),
            key="status_filter"
        )
        if status_filter != st.session_state.eval_filter:
            st.session_state.eval_filter = status_filter
            st.rerun()

    with col3:
        source_filter = st.selectbox(
            "Source",
            options=["all", "manual", "scraped"],
            format_func=lambda x: {
                "all": "All Sources",
                "manual": "Manual Templates",
                "scraped": "Scraped Templates"
            }.get(x, x),
            key="source_filter"
        )
        if source_filter != st.session_state.eval_source:
            st.session_state.eval_source = source_filter
            st.rerun()


def render_batch_actions():
    """Render batch action buttons."""
    col1, col2, col3 = st.columns([2, 1, 1])

    with col1:
        st.caption("Batch evaluation uses Claude Opus 4.5 to score all templates.")

    with col2:
        if st.button(
            "Evaluate Not Evaluated",
            type="secondary",
            disabled=st.session_state.batch_running,
            help="Only evaluate templates without scores"
        ):
            st.session_state.batch_running = True
            st.rerun()

    with col3:
        if st.button(
            "Evaluate All Templates",
            type="primary",
            disabled=st.session_state.batch_running,
            help="Re-evaluate all templates"
        ):
            st.session_state.batch_running = True
            st.rerun()


def render_batch_progress():
    """Run batch evaluation with progress display."""
    with st.spinner("Running batch evaluation with Claude Opus 4.5... This may take a few minutes."):
        result = batch_evaluate_templates(
            phase_id=st.session_state.eval_phase,
            source=None if st.session_state.eval_source == "all" else st.session_state.eval_source
        )

    st.session_state.batch_running = False

    if "error" in result:
        st.error(f"Batch evaluation failed: {result['error']}")
    else:
        st.success(
            f"Evaluated {result.get('evaluated', 0)} templates. "
            f"{result.get('eligible', 0)} eligible, {result.get('failed', 0)} failed."
        )

    st.rerun()


def render_score_badge(score: Optional[float], eligible: bool, evaluated: bool) -> str:
    """Generate HTML for score badge."""
    if not evaluated:
        return "⚪ Not Evaluated"

    if eligible:
        return f"✅ **{score:.0f}/15** (Eligible)"
    else:
        return f"❌ **{score:.0f}/15** (Not Eligible)"


def render_dimension_breakdown(template: Dict):
    """Render D1-D6 scores in an expander."""
    phase_tags = template.get("phase_tags", {}) or {}

    if not phase_tags:
        st.caption("No evaluation details available")
        return

    cols = st.columns(6)
    dimensions = [
        ("D1", "Belief Clarity", phase_tags.get("d1_belief_clarity", "?")),
        ("D2", "Neutrality", phase_tags.get("d2_neutrality", "?")),
        ("D3", "Reusability", phase_tags.get("d3_reusability", "?")),
        ("D4", "Problem-Aware", phase_tags.get("d4_problem_aware_entry", "?")),
        ("D5", "Slot Avail.", phase_tags.get("d5_slot_availability", "?")),
        ("D6", "Compliance", "Pass" if phase_tags.get("d6_compliance_pass") else "Fail"),
    ]

    for i, (code, name, score) in enumerate(dimensions):
        with cols[i]:
            if code == "D6":
                color = "green" if score == "Pass" else "red"
                st.markdown(f"**{code}**: :{color}[{score}]")
            else:
                score_int = int(score) if score != "?" else 0
                color = "green" if score_int >= 2 else "orange" if score_int == 1 else "red"
                st.markdown(f"**{code}**: :{color}[{score}/3]")
            st.caption(name)


def render_template_card(template: Dict, index: int):
    """Render a single template card."""
    template_id = template.get("id")
    source = template.get("source", "unknown")
    name = template.get("name", "Unnamed")
    score = template.get("evaluation_score")
    eligible = template.get("eligible", False)
    evaluated = template.get("evaluated", False)
    notes = template.get("evaluation_notes", "")

    with st.container():
        col1, col2, col3 = st.columns([3, 1, 1])

        with col1:
            # Template name and source badge
            source_badge = "📋" if source == "manual" else "🔗"
            st.markdown(f"### {source_badge} {name}")

            # Description/instructions preview
            desc = template.get("description") or template.get("instructions") or ""
            if desc:
                st.caption(desc[:150] + ("..." if len(desc) > 150 else ""))

        with col2:
            st.markdown(render_score_badge(score, eligible, evaluated))
            if template.get("evaluated_at"):
                evaluated_at = template.get("evaluated_at")
                if isinstance(evaluated_at, str):
                    st.caption(f"Evaluated: {evaluated_at[:10]}")

        with col3:
            if st.button(
                "Evaluate" if not evaluated else "Re-evaluate",
                key=f"eval_{index}",
                type="primary" if not evaluated else "secondary"
            ):
                with st.spinner("Evaluating..."):
                    if evaluate_single_template(template_id, source, st.session_state.eval_phase):
                        st.success("Evaluation complete!")
                        st.rerun()
                    else:
                        st.error("Evaluation failed")

        # Expandable details
        if evaluated:
            with st.expander("View Scores & Notes"):
                render_dimension_breakdown(template)
                if notes:
                    st.markdown("**Notes:**")
                    st.info(notes)

        st.divider()


def render_template_list():
    """Render the filterable template list."""
    templates = get_templates_for_display(
        phase_id=st.session_state.eval_phase,
        filter_status=st.session_state.eval_filter,
        filter_source=st.session_state.eval_source
    )

    if not templates:
        st.info("No templates match the current filters.")
        return

    st.caption(f"Showing {len(templates)} templates")

    for i, template in enumerate(templates):
        render_template_card(template, i)


def render_rubric_reference():
    """Render the evaluation rubric reference."""
    st.markdown("""
    ### D1-D6 Evaluation Rubric

    | Dimension | Description | Score |
    |-----------|-------------|-------|
    | **D1 - Belief Clarity** | Can template clearly express a single belief? | 0-3 |
    | **D2 - Neutrality** | Free of sales bias, offers, urgency? | 0-3 |
    | **D3 - Reusability** | Works across different angles? | 0-3 |
    | **D4 - Problem-Aware Entry** | Supports problem-aware audiences? | 0-3 |
    | **D5 - Slot Availability** | Has clear text slots? | 0-3 |
    | **D6 - Compliance** | No before/after, medical claims, guarantees? | Pass/Fail |

    ### Phase 1-2 Eligibility Criteria

    A template is **eligible** for Phase 1-2 belief testing if:
    - D6 Compliance = **Pass**
    - Total Score (D1-D5) >= **12 out of 15**
    - D2 Neutrality >= **2 out of 3**

    *Templates that don't meet these criteria can still be used in later phases.*
    """)


# ============================================================================
# Main Page
# ============================================================================

st.title("🔍 Template Evaluation")
st.caption("Evaluate templates for Phase 1-2 belief testing eligibility using AI-powered rubric scoring")

# Check if batch is running
if st.session_state.batch_running:
    render_batch_progress()
else:
    # Stats
    render_stats()
    st.divider()

    # Tabs
    tab1, tab2 = st.tabs(["Templates", "Rubric Reference"])

    with tab1:
        # Filters
        render_filters()
        st.divider()

        # Batch actions
        render_batch_actions()
        st.divider()

        # Template list
        render_template_list()

    with tab2:
        render_rubric_reference()
