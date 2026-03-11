"""
Cluster Research Registry — extensible registry of keyword/topic research sources.

Built-in sources:
- google_autocomplete: Google Autocomplete keyword discovery
- gsc_queries: GSC search queries (high-impression, page-2 opportunities)

To add a new source:
    registry.register("ahrefs", ahrefs_keyword_fetcher, "Ahrefs keyword data")
"""

import logging
from typing import Any, Callable, Dict, List, Optional

logger = logging.getLogger(__name__)


class ClusterResearchRegistry:
    """Extensible registry of keyword/topic research sources."""

    def __init__(self, supabase_client=None):
        self._supabase = supabase_client
        self._sources: Dict[str, Dict[str, Any]] = {}
        self._register_builtins()

    @property
    def supabase(self):
        if self._supabase is None:
            from viraltracker.core.database import get_supabase_client
            self._supabase = get_supabase_client()
        return self._supabase

    def register(self, name: str, fetcher: Callable, description: str = "") -> None:
        """
        Register a research source.

        Fetcher signature: (brand_id, org_id, seeds: List[str]) -> List[str]
        """
        self._sources[name] = {"fetcher": fetcher, "description": description}

    def get_sources(self) -> List[Dict[str, str]]:
        """List available sources with descriptions."""
        return [{"name": k, "description": v["description"]} for k, v in self._sources.items()]

    def fetch_from(
        self,
        source_name: str,
        brand_id: str,
        organization_id: str,
        seeds: List[str],
    ) -> List[str]:
        """Fetch keywords from a specific source."""
        if source_name not in self._sources:
            raise ValueError(f"Unknown research source: {source_name}")
        fetcher = self._sources[source_name]["fetcher"]
        try:
            return fetcher(brand_id, organization_id, seeds)
        except Exception as e:
            logger.warning(f"Research source '{source_name}' failed: {e}")
            return []

    def fetch_all(
        self,
        brand_id: str,
        organization_id: str,
        seeds: List[str],
        sources: Optional[List[str]] = None,
    ) -> Dict[str, List[str]]:
        """
        Fetch from multiple sources, return per-source results.

        Args:
            brand_id: Brand UUID
            organization_id: Org UUID
            seeds: Seed keywords to expand
            sources: Source names to use (default: all)

        Returns:
            Dict mapping source name to keyword list
        """
        source_names = sources or list(self._sources.keys())
        results = {}
        seen = set()

        for name in source_names:
            if name not in self._sources:
                logger.warning(f"Skipping unknown research source: {name}")
                continue
            keywords = self.fetch_from(name, brand_id, organization_id, seeds)
            # Dedup across sources
            unique = [kw for kw in keywords if kw.lower() not in seen]
            for kw in unique:
                seen.add(kw.lower())
            results[name] = unique

        return results

    def _register_builtins(self) -> None:
        """Register built-in research sources."""
        self.register(
            "google_autocomplete",
            self._fetch_google_autocomplete,
            "Google Autocomplete keyword suggestions",
        )
        self.register(
            "gsc_queries",
            self._fetch_gsc_queries,
            "High-impression GSC queries and page-2 opportunities",
        )

    def _fetch_google_autocomplete(
        self,
        brand_id: str,
        organization_id: str,
        seeds: List[str],
    ) -> List[str]:
        """Fetch keywords via Google Autocomplete (KeywordDiscoveryService)."""
        import asyncio
        from viraltracker.services.seo_pipeline.services.keyword_discovery_service import KeywordDiscoveryService

        # Need a project_id — look for existing or skip
        projects = (
            self.supabase.table("seo_projects")
            .select("id")
            .eq("brand_id", brand_id)
            .limit(1)
            .execute()
        ).data or []

        if not projects:
            logger.info("No project for google_autocomplete source — skipping")
            return seeds  # Return seeds unchanged

        project_id = projects[0]["id"]
        svc = KeywordDiscoveryService(supabase_client=self.supabase)

        # discover_keywords is async
        try:
            result = asyncio.get_event_loop().run_until_complete(
                svc.discover_keywords(project_id, seeds)
            )
        except RuntimeError:
            # No running event loop — create one
            result = asyncio.run(
                svc.discover_keywords(project_id, seeds)
            )

        keywords = [kw.get("keyword", "") for kw in (result.get("keywords") or [])]
        return [kw for kw in keywords if kw]

    def _fetch_gsc_queries(
        self,
        brand_id: str,
        organization_id: str,
        seeds: List[str],
    ) -> List[str]:
        """Fetch high-impression GSC queries as research input."""
        # Query ranking data for this brand's articles
        articles = (
            self.supabase.table("seo_articles")
            .select("id")
            .eq("brand_id", brand_id)
            .limit(100)
            .execute()
        ).data or []

        if not articles:
            return []

        article_ids = [a["id"] for a in articles[:50]]

        # Get GSC ranking keywords sorted by impressions
        rankings = (
            self.supabase.table("seo_article_rankings")
            .select("keyword, impressions")
            .in_("article_id", article_ids)
            .order("impressions", desc=True)
            .limit(200)
            .execute()
        ).data or []

        seen = set()
        keywords = []
        for r in rankings:
            kw = r.get("keyword", "").strip()
            if kw and kw.lower() not in seen:
                seen.add(kw.lower())
                keywords.append(kw)

        return keywords[:100]
