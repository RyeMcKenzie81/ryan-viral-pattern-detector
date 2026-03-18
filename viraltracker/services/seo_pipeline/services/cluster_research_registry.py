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
        self.register(
            "people_also_ask",
            self._fetch_paa_questions,
            "People Also Ask questions from Google SERPs (DataForSEO)",
        )
        self.register(
            "competitor_keywords",
            self._fetch_competitor_gap_keywords,
            "Keywords competitors rank for that you don't cover (DataForSEO)",
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

    def _fetch_paa_questions(
        self,
        brand_id: str,
        organization_id: str,
        seeds: List[str],
    ) -> List[str]:
        """Fetch People Also Ask questions for seed keywords via DataForSEO."""
        from viraltracker.services.seo_pipeline.services.dataforseo_service import DataForSEOService

        dataforseo = DataForSEOService(supabase_client=self._supabase)
        if not dataforseo._available:
            logger.info("DataForSEO not configured — skipping PAA source")
            return []

        questions = []
        for seed in seeds[:10]:  # Limit to 10 seeds (~$0.01 total)
            paa = dataforseo.fetch_people_also_ask(seed, depth=2)
            questions.extend(paa)

        # Dedup
        seen: set = set()
        unique = []
        for q in questions:
            key = q.lower().strip()
            if key not in seen:
                seen.add(key)
                unique.append(q)

        logger.info(f"PAA source returned {len(unique)} unique questions from {min(len(seeds), 10)} seeds")
        return unique

    def _fetch_competitor_gap_keywords(
        self,
        brand_id: str,
        organization_id: str,
        seeds: List[str],
    ) -> List[str]:
        """
        Find keywords competitors rank for that we don't cover.

        1. Get competitor domains from seo_competitor_analyses
        2. Fetch their organic keywords via DataForSEO
        3. Filter out keywords we already have (embedding similarity >= 0.50)
        4. Return gap keywords
        """
        from viraltracker.services.seo_pipeline.services.dataforseo_service import DataForSEOService

        dataforseo = DataForSEOService(supabase_client=self._supabase)
        if not dataforseo._available:
            logger.info("DataForSEO not configured — skipping competitor keywords source")
            return []

        # Get competitor domains from existing analyses
        comp_result = (
            self.supabase.table("seo_competitor_analyses")
            .select("competitor_domain")
            .eq("brand_id", brand_id)
            .limit(5)
            .execute()
        )
        domains = list({
            r["competitor_domain"] for r in (comp_result.data or [])
            if r.get("competitor_domain")
        })

        if not domains:
            logger.info("No competitor domains found — skipping competitor keywords source")
            return []

        # Fetch competitor keywords
        competitor_keywords = []
        for domain in domains[:3]:  # Limit to 3 domains
            kws = dataforseo.get_competitor_keywords(domain, limit=200)
            competitor_keywords.extend(kw.get("keyword", "") for kw in kws if kw.get("keyword"))

        if not competitor_keywords:
            return []

        # Get our existing keyword embeddings for gap detection
        existing = (
            self.supabase.table("seo_keywords")
            .select("keyword, embedding")
            .eq("project_id", self._get_project_id(brand_id))
            .execute()
        ).data or [] if self._get_project_id(brand_id) else []

        existing_embeddings = [
            (r["keyword"], r["embedding"])
            for r in existing
            if r.get("embedding")
        ]

        # Batch embed competitor keywords for comparison
        gap_keywords = []
        if existing_embeddings:
            try:
                from viraltracker.core.embeddings import create_seo_embedder, cosine_similarity as _cosine
                embedder = create_seo_embedder()
                comp_vecs = embedder.embed_texts(competitor_keywords[:500], task_type="CLUSTERING")

                for comp_kw, comp_vec in zip(competitor_keywords[:500], comp_vecs):
                    max_sim = max(
                        (_cosine(comp_vec, ex_emb) for _, ex_emb in existing_embeddings),
                        default=0.0,
                    )
                    if max_sim < 0.50:
                        gap_keywords.append(comp_kw)
            except Exception as e:
                logger.warning(f"Embedding-based gap detection failed, using text dedup: {e}")
                # Fallback: simple text dedup
                existing_set = {r["keyword"].lower() for r in existing}
                gap_keywords = [kw for kw in competitor_keywords if kw.lower() not in existing_set]
        else:
            # No embeddings — simple text dedup
            existing_set = {r["keyword"].lower() for r in existing}
            gap_keywords = [kw for kw in competitor_keywords if kw.lower() not in existing_set]

        # Dedup
        seen: set = set()
        unique = []
        for kw in gap_keywords:
            key = kw.lower().strip()
            if key not in seen:
                seen.add(key)
                unique.append(kw)

        logger.info(f"Competitor gap source returned {len(unique)} gap keywords from {len(domains)} domains")
        return unique[:200]

    def _get_project_id(self, brand_id: str) -> Optional[str]:
        """Get SEO project ID for a brand."""
        result = (
            self.supabase.table("seo_projects")
            .select("id")
            .eq("brand_id", brand_id)
            .limit(1)
            .execute()
        )
        return result.data[0]["id"] if result.data else None
