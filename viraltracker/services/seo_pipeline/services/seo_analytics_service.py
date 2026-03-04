"""
SEO Analytics Service - Ranking history and project-level analytics.

Handles:
- Recording keyword ranking positions
- Retrieving ranking history per article
- Project-level dashboard analytics (aggregated KPIs)
- Internal link statistics

All queries filter by organization_id for multi-tenancy.
"""

import logging
from datetime import datetime, timedelta, timezone
from typing import Dict, Any, Optional, List

logger = logging.getLogger(__name__)


class SEOAnalyticsService:
    """Service for SEO ranking tracking and analytics."""

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
    # RANKING TRACKING
    # =========================================================================

    def record_ranking(
        self,
        article_id: str,
        keyword: str,
        position: int,
        checked_at: Optional[str] = None,
    ) -> Dict[str, Any]:
        """
        Record a keyword ranking data point.

        Args:
            article_id: Article UUID
            keyword: Keyword being tracked
            position: SERP position (1-100+)
            checked_at: ISO timestamp (defaults to now)

        Returns:
            Created ranking record
        """
        data = {
            "article_id": article_id,
            "keyword": keyword,
            "position": position,
        }
        if checked_at:
            data["checked_at"] = checked_at

        result = self.supabase.table("seo_article_rankings").insert(data).execute()
        logger.info(f"Recorded ranking: article={article_id[:8]}... keyword='{keyword}' position={position}")
        return result.data[0] if result.data else data

    def get_ranking_history(
        self,
        article_id: str,
        keyword: Optional[str] = None,
        days: int = 30,
    ) -> List[Dict[str, Any]]:
        """
        Get ranking history for an article.

        Args:
            article_id: Article UUID
            keyword: Optional keyword filter (all keywords if omitted)
            days: Number of days to look back (default: 30)

        Returns:
            List of ranking records ordered by checked_at descending
        """
        since = (datetime.now(timezone.utc) - timedelta(days=days)).isoformat()

        query = (
            self.supabase.table("seo_article_rankings")
            .select("*")
            .eq("article_id", article_id)
            .gte("checked_at", since)
        )
        if keyword:
            query = query.eq("keyword", keyword)

        result = query.order("checked_at", desc=True).execute()
        return result.data or []

    def get_latest_rankings(
        self,
        project_id: str,
        organization_id: str,
    ) -> List[Dict[str, Any]]:
        """
        Get the latest ranking for each article in a project.

        Fetches all articles in the project, then gets the most recent
        ranking for each.

        Args:
            project_id: SEO project UUID
            organization_id: Org UUID for access control

        Returns:
            List of dicts with article_id, keyword, position, checked_at
        """
        # Get articles for the project
        query = (
            self.supabase.table("seo_articles")
            .select("id, keyword")
            .eq("project_id", project_id)
        )
        if organization_id != "all":
            query = query.eq("organization_id", organization_id)
        articles = query.execute().data or []

        rankings = []
        for article in articles:
            history = self.get_ranking_history(article["id"], days=90)
            if history:
                latest = history[0]
                rankings.append({
                    "article_id": article["id"],
                    "keyword": article.get("keyword", latest.get("keyword", "")),
                    "position": latest.get("position"),
                    "checked_at": latest.get("checked_at"),
                })

        return rankings

    # =========================================================================
    # PROJECT DASHBOARD
    # =========================================================================

    def _get_link_stats_batch(self, article_ids: List[str]) -> Dict[str, int]:
        """Get internal link stats using batch .in_() query instead of N+1 loop."""
        link_stats = {"suggested": 0, "implemented": 0, "total": 0}
        if not article_ids:
            return link_stats

        # Batch query: up to 50 article IDs at once
        batch_ids = article_ids[:50]
        link_query = (
            self.supabase.table("seo_internal_links")
            .select("id, status")
            .in_("source_article_id", batch_ids)
        )
        links = link_query.execute().data or []
        for link in links:
            link_stats["total"] += 1
            if link.get("status") == "implemented":
                link_stats["implemented"] += 1
            elif link.get("status") == "pending":
                link_stats["suggested"] += 1

        return link_stats

    def get_project_dashboard(
        self,
        project_id: str,
        organization_id: str,
    ) -> Dict[str, Any]:
        """
        Get comprehensive project dashboard analytics.

        Returns:
            Dict with:
            - total_articles, status_counts, published_count
            - total_keywords, selected_keywords
            - internal_links (suggested, implemented)
        """
        # Article stats
        article_query = (
            self.supabase.table("seo_articles")
            .select("id, keyword, status, published_url, cms_article_id")
            .eq("project_id", project_id)
        )
        if organization_id != "all":
            article_query = article_query.eq("organization_id", organization_id)
        articles = article_query.execute().data or []

        status_counts = {}
        for a in articles:
            s = a.get("status", "unknown")
            status_counts[s] = status_counts.get(s, 0) + 1

        published = [a for a in articles if a.get("published_url")]

        # Keyword stats
        keyword_query = (
            self.supabase.table("seo_keywords")
            .select("id, status")
            .eq("project_id", project_id)
        )
        keywords = keyword_query.execute().data or []
        keyword_status = {}
        for k in keywords:
            s = k.get("status", "unknown")
            keyword_status[s] = keyword_status.get(s, 0) + 1

        # Internal link stats — batch query
        article_ids = [a["id"] for a in articles]
        link_stats = self._get_link_stats_batch(article_ids)

        return {
            "project_id": project_id,
            "articles": {
                "total": len(articles),
                "published": len(published),
                "status_counts": status_counts,
            },
            "keywords": {
                "total": len(keywords),
                "status_counts": keyword_status,
            },
            "links": link_stats,
        }

    def get_brand_dashboard(
        self,
        brand_id: str,
        organization_id: str,
    ) -> Dict[str, Any]:
        """
        Get brand-level dashboard aggregated across all projects.

        Returns zero-state dict when no projects exist (never errors).

        Returns:
            Dict with articles, keywords, links, projects counts
        """
        zero_state = {
            "articles": {"total": 0, "published": 0, "status_counts": {}},
            "keywords": {"total": 0, "status_counts": {}},
            "links": {"suggested": 0, "implemented": 0, "total": 0},
            "projects": {"total": 0, "active": 0},
        }

        # Get projects for brand
        project_query = (
            self.supabase.table("seo_projects")
            .select("id, status")
            .eq("brand_id", brand_id)
        )
        if organization_id != "all":
            project_query = project_query.eq("organization_id", organization_id)
        projects = project_query.execute().data or []

        if not projects:
            return zero_state

        project_ids = [p["id"] for p in projects]
        active_projects = [p for p in projects if p.get("status") != "archived"]

        # Articles by brand_id (seo_articles has brand_id column)
        article_query = (
            self.supabase.table("seo_articles")
            .select("id, keyword, status, published_url")
            .eq("brand_id", brand_id)
        )
        if organization_id != "all":
            article_query = article_query.eq("organization_id", organization_id)
        articles = article_query.execute().data or []

        status_counts = {}
        for a in articles:
            s = a.get("status", "unknown")
            status_counts[s] = status_counts.get(s, 0) + 1
        published = [a for a in articles if a.get("published_url")]

        # Keywords — batch by project IDs
        keyword_query = (
            self.supabase.table("seo_keywords")
            .select("id, status")
            .in_("project_id", project_ids)
        )
        keywords = keyword_query.execute().data or []
        keyword_status = {}
        for k in keywords:
            s = k.get("status", "unknown")
            keyword_status[s] = keyword_status.get(s, 0) + 1

        # Internal links — batch by article IDs
        article_ids = [a["id"] for a in articles]
        link_stats = self._get_link_stats_batch(article_ids)

        return {
            "articles": {
                "total": len(articles),
                "published": len(published),
                "status_counts": status_counts,
            },
            "keywords": {
                "total": len(keywords),
                "status_counts": keyword_status,
            },
            "links": link_stats,
            "projects": {
                "total": len(projects),
                "active": len(active_projects),
            },
        }
