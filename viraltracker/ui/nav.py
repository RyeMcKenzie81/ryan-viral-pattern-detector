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

Visibility rules::

    base_page_visible  = section_enabled
    opt_in_page_visible = page_key_enabled   (independent of section)

Disabling a section hides its base pages but does NOT affect opt-in pages.
Enabling a section shows base pages but does NOT auto-enable opt-in pages.

Usage (from app.py):
    from viraltracker.ui.nav import build_navigation_pages
    pages = build_navigation_pages()
    pg = st.navigation(pages)
    pg.run()
"""

import glob
import logging
import os
from typing import Any, Dict, List

import streamlit as st

logger = logging.getLogger(__name__)

# Pages with custom url_path that differs from the auto-derived filename path.
# Must stay in sync with the url_path= arguments in build_navigation_pages().
_CUSTOM_URL_PATHS: Dict[str, str] = {
    "29_🔍_Template_Evaluation.py": "template-evaluation",
    "29_📦_Template_Recommendations.py": "template-recommendations",
    "61_🤖_Agent_Catalog.py": "agent-catalog",
    "61_📅_Scheduled_Tasks.py": "scheduled-tasks",
    "64_🗄️_Database_Browser.py": "database-browser",
    "64_⚙️_Platform_Settings.py": "platform-settings",
}

_DEFAULT_PAGE_FILE = "00_🎯_Agent_Chat.py"


# ---------------------------------------------------------------------------
# Loading-phase navigation (no auth required)
# ---------------------------------------------------------------------------

def build_loading_pages() -> List[st.Page]:
    """Build a flat list of ALL page objects without feature gating.

    Used during the cookie-loading phase (first render after refresh) so that
    ``st.navigation()`` can be called before ``st.stop()``.  This preserves
    the current browser URL — without it, Streamlit resets to the default page
    because it has no routing information for that render cycle.

    Does NOT require authentication or organization context.
    """
    pages_dir = os.path.join(os.path.dirname(__file__), "pages")
    pages: List[st.Page] = []

    for filepath in sorted(glob.glob(os.path.join(pages_dir, "*.py"))):
        filename = os.path.basename(filepath)
        rel_path = f"pages/{filename}"

        kwargs: Dict[str, Any] = {}
        if filename in _CUSTOM_URL_PATHS:
            kwargs["url_path"] = _CUSTOM_URL_PATHS[filename]
        if filename == _DEFAULT_PAGE_FILE:
            kwargs["default"] = True

        pages.append(st.Page(rel_path, **kwargs))

    return pages


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
            # Brands pages
            FeatureKey.BRAND_MANAGER: True,
            FeatureKey.PERSONAS: True,
            FeatureKey.URL_MAPPING: True,
            FeatureKey.BRAND_RESEARCH: True,
            FeatureKey.TOOL_READINESS: True,
            # Competitors pages
            FeatureKey.COMPETITORS: True,
            FeatureKey.COMPETITIVE_ANALYSIS: True,
            FeatureKey.COMPETITOR_RESEARCH: True,
            FeatureKey.REDDIT_RESEARCH: True,
            # Ads pages
            FeatureKey.AD_CREATOR: True,
            FeatureKey.AD_HISTORY: True,
            FeatureKey.AD_PERFORMANCE: True,
            FeatureKey.AD_SCHEDULER: True,
            FeatureKey.AD_PLANNING: True,
            FeatureKey.BELIEF_CANVAS: True,
            FeatureKey.RESEARCH_INSIGHTS: True,
            FeatureKey.CONGRUENCE_INSIGHTS: True,
            FeatureKey.LANDING_PAGE_ANALYZER: True,
            FeatureKey.HOOK_ANALYSIS: True,
            FeatureKey.PLAN_LIST: True,
            FeatureKey.PLAN_EXECUTOR: True,
            FeatureKey.TEMPLATE_QUEUE: True,
            FeatureKey.TEMPLATE_EVALUATION: True,
            FeatureKey.TEMPLATE_RECOMMENDATIONS: True,
            FeatureKey.PUBLIC_GALLERY: True,
            # Content pages
            FeatureKey.CONTENT_PIPELINE: True,
            FeatureKey.COMIC_VIDEO: True,
            FeatureKey.COMIC_JSON_GENERATOR: True,
            FeatureKey.EDITOR_HANDOFF: True,
            FeatureKey.AUDIO_PRODUCTION: True,
            FeatureKey.KNOWLEDGE_BASE: True,
            FeatureKey.VEO_AVATARS: True,
            FeatureKey.SORA_MVP: True,
            # Video Tools pages
            FeatureKey.SECTION_VIDEO_TOOLS: True,
            FeatureKey.INSTAGRAM_CONTENT: True,
            FeatureKey.VIDEO_STUDIO: True,
            # System pages
            FeatureKey.AGENT_CATALOG: True,
            FeatureKey.SCHEDULED_TASKS: True,
            FeatureKey.TOOLS_CATALOG: True,
            FeatureKey.SERVICES_CATALOG: True,
            FeatureKey.DATABASE_BROWSER: True,
            FeatureKey.PLATFORM_SETTINGS: True,
            FeatureKey.HISTORY: True,
            FeatureKey.CLIENT_ONBOARDING: True,
            FeatureKey.PIPELINE_MANAGER: True,
            FeatureKey.PIPELINE_VISUALIZER: True,
            FeatureKey.ADMIN: True,
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
        """True when a page should appear in the sidebar.

        - Base pages (no page_key): follow the section toggle.
        - Opt-in pages (page_key given): follow their own toggle only,
          independent of the section state.
        """
        if page_key:
            return has_page(page_key)
        return has_section(section_key)

    # -- build pages ------------------------------------------------------

    pages: Dict[str, List[st.Page]] = {}

    # Default page (always visible)
    pages[""] = [
        st.Page("pages/00_🎯_Agent_Chat.py", title="Agent Chat", icon="🎯", default=True),
    ]

    # --- Brands ---
    SK_BRANDS = "section_brands"
    brands: List[st.Page] = []
    if visible(SK_BRANDS, "brand_manager"):
        brands.append(st.Page("pages/02_🏢_Brand_Manager.py", title="Brand Manager", icon="🏢"))
    if visible(SK_BRANDS, "personas"):
        brands.append(st.Page("pages/03_👤_Personas.py", title="Personas", icon="👤"))
    if visible(SK_BRANDS, "url_mapping"):
        brands.append(st.Page("pages/04_🔗_URL_Mapping.py", title="URL Mapping", icon="🔗"))
    if visible(SK_BRANDS, "brand_research"):
        brands.append(st.Page("pages/05_🔬_Brand_Research.py", title="Brand Research", icon="🔬"))
    if visible(SK_BRANDS, "tool_readiness"):
        brands.append(st.Page("pages/07_📥_Tool_Readiness.py", title="Tool Readiness", icon="📥"))
    if brands:
        pages["Brands"] = brands

    # --- Competitors ---
    SK_COMP = "section_competitors"
    competitors: List[st.Page] = []
    if visible(SK_COMP, "competitors"):
        competitors.append(st.Page("pages/11_🎯_Competitors.py", title="Competitors", icon="🎯"))
    if visible(SK_COMP, "competitive_analysis"):
        competitors.append(st.Page("pages/13_📊_Competitive_Analysis.py", title="Competitive Analysis", icon="📊"))
    if visible(SK_COMP, "competitor_research"):
        competitors.append(st.Page("pages/12_🔍_Competitor_Research.py", title="Competitor Research", icon="🔍"))
    if visible(SK_COMP, "reddit_research"):
        competitors.append(st.Page("pages/15_🔍_Reddit_Research.py", title="Reddit Research", icon="🔍"))
    if competitors:
        pages["Competitors"] = competitors

    # --- Ads ---
    SK_ADS = "section_ads"
    ads: List[st.Page] = []
    if has_section(SK_ADS):
        ads.append(st.Page("pages/23_🖼️_Ad_Gallery.py", title="Ad Gallery", icon="🖼️"))
    if visible(SK_ADS, "ad_creator"):
        ads.append(st.Page("pages/21_🎨_Ad_Creator.py", title="Ad Creator", icon="🎨"))
    if visible(SK_ADS, "ad_history"):
        ads.append(st.Page("pages/22_📊_Ad_History.py", title="Ad History", icon="📊"))
    if visible(SK_ADS, "ad_performance"):
        ads.append(st.Page("pages/30_📈_Ad_Performance.py", title="Ad Performance", icon="📈"))
    if visible(SK_ADS, "ad_scheduler"):
        ads.append(st.Page("pages/24_📅_Ad_Scheduler.py", title="Scheduler", icon="📅"))
    if visible(SK_ADS, "ad_planning"):
        ads.append(st.Page("pages/25_📋_Ad_Planning.py", title="Ad Planning", icon="📋"))
    if visible(SK_ADS, "plan_list"):
        ads.append(st.Page("pages/26_📊_Plan_List.py", title="Plan List", icon="📊"))
    if visible(SK_ADS, "plan_executor"):
        ads.append(st.Page("pages/27_🎯_Plan_Executor.py", title="Plan Executor", icon="🎯"))
    if visible(SK_ADS, "template_queue"):
        ads.append(st.Page("pages/28_📋_Template_Queue.py", title="Template Queue", icon="📋"))
    if visible(SK_ADS, "template_evaluation"):
        ads.append(st.Page(
            "pages/29_🔍_Template_Evaluation.py",
            title="Template Evaluation", icon="🔍",
            url_path="template-evaluation",
        ))
    if visible(SK_ADS, "template_recommendations"):
        ads.append(st.Page(
            "pages/29_📦_Template_Recommendations.py",
            title="Template Recommendations", icon="📦",
            url_path="template-recommendations",
        ))
    if visible(SK_ADS, "belief_canvas"):
        ads.append(st.Page("pages/31_🧠_Belief_Canvas.py", title="Belief Canvas", icon="🧠"))
    if visible(SK_ADS, "research_insights"):
        ads.append(st.Page("pages/32_💡_Research_Insights.py", title="Research Insights", icon="💡"))
    if visible(SK_ADS, "landing_page_analyzer"):
        ads.append(st.Page("pages/33_🏗️_Landing_Page_Analyzer.py", title="Landing Page Analyzer", icon="🏗️"))
    if visible(SK_ADS, "congruence_insights"):
        ads.append(st.Page("pages/34_🔗_Congruence_Insights.py", title="Congruence Insights", icon="🔗"))
    if visible(SK_ADS, "hook_analysis"):
        ads.append(st.Page("pages/35_🎣_Hook_Analysis.py", title="Hook Analysis", icon="🎣"))
    if visible(SK_ADS, "public_gallery"):
        ads.append(st.Page("pages/66_🌐_Public_Gallery.py", title="Public Gallery", icon="🌐"))
    if ads:
        pages["Ads"] = ads

    # --- Content ---
    SK_CONTENT = "section_content"
    content: List[st.Page] = []
    if visible(SK_CONTENT, "content_pipeline"):
        content.append(st.Page("pages/41_📝_Content_Pipeline.py", title="Content Pipeline", icon="📝"))
    if visible(SK_CONTENT, "comic_video"):
        content.append(st.Page("pages/42_🎬_Comic_Video.py", title="Comic Video", icon="🎬"))
    if visible(SK_CONTENT, "comic_json_generator"):
        content.append(st.Page("pages/43_📝_Comic_JSON_Generator.py", title="Comic JSON Generator", icon="📝"))
    if visible(SK_CONTENT, "editor_handoff"):
        content.append(st.Page("pages/44_🎬_Editor_Handoff.py", title="Editor Handoff", icon="🎬"))
    if visible(SK_CONTENT, "audio_production"):
        content.append(st.Page("pages/45_🎙️_Audio_Production.py", title="Audio Production", icon="🎙️"))
    if visible(SK_CONTENT, "knowledge_base"):
        content.append(st.Page("pages/46_📚_Knowledge_Base.py", title="Knowledge Base", icon="📚"))
    if visible(SK_CONTENT, "veo_avatars"):
        content.append(st.Page("pages/47_🎭_Avatars.py", title="Avatars", icon="🎭"))
    if visible(SK_CONTENT, "sora_mvp"):
        content.append(st.Page("pages/99_🎥_Sora_MVP.py", title="Sora MVP", icon="🎥"))
    if content:
        pages["Content"] = content

    # --- Video Tools ---
    SK_VIDEO = "section_video_tools"
    video_tools: List[st.Page] = []
    if visible(SK_VIDEO, "instagram_content"):
        video_tools.append(st.Page("pages/50_📸_Instagram_Content.py", title="Instagram Content", icon="📸"))
    if visible(SK_VIDEO, "video_studio"):
        video_tools.append(st.Page("pages/51_🎬_Video_Studio.py", title="Video Studio", icon="🎬"))
    if video_tools:
        pages["Video Tools"] = video_tools

    # --- System ---
    SK_SYSTEM = "section_system"
    system: List[st.Page] = []
    if visible(SK_SYSTEM, "agent_catalog"):
        system.append(st.Page("pages/61_🤖_Agent_Catalog.py", title="Agent Catalog", icon="🤖", url_path="agent-catalog"))
    if visible(SK_SYSTEM, "scheduled_tasks"):
        system.append(st.Page("pages/61_📅_Scheduled_Tasks.py", title="Scheduled Tasks", icon="📅", url_path="scheduled-tasks"))
    if visible(SK_SYSTEM, "tools_catalog"):
        system.append(st.Page("pages/62_📚_Tools_Catalog.py", title="Tools Catalog", icon="📚"))
    if visible(SK_SYSTEM, "services_catalog"):
        system.append(st.Page("pages/63_⚙️_Services_Catalog.py", title="Services Catalog", icon="⚙️"))
    if visible(SK_SYSTEM, "database_browser"):
        system.append(st.Page("pages/64_🗄️_Database_Browser.py", title="Database Browser", icon="🗄️", url_path="database-browser"))
    if visible(SK_SYSTEM, "platform_settings"):
        system.append(st.Page("pages/64_⚙️_Platform_Settings.py", title="Platform Settings", icon="⚙️", url_path="platform-settings"))
    if visible(SK_SYSTEM, "history"):
        system.append(st.Page("pages/65_📜_History.py", title="History", icon="📜"))
    if visible(SK_SYSTEM, "client_onboarding"):
        system.append(st.Page("pages/06_🚀_Client_Onboarding.py", title="Client Onboarding", icon="🚀"))
    if visible(SK_SYSTEM, "pipeline_manager"):
        system.append(st.Page("pages/62_🔧_Pipeline_Manager.py", title="Pipeline Manager", icon="🔧", url_path="pipeline-manager"))
    if visible(SK_SYSTEM, "pipeline_visualizer"):
        system.append(st.Page("pages/67_📊_Pipeline_Visualizer.py", title="Pipeline Visualizer", icon="📊"))
    if has_section(SK_SYSTEM):
        system.append(st.Page("pages/68_📊_Usage_Dashboard.py", title="Usage Dashboard", icon="📊"))
    if visible(SK_SYSTEM, "admin"):
        system.append(st.Page("pages/69_🔧_Admin.py", title="Admin", icon="🔧"))
    if system:
        pages["System"] = system

    return pages
