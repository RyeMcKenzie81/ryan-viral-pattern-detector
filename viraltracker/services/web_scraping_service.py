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
    screenshot: Optional[str] = None
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

            # Call scrape with formats + optional params
            scrape_params = {"formats": formats}
            if not only_main_content:
                scrape_params["onlyMainContent"] = False
            if wait_for > 0:
                scrape_params["waitFor"] = wait_for
            result = client.scrape(url, **scrape_params)

            # FireCrawl returns a Document object, not a dict
            # Use getattr to safely access attributes
            return ScrapeResult(
                url=url,
                success=True,
                markdown=getattr(result, 'markdown', None),
                html=getattr(result, 'html', None),
                links=getattr(result, 'links', None),
                metadata=getattr(result, 'metadata', None),
                screenshot=getattr(result, 'screenshot', None),
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

            # Call scrape with formats + optional params
            scrape_params = {"formats": formats}
            if not only_main_content:
                scrape_params["onlyMainContent"] = False
            if wait_for > 0:
                scrape_params["waitFor"] = wait_for
            result = await client.scrape(url, **scrape_params)

            # FireCrawl returns a Document object, not a dict
            # Use getattr to safely access attributes
            return ScrapeResult(
                url=url,
                success=True,
                markdown=getattr(result, 'markdown', None),
                html=getattr(result, 'html', None),
                links=getattr(result, 'links', None),
                metadata=getattr(result, 'metadata', None),
                screenshot=getattr(result, 'screenshot', None),
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
                poll_interval=poll_interval
            )

            results = []
            for item in job.data or []:
                # Items may be Document objects or dicts
                if hasattr(item, 'url'):
                    # Document object
                    results.append(ScrapeResult(
                        url=getattr(item, 'url', ''),
                        success=True,
                        markdown=getattr(item, 'markdown', None),
                        html=getattr(item, 'html', None),
                        links=getattr(item, 'links', None),
                        metadata=getattr(item, 'metadata', None)
                    ))
                else:
                    # Dict
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

    def extract_product_images(
        self,
        url: str,
        min_width: int = 200,
        max_images: int = 10,
        timeout: int = 30000
    ) -> List[str]:
        """
        Extract product image URLs from a landing page.

        Scrapes the page and extracts image URLs that are likely product images
        (filtering out icons, logos, and small images).

        Args:
            url: Landing page URL to scrape
            min_width: Minimum image width to consider (filters icons)
            max_images: Maximum number of images to return
            timeout: Request timeout in milliseconds

        Returns:
            List of image URLs (absolute URLs)
        """
        import re
        from urllib.parse import urljoin, urlparse

        logger.info(f"Extracting product images from: {url}")

        try:
            # Scrape with HTML format to parse images
            result = self.scrape_url(url, formats=["html"], only_main_content=False, timeout=timeout)

            if not result.success or not result.html:
                logger.warning(f"Failed to scrape {url} for images: {result.error}")
                return []

            html = result.html
            base_url = f"{urlparse(url).scheme}://{urlparse(url).netloc}"

            # Extract image URLs using regex (faster than parsing full HTML)
            # Match src attributes in img tags
            img_pattern = r'<img[^>]+src=["\']([^"\']+)["\']'
            srcset_pattern = r'<img[^>]+srcset=["\']([^"\']+)["\']'

            image_urls = set()

            # Extract from src attributes
            for match in re.finditer(img_pattern, html, re.IGNORECASE):
                src = match.group(1)
                if src:
                    image_urls.add(src)

            # Extract from srcset (take largest image)
            for match in re.finditer(srcset_pattern, html, re.IGNORECASE):
                srcset = match.group(1)
                # srcset format: "url1 1x, url2 2x" or "url1 300w, url2 600w"
                parts = [p.strip() for p in srcset.split(',') if p.strip()]
                if parts:
                    # Take the last (usually largest) image
                    last_parts = parts[-1].split()
                    if last_parts:
                        image_urls.add(last_parts[0])

            # Also check for background images in style attributes
            bg_pattern = r'background(?:-image)?:\s*url\(["\']?([^"\')\s]+)["\']?\)'
            for match in re.finditer(bg_pattern, html, re.IGNORECASE):
                bg_url = match.group(1)
                if bg_url:
                    image_urls.add(bg_url)

            # Filter and normalize URLs
            filtered_images = []
            excluded_patterns = [
                r'icon', r'logo', r'sprite', r'favicon', r'avatar',
                r'button', r'arrow', r'close', r'menu', r'nav',
                r'social', r'facebook', r'twitter', r'instagram',
                r'\.svg$', r'\.gif$', r'data:image',
                r'1x1', r'pixel', r'tracking', r'analytics',
                r'shopify.*badge', r'payment.*icon'
            ]

            for img_url in image_urls:
                # Skip data URLs and very short URLs
                if img_url.startswith('data:') or len(img_url) < 10:
                    continue

                # Convert to absolute URL
                if img_url.startswith('//'):
                    img_url = 'https:' + img_url
                elif img_url.startswith('/'):
                    img_url = urljoin(base_url, img_url)
                elif not img_url.startswith('http'):
                    img_url = urljoin(url, img_url)

                # Check against excluded patterns
                img_lower = img_url.lower()
                if any(re.search(pattern, img_lower) for pattern in excluded_patterns):
                    continue

                # Check file extension (prefer jpg, png, webp)
                if not any(ext in img_lower for ext in ['.jpg', '.jpeg', '.png', '.webp']):
                    continue

                filtered_images.append(img_url)

            # Remove duplicates while preserving order
            seen = set()
            unique_images = []
            for img in filtered_images:
                # Normalize for deduplication
                normalized = img.split('?')[0].lower()
                if normalized not in seen:
                    seen.add(normalized)
                    unique_images.append(img)

            logger.info(f"Extracted {len(unique_images)} product images from {url}")
            return unique_images[:max_images]

        except Exception as e:
            logger.error(f"Failed to extract images from {url}: {e}")
            return []


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
