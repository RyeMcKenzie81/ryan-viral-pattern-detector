"""
Article Tracking Service - CRUD and status management for SEO articles.

Handles:
- Article lifecycle (status transitions)
- Listing articles by project, status, brand
- Status aggregation for dashboards
- Content HTML management

All queries filter by organization_id for multi-tenancy.
"""

import logging
from typing import Dict, Any, Optional, List

from viraltracker.services.seo_pipeline.models import ArticleStatus

logger = logging.getLogger(__name__)

# Valid status transitions
VALID_TRANSITIONS = {
    ArticleStatus.DRAFT.value: [
        ArticleStatus.OUTLINE_COMPLETE.value,
        ArticleStatus.ARCHIVED.value,
    ],
    ArticleStatus.OUTLINE_COMPLETE.value: [
        ArticleStatus.DRAFT_COMPLETE.value,
        ArticleStatus.DRAFT.value,
    ],
    ArticleStatus.DRAFT_COMPLETE.value: [
        ArticleStatus.OPTIMIZED.value,
        ArticleStatus.DRAFT.value,
    ],
    ArticleStatus.OPTIMIZED.value: [
        ArticleStatus.QA_PENDING.value,
        ArticleStatus.DRAFT_COMPLETE.value,
    ],
    ArticleStatus.QA_PENDING.value: [
        ArticleStatus.QA_PASSED.value,
        ArticleStatus.QA_FAILED.value,
    ],
    ArticleStatus.QA_PASSED.value: [
        ArticleStatus.PUBLISHING.value,
        ArticleStatus.OPTIMIZED.value,
    ],
    ArticleStatus.QA_FAILED.value: [
        ArticleStatus.OPTIMIZED.value,
        ArticleStatus.DRAFT_COMPLETE.value,
    ],
    ArticleStatus.PUBLISHING.value: [
        ArticleStatus.PUBLISHED.value,
        ArticleStatus.QA_PASSED.value,
    ],
    ArticleStatus.PUBLISHED.value: [
        ArticleStatus.ARCHIVED.value,
    ],
    ArticleStatus.ARCHIVED.value: [
        ArticleStatus.DRAFT.value,
    ],
    ArticleStatus.DISCOVERED.value: [
        ArticleStatus.DRAFT.value,
        ArticleStatus.ARCHIVED.value,
    ],
}


class ArticleTrackingService:
    """Service for managing SEO article lifecycle and status."""

    def __init__(self, supabase_client=None):
        self._supabase = supabase_client

    @property
    def supabase(self):
        """Lazy-load Supabase client."""
        if self._supabase is None:
            from viraltracker.core.database import get_supabase_client
            self._supabase = get_supabase_client()
        return self._supabase

    # =========================================================================
    # ARTICLE CRUD
    # =========================================================================

    def get_article(self, article_id: str) -> Optional[Dict[str, Any]]:
        """Get article by ID."""
        result = (
            self.supabase.table("seo_articles")
            .select("*")
            .eq("id", article_id)
            .execute()
        )
        return result.data[0] if result.data else None

    def list_articles(
        self,
        organization_id: str,
        project_id: Optional[str] = None,
        brand_id: Optional[str] = None,
        status: Optional[str] = None,
        exclude_discovered: bool = True,
    ) -> List[Dict[str, Any]]:
        """
        List articles with optional filters.

        Args:
            organization_id: Organization UUID (or "all" for superuser)
            project_id: Filter by project
            brand_id: Filter by brand
            status: Filter by ArticleStatus value
            exclude_discovered: Exclude discovered (GSC-auto-created) articles (default True)
        """
        query = self.supabase.table("seo_articles").select("*")

        if organization_id != "all":
            query = query.eq("organization_id", organization_id)
        if project_id:
            query = query.eq("project_id", project_id)
        if brand_id:
            query = query.eq("brand_id", brand_id)
        if status:
            query = query.eq("status", status)
        elif exclude_discovered:
            query = query.neq("status", "discovered")

        result = query.order("created_at", desc=True).execute()
        return result.data or []

    def update_status(
        self,
        article_id: str,
        new_status: str,
        force: bool = False,
    ) -> Dict[str, Any]:
        """
        Update article status with transition validation.

        Args:
            article_id: Article UUID
            new_status: Target ArticleStatus value
            force: Skip transition validation (for admin overrides)

        Returns:
            Updated article dict

        Raises:
            ValueError: If transition is invalid
        """
        article = self.get_article(article_id)
        if not article:
            raise ValueError(f"Article not found: {article_id}")

        current = article.get("status", "")

        if not force:
            valid_targets = VALID_TRANSITIONS.get(current, [])
            if new_status not in valid_targets:
                raise ValueError(
                    f"Invalid status transition: {current} -> {new_status}. "
                    f"Valid transitions from '{current}': {valid_targets}"
                )

        result = (
            self.supabase.table("seo_articles")
            .update({"status": new_status})
            .eq("id", article_id)
            .execute()
        )

        logger.info(f"Article {article_id} status: {current} -> {new_status}")
        return result.data[0] if result.data else {"id": article_id, "status": new_status}

    def update_article(
        self,
        article_id: str,
        **updates,
    ) -> Optional[Dict[str, Any]]:
        """
        Update article fields.

        Args:
            article_id: Article UUID
            **updates: Fields to update (title, seo_title, meta_description, etc.)
        """
        if not updates:
            return self.get_article(article_id)

        result = (
            self.supabase.table("seo_articles")
            .update(updates)
            .eq("id", article_id)
            .execute()
        )
        return result.data[0] if result.data else None

    # =========================================================================
    # DASHBOARD AGGREGATES
    # =========================================================================

    def get_status_counts(
        self,
        organization_id: str,
        project_id: Optional[str] = None,
        brand_id: Optional[str] = None,
    ) -> Dict[str, int]:
        """
        Get article count by status for dashboard KPIs.

        Returns:
            Dict mapping status -> count
        """
        articles = self.list_articles(
            organization_id=organization_id,
            project_id=project_id,
            brand_id=brand_id,
        )

        counts = {}
        for article in articles:
            status = article.get("status", "unknown")
            counts[status] = counts.get(status, 0) + 1

        return counts

    def get_project_summary(
        self,
        project_id: str,
        organization_id: str,
    ) -> Dict[str, Any]:
        """
        Get project-level summary for dashboard.

        Returns:
            Dict with total_articles, status_counts, published_count,
            latest_article
        """
        articles = self.list_articles(
            organization_id=organization_id,
            project_id=project_id,
        )

        status_counts = {}
        for a in articles:
            s = a.get("status", "unknown")
            status_counts[s] = status_counts.get(s, 0) + 1

        published = [a for a in articles if a.get("status") == ArticleStatus.PUBLISHED.value]

        return {
            "project_id": project_id,
            "total_articles": len(articles),
            "status_counts": status_counts,
            "published_count": len(published),
            "latest_article": articles[0] if articles else None,
        }
