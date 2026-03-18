"""
DataForSEO Service — keyword data, PAA, and competitor keyword analysis.

External API wrapper following the same pattern as GSCService.
Requires DATAFORSEO_LOGIN and DATAFORSEO_PASSWORD env vars.
Degrades gracefully when credentials are missing.

Endpoints used:
- keywords_data/clickstream_data/bulk_search_volume/live — search volume
- dataforseo_labs/google/bulk_keyword_difficulty/live — keyword difficulty
- serp/google/organic/live/advanced — People Also Ask questions
- dataforseo_labs/google/ranked_keywords/live — competitor organic keywords
"""

import logging
import os
from typing import Any, Dict, List, Optional

import httpx

logger = logging.getLogger(__name__)

BASE_URL = "https://api.dataforseo.com/v3"


class DataForSEOService:
    """DataForSEO API wrapper for keyword data, PAA, and competitor analysis."""

    def __init__(self, supabase_client=None):
        self._supabase = supabase_client
        self._login = os.getenv("DATAFORSEO_LOGIN", "")
        self._password = os.getenv("DATAFORSEO_PASSWORD", "")

    @property
    def supabase(self):
        if self._supabase is None:
            from viraltracker.core.database import get_supabase_client
            self._supabase = get_supabase_client()
        return self._supabase

    @property
    def _available(self) -> bool:
        return bool(self._login and self._password)

    @property
    def _auth(self) -> tuple:
        return (self._login, self._password)

    def _post(self, endpoint: str, payload: List[Dict]) -> Dict[str, Any]:
        """Make a POST request to DataForSEO API."""
        if not self._available:
            raise RuntimeError("DataForSEO credentials not configured (DATAFORSEO_LOGIN/DATAFORSEO_PASSWORD)")

        url = f"{BASE_URL}/{endpoint}"
        with httpx.Client(timeout=30.0) as client:
            resp = client.post(url, json=payload, auth=self._auth)
            resp.raise_for_status()
            data = resp.json()

        if data.get("status_code") != 20000:
            msg = data.get("status_message", "Unknown error")
            raise RuntimeError(f"DataForSEO error: {msg}")

        return data

    # =========================================================================
    # VOLUME + DIFFICULTY ENRICHMENT
    # =========================================================================

    def enrich_keywords_bulk(
        self,
        keyword_texts: List[str],
        location_code: int = 2840,
        language_code: str = "en",
    ) -> List[Dict[str, Any]]:
        """
        Fetch search volume + keyword difficulty for up to 1,000 keywords.

        Two API calls:
        1. clickstream_data/bulk_search_volume/live → search_volume
        2. dataforseo_labs/google/bulk_keyword_difficulty/live → keyword_difficulty

        Args:
            keyword_texts: List of keyword strings (max 1,000)
            location_code: Geo location (default: 2840 = US)
            language_code: Language code (default: "en")

        Returns:
            List of dicts: [{keyword, search_volume, keyword_difficulty}, ...]
        """
        if not self._available:
            logger.warning("DataForSEO not configured — skipping keyword enrichment")
            return []

        if not keyword_texts:
            return []

        # Cap at 1,000 per API limit
        keywords = [kw.lower() for kw in keyword_texts[:1000]]

        # Merge results from both endpoints
        results: Dict[str, Dict] = {kw: {"keyword": kw} for kw in keywords}

        # 1. Search volume
        try:
            vol_data = self._post(
                "keywords_data/clickstream_data/bulk_search_volume/live",
                [{"keywords": keywords, "location_code": location_code}],
            )
            for task in vol_data.get("tasks", []):
                for result_block in (task.get("result") or []):
                    for item in (result_block.get("items") or []):
                        kw = item.get("keyword", "").lower()
                        if kw in results:
                            results[kw]["search_volume"] = item.get("search_volume")
        except Exception as e:
            logger.warning(f"DataForSEO search volume failed: {e}")

        # 2. Keyword difficulty
        try:
            kd_data = self._post(
                "dataforseo_labs/google/bulk_keyword_difficulty/live",
                [{
                    "keywords": keywords,
                    "location_code": location_code,
                    "language_code": language_code,
                }],
            )
            for task in kd_data.get("tasks", []):
                for result_block in (task.get("result") or []):
                    for item in (result_block.get("items") or []):
                        kw = item.get("keyword", "").lower()
                        if kw in results:
                            results[kw]["keyword_difficulty"] = item.get("keyword_difficulty")
        except Exception as e:
            logger.warning(f"DataForSEO keyword difficulty failed: {e}")

        return list(results.values())

    # =========================================================================
    # PEOPLE ALSO ASK
    # =========================================================================

    def fetch_people_also_ask(
        self,
        keyword: str,
        depth: int = 2,
        location_code: int = 2840,
        language_code: str = "en",
    ) -> List[str]:
        """
        Extract People Also Ask questions from Google SERP.

        Args:
            keyword: Seed keyword to query
            depth: PAA click depth for expansion (default: 2)
            location_code: Geo location (default: 2840 = US)
            language_code: Language code (default: "en")

        Returns:
            List of PAA question strings
        """
        if not self._available:
            logger.warning("DataForSEO not configured — skipping PAA fetch")
            return []

        try:
            data = self._post(
                "serp/google/organic/live/advanced",
                [{
                    "keyword": keyword,
                    "location_code": location_code,
                    "language_code": language_code,
                    "people_also_ask_click_depth": depth,
                }],
            )
        except Exception as e:
            logger.warning(f"DataForSEO PAA fetch failed for '{keyword}': {e}")
            return []

        questions = []
        for task in data.get("tasks", []):
            for result_block in (task.get("result") or []):
                for item in (result_block.get("items") or []):
                    if item.get("type") == "people_also_ask":
                        for paa_item in (item.get("items") or []):
                            title = paa_item.get("title", "").strip()
                            if title:
                                questions.append(title)

        return questions

    # =========================================================================
    # COMPETITOR KEYWORDS
    # =========================================================================

    def get_competitor_keywords(
        self,
        domain: str,
        limit: int = 500,
        location_code: int = 2840,
        language_code: str = "en",
    ) -> List[Dict[str, Any]]:
        """
        Get organic keywords a competitor domain ranks for.

        Args:
            domain: Competitor domain (e.g. "competitor.com")
            limit: Max keywords to return (default: 500)
            location_code: Geo location (default: 2840 = US)
            language_code: Language code (default: "en")

        Returns:
            List of dicts: [{keyword, position, search_volume, etv}, ...]
        """
        if not self._available:
            logger.warning("DataForSEO not configured — skipping competitor keywords")
            return []

        try:
            data = self._post(
                "dataforseo_labs/google/ranked_keywords/live",
                [{
                    "target": domain,
                    "location_code": location_code,
                    "language_code": language_code,
                    "limit": min(limit, 1000),
                }],
            )
        except Exception as e:
            logger.warning(f"DataForSEO competitor keywords failed for '{domain}': {e}")
            return []

        keywords = []
        for task in data.get("tasks", []):
            for result_block in (task.get("result") or []):
                for item in (result_block.get("items") or []):
                    kw_data = item.get("keyword_data") or {}
                    ranked = item.get("ranked_serp_element") or {}
                    serp_item = ranked.get("serp_item") or {}
                    keywords.append({
                        "keyword": kw_data.get("keyword", ""),
                        "position": serp_item.get("rank_group"),
                        "search_volume": kw_data.get("keyword_info", {}).get("search_volume"),
                        "etv": serp_item.get("etv"),
                    })

        return keywords[:limit]

    # =========================================================================
    # DB ENRICHMENT HELPER
    # =========================================================================

    def enrich_and_store(
        self,
        keyword_texts: List[str],
        project_id: Optional[str] = None,
    ) -> int:
        """
        Fetch volume/KD and store in seo_keywords. Returns count of updated rows.

        Args:
            keyword_texts: Keyword strings to enrich
            project_id: Optional project filter for matching

        Returns:
            Number of keywords updated in DB
        """
        enriched = self.enrich_keywords_bulk(keyword_texts)
        if not enriched:
            return 0

        updated = 0
        for item in enriched:
            kw = item.get("keyword", "")
            vol = item.get("search_volume")
            kd = item.get("keyword_difficulty")
            if vol is None and kd is None:
                continue

            update_data: Dict[str, Any] = {}
            if vol is not None:
                update_data["search_volume"] = vol
            if kd is not None:
                update_data["keyword_difficulty"] = kd

            try:
                query = (
                    self.supabase.table("seo_keywords")
                    .update(update_data)
                    .eq("keyword", kw)
                )
                if project_id:
                    query = query.eq("project_id", project_id)
                query.execute()
                updated += 1
            except Exception as e:
                logger.warning(f"Failed to store enrichment for '{kw}': {e}")

        logger.info(f"Enriched {updated}/{len(enriched)} keywords with volume/KD data")
        return updated
