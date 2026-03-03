"""
SEO Project Service - Project CRUD, brand integrations, and author management.

Handles:
- SEO project lifecycle (create, list, update, delete)
- Brand integration configuration (Shopify, etc.)
- Author CRUD (create, list, set default, get with persona)

All queries filter by organization_id for multi-tenancy.
"""

import logging
from typing import Optional, List, Dict, Any

from viraltracker.services.seo_pipeline.models import ProjectStatus

logger = logging.getLogger(__name__)


class SEOProjectService:
    """Service for managing SEO projects, integrations, and authors."""

    def __init__(self, supabase_client=None):
        """
        Initialize with Supabase client.

        Args:
            supabase_client: Supabase client instance. If None, will be
                created from environment on first use.
        """
        self._supabase = supabase_client

    @property
    def supabase(self):
        """Lazy-load Supabase client."""
        if self._supabase is None:
            from viraltracker.core.database import get_supabase_client
            self._supabase = get_supabase_client()
        return self._supabase

    # =========================================================================
    # PROJECT CRUD
    # =========================================================================

    def create_project(
        self,
        brand_id: str,
        organization_id: str,
        name: str,
        config: Optional[Dict[str, Any]] = None,
    ) -> Dict[str, Any]:
        """
        Create a new SEO project for a brand.

        Args:
            brand_id: Brand UUID
            organization_id: Organization UUID for multi-tenancy
            name: Project name
            config: Optional JSONB configuration

        Returns:
            Created project record
        """
        data = {
            "brand_id": brand_id,
            "organization_id": organization_id,
            "name": name,
            "status": ProjectStatus.ACTIVE.value,
            "config": config or {},
        }
        result = self.supabase.table("seo_projects").insert(data).execute()
        logger.info(f"Created SEO project '{name}' for brand {brand_id}")
        return result.data[0]

    def list_projects(
        self,
        organization_id: str,
        brand_id: Optional[str] = None,
        status: Optional[str] = None,
    ) -> List[Dict[str, Any]]:
        """
        List SEO projects filtered by organization and optionally brand.

        Args:
            organization_id: Organization UUID (or "all" for superuser)
            brand_id: Optional brand UUID filter
            status: Optional ProjectStatus value filter

        Returns:
            List of project records

        Raises:
            ValueError: If status is not a valid ProjectStatus value
        """
        if status:
            valid = {s.value for s in ProjectStatus}
            if status not in valid:
                raise ValueError(
                    f"Invalid project status: '{status}'. "
                    f"Valid values: {sorted(valid)}"
                )

        query = self.supabase.table("seo_projects").select("*")

        if organization_id != "all":
            query = query.eq("organization_id", organization_id)

        if brand_id:
            query = query.eq("brand_id", brand_id)

        if status:
            query = query.eq("status", status)

        query = query.order("created_at", desc=True)
        result = query.execute()
        return result.data

    def get_project(self, project_id: str, organization_id: str) -> Optional[Dict[str, Any]]:
        """
        Get a single SEO project by ID.

        Args:
            project_id: Project UUID
            organization_id: Organization UUID for access control

        Returns:
            Project record or None
        """
        query = self.supabase.table("seo_projects").select("*").eq("id", project_id)

        if organization_id != "all":
            query = query.eq("organization_id", organization_id)

        result = query.execute()
        return result.data[0] if result.data else None

    def update_project(
        self,
        project_id: str,
        organization_id: str,
        **updates,
    ) -> Optional[Dict[str, Any]]:
        """
        Update an SEO project.

        Args:
            project_id: Project UUID
            organization_id: Organization UUID for access control
            **updates: Fields to update

        Returns:
            Updated project record or None
        """
        query = self.supabase.table("seo_projects").update(updates).eq("id", project_id)

        if organization_id != "all":
            query = query.eq("organization_id", organization_id)

        result = query.execute()
        return result.data[0] if result.data else None

    def update_workflow_state(
        self,
        project_id: str,
        workflow_state: str,
        workflow_data: Dict[str, Any],
    ) -> None:
        """
        Update the workflow state and data for a project.

        Args:
            project_id: Project UUID
            workflow_state: Current workflow step name
            workflow_data: Serialized pipeline state dict
        """
        self.supabase.table("seo_projects").update({
            "workflow_state": workflow_state,
            "workflow_data": workflow_data,
        }).eq("id", project_id).execute()
        logger.info(f"Updated workflow state for project {project_id}: {workflow_state}")

    # =========================================================================
    # BRAND INTEGRATIONS
    # =========================================================================

    def get_brand_integration(
        self,
        brand_id: str,
        organization_id: str,
        platform: str = "shopify",
    ) -> Optional[Dict[str, Any]]:
        """
        Get CMS integration config for a brand.

        Args:
            brand_id: Brand UUID
            organization_id: Organization UUID for access control
            platform: CMS platform name (e.g., "shopify")

        Returns:
            Integration record with config JSONB, or None
        """
        query = (
            self.supabase.table("brand_integrations")
            .select("*")
            .eq("brand_id", brand_id)
            .eq("platform", platform)
        )

        if organization_id != "all":
            query = query.eq("organization_id", organization_id)

        result = query.execute()
        return result.data[0] if result.data else None

    def upsert_brand_integration(
        self,
        brand_id: str,
        organization_id: str,
        platform: str,
        config: Dict[str, Any],
    ) -> Dict[str, Any]:
        """
        Create or update a brand integration.

        Args:
            brand_id: Brand UUID
            organization_id: Organization UUID
            platform: CMS platform name
            config: JSONB configuration (credentials, settings)

        Returns:
            Upserted integration record
        """
        data = {
            "brand_id": brand_id,
            "organization_id": organization_id,
            "platform": platform,
            "config": config,
        }
        result = (
            self.supabase.table("brand_integrations")
            .upsert(data, on_conflict="brand_id,platform")
            .execute()
        )
        logger.info(f"Upserted {platform} integration for brand {brand_id}")
        return result.data[0]

    # =========================================================================
    # AUTHOR CRUD
    # =========================================================================

    def create_author(
        self,
        brand_id: str,
        organization_id: str,
        name: str,
        bio: Optional[str] = None,
        image_url: Optional[str] = None,
        job_title: Optional[str] = None,
        author_url: Optional[str] = None,
        persona_id: Optional[str] = None,
        schema_data: Optional[Dict[str, Any]] = None,
        is_default: bool = False,
    ) -> Dict[str, Any]:
        """
        Create a new author for a brand.

        If is_default is True, unsets any existing default author first.

        Args:
            brand_id: Brand UUID
            organization_id: Organization UUID
            name: Author display name
            bio: Author bio text
            image_url: Headshot URL
            job_title: e.g., "Co-Founder"
            author_url: About page link
            persona_id: Optional link to personas_4d for voice/style
            schema_data: Pre-built Article schema author object
            is_default: Whether this is the default author for the brand

        Returns:
            Created author record
        """
        if is_default:
            self._unset_default_author(brand_id, organization_id)

        data = {
            "brand_id": brand_id,
            "organization_id": organization_id,
            "name": name,
            "bio": bio,
            "image_url": image_url,
            "job_title": job_title,
            "author_url": author_url,
            "persona_id": persona_id,
            "schema_data": schema_data,
            "is_default": is_default,
        }
        # Remove None values to let DB defaults apply
        data = {k: v for k, v in data.items() if v is not None}
        # But always include is_default
        data["is_default"] = is_default

        result = self.supabase.table("seo_authors").insert(data).execute()
        logger.info(f"Created author '{name}' for brand {brand_id}")
        return result.data[0]

    def list_authors(
        self,
        brand_id: str,
        organization_id: str,
    ) -> List[Dict[str, Any]]:
        """
        List all authors for a brand.

        Args:
            brand_id: Brand UUID
            organization_id: Organization UUID for access control

        Returns:
            List of author records, default author first
        """
        query = (
            self.supabase.table("seo_authors")
            .select("*")
            .eq("brand_id", brand_id)
        )

        if organization_id != "all":
            query = query.eq("organization_id", organization_id)

        query = query.order("is_default", desc=True).order("created_at")
        result = query.execute()
        return result.data

    def get_author(
        self,
        author_id: str,
        organization_id: str,
    ) -> Optional[Dict[str, Any]]:
        """
        Get an author by ID with optional persona data.

        Args:
            author_id: Author UUID
            organization_id: Organization UUID for access control

        Returns:
            Author record or None
        """
        query = (
            self.supabase.table("seo_authors")
            .select("*")
            .eq("id", author_id)
        )

        if organization_id != "all":
            query = query.eq("organization_id", organization_id)

        result = query.execute()
        return result.data[0] if result.data else None

    def get_default_author(
        self,
        brand_id: str,
        organization_id: str,
    ) -> Optional[Dict[str, Any]]:
        """
        Get the default author for a brand.

        Args:
            brand_id: Brand UUID
            organization_id: Organization UUID for access control

        Returns:
            Default author record, or first author, or None
        """
        authors = self.list_authors(brand_id, organization_id)
        if not authors:
            return None

        # Return the default author (sorted first) or first author
        for author in authors:
            if author.get("is_default"):
                return author
        return authors[0]

    def set_default_author(
        self,
        author_id: str,
        brand_id: str,
        organization_id: str,
    ) -> Optional[Dict[str, Any]]:
        """
        Set an author as the default for their brand.

        Args:
            author_id: Author UUID to make default
            brand_id: Brand UUID
            organization_id: Organization UUID

        Returns:
            Updated author record or None
        """
        self._unset_default_author(brand_id, organization_id)

        result = (
            self.supabase.table("seo_authors")
            .update({"is_default": True})
            .eq("id", author_id)
            .eq("brand_id", brand_id)
            .execute()
        )
        logger.info(f"Set author {author_id} as default for brand {brand_id}")
        return result.data[0] if result.data else None

    def update_author(
        self,
        author_id: str,
        organization_id: str,
        **updates,
    ) -> Optional[Dict[str, Any]]:
        """
        Update an author's fields.

        Args:
            author_id: Author UUID
            organization_id: Organization UUID for access control
            **updates: Fields to update

        Returns:
            Updated author record or None
        """
        query = (
            self.supabase.table("seo_authors")
            .update(updates)
            .eq("id", author_id)
        )

        if organization_id != "all":
            query = query.eq("organization_id", organization_id)

        result = query.execute()
        return result.data[0] if result.data else None

    def _unset_default_author(self, brand_id: str, organization_id: str) -> None:
        """Unset any existing default author for a brand."""
        query = (
            self.supabase.table("seo_authors")
            .update({"is_default": False})
            .eq("brand_id", brand_id)
            .eq("is_default", True)
        )

        if organization_id != "all":
            query = query.eq("organization_id", organization_id)

        query.execute()
