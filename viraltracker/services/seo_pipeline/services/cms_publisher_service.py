"""
CMS Publisher Service - Abstract CMS publishing with Shopify implementation.

Publishes SEO articles to CMS platforms. Currently supports Shopify via REST API.

Architecture:
- CMSPublisher ABC: Abstract base for CMS implementations
- ShopifyPublisher: Shopify REST API v2024-10 via httpx
- CMSPublisherService: Factory that loads publisher from brand_integrations

Ported from seo-pipeline/publisher/convert-and-publish.js.

Shopify API details:
- Create: POST /admin/api/{version}/blogs/{blog_id}/articles.json
- Update: PUT /admin/api/{version}/articles/{article_id}.json
- Auth: X-Shopify-Access-Token header (client credentials custom app)
- Metafields: global.title_tag, global.description_tag, seo.schema_json
"""

import json
import logging
import re
from abc import ABC, abstractmethod
from typing import Dict, Any, Optional, List

import httpx

logger = logging.getLogger(__name__)


# =============================================================================
# ABSTRACT BASE
# =============================================================================


class CMSPublisher(ABC):
    """Abstract base class for CMS publishers."""

    @abstractmethod
    def publish(
        self,
        article_data: Dict[str, Any],
        draft: bool = True,
    ) -> Dict[str, Any]:
        """
        Publish an article to the CMS.

        Args:
            article_data: Article data dict with keys:
                - title: Article title
                - body_html: HTML content
                - author: Author name
                - seo_title: SEO title tag
                - meta_description: Meta description
                - keyword: Target keyword
                - tags: Comma-separated tags
                - schema_markup: Schema.org JSON-LD (optional)
                - hero_image_url: Featured image URL (optional)
                - summary_html: Article excerpt (optional)
                - handle: URL slug (optional, generated from keyword)
            draft: If True, publish as draft. If False, publish live.

        Returns:
            Dict with cms_article_id, published_url, admin_url, status
        """
        ...

    @abstractmethod
    def update(
        self,
        cms_article_id: str,
        article_data: Dict[str, Any],
    ) -> Dict[str, Any]:
        """
        Update an existing article in the CMS.

        Args:
            cms_article_id: The CMS-side article ID
            article_data: Updated article data (same format as publish)

        Returns:
            Dict with cms_article_id, published_url, admin_url, status
        """
        ...

    @abstractmethod
    def get_article(self, cms_article_id: str) -> Optional[Dict[str, Any]]:
        """
        Fetch an article from the CMS.

        Args:
            cms_article_id: The CMS-side article ID

        Returns:
            Article data dict or None
        """
        ...


# =============================================================================
# SHOPIFY PUBLISHER
# =============================================================================


class ShopifyPublisher(CMSPublisher):
    """
    Shopify REST API publisher for blog articles.

    Uses Shopify REST Admin API v2024-10 via httpx.
    Credentials come from brand_integrations table (per-brand config).

    Config format (from brand_integrations.config JSONB):
        {
            "store_domain": "mystore.myshopify.com",
            "access_token": "shpat_...",
            "api_version": "2024-10",
            "blog_id": "99206135908",
            "blog_handle": "articles"
        }
    """

    def __init__(
        self,
        store_domain: str,
        access_token: str,
        blog_id: str,
        api_version: str = "2024-10",
        blog_handle: str = "articles",
    ):
        self.store_domain = store_domain
        self.access_token = access_token
        self.blog_id = blog_id
        self.api_version = api_version
        self.blog_handle = blog_handle
        self._base_url = f"https://{store_domain}/admin/api/{api_version}"

    def publish(
        self,
        article_data: Dict[str, Any],
        draft: bool = True,
    ) -> Dict[str, Any]:
        """Publish article to Shopify as a blog post."""
        payload = self._build_article_payload(article_data, draft=draft)
        url = f"{self._base_url}/blogs/{self.blog_id}/articles.json"

        response = self._api_request("POST", url, payload)
        article = response.get("article", {})

        article_id = str(article.get("id", ""))
        handle = article.get("handle", "")

        # Build public URL from store domain
        # Strip .myshopify.com for public URL (custom domain may differ)
        public_url = f"https://{self.store_domain}/blogs/{self.blog_handle}/{handle}"

        result = {
            "cms_article_id": article_id,
            "handle": handle,
            "published_url": public_url,
            "admin_url": f"https://{self.store_domain}/admin/articles/{article_id}",
            "status": "draft" if draft else "published",
            "created_at": article.get("created_at"),
        }

        logger.info(
            f"Published article to Shopify: {article_id} "
            f"({'draft' if draft else 'live'})"
        )
        return result

    def update(
        self,
        cms_article_id: str,
        article_data: Dict[str, Any],
    ) -> Dict[str, Any]:
        """Update an existing Shopify blog article."""
        payload = self._build_article_payload(article_data)
        url = f"{self._base_url}/articles/{cms_article_id}.json"

        response = self._api_request("PUT", url, payload)
        article = response.get("article", {})

        handle = article.get("handle", "")
        public_url = f"https://{self.store_domain}/blogs/{self.blog_handle}/{handle}"

        result = {
            "cms_article_id": str(article.get("id", cms_article_id)),
            "handle": handle,
            "published_url": public_url,
            "admin_url": f"https://{self.store_domain}/admin/articles/{cms_article_id}",
            "status": "published" if article.get("published_at") else "draft",
            "updated_at": article.get("updated_at"),
        }

        logger.info(f"Updated Shopify article: {cms_article_id}")
        return result

    def get_article(self, cms_article_id: str) -> Optional[Dict[str, Any]]:
        """Fetch a Shopify blog article by ID."""
        url = f"{self._base_url}/articles/{cms_article_id}.json"
        try:
            response = self._api_request("GET", url)
            return response.get("article")
        except Exception as e:
            logger.warning(f"Failed to fetch Shopify article {cms_article_id}: {e}")
            return None

    # =========================================================================
    # PAYLOAD BUILDING
    # =========================================================================

    def _build_article_payload(
        self,
        article_data: Dict[str, Any],
        draft: bool = True,
    ) -> Dict[str, Any]:
        """
        Build Shopify article JSON payload.

        Matches the format used by the original convert-and-publish.js.
        """
        title = article_data.get("title", "Untitled")
        keyword = article_data.get("keyword", "")

        # Generate URL handle from keyword or title
        handle = article_data.get("handle") or self._generate_handle(keyword or title)

        # Build body HTML
        body_html = article_data.get("body_html", "")
        if not body_html and article_data.get("content_markdown"):
            body_html = self._markdown_to_html(article_data["content_markdown"])

        # Build metafields
        metafields = self._build_metafields(article_data)

        # Build article payload
        article = {
            "title": title,
            "author": article_data.get("author", ""),
            "body_html": body_html,
            "handle": handle,
            "published": not draft,
            "metafields": metafields,
        }

        # Optional fields
        tags = article_data.get("tags")
        if tags:
            article["tags"] = tags

        summary = article_data.get("summary_html")
        if summary:
            article["summary_html"] = summary

        hero_url = article_data.get("hero_image_url")
        if hero_url:
            article["image"] = {"src": hero_url}

        return {"article": article}

    def _build_metafields(self, article_data: Dict[str, Any]) -> List[Dict[str, Any]]:
        """
        Build Shopify metafields for SEO metadata.

        Sets:
        - global.title_tag: SEO title
        - global.description_tag: Meta description
        - seo.schema_json: Schema.org JSON-LD (if present)
        """
        metafields = []

        seo_title = article_data.get("seo_title", article_data.get("title", ""))
        if seo_title:
            metafields.append({
                "namespace": "global",
                "key": "title_tag",
                "value": seo_title,
                "type": "single_line_text_field",
            })

        meta_desc = article_data.get("meta_description", "")
        if meta_desc:
            metafields.append({
                "namespace": "global",
                "key": "description_tag",
                "value": meta_desc,
                "type": "single_line_text_field",
            })

        schema = article_data.get("schema_markup")
        if schema:
            schema_value = schema if isinstance(schema, str) else json.dumps(schema)
            metafields.append({
                "namespace": "seo",
                "key": "schema_json",
                "value": schema_value,
                "type": "json",
            })

        return metafields

    # =========================================================================
    # HELPERS
    # =========================================================================

    @staticmethod
    def _markdown_to_html(markdown_text: str) -> str:
        """
        Convert markdown to HTML using markdown-it-py.

        Strips frontmatter, schema blocks, and metadata sections
        before converting (matches original convert-and-publish.js behavior).
        """
        content = markdown_text

        # Strip YAML frontmatter
        content = re.sub(r'^---\n[\s\S]+?\n---\n', '', content)

        # Remove schema markup sections (kept in metafields, not body)
        content = re.sub(r'<!--[\s\S]*?SCHEMA MARKUP[\s\S]*?-->\s*```json\s*[\s\S]*?\s*```', '', content)
        content = re.sub(r'## Schema Markup[\s\S]*?(?=##|$)', '', content)

        # Remove metadata sections that shouldn't be in article body
        content = re.sub(r'## Internal Links to Add[\s\S]*?(?=##|$)', '', content)
        content = re.sub(r'## Images Needed[\s\S]*?(?=##|$)', '', content)
        content = re.sub(r'### Hero Image[\s\S]*?(?=###|##|$)', '', content)
        content = re.sub(r'### Inline Image \d+[\s\S]*?(?=###|##|$)', '', content)
        content = re.sub(r'<!--[\s\S]*?-->', '', content)
        content = re.sub(r'```json[\s\S]*?```', '', content)

        # Remove author bio if present (added via template)
        content = re.sub(r'---\s*\n\s*\*\*About the Author:[\s\S]*$', '', content)
        content = re.sub(r'\*\*Last Updated:\*\*.*$', '', content, flags=re.MULTILINE)

        try:
            from markdown_it import MarkdownIt
            md = MarkdownIt()
            html = md.render(content)
        except ImportError:
            logger.warning("markdown-it-py not available, returning raw content")
            html = content

        # Add responsive image styling
        html = f'<style>img {{ max-width: 100%; height: auto; display: block; margin: 2rem auto; border-radius: 8px; }}</style>\n{html}'

        return html

    @staticmethod
    def _generate_handle(text: str) -> str:
        """Generate URL-safe handle from text (matches original JS behavior)."""
        handle = text.lower()
        handle = re.sub(r'[^a-z0-9]+', '-', handle)
        handle = handle.strip('-')
        return handle

    def _api_request(
        self,
        method: str,
        url: str,
        json_data: Optional[Dict[str, Any]] = None,
    ) -> Dict[str, Any]:
        """
        Make an authenticated request to the Shopify REST API.

        Args:
            method: HTTP method (GET, POST, PUT)
            url: Full API URL
            json_data: Request body (for POST/PUT)

        Returns:
            Parsed JSON response

        Raises:
            Exception: On API errors (4xx, 5xx)
        """
        headers = {
            "X-Shopify-Access-Token": self.access_token,
            "Content-Type": "application/json",
        }

        with httpx.Client(timeout=30.0) as client:
            response = client.request(
                method=method,
                url=url,
                headers=headers,
                json=json_data if method in ("POST", "PUT") else None,
            )

        if response.status_code in (200, 201):
            return response.json()

        error_body = response.text[:500]
        logger.error(
            f"Shopify API error: {response.status_code} {method} {url} — {error_body}"
        )
        raise Exception(
            f"Shopify API error: {response.status_code} — {error_body}"
        )


# =============================================================================
# PUBLISHER SERVICE (FACTORY)
# =============================================================================


class CMSPublisherService:
    """
    Factory service that creates the right CMS publisher for a brand.

    Reads brand_integrations table to get CMS credentials,
    then creates the appropriate publisher instance.
    """

    def __init__(self, supabase_client=None):
        self._supabase = supabase_client

    @property
    def supabase(self):
        """Lazy-load Supabase client."""
        if self._supabase is None:
            from viraltracker.core.database import get_supabase_client
            self._supabase = get_supabase_client()
        return self._supabase

    def get_publisher(
        self,
        brand_id: str,
        organization_id: str,
    ) -> Optional[CMSPublisher]:
        """
        Get the CMS publisher for a brand.

        Looks up brand_integrations for the brand's configured CMS platform
        and returns an initialized publisher instance.

        Args:
            brand_id: Brand UUID
            organization_id: Organization UUID for access control

        Returns:
            CMSPublisher instance or None if no integration configured
        """
        integration = self._get_integration(brand_id, organization_id)
        if not integration:
            return None

        platform = integration.get("platform", "")
        config = integration.get("config", {})

        if platform == "shopify":
            return self._create_shopify_publisher(config)

        logger.warning(f"Unsupported CMS platform: {platform}")
        return None

    def publish_article(
        self,
        article_id: str,
        brand_id: str,
        organization_id: str,
        draft: bool = True,
    ) -> Dict[str, Any]:
        """
        Publish an article to its brand's configured CMS.

        Loads the article from DB, gets the publisher, converts content,
        publishes (or updates if already published), and saves the CMS ID back.

        Args:
            article_id: Article UUID
            brand_id: Brand UUID
            organization_id: Organization UUID
            draft: If True, publish as draft

        Returns:
            Dict with publishing result
        """
        publisher = self.get_publisher(brand_id, organization_id)
        if not publisher:
            raise ValueError(
                f"No CMS integration configured for brand {brand_id}. "
                "Set up Shopify integration in brand settings."
            )

        article = self._get_article(article_id)
        if not article:
            raise ValueError(f"Article not found: {article_id}")

        # Load author name
        author_name = self._get_author_name(article.get("author_id"))

        # Build article data for publisher
        content_md = (
            article.get("content_markdown")
            or article.get("phase_c_output")
            or article.get("phase_b_output")
            or ""
        )

        article_data = {
            "title": article.get("title") or article.get("seo_title") or article.get("keyword", "Untitled"),
            "content_markdown": content_md,
            "body_html": article.get("content_html", ""),
            "author": author_name,
            "seo_title": article.get("seo_title", ""),
            "meta_description": article.get("meta_description", ""),
            "keyword": article.get("keyword", ""),
            "schema_markup": article.get("schema_markup"),
            "hero_image_url": article.get("hero_image_url"),
            "summary_html": article.get("summary_html", ""),
        }

        # Check if already published (update vs create)
        cms_article_id = article.get("cms_article_id")
        if cms_article_id:
            result = publisher.update(cms_article_id, article_data)
        else:
            result = publisher.publish(article_data, draft=draft)

        # Save CMS data back to article
        self._update_article_cms_data(article_id, result, draft)

        return result

    # =========================================================================
    # HELPERS
    # =========================================================================

    def _get_integration(
        self,
        brand_id: str,
        organization_id: str,
    ) -> Optional[Dict[str, Any]]:
        """Get brand integration from DB."""
        query = (
            self.supabase.table("brand_integrations")
            .select("*")
            .eq("brand_id", brand_id)
        )
        if organization_id != "all":
            query = query.eq("organization_id", organization_id)

        result = query.execute()
        return result.data[0] if result.data else None

    def _create_shopify_publisher(self, config: Dict[str, Any]) -> ShopifyPublisher:
        """Create a ShopifyPublisher from integration config."""
        required = ["store_domain", "access_token", "blog_id"]
        missing = [k for k in required if not config.get(k)]
        if missing:
            raise ValueError(
                f"Shopify integration missing required config: {', '.join(missing)}. "
                f"Required: store_domain, access_token, blog_id"
            )

        return ShopifyPublisher(
            store_domain=config["store_domain"],
            access_token=config["access_token"],
            blog_id=config["blog_id"],
            api_version=config.get("api_version", "2024-10"),
            blog_handle=config.get("blog_handle", "articles"),
        )

    def _get_article(self, article_id: str) -> Optional[Dict[str, Any]]:
        """Get article from DB."""
        result = (
            self.supabase.table("seo_articles")
            .select("*")
            .eq("id", article_id)
            .execute()
        )
        return result.data[0] if result.data else None

    def _get_author_name(self, author_id: Optional[str]) -> str:
        """Get author name from seo_authors table."""
        if not author_id:
            return ""
        try:
            result = (
                self.supabase.table("seo_authors")
                .select("name")
                .eq("id", author_id)
                .execute()
            )
            if result.data:
                return result.data[0].get("name", "")
        except Exception as e:
            logger.warning(f"Failed to load author {author_id}: {e}")
        return ""

    def _update_article_cms_data(
        self,
        article_id: str,
        result: Dict[str, Any],
        draft: bool,
    ) -> None:
        """Save CMS publishing data back to seo_articles."""
        from viraltracker.services.seo_pipeline.models import ArticleStatus

        update_data = {
            "cms_article_id": result.get("cms_article_id"),
            "published_url": result.get("published_url"),
        }

        if not draft:
            update_data["status"] = ArticleStatus.PUBLISHED.value
        else:
            update_data["status"] = ArticleStatus.PUBLISHING.value

        try:
            self.supabase.table("seo_articles").update(
                update_data
            ).eq("id", article_id).execute()
            logger.info(f"Updated article {article_id} with CMS data: {result.get('cms_article_id')}")
        except Exception as e:
            logger.error(f"Failed to update article CMS data for {article_id}: {e}")
            raise
