"""
Dynamic navigation builder for Streamlit st.navigation().

Builds a dict of section -> page lists, conditionally including pages
based on the current organization's enabled features.

Two-tier gating model:

- **Section keys** (``section_brands``, ``section_ads``, …) are opt-out:
  visible by default unless explicitly disabled in ``org_features``.
  Disabling a section hides every page in it at once.

- **Page keys** (``ad_creator``, ``veo_avatars``, …) are opt-in:
  hidden by default unless explicitly enabled.

Visibility rule::

    page_visible = section_enabled OR page_key_enabled

This lets admins disable an entire section, then selectively re-enable
individual pages within it.

Usage (from app.py):
    from viraltracker.ui.nav import build_navigation_pages
    pages = build_navigation_pages()
    pg = st.navigation(pages)
    pg.run()
"""

import logging
from typing import Any, Dict, List

import streamlit as st

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Feature lookup (cached)
# ---------------------------------------------------------------------------

def _get_org_features(org_id: str) -> Dict[str, bool]:
    """
    Get feature flag dict for an organization.

    Returns:
        Dict mapping feature_key -> enabled (bool) for every configured key.
        Keys not present in the dict are "not configured".
    """
    return _get_org_features_cached(org_id)


@st.cache_data(ttl=300)
def _get_org_features_cached(org_id: str) -> Dict[str, bool]:
    """Cached inner function for feature lookups."""
    from viraltracker.services.feature_service import FeatureService, FeatureKey
    from viraltracker.core.database import get_supabase_client

    # Superuser "all" mode — everything enabled
    if org_id == "all":
        return {
            # Sections
            FeatureKey.SECTION_BRANDS: True,
            FeatureKey.SECTION_COMPETITORS: True,
            FeatureKey.SECTION_ADS: True,
            FeatureKey.SECTION_CONTENT: True,
            FeatureKey.SECTION_SYSTEM: True,
            # Pages
            FeatureKey.AD_CREATOR: True,
            FeatureKey.AD_LIBRARY: True,
            FeatureKey.AD_SCHEDULER: True,
            FeatureKey.AD_PLANNING: True,
            FeatureKey.VEO_AVATARS: True,
            FeatureKey.COMPETITOR_RESEARCH: True,
            FeatureKey.REDDIT_RESEARCH: True,
            FeatureKey.BRAND_RESEARCH: True,
            FeatureKey.BELIEF_CANVAS: True,
            FeatureKey.CONTENT_PIPELINE: True,
            FeatureKey.RESEARCH_INSIGHTS: True,
        }

    try:
        service = FeatureService(get_supabase_client())
        rows = service.get_org_features(org_id)
        return {r["feature_key"]: r.get("enabled", False) for r in rows}
    except Exception as e:
        logger.warning(f"Failed to load features for org {org_id}: {e}")
        return {}


# ---------------------------------------------------------------------------
# Navigation builder
# ---------------------------------------------------------------------------

def build_navigation_pages() -> Dict[str, List[st.Page]]:
    """
    Build the full navigation dict for st.navigation().

    Returns:
        Dict mapping section names to lists of st.Page objects.
        The empty-string key ("") holds the default/unsectioned page.
    """
    from viraltracker.ui.utils import get_current_organization_id, _auto_init_organization

    org_id = get_current_organization_id() or _auto_init_organization()
    features = _get_org_features(org_id) if org_id else {}

    # -- helpers ----------------------------------------------------------

    def has_section(key: str) -> bool:
        """Section key: opt-out (visible unless explicitly disabled)."""
        return features.get(key, True)

    def has_page(key: str) -> bool:
        """Page key: opt-in (hidden unless explicitly enabled)."""
        return features.get(key, False)

    def visible(section_key: str, page_key: str | None = None) -> bool:
        """True when a page should appear in the sidebar."""
        if has_section(section_key):
            return True
        if page_key and has_page(page_key):
            return True
        return False

    # -- build pages ------------------------------------------------------

    pages: Dict[str, List[st.Page]] = {}

    # Default page (always visible)
    pages[""] = [
        st.Page("pages/00_🎯_Agent_Chat.py", title="Agent Chat", icon="🎯", default=True),
    ]

    # --- Brands ---
    SK_BRANDS = "section_brands"
    brands: List[st.Page] = []
    if has_section(SK_BRANDS):
        brands.extend([
            st.Page("pages/02_🏢_Brand_Manager.py", title="Brand Manager", icon="🏢"),
            st.Page("pages/03_👤_Personas.py", title="Personas", icon="👤"),
            st.Page("pages/04_🔗_URL_Mapping.py", title="URL Mapping", icon="🔗"),
            st.Page("pages/06_🚀_Client_Onboarding.py", title="Client Onboarding", icon="🚀"),
        ])
    if visible(SK_BRANDS, "brand_research"):
        brands.append(st.Page("pages/05_🔬_Brand_Research.py", title="Brand Research", icon="🔬"))
    if brands:
        pages["Brands"] = brands

    # --- Competitors ---
    SK_COMP = "section_competitors"
    competitors: List[st.Page] = []
    if has_section(SK_COMP):
        competitors.extend([
            st.Page("pages/11_🎯_Competitors.py", title="Competitors", icon="🎯"),
            st.Page("pages/13_📊_Competitive_Analysis.py", title="Competitive Analysis", icon="📊"),
        ])
    if visible(SK_COMP, "competitor_research"):
        competitors.append(st.Page("pages/12_🔍_Competitor_Research.py", title="Competitor Research", icon="🔍"))
    if visible(SK_COMP, "reddit_research"):
        competitors.append(st.Page("pages/15_🔍_Reddit_Research.py", title="Reddit Research", icon="🔍"))
    if competitors:
        pages["Competitors"] = competitors

    # --- Ads ---
    SK_ADS = "section_ads"
    ads: List[st.Page] = []
    if visible(SK_ADS, "ad_creator"):
        ads.append(st.Page("pages/21_🎨_Ad_Creator.py", title="Ad Creator", icon="🎨"))
    if has_section(SK_ADS):
        ads.extend([
            st.Page("pages/23_🖼️_Ad_Gallery.py", title="Ad Gallery", icon="🖼️"),
            st.Page("pages/26_📊_Plan_List.py", title="Plan List", icon="📊"),
            st.Page("pages/27_🎯_Plan_Executor.py", title="Plan Executor", icon="🎯"),
            st.Page("pages/28_📋_Template_Queue.py", title="Template Queue", icon="📋"),
            st.Page(
                "pages/29_🔍_Template_Evaluation.py",
                title="Template Evaluation", icon="🔍",
                url_path="template-evaluation",
            ),
            st.Page(
                "pages/29_📦_Template_Recommendations.py",
                title="Template Recommendations", icon="📦",
                url_path="template-recommendations",
            ),
        ])
    if visible(SK_ADS, "ad_library"):
        ads.append(st.Page("pages/22_📊_Ad_History.py", title="Ad History", icon="📊"))
        ads.append(st.Page("pages/30_📈_Ad_Performance.py", title="Ad Performance", icon="📈"))
    if visible(SK_ADS, "ad_scheduler"):
        ads.append(st.Page("pages/24_📅_Ad_Scheduler.py", title="Ad Scheduler", icon="📅"))
    if visible(SK_ADS, "ad_planning"):
        ads.append(st.Page("pages/25_📋_Ad_Planning.py", title="Ad Planning", icon="📋"))
    if visible(SK_ADS, "belief_canvas"):
        ads.append(st.Page("pages/31_🧠_Belief_Canvas.py", title="Belief Canvas", icon="🧠"))
    if visible(SK_ADS, "research_insights"):
        ads.append(st.Page("pages/32_💡_Research_Insights.py", title="Research Insights", icon="💡"))
    if ads:
        pages["Ads"] = ads

    # --- Content ---
    SK_CONTENT = "section_content"
    content: List[st.Page] = []
    if visible(SK_CONTENT, "content_pipeline"):
        content.append(st.Page("pages/41_📝_Content_Pipeline.py", title="Content Pipeline", icon="📝"))
    if has_section(SK_CONTENT):
        content.extend([
            st.Page("pages/42_🎬_Comic_Video.py", title="Comic Video", icon="🎬"),
            st.Page("pages/43_📝_Comic_JSON_Generator.py", title="Comic JSON Generator", icon="📝"),
            st.Page("pages/44_🎬_Editor_Handoff.py", title="Editor Handoff", icon="🎬"),
            st.Page("pages/45_🎙️_Audio_Production.py", title="Audio Production", icon="🎙️"),
            st.Page("pages/46_📚_Knowledge_Base.py", title="Knowledge Base", icon="📚"),
        ])
    if visible(SK_CONTENT, "veo_avatars"):
        content.append(st.Page("pages/47_🎬_Veo_Avatars.py", title="Veo Avatars", icon="🎬"))
    if content:
        pages["Content"] = content

    # --- System ---
    SK_SYSTEM = "section_system"
    system: List[st.Page] = []
    if has_section(SK_SYSTEM):
        system.extend([
            st.Page("pages/61_🤖_Agent_Catalog.py", title="Agent Catalog", icon="🤖", url_path="agent-catalog"),
            st.Page("pages/61_📅_Scheduled_Tasks.py", title="Scheduled Tasks", icon="📅", url_path="scheduled-tasks"),
            st.Page("pages/62_📚_Tools_Catalog.py", title="Tools Catalog", icon="📚"),
            st.Page("pages/63_⚙️_Services_Catalog.py", title="Services Catalog", icon="⚙️"),
            st.Page("pages/64_🗄️_Database_Browser.py", title="Database Browser", icon="🗄️", url_path="database-browser"),
            st.Page("pages/64_⚙️_Platform_Settings.py", title="Platform Settings", icon="⚙️", url_path="platform-settings"),
            st.Page("pages/65_📜_History.py", title="History", icon="📜"),
            st.Page("pages/66_🌐_Public_Gallery.py", title="Public Gallery", icon="🌐"),
            st.Page("pages/67_📊_Pipeline_Visualizer.py", title="Pipeline Visualizer", icon="📊"),
            st.Page("pages/68_📊_Usage_Dashboard.py", title="Usage Dashboard", icon="📊"),
            st.Page("pages/69_🔧_Admin.py", title="Admin", icon="🔧"),
            st.Page("pages/99_🎥_Sora_MVP.py", title="Sora MVP", icon="🎥"),
        ])
    if system:
        pages["System"] = system

    return pages
