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
    """
    AD_CREATOR = "ad_creator"
    AD_LIBRARY = "ad_library"
    AD_SCHEDULER = "ad_scheduler"
    AD_PLANNING = "ad_planning"
    VEO_AVATARS = "veo_avatars"
    COMPETITOR_RESEARCH = "competitor_research"
    REDDIT_RESEARCH = "reddit_research"
    BRAND_RESEARCH = "brand_research"
    BELIEF_CANVAS = "belief_canvas"
    CONTENT_PIPELINE = "content_pipeline"
    RESEARCH_INSIGHTS = "research_insights"


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
        ]
        for feature in all_features:
            self.set_feature(organization_id, feature, True)

        logger.info(f"Enabled all features for org {organization_id}")

    def clear_cache(self) -> None:
        """Clear the feature cache."""
        self._cache.clear()
