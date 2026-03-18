"""
DataForSEO Service — keyword data, PAA, and competitor keyword analysis.

External API wrapper following the same pattern as GSCService.
Requires DATAFORSEO_LOGIN and DATAFORSEO_PASSWORD env vars.
Degrades gracefully when credentials are missing.

Endpoints used:
- keywords_data/google_ads/search_volume/live — search volume (Google Ads)
- keywords_data/clickstream_data/bulk_search_volume/live — clickstream fallback for restricted keywords
- dataforseo_labs/google/bulk_keyword_difficulty/live — keyword difficulty
- dataforseo_labs/google/keyword_suggestions/live — keyword suggestions
- serp/google/organic/live/advanced — People Also Ask questions
- dataforseo_labs/google/ranked_keywords/live — competitor organic keywords
"""

import logging
import os
from datetime import datetime
from typing import Any, Dict, List, Optional

import httpx

logger = logging.getLogger(__name__)

BASE_URL = "https://api.dataforseo.com/v3"


def _days_ago_iso(days: int) -> str:
    """Return ISO timestamp for `days` ago from now (UTC)."""
    from datetime import timedelta
    return (datetime.utcnow() - timedelta(days=days)).isoformat()


_COMP_MAP = {"LOW": 0.33, "MEDIUM": 0.66, "HIGH": 1.0}


def _normalize_competition(val) -> Optional[float]:
    """Normalize competition to float 0-1. Google Ads returns string, Labs returns float."""
    if val is None:
        return None
    if isinstance(val, (int, float)):
        return float(val)
    if isinstance(val, str):
        return _COMP_MAP.get(val.upper())
    return None


_QUESTION_PREFIXES = [
    "what is the", "what are the", "what is", "what are",
    "how to", "how do you", "how do", "how does", "how can",
    "why do", "why does", "why is", "why are",
    "can you", "can i", "is it", "is there", "are there",
    "what", "how", "why", "when", "where", "which",
]

_STOP_WORDS = frozenset({
    "a", "an", "the", "and", "or", "but", "in", "on", "at", "to", "for",
    "of", "with", "by", "from", "about", "into", "through", "during",
    "before", "after", "between", "under", "over",
    "is", "are", "was", "were", "be", "been", "being",
    "have", "has", "had", "do", "does", "did",
    "will", "would", "could", "should", "may", "might", "can",
    "i", "you", "he", "she", "it", "we", "they", "me", "him", "her", "us", "them",
    "my", "your", "his", "its", "our", "their",
    "this", "that", "these", "those",
    "not", "no", "nor", "so", "too", "very",
})


def extract_core_keyword(phrase: str, max_words: int = 4) -> str:
    """
    Extract 2-4 word core keyword from a long-tail phrase.

    Long-tail AI-generated spoke keywords like "gaming stress keeping me up nights"
    have zero search volume. The core phrase "gaming stress" does have data.
    This extracts the searchable core for volume enrichment.

    Args:
        phrase: Long-tail keyword or question
        max_words: Maximum words in the core (default: 4)

    Returns:
        Shortened core keyword (2-4 words), or original if already short enough
    """
    text = phrase.lower().strip().rstrip("?!.")

    # Already short enough
    if len(text.split()) <= max_words:
        return text

    # Strip question prefixes
    for prefix in _QUESTION_PREFIXES:
        if text.startswith(prefix + " "):
            text = text[len(prefix):].strip()
            break

    # Remove stop words, keep content words
    words = [w for w in text.split() if w not in _STOP_WORDS and len(w) > 1]

    core = " ".join(words[:max_words])

    # If we stripped too much, fall back to first max_words of original
    if len(core.split()) < 2:
        words = phrase.lower().strip().rstrip("?!.").split()
        core = " ".join(words[:max_words])

    return core


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
        Fetch search volume + keyword difficulty for up to 700 keywords.

        Uses Google Ads for volume/CPC/competition with clickstream fallback
        for restricted keywords (e.g. child-related terms blocked by Google Ads).

        Args:
            keyword_texts: List of keyword strings (max 700)
            location_code: Geo location (default: 2840 = US)
            language_code: Language code (default: "en")

        Returns:
            List of dicts: [{keyword, search_volume, keyword_difficulty, cpc, competition, volume_source}, ...]
        """
        if not self._available:
            logger.warning("DataForSEO not configured — skipping keyword enrichment")
            return []

        if not keyword_texts:
            return []

        # Cap at 700 per Google Ads API limit
        keywords = [kw.lower() for kw in keyword_texts[:700]]

        # Merge results from both endpoints
        results: Dict[str, Dict] = {kw: {"keyword": kw} for kw in keywords}

        # 1. Search volume via Google Ads Keyword Planner
        try:
            vol_data = self._post(
                "keywords_data/google_ads/search_volume/live",
                [{"keywords": keywords, "location_code": location_code, "language_code": language_code}],
            )
            for task in vol_data.get("tasks", []):
                for item in (task.get("result") or []):
                    kw = item.get("keyword", "").lower()
                    if kw in results:
                        results[kw]["search_volume"] = item.get("search_volume")
                        results[kw]["cpc"] = item.get("cpc")
                        results[kw]["competition"] = _normalize_competition(item.get("competition"))
                        results[kw]["volume_source"] = "google_ads"
        except Exception as e:
            logger.warning(f"DataForSEO search volume failed: {e}")

        # 1b. Clickstream fallback for keywords with null volume
        # (Google Ads blocks child-related keywords like "kids", "children", "baby")
        null_vol_kws = [kw for kw in keywords if results[kw].get("search_volume") is None]
        if null_vol_kws:
            logger.info(f"Clickstream fallback for {len(null_vol_kws)} keywords with null Google Ads volume")
            self._clickstream_fallback(null_vol_kws, results, location_code, language_code)

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

    def enrich_keywords_google_ads(
        self,
        keyword_texts: List[str],
        location_code: int = 2840,
        language_code: str = "en",
    ) -> List[Dict[str, Any]]:
        """
        Fetch search volume, CPC, and competition via Google Ads + clickstream fallback.

        Google Ads blocks volume for child-related keywords ("kids", "children",
        "baby"). Automatically falls back to clickstream data for any nulls.

        Args:
            keyword_texts: List of keyword strings (max 700)
            location_code: Geo location (default: 2840 = US)
            language_code: Language code (default: "en")

        Returns:
            List of dicts: [{keyword, search_volume, cpc, competition, volume_source}, ...]
        """
        if not self._available:
            logger.warning("DataForSEO not configured — skipping Google Ads enrichment")
            return []

        if not keyword_texts:
            return []

        # Cap at 700 per API limit
        keywords = [kw.lower() for kw in keyword_texts[:700]]
        results: Dict[str, Dict] = {kw: {"keyword": kw} for kw in keywords}

        try:
            data = self._post(
                "keywords_data/google_ads/search_volume/live",
                [{"keywords": keywords, "location_code": location_code, "language_code": language_code}],
            )
            for task in data.get("tasks", []):
                for item in (task.get("result") or []):
                    kw = item.get("keyword", "").lower()
                    if kw in results:
                        results[kw]["search_volume"] = item.get("search_volume")
                        results[kw]["cpc"] = item.get("cpc")
                        results[kw]["competition"] = _normalize_competition(item.get("competition"))
                        results[kw]["volume_source"] = "google_ads"
        except Exception as e:
            logger.warning(f"DataForSEO Google Ads enrichment failed: {e}")

        # Clickstream fallback for keywords with null volume
        null_vol_kws = [kw for kw in keywords if results[kw].get("search_volume") is None]
        if null_vol_kws:
            logger.info(f"Clickstream fallback for {len(null_vol_kws)} keywords with null Google Ads volume")
            self._clickstream_fallback(null_vol_kws, results, location_code, language_code)

        return list(results.values())

    def _clickstream_fallback(
        self,
        keywords: List[str],
        results: Dict[str, Dict],
        location_code: int = 2840,
        language_code: str = "en",
    ) -> None:
        """
        Fill in null search_volume from clickstream data (in-place).

        Google Ads blocks volume for child-related keywords. Clickstream
        uses DataForSEO's own panel data which doesn't have these restrictions.
        Volumes are typically 30-70% of Google Ads numbers but better than nothing.
        """
        try:
            cs_data = self._post(
                "keywords_data/clickstream_data/bulk_search_volume/live",
                [{"keywords": keywords[:1000], "location_code": location_code, "language_code": language_code}],
            )
            filled = 0
            for task in cs_data.get("tasks", []):
                for result_block in (task.get("result") or []):
                    for item in (result_block.get("items") or []):
                        kw = item.get("keyword", "").lower()
                        vol = item.get("search_volume")
                        if kw in results and vol is not None and vol > 0:
                            results[kw]["search_volume"] = vol
                            results[kw]["volume_source"] = "clickstream"
                            filled += 1
            logger.info(f"Clickstream fallback filled volume for {filled}/{len(keywords)} keywords")
        except Exception as e:
            logger.warning(f"Clickstream fallback failed: {e}")

    def get_keyword_suggestions(
        self,
        seed_keyword: str,
        limit: int = 200,
        location_code: int = 2840,
        language_code: str = "en",
        include_seed: bool = True,
    ) -> List[Dict[str, Any]]:
        """
        Get keyword suggestions for a seed keyword with full metrics.

        Args:
            seed_keyword: Starting keyword to expand
            limit: Max results (1-1000, default 200)
            location_code: Geo location (default: 2840 = US)
            language_code: Language code (default: "en")
            include_seed: Include seed keyword data in results

        Returns:
            List of dicts with: keyword, search_volume, cpc, competition,
            keyword_difficulty, search_intent
        """
        if not self._available:
            logger.warning("DataForSEO not configured — skipping keyword suggestions")
            return []

        try:
            data = self._post(
                "dataforseo_labs/google/keyword_suggestions/live",
                [{
                    "keyword": seed_keyword,
                    "location_code": location_code,
                    "language_code": language_code,
                    "include_seed_keyword": include_seed,
                    "limit": min(limit, 1000),
                }],
            )
        except Exception as e:
            logger.warning(f"DataForSEO keyword suggestions failed for '{seed_keyword}': {e}")
            return []

        suggestions = []
        for task in data.get("tasks", []):
            for result_block in (task.get("result") or []):
                for item in (result_block.get("items") or []):
                    # keyword is at item level, metrics are in nested objects
                    kw_info = item.get("keyword_info") or {}
                    kw_props = item.get("keyword_properties") or {}
                    intent_info = item.get("search_intent_info") or {}
                    keyword = item.get("keyword", "")
                    suggestions.append({
                        "keyword": keyword,
                        "search_volume": kw_info.get("search_volume"),
                        "cpc": kw_info.get("cpc"),
                        "competition": _normalize_competition(kw_info.get("competition")),
                        "keyword_difficulty": kw_props.get("keyword_difficulty"),
                        "search_intent": intent_info.get("main_intent"),
                    })

        # Clickstream fallback for suggestions with null volume
        null_vol = [s for s in suggestions if s.get("search_volume") is None and s.get("keyword")]
        if null_vol:
            null_kws = [s["keyword"] for s in null_vol]
            logger.info(f"Keyword suggestions: {len(null_kws)} have null volume, trying clickstream fallback")
            cs_results: Dict[str, Dict] = {kw.lower(): {} for kw in null_kws}
            self._clickstream_fallback(null_kws, cs_results, location_code, language_code)
            for s in suggestions:
                kw = s["keyword"].lower()
                if kw in cs_results and cs_results[kw].get("search_volume") is not None:
                    s["search_volume"] = cs_results[kw]["search_volume"]
                    s["volume_source"] = "clickstream"

        return suggestions

    def enrich_with_cache(
        self,
        keyword_texts: List[str],
        location_code: int = 2840,
        language_code: str = "en",
        force_refresh: bool = False,
        max_age_days: int = 7,
    ) -> List[Dict[str, Any]]:
        """
        Enrich keywords with volume/KD/CPC, using DB cache to avoid redundant API calls.

        Checks seo_keyword_metrics_cache for fresh data (< max_age_days old).
        Only fetches stale/missing keywords from API. Stores results in cache.

        Args:
            keyword_texts: Keywords to enrich
            location_code: Geo location
            language_code: Language code
            force_refresh: Bypass cache, always fetch from API
            max_age_days: Cache freshness window in days (default: 7)

        Returns:
            List of dicts: [{keyword, search_volume, keyword_difficulty, cpc, competition, search_intent}, ...]
        """
        if not keyword_texts:
            return []

        keywords = [kw.lower() for kw in keyword_texts]
        cached: Dict[str, Dict[str, Any]] = {}

        # 1. Check cache for fresh data
        if not force_refresh:
            try:
                resp = (
                    self.supabase.table("seo_keyword_metrics_cache")
                    .select("keyword, search_volume, keyword_difficulty, cpc, competition, search_intent, refreshed_at")
                    .in_("keyword", keywords)
                    .eq("location_code", location_code)
                    .gte("refreshed_at", _days_ago_iso(max_age_days))
                    .execute()
                )
                for row in (resp.data or []):
                    kw = row["keyword"].lower()
                    cached[kw] = {
                        "keyword": kw,
                        "search_volume": row.get("search_volume"),
                        "keyword_difficulty": row.get("keyword_difficulty"),
                        "cpc": row.get("cpc"),
                        "competition": row.get("competition"),
                        "search_intent": row.get("search_intent"),
                    }
            except Exception as e:
                logger.warning(f"Cache lookup failed, will fetch all from API: {e}")

        # 2. Identify stale/missing keywords
        stale = [kw for kw in keywords if kw not in cached]

        # 3. Fetch stale keywords from API
        fresh: Dict[str, Dict[str, Any]] = {}
        if stale:
            # 3a. Volume + CPC + competition via Google Ads
            vol_results = self.enrich_keywords_google_ads(stale, location_code, language_code)
            for item in vol_results:
                kw = item.get("keyword", "").lower()
                fresh[kw] = {
                    "keyword": kw,
                    "search_volume": item.get("search_volume"),
                    "cpc": item.get("cpc"),
                    "competition": item.get("competition"),
                    "keyword_difficulty": None,
                    "search_intent": None,
                }

            # 3b. Keyword difficulty via standalone KD endpoint (avoids double volume call)
            try:
                kd_data = self._post(
                    "dataforseo_labs/google/bulk_keyword_difficulty/live",
                    [{
                        "keywords": stale[:1000],
                        "location_code": location_code,
                        "language_code": language_code,
                    }],
                )
                for task in kd_data.get("tasks", []):
                    for result_block in (task.get("result") or []):
                        for item in (result_block.get("items") or []):
                            kw = item.get("keyword", "").lower()
                            if kw in fresh:
                                fresh[kw]["keyword_difficulty"] = item.get("keyword_difficulty")
            except Exception as e:
                logger.warning(f"KD enrichment failed in cache flow: {e}")

            # 3c. Upsert fresh results into cache
            rows_to_upsert = []
            for kw, data in fresh.items():
                rows_to_upsert.append({
                    "keyword": kw,
                    "location_code": location_code,
                    "search_volume": data.get("search_volume"),
                    "keyword_difficulty": data.get("keyword_difficulty"),
                    "cpc": data.get("cpc"),
                    "competition": data.get("competition"),
                    "search_intent": data.get("search_intent"),
                    "refreshed_at": datetime.utcnow().isoformat(),
                })
            if rows_to_upsert:
                try:
                    self.supabase.table("seo_keyword_metrics_cache").upsert(
                        rows_to_upsert
                    ).execute()
                except Exception as e:
                    logger.warning(f"Failed to upsert keyword metrics cache: {e}")

        # 4. Merge cached + fresh
        all_results: Dict[str, Dict[str, Any]] = {}
        all_results.update(cached)
        all_results.update(fresh)

        # Return in original order, only for requested keywords
        return [all_results[kw] for kw in keywords if kw in all_results]

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
