"""
Feature Service - Organization Feature Flag Management

Controls which features each organization can access.

Usage:
    from viraltracker.services.feature_service import FeatureService, FeatureKey
    from viraltracker.core.database import get_supabase_client

    service = FeatureService(get_supabase_client())
    if service.has_feature(org_id, FeatureKey.VEO_AVATARS):
        # Show Veo feature
"""

from typing import List, Optional
import logging

from supabase import Client

logger = logging.getLogger(__name__)


class FeatureKey:
    """
    Feature flag keys.

    Use these constants when checking/setting features to avoid typos.

    Two kinds of keys:

    - **Section keys** (``SECTION_*``): opt-out — visible by default.
      Disable one to hide every page in that sidebar section.
    - **Page keys** (everything else): opt-in — hidden by default.
      Enable one to show a specific page.

    Visibility rules used by ``nav.py``::

        base_page_visible  = section_enabled
        opt_in_page_visible = page_key_enabled   (independent of section)
    """

    # --- Section-level keys (opt-out: visible unless explicitly disabled) ---
    SECTION_BRANDS = "section_brands"
    SECTION_COMPETITORS = "section_competitors"
    SECTION_ADS = "section_ads"
    SECTION_CONTENT = "section_content"
    SECTION_SYSTEM = "section_system"

    # --- Page-level keys (opt-in: hidden unless explicitly enabled) ---
    # Brands
    BRAND_MANAGER = "brand_manager"
    PERSONAS = "personas"
    URL_MAPPING = "url_mapping"
    BRAND_RESEARCH = "brand_research"
    TOOL_READINESS = "tool_readiness"
    # Competitors
    COMPETITORS = "competitors"
    COMPETITIVE_ANALYSIS = "competitive_analysis"
    COMPETITOR_RESEARCH = "competitor_research"
    REDDIT_RESEARCH = "reddit_research"
    # Ads
    AD_CREATOR = "ad_creator"
    AD_HISTORY = "ad_history"
    AD_PERFORMANCE = "ad_performance"
    AD_INTELLIGENCE = "ad_intelligence"
    AD_LIBRARY = "ad_library"  # legacy — kept for backward compat
    AD_SCHEDULER = "ad_scheduler"
    AD_PLANNING = "ad_planning"
    BELIEF_CANVAS = "belief_canvas"
    RESEARCH_INSIGHTS = "research_insights"
    CONGRUENCE_INSIGHTS = "congruence_insights"
    LANDING_PAGE_ANALYZER = "landing_page_analyzer"
    HOOK_ANALYSIS = "hook_analysis"
    EXPERIMENTS = "experiments"
    VIDEO_BUCKETS = "video_buckets"
    PLAN_LIST = "plan_list"
    PLAN_EXECUTOR = "plan_executor"
    TEMPLATE_QUEUE = "template_queue"
    TEMPLATE_EVALUATION = "template_evaluation"
    TEMPLATE_RECOMMENDATIONS = "template_recommendations"
    PUBLIC_GALLERY = "public_gallery"
    # Content
    CONTENT_PIPELINE = "content_pipeline"
    COMIC_VIDEO = "comic_video"
    COMIC_JSON_GENERATOR = "comic_json_generator"
    EDITOR_HANDOFF = "editor_handoff"
    AUDIO_PRODUCTION = "audio_production"
    KNOWLEDGE_BASE = "knowledge_base"
    VEO_AVATARS = "veo_avatars"
    SORA_MVP = "sora_mvp"
    # System
    AGENT_CATALOG = "agent_catalog"
    SCHEDULED_TASKS = "scheduled_tasks"
    TOOLS_CATALOG = "tools_catalog"
    SERVICES_CATALOG = "services_catalog"
    DATABASE_BROWSER = "database_browser"
    PLATFORM_SETTINGS = "platform_settings"
    HISTORY = "history"
    CLIENT_ONBOARDING = "client_onboarding"
    PIPELINE_VISUALIZER = "pipeline_visualizer"
    PIPELINE_MANAGER = "pipeline_manager"
    USAGE_DASHBOARD = "usage_dashboard"
    ADMIN = "admin"


class FeatureService:
    """Service for organization feature flag management."""

    def __init__(self, supabase_client: Client):
        """
        Initialize FeatureService.

        Args:
            supabase_client: Supabase client instance
        """
        self.client = supabase_client
        self._cache: dict = {}  # Simple in-memory cache

    def has_feature(self, organization_id: str, feature_key: str) -> bool:
        """
        Check if organization has a feature enabled.

        Args:
            organization_id: Organization ID (or "all" for superuser)
            feature_key: Feature to check (use FeatureKey constants)

        Returns:
            True if feature is enabled. Superusers ("all") always return True.
        """
        # Superuser mode - all features enabled
        if organization_id == "all":
            return True

        # Check cache first
        cache_key = f"{organization_id}:{feature_key}"
        if cache_key in self._cache:
            return self._cache[cache_key]

        # Query database
        try:
            result = self.client.table("org_features").select("enabled").eq(
                "organization_id", organization_id
            ).eq("feature_key", feature_key).single().execute()

            enabled = result.data.get("enabled", False) if result.data else False
        except Exception:
            # Feature not configured - default to disabled
            enabled = False

        self._cache[cache_key] = enabled
        return enabled

    def get_org_features(self, organization_id: str) -> List[dict]:
        """
        Get all feature flags for an organization.

        Args:
            organization_id: Organization ID

        Returns:
            List of feature flag dicts with feature_key, enabled, config
        """
        result = self.client.table("org_features").select("*").eq(
            "organization_id", organization_id
        ).execute()
        return result.data or []

    def set_feature(
        self,
        organization_id: str,
        feature_key: str,
        enabled: bool,
        config: dict = None
    ) -> None:
        """
        Enable or disable a feature for an organization.

        Args:
            organization_id: Organization ID
            feature_key: Feature to set
            enabled: Whether to enable or disable
            config: Optional feature-specific configuration
        """
        self.client.table("org_features").upsert({
            "organization_id": organization_id,
            "feature_key": feature_key,
            "enabled": enabled,
            "config": config or {},
            "updated_at": "now()"
        }).execute()

        # Clear cache
        cache_key = f"{organization_id}:{feature_key}"
        self._cache.pop(cache_key, None)

        logger.info(
            f"Feature {feature_key} {'enabled' if enabled else 'disabled'} "
            f"for org {organization_id}"
        )

    def enable_feature(self, organization_id: str, feature_key: str) -> None:
        """Enable a feature for an organization."""
        self.set_feature(organization_id, feature_key, True)

    def disable_feature(self, organization_id: str, feature_key: str) -> None:
        """Disable a feature for an organization."""
        self.set_feature(organization_id, feature_key, False)

    def enable_all_features(self, organization_id: str) -> None:
        """
        Enable all standard features for an organization.

        Useful when onboarding a new client with full access.
        """
        all_features = [
            # Sections
            FeatureKey.SECTION_BRANDS,
            FeatureKey.SECTION_COMPETITORS,
            FeatureKey.SECTION_ADS,
            FeatureKey.SECTION_CONTENT,
            FeatureKey.SECTION_SYSTEM,
            # Brands pages
            FeatureKey.BRAND_MANAGER,
            FeatureKey.PERSONAS,
            FeatureKey.URL_MAPPING,
            FeatureKey.BRAND_RESEARCH,
            FeatureKey.TOOL_READINESS,
            # Competitors pages
            FeatureKey.COMPETITORS,
            FeatureKey.COMPETITIVE_ANALYSIS,
            FeatureKey.COMPETITOR_RESEARCH,
            FeatureKey.REDDIT_RESEARCH,
            # Ads pages
            FeatureKey.AD_CREATOR,
            FeatureKey.AD_HISTORY,
            FeatureKey.AD_PERFORMANCE,
            FeatureKey.AD_INTELLIGENCE,
            FeatureKey.AD_SCHEDULER,
            FeatureKey.AD_PLANNING,
            FeatureKey.BELIEF_CANVAS,
            FeatureKey.RESEARCH_INSIGHTS,
            FeatureKey.CONGRUENCE_INSIGHTS,
            FeatureKey.LANDING_PAGE_ANALYZER,
            FeatureKey.HOOK_ANALYSIS,
            FeatureKey.EXPERIMENTS,
            FeatureKey.PLAN_LIST,
            FeatureKey.PLAN_EXECUTOR,
            FeatureKey.TEMPLATE_QUEUE,
            FeatureKey.TEMPLATE_EVALUATION,
            FeatureKey.TEMPLATE_RECOMMENDATIONS,
            FeatureKey.PUBLIC_GALLERY,
            # Content pages
            FeatureKey.CONTENT_PIPELINE,
            FeatureKey.COMIC_VIDEO,
            FeatureKey.COMIC_JSON_GENERATOR,
            FeatureKey.EDITOR_HANDOFF,
            FeatureKey.AUDIO_PRODUCTION,
            FeatureKey.KNOWLEDGE_BASE,
            FeatureKey.VEO_AVATARS,
            FeatureKey.SORA_MVP,
            # System pages
            FeatureKey.AGENT_CATALOG,
            FeatureKey.SCHEDULED_TASKS,
            FeatureKey.TOOLS_CATALOG,
            FeatureKey.SERVICES_CATALOG,
            FeatureKey.DATABASE_BROWSER,
            FeatureKey.PLATFORM_SETTINGS,
            FeatureKey.HISTORY,
            FeatureKey.CLIENT_ONBOARDING,
            FeatureKey.PIPELINE_VISUALIZER,
            FeatureKey.PIPELINE_MANAGER,
            FeatureKey.USAGE_DASHBOARD,
            FeatureKey.ADMIN,
        ]
        for feature in all_features:
            self.set_feature(organization_id, feature, True)

        logger.info(f"Enabled all features for org {organization_id}")

    def clear_cache(self) -> None:
        """Clear the feature cache."""
        self._cache.clear()
