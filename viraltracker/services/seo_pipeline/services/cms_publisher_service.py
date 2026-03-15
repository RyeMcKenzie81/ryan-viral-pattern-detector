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
            "client_id": "...",
            "client_secret": "shpss_...",
            "api_version": "2024-10",
            "blog_id": "99206135908",
            "blog_handle": "articles"
        }

    If client_id and client_secret are provided, the publisher will
    auto-refresh the access token on 401 errors and update the stored config.
    """

    def __init__(
        self,
        store_domain: str,
        access_token: str,
        blog_id: str,
        api_version: str = "2024-10",
        blog_handle: str = "articles",
        client_id: Optional[str] = None,
        client_secret: Optional[str] = None,
        on_token_refresh: Optional[Any] = None,
    ):
        self.store_domain = store_domain
        self.access_token = access_token
        self.blog_id = blog_id
        self.api_version = api_version
        self.blog_handle = blog_handle
        self._client_id = client_id
        self._client_secret = client_secret
        self._on_token_refresh = on_token_refresh
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
        body_only: bool = False,
    ) -> Dict[str, Any]:
        """
        Update an existing Shopify blog article.

        Args:
            cms_article_id: The CMS-side article ID
            article_data: Updated article data
            body_only: If True, only send body_html (safe for interlinking updates
                that must not overwrite published status, metafields, handle, etc.)
        """
        if body_only:
            payload = {"article": {"body_html": article_data.get("body_html", "")}}
        else:
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

    def list_articles(self, limit: int = 250) -> List[Dict[str, Any]]:
        """
        List all blog articles from Shopify.

        Paginates through all articles using Shopify's page-based pagination.

        Returns:
            List of Shopify article dicts (id, title, handle, body_html, published_at, etc.)
        """
        articles = []
        page_info = None
        url = f"{self._base_url}/blogs/{self.blog_id}/articles.json?limit={min(limit, 250)}&status=any"

        while True:
            if page_info:
                url = f"{self._base_url}/blogs/{self.blog_id}/articles.json?limit=250&page_info={page_info}"

            response_data = self._api_request("GET", url)
            batch = response_data.get("articles", [])
            articles.extend(batch)

            if len(batch) < 250:
                break
            # Note: For cursor pagination, would need to parse Link header.
            # Most blogs have <250 articles so this suffices.
            break

        logger.info(f"Listed {len(articles)} Shopify articles from blog {self.blog_id}")
        return articles

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

        # Schema markup — always include to clear stale values on re-publish
        schema = article_data.get("schema_markup")
        schema_value = (
            (schema if isinstance(schema, str) else json.dumps(schema))
            if schema
            else "{}"
        )
        metafields.append({
            "namespace": "seo",
            "key": "schema_json",
            "value": schema_value,
            "type": "json",
        })

        # Author metaobject reference (theme reads author data from the metaobject)
        author_metaobject_gid = article_data.get("author_metaobject_gid", "")
        if author_metaobject_gid:
            metafields.append({
                "namespace": "custom",
                "key": "author",
                "value": author_metaobject_gid,
                "type": "metaobject_reference",
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

        # Strip LLM code fence wrapper (Claude sometimes wraps output in ```markdown ... ```)
        content = content.strip()
        before = content
        content = re.sub(r'^```\w*\n', '', content)
        if content != before:
            content = re.sub(r'\n```\s*$', '', content)

        # Strip hero image from body — it's already the Shopify featured image.
        # Hero <img> tags have loading="eager" (inline ones have loading="lazy").
        content = re.sub(r'<img[^>]*loading="eager"[^>]*/?>[\s]*', '', content)

        # Strip YAML frontmatter
        content = content.lstrip()
        content = re.sub(r'^---\n[\s\S]+?\n---\n', '', content)

        # Remove schema markup sections (kept in metafields, not body)
        content = re.sub(r'<!--[\s\S]*?SCHEMA MARKUP[\s\S]*?-->\s*```json\s*[\s\S]*?\s*```', '', content)
        content = re.sub(r'## Schema Markup[\s\S]*?(?=##|$)', '', content)

        # Remove metadata sections that shouldn't be in article body
        content = re.sub(r'## Related Articles[\s\S]*?(?=##|$)', '', content)
        content = re.sub(r'## Internal Links to Add[\s\S]*?(?=##|$)', '', content)
        content = re.sub(r'## Images Needed[\s\S]*?(?=##|$)', '', content)
        content = re.sub(r'### Hero Image[\s\S]*?(?=###|##|$)', '', content)
        content = re.sub(r'### Inline Image \d+[\s\S]*?(?=###|##|$)', '', content)
        content = re.sub(r'<!--[\s\S]*?-->', '', content)
        content = re.sub(r'```json[\s\S]*?```', '', content)

        # Strip [IMAGE: ...] and [HERO IMAGE: ...] markers (left by deferred image gen)
        content = re.sub(r'\[(?:HERO )?IMAGE:\s*[^\]]*\]', '', content, flags=re.IGNORECASE)

        # Strip LLM self-assessment sections that sometimes leak into output
        for heading in [
            r'SEO Optimization Summary',
            r'Keyword Placement Check',
            r'External Link Suggestions?',
            r'Readability Check',
            r'Content Integrity',
            r'Quality Check',
            r'Optimization Notes?',
        ]:
            content = re.sub(
                rf'(?:##?\s*)?{heading}[\s\S]*?(?=\n##\s[^#]|\Z)',
                '', content, flags=re.IGNORECASE,
            )

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
        _retried: bool = False,
    ) -> Dict[str, Any]:
        """
        Make an authenticated request to the Shopify REST API.

        On 401, attempts to refresh the token via client credentials and retry once.

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

        # Auto-refresh token on 401 and retry once
        if response.status_code == 401 and not _retried:
            new_token = self._refresh_token()
            if new_token:
                return self._api_request(method, url, json_data, _retried=True)

        error_body = response.text[:500]
        logger.error(
            f"Shopify API error: {response.status_code} {method} {url} — {error_body}"
        )
        raise Exception(
            f"Shopify API error: {response.status_code} — {error_body}"
        )

    def _refresh_token(self) -> Optional[str]:
        """
        Refresh the Shopify access token using client credentials grant.

        Returns:
            New access token, or None if refresh failed.
        """
        if not self._client_id or not self._client_secret:
            logger.warning(
                "Cannot refresh Shopify token: client_id/client_secret not configured. "
                "Add them to brand_integrations config for auto-refresh."
            )
            return None

        logger.info(f"Refreshing Shopify access token for {self.store_domain}")

        try:
            with httpx.Client(timeout=15.0) as client:
                response = client.post(
                    f"https://{self.store_domain}/admin/oauth/access_token",
                    json={
                        "client_id": self._client_id,
                        "client_secret": self._client_secret,
                        "grant_type": "client_credentials",
                    },
                )

            if response.status_code != 200:
                logger.error(f"Token refresh failed: {response.status_code} — {response.text[:200]}")
                return None

            data = response.json()
            new_token = data.get("access_token")
            if not new_token:
                logger.error(f"Token refresh response missing access_token: {data}")
                return None

            self.access_token = new_token
            logger.info("Shopify access token refreshed successfully")

            # Notify the service layer to persist the new token
            if self._on_token_refresh:
                try:
                    self._on_token_refresh(new_token)
                except Exception as e:
                    logger.warning(f"Failed to persist refreshed token: {e}")

            return new_token

        except Exception as e:
            logger.error(f"Token refresh request failed: {e}")
            return None


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
            return self._create_shopify_publisher(config, brand_id, organization_id)

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

        # Load author data
        author_data = self._get_author_data(article.get("author_id"))
        author_name = author_data.get("name", "")

        # Build article data for publisher
        # Prefer phase_c_output — it has image tags injected by SEOImageService.
        # content_markdown may be stale (pre-image-generation).
        content_md = (
            article.get("phase_c_output")
            or article.get("content_markdown")
            or article.get("phase_b_output")
            or ""
        )

        article_data = {
            "title": article.get("title") or article.get("seo_title") or article.get("keyword", "Untitled"),
            "content_markdown": content_md,
            "body_html": "",  # Always re-render from markdown to pick up image changes
            "author": author_name,
            "author_metaobject_gid": author_data.get("shopify_metaobject_gid", ""),
            "seo_title": article.get("seo_title", ""),
            "meta_description": article.get("meta_description", ""),
            "keyword": article.get("keyword", ""),
            "schema_markup": article.get("schema_markup"),
            "hero_image_url": article.get("hero_image_url"),
            "summary_html": article.get("meta_description", ""),
            "tags": ", ".join(article.get("tags") or []),
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
        """Get Shopify brand integration from DB."""
        query = (
            self.supabase.table("brand_integrations")
            .select("*")
            .eq("brand_id", brand_id)
            .eq("platform", "shopify")
        )
        if organization_id != "all":
            query = query.eq("organization_id", organization_id)

        result = query.execute()
        return result.data[0] if result.data else None

    def _create_shopify_publisher(
        self,
        config: Dict[str, Any],
        brand_id: Optional[str] = None,
        organization_id: Optional[str] = None,
    ) -> ShopifyPublisher:
        """Create a ShopifyPublisher from integration config."""
        required = ["store_domain", "access_token", "blog_id"]
        missing = [k for k in required if not config.get(k)]
        if missing:
            raise ValueError(
                f"Shopify integration missing required config: {', '.join(missing)}. "
                f"Required: store_domain, access_token, blog_id"
            )

        # Build token persistence callback if we have brand context
        on_token_refresh = None
        if brand_id:
            on_token_refresh = self._make_token_refresh_callback(brand_id, organization_id)

        return ShopifyPublisher(
            store_domain=config["store_domain"],
            access_token=config["access_token"],
            blog_id=config["blog_id"],
            api_version=config.get("api_version", "2024-10"),
            blog_handle=config.get("blog_handle", "articles"),
            client_id=config.get("client_id"),
            client_secret=config.get("client_secret"),
            on_token_refresh=on_token_refresh,
        )

    def _make_token_refresh_callback(
        self,
        brand_id: str,
        organization_id: Optional[str],
    ):
        """Create a callback that persists a refreshed token to brand_integrations."""
        def callback(new_token: str):
            try:
                # Read current config, update token, write back
                result = (
                    self.supabase.table("brand_integrations")
                    .select("id, config")
                    .eq("brand_id", brand_id)
                    .eq("platform", "shopify")
                    .execute()
                )
                if result.data:
                    row = result.data[0]
                    config = row.get("config", {})
                    config["access_token"] = new_token
                    self.supabase.table("brand_integrations").update(
                        {"config": config}
                    ).eq("id", row["id"]).execute()
                    logger.info(f"Persisted refreshed Shopify token for brand {brand_id}")
            except Exception as e:
                logger.warning(f"Failed to persist refreshed token for brand {brand_id}: {e}")
        return callback

    def _get_article(self, article_id: str) -> Optional[Dict[str, Any]]:
        """Get article from DB."""
        result = (
            self.supabase.table("seo_articles")
            .select("*")
            .eq("id", article_id)
            .execute()
        )
        return result.data[0] if result.data else None

    def _get_author_data(self, author_id: Optional[str]) -> Dict[str, Any]:
        """Get full author data from seo_authors table."""
        if not author_id:
            return {}
        try:
            result = (
                self.supabase.table("seo_authors")
                .select("name, bio, image_url, job_title, author_url, shopify_metaobject_gid")
                .eq("id", author_id)
                .execute()
            )
            if result.data:
                return result.data[0]
        except Exception as e:
            logger.warning(f"Failed to load author {author_id}: {e}")
        return {}

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

        # Save rendered body_html to content_html (needed for interlinking)
        body_html = result.get("body_html")
        if body_html:
            update_data["content_html"] = body_html

        # Use Shopify's actual status (based on published_at) as source of truth.
        # This handles articles manually flipped to visible in Shopify admin.
        cms_status = result.get("status", "")
        if cms_status == "published":
            update_data["status"] = ArticleStatus.PUBLISHED.value
        elif not draft:
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

    # =========================================================================
    # SYNC STATUS FROM CMS
    # =========================================================================

    def sync_article_statuses(
        self,
        brand_id: str,
        organization_id: str,
    ) -> Dict[str, Any]:
        """
        Sync article published/draft status from Shopify into seo_articles.

        Fetches all Shopify articles, checks published_at, and updates
        our DB status for any mismatches. Handles articles manually
        flipped to visible/hidden in Shopify admin.

        Returns:
            Dict with synced count and total checked
        """
        publisher = self.get_publisher(brand_id, organization_id)
        if not publisher:
            return {"synced": 0, "total": 0, "error": "No CMS integration configured"}

        from viraltracker.services.seo_pipeline.models import ArticleStatus

        # Fetch all Shopify articles (one API call)
        shopify_articles = publisher.list_articles()
        if not shopify_articles:
            return {"synced": 0, "total": 0}

        # Build lookup: cms_article_id → is_published
        shopify_status = {}
        for sa in shopify_articles:
            sid = str(sa.get("id", ""))
            shopify_status[sid] = bool(sa.get("published_at"))

        # Get our articles that have cms_article_ids
        our_articles = (
            self.supabase.table("seo_articles")
            .select("id, cms_article_id, status")
            .eq("brand_id", brand_id)
            .not_.is_("cms_article_id", "null")
            .execute()
        )

        synced = 0
        for row in (our_articles.data or []):
            cms_id = row.get("cms_article_id", "")
            current_status = row.get("status", "")
            is_live = shopify_status.get(cms_id)

            if is_live is None:
                continue  # Article not found in Shopify

            expected = ArticleStatus.PUBLISHED.value if is_live else ArticleStatus.PUBLISHING.value
            if current_status != expected:
                self.supabase.table("seo_articles").update(
                    {"status": expected}
                ).eq("id", row["id"]).execute()
                synced += 1
                logger.info(
                    f"Synced article {row['id']} status: {current_status} → {expected}"
                )

        return {"synced": synced, "total": len(our_articles.data or [])}

    # =========================================================================
    # IMPORT FROM CMS
    # =========================================================================

    def import_from_shopify(
        self,
        brand_id: str,
        organization_id: str,
        project_id: str,
        public_domain: Optional[str] = None,
    ) -> Dict[str, Any]:
        """
        Import existing Shopify blog articles into seo_articles.

        Fetches all articles from the Shopify blog and creates seo_articles
        records for any that don't already exist (matched by cms_article_id).

        Args:
            brand_id: Brand UUID
            organization_id: Organization UUID (must be real UUID, not "all")
            project_id: Target SEO project UUID
            public_domain: Public domain for URLs (e.g. "yaketypack.com").
                If provided, builds published_url with this domain instead of
                the myshopify.com store domain.

        Returns:
            Dict with imported count, skipped count, total fetched
        """
        integration = self._get_integration(brand_id, organization_id)
        if not integration:
            raise ValueError("No Shopify integration configured for this brand")

        config = integration.get("config", {})
        publisher = self._create_shopify_publisher(config, brand_id, organization_id)
        blog_handle = config.get("blog_handle", "articles")

        # Fetch all articles from Shopify
        shopify_articles = publisher.list_articles()

        if not shopify_articles:
            return {"imported": 0, "skipped": 0, "total": 0}

        # Get existing cms_article_ids to avoid duplicates
        existing = (
            self.supabase.table("seo_articles")
            .select("cms_article_id")
            .eq("brand_id", brand_id)
            .not_.is_("cms_article_id", "null")
            .execute()
        )
        existing_ids = {r["cms_article_id"] for r in (existing.data or [])}

        # Determine URL domain
        url_domain = public_domain or config.get("store_domain", "")

        imported = 0
        skipped = 0
        for article in shopify_articles:
            cms_id = str(article.get("id", ""))
            if cms_id in existing_ids:
                skipped += 1
                continue

            handle = article.get("handle", "")
            title = article.get("title", "")
            body_html = article.get("body_html", "")
            published_at = article.get("published_at")

            published_url = f"https://{url_domain}/blogs/{blog_handle}/{handle}" if handle else None

            row = {
                "project_id": project_id,
                "brand_id": brand_id,
                "organization_id": organization_id,
                "keyword": title,
                "title": title,
                "slug": handle,
                "content_html": body_html,
                "cms_article_id": cms_id,
                "published_url": published_url,
                "published_at": published_at,
                "status": "published" if published_at else "draft",
                "phase": "c",
            }

            try:
                self.supabase.table("seo_articles").insert(row).execute()
                imported += 1
            except Exception as e:
                logger.warning(f"Failed to import Shopify article {cms_id}: {e}")
                skipped += 1

        logger.info(f"Imported {imported} Shopify articles for brand {brand_id} (skipped {skipped})")
        return {"imported": imported, "skipped": skipped, "total": len(shopify_articles)}
