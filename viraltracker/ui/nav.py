"""
Dynamic navigation builder for Streamlit st.navigation().

Builds a dict of section -> page lists, conditionally including
feature-gated pages based on the current organization's enabled features.

Usage (from app_v2.py):
    from viraltracker.ui.nav import build_navigation_pages
    pages = build_navigation_pages()
    pg = st.navigation(pages)
    pg.run()
"""

import logging
from typing import Dict, List, Set

import streamlit as st

logger = logging.getLogger(__name__)


def _get_org_features(org_id: str) -> Set[str]:
    """
    Get set of enabled feature keys for an organization.

    Cached per org for 5 minutes to avoid hitting the DB on every Streamlit rerun.

    Args:
        org_id: Organization ID

    Returns:
        Set of enabled feature key strings
    """
    return _get_org_features_cached(org_id)


@st.cache_data(ttl=300)
def _get_org_features_cached(org_id: str) -> Set[str]:
    """Cached inner function for feature lookups."""
    from viraltracker.services.feature_service import FeatureService
    from viraltracker.core.database import get_supabase_client

    # Superuser "all" mode — every feature enabled
    if org_id == "all":
        from viraltracker.services.feature_service import FeatureKey
        return {
            FeatureKey.AD_CREATOR,
            FeatureKey.AD_LIBRARY,
            FeatureKey.AD_SCHEDULER,
            FeatureKey.AD_PLANNING,
            FeatureKey.VEO_AVATARS,
            FeatureKey.COMPETITOR_RESEARCH,
            FeatureKey.REDDIT_RESEARCH,
            FeatureKey.BRAND_RESEARCH,
            FeatureKey.BELIEF_CANVAS,
            FeatureKey.CONTENT_PIPELINE,
            FeatureKey.RESEARCH_INSIGHTS,
        }

    try:
        service = FeatureService(get_supabase_client())
        rows = service.get_org_features(org_id)
        return {r["feature_key"] for r in rows if r.get("enabled")}
    except Exception as e:
        logger.warning(f"Failed to load features for org {org_id}: {e}")
        return set()


def build_navigation_pages() -> Dict[str, List[st.Page]]:
    """
    Build the full navigation dict for st.navigation().

    Resolves the current org and its enabled features, then
    conditionally includes feature-gated pages.

    Returns:
        Dict mapping section names to lists of st.Page objects.
        The empty-string key ("") holds the default/unsectioned page.
    """
    from viraltracker.ui.utils import get_current_organization_id, _auto_init_organization

    # Resolve org
    org_id = get_current_organization_id() or _auto_init_organization()
    features = _get_org_features(org_id) if org_id else set()

    # Helper: quick membership test
    def has(key: str) -> bool:
        return key in features

    # ------------------------------------------------------------------
    # Build page lists per section
    # ------------------------------------------------------------------

    pages: Dict[str, List[st.Page]] = {}

    # Default page (unsectioned)
    pages[""] = [
        st.Page("pages/00_🎯_Agent_Chat.py", title="Agent Chat", icon="🎯", default=True),
    ]

    # --- Brands ---
    brands: List[st.Page] = [
        st.Page("pages/02_🏢_Brand_Manager.py", title="Brand Manager", icon="🏢"),
        st.Page("pages/03_👤_Personas.py", title="Personas", icon="👤"),
        st.Page("pages/04_🔗_URL_Mapping.py", title="URL Mapping", icon="🔗"),
        st.Page("pages/06_🚀_Client_Onboarding.py", title="Client Onboarding", icon="🚀"),
    ]
    if has("brand_research"):
        brands.append(
            st.Page("pages/05_🔬_Brand_Research.py", title="Brand Research", icon="🔬"),
        )
    pages["Brands"] = brands

    # --- Competitors ---
    competitors: List[st.Page] = [
        st.Page("pages/11_🎯_Competitors.py", title="Competitors", icon="🎯"),
        st.Page("pages/13_📊_Competitive_Analysis.py", title="Competitive Analysis", icon="📊"),
    ]
    if has("competitor_research"):
        competitors.append(
            st.Page("pages/12_🔍_Competitor_Research.py", title="Competitor Research", icon="🔍"),
        )
    if has("reddit_research"):
        competitors.append(
            st.Page("pages/15_🔍_Reddit_Research.py", title="Reddit Research", icon="🔍"),
        )
    pages["Competitors"] = competitors

    # --- Ads ---
    ads: List[st.Page] = [
        st.Page("pages/23_🖼️_Ad_Gallery.py", title="Ad Gallery", icon="🖼️"),
        st.Page("pages/26_📊_Plan_List.py", title="Plan List", icon="📊"),
        st.Page("pages/27_🎯_Plan_Executor.py", title="Plan Executor", icon="🎯"),
        st.Page("pages/28_📋_Template_Queue.py", title="Template Queue", icon="📋"),
        st.Page(
            "pages/29_🔍_Template_Evaluation.py",
            title="Template Evaluation",
            icon="🔍",
            url_path="template-evaluation",
        ),
        st.Page(
            "pages/29_📦_Template_Recommendations.py",
            title="Template Recommendations",
            icon="📦",
            url_path="template-recommendations",
        ),
    ]
    if has("ad_creator"):
        ads.insert(0, st.Page("pages/21_🎨_Ad_Creator.py", title="Ad Creator", icon="🎨"))
    if has("ad_library"):
        ads.append(st.Page("pages/22_📊_Ad_History.py", title="Ad History", icon="📊"))
        ads.append(st.Page("pages/30_📈_Ad_Performance.py", title="Ad Performance", icon="📈"))
    if has("ad_scheduler"):
        ads.append(st.Page("pages/24_📅_Ad_Scheduler.py", title="Ad Scheduler", icon="📅"))
    if has("ad_planning"):
        ads.append(st.Page("pages/25_📋_Ad_Planning.py", title="Ad Planning", icon="📋"))
    if has("belief_canvas"):
        ads.append(st.Page("pages/31_🧠_Belief_Canvas.py", title="Belief Canvas", icon="🧠"))
    if has("research_insights"):
        ads.append(st.Page("pages/32_💡_Research_Insights.py", title="Research Insights", icon="💡"))
    pages["Ads"] = ads

    # --- Content ---
    content: List[st.Page] = [
        st.Page("pages/42_🎬_Comic_Video.py", title="Comic Video", icon="🎬"),
        st.Page("pages/43_📝_Comic_JSON_Generator.py", title="Comic JSON Generator", icon="📝"),
        st.Page("pages/44_🎬_Editor_Handoff.py", title="Editor Handoff", icon="🎬"),
        st.Page("pages/45_🎙️_Audio_Production.py", title="Audio Production", icon="🎙️"),
        st.Page("pages/46_📚_Knowledge_Base.py", title="Knowledge Base", icon="📚"),
    ]
    if has("content_pipeline"):
        content.insert(
            0,
            st.Page("pages/41_📝_Content_Pipeline.py", title="Content Pipeline", icon="📝"),
        )
    if has("veo_avatars"):
        content.append(
            st.Page("pages/47_🎬_Veo_Avatars.py", title="Veo Avatars", icon="🎬"),
        )
    pages["Content"] = content

    # --- System ---
    system: List[st.Page] = [
        st.Page(
            "pages/61_🤖_Agent_Catalog.py",
            title="Agent Catalog",
            icon="🤖",
            url_path="agent-catalog",
        ),
        st.Page(
            "pages/61_📅_Scheduled_Tasks.py",
            title="Scheduled Tasks",
            icon="📅",
            url_path="scheduled-tasks",
        ),
        st.Page("pages/62_📚_Tools_Catalog.py", title="Tools Catalog", icon="📚"),
        st.Page("pages/63_⚙️_Services_Catalog.py", title="Services Catalog", icon="⚙️"),
        st.Page(
            "pages/64_🗄️_Database_Browser.py",
            title="Database Browser",
            icon="🗄️",
            url_path="database-browser",
        ),
        st.Page(
            "pages/64_⚙️_Platform_Settings.py",
            title="Platform Settings",
            icon="⚙️",
            url_path="platform-settings",
        ),
        st.Page("pages/65_📜_History.py", title="History", icon="📜"),
        st.Page("pages/66_🌐_Public_Gallery.py", title="Public Gallery", icon="🌐"),
        st.Page("pages/67_📊_Pipeline_Visualizer.py", title="Pipeline Visualizer", icon="📊"),
        st.Page("pages/68_📊_Usage_Dashboard.py", title="Usage Dashboard", icon="📊"),
        st.Page("pages/69_🔧_Admin.py", title="Admin", icon="🔧"),
        st.Page("pages/99_🎥_Sora_MVP.py", title="Sora MVP", icon="🎥"),
    ]
    pages["System"] = system

    return pages
