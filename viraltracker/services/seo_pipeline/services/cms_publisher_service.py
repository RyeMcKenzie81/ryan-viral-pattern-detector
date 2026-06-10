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
# STANDALONE HELPERS
# =============================================================================


def render_markdown_to_html(content: str) -> str:
    """
    Convert markdown to clean HTML. Strips frontmatter, code fences, markers, metadata.

    This is a pure text transformation (markdown-it-py + regex stripping) with no
    CMS dependency — safe to call from any service layer.
    """
    # Normalize line endings (API responses may use \r\n)
    text = content.replace('\r\n', '\n')

    # Strip hero image from body FIRST — it's already the Shopify featured image.
    text = re.sub(r'<img[^>]*loading="eager"[^>]*/?>[\s]*', '', text)

    text = text.strip()

    # Strip LLM code fence wrappers. The model wraps its output in a ```markdown
    # fence in two different ways, and BOTH must be handled or the article gets
    # published as raw markdown inside a <pre> block:
    #
    #   (a) Whole-document wrapper — ```markdown at the very top, ``` at the very
    #       bottom, everything in between.
    #   (b) Frontmatter-only wrapper — ```markdown, the YAML frontmatter, then a
    #       closing ``` *right after the frontmatter*, with the article body
    #       outside the fence.
    #
    # Case (b) is the dangerous one: stripping only the opening fence leaves an
    # orphaned closing ``` that, once the frontmatter is removed, becomes the
    # first line of the body. markdown-it then reads it as the start of a fenced
    # code block with no terminator and swallows the ENTIRE article into
    # <pre><code>…</code></pre>. (Observed in production: bug fix 2026-06.)

    # Case (b): unwrap a fence that contains only the frontmatter.
    text = re.sub(
        r'^```\w*[ \t]*\n(---\n[\s\S]+?\n---)[ \t]*\n```[ \t]*\n',
        r'\1\n',
        text,
    )

    # Case (a): whole-document wrapper — strip opening fence, and the matching
    # closing fence only if the opening one was actually present.
    before = text
    text = re.sub(r'^```\w*\n', '', text)
    if text != before:
        text = re.sub(r'\n```\s*$', '', text)

    # Strip YAML frontmatter
    text = text.lstrip()
    text = re.sub(r'^---\n[\s\S]+?\n---\n?', '', text)

    # Defensive guard: a single orphaned code fence at the start of the body
    # makes markdown-it swallow the whole article into one <pre> block. This
    # happens when an LLM wraps only the frontmatter in a ```fence (the closing
    # ``` is left behind once the frontmatter is removed). Only strip a LEADING
    # fence when the total number of fences is ODD — i.e. genuinely unbalanced —
    # so we never eat the opening fence of a legitimate, balanced code block that
    # an article body might actually contain.
    text = text.lstrip()
    if text.startswith('```'):
        fence_count = len(re.findall(r'(?m)^```', text))
        if fence_count % 2 == 1:
            text = re.sub(r'^```\w*[ \t]*\n', '', text)
            text = text.lstrip()

    # Remove schema markup sections
    text = re.sub(r'<!--[\s\S]*?SCHEMA MARKUP[\s\S]*?-->\s*```json\s*[\s\S]*?\s*```', '', text)
    text = re.sub(r'## Schema Markup[\s\S]*?(?=##|$)', '', text)

    # Remove metadata sections
    text = re.sub(r'## Related Articles[\s\S]*?(?=##|$)', '', text)
    text = re.sub(r'## Internal Links to Add[\s\S]*?(?=##|$)', '', text)
    text = re.sub(r'## Images Needed[\s\S]*?(?=##|$)', '', text)
    text = re.sub(r'### Hero Image[\s\S]*?(?=###|##|$)', '', text)
    text = re.sub(r'### Inline Image \d+[\s\S]*?(?=###|##|$)', '', text)
    text = re.sub(r'<!--[\s\S]*?-->', '', text)
    text = re.sub(r'```json[\s\S]*?```', '', text)

    # Strip [IMAGE: ...] and [HERO IMAGE: ...] markers
    text = re.sub(r'\[(?:HERO )?IMAGE:\s*[^\]]*\]', '', text, flags=re.IGNORECASE)

    # Convert [LINK: anchor](url) internal-link suggestion markers into real
    # markdown links by dropping the "LINK: " prefix. The Phase C prompt emits
    # links as [LINK: anchor](url); without this, markdown-it renders the prefix
    # into the visible anchor text (<a href="url">LINK: anchor</a>). Only the
    # bracketed label is touched; the (url) part is left for markdown to render.
    text = re.sub(r'\[LINK:\s*([^\]]+)\]', r'[\1]', text, flags=re.IGNORECASE)

    # Strip LLM self-assessment sections
    for heading in [
        r'SEO Optimization Summary',
        r'Keyword Placement Check',
        r'External Link Suggestions?',
        r'Readability Check',
        r'Content Integrity',
        r'Quality Check',
        r'Optimization Notes?',
    ]:
        text = re.sub(
            rf'(?:##?\s*)?{heading}[\s\S]*?(?=\n##\s[^#]|\Z)',
            '', text, flags=re.IGNORECASE,
        )

    # Remove author bio if present
    text = re.sub(r'---\s*\n\s*\*\*About the Author:[\s\S]*$', '', text)
    text = re.sub(r'\*\*Last Updated:\*\*.*$', '', text, flags=re.MULTILINE)

    try:
        from markdown_it import MarkdownIt
        md = MarkdownIt()
        html = md.render(text)
    except ImportError:
        logger.error(
            "markdown-it-py not installed — body_html will contain raw markdown! "
            "Install with: pip install markdown-it-py"
        )
        import html as html_mod
        html = f"<pre>{html_mod.escape(text)}</pre>"

    # Add responsive image styling
    html = f'<style>img {{ max-width: 100%; height: auto; display: block; margin: 2rem auto; border-radius: 8px; }}</style>\n{html}'

    return html


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
        draft: Optional[bool] = None,
    ) -> Dict[str, Any]:
        """
        Update an existing article in the CMS.

        Args:
            cms_article_id: The CMS-side article ID
            article_data: Updated article data (same format as publish)
            draft: If None, preserve current published state. If True/False,
                explicitly set draft/live status.

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
        public_domain: Optional[str] = None,
    ):
        self.store_domain = store_domain
        self.access_token = access_token
        self.blog_id = blog_id
        self.api_version = api_version
        self.blog_handle = blog_handle
        self._client_id = client_id
        self._client_secret = client_secret
        self._on_token_refresh = on_token_refresh
        # Public domain for published URLs (falls back to store_domain)
        self.public_domain = public_domain or store_domain
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

        public_url = f"https://{self.public_domain}/blogs/{self.blog_handle}/{handle}"

        result = {
            "cms_article_id": article_id,
            "handle": handle,
            "published_url": public_url,
            "admin_url": f"https://{self.store_domain}/admin/articles/{article_id}",
            "status": "draft" if draft else "published",
            "created_at": article.get("created_at"),
            # §10 inc 2: what Shopify STORED + its own updated_at, for the
            # manual-edit detection baseline (hash this, not what we sent).
            "cms_body_html": article.get("body_html"),
            "cms_updated_at": article.get("updated_at"),
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
        draft: Optional[bool] = None,
    ) -> Dict[str, Any]:
        """
        Update an existing Shopify blog article.

        Args:
            cms_article_id: The CMS-side article ID
            article_data: Updated article data
            body_only: If True, only send body_html (safe for interlinking updates
                that must not overwrite published status, metafields, handle, etc.)
            draft: If None, preserve current published state. If True/False,
                explicitly set draft/live status.
        """
        if body_only:
            payload = {"article": {"body_html": article_data.get("body_html", "")}}
        else:
            payload = self._build_article_payload(
                article_data, draft=draft if draft is not None else True
            )
            if draft is None:
                # Preserve mode — don't change published status
                payload.get("article", {}).pop("published", None)
        url = f"{self._base_url}/articles/{cms_article_id}.json"

        response = self._api_request("PUT", url, payload)
        article = response.get("article", {})

        handle = article.get("handle", "")
        public_url = f"https://{self.public_domain}/blogs/{self.blog_handle}/{handle}"

        result = {
            "cms_article_id": str(article.get("id", cms_article_id)),
            "handle": handle,
            "published_url": public_url,
            "admin_url": f"https://{self.store_domain}/admin/articles/{cms_article_id}",
            "status": "published" if article.get("published_at") else "draft",
            "updated_at": article.get("updated_at"),
            # §10 inc 2: what Shopify STORED + its own updated_at, for the
            # manual-edit detection baseline (hash this, not what we sent).
            "cms_body_html": article.get("body_html"),
            "cms_updated_at": article.get("updated_at"),
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
        """Convert markdown to HTML. Delegates to module-level render_markdown_to_html()."""
        return render_markdown_to_html(markdown_text)

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

        # Content lock: the body is human-owned on the CMS. Skip the publish so
        # we never overwrite a manual Shopify edit with our re-rendered body.
        # (First-publish articles are never locked; the flag is set after a human
        # edits the live copy.)
        if article.get("content_locked"):
            logger.info(
                f"Article {article_id} is content_locked; skipping CMS publish "
                "(manual edit protected)"
            )
            return {
                "skipped": "content_locked",
                "cms_article_id": article.get("cms_article_id"),
                "published_url": article.get("published_url"),
                "status": article.get("status"),
            }

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

        # Pre-render markdown to HTML so we can (a) send to CMS and (b) save to content_html
        rendered_html = publisher._markdown_to_html(content_md) if content_md else ""

        article_data = {
            "title": article.get("title") or article.get("seo_title") or article.get("keyword", "Untitled"),
            "content_markdown": content_md,
            "body_html": rendered_html,  # Pre-rendered — _build_article_payload will use as-is
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
            # §10 inc 2: before overwriting an existing live article, detect a
            # manual Shopify edit since our last push. If found, auto-lock and
            # skip — protects the human's work without them having to remember
            # to lock first. (First publishes skip this — nothing to protect.)
            if self.detect_manual_edit(article, publisher):
                self.set_content_locked(article_id, True)
                logger.warning(
                    f"Article {article_id} edited on Shopify since our last push; "
                    "auto-locked and skipping publish to protect the manual edit."
                )
                return {
                    "skipped": "manual_edit",
                    "cms_article_id": cms_article_id,
                    "published_url": article.get("published_url"),
                    "status": article.get("status"),
                }
            result = publisher.update(
                cms_article_id, article_data,
                draft=draft if not draft else None,
            )
        else:
            result = publisher.publish(article_data, draft=draft)

        # Include rendered HTML so _update_article_cms_data can save to content_html
        result["body_html"] = rendered_html

        # Save CMS data back to article
        self._update_article_cms_data(article_id, result, draft)
        # Refresh the manual-edit baseline from what Shopify stored (non-fatal,
        # separate from the critical writeback above).
        self.record_push_baseline(article_id, result)

        # Update spoke status in clusters (non-fatal)
        try:
            from viraltracker.services.seo_pipeline.services.cluster_management_service import ClusterManagementService
            cluster_svc = ClusterManagementService(supabase_client=self.supabase)
            cluster_svc.mark_spokes_published_for_article(article_id)
        except Exception as e:
            logger.warning(f"Spoke status update failed for article {article_id}: {e}")

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
            public_domain=config.get("public_domain"),
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

    # =========================================================================
    # MANUAL-EDIT DETECTION (§10 increment 2)
    # =========================================================================

    @staticmethod
    def _body_hash(html: Optional[str]) -> str:
        """sha256 of a CMS body, for manual-edit detection."""
        import hashlib
        return hashlib.sha256((html or "").encode("utf-8")).hexdigest()

    def detect_manual_edit(self, article: Dict[str, Any], publisher) -> bool:
        """True if the live Shopify body differs from what we last pushed —
        the caller must then SKIP the push and auto-lock to protect the edit.

        The decision is a pure BODY-HASH comparison: hash the live body and
        compare to last_pushed_body_hash (the hash of the body Shopify STORED
        on our last push). This is exactly right because:
        - our own non-body writes (metafields, author, status) don't change the
          stored body, so the hash still matches -> no false lock;
        - a human body edit changes the stored body -> hash differs -> detected.
        We deliberately do NOT gate on `updated_at`: comparing a TIMESTAMPTZ
        (DB-normalized to UTC) against Shopify's store-offset timestamp as
        strings can misorder the same instant and skip the hash check, silently
        overwriting an edit. The hash needs no clock.

        Conservative by construction — returns False (proceed) on EVERY
        uncertainty so we never block legitimate publishing or auto-lock on
        noise:
        - no cms_article_id (never pushed — nothing to protect)
        - no last_pushed_body_hash baseline (pre-migration / pre-first-push;
          self-heals on the next push)
        - live fetch fails (transient infra must not freeze the article)
        """
        cms_id = article.get("cms_article_id")
        if not cms_id:
            return False
        baseline_hash = article.get("last_pushed_body_hash")
        if not baseline_hash:
            return False
        try:
            live = publisher.get_article(str(cms_id))
        except Exception as e:
            logger.warning(f"Manual-edit detect: live fetch failed for {cms_id}: {e}")
            return False
        if not live:
            return False
        return self._body_hash(live.get("body_html")) != baseline_hash

    def set_content_locked(self, article_id: str, locked: bool) -> bool:
        """Set/clear the content lock (UI toggle / auto-lock). Returns success."""
        try:
            self.supabase.table("seo_articles").update(
                {"content_locked": locked}
            ).eq("id", article_id).execute()
            return True
        except Exception as e:
            logger.error(f"Failed to set content_locked={locked} for {article_id}: {e}")
            return False

    def record_push_baseline(self, article_id: str, push_result: Dict[str, Any]) -> None:
        """Stamp last_pushed_at + last_pushed_body_hash from what Shopify STORED
        on a successful push (its own updated_at + the body it returned).

        Called by EVERY path that pushes a body to Shopify (publish, interlink,
        repair) so the next detect_manual_edit compares against what we just
        wrote — otherwise our own push reads as an "edit" and auto-locks a clean
        article. Its OWN non-fatal try/except (and separate from the critical
        cms-id writeback) so a missing baseline column pre-migration can't break
        publishing.
        """
        try:
            patch: Dict[str, Any] = {}
            if push_result.get("cms_updated_at"):
                patch["last_pushed_at"] = push_result["cms_updated_at"]
            if push_result.get("cms_body_html") is not None:
                patch["last_pushed_body_hash"] = self._body_hash(push_result["cms_body_html"])
            if patch:
                self.supabase.table("seo_articles").update(patch).eq(
                    "id", article_id
                ).execute()
        except Exception as e:
            logger.warning(
                f"Failed to record push baseline for {article_id} "
                f"(migration applied?): {e}"
            )

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

    def sync_content_html(self, article_id: str) -> str:
        """
        Re-render phase_c_output → content_html and persist to DB.

        Returns:
            Rendered HTML string (empty string if no phase_c_output).
        """
        article = self._get_article(article_id)
        if not article:
            return ""

        # Content lock: don't regenerate the body of a human-owned article.
        if article.get("content_locked"):
            logger.info(
                f"Article {article_id} is content_locked; skipping content_html re-render"
            )
            return article.get("content_html") or ""

        phase_c = article.get("phase_c_output") or ""
        if not phase_c:
            return ""

        html = render_markdown_to_html(phase_c)

        self.supabase.table("seo_articles").update(
            {"content_html": html}
        ).eq("id", article_id).execute()

        logger.info(f"Synced content_html for article {article_id}")
        return html

    def repair_markdown_html(
        self,
        brand_id: str,
        organization_id: str,
        push_to_cms: bool = True,
        dry_run: bool = False,
    ) -> Dict[str, Any]:
        """
        Repair articles whose content_html was published as raw markdown.

        Finds articles whose content_html contains a stray ``<pre><code>`` block
        (the symptom of the fenced-frontmatter rendering bug), re-renders their
        content_html from phase_c_output using the fixed renderer, and — if they
        are already live in the CMS — pushes the corrected HTML back to Shopify.

        Idempotent: once an article renders cleanly it no longer matches and is
        skipped on subsequent runs.

        Args:
            brand_id: Brand UUID
            organization_id: Organization UUID
            push_to_cms: If True, re-push corrected HTML to Shopify for articles
                that have a cms_article_id. If False, only fix the DB column.
            dry_run: If True, report what *would* change without writing anything.

        Returns:
            Dict with counts: scanned, repaired_db, repushed, skipped, errors,
            and a list of affected article ids.
        """
        # Find candidates: content_html contains a code block that shouldn't be
        # there. We re-check each one after re-render to confirm it's actually
        # fixed before counting it.
        candidates = (
            self.supabase.table("seo_articles")
            # select("*") (not a narrow list) so this stays graceful when the
            # content_locked migration hasn't been applied yet: the missing
            # column simply won't appear and row.get() reads as unlocked.
            .select("*")
            .eq("brand_id", brand_id)
            .like("content_html", "%<pre><code>%")
            .execute()
        )
        rows = candidates.data or []

        publisher = None
        if push_to_cms and not dry_run:
            publisher = self.get_publisher(brand_id, organization_id)

        repaired_db = 0
        repushed = 0
        skipped = 0
        errors: List[str] = []
        affected: List[str] = []

        for row in rows:
            article_id = row["id"]
            # Content lock: never re-render/overwrite a human-owned article.
            if row.get("content_locked"):
                skipped += 1
                logger.info(
                    f"repair_markdown_html: article {article_id} is content_locked — skipping"
                )
                continue
            phase_c = row.get("phase_c_output") or ""
            if not phase_c:
                skipped += 1
                logger.warning(
                    f"repair_markdown_html: article {article_id} has <pre> but no "
                    "phase_c_output to re-render from — skipping"
                )
                continue

            new_html = render_markdown_to_html(phase_c)
            if "<pre><code>" in new_html:
                # Re-render didn't fix it — leave it for manual review rather than
                # silently re-pushing still-broken content.
                skipped += 1
                logger.warning(
                    f"repair_markdown_html: article {article_id} still renders a "
                    "code block after re-render — needs manual review"
                )
                continue

            affected.append(article_id)

            if dry_run:
                continue

            try:
                self.supabase.table("seo_articles").update(
                    {"content_html": new_html}
                ).eq("id", article_id).execute()
                repaired_db += 1
            except Exception as e:
                errors.append(f"{article_id}: DB update failed: {e}")
                continue

            cms_id = row.get("cms_article_id")
            if push_to_cms and publisher and cms_id:
                # §10 inc 2: a repair push is a body overwrite too — detect a
                # manual Shopify edit first (don't clobber a hand-fix), and
                # refresh the baseline after pushing (else this clean repair
                # leaves a stale baseline that auto-locks the article next run).
                if self.detect_manual_edit(row, publisher):
                    self.set_content_locked(article_id, True)
                    skipped += 1
                    logger.warning(
                        f"repair_markdown_html: article {article_id} edited on "
                        "Shopify since our last push — auto-locked, not repushing."
                    )
                    continue
                try:
                    push_result = publisher.update(
                        cms_id, {"body_html": new_html}, body_only=True
                    )
                    self.record_push_baseline(article_id, push_result)
                    repushed += 1
                except Exception as e:
                    errors.append(f"{article_id}: CMS push failed: {e}")

        result = {
            "scanned": len(rows),
            "repaired_db": repaired_db,
            "repushed": repushed,
            "skipped": skipped,
            "errors": errors,
            "affected_article_ids": affected,
            "dry_run": dry_run,
        }
        logger.info(f"repair_markdown_html for brand {brand_id}: {result}")
        return result

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

        # Auto-fix published_url domain mismatches (myshopify.com → public domain)
        urls_fixed = self._fix_published_urls(brand_id, organization_id)

        return {"synced": synced, "total": len(our_articles.data or []), "urls_fixed": urls_fixed}

    def _fix_published_urls(
        self,
        brand_id: str,
        organization_id: str,
    ) -> int:
        """
        Rewrite published_url from myshopify.com internal domain to public domain.

        Runs on every status sync to catch articles published before
        the public_domain config was set.
        """
        integration = self._get_integration(brand_id, organization_id)
        if not integration:
            return 0

        config = integration.get("config", {})
        public_domain = config.get("public_domain")
        store_domain = config.get("store_domain", "")

        if not public_domain or public_domain == store_domain:
            return 0  # No public domain configured or same as store domain

        # Find articles with store domain in published_url
        articles = (
            self.supabase.table("seo_articles")
            .select("id, published_url")
            .eq("brand_id", brand_id)
            .not_.is_("published_url", "null")
            .like("published_url", f"%{store_domain}%")
            .execute()
        )

        fixed = 0
        for row in (articles.data or []):
            old_url = row.get("published_url", "")
            new_url = old_url.replace(store_domain, public_domain)
            if new_url != old_url:
                self.supabase.table("seo_articles").update(
                    {"published_url": new_url}
                ).eq("id", row["id"]).execute()
                fixed += 1
                logger.info(f"Fixed published_url for article {row['id']}: {store_domain} → {public_domain}")

        if fixed:
            logger.info(f"Fixed {fixed} published_url(s) for brand {brand_id}")
        return fixed

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
