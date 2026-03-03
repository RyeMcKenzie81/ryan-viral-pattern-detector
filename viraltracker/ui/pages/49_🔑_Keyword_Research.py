"""
Keyword Research Page - SEO keyword discovery and analysis.

Provides UI for:
- Seed keyword input and Google Autocomplete discovery
- Keyword results table with filtering
- Competitor URL analysis (Phase 3)
"""

import asyncio
import logging

import streamlit as st

from viraltracker.ui.auth import require_auth

st.set_page_config(page_title="Keyword Research", page_icon="🔑", layout="wide")
require_auth()

logger = logging.getLogger(__name__)


# =============================================================================
# HELPERS
# =============================================================================

def get_project_service():
    from viraltracker.services.seo_pipeline.services.seo_project_service import SEOProjectService
    return SEOProjectService()


def get_keyword_service():
    from viraltracker.services.seo_pipeline.services.keyword_discovery_service import KeywordDiscoveryService
    return KeywordDiscoveryService()


# =============================================================================
# SESSION STATE
# =============================================================================

if "seo_discovery_results" not in st.session_state:
    st.session_state.seo_discovery_results = None

if "seo_selected_project_id" not in st.session_state:
    st.session_state.seo_selected_project_id = None


# =============================================================================
# MAIN PAGE
# =============================================================================

st.title("🔑 Keyword Research")

# Brand selector
from viraltracker.ui.utils import render_brand_selector, get_current_organization_id

brand_id = render_brand_selector(key="seo_keyword_brand_selector")
if not brand_id:
    st.stop()

org_id = get_current_organization_id()

# Project selector / creator
project_service = get_project_service()
projects = project_service.list_projects(org_id, brand_id=brand_id)

col1, col2 = st.columns([3, 1])
with col1:
    if projects:
        project_options = {p["id"]: p["name"] for p in projects}
        selected_project_id = st.selectbox(
            "SEO Project",
            options=list(project_options.keys()),
            format_func=lambda x: project_options[x],
            key="seo_project_selector",
        )
        st.session_state.seo_selected_project_id = selected_project_id
    else:
        st.info("No SEO projects yet. Create one to get started.")
        selected_project_id = None

with col2:
    with st.popover("New Project"):
        new_name = st.text_input("Project name", key="seo_new_project_name")
        if st.button("Create", key="seo_create_project"):
            if new_name:
                project = project_service.create_project(
                    brand_id=brand_id,
                    organization_id=org_id,
                    name=new_name,
                )
                st.success(f"Created project: {new_name}")
                st.session_state.seo_selected_project_id = project["id"]
                st.rerun()

if not selected_project_id:
    st.stop()

# =============================================================================
# KEYWORD DISCOVERY
# =============================================================================

st.subheader("Keyword Discovery")

seeds_input = st.text_area(
    "Seed Keywords (one per line)",
    placeholder="minecraft parenting\nfamily gaming tips\nkids screen time",
    height=100,
    key="seo_seeds_input",
)

col_a, col_b, col_c = st.columns(3)
with col_a:
    min_words = st.number_input("Min words", value=3, min_value=1, max_value=10, key="seo_min_words")
with col_b:
    max_words = st.number_input("Max words", value=10, min_value=1, max_value=20, key="seo_max_words")
with col_c:
    st.write("")  # Spacer
    st.write("")
    discover_btn = st.button("Discover Keywords", type="primary", key="seo_discover_btn")

if discover_btn and seeds_input:
    seed_list = [s.strip() for s in seeds_input.strip().split("\n") if s.strip()]
    if not seed_list:
        st.warning("Enter at least one seed keyword.")
    else:
        keyword_service = get_keyword_service()
        with st.spinner(f"Discovering keywords for {len(seed_list)} seed(s)..."):
            loop = asyncio.new_event_loop()
            try:
                result = loop.run_until_complete(
                    keyword_service.discover_keywords(
                        selected_project_id, seed_list, min_words, max_words
                    )
                )
            finally:
                loop.close()

        st.session_state.seo_discovery_results = result
        st.success(
            f"Found {result['total_keywords']} unique keywords, "
            f"{result['saved_count']} new saved to database."
        )

# =============================================================================
# KEYWORDS TABLE
# =============================================================================

st.subheader("Keywords")

keyword_service = get_keyword_service()
keywords = keyword_service.get_keywords(selected_project_id)

if keywords:
    # Status filter
    statuses = sorted(set(k.get("status", "discovered") for k in keywords))
    status_filter = st.multiselect(
        "Filter by status",
        options=statuses,
        default=statuses,
        key="seo_keyword_status_filter",
    )

    filtered = [k for k in keywords if k.get("status", "discovered") in status_filter]

    st.write(f"Showing {len(filtered)} of {len(keywords)} keywords")

    # Display as dataframe
    if filtered:
        import pandas as pd
        df = pd.DataFrame([
            {
                "Keyword": k["keyword"],
                "Words": k.get("word_count", 0),
                "Seed": k.get("seed_keyword", ""),
                "Frequency": k.get("found_in_seeds", 1),
                "Status": k.get("status", "discovered"),
                "Volume": k.get("search_volume") or "-",
                "Difficulty": k.get("keyword_difficulty") or "-",
            }
            for k in filtered
        ])
        st.dataframe(df, use_container_width=True, hide_index=True)
else:
    st.info("No keywords yet. Run discovery above to get started.")


# =============================================================================
# COMPETITOR ANALYSIS
# =============================================================================

st.divider()
st.subheader("Competitor Analysis")
st.caption(
    "Search Google for your target keyword, then paste the top 10-20 competitor URLs below. "
    "We'll analyze each page for SEO metrics and calculate a winning formula."
)

# Keyword for analysis context
analysis_keyword = st.text_input(
    "Target Keyword",
    placeholder="minecraft parenting tips",
    key="seo_analysis_keyword",
)

urls_input = st.text_area(
    "Competitor URLs (one per line)",
    placeholder="https://example.com/article-1\nhttps://example.com/article-2",
    height=150,
    key="seo_analysis_urls",
)

analyze_btn = st.button("Analyze Competitors", type="primary", key="seo_analyze_btn")

if analyze_btn:
    if not urls_input or not urls_input.strip():
        st.warning("Paste at least one competitor URL.")
    else:
        url_list = [u.strip() for u in urls_input.strip().split("\n") if u.strip()]
        if not url_list:
            st.warning("No valid URLs found.")
        else:
            from viraltracker.services.seo_pipeline.services.competitor_analysis_service import (
                CompetitorAnalysisService,
            )

            service = CompetitorAnalysisService()

            # Use a keyword_id if we have a selected keyword, otherwise placeholder
            keyword_id = "00000000-0000-0000-0000-000000000000"

            with st.spinner(f"Analyzing {len(url_list)} competitor page(s)..."):
                result = service.analyze_urls(keyword_id, url_list)

            st.session_state.seo_analysis_result = result

            if result["failed_count"] > 0:
                st.warning(
                    f"{result['analyzed_count']} analyzed, {result['failed_count']} failed. "
                    f"Failed: {', '.join(result.get('failed_urls', []))}"
                )
            else:
                st.success(f"Successfully analyzed {result['analyzed_count']} pages.")

# Display analysis results
if st.session_state.get("seo_analysis_result"):
    result = st.session_state.seo_analysis_result

    if result.get("results"):
        import pandas as pd

        st.write("**Per-Page Metrics**")
        df = pd.DataFrame([
            {
                "URL": r.get("url", "")[:60] + "..." if len(r.get("url", "")) > 60 else r.get("url", ""),
                "Words": r.get("word_count", 0),
                "H2s": r.get("h2_count", 0),
                "H3s": r.get("h3_count", 0),
                "Flesch": r.get("flesch_reading_ease", "-"),
                "Images": r.get("image_count", 0),
                "Int Links": r.get("internal_link_count", 0),
                "Ext Links": r.get("external_link_count", 0),
                "Schema": "Yes" if r.get("has_schema") else "No",
                "FAQ": "Yes" if r.get("has_faq") else "No",
                "TOC": "Yes" if r.get("has_toc") else "No",
            }
            for r in result["results"]
        ])
        st.dataframe(df, use_container_width=True, hide_index=True)

    if result.get("winning_formula"):
        wf = result["winning_formula"]
        st.write("**Winning Formula**")

        col1, col2, col3, col4 = st.columns(4)
        with col1:
            st.metric("Target Word Count", wf.get("target_word_count", 0))
            st.metric("Avg H2 Count", wf.get("avg_h2_count", 0))
        with col2:
            st.metric("Avg Images", wf.get("avg_image_count", 0))
            st.metric("Avg Flesch", wf.get("avg_flesch_score", 0))
        with col3:
            st.metric("Schema %", f"{wf.get('pct_with_schema', 0)}%")
            st.metric("FAQ %", f"{wf.get('pct_with_faq', 0)}%")
        with col4:
            st.metric("Author %", f"{wf.get('pct_with_author', 0)}%")
            st.metric("TOC %", f"{wf.get('pct_with_toc', 0)}%")

        if wf.get("opportunities"):
            st.write("**Opportunities**")
            for opp in wf["opportunities"]:
                severity = opp.get("severity", "")
                icon = {"HIGH": "🔴", "MEDIUM": "🟡", "LOW": "🟢"}.get(severity, "⚪")
                st.write(f"{icon} **[{severity}]** {opp['detail']}")
