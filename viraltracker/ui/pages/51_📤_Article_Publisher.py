"""
Article Publisher Page - QA validation and CMS publishing for SEO articles.

Provides UI for:
- Running QA validation checks on articles
- Viewing QA pass/fail results with details
- Configuring CMS integration (Shopify) per brand
- Publishing articles to configured CMS (draft or live)
"""

import logging

import streamlit as st

from viraltracker.ui.auth import require_auth

st.set_page_config(page_title="Article Publisher", page_icon="📤", layout="wide")
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


def get_qa_service():
    from viraltracker.services.seo_pipeline.services.qa_validation_service import QAValidationService
    return QAValidationService()


def get_publisher_service():
    from viraltracker.services.seo_pipeline.services.cms_publisher_service import CMSPublisherService
    return CMSPublisherService()


# =============================================================================
# SESSION STATE
# =============================================================================

if "seo_pub_qa_result" not in st.session_state:
    st.session_state.seo_pub_qa_result = None


# =============================================================================
# MAIN PAGE
# =============================================================================

st.title("📤 Article Publisher")

from viraltracker.ui.utils import render_brand_selector, get_current_organization_id

brand_id = render_brand_selector(key="seo_publisher_brand_selector")
if not brand_id:
    st.stop()

org_id = get_current_organization_id()

# Project selector
project_service = get_project_service()
projects = project_service.list_projects(org_id, brand_id=brand_id)

if not projects:
    st.info("No SEO projects found. Create one in the Keyword Research page first.")
    st.stop()

project_options = {p["id"]: p["name"] for p in projects}
selected_project_id = st.selectbox(
    "SEO Project",
    options=list(project_options.keys()),
    format_func=lambda x: project_options[x],
    key="seo_pub_project_selector",
)


# =============================================================================
# ARTICLE SELECTOR
# =============================================================================

content_service = get_content_service()
articles = content_service.list_articles(selected_project_id)

if not articles:
    st.info("No articles found in this project. Generate content in the Article Writer page first.")
    st.stop()

article_options = {}
for a in articles:
    keyword = a.get("keyword", "Untitled")
    status = a.get("status", "draft")
    article_options[a["id"]] = f"{keyword} [{status}]"

selected_article_id = st.selectbox(
    "Select Article",
    options=list(article_options.keys()),
    format_func=lambda x: article_options[x],
    key="seo_pub_article_selector",
)

article = content_service.get_article(selected_article_id)
if not article:
    st.error("Failed to load article.")
    st.stop()

# Article info
col_info1, col_info2, col_info3 = st.columns(3)
with col_info1:
    st.metric("Status", article.get("status", "unknown"))
with col_info2:
    st.metric("Phase", article.get("phase", "pending").upper())
with col_info3:
    cms_id = article.get("cms_article_id")
    st.metric("CMS ID", cms_id[:12] + "..." if cms_id else "Not published")


# =============================================================================
# QA VALIDATION
# =============================================================================

st.divider()
st.subheader("QA Validation")

col_qa1, col_qa2 = st.columns([1, 3])
with col_qa1:
    run_qa = st.button("Run QA Checks", key="seo_pub_run_qa", type="primary")

if run_qa:
    qa_service = get_qa_service()
    with st.spinner("Running QA checks..."):
        try:
            result = qa_service.validate_article(selected_article_id)
            st.session_state.seo_pub_qa_result = result
        except Exception as e:
            st.error(f"QA validation failed: {e}")

# Display QA results
qa_result = st.session_state.seo_pub_qa_result
if qa_result and qa_result.get("article_id") == selected_article_id:
    if qa_result["passed"]:
        st.success(
            f"QA PASSED — {qa_result['passed_checks']}/{qa_result['total_checks']} checks passed"
            + (f" ({qa_result['warning_count']} warnings)" if qa_result["warning_count"] else "")
        )
    else:
        st.error(
            f"QA FAILED — {qa_result['error_count']} error(s), {qa_result['warning_count']} warning(s)"
        )

    # Show individual checks
    with st.expander("Check Details", expanded=not qa_result["passed"]):
        for check in qa_result.get("checks", []):
            if check["passed"]:
                st.markdown(f"✅ **{check['name']}**: {check['message']}")
            elif check["severity"] == "error":
                st.markdown(f"❌ **{check['name']}**: {check['message']}")
            else:
                st.markdown(f"⚠️ **{check['name']}**: {check['message']}")

elif article.get("qa_report"):
    # Show saved QA report from DB
    saved_report = article["qa_report"]
    if isinstance(saved_report, dict):
        if saved_report.get("passed"):
            st.info(f"Previous QA: PASSED ({saved_report.get('passed_checks', '?')}/{saved_report.get('total_checks', '?')} checks)")
        else:
            st.warning(f"Previous QA: FAILED ({saved_report.get('error_count', '?')} errors)")


# =============================================================================
# CMS INTEGRATION STATUS
# =============================================================================

st.divider()
st.subheader("CMS Publishing")

integration = project_service.get_brand_integration(brand_id, org_id)

if not integration:
    st.warning("No CMS integration configured for this brand.")
    with st.expander("Configure Shopify Integration"):
        st.markdown("""
        To publish articles, configure Shopify integration for this brand:

        1. Go to your Shopify Admin > Settings > Apps > Develop apps
        2. Create a custom app with `read_content` and `write_content` scopes
        3. Generate access token (client credentials)
        4. Enter the details below
        """)

        with st.form("shopify_config_form"):
            store_domain = st.text_input("Store Domain", placeholder="mystore.myshopify.com")
            access_token = st.text_input("Access Token", placeholder="shpat_...", type="password")
            blog_id = st.text_input("Blog ID", placeholder="99206135908")
            api_version = st.text_input("API Version", value="2024-10")
            blog_handle = st.text_input("Blog Handle", value="articles")

            submitted = st.form_submit_button("Save Integration")
            if submitted:
                if store_domain and access_token and blog_id:
                    config = {
                        "store_domain": store_domain,
                        "access_token": access_token,
                        "blog_id": blog_id,
                        "api_version": api_version,
                        "blog_handle": blog_handle,
                    }
                    try:
                        project_service.upsert_brand_integration(
                            brand_id=brand_id,
                            organization_id=org_id,
                            platform="shopify",
                            config=config,
                        )
                        st.success("Shopify integration saved!")
                        st.rerun()
                    except Exception as e:
                        st.error(f"Failed to save: {e}")
                else:
                    st.error("Store domain, access token, and blog ID are required.")
else:
    platform = integration.get("platform", "unknown")
    config = integration.get("config", {})
    st.markdown(f"**Platform:** {platform.title()}")
    st.markdown(f"**Store:** {config.get('store_domain', 'N/A')}")
    st.markdown(f"**Blog ID:** {config.get('blog_id', 'N/A')}")
    st.markdown(f"**API Version:** {config.get('api_version', 'N/A')}")

    # Publish controls
    col_pub1, col_pub2 = st.columns(2)
    with col_pub1:
        publish_draft = st.button("Publish as Draft", key="seo_pub_draft", type="primary")
    with col_pub2:
        publish_live = st.button("Publish Live", key="seo_pub_live")

    if publish_draft or publish_live:
        draft = publish_draft
        publisher_service = get_publisher_service()
        with st.spinner(f"Publishing {'draft' if draft else 'live'}..."):
            try:
                result = publisher_service.publish_article(
                    article_id=selected_article_id,
                    brand_id=brand_id,
                    organization_id=org_id,
                    draft=draft,
                )
                st.success(f"Published successfully! CMS ID: {result.get('cms_article_id')}")
                if result.get("admin_url"):
                    st.markdown(f"[View in Shopify Admin]({result['admin_url']})")
                if result.get("published_url"):
                    st.markdown(f"[View Article]({result['published_url']})")

                # Auto-update cluster spoke status on publish
                if not draft:
                    try:
                        from viraltracker.services.seo_pipeline.services.cluster_management_service import ClusterManagementService
                        _csvc = ClusterManagementService()
                        _csvc.mark_spokes_published_for_article(selected_article_id)
                    except Exception as _e:
                        logger.warning(f"Failed to update spoke status: {_e}")
            except Exception as e:
                st.error(f"Publishing failed: {e}")

    # Show existing published URL
    if article.get("published_url"):
        st.divider()
        st.markdown(f"**Published URL:** [{article['published_url']}]({article['published_url']})")
