"""
SEO Image Service - Generate and upload article images.

Handles:
- Extracting [IMAGE: desc] and [HERO IMAGE: desc] markers from article markdown
- Generating images via GeminiService (async)
- Uploading to Supabase Storage (seo-article-images bucket)
- Replacing markers with responsive <img> tags
- Storing image metadata for regeneration

Uses async throughout since GeminiService.generate_image() is async.
"""

import asyncio
import base64
import logging
import re
import time
from typing import Any, Callable, Dict, List, Optional, Tuple

logger = logging.getLogger(__name__)

# Storage bucket for SEO article images (must be public for CDN URLs)
BUCKET_NAME = "seo-article-images"

# Photography-style prompt suffix (from original Node.js pipeline)
PHOTOGRAPHY_STYLE = (
    "Shot on iPhone, natural lighting, casual authentic feel, slightly candid, "
    "warm tones, real family moment, not overly staged or perfect, "
    "realistic everyday photography"
)

# Delay between image generations to avoid rate limits
IMAGE_GENERATION_DELAY_SECONDS = 2.0

# Marker patterns
_MARKER_PATTERNS = [
    # [HERO IMAGE: description]
    re.compile(r'\[HERO IMAGE:\s*(.+?)\]', re.IGNORECASE),
    # [IMAGE: description]
    re.compile(r'\[IMAGE:\s*(.+?)\]', re.IGNORECASE),
    # <!-- FEATURED IMAGE: description -->
    re.compile(r'<!--\s*FEATURED IMAGE:\s*(.+?)\s*-->', re.IGNORECASE),
    # <!-- IMAGE: description -->
    re.compile(r'<!--\s*IMAGE:\s*(.+?)\s*-->', re.IGNORECASE),
]


class SEOImageService:
    """Service for generating and managing SEO article images."""

    def __init__(self, supabase_client=None, gemini_service=None):
        self._supabase = supabase_client
        self._gemini = gemini_service
        self._usage_tracker = None

    @property
    def supabase(self):
        """Lazy-load Supabase client."""
        if self._supabase is None:
            from viraltracker.core.database import get_supabase_client
            self._supabase = get_supabase_client()
        return self._supabase

    @property
    def gemini(self):
        """Lazy-load GeminiService."""
        if self._gemini is None:
            from viraltracker.services.gemini_service import GeminiService
            self._gemini = GeminiService()
        return self._gemini

    @property
    def usage_tracker(self):
        """Lazy-load UsageTracker."""
        if self._usage_tracker is None:
            from viraltracker.services.usage_tracker import UsageTracker
            self._usage_tracker = UsageTracker(self.supabase)
        return self._usage_tracker

    # =========================================================================
    # MARKER EXTRACTION
    # =========================================================================

    def extract_image_markers(
        self,
        markdown: str,
    ) -> List[Dict[str, Any]]:
        """
        Parse image markers from article markdown.

        Supports formats:
        - [IMAGE: description]
        - [HERO IMAGE: description]
        - <!-- FEATURED IMAGE: description -->
        - <!-- IMAGE: description -->

        The first marker or any explicitly tagged HERO/FEATURED marker is the hero.

        Returns:
            List of dicts: [{index, type, description, original_marker, position}]
        """
        markers = []
        seen_positions = set()

        for pattern in _MARKER_PATTERNS:
            for match in pattern.finditer(markdown):
                pos = match.start()
                if pos in seen_positions:
                    continue
                seen_positions.add(pos)

                description = match.group(1).strip()
                original = match.group(0)

                # Determine type
                is_hero = bool(re.search(r'HERO|FEATURED', original, re.IGNORECASE))
                marker_type = "hero" if is_hero else "inline"

                markers.append({
                    "index": len(markers),
                    "type": marker_type,
                    "description": description,
                    "original_marker": original,
                    "position": pos,
                })

        # Sort by position in document
        markers.sort(key=lambda m: m["position"])

        # Re-index after sort
        for i, m in enumerate(markers):
            m["index"] = i

        # If no explicit hero, first marker becomes hero
        if markers and not any(m["type"] == "hero" for m in markers):
            markers[0]["type"] = "hero"

        return markers

    # =========================================================================
    # IMAGE GENERATION
    # =========================================================================

    async def generate_article_images(
        self,
        article_id: str,
        markdown: str,
        brand_id: str,
        organization_id: str,
        keyword: str,
        progress_callback: Optional[Callable] = None,
        image_style: Optional[str] = None,
    ) -> Dict[str, Any]:
        """
        Generate all images for an article.

        Extracts markers, generates images, uploads to storage,
        replaces markers with <img> tags, and saves to DB.

        Args:
            article_id: Article UUID
            markdown: Article markdown with image markers
            brand_id: Brand UUID
            organization_id: Org UUID
            keyword: Article keyword (used for slug generation)
            progress_callback: Optional callback(current, total, description)

        Returns:
            Dict with hero_image_url, updated_markdown, image_metadata, stats
        """
        markers = self.extract_image_markers(markdown)

        if not markers:
            return {
                "hero_image_url": None,
                "updated_markdown": markdown,
                "image_metadata": [],
                "stats": {"total": 0, "success": 0, "failed": 0},
            }

        slug = self._generate_slug(keyword)
        image_metadata = []
        hero_image_url = None
        success_count = 0
        fail_count = 0

        for marker in markers:
            idx = marker["index"]
            total = len(markers)

            if progress_callback:
                progress_callback(idx, total, f"Generating image {idx + 1}/{total}: {marker['description'][:50]}")

            result = await self._generate_and_upload_single(
                description=marker["description"],
                brand_id=brand_id,
                organization_id=organization_id,
                slug=slug,
                image_type=marker["type"],
                index=idx,
                image_style=image_style,
            )

            image_metadata.append(result)

            if result["status"] == "success":
                success_count += 1
                if marker["type"] == "hero" and not hero_image_url:
                    hero_image_url = result["cdn_url"]
            else:
                fail_count += 1

            # Delay between generations to avoid rate limits
            if idx < total - 1:
                await asyncio.sleep(IMAGE_GENERATION_DELAY_SECONDS)

        if progress_callback:
            progress_callback(len(markers), len(markers), "Image generation complete")

        # Replace markers with img tags
        updated_markdown = self._replace_markers_with_images(markdown, markers, image_metadata)

        # Save to DB
        self._save_image_data(article_id, hero_image_url, updated_markdown, image_metadata)

        return {
            "hero_image_url": hero_image_url,
            "updated_markdown": updated_markdown,
            "image_metadata": image_metadata,
            "stats": {
                "total": len(markers),
                "success": success_count,
                "failed": fail_count,
            },
        }

    async def regenerate_image(
        self,
        article_id: str,
        image_index: int,
        brand_id: str,
        organization_id: str,
        custom_prompt: Optional[str] = None,
        image_style: Optional[str] = None,
    ) -> Dict[str, Any]:
        """
        Regenerate a specific image by index.

        Args:
            article_id: Article UUID
            image_index: Index in image_metadata array
            brand_id: Brand UUID
            organization_id: Org UUID
            custom_prompt: Optional custom prompt (overrides original description)
            image_style: Optional brand image style (overrides default photography style)

        Returns:
            Updated image metadata entry
        """
        # Load current article data
        article = self._get_article(article_id)
        if not article:
            raise ValueError(f"Article not found: {article_id}")

        metadata_list = article.get("image_metadata") or []
        if image_index >= len(metadata_list):
            raise ValueError(f"Image index {image_index} out of range (have {len(metadata_list)} images)")

        old_entry = metadata_list[image_index]
        description = custom_prompt or old_entry.get("description", "")
        slug = self._generate_slug(article.get("keyword", "article"))

        result = await self._generate_and_upload_single(
            description=description,
            brand_id=brand_id,
            organization_id=organization_id,
            slug=slug,
            image_type=old_entry.get("type", "inline"),
            index=image_index,
            image_style=image_style,
        )

        # Update metadata
        metadata_list[image_index] = result

        # Update hero_image_url if this was the hero
        hero_image_url = article.get("hero_image_url")
        if old_entry.get("type") == "hero" and result["status"] == "success":
            hero_image_url = result["cdn_url"]

        # Replace the image tag in markdown
        markdown = article.get("phase_c_output") or article.get("content_markdown") or ""
        if result["status"] == "success" and old_entry.get("cdn_url"):
            # Replace old img tag with new one
            old_img = self._build_img_tag(old_entry)
            new_img = self._build_img_tag(result)
            if old_img in markdown:
                markdown = markdown.replace(old_img, new_img)

        self._save_image_data(article_id, hero_image_url, markdown, metadata_list)

        return result

    # =========================================================================
    # PRIVATE HELPERS
    # =========================================================================

    async def _generate_and_upload_single(
        self,
        description: str,
        brand_id: str,
        organization_id: str,
        slug: str,
        image_type: str,
        index: int,
        image_style: Optional[str] = None,
    ) -> Dict[str, Any]:
        """Generate a single image and upload to storage."""
        filename = self._generate_filename(slug, image_type, index)
        storage_path = self._storage_path(brand_id, slug, filename)
        aspect_ratio = "16:9" if image_type == "hero" else "4:3"

        entry = {
            "index": index,
            "type": image_type,
            "description": description,
            "status": "failed",
            "cdn_url": None,
            "storage_path": storage_path,
            "alt_text": description[:125],
            "error": None,
        }

        try:
            prompt = self._enhance_prompt(description, image_style=image_style)
            start_ms = time.time()

            image_base64 = await self.gemini.generate_image(
                prompt=prompt,
                max_retries=2,
                aspect_ratio=aspect_ratio,
            )

            duration_ms = int((time.time() - start_ms) * 1000)

            # Decode base64 to bytes and convert to WebP
            if isinstance(image_base64, dict):
                image_base64 = image_base64.get("image_base64", image_base64)
            png_bytes = base64.b64decode(image_base64)

            from io import BytesIO
            from PIL import Image
            with Image.open(BytesIO(png_bytes)) as img:
                webp_buf = BytesIO()
                img.save(webp_buf, format="WEBP", quality=85)
                image_bytes = webp_buf.getvalue()

            # Upload to Supabase Storage
            await asyncio.to_thread(
                lambda: self.supabase.storage.from_(BUCKET_NAME).upload(
                    storage_path,
                    image_bytes,
                    {"content-type": "image/webp", "upsert": "true"},
                )
            )

            # Get public URL
            cdn_url = self.supabase.storage.from_(BUCKET_NAME).get_public_url(storage_path)
            cdn_url = cdn_url.rstrip("?") if cdn_url else ""

            entry["status"] = "success"
            entry["cdn_url"] = cdn_url

            # Track usage
            self._track_usage(organization_id, duration_ms)

            logger.info(f"Generated image: {filename} ({duration_ms}ms)")

        except Exception as e:
            entry["error"] = str(e)[:500]
            logger.warning(f"Image generation failed for '{description[:50]}': {e}")

        return entry

    def _enhance_prompt(self, description: str, image_style: Optional[str] = None) -> str:
        """Add photography style to prompt."""
        style = image_style or PHOTOGRAPHY_STYLE
        return f"{description}. {style}"

    @staticmethod
    def _generate_slug(keyword: str) -> str:
        """Generate URL-safe slug from keyword."""
        slug = keyword.lower().strip()
        slug = re.sub(r'[^a-z0-9]+', '-', slug)
        slug = slug.strip('-')
        return slug[:60] if slug else "article"

    @staticmethod
    def _generate_filename(slug: str, image_type: str, index: int) -> str:
        """Generate filename for storage."""
        if image_type == "hero":
            return f"{slug}-hero.webp"
        return f"{slug}-inline-{index}.webp"

    @staticmethod
    def _storage_path(brand_id: str, slug: str, filename: str) -> str:
        """Build storage path."""
        return f"seo-articles/{brand_id}/{slug}/{filename}"

    @staticmethod
    def _build_img_tag(entry: Dict[str, Any]) -> str:
        """Build responsive HTML img tag from image entry."""
        if entry.get("status") != "success" or not entry.get("cdn_url"):
            return (
                '<div style="background:#f0f0f0;padding:2rem;text-align:center;'
                'margin:1.5rem 0;">[Image unavailable]</div>'
            )

        import html as html_mod

        alt = html_mod.escape(entry.get("alt_text", ""))
        url = entry["cdn_url"]
        is_hero = entry.get("type") == "hero"

        loading = "eager" if is_hero else "lazy"
        style = (
            'max-width:100%;height:auto;display:block;margin:2rem auto;border-radius:8px;'
        )

        return f'<img src="{url}" alt="{alt}" loading="{loading}" style="{style}" />'

    def _replace_markers_with_images(
        self,
        markdown: str,
        markers: List[Dict[str, Any]],
        image_metadata: List[Dict[str, Any]],
    ) -> str:
        """Replace all markers in markdown with img tags or placeholders."""
        result = markdown
        # Replace in reverse order to preserve positions
        for marker, meta in sorted(
            zip(markers, image_metadata),
            key=lambda x: x[0]["position"],
            reverse=True,
        ):
            img_tag = self._build_img_tag(meta)
            result = result[:marker["position"]] + img_tag + result[marker["position"] + len(marker["original_marker"]):]
        return result

    def _save_image_data(
        self,
        article_id: str,
        hero_image_url: Optional[str],
        updated_markdown: str,
        image_metadata: List[Dict[str, Any]],
    ) -> None:
        """Save image data back to seo_articles."""
        update_data = {
            "image_metadata": image_metadata,
            "phase_c_output": updated_markdown,
        }
        if hero_image_url:
            update_data["hero_image_url"] = hero_image_url

        try:
            self.supabase.table("seo_articles").update(
                update_data
            ).eq("id", article_id).execute()
            logger.info(f"Saved image data for article {article_id}")
        except Exception as e:
            logger.error(f"Failed to save image data for {article_id}: {e}")

    def _get_article(self, article_id: str) -> Optional[Dict[str, Any]]:
        """Get article from DB."""
        result = (
            self.supabase.table("seo_articles")
            .select("*")
            .eq("id", article_id)
            .execute()
        )
        return result.data[0] if result.data else None

    def _track_usage(self, organization_id: str, duration_ms: int) -> None:
        """Track image generation usage."""
        try:
            from viraltracker.services.usage_tracker import UsageRecord
            record = UsageRecord(
                provider="google",
                model="gemini-3-pro-image-preview",
                tool_name="seo_pipeline",
                operation="seo_image_generation",
                input_tokens=0,
                output_tokens=0,
                duration_ms=duration_ms,
            )
            self.usage_tracker.track(
                user_id=None,
                organization_id=organization_id,
                record=record,
            )
        except Exception as e:
            logger.warning(f"Failed to track image usage: {e}")
