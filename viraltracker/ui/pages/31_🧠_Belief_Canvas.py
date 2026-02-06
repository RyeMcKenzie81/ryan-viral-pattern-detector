"""
Belief-First Reverse Engineer - Extract belief structure from messaging.

This page provides:
1. Input messages (hooks, claims, ad copy) to reverse-engineer
2. Choose draft mode (fast) or research mode (with Reddit validation)
3. Pipeline execution with progress tracking
4. Canvas output with evidence status tracking
5. Risk flag review and gaps analysis
6. Historical run management
"""

import streamlit as st
import asyncio
from datetime import datetime
from uuid import UUID
from typing import Optional, List, Dict, Any

# Page config (must be first)
st.set_page_config(
    page_title="Belief Canvas",
    page_icon="🧠",
    layout="wide"
)

# Auth
from viraltracker.ui.auth import require_auth
require_auth()
from viraltracker.ui.utils import require_feature
require_feature("belief_canvas", "Belief Canvas")

# ============================================
# SESSION STATE
# ============================================

def init_session_state():
    """Initialize all session state variables."""
    defaults = {
        "belief_messages": "",
        "belief_draft_mode": True,
        "belief_research_mode": False,
        "belief_format_hint": "",
        "belief_persona_hint": "",
        "belief_subreddits": "",
        "belief_search_terms": "",
        "belief_running": False,
        "belief_results": None,
        "belief_selected_run": None,
        "belief_show_trace": False,
    }
    for key, val in defaults.items():
        if key not in st.session_state:
            st.session_state[key] = val

init_session_state()

# ============================================
# SERVICES
# ============================================

def get_supabase():
    """Get Supabase client."""
    from viraltracker.core.database import get_supabase_client
    return get_supabase_client()

def get_brands():
    """Fetch brands filtered by current organization."""
    from viraltracker.ui.utils import get_brands as get_org_brands
    return get_org_brands()

def get_products_for_brand(brand_id: str):
    """Fetch products for a brand."""
    db = get_supabase()
    result = db.table("products").select(
        "id, name, category"
    ).eq("brand_id", brand_id).order("name").execute()
    return result.data or []

def get_recent_runs(limit: int = 10, product_id: Optional[str] = None):
    """Fetch recent pipeline runs."""
    db = get_supabase()
    query = db.table("belief_reverse_engineer_runs").select(
        "id, messages, draft_mode, research_mode, status, "
        "completeness_score, risk_flags, created_at, completed_at, "
        "products(name), brands(name)"
    ).order("created_at", desc=True).limit(limit)

    if product_id:
        query = query.eq("product_id", product_id)

    result = query.execute()
    return result.data or []

def get_run_details(run_id: str) -> Optional[Dict]:
    """Fetch full run details."""
    db = get_supabase()
    result = db.table("belief_reverse_engineer_runs").select(
        "*"
    ).eq("id", run_id).execute()
    return result.data[0] if result.data else None

def create_run(
    product_id: str,
    brand_id: str,
    messages: List[str],
    draft_mode: bool,
    research_mode: bool,
    format_hint: Optional[str],
    persona_hint: Optional[str],
    subreddits: List[str],
    search_terms: List[str],
) -> str:
    """Create a new pipeline run record."""
    import json
    db = get_supabase()
    result = db.table("belief_reverse_engineer_runs").insert({
        "product_id": product_id,
        "brand_id": brand_id,
        "messages": json.dumps(messages),
        "draft_mode": draft_mode,
        "research_mode": research_mode,
        "format_hint": format_hint,
        "persona_hint": persona_hint,
        "subreddits": subreddits if subreddits else None,
        "search_terms": search_terms if search_terms else None,
        "status": "pending",
        "current_step": "pending",
    }).execute()
    return result.data[0]["id"]

def update_run(run_id: str, updates: Dict):
    """Update a run record."""
    db = get_supabase()
    db.table("belief_reverse_engineer_runs").update(updates).eq("id", run_id).execute()

# ============================================
# PIPELINE EXECUTION
# ============================================

async def run_pipeline(
    product_id: str,
    messages: List[str],
    draft_mode: bool,
    research_mode: bool,
    format_hint: Optional[str],
    persona_hint: Optional[str],
    subreddits: List[str],
    search_terms: List[str],
    run_id: str,
    scrape_config: Optional[Dict] = None,
    progress_callback=None,
):
    """Execute the belief reverse engineer pipeline."""
    from viraltracker.pipelines.belief_reverse_engineer import run_belief_reverse_engineer

    try:
        # Update status to running
        update_run(run_id, {
            "status": "running",
            "started_at": datetime.utcnow().isoformat(),
        })

        if progress_callback:
            progress_callback("Starting pipeline...")

        # Run the pipeline
        result = await run_belief_reverse_engineer(
            product_id=UUID(product_id),
            messages=messages,
            draft_mode=draft_mode,
            research_mode=research_mode,
            format_hint=format_hint,
            persona_hint=persona_hint,
            subreddits=subreddits,
            search_terms=search_terms,
            scrape_config=scrape_config,
        )

        # Extract result data
        import json

        updates = {
            "status": "complete",
            "completed_at": datetime.utcnow().isoformat(),
            "canvas": json.dumps(result.get("canvas", {})),
            "research_canvas": json.dumps(result.get("canvas", {}).get("research_canvas", {})),
            "belief_canvas": json.dumps(result.get("canvas", {}).get("belief_canvas", {})),
            "gaps": json.dumps(result.get("gaps", {})),
            "risk_flags": json.dumps([rf.model_dump() if hasattr(rf, 'model_dump') else rf for rf in result.get("risk_flags", [])]),
            "trace_map": json.dumps([t.model_dump() if hasattr(t, 'model_dump') else t for t in result.get("trace_map", [])]),
            "rendered_markdown": result.get("rendered_markdown", ""),
            "completeness_score": result.get("completeness_score"),
        }

        if result.get("reddit_bundle"):
            updates["reddit_bundle"] = json.dumps(
                result["reddit_bundle"].model_dump() if hasattr(result["reddit_bundle"], 'model_dump')
                else result["reddit_bundle"]
            )
            updates["posts_analyzed"] = result["reddit_bundle"].get("posts_analyzed_count", 0)
            updates["comments_analyzed"] = result["reddit_bundle"].get("comments_analyzed_count", 0)

        update_run(run_id, updates)

        if progress_callback:
            progress_callback("Pipeline complete!")

        return result

    except Exception as e:
        update_run(run_id, {
            "status": "failed",
            "error_message": str(e),
            "completed_at": datetime.utcnow().isoformat(),
        })
        raise

# ============================================
# UI COMPONENTS
# ============================================

def render_input_section(brand_id: str, product_id: str):
    """Render the input configuration section."""
    st.subheader("📝 Input Messages")

    st.info(
        "Enter the marketing messages you want to reverse-engineer into a Belief-First Canvas. "
        "These can be hooks, claims, ad copy, or any messaging you want to analyze."
    )

    messages = st.text_area(
        "Messages (one per line)",
        value=st.session_state.belief_messages,
        height=150,
        help="Enter each message on a new line",
        key="belief_messages_input",
    )
    st.session_state.belief_messages = messages

    col1, col2 = st.columns(2)

    with col1:
        format_hint = st.selectbox(
            "Format Hint (optional)",
            options=["", "ad", "landing_page", "video", "email", "social"],
            help="What format is this messaging for?",
        )
        st.session_state.belief_format_hint = format_hint

    with col2:
        persona_hint = st.text_input(
            "Persona Hint (optional)",
            value=st.session_state.belief_persona_hint,
            help="E.g., 'GLP-1 user', 'busy parent', 'fitness enthusiast'",
        )
        st.session_state.belief_persona_hint = persona_hint

    return messages.strip().split("\n") if messages.strip() else []

def render_mode_section():
    """Render the mode selection section."""
    st.subheader("⚙️ Mode Selection")

    col1, col2 = st.columns(2)

    with col1:
        draft_mode = st.checkbox(
            "Draft Mode (Fast)",
            value=st.session_state.belief_draft_mode,
            help="Fill canvas from message inference + product DB. Creates 'research needed' gaps.",
        )
        st.session_state.belief_draft_mode = draft_mode

    with col2:
        research_mode = st.checkbox(
            "Research Mode (Reddit)",
            value=st.session_state.belief_research_mode,
            help="Run Reddit research to validate and fill canvas with observed evidence.",
        )
        st.session_state.belief_research_mode = research_mode

    if research_mode:
        st.divider()
        st.markdown("**Reddit Research Configuration**")

        col1, col2 = st.columns(2)

        with col1:
            subreddits = st.text_input(
                "Subreddits (comma-separated)",
                value=st.session_state.belief_subreddits,
                help="E.g., nutrition, loseit, fitness, Ozempic",
            )
            st.session_state.belief_subreddits = subreddits

        with col2:
            search_terms = st.text_input(
                "Search Terms (comma-separated)",
                value=st.session_state.belief_search_terms,
                help="E.g., protein shake, bloating, sugar crash",
            )
            st.session_state.belief_search_terms = search_terms

        # Cost guardrails
        st.markdown("**⚠️ Cost Guardrails** (Apify charges per API call)")

        # Calculate estimated calls
        sub_count = len([s.strip() for s in subreddits.split(",") if s.strip()]) if subreddits else 0
        term_count = len([s.strip() for s in search_terms.split(",") if s.strip()]) if search_terms else 0
        estimated_calls = sub_count * term_count

        col1, col2, col3 = st.columns(3)

        with col1:
            max_api_calls = st.number_input(
                "Max API Calls",
                min_value=1,
                max_value=50,
                value=st.session_state.get("belief_max_api_calls", 10),
                help="Hard limit on number of Reddit scrape calls",
            )
            st.session_state.belief_max_api_calls = max_api_calls

        with col2:
            max_total_posts = st.number_input(
                "Max Total Posts",
                min_value=10,
                max_value=500,
                value=st.session_state.get("belief_max_total_posts", 100),
                help="Stop after this many posts total",
            )
            st.session_state.belief_max_total_posts = max_total_posts

        with col3:
            posts_per_query = st.number_input(
                "Posts per Query",
                min_value=5,
                max_value=50,
                value=st.session_state.get("belief_posts_per_query", 25),
                help="Max posts per subreddit/term combo",
            )
            st.session_state.belief_posts_per_query = posts_per_query

        # Quality filters (like Reddit Research tool)
        with st.expander("🎯 Quality Filters (LLM-powered)", expanded=False):
            st.caption("These filters use Claude to score posts for relevance - improves quality but adds LLM cost")

            col1, col2 = st.columns(2)

            with col1:
                min_upvotes = st.number_input(
                    "Min Upvotes",
                    min_value=0,
                    max_value=100,
                    value=st.session_state.get("belief_min_upvotes", 10),
                    help="Minimum upvotes for engagement filter",
                )
                st.session_state.belief_min_upvotes = min_upvotes

                min_comments = st.number_input(
                    "Min Comments",
                    min_value=0,
                    max_value=50,
                    value=st.session_state.get("belief_min_comments", 3),
                    help="Minimum comments for engagement filter",
                )
                st.session_state.belief_min_comments = min_comments

            with col2:
                relevance_threshold = st.slider(
                    "Relevance Threshold",
                    min_value=0.0,
                    max_value=1.0,
                    value=st.session_state.get("belief_relevance_threshold", 0.5),
                    step=0.1,
                    help="LLM scores posts for relevance to product/topic (0=disabled)",
                )
                st.session_state.belief_relevance_threshold = relevance_threshold

                top_percentile = st.slider(
                    "Top Percentile",
                    min_value=0.1,
                    max_value=1.0,
                    value=st.session_state.get("belief_top_percentile", 0.30),
                    step=0.1,
                    format="%.0f%%",
                    help="Keep only top X% of posts after scoring",
                )
                st.session_state.belief_top_percentile = top_percentile

        # Show estimate
        if estimated_calls > 0:
            actual_calls = min(estimated_calls, max_api_calls)
            st.info(
                f"📊 **Estimate:** {sub_count} subreddits × {term_count} terms = "
                f"{estimated_calls} potential calls → capped at **{actual_calls}** calls "
                f"(up to {actual_calls * posts_per_query} posts before filtering)"
            )
        else:
            st.caption("Enter subreddits and search terms to see cost estimate")

    return draft_mode, research_mode

def render_results_section(result: Dict):
    """Render the pipeline results."""
    st.subheader("📊 Results")

    # Check for error status
    status = result.get("status", "unknown")
    error_message = result.get("error_message") or result.get("error")

    if status == "failed" or status == "error":
        st.error(f"❌ Pipeline failed: {error_message or 'Unknown error'}")
        current_step = result.get("current_step", "unknown")
        st.caption(f"Failed at step: {current_step}")
        return

    if status == "pending":
        st.warning("⏳ This run is still pending or was never started.")
        return

    if status == "running":
        st.info("🔄 This run is still in progress...")
        return

    # Tabs for different views
    tab1, tab2, tab3, tab4 = st.tabs([
        "📄 Canvas", "⚠️ Risk Flags", "🔍 Gaps", "🔗 Trace Map"
    ])

    with tab1:
        render_canvas_view(result)

    with tab2:
        render_risk_flags(result.get("risk_flags", []))

    with tab3:
        render_gaps(result.get("gaps", {}))

    with tab4:
        render_trace_map(result.get("trace_map", []))

def safe_json_parse(value, default=None):
    """Safely parse a value that might be JSON string or already a dict/list."""
    import json
    if default is None:
        default = {}
    if value is None:
        return default
    if isinstance(value, (dict, list)):
        return value
    if isinstance(value, str):
        try:
            return json.loads(value)
        except (json.JSONDecodeError, TypeError):
            return default
    return default

def render_canvas_view(result: Dict):
    """Render the canvas output."""
    # Show rendered markdown if available
    rendered_markdown = result.get("rendered_markdown", "")

    if rendered_markdown:
        with st.expander("📝 Rendered Canvas (Markdown)", expanded=True):
            st.markdown(rendered_markdown)

    # Show JSON structure - parse if string
    canvas = safe_json_parse(result.get("canvas", {}))

    # Also check for separate research_canvas/belief_canvas fields (from DB)
    if not canvas or (not canvas.get("research_canvas") and not canvas.get("belief_canvas")):
        research_canvas = safe_json_parse(result.get("research_canvas", {}))
        belief_canvas = safe_json_parse(result.get("belief_canvas", {}))
        if research_canvas or belief_canvas:
            canvas = {"research_canvas": research_canvas, "belief_canvas": belief_canvas}

    if canvas:
        col1, col2 = st.columns(2)

        with col1:
            with st.expander("🔬 Research Canvas (Sections 1-9)", expanded=False):
                st.json(safe_json_parse(canvas.get("research_canvas", {})))

        with col2:
            with st.expander("🎯 Belief Canvas (Sections 10-15)", expanded=False):
                st.json(safe_json_parse(canvas.get("belief_canvas", {})))

def render_risk_flags(risk_flags):
    """Render risk flags with severity indicators."""
    # Parse if JSON string
    risk_flags = safe_json_parse(risk_flags, default=[])

    if not risk_flags:
        st.success("No risk flags detected!")
        return

    for rf in risk_flags:
        if isinstance(rf, dict):
            severity = rf.get("severity", "low")
            flag_type = rf.get("type", "unknown")
            reason = rf.get("reason", "")
            suggested_fix = rf.get("suggested_fix", "")
            affected = rf.get("affected_fields", [])
        else:
            severity = getattr(rf, "severity", "low")
            flag_type = getattr(rf, "type", "unknown")
            reason = getattr(rf, "reason", "")
            suggested_fix = getattr(rf, "suggested_fix", "")
            affected = getattr(rf, "affected_fields", [])

        # Color by severity
        if severity == "high":
            st.error(f"🚨 **{flag_type}**: {reason}")
        elif severity == "medium":
            st.warning(f"⚠️ **{flag_type}**: {reason}")
        else:
            st.info(f"ℹ️ **{flag_type}**: {reason}")

        if suggested_fix:
            st.markdown(f"  **Suggested fix:** {suggested_fix}")
        if affected:
            st.markdown(f"  **Affected fields:** {', '.join(affected)}")

def render_gaps(gaps):
    """Render gaps analysis."""
    # Parse if JSON string
    gaps = safe_json_parse(gaps, default={})

    research_needed = safe_json_parse(gaps.get("research_needed", []), default=[])
    proof_needed = safe_json_parse(gaps.get("proof_needed", []), default=[])

    col1, col2 = st.columns(2)

    with col1:
        st.markdown("**🔬 Research Needed**")
        if research_needed:
            for gap in research_needed:
                if isinstance(gap, dict):
                    st.markdown(f"- {gap.get('field', '')}: {gap.get('reason', '')}")
                else:
                    st.markdown(f"- {gap}")
        else:
            st.success("No research gaps!")

    with col2:
        st.markdown("**📋 Proof Needed**")
        if proof_needed:
            for gap in proof_needed:
                if isinstance(gap, dict):
                    st.markdown(f"- {gap.get('field', '')}: {gap.get('reason', '')}")
                else:
                    st.markdown(f"- {gap}")
        else:
            st.success("No proof gaps!")

def render_trace_map(trace_map):
    """Render the trace map showing field sources."""
    # Parse if JSON string
    trace_map = safe_json_parse(trace_map, default=[])

    if not trace_map:
        st.info("No trace map available.")
        return

    # Group by evidence status
    observed = []
    inferred = []
    hypothesis = []

    for item in trace_map:
        if isinstance(item, dict):
            status = item.get("evidence_status", "")
            field = item.get("field_path", "")
            source = item.get("source", "")
            detail = item.get("source_detail", "")
        else:
            status = getattr(item, "evidence_status", "")
            field = getattr(item, "field_path", "")
            source = getattr(item, "source", "")
            detail = getattr(item, "source_detail", "")

        entry = f"**{field}** ← {source}: {detail}"

        if status == "observed":
            observed.append(entry)
        elif status == "inferred":
            inferred.append(entry)
        else:
            hypothesis.append(entry)

    col1, col2, col3 = st.columns(3)

    with col1:
        st.markdown("**✅ Observed**")
        for item in observed[:10]:
            st.markdown(f"- {item}")
        if len(observed) > 10:
            st.caption(f"...and {len(observed) - 10} more")

    with col2:
        st.markdown("**🔶 Inferred**")
        for item in inferred[:10]:
            st.markdown(f"- {item}")
        if len(inferred) > 10:
            st.caption(f"...and {len(inferred) - 10} more")

    with col3:
        st.markdown("**❓ Hypothesis**")
        for item in hypothesis[:10]:
            st.markdown(f"- {item}")
        if len(hypothesis) > 10:
            st.caption(f"...and {len(hypothesis) - 10} more")

def render_run_history(product_id: Optional[str]):
    """Render historical runs."""
    st.subheader("📜 Run History")

    runs = get_recent_runs(limit=10, product_id=product_id)

    if not runs:
        st.info("No previous runs found.")
        return

    for run in runs:
        import json

        status = run.get("status", "unknown")
        created = run.get("created_at", "")[:16].replace("T", " ")
        mode = "Draft" if run.get("draft_mode") else "Research" if run.get("research_mode") else "Standard"

        messages = run.get("messages", "[]")
        if isinstance(messages, str):
            try:
                messages = json.loads(messages)
            except:
                messages = []

        message_preview = messages[0][:50] + "..." if messages else "No messages"

        # Status indicator
        if status == "complete":
            status_icon = "✅"
        elif status == "running":
            status_icon = "🔄"
        elif status == "failed":
            status_icon = "❌"
        else:
            status_icon = "⏳"

        with st.expander(f"{status_icon} {created} | {mode} | {message_preview}"):
            if st.button("Load This Run", key=f"load_run_{run['id']}"):
                run_details = get_run_details(run["id"])
                if run_details:
                    st.session_state.belief_selected_run = run_details
                    st.session_state.belief_results = run_details
                    st.rerun()

            if run.get("risk_flags"):
                risk_flags = run["risk_flags"]
                if isinstance(risk_flags, str):
                    try:
                        risk_flags = json.loads(risk_flags)
                    except:
                        risk_flags = []
                if risk_flags:
                    st.warning(f"⚠️ {len(risk_flags)} risk flag(s)")

            if run.get("completeness_score"):
                st.metric("Completeness", f"{run['completeness_score']:.0%}")

# ============================================
# MAIN PAGE
# ============================================

st.title("🧠 Belief-First Canvas")
st.markdown(
    "Reverse-engineer marketing messages into a structured Belief-First Master Canvas. "
    "Extract the belief structure, identify gaps, and detect compliance risks."
)

# Brand and product selector
from viraltracker.ui.utils import render_brand_selector, get_products_for_brand

brand_id, product_id = render_brand_selector(
    key="belief_brand_selector",
    include_product=True,
    product_key="belief_product_selector",
    product_label="Select Product",
)

if not brand_id:
    st.stop()

if not product_id:
    products = get_products_for_brand(brand_id)
    if products:
        product_id = st.selectbox(
            "Select Product",
            options=[p["id"] for p in products],
            format_func=lambda x: next((p["name"] for p in products if p["id"] == x), x),
            key="belief_product_fallback",
        )
    else:
        st.warning("No products found for this brand. Create a product first.")
        st.stop()

st.divider()

# Main layout
col_input, col_results = st.columns([1, 1])

with col_input:
    # Input section
    messages = render_input_section(brand_id, product_id)

    st.divider()

    # Mode section
    draft_mode, research_mode = render_mode_section()

    st.divider()

    # Run button
    if messages:
        if st.button("🚀 Run Pipeline", type="primary", disabled=st.session_state.belief_running):
            # Parse subreddits and search terms
            subreddits = [s.strip() for s in st.session_state.belief_subreddits.split(",") if s.strip()]
            search_terms = [s.strip() for s in st.session_state.belief_search_terms.split(",") if s.strip()]

            # Build scrape config with guardrails and quality filters
            scrape_config = {
                # Cost guardrails
                "max_api_calls": st.session_state.get("belief_max_api_calls", 10),
                "max_total_posts": st.session_state.get("belief_max_total_posts", 100),
                "max_posts_per_query": st.session_state.get("belief_posts_per_query", 25),
                "dedupe": True,
                # Quality filters
                "min_upvotes": st.session_state.get("belief_min_upvotes", 10),
                "min_comments": st.session_state.get("belief_min_comments", 3),
                "relevance_threshold": st.session_state.get("belief_relevance_threshold", 0.5),
                "top_percentile": st.session_state.get("belief_top_percentile", 0.30),
            }

            # Create run record
            run_id = create_run(
                product_id=product_id,
                brand_id=brand_id,
                messages=messages,
                draft_mode=draft_mode,
                research_mode=research_mode,
                format_hint=st.session_state.belief_format_hint or None,
                persona_hint=st.session_state.belief_persona_hint or None,
                subreddits=subreddits,
                search_terms=search_terms,
            )

            st.session_state.belief_running = True

            # Progress container
            progress = st.empty()

            def update_progress(msg):
                progress.info(msg)

            try:
                # Run pipeline
                result = asyncio.run(run_pipeline(
                    product_id=product_id,
                    messages=messages,
                    draft_mode=draft_mode,
                    research_mode=research_mode,
                    format_hint=st.session_state.belief_format_hint or None,
                    persona_hint=st.session_state.belief_persona_hint or None,
                    subreddits=subreddits,
                    search_terms=search_terms,
                    run_id=run_id,
                    scrape_config=scrape_config,
                    progress_callback=update_progress,
                ))

                st.session_state.belief_results = result
                st.session_state.belief_running = False
                st.rerun()

            except Exception as e:
                st.error(f"Pipeline failed: {e}")
                st.session_state.belief_running = False
    else:
        st.warning("Enter at least one message to analyze.")

    st.divider()

    # Run history
    render_run_history(product_id)

with col_results:
    # Results section
    if st.session_state.belief_results:
        render_results_section(st.session_state.belief_results)
    else:
        st.info("Run the pipeline to see results here.")
