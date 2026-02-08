"""
Reddit Domain Sentiment Analysis - Research and extract customer insights from Reddit.

This page provides:
1. Reddit scraping configuration (queries, subreddits, timeframe)
2. Optional brand/persona association
3. Pipeline execution with progress tracking
4. Quote review by sentiment category
5. Historical run management
"""

import streamlit as st
import asyncio
from datetime import datetime
from uuid import UUID
from typing import Optional, List, Dict

# Page config (must be first)
st.set_page_config(
    page_title="Reddit Research",
    page_icon="🔍",
    layout="wide"
)

# Auth
from viraltracker.ui.auth import require_auth
require_auth()
from viraltracker.ui.utils import require_feature
require_feature("reddit_research", "Reddit Research")

# ============================================
# SESSION STATE
# ============================================

def init_session_state():
    """Initialize all session state variables."""
    defaults = {
        "reddit_search_queries": "",
        "reddit_subreddits": "",
        "reddit_timeframe": "month",
        "reddit_max_posts": 500,
        "reddit_min_upvotes": 20,
        "reddit_min_comments": 5,
        "reddit_relevance_threshold": 0.6,
        "reddit_signal_threshold": 0.5,
        "reddit_top_percentile": 0.20,
        "reddit_auto_sync": True,
        "reddit_running": False,
        "reddit_results": None,
        "reddit_selected_run": None,
        "reddit_persona_context": "",
        "reddit_topic_context": "",
        "reddit_scrape_legacy_mode": False,
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

def get_personas_for_brand(brand_id: str):
    """Fetch personas for a brand."""
    db = get_supabase()
    result = db.table("personas_4d").select(
        "id, name"
    ).eq("brand_id", brand_id).order("name").execute()
    return result.data or []

def get_recent_runs(limit: int = 10):
    """Fetch recent pipeline runs."""
    db = get_supabase()
    result = db.table("reddit_scrape_runs").select(
        "id, search_queries, subreddits, status, posts_scraped, "
        "quotes_extracted, created_at, completed_at, brands(name)"
    ).order("created_at", desc=True).limit(limit).execute()
    return result.data or []

def get_run_quotes(run_id: str):
    """Fetch quotes for a run grouped by category."""
    db = get_supabase()
    result = db.table("reddit_sentiment_quotes").select(
        "id, quote_text, source_type, sentiment_category, sentiment_subtype, "
        "confidence_score, extraction_reasoning, synced_to_persona"
    ).eq("run_id", run_id).order("sentiment_category").execute()
    return result.data or []

def get_products_for_brand(brand_id: str):
    """Fetch products for a brand."""
    db = get_supabase()
    result = db.table("products").select(
        "id, name"
    ).eq("brand_id", brand_id).order("name").execute()
    return result.data or []

def get_angle_candidate_service():
    """Get AngleCandidateService instance."""
    from viraltracker.services.angle_candidate_service import AngleCandidateService
    return AngleCandidateService()

def extract_candidates_from_run(run_id: str, product_id: str, brand_id: Optional[str] = None) -> Dict:
    """Extract angle candidates from a Reddit run's quotes.

    Args:
        run_id: Reddit scrape run UUID
        product_id: Product UUID to link candidates to
        brand_id: Optional brand UUID

    Returns:
        Dict with extraction stats {created, updated, errors}
    """
    from uuid import UUID
    service = get_angle_candidate_service()
    return service.extract_from_reddit_quotes(
        run_id=UUID(run_id),
        product_id=UUID(product_id),
        brand_id=UUID(brand_id) if brand_id else None,
    )

def render_recent_reddit_scrapes(brand_id: str):
    """Show recent one-time reddit_scrape runs for this brand."""
    db = get_supabase()
    try:
        jobs_result = db.table("scheduled_jobs").select(
            "id, status, created_at, parameters"
        ).eq("brand_id", brand_id).eq(
            "job_type", "reddit_scrape"
        ).eq("schedule_type", "one_time").order(
            "created_at", desc=True
        ).limit(5).execute()

        jobs = jobs_result.data or []
        if not jobs:
            return

        st.divider()
        st.caption("**Recent Reddit Scrapes**")

        for job in jobs:
            job_id = job["id"]

            # Fetch latest run for this job
            run_result = db.table("scheduled_job_runs").select(
                "status, started_at, completed_at, logs"
            ).eq("scheduled_job_id", job_id).order(
                "started_at", desc=True
            ).limit(1).execute()

            run = run_result.data[0] if run_result.data else None

            if run:
                run_status = run.get("status", "unknown")
                status_emoji = {"completed": "✅", "failed": "❌", "running": "🔄"}.get(run_status, "⏳")
                started = run.get("started_at", "")
                if started:
                    try:
                        started_dt = datetime.fromisoformat(started.replace("Z", "+00:00"))
                        started_str = started_dt.strftime("%b %d, %I:%M %p")
                    except Exception:
                        started_str = started[:16]
                else:
                    started_str = "Pending"

                # Extract summary from logs
                logs = run.get("logs", "") or ""
                summary = ""
                for line in logs.split("\n"):
                    if "Quotes extracted:" in line or "Posts scraped:" in line:
                        summary = line.strip()
                        break

                # Show queries from parameters
                params = job.get("parameters") or {}
                queries = params.get("search_queries", [])
                queries_preview = ", ".join(queries[:2]) + ("..." if len(queries) > 2 else "") if queries else ""

                display = f"{status_emoji} {started_str}"
                if queries_preview:
                    display += f" — {queries_preview}"
                if summary:
                    display += f" | {summary}"
                st.caption(display)
            else:
                # Job queued but no run yet
                st.caption(f"⏳ Queued — waiting for worker pickup")

    except Exception as e:
        st.caption(f"Could not load recent runs: {e}")


# ============================================
# UI COMPONENTS
# ============================================

def render_search_config():
    """Render search configuration section."""
    st.subheader("Search Configuration")

    col1, col2 = st.columns(2)

    with col1:
        st.session_state.reddit_search_queries = st.text_area(
            "Search Queries (one per line)",
            value=st.session_state.reddit_search_queries,
            placeholder="dog food allergies\nbest dog food for sensitive stomach\ndog digestive issues",
            height=120,
            help="Enter search terms to find relevant Reddit posts"
        )

        st.session_state.reddit_subreddits = st.text_input(
            "Subreddits (comma-separated, optional)",
            value=st.session_state.reddit_subreddits,
            placeholder="dogs, DogFood, puppy101",
            help="Leave empty to search all of Reddit"
        )

    with col2:
        st.session_state.reddit_timeframe = st.selectbox(
            "Time Range",
            options=["hour", "day", "week", "month", "year", "all"],
            index=["hour", "day", "week", "month", "year", "all"].index(
                st.session_state.reddit_timeframe
            ),
            help="How far back to search"
        )

        st.session_state.reddit_max_posts = st.slider(
            "Max Posts to Scrape",
            min_value=100,
            max_value=2000,
            value=st.session_state.reddit_max_posts,
            step=100,
            help="More posts = higher cost but better coverage"
        )

    # Context for LLM
    st.subheader("Context for Analysis")
    col3, col4 = st.columns(2)

    with col3:
        st.session_state.reddit_persona_context = st.text_area(
            "Target Persona Description",
            value=st.session_state.reddit_persona_context,
            placeholder="Health-conscious dog owners aged 30-50 who are concerned about their pet's nutrition and digestive health",
            height=80,
            help="Describe who you're researching to improve relevance filtering"
        )

    with col4:
        st.session_state.reddit_topic_context = st.text_area(
            "Topic/Domain Focus",
            value=st.session_state.reddit_topic_context,
            placeholder="Premium dog food, digestive health supplements, pet nutrition",
            height=80,
            help="What specific area are you researching?"
        )

def render_filter_config():
    """Render filtering configuration."""
    with st.expander("Advanced Filters", expanded=False):
        col1, col2, col3 = st.columns(3)

        with col1:
            st.session_state.reddit_min_upvotes = st.number_input(
                "Min Upvotes",
                min_value=0,
                max_value=1000,
                value=st.session_state.reddit_min_upvotes,
                help="Minimum upvotes for engagement filter"
            )

            st.session_state.reddit_min_comments = st.number_input(
                "Min Comments",
                min_value=0,
                max_value=100,
                value=st.session_state.reddit_min_comments,
                help="Minimum comments for engagement filter"
            )

        with col2:
            st.session_state.reddit_relevance_threshold = st.slider(
                "Relevance Threshold",
                min_value=0.0,
                max_value=1.0,
                value=st.session_state.reddit_relevance_threshold,
                step=0.05,
                help="Minimum relevance score (0-1)"
            )

            st.session_state.reddit_signal_threshold = st.slider(
                "Signal Threshold",
                min_value=0.0,
                max_value=1.0,
                value=st.session_state.reddit_signal_threshold,
                step=0.05,
                help="Minimum signal score (0-1)"
            )

        with col3:
            st.session_state.reddit_top_percentile = st.slider(
                "Top Percentile",
                min_value=0.05,
                max_value=0.50,
                value=st.session_state.reddit_top_percentile,
                step=0.05,
                format="%.0f%%",
                help="Keep top X% of posts for extraction"
            )

def render_brand_association():
    """Render optional brand/persona association."""
    st.subheader("Brand Association (Optional)")
    st.caption("Associate results with a brand to enable persona sync")

    col1, col2 = st.columns(2)

    with col1:
        brands = get_brands()
        brand_options = {"None (Standalone Research)": None}
        brand_options.update({b["name"]: b["id"] for b in brands})

        selected_brand_name = st.selectbox(
            "Associate with Brand",
            options=list(brand_options.keys()),
            key="reddit_brand_selector"
        )
        brand_id = brand_options[selected_brand_name]

    with col2:
        persona_id = None
        if brand_id:
            personas = get_personas_for_brand(brand_id)
            if personas:
                persona_options = {"None": None}
                persona_options.update({p["name"]: p["id"] for p in personas})

                selected_persona = st.selectbox(
                    "Sync to Persona",
                    options=list(persona_options.keys()),
                    key="reddit_persona_selector"
                )
                persona_id = persona_options[selected_persona]

                if persona_id:
                    st.session_state.reddit_auto_sync = st.checkbox(
                        "Auto-sync quotes to persona fields",
                        value=st.session_state.reddit_auto_sync,
                        help="Automatically populate pain_points, desired_outcomes, etc."
                    )
            else:
                st.info("No personas found for this brand")
        else:
            st.info("Select a brand to enable persona sync")

    return brand_id, persona_id

def render_run_button(brand_id: Optional[str], persona_id: Optional[str]):
    """Render the run button and execute pipeline (queued or legacy)."""
    # Parse queries
    queries = [
        q.strip() for q in st.session_state.reddit_search_queries.split("\n")
        if q.strip()
    ]

    # Parse subreddits
    subreddits = None
    if st.session_state.reddit_subreddits:
        subreddits = [
            s.strip() for s in st.session_state.reddit_subreddits.split(",")
            if s.strip()
        ]

    # Require at least one of: search queries OR subreddits
    if not queries and not subreddits:
        st.warning("Please enter search queries or specify subreddits")
        return

    # Cost estimate
    estimated_cost = (st.session_state.reddit_max_posts / 1000) * 1.50 + 0.85
    st.info(f"Estimated cost: ~${estimated_cost:.2f} (Apify + LLM)")

    legacy_mode = st.checkbox(
        "Run analysis directly (legacy)", value=False, key="reddit_scrape_legacy_mode",
        help="Runs the pipeline in-process instead of queuing to the background worker"
    )

    if legacy_mode:
        # Legacy mode: original in-process behavior
        if st.button(
            "Run Reddit Sentiment Analysis",
            type="primary",
            disabled=st.session_state.reddit_running,
            use_container_width=True,
            key="reddit_run_legacy"
        ):
            st.session_state.reddit_running = True
            st.session_state.reddit_results = None

            with st.spinner("Running pipeline... This may take several minutes."):
                progress_bar = st.progress(0, text="Starting...")

                async def run_pipeline():
                    from viraltracker.pipelines.reddit_sentiment import run_reddit_sentiment

                    result = await run_reddit_sentiment(
                        search_queries=queries,
                        brand_id=UUID(brand_id) if brand_id else None,
                        persona_id=UUID(persona_id) if persona_id else None,
                        subreddits=subreddits,
                        timeframe=st.session_state.reddit_timeframe,
                        max_posts=st.session_state.reddit_max_posts,
                        min_upvotes=st.session_state.reddit_min_upvotes,
                        min_comments=st.session_state.reddit_min_comments,
                        relevance_threshold=st.session_state.reddit_relevance_threshold,
                        signal_threshold=st.session_state.reddit_signal_threshold,
                        top_percentile=st.session_state.reddit_top_percentile,
                        auto_sync_to_persona=st.session_state.reddit_auto_sync and persona_id is not None,
                        persona_context=st.session_state.reddit_persona_context or None,
                        topic_context=st.session_state.reddit_topic_context or None,
                    )
                    return result

                try:
                    result = asyncio.run(run_pipeline())
                    st.session_state.reddit_results = result
                    progress_bar.progress(100, text="Complete!")

                    if result.get("status") == "success":
                        st.success(
                            f"Analysis complete! Extracted {result.get('quotes_extracted', 0)} quotes "
                            f"from {result.get('posts_top_selected', 0)} top posts."
                        )
                    else:
                        st.error(f"Pipeline failed: {result.get('error', 'Unknown error')}")

                except Exception as e:
                    st.error(f"Pipeline error: {str(e)}")

            st.session_state.reddit_running = False
            st.rerun()
    else:
        # Queued mode: queue to background worker
        if not brand_id:
            st.warning("Select a brand above to use background processing, or enable legacy mode for standalone research.")
            return

        if st.button(
            "Run Reddit Sentiment Analysis",
            type="primary",
            use_container_width=True,
            key="reddit_run_queued"
        ):
            from viraltracker.services.pipeline_helpers import queue_one_time_job

            parameters = {
                "search_queries": queries,
                "timeframe": st.session_state.reddit_timeframe,
                "max_posts": st.session_state.reddit_max_posts,
                "min_upvotes": st.session_state.reddit_min_upvotes,
                "min_comments": st.session_state.reddit_min_comments,
                "relevance_threshold": st.session_state.reddit_relevance_threshold,
                "signal_threshold": st.session_state.reddit_signal_threshold,
                "top_percentile": st.session_state.reddit_top_percentile,
                "auto_sync_to_persona": st.session_state.reddit_auto_sync and persona_id is not None,
            }
            if subreddits:
                parameters["subreddits"] = subreddits
            if persona_id:
                parameters["persona_id"] = persona_id
            if st.session_state.reddit_persona_context:
                parameters["persona_context"] = st.session_state.reddit_persona_context
            if st.session_state.reddit_topic_context:
                parameters["topic_context"] = st.session_state.reddit_topic_context

            job_id = queue_one_time_job(
                brand_id=brand_id,
                job_type="reddit_scrape",
                parameters=parameters,
            )
            if job_id:
                st.success("Reddit scrape queued! It will start within 60 seconds. Check recent runs below for progress.")
            else:
                st.error("Failed to queue scrape job. Please try legacy mode.")

        # Recent manual scrape runs
        render_recent_reddit_scrapes(brand_id)

def render_results():
    """Render pipeline results."""
    if not st.session_state.reddit_results:
        return

    results = st.session_state.reddit_results

    st.divider()
    st.subheader("Results")

    # Metrics row
    col1, col2, col3, col4, col5 = st.columns(5)
    with col1:
        st.metric("Posts Scraped", results.get("posts_scraped", 0))
    with col2:
        st.metric("After Filters", results.get("posts_after_signal", 0))
    with col3:
        st.metric("Top Selected", results.get("posts_top_selected", 0))
    with col4:
        st.metric("Quotes Extracted", results.get("quotes_extracted", 0))
    with col5:
        st.metric("Synced to Persona", results.get("quotes_synced", 0))

    # Cost
    total_cost = results.get("apify_cost", 0) + results.get("llm_cost_estimate", 0)
    st.caption(f"Total estimated cost: ${total_cost:.2f}")

    # Quotes by category
    quotes_by_cat = results.get("quotes_by_category", {})
    if quotes_by_cat:
        st.subheader("Quotes by Category")

        category_info = {
            "PAIN_POINT": ("Pain Points", "Problems and frustrations"),
            "DESIRED_OUTCOME": ("Desired Outcomes", "What success looks like"),
            "BUYING_OBJECTION": ("Buying Objections", "Why they hesitate"),
            "FAILED_SOLUTION": ("Failed Solutions", "What didn't work"),
            "DESIRED_FEATURE": ("Desired Features", "What they want"),
            "FAMILIAR_SOLUTION": ("Familiar Solutions", "What they know about"),
        }

        tab_labels = [
            f"{info[0]} ({quotes_by_cat.get(cat, 0)})"
            for cat, info in category_info.items()
        ]
        tabs = st.tabs(tab_labels)

        run_id = results.get("run_id")
        if run_id:
            quotes = get_run_quotes(run_id)

            for tab, (cat_key, (cat_name, cat_desc)) in zip(tabs, category_info.items()):
                with tab:
                    cat_quotes = [q for q in quotes if q["sentiment_category"] == cat_key]

                    if cat_quotes:
                        st.caption(cat_desc)
                        for q in cat_quotes:
                            with st.container():
                                st.markdown(f'> "{q["quote_text"]}"')
                                col1, col2 = st.columns([3, 1])
                                with col1:
                                    if q.get("sentiment_subtype"):
                                        st.caption(f"Type: {q['sentiment_subtype']}")
                                    if q.get("extraction_reasoning"):
                                        st.caption(f"Why: {q['extraction_reasoning'][:100]}...")
                                with col2:
                                    st.caption(f"Confidence: {q.get('confidence_score', 0):.0%}")
                                st.divider()
                    else:
                        st.info(f"No {cat_name.lower()} found")

        # Angle Pipeline Extraction Section
        render_candidate_extraction(run_id, results)

def render_candidate_extraction(run_id: str, results: Dict):
    """Render UI for extracting angle candidates from quotes."""
    st.divider()
    st.subheader("Extract to Angle Pipeline")
    st.caption("Create angle candidates from extracted quotes for ad testing.")

    # Get brand from session or results
    brand_id = st.session_state.get("reddit_brand_selector_value")
    if not brand_id:
        # Try to get from run data
        runs = get_recent_runs(limit=1)
        for run in runs:
            if run.get("id") == run_id and run.get("brands"):
                brand_id = run["brands"].get("id")
                break

    # Need a brand to get products
    if not brand_id:
        brands = get_brands()
        if not brands:
            st.info("No brands configured. Create a brand first to extract candidates.")
            return

        brand_options = {b["name"]: b["id"] for b in brands}
        selected_brand = st.selectbox(
            "Select Brand for Extraction",
            options=list(brand_options.keys()),
            key="reddit_extract_brand"
        )
        brand_id = brand_options[selected_brand]

    # Get products for brand
    products = get_products_for_brand(brand_id)
    if not products:
        st.warning("No products found for this brand. Create a product first.")
        return

    product_options = {p["name"]: p["id"] for p in products}

    col1, col2 = st.columns([2, 1])

    with col1:
        selected_product = st.selectbox(
            "Link Candidates to Product",
            options=list(product_options.keys()),
            key="reddit_extract_product",
            help="Candidates will be linked to this product for angle testing"
        )
        product_id = product_options[selected_product]

    with col2:
        # Count extractable quotes
        quotes_by_cat = results.get("quotes_by_category", {})
        extractable = sum(
            quotes_by_cat.get(cat, 0)
            for cat in ["PAIN_POINT", "DESIRED_OUTCOME", "BUYING_OBJECTION", "FAILED_SOLUTION"]
        )
        st.metric("Extractable Quotes", extractable)

    if extractable > 0:
        if st.button(
            "Extract to Angle Pipeline",
            type="primary",
            key="reddit_extract_btn",
            help="Create angle candidates from pain points, desired outcomes, objections, and failed solutions"
        ):
            with st.spinner("Extracting candidates..."):
                try:
                    stats = extract_candidates_from_run(
                        run_id=run_id,
                        product_id=product_id,
                        brand_id=brand_id
                    )

                    if stats.get("created", 0) > 0 or stats.get("updated", 0) > 0:
                        st.success(
                            f"Extraction complete! Created {stats.get('created', 0)} new candidates, "
                            f"updated {stats.get('updated', 0)} existing."
                        )
                    else:
                        st.info("No new candidates created. Quotes may already exist as candidates.")

                    if stats.get("errors", 0) > 0:
                        st.warning(f"{stats.get('errors', 0)} errors during extraction.")

                except Exception as e:
                    st.error(f"Extraction failed: {e}")
    else:
        st.info("No extractable quotes found (pain points, desired outcomes, objections, failed solutions).")

def render_history():
    """Render historical runs."""
    st.subheader("Previous Runs")

    runs = get_recent_runs(limit=10)

    if not runs:
        st.info("No previous runs found")
        return

    for run in runs:
        run_date = run.get("created_at", "")[:10] if run.get("created_at") else "Unknown"
        status = run.get("status", "unknown")
        brand_name = run.get("brands", {}).get("name", "Standalone") if run.get("brands") else "Standalone"
        queries = run.get("search_queries", [])
        queries_preview = ", ".join(queries[:2]) + ("..." if len(queries) > 2 else "")

        status_icon = {
            "completed": "✅",
            "failed": "❌",
            "running": "🔄",
            "pending": "⏳"
        }.get(status, "❓")

        with st.expander(
            f"{status_icon} {run_date} - {queries_preview} ({brand_name})",
            expanded=False
        ):
            col1, col2 = st.columns(2)
            with col1:
                st.write(f"**Status:** {status}")
                st.write(f"**Posts Scraped:** {run.get('posts_scraped', 0)}")
                st.write(f"**Quotes Extracted:** {run.get('quotes_extracted', 0)}")
            with col2:
                st.write(f"**Queries:** {', '.join(queries)}")
                subreddits = run.get("subreddits")
                if subreddits:
                    st.write(f"**Subreddits:** {', '.join(subreddits)}")

            if st.button("View Quotes", key=f"view_{run['id']}"):
                st.session_state.reddit_selected_run = run["id"]
                # Load quotes to get category counts
                quotes = get_run_quotes(run["id"])
                quotes_by_cat = {}
                for q in quotes:
                    cat = q.get("sentiment_category", "UNKNOWN")
                    quotes_by_cat[cat] = quotes_by_cat.get(cat, 0) + 1

                st.session_state.reddit_results = {
                    "status": "success",
                    "run_id": run["id"],
                    "posts_scraped": run.get("posts_scraped", 0),
                    "quotes_extracted": run.get("quotes_extracted", 0),
                    "quotes_by_category": quotes_by_cat,
                }
                st.rerun()

# ============================================
# MAIN
# ============================================

def main():
    st.title("🔍 Reddit Domain Sentiment Analysis")
    st.markdown(
        "Extract customer insights and quotes from Reddit discussions. "
        "Results can be synced to persona fields for belief-first planning."
    )

    # Organization context (selector rendered once in app.py sidebar)

    # Search config
    render_search_config()

    st.divider()

    # Filter config
    render_filter_config()

    st.divider()

    # Brand association
    brand_id, persona_id = render_brand_association()

    st.divider()

    # Run button
    render_run_button(brand_id, persona_id)

    # Results
    render_results()

    st.divider()

    # History
    render_history()

if __name__ == "__main__":
    main()
