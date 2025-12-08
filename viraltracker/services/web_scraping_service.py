"""
WebScrapingService - Generic web scraping service using FireCrawl.

This service provides a reusable interface for scraping web content,
supporting multiple output formats and structured data extraction.

Use cases:
- Landing page scraping for brand research
- Competitor website analysis
- Product page data enrichment
- Any tool that needs web content

Part of the Service Layer - contains business logic, no UI or agent code.
"""

import logging
import os
from typing import List, Dict, Optional, Any
from dataclasses import dataclass

logger = logging.getLogger(__name__)


@dataclass
class ScrapeResult:
    """Result from scraping a URL."""
    url: str
    success: bool
    markdown: Optional[str] = None
    html: Optional[str] = None
    links: Optional[List[str]] = None
    metadata: Optional[Dict[str, Any]] = None
    error: Optional[str] = None


@dataclass
class ExtractResult:
    """Result from structured extraction."""
    url: str
    success: bool
    data: Optional[Dict[str, Any]] = None
    error: Optional[str] = None


class WebScrapingService:
    """
    Generic web scraping service using FireCrawl API.

    Provides methods for:
    - Single URL scraping with multiple formats
    - Batch URL scraping
    - Structured data extraction with schemas
    - Async operations for non-blocking scrapes

    All methods are reusable across different features.
    """

    def __init__(self, api_key: Optional[str] = None):
        """
        Initialize WebScrapingService.

        Args:
            api_key: FireCrawl API key. If not provided, reads from FIRECRAWL_API_KEY env var.
        """
        self.api_key = api_key or os.getenv("FIRECRAWL_API_KEY")
        if not self.api_key:
            logger.warning("FIRECRAWL_API_KEY not set - scraping will fail")

        self._client = None
        self._async_client = None

    def _get_client(self):
        """Get or create sync FireCrawl client."""
        if self._client is None:
            from firecrawl import Firecrawl
            self._client = Firecrawl(api_key=self.api_key)
        return self._client

    def _get_async_client(self):
        """Get or create async FireCrawl client."""
        if self._async_client is None:
            from firecrawl import AsyncFirecrawl
            self._async_client = AsyncFirecrawl(api_key=self.api_key)
        return self._async_client

    def scrape_url(
        self,
        url: str,
        formats: Optional[List[str]] = None,
        only_main_content: bool = True,
        wait_for: int = 0,
        timeout: int = 30000
    ) -> ScrapeResult:
        """
        Scrape a single URL and return content in requested formats.

        Args:
            url: The URL to scrape
            formats: List of formats to return. Options: "markdown", "html", "links".
                    Defaults to ["markdown"].
            only_main_content: If True, extract only main content (no nav, footer, etc.)
            wait_for: Milliseconds to wait for JavaScript to execute (0 = no wait)
            timeout: Request timeout in milliseconds

        Returns:
            ScrapeResult with content in requested formats
        """
        if formats is None:
            formats = ["markdown"]

        logger.info(f"Scraping URL: {url} (formats={formats})")

        try:
            client = self._get_client()

            # Build scrape options
            options = {
                "formats": formats,
                "onlyMainContent": only_main_content,
                "timeout": timeout
            }

            if wait_for > 0:
                options["waitFor"] = wait_for

            result = client.scrape(url, **options)

            return ScrapeResult(
                url=url,
                success=True,
                markdown=result.get("markdown"),
                html=result.get("html"),
                links=result.get("links"),
                metadata=result.get("metadata")
            )

        except Exception as e:
            logger.error(f"Failed to scrape {url}: {e}")
            return ScrapeResult(
                url=url,
                success=False,
                error=str(e)
            )

    async def scrape_url_async(
        self,
        url: str,
        formats: Optional[List[str]] = None,
        only_main_content: bool = True,
        wait_for: int = 0,
        timeout: int = 30000
    ) -> ScrapeResult:
        """
        Async version of scrape_url.

        Args:
            url: The URL to scrape
            formats: List of formats to return. Options: "markdown", "html", "links".
            only_main_content: If True, extract only main content
            wait_for: Milliseconds to wait for JavaScript
            timeout: Request timeout in milliseconds

        Returns:
            ScrapeResult with content in requested formats
        """
        if formats is None:
            formats = ["markdown"]

        logger.info(f"Async scraping URL: {url} (formats={formats})")

        try:
            client = self._get_async_client()

            # Build scrape options
            options = {
                "formats": formats,
                "onlyMainContent": only_main_content,
                "timeout": timeout
            }

            if wait_for > 0:
                options["waitFor"] = wait_for

            result = await client.scrape(url, **options)

            return ScrapeResult(
                url=url,
                success=True,
                markdown=result.get("markdown"),
                html=result.get("html"),
                links=result.get("links"),
                metadata=result.get("metadata")
            )

        except Exception as e:
            logger.error(f"Failed to async scrape {url}: {e}")
            return ScrapeResult(
                url=url,
                success=False,
                error=str(e)
            )

    def batch_scrape(
        self,
        urls: List[str],
        formats: Optional[List[str]] = None,
        only_main_content: bool = True,
        timeout: int = 60000
    ) -> List[ScrapeResult]:
        """
        Scrape multiple URLs synchronously.

        Args:
            urls: List of URLs to scrape
            formats: List of formats to return
            only_main_content: If True, extract only main content
            timeout: Request timeout in milliseconds

        Returns:
            List of ScrapeResult objects
        """
        if formats is None:
            formats = ["markdown"]

        logger.info(f"Batch scraping {len(urls)} URLs")

        results = []
        for url in urls:
            result = self.scrape_url(
                url=url,
                formats=formats,
                only_main_content=only_main_content,
                timeout=timeout
            )
            results.append(result)

        success_count = sum(1 for r in results if r.success)
        logger.info(f"Batch scrape complete: {success_count}/{len(urls)} successful")

        return results

    async def batch_scrape_async(
        self,
        urls: List[str],
        formats: Optional[List[str]] = None,
        only_main_content: bool = True,
        poll_interval: int = 1,
        timeout: int = 120
    ) -> List[ScrapeResult]:
        """
        Scrape multiple URLs asynchronously using FireCrawl's batch endpoint.

        Args:
            urls: List of URLs to scrape
            formats: List of formats to return
            only_main_content: If True, extract only main content
            poll_interval: Seconds between status checks
            timeout: Total timeout in seconds

        Returns:
            List of ScrapeResult objects
        """
        if formats is None:
            formats = ["markdown"]

        logger.info(f"Async batch scraping {len(urls)} URLs")

        try:
            client = self._get_async_client()

            job = await client.batch_scrape(
                urls,
                formats=formats,
                onlyMainContent=only_main_content,
                poll_interval=poll_interval,
                timeout=timeout
            )

            results = []
            for item in job.data or []:
                results.append(ScrapeResult(
                    url=item.get("url", ""),
                    success=True,
                    markdown=item.get("markdown"),
                    html=item.get("html"),
                    links=item.get("links"),
                    metadata=item.get("metadata")
                ))

            logger.info(f"Async batch scrape complete: {len(results)} results")
            return results

        except Exception as e:
            logger.error(f"Batch scrape failed: {e}")
            # Return error results for all URLs
            return [
                ScrapeResult(url=url, success=False, error=str(e))
                for url in urls
            ]

    def extract_structured(
        self,
        url: str,
        schema: Optional[Dict[str, Any]] = None,
        prompt: Optional[str] = None
    ) -> ExtractResult:
        """
        Extract structured data from a URL using LLM.

        Provide either a schema, a prompt, or both:
        - Schema: JSON schema defining the structure of data to extract
        - Prompt: Natural language description of what to extract

        Args:
            url: The URL to extract data from
            schema: JSON schema for structured extraction (optional)
            prompt: Natural language prompt for extraction (optional)

        Returns:
            ExtractResult with extracted data

        Example schema:
            {
                "type": "object",
                "properties": {
                    "title": {"type": "string"},
                    "price": {"type": "number"},
                    "features": {"type": "array", "items": {"type": "string"}}
                },
                "required": ["title"]
            }
        """
        if not schema and not prompt:
            raise ValueError("Must provide either schema or prompt for extraction")

        logger.info(f"Extracting structured data from: {url}")

        try:
            client = self._get_client()

            kwargs = {"urls": [url]}
            if schema:
                kwargs["schema"] = schema
            if prompt:
                kwargs["prompt"] = prompt

            result = client.extract(**kwargs)

            return ExtractResult(
                url=url,
                success=True,
                data=result.data if hasattr(result, 'data') else result
            )

        except Exception as e:
            logger.error(f"Failed to extract from {url}: {e}")
            return ExtractResult(
                url=url,
                success=False,
                error=str(e)
            )

    async def extract_structured_async(
        self,
        url: str,
        schema: Optional[Dict[str, Any]] = None,
        prompt: Optional[str] = None
    ) -> ExtractResult:
        """
        Async version of extract_structured.

        Args:
            url: The URL to extract data from
            schema: JSON schema for structured extraction
            prompt: Natural language prompt for extraction

        Returns:
            ExtractResult with extracted data
        """
        if not schema and not prompt:
            raise ValueError("Must provide either schema or prompt for extraction")

        logger.info(f"Async extracting structured data from: {url}")

        try:
            client = self._get_async_client()

            kwargs = {"urls": [url]}
            if schema:
                kwargs["schema"] = schema
            if prompt:
                kwargs["prompt"] = prompt

            result = await client.extract(**kwargs)

            return ExtractResult(
                url=url,
                success=True,
                data=result.data if hasattr(result, 'data') else result
            )

        except Exception as e:
            logger.error(f"Failed to async extract from {url}: {e}")
            return ExtractResult(
                url=url,
                success=False,
                error=str(e)
            )

    def batch_extract(
        self,
        urls: List[str],
        schema: Optional[Dict[str, Any]] = None,
        prompt: Optional[str] = None
    ) -> List[ExtractResult]:
        """
        Extract structured data from multiple URLs.

        Args:
            urls: List of URLs to extract from
            schema: JSON schema for structured extraction
            prompt: Natural language prompt for extraction

        Returns:
            List of ExtractResult objects
        """
        if not schema and not prompt:
            raise ValueError("Must provide either schema or prompt for extraction")

        logger.info(f"Batch extracting from {len(urls)} URLs")

        try:
            client = self._get_client()

            kwargs = {"urls": urls}
            if schema:
                kwargs["schema"] = schema
            if prompt:
                kwargs["prompt"] = prompt

            result = client.extract(**kwargs)

            # Handle different response formats
            if hasattr(result, 'data') and isinstance(result.data, list):
                return [
                    ExtractResult(
                        url=urls[i] if i < len(urls) else "",
                        success=True,
                        data=item
                    )
                    for i, item in enumerate(result.data)
                ]
            else:
                # Single result for all URLs
                return [
                    ExtractResult(
                        url=urls[0] if urls else "",
                        success=True,
                        data=result.data if hasattr(result, 'data') else result
                    )
                ]

        except Exception as e:
            logger.error(f"Batch extract failed: {e}")
            return [
                ExtractResult(url=url, success=False, error=str(e))
                for url in urls
            ]


# Commonly used extraction schemas for reuse

LANDING_PAGE_SCHEMA = {
    "type": "object",
    "properties": {
        "page_title": {"type": "string", "description": "Main page title or headline"},
        "meta_description": {"type": "string", "description": "Meta description or subtitle"},
        "product_name": {"type": "string", "description": "Name of the main product/service"},
        "pricing": {
            "type": "object",
            "properties": {
                "price": {"type": "string"},
                "currency": {"type": "string"},
                "billing_period": {"type": "string"},
                "discount": {"type": "string"}
            }
        },
        "benefits": {
            "type": "array",
            "items": {"type": "string"},
            "description": "List of product benefits mentioned"
        },
        "features": {
            "type": "array",
            "items": {"type": "string"},
            "description": "List of product features"
        },
        "testimonials": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "quote": {"type": "string"},
                    "author": {"type": "string"},
                    "title": {"type": "string"}
                }
            }
        },
        "social_proof": {
            "type": "array",
            "items": {"type": "string"},
            "description": "Social proof elements (stats, logos, badges)"
        },
        "call_to_action": {"type": "string", "description": "Primary CTA text"},
        "objection_handling": {
            "type": "array",
            "items": {"type": "string"},
            "description": "FAQ or objection-handling content"
        },
        "guarantee": {"type": "string", "description": "Money-back guarantee or risk reversal"},
        "urgency_elements": {
            "type": "array",
            "items": {"type": "string"},
            "description": "Scarcity or urgency messaging"
        }
    }
}

PRODUCT_PAGE_SCHEMA = {
    "type": "object",
    "properties": {
        "product_name": {"type": "string"},
        "description": {"type": "string"},
        "price": {"type": "string"},
        "currency": {"type": "string"},
        "availability": {"type": "string"},
        "images": {"type": "array", "items": {"type": "string"}},
        "features": {"type": "array", "items": {"type": "string"}},
        "specifications": {"type": "object"},
        "reviews_summary": {
            "type": "object",
            "properties": {
                "average_rating": {"type": "number"},
                "total_reviews": {"type": "integer"}
            }
        }
    }
}

COMPETITOR_PAGE_SCHEMA = {
    "type": "object",
    "properties": {
        "company_name": {"type": "string"},
        "tagline": {"type": "string"},
        "value_proposition": {"type": "string"},
        "target_audience": {"type": "string"},
        "key_differentiators": {"type": "array", "items": {"type": "string"}},
        "pricing_model": {"type": "string"},
        "social_proof": {"type": "array", "items": {"type": "string"}},
        "trust_signals": {"type": "array", "items": {"type": "string"}}
    }
}
