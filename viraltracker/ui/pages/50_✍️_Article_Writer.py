"""
Article Writer Page - 3-phase SEO article generation.

Provides UI for:
- Creating new articles from keywords
- Running 3-phase generation (Research, Write, Optimize)
- Reviewing phase outputs
- CLI mode toggle for external execution
"""

import logging

import streamlit as st

from viraltracker.ui.auth import require_auth

st.set_page_config(page_title="Article Writer", page_icon="✍️", layout="wide")
require_auth()

logger = logging.getLogger(__name__)


# =============================================================================
# HELPERS
# =============================================================================

def get_project_service():
    from viraltracker.services.seo_pipeline.services.seo_project_service import SEOProjectService
    return SEOProjectService()


def get_content_service():
    from viraltracker.services.seo_pipeline.services.content_generation_service import ContentGenerationService
    return ContentGenerationService()


# =============================================================================
# SESSION STATE
# =============================================================================

if "seo_writer_article_id" not in st.session_state:
    st.session_state.seo_writer_article_id = None


# =============================================================================
# MAIN PAGE
# =============================================================================

st.title("✍️ Article Writer")

from viraltracker.ui.utils import render_brand_selector, get_current_organization_id

brand_id = render_brand_selector(key="seo_writer_brand_selector")
if not brand_id:
    st.stop()

org_id = get_current_organization_id()

# Project selector
project_service = get_project_service()
projects = project_service.list_projects(org_id, brand_id=brand_id)

if not projects:
    st.info("No SEO projects. Create one in the Keyword Research page first.")
    st.stop()

project_options = {p["id"]: p["name"] for p in projects}
selected_project_id = st.selectbox(
    "SEO Project",
    options=list(project_options.keys()),
    format_func=lambda x: project_options[x],
    key="seo_writer_project_selector",
)

# =============================================================================
# ARTICLE SELECTOR / CREATOR
# =============================================================================

content_service = get_content_service()

col_left, col_right = st.columns([3, 1])

with col_left:
    articles = content_service.list_articles(selected_project_id)
    if articles:
        article_options = {
            a["id"]: f"{a.get('keyword', 'Untitled')} [{a.get('status', 'draft')}]"
            for a in articles
        }
        selected_article_id = st.selectbox(
            "Select Article",
            options=list(article_options.keys()),
            format_func=lambda x: article_options[x],
            key="seo_writer_article_selector",
        )
        st.session_state.seo_writer_article_id = selected_article_id
    else:
        st.info("No articles yet. Create one below.")
        selected_article_id = None

with col_right:
    with st.popover("New Article"):
        new_keyword = st.text_input("Target Keyword", key="seo_writer_new_keyword")

        # Author selector
        authors = project_service.list_authors(brand_id, org_id)
        author_id = None
        if authors:
            author_options = {a["id"]: a["name"] for a in authors}
            author_options[""] = "(No specific author)"
            author_id = st.selectbox(
                "Author",
                options=list(author_options.keys()),
                format_func=lambda x: author_options[x],
                key="seo_writer_new_author",
            )
            if not author_id:
                author_id = None

        # Optional cluster spoke linking
        spoke_id_to_link = None
        try:
            from viraltracker.services.seo_pipeline.services.cluster_management_service import ClusterManagementService
            _cluster_svc = ClusterManagementService()
            _planned_spokes = _cluster_svc.get_unlinked_planned_spokes(selected_project_id)
            if _planned_spokes:
                spoke_opts = {"": "(None)"} | {
                    s["spoke_id"]: f"{s['cluster_name']}: {s['keyword']}" for s in _planned_spokes
                }
                spoke_id_to_link = st.selectbox(
                    "Link to Cluster Spoke",
                    options=list(spoke_opts.keys()),
                    format_func=lambda x: spoke_opts[x],
                    key="seo_writer_spoke_link",
                ) or None
        except Exception:
            pass  # Cluster service not available, skip

        if st.button("Create Article", key="seo_writer_create_btn"):
            if new_keyword:
                article = content_service.create_article(
                    project_id=selected_project_id,
                    brand_id=brand_id,
                    organization_id=org_id,
                    keyword=new_keyword,
                    author_id=author_id,
                )
                st.session_state.seo_writer_article_id = article["id"]

                # Link to spoke if selected
                if spoke_id_to_link:
                    try:
                        _cluster_svc.assign_article_to_spoke(spoke_id_to_link, article["id"])
                    except Exception as e:
                        logger.warning(f"Failed to link article to spoke: {e}")

                st.success(f"Created article for '{new_keyword}'")
                st.rerun()

if not selected_article_id:
    st.stop()

# =============================================================================
# PHASE TABS
# =============================================================================

article = content_service.get_article(selected_article_id)
if not article:
    st.error("Article not found.")
    st.stop()

st.divider()

keyword = article.get("keyword", "")
st.subheader(f"Article: {keyword}")

# Mode selector
mode = st.radio(
    "Execution Mode",
    options=["api", "cli"],
    format_func=lambda x: "API Mode (direct generation)" if x == "api" else "CLI Mode (write prompt to file)",
    horizontal=True,
    key="seo_writer_mode",
)

tab_a, tab_b, tab_c = st.tabs(["Phase A: Research", "Phase B: Write", "Phase C: Optimize"])

with tab_a:
    phase_a_output = article.get("phase_a_output", "")

    if phase_a_output:
        st.success("Phase A complete")
        with st.expander("View Phase A Output", expanded=False):
            st.markdown(phase_a_output)
    else:
        st.info("Phase A not yet run.")

    if st.button("Run Phase A", type="primary", key="seo_writer_run_a"):
        with st.spinner("Running Phase A: Research & Outline..."):
            result = content_service.generate_phase_a(
                article_id=selected_article_id,
                keyword=keyword,
                author_id=article.get("author_id"),
                mode=mode,
                organization_id=org_id,
            )

        if result.get("mode") == "cli":
            st.info(f"Prompt written to: `{result['prompt_file']}`")
            st.code(result["instructions"])
        else:
            st.success(
                f"Phase A complete: {result.get('input_tokens', 0)} in / "
                f"{result.get('output_tokens', 0)} out tokens"
            )
            st.rerun()

with tab_b:
    phase_b_output = article.get("phase_b_output", "")
    phase_a_output = article.get("phase_a_output", "")

    if phase_b_output:
        st.success("Phase B complete")
        with st.expander("View Phase B Output", expanded=False):
            st.markdown(phase_b_output)
    elif not phase_a_output:
        st.warning("Complete Phase A first.")
    else:
        st.info("Phase B not yet run.")

    if phase_a_output and st.button("Run Phase B", type="primary", key="seo_writer_run_b"):
        with st.spinner("Running Phase B: Writing article..."):
            result = content_service.generate_phase_b(
                article_id=selected_article_id,
                keyword=keyword,
                phase_a_output=phase_a_output,
                author_id=article.get("author_id"),
                mode=mode,
                organization_id=org_id,
            )

        if result.get("mode") == "cli":
            st.info(f"Prompt written to: `{result['prompt_file']}`")
            st.code(result["instructions"])
        else:
            st.success(
                f"Phase B complete: {result.get('input_tokens', 0)} in / "
                f"{result.get('output_tokens', 0)} out tokens"
            )
            st.rerun()

with tab_c:
    phase_c_output = article.get("phase_c_output", "")
    phase_b_output = article.get("phase_b_output", "")

    if phase_c_output:
        st.success("Phase C complete")
        with st.expander("View Phase C Output", expanded=False):
            st.markdown(phase_c_output)
    elif not phase_b_output:
        st.warning("Complete Phase B first.")
    else:
        st.info("Phase C not yet run.")

    if phase_b_output and st.button("Run Phase C", type="primary", key="seo_writer_run_c"):
        with st.spinner("Running Phase C: SEO Optimization..."):
            result = content_service.generate_phase_c(
                article_id=selected_article_id,
                keyword=keyword,
                phase_b_output=phase_b_output,
                author_id=article.get("author_id"),
                mode=mode,
                organization_id=org_id,
            )

        if result.get("mode") == "cli":
            st.info(f"Prompt written to: `{result['prompt_file']}`")
            st.code(result["instructions"])
        else:
            st.success(
                f"Phase C complete: {result.get('input_tokens', 0)} in / "
                f"{result.get('output_tokens', 0)} out tokens"
            )
            st.rerun()
