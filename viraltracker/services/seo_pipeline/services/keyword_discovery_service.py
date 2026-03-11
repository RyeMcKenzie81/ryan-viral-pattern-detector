"""
Keyword Discovery Service - Google Autocomplete keyword research.

Discovers long-tail keywords by querying Google's Autocomplete API with
seed keywords combined with modifier prefixes and suffixes.

Ported from seo-pipeline/discovery/autocomplete.js and batch-discover.js.

Key features:
- 16 modifiers + 10 suffixes for variation generation
- Word count filtering (3-10 words for long-tail)
- Deduplication and cross-seed frequency tracking
- Rate-limited requests (100ms between queries)
"""

import asyncio
import logging
import re
from typing import List, Dict, Any, Optional, Set

import httpx

logger = logging.getLogger(__name__)

# Google Autocomplete endpoint (no auth needed)
AUTOCOMPLETE_URL = "http://suggestqueries.google.com/complete/search"

# Variation modifiers (prefixed to seed keyword)
MODIFIERS = [
    "", "how to", "why", "what", "when", "where", "best", "top",
    "should i", "can i", "is it", "do kids", "for kids",
    "for parents", "family", "guide",
]

# Variation suffixes (appended to seed keyword)
SUFFIXES = [
    "", "guide", "tips", "advice", "ideas", "activities",
    "conversation", "for parents", "with kids", "family",
]

# Valid keyword characters
VALID_CHARS_PATTERN = re.compile(r"^[a-z0-9\s\-']+$")

# Rate limit between requests (seconds)
REQUEST_DELAY = 0.1


class KeywordDiscoveryService:
    """Service for discovering long-tail keywords via Google Autocomplete."""

    def __init__(self, supabase_client=None):
        """
        Initialize with optional Supabase client.

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

    async def discover_keywords(
        self,
        project_id: str,
        seeds: List[str],
        min_word_count: int = 3,
        max_word_count: int = 10,
    ) -> Dict[str, Any]:
        """
        Discover keywords from seed keywords via Google Autocomplete.

        For each seed, generates modifier+suffix variations and queries
        Google Autocomplete. Results are filtered by word count and
        character validity, deduplicated, and tracked for cross-seed frequency.

        Args:
            project_id: SEO project UUID
            seeds: List of seed keywords
            min_word_count: Minimum words in keyword (default 3)
            max_word_count: Maximum words in keyword (default 10)

        Returns:
            Dict with:
                - total_keywords: Count of unique keywords found
                - keywords: List of keyword dicts (keyword, word_count, seed, found_in_seeds)
                - saved_count: Number of new keywords saved to DB
        """
        all_keywords: Dict[str, Dict[str, Any]] = {}
        total_queries = 0

        async with httpx.AsyncClient(timeout=10.0) as client:
            for seed in seeds:
                seed = seed.strip().lower()
                if not seed:
                    continue

                variations = self._generate_variations(seed)
                logger.info(f"Querying {len(variations)} variations for seed '{seed}'")

                for query in variations:
                    suggestions = await self._query_autocomplete(client, query)
                    total_queries += 1

                    for suggestion in suggestions:
                        filtered = self._filter_keyword(
                            suggestion, min_word_count, max_word_count
                        )
                        if filtered:
                            normalized = filtered.lower().strip()
                            if normalized in all_keywords:
                                all_keywords[normalized]["found_in_seeds"] += 1
                            else:
                                all_keywords[normalized] = {
                                    "keyword": normalized,
                                    "word_count": len(normalized.split()),
                                    "seed_keyword": seed,
                                    "found_in_seeds": 1,
                                }

                    # Rate limit
                    await asyncio.sleep(REQUEST_DELAY)

        # Sort by cross-seed frequency (desc), then word count (desc = more specific)
        keywords_list = sorted(
            all_keywords.values(),
            key=lambda k: (k["found_in_seeds"], k["word_count"]),
            reverse=True,
        )

        logger.info(
            f"Discovery complete: {len(keywords_list)} unique keywords "
            f"from {total_queries} queries across {len(seeds)} seeds"
        )

        # Save to database
        saved_count = 0
        for kw_data in keywords_list:
            saved = self._save_keyword(project_id, kw_data)
            if saved:
                saved_count += 1

        return {
            "total_keywords": len(keywords_list),
            "keywords": keywords_list,
            "saved_count": saved_count,
        }

    def _generate_variations(self, seed: str) -> List[str]:
        """
        Generate query variations from a seed keyword.

        Combines modifiers (prefixes) and suffixes with the seed to create
        a comprehensive set of autocomplete queries.

        Args:
            seed: Base seed keyword

        Returns:
            List of query strings
        """
        variations: List[str] = []
        seen: Set[str] = set()

        for modifier in MODIFIERS:
            for suffix in SUFFIXES:
                parts = []
                if modifier:
                    parts.append(modifier)
                parts.append(seed)
                if suffix:
                    parts.append(suffix)
                query = " ".join(parts).strip()
                normalized = query.lower()
                if normalized not in seen:
                    seen.add(normalized)
                    variations.append(query)

        return variations

    async def _query_autocomplete(
        self, client: httpx.AsyncClient, query: str
    ) -> List[str]:
        """
        Query Google Autocomplete API.

        Args:
            client: httpx async client
            query: Search query

        Returns:
            List of suggestion strings
        """
        try:
            response = await client.get(
                AUTOCOMPLETE_URL,
                params={"client": "firefox", "q": query},
            )
            response.raise_for_status()
            data = response.json()
            # Response format: [query, [suggestions]]
            if isinstance(data, list) and len(data) >= 2:
                return data[1] if isinstance(data[1], list) else []
            return []
        except httpx.HTTPStatusError as e:
            logger.warning(f"Autocomplete HTTP error for '{query}': {e.response.status_code}")
            return []
        except Exception as e:
            logger.warning(f"Autocomplete error for '{query}': {e}")
            return []

    def _filter_keyword(
        self,
        keyword: str,
        min_words: int,
        max_words: int,
    ) -> Optional[str]:
        """
        Filter a keyword by word count and character validity.

        Args:
            keyword: Raw keyword suggestion
            min_words: Minimum word count
            max_words: Maximum word count

        Returns:
            Cleaned keyword string or None if filtered out
        """
        cleaned = keyword.strip().lower()
        if not cleaned:
            return None

        # Character validity check
        if not VALID_CHARS_PATTERN.match(cleaned):
            return None

        # Word count check
        word_count = len(cleaned.split())
        if word_count < min_words or word_count > max_words:
            return None

        return cleaned

    def _save_keyword(
        self,
        project_id: str,
        kw_data: Dict[str, Any],
    ) -> bool:
        """
        Save a keyword to the database, skipping duplicates.

        Args:
            project_id: SEO project UUID
            kw_data: Keyword data dict

        Returns:
            True if saved (new), False if duplicate
        """
        try:
            # Check for existing keyword in this project
            existing = (
                self.supabase.table("seo_keywords")
                .select("id")
                .eq("project_id", project_id)
                .eq("keyword", kw_data["keyword"])
                .execute()
            )
            if existing.data:
                # Update found_in_seeds if higher
                current = existing.data[0]
                self.supabase.table("seo_keywords").update({
                    "found_in_seeds": kw_data["found_in_seeds"],
                }).eq("id", current["id"]).execute()
                return False

            # Insert new keyword
            self.supabase.table("seo_keywords").insert({
                "project_id": project_id,
                "keyword": kw_data["keyword"],
                "word_count": kw_data["word_count"],
                "seed_keyword": kw_data["seed_keyword"],
                "found_in_seeds": kw_data["found_in_seeds"],
                "status": "discovered",
            }).execute()
            return True

        except Exception as e:
            logger.error(f"Error saving keyword '{kw_data['keyword']}': {e}")
            return False

    def create_keyword(self, project_id: str, keyword: str) -> Dict[str, Any]:
        """
        Create a single keyword record for the workflow pipeline.

        Args:
            project_id: SEO project UUID
            keyword: Keyword string

        Returns:
            Created keyword record with id
        """
        word_count = len(keyword.split())
        result = self.supabase.table("seo_keywords").insert({
            "project_id": project_id,
            "keyword": keyword,
            "word_count": word_count,
            "seed_keyword": keyword,
            "found_in_seeds": 1,
            "status": "in_progress",
        }).execute()
        if result.data:
            logger.info(f"Created keyword '{keyword}' in project {project_id}")
            return result.data[0]
        raise ValueError(f"Failed to create keyword record for '{keyword}'")

    def get_keywords(
        self,
        project_id: str,
        status: Optional[str] = None,
        order_by: str = "found_in_seeds",
    ) -> List[Dict[str, Any]]:
        """
        Get keywords for a project.

        Args:
            project_id: SEO project UUID
            status: Optional status filter
            order_by: Sort field (default: found_in_seeds)

        Returns:
            List of keyword records
        """
        query = (
            self.supabase.table("seo_keywords")
            .select("*")
            .eq("project_id", project_id)
        )

        if status:
            query = query.eq("status", status)

        query = query.order(order_by, desc=True)
        result = query.execute()
        return result.data

    def update_keyword_status(
        self,
        keyword_id: str,
        status: str,
    ) -> Optional[Dict[str, Any]]:
        """
        Update a keyword's status.

        Args:
            keyword_id: Keyword UUID
            status: New status value

        Returns:
            Updated keyword record or None
        """
        result = (
            self.supabase.table("seo_keywords")
            .update({"status": status})
            .eq("id", keyword_id)
            .execute()
        )
        return result.data[0] if result.data else None
