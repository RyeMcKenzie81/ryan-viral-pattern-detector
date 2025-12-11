"""
CompetitorService - Competitor research and analysis.

This service handles:
- Managing competitors for a brand
- Scraping competitor ads from Facebook Ad Library
- Downloading competitor ad assets
- Analyzing competitor ads (video, image, copy)
- Scraping and analyzing competitor landing pages
- Synthesizing competitor personas

Mirrors BrandResearchService patterns for consistency.
"""

import logging
import asyncio
import json
import httpx
from typing import List, Dict, Optional, Any
from uuid import UUID
from datetime import datetime

from supabase import Client
from ..core.database import get_supabase_client

logger = logging.getLogger(__name__)


class CompetitorService:
    """Service for competitor research and analysis."""

    def __init__(self, supabase: Optional[Client] = None):
        self.supabase = supabase or get_supabase_client()
        logger.info("CompetitorService initialized")

    # =========================================================================
    # Competitor CRUD
    # =========================================================================

    def create_competitor(
        self,
        brand_id: UUID,
        name: str,
        website_url: Optional[str] = None,
        facebook_page_id: Optional[str] = None,
        ad_library_url: Optional[str] = None,
        amazon_url: Optional[str] = None,
        industry: Optional[str] = None,
        notes: Optional[str] = None
    ) -> Dict[str, Any]:
        """Create a new competitor for a brand."""
        record = {
            "brand_id": str(brand_id),
            "name": name,
            "website_url": website_url,
            "facebook_page_id": facebook_page_id,
            "ad_library_url": ad_library_url,
            "amazon_url": amazon_url,
            "industry": industry,
            "notes": notes
        }

        result = self.supabase.table("competitors").insert(record).execute()

        if result.data:
            logger.info(f"Created competitor: {name} for brand {brand_id}")
            return result.data[0]

        raise Exception(f"Failed to create competitor: {name}")

    def get_competitor(self, competitor_id: UUID) -> Optional[Dict[str, Any]]:
        """Get a competitor by ID."""
        result = self.supabase.table("competitors").select("*").eq(
            "id", str(competitor_id)
        ).execute()

        return result.data[0] if result.data else None

    def get_competitors_for_brand(self, brand_id: UUID) -> List[Dict[str, Any]]:
        """Get all competitors for a brand."""
        result = self.supabase.table("competitors").select("*").eq(
            "brand_id", str(brand_id)
        ).order("name").execute()

        return result.data or []

    def update_competitor(self, competitor_id: UUID, updates: Dict[str, Any]) -> bool:
        """Update a competitor."""
        updates["updated_at"] = datetime.utcnow().isoformat()

        result = self.supabase.table("competitors").update(updates).eq(
            "id", str(competitor_id)
        ).execute()

        if result.data:
            logger.info(f"Updated competitor: {competitor_id}")
            return True
        return False

    def delete_competitor(self, competitor_id: UUID) -> bool:
        """Delete a competitor and all related data."""
        # Cascading deletes should handle related tables
        result = self.supabase.table("competitors").delete().eq(
            "id", str(competitor_id)
        ).execute()

        if result.data:
            logger.info(f"Deleted competitor: {competitor_id}")
            return True
        return False

    # =========================================================================
    # Statistics
    # =========================================================================

    def get_competitor_stats(self, competitor_id: UUID) -> Dict[str, int]:
        """Get statistics for a competitor."""
        try:
            # Count ads
            ads_result = self.supabase.table("competitor_ads").select(
                "id", count="exact"
            ).eq("competitor_id", str(competitor_id)).execute()
            ads_count = ads_result.count or 0

            # Count assets
            if ads_count > 0:
                ad_ids_result = self.supabase.table("competitor_ads").select(
                    "id"
                ).eq("competitor_id", str(competitor_id)).execute()
                ad_ids = [r['id'] for r in ad_ids_result.data or []]

                assets_result = self.supabase.table("competitor_ad_assets").select(
                    "id, asset_type"
                ).in_("competitor_ad_id", ad_ids).execute()

                videos = sum(1 for a in (assets_result.data or []) if a.get('asset_type') == 'video')
                images = sum(1 for a in (assets_result.data or []) if a.get('asset_type') == 'image')
            else:
                videos = 0
                images = 0

            # Count analyses
            analysis_result = self.supabase.table("competitor_ad_analysis").select(
                "analysis_type"
            ).eq("competitor_id", str(competitor_id)).execute()

            analysis_counts = {
                "video_vision": 0,
                "image_vision": 0,
                "copy_analysis": 0
            }
            for row in (analysis_result.data or []):
                atype = row.get("analysis_type", "")
                if atype in analysis_counts:
                    analysis_counts[atype] += 1

            # Count landing pages
            lp_result = self.supabase.table("competitor_landing_pages").select(
                "id, scraped_at, analyzed_at"
            ).eq("competitor_id", str(competitor_id)).execute()

            lp_total = len(lp_result.data or [])
            lp_scraped = sum(1 for lp in (lp_result.data or []) if lp.get('scraped_at'))
            lp_analyzed = sum(1 for lp in (lp_result.data or []) if lp.get('analyzed_at'))

            # Count Amazon reviews
            amazon_stats = self.get_competitor_amazon_stats(competitor_id)

            return {
                "ads": ads_count,
                "videos": videos,
                "images": images,
                "video_analyses": analysis_counts["video_vision"],
                "image_analyses": analysis_counts["image_vision"],
                "copy_analyses": analysis_counts["copy_analysis"],
                "landing_pages": lp_total,
                "landing_pages_scraped": lp_scraped,
                "landing_pages_analyzed": lp_analyzed,
                "amazon_reviews": amazon_stats.get("reviews_in_db", 0),
                "amazon_reviews_analyzed": amazon_stats.get("reviews_analyzed", 0)
            }

        except Exception as e:
            logger.error(f"Failed to get competitor stats: {e}")
            return {
                "ads": 0, "videos": 0, "images": 0,
                "video_analyses": 0, "image_analyses": 0, "copy_analyses": 0,
                "landing_pages": 0, "landing_pages_scraped": 0, "landing_pages_analyzed": 0,
                "amazon_reviews": 0, "amazon_reviews_analyzed": 0
            }

    # =========================================================================
    # Ad Scraping (from Facebook Ad Library via Apify)
    # =========================================================================

    async def scrape_competitor_ads(
        self,
        competitor_id: UUID,
        ad_library_url: str,
        max_ads: int = 50
    ) -> Dict[str, Any]:
        """
        Scrape ads from Facebook Ad Library for a competitor.

        Uses Apify's Facebook Ad Library Scraper.

        Args:
            competitor_id: Competitor UUID
            ad_library_url: Facebook Ad Library URL for the competitor
            max_ads: Maximum ads to scrape

        Returns:
            Dict with counts: {"ads_scraped", "ads_new", "ads_existing"}
        """
        import os

        apify_token = os.environ.get("APIFY_API_TOKEN")
        if not apify_token:
            raise ValueError("APIFY_API_TOKEN not set")

        # Extract page ID from Ad Library URL
        # URL format: https://www.facebook.com/ads/library/?active_status=all&ad_type=all&country=US&view_all_page_id=123456789
        page_id = None
        if "view_all_page_id=" in ad_library_url:
            page_id = ad_library_url.split("view_all_page_id=")[1].split("&")[0]
        elif "id=" in ad_library_url:
            page_id = ad_library_url.split("id=")[1].split("&")[0]

        if not page_id:
            raise ValueError(f"Could not extract page ID from URL: {ad_library_url}")

        logger.info(f"Scraping ads for competitor {competitor_id}, page_id={page_id}")

        # Call Apify Facebook Ad Library Scraper
        actor_id = "apify/facebook-ads-library-scraper"
        run_input = {
            "pageIds": [page_id],
            "countryCode": "US",
            "adType": "ALL",
            "adActiveStatus": "ALL",
            "maxAds": max_ads
        }

        async with httpx.AsyncClient(timeout=300) as client:
            # Start the actor run
            response = await client.post(
                f"https://api.apify.com/v2/acts/{actor_id}/runs",
                headers={"Authorization": f"Bearer {apify_token}"},
                json=run_input
            )
            response.raise_for_status()
            run_data = response.json()
            run_id = run_data["data"]["id"]

            logger.info(f"Started Apify run: {run_id}")

            # Poll for completion
            while True:
                await asyncio.sleep(5)
                status_response = await client.get(
                    f"https://api.apify.com/v2/actor-runs/{run_id}",
                    headers={"Authorization": f"Bearer {apify_token}"}
                )
                status_data = status_response.json()
                status = status_data["data"]["status"]

                if status == "SUCCEEDED":
                    break
                elif status in ["FAILED", "ABORTED", "TIMED-OUT"]:
                    raise Exception(f"Apify run failed with status: {status}")

                logger.info(f"Apify run status: {status}, waiting...")

            # Get results
            dataset_id = status_data["data"]["defaultDatasetId"]
            results_response = await client.get(
                f"https://api.apify.com/v2/datasets/{dataset_id}/items",
                headers={"Authorization": f"Bearer {apify_token}"}
            )
            ads_data = results_response.json()

        # Save ads to database
        ads_new = 0
        ads_existing = 0

        for ad in ads_data:
            ad_archive_id = ad.get("adArchiveID") or ad.get("id")
            if not ad_archive_id:
                continue

            # Check if already exists
            existing = self.supabase.table("competitor_ads").select("id").eq(
                "competitor_id", str(competitor_id)
            ).eq("ad_archive_id", str(ad_archive_id)).execute()

            if existing.data:
                ads_existing += 1
                continue

            # Insert new ad
            record = {
                "competitor_id": str(competitor_id),
                "ad_archive_id": str(ad_archive_id),
                "page_name": ad.get("pageName"),
                "ad_body": ad.get("adBodyText") or ad.get("bodyText"),
                "ad_title": ad.get("adTitle") or ad.get("title"),
                "link_url": ad.get("linkUrl") or ad.get("websiteUrl"),
                "cta_text": ad.get("ctaText"),
                "started_running": ad.get("startDate"),
                "is_active": ad.get("isActive", True),
                "platforms": ad.get("platforms", []),
                "snapshot_data": ad  # Store full response
            }

            self.supabase.table("competitor_ads").insert(record).execute()
            ads_new += 1

        # Update competitor record
        self.supabase.table("competitors").update({
            "last_scraped_at": datetime.utcnow().isoformat(),
            "ads_count": ads_new + ads_existing
        }).eq("id", str(competitor_id)).execute()

        logger.info(f"Scraped {ads_new} new ads, {ads_existing} existing for competitor {competitor_id}")

        return {
            "ads_scraped": len(ads_data),
            "ads_new": ads_new,
            "ads_existing": ads_existing
        }

    # =========================================================================
    # Asset Download
    # =========================================================================

    async def download_competitor_assets(
        self,
        competitor_id: UUID,
        limit: int = 50
    ) -> Dict[str, int]:
        """
        Download video/image assets from competitor ads.

        Args:
            competitor_id: Competitor UUID
            limit: Maximum ads to process

        Returns:
            Dict with counts
        """
        from ..core.storage import get_storage_client

        # Get ads that need asset download
        ads_result = self.supabase.table("competitor_ads").select(
            "id, snapshot_data"
        ).eq("competitor_id", str(competitor_id)).limit(limit).execute()

        if not ads_result.data:
            return {"ads_processed": 0, "videos_downloaded": 0, "images_downloaded": 0}

        # Get ads that already have assets
        ad_ids = [ad['id'] for ad in ads_result.data]
        existing_assets = self.supabase.table("competitor_ad_assets").select(
            "competitor_ad_id"
        ).in_("competitor_ad_id", ad_ids).execute()

        ads_with_assets = set(r['competitor_ad_id'] for r in (existing_assets.data or []))
        ads_to_process = [ad for ad in ads_result.data if ad['id'] not in ads_with_assets]

        if not ads_to_process:
            return {"ads_processed": 0, "videos_downloaded": 0, "images_downloaded": 0, "reason": "all_have_assets"}

        storage = get_storage_client()
        videos_downloaded = 0
        images_downloaded = 0

        async with httpx.AsyncClient(timeout=60) as client:
            for ad in ads_to_process:
                snapshot = ad.get('snapshot_data', {})
                if isinstance(snapshot, str):
                    try:
                        snapshot = json.loads(snapshot)
                    except:
                        continue

                # Extract asset URLs from snapshot
                asset_urls = []

                # Video URLs
                for video in snapshot.get('videos', []):
                    if isinstance(video, dict) and video.get('videoHD'):
                        asset_urls.append(('video', video['videoHD']))
                    elif isinstance(video, dict) and video.get('videoSD'):
                        asset_urls.append(('video', video['videoSD']))
                    elif isinstance(video, str):
                        asset_urls.append(('video', video))

                # Image URLs
                for image in snapshot.get('images', []):
                    if isinstance(image, dict) and image.get('originalImageUrl'):
                        asset_urls.append(('image', image['originalImageUrl']))
                    elif isinstance(image, dict) and image.get('url'):
                        asset_urls.append(('image', image['url']))
                    elif isinstance(image, str):
                        asset_urls.append(('image', image))

                # Download each asset
                for asset_type, url in asset_urls:
                    try:
                        response = await client.get(url)
                        if response.status_code != 200:
                            continue

                        content = response.content
                        content_type = response.headers.get('content-type', '')

                        # Determine extension
                        if 'video' in content_type:
                            ext = 'mp4'
                            mime = 'video/mp4'
                        elif 'image' in content_type:
                            if 'png' in content_type:
                                ext = 'png'
                                mime = 'image/png'
                            else:
                                ext = 'jpg'
                                mime = 'image/jpeg'
                        else:
                            ext = 'mp4' if asset_type == 'video' else 'jpg'
                            mime = 'video/mp4' if asset_type == 'video' else 'image/jpeg'

                        # Upload to storage
                        path = f"competitor-assets/{competitor_id}/{ad['id']}/{asset_type}_{datetime.utcnow().timestamp()}.{ext}"
                        storage.from_("ad-assets").upload(path, content, {"content-type": mime})

                        # Save record
                        self.supabase.table("competitor_ad_assets").insert({
                            "competitor_ad_id": ad['id'],
                            "asset_type": asset_type,
                            "storage_path": path,
                            "original_url": url,
                            "mime_type": mime,
                            "file_size": len(content)
                        }).execute()

                        if asset_type == 'video':
                            videos_downloaded += 1
                        else:
                            images_downloaded += 1

                    except Exception as e:
                        logger.warning(f"Failed to download asset: {e}")
                        continue

        return {
            "ads_processed": len(ads_to_process),
            "videos_downloaded": videos_downloaded,
            "images_downloaded": images_downloaded
        }

    # =========================================================================
    # Analysis (Video, Image, Copy)
    # =========================================================================

    async def analyze_competitor_videos(
        self,
        competitor_id: UUID,
        limit: int = 10
    ) -> List[Dict]:
        """Analyze competitor video assets with Gemini Vision."""
        from .gemini_service import GeminiService

        # Get video assets that haven't been analyzed
        ads_result = self.supabase.table("competitor_ads").select("id").eq(
            "competitor_id", str(competitor_id)
        ).execute()

        if not ads_result.data:
            return []

        ad_ids = [r['id'] for r in ads_result.data]

        assets_result = self.supabase.table("competitor_ad_assets").select(
            "id, competitor_ad_id, storage_path, mime_type"
        ).in_("competitor_ad_id", ad_ids).eq("asset_type", "video").execute()

        if not assets_result.data:
            return []

        # Filter out already analyzed
        asset_ids = [a['id'] for a in assets_result.data]
        analyzed_result = self.supabase.table("competitor_ad_analysis").select(
            "asset_id"
        ).in_("asset_id", asset_ids).eq("analysis_type", "video_vision").execute()

        analyzed_ids = {r['asset_id'] for r in (analyzed_result.data or [])}
        assets_to_analyze = [a for a in assets_result.data if a['id'] not in analyzed_ids][:limit]

        if not assets_to_analyze:
            return []

        gemini = GeminiService()
        results = []

        for asset in assets_to_analyze:
            try:
                analysis = await gemini.analyze_video_for_persona(asset['storage_path'])

                # Save analysis
                self.supabase.table("competitor_ad_analysis").insert({
                    "competitor_id": str(competitor_id),
                    "competitor_ad_id": asset['competitor_ad_id'],
                    "asset_id": asset['id'],
                    "analysis_type": "video_vision",
                    "raw_response": analysis,
                    "hooks_extracted": analysis.get('hook', []),
                    "pain_points_addressed": analysis.get('pain_points', {}).get('emotional', []),
                    "model_used": "gemini-2.0-flash"
                }).execute()

                results.append({"asset_id": asset['id'], "analysis": analysis})

                await asyncio.sleep(2)  # Rate limiting

            except Exception as e:
                logger.error(f"Failed to analyze video {asset['id']}: {e}")
                results.append({"asset_id": asset['id'], "error": str(e)})

        return results

    async def analyze_competitor_images(
        self,
        competitor_id: UUID,
        limit: int = 20
    ) -> List[Dict]:
        """Analyze competitor image assets with Gemini Vision."""
        from .gemini_service import GeminiService

        # Get image assets that haven't been analyzed
        ads_result = self.supabase.table("competitor_ads").select("id").eq(
            "competitor_id", str(competitor_id)
        ).execute()

        if not ads_result.data:
            return []

        ad_ids = [r['id'] for r in ads_result.data]

        assets_result = self.supabase.table("competitor_ad_assets").select(
            "id, competitor_ad_id, storage_path, mime_type"
        ).in_("competitor_ad_id", ad_ids).eq("asset_type", "image").execute()

        if not assets_result.data:
            return []

        # Filter out already analyzed
        asset_ids = [a['id'] for a in assets_result.data]
        analyzed_result = self.supabase.table("competitor_ad_analysis").select(
            "asset_id"
        ).in_("asset_id", asset_ids).eq("analysis_type", "image_vision").execute()

        analyzed_ids = {r['asset_id'] for r in (analyzed_result.data or [])}
        assets_to_analyze = [a for a in assets_result.data if a['id'] not in analyzed_ids][:limit]

        if not assets_to_analyze:
            return []

        gemini = GeminiService()
        results = []

        for asset in assets_to_analyze:
            try:
                analysis = await gemini.analyze_image_for_persona(asset['storage_path'])

                # Save analysis
                self.supabase.table("competitor_ad_analysis").insert({
                    "competitor_id": str(competitor_id),
                    "competitor_ad_id": asset['competitor_ad_id'],
                    "asset_id": asset['id'],
                    "analysis_type": "image_vision",
                    "raw_response": analysis,
                    "hooks_extracted": analysis.get('hooks', []),
                    "benefits_mentioned": analysis.get('benefits', []),
                    "model_used": "gemini-2.0-flash"
                }).execute()

                results.append({"asset_id": asset['id'], "analysis": analysis})

                await asyncio.sleep(1)  # Rate limiting

            except Exception as e:
                logger.error(f"Failed to analyze image {asset['id']}: {e}")
                results.append({"asset_id": asset['id'], "error": str(e)})

        return results

    async def analyze_competitor_copy(
        self,
        competitor_id: UUID,
        limit: int = 50
    ) -> List[Dict]:
        """Analyze competitor ad copy with Claude."""
        from anthropic import Anthropic

        # Get ads that haven't had copy analyzed
        ads_result = self.supabase.table("competitor_ads").select(
            "id, ad_body, ad_title"
        ).eq("competitor_id", str(competitor_id)).execute()

        if not ads_result.data:
            return []

        # Filter out already analyzed
        ad_ids = [a['id'] for a in ads_result.data]
        analyzed_result = self.supabase.table("competitor_ad_analysis").select(
            "competitor_ad_id"
        ).in_("competitor_ad_id", ad_ids).eq("analysis_type", "copy_analysis").execute()

        analyzed_ids = {r['competitor_ad_id'] for r in (analyzed_result.data or [])}
        ads_to_analyze = [a for a in ads_result.data if a['id'] not in analyzed_ids][:limit]

        if not ads_to_analyze:
            return []

        anthropic = Anthropic()
        results = []

        for ad in ads_to_analyze:
            ad_text = f"{ad.get('ad_title', '')}\n\n{ad.get('ad_body', '')}".strip()
            if not ad_text or len(ad_text) < 20:
                continue

            # Skip dynamic catalog ads
            if "{{product" in ad_text.lower():
                continue

            try:
                prompt = f"""Analyze this competitor ad copy for persona and marketing signals.

AD COPY:
{ad_text}

Extract:
1. Hook type and text
2. Pain points addressed
3. Desires appealed to
4. Target persona signals (who is this for?)
5. Key messaging patterns
6. Awareness level (1-5, where 1=unaware, 5=most aware)

Return JSON with: hook, pain_points, desires, persona_signals, messaging_patterns, awareness_level"""

                message = anthropic.messages.create(
                    model="claude-sonnet-4-20250514",
                    max_tokens=1500,
                    messages=[{"role": "user", "content": prompt}]
                )

                response_text = message.content[0].text
                # Parse JSON from response
                if "```json" in response_text:
                    response_text = response_text.split("```json")[1].split("```")[0]
                elif "```" in response_text:
                    response_text = response_text.split("```")[1].split("```")[0]

                analysis = json.loads(response_text.strip())

                # Save analysis
                self.supabase.table("competitor_ad_analysis").insert({
                    "competitor_id": str(competitor_id),
                    "competitor_ad_id": ad['id'],
                    "analysis_type": "copy_analysis",
                    "raw_response": analysis,
                    "hooks_extracted": [analysis.get('hook', {})],
                    "pain_points_addressed": analysis.get('pain_points', []),
                    "desires_appealed": analysis.get('desires', {}),
                    "messaging_patterns": analysis.get('messaging_patterns', []),
                    "awareness_level": analysis.get('awareness_level'),
                    "model_used": "claude-sonnet-4-20250514"
                }).execute()

                results.append({"ad_id": ad['id'], "analysis": analysis})

                await asyncio.sleep(1)  # Rate limiting

            except Exception as e:
                logger.error(f"Failed to analyze copy for ad {ad['id']}: {e}")
                results.append({"ad_id": ad['id'], "error": str(e)})

        return results

    # =========================================================================
    # Landing Page Scraping & Analysis
    # =========================================================================

    async def scrape_competitor_landing_pages(
        self,
        competitor_id: UUID,
        urls: Optional[List[str]] = None,
        limit: int = 10
    ) -> Dict[str, int]:
        """
        Scrape landing pages for a competitor.

        If urls not provided, extracts unique URLs from competitor ads.
        """
        from .web_scraping_service import WebScrapingService

        # Get URLs from ads if not provided
        if not urls:
            ads_result = self.supabase.table("competitor_ads").select(
                "link_url"
            ).eq("competitor_id", str(competitor_id)).execute()

            urls = list(set(
                ad['link_url'] for ad in (ads_result.data or [])
                if ad.get('link_url')
            ))[:limit]

        if not urls:
            return {"urls_found": 0, "pages_scraped": 0, "pages_failed": 0}

        # Filter out already scraped
        existing_result = self.supabase.table("competitor_landing_pages").select(
            "url"
        ).eq("competitor_id", str(competitor_id)).execute()

        existing_urls = {r['url'] for r in (existing_result.data or [])}
        urls_to_scrape = [u for u in urls if u not in existing_urls][:limit]

        if not urls_to_scrape:
            return {"urls_found": len(urls), "pages_scraped": 0, "pages_failed": 0, "already_scraped": len(existing_urls)}

        scraper = WebScrapingService()
        pages_scraped = 0
        pages_failed = 0

        for url in urls_to_scrape:
            try:
                result = await scraper.scrape_url_async(
                    url=url,
                    formats=["markdown"],
                    only_main_content=True,
                    timeout=30000
                )

                if result.success:
                    self.supabase.table("competitor_landing_pages").insert({
                        "competitor_id": str(competitor_id),
                        "url": url,
                        "page_title": result.metadata.get('title') if result.metadata else None,
                        "meta_description": result.metadata.get('description') if result.metadata else None,
                        "raw_markdown": result.markdown,
                        "scraped_at": datetime.utcnow().isoformat()
                    }).execute()
                    pages_scraped += 1
                else:
                    pages_failed += 1

                await asyncio.sleep(2)  # Rate limiting

            except Exception as e:
                logger.error(f"Failed to scrape {url}: {e}")
                pages_failed += 1

        return {
            "urls_found": len(urls),
            "pages_scraped": pages_scraped,
            "pages_failed": pages_failed
        }

    async def analyze_competitor_landing_pages(
        self,
        competitor_id: UUID,
        limit: int = 10
    ) -> List[Dict]:
        """Analyze scraped competitor landing pages."""
        from anthropic import Anthropic

        # Get pages that need analysis
        pages_result = self.supabase.table("competitor_landing_pages").select(
            "id, url, raw_markdown"
        ).eq("competitor_id", str(competitor_id)).is_("analyzed_at", "null").limit(limit).execute()

        if not pages_result.data:
            return []

        anthropic = Anthropic()
        results = []

        for page in pages_result.data:
            if not page.get('raw_markdown'):
                continue

            try:
                prompt = f"""Analyze this competitor landing page for marketing intelligence.

LANDING PAGE CONTENT:
{page['raw_markdown'][:8000]}

Extract:
1. Products mentioned with prices
2. Offers and promotions
3. Social proof elements
4. Guarantees
5. Unique selling propositions (USPs)
6. Objection handling
7. Target persona signals

Return JSON with: products, offers, social_proof, guarantees, usps, objection_handling, persona_signals"""

                message = anthropic.messages.create(
                    model="claude-sonnet-4-20250514",
                    max_tokens=2000,
                    messages=[{"role": "user", "content": prompt}]
                )

                response_text = message.content[0].text
                if "```json" in response_text:
                    response_text = response_text.split("```json")[1].split("```")[0]
                elif "```" in response_text:
                    response_text = response_text.split("```")[1].split("```")[0]

                analysis = json.loads(response_text.strip())

                # Update page with analysis
                self.supabase.table("competitor_landing_pages").update({
                    "products": analysis.get('products', []),
                    "offers": analysis.get('offers', []),
                    "social_proof": analysis.get('social_proof', []),
                    "guarantees": analysis.get('guarantees', []),
                    "usps": analysis.get('usps', []),
                    "objection_handling": analysis.get('objection_handling', []),
                    "analyzed_at": datetime.utcnow().isoformat(),
                    "model_used": "claude-sonnet-4-20250514"
                }).eq("id", page['id']).execute()

                results.append({"page_id": page['id'], "analysis": analysis})

                await asyncio.sleep(2)  # Rate limiting

            except Exception as e:
                logger.error(f"Failed to analyze page {page['id']}: {e}")
                results.append({"page_id": page['id'], "error": str(e)})

        return results

    # =========================================================================
    # Persona Synthesis
    # =========================================================================

    async def synthesize_competitor_persona(
        self,
        competitor_id: UUID
    ) -> Dict[str, Any]:
        """
        Synthesize a 4D persona from all competitor analyses.

        Aggregates insights from video, image, copy, and landing page analyses
        to generate a comprehensive persona of who the competitor is targeting.
        """
        from anthropic import Anthropic

        # Gather all analyses
        analyses_result = self.supabase.table("competitor_ad_analysis").select(
            "analysis_type, raw_response, hooks_extracted, pain_points_addressed, desires_appealed"
        ).eq("competitor_id", str(competitor_id)).execute()

        lp_result = self.supabase.table("competitor_landing_pages").select(
            "products, offers, social_proof, usps, objection_handling"
        ).eq("competitor_id", str(competitor_id)).not_.is_("analyzed_at", "null").execute()

        if not analyses_result.data and not lp_result.data:
            raise ValueError("No analyses found for competitor. Run analysis first.")

        # Compile insights
        all_hooks = []
        all_pain_points = []
        all_desires = []
        all_messaging = []

        for analysis in (analyses_result.data or []):
            if analysis.get('hooks_extracted'):
                all_hooks.extend(analysis['hooks_extracted'])
            if analysis.get('pain_points_addressed'):
                all_pain_points.extend(analysis['pain_points_addressed'])
            if analysis.get('desires_appealed'):
                all_desires.append(analysis['desires_appealed'])
            raw = analysis.get('raw_response', {})
            if raw.get('messaging_patterns'):
                all_messaging.extend(raw['messaging_patterns'])

        lp_insights = {
            "products": [],
            "offers": [],
            "social_proof": [],
            "usps": [],
            "objection_handling": []
        }
        for lp in (lp_result.data or []):
            for key in lp_insights:
                if lp.get(key):
                    lp_insights[key].extend(lp[key] if isinstance(lp[key], list) else [lp[key]])

        # Get competitor info
        competitor = self.get_competitor(competitor_id)

        anthropic = Anthropic()
        prompt = f"""Based on the following analysis of a competitor's marketing, synthesize a detailed 4D persona of their target customer.

COMPETITOR: {competitor.get('name', 'Unknown')}

HOOKS USED IN ADS:
{json.dumps(all_hooks[:20], indent=2)}

PAIN POINTS ADDRESSED:
{json.dumps(list(set(all_pain_points))[:15], indent=2)}

DESIRES APPEALED TO:
{json.dumps(all_desires[:10], indent=2)}

MESSAGING PATTERNS:
{json.dumps(list(set(all_messaging))[:15], indent=2)}

LANDING PAGE INSIGHTS:
- Products: {json.dumps(lp_insights['products'][:5], indent=2)}
- Offers: {json.dumps(lp_insights['offers'][:5], indent=2)}
- Social Proof: {json.dumps(lp_insights['social_proof'][:5], indent=2)}
- USPs: {json.dumps(lp_insights['usps'][:10], indent=2)}
- Objection Handling: {json.dumps(lp_insights['objection_handling'][:5], indent=2)}

Generate a comprehensive 4D persona with:
1. Name and snapshot description
2. Demographics
3. Transformation map (before/after)
4. Pain points (emotional, social, functional)
5. Desires by category
6. Self-narratives and identity
7. Social relations
8. Worldview and values
9. Buying objections
10. Purchase behavior

Return as JSON matching the Persona4D schema."""

        message = anthropic.messages.create(
            model="claude-sonnet-4-20250514",
            max_tokens=4000,
            messages=[{"role": "user", "content": prompt}]
        )

        response_text = message.content[0].text
        if "```json" in response_text:
            response_text = response_text.split("```json")[1].split("```")[0]
        elif "```" in response_text:
            response_text = response_text.split("```")[1].split("```")[0]

        persona_data = json.loads(response_text.strip())

        # Update competitor with last analyzed timestamp
        self.supabase.table("competitors").update({
            "last_analyzed_at": datetime.utcnow().isoformat()
        }).eq("id", str(competitor_id)).execute()

        return persona_data

    # =========================================================================
    # Amazon Review Support
    # =========================================================================

    def scrape_competitor_amazon_reviews(
        self,
        competitor_id: UUID,
        amazon_url: str,
        include_keywords: bool = True,
        include_helpful: bool = True,
        timeout: int = 900
    ) -> Dict[str, Any]:
        """
        Scrape Amazon reviews for a competitor product.

        Delegates to the same Apify actor and scraping strategy used by
        AmazonReviewService for consistency.

        Args:
            competitor_id: Competitor UUID
            amazon_url: Amazon product URL
            include_keywords: Include keyword filter configs
            include_helpful: Include helpful-sort configs
            timeout: Apify run timeout in seconds

        Returns:
            Dict with scrape results (raw_count, unique_count, saved_count)
        """
        from .amazon_review_service import AmazonReviewService

        amazon_service = AmazonReviewService()

        # Parse URL to get ASIN and domain
        asin, domain = amazon_service.parse_amazon_url(amazon_url)
        if not asin:
            return {
                "success": False,
                "error": "Could not extract ASIN from URL",
                "asin": "",
                "raw_reviews_count": 0,
                "unique_reviews_count": 0,
                "reviews_saved": 0
            }

        # Get competitor's brand_id
        competitor = self.get_competitor(competitor_id)
        if not competitor:
            return {"success": False, "error": "Competitor not found"}

        brand_id = competitor['brand_id']

        # Get or create competitor_amazon_urls record
        amazon_url_id = self._get_or_create_competitor_amazon_url(
            competitor_id=competitor_id,
            brand_id=UUID(brand_id),
            amazon_url=amazon_url,
            asin=asin,
            domain=domain
        )

        # Build configs using the same strategy as AmazonReviewService
        configs = amazon_service.build_scrape_configs(
            asin=asin,
            domain=domain,
            include_keywords=include_keywords,
            include_helpful=include_helpful
        )

        logger.info(f"Running Apify with {len(configs)} configs for competitor ASIN {asin}")

        # Run Apify actor
        try:
            result = amazon_service.apify.run_actor_batch(
                actor_id="axesso_data/amazon-reviews-scraper",
                batch_inputs=configs,
                timeout=timeout,
                memory_mbytes=2048
            )
            raw_reviews = result.items
            raw_count = len(raw_reviews)
            logger.info(f"Got {raw_count} raw reviews from Apify")

        except Exception as e:
            logger.error(f"Apify scrape failed for competitor: {e}")
            return {
                "success": False,
                "error": str(e),
                "asin": asin,
                "raw_reviews_count": 0,
                "unique_reviews_count": 0,
                "reviews_saved": 0
            }

        # Deduplicate using same method
        unique_reviews = amazon_service._deduplicate_reviews(raw_reviews)
        unique_count = len(unique_reviews)

        # Save to competitor-specific tables
        saved_count = self._save_competitor_reviews(
            reviews=unique_reviews,
            amazon_url_id=amazon_url_id,
            competitor_id=competitor_id,
            brand_id=UUID(brand_id),
            asin=asin
        )

        # Update stats
        self._update_competitor_amazon_stats(
            amazon_url_id=amazon_url_id,
            reviews_count=saved_count,
            cost_estimate=amazon_service.apify.estimate_cost(raw_count)
        )

        return {
            "success": True,
            "asin": asin,
            "raw_reviews_count": raw_count,
            "unique_reviews_count": unique_count,
            "reviews_saved": saved_count,
            "cost_estimate": amazon_service.apify.estimate_cost(raw_count)
        }

    def _get_or_create_competitor_amazon_url(
        self,
        competitor_id: UUID,
        brand_id: UUID,
        amazon_url: str,
        asin: str,
        domain: str
    ) -> UUID:
        """Get or create competitor_amazon_urls record."""
        # Check if exists
        existing = self.supabase.table("competitor_amazon_urls").select(
            "id"
        ).eq("competitor_id", str(competitor_id)).eq("asin", asin).execute()

        if existing.data:
            return UUID(existing.data[0]["id"])

        # Create new record
        result = self.supabase.table("competitor_amazon_urls").insert({
            "competitor_id": str(competitor_id),
            "brand_id": str(brand_id),
            "amazon_url": amazon_url,
            "asin": asin,
            "domain_code": domain
        }).execute()

        return UUID(result.data[0]["id"])

    def _save_competitor_reviews(
        self,
        reviews: List[Dict],
        amazon_url_id: UUID,
        competitor_id: UUID,
        brand_id: UUID,
        asin: str
    ) -> int:
        """Save competitor reviews to database."""
        import re

        if not reviews:
            return 0

        saved_count = 0
        batch_size = 100

        for i in range(0, len(reviews), batch_size):
            batch = reviews[i:i + batch_size]
            records = []

            for review in batch:
                # Parse date
                review_date = None
                date_str = review.get("date")
                if date_str:
                    try:
                        review_date = datetime.strptime(date_str[:10], "%Y-%m-%d").date()
                    except (ValueError, TypeError):
                        pass

                # Parse rating
                rating = self._parse_rating(review.get("rating"))

                records.append({
                    "competitor_amazon_url_id": str(amazon_url_id),
                    "competitor_id": str(competitor_id),
                    "brand_id": str(brand_id),
                    "review_id": review.get("reviewId"),
                    "asin": asin,
                    "rating": rating,
                    "title": review.get("title"),
                    "body": review.get("text"),
                    "author": review.get("author"),
                    "review_date": review_date.isoformat() if review_date else None,
                    "verified_purchase": review.get("verified", False),
                    "helpful_votes": review.get("numberOfHelpful", 0) or 0,
                })

            try:
                result = self.supabase.table("competitor_amazon_reviews").upsert(
                    records,
                    on_conflict="review_id,asin"
                ).execute()
                saved_count += len(result.data)
            except Exception as e:
                logger.error(f"Error saving competitor review batch: {e}")

        logger.info(f"Saved {saved_count} competitor reviews to database")
        return saved_count

    def _parse_rating(self, rating_value: Any) -> Optional[int]:
        """Parse rating from various formats (mirrors AmazonReviewService)."""
        import re

        if rating_value is None:
            return None

        if isinstance(rating_value, int):
            return rating_value if 1 <= rating_value <= 5 else None

        if isinstance(rating_value, float):
            return int(rating_value) if 1 <= rating_value <= 5 else None

        if isinstance(rating_value, str):
            match = re.search(r'(\d+(?:\.\d+)?)', rating_value)
            if match:
                try:
                    rating = float(match.group(1))
                    return int(rating) if 1 <= rating <= 5 else None
                except ValueError:
                    pass

        return None

    def _update_competitor_amazon_stats(
        self,
        amazon_url_id: UUID,
        reviews_count: int,
        cost_estimate: float
    ):
        """Update competitor_amazon_urls with scrape statistics."""
        try:
            self.supabase.table("competitor_amazon_urls").update({
                "last_scraped_at": datetime.utcnow().isoformat(),
                "total_reviews_scraped": reviews_count,
                "scrape_cost_estimate": cost_estimate
            }).eq("id", str(amazon_url_id)).execute()
        except Exception as e:
            logger.error(f"Error updating competitor amazon stats: {e}")

    async def analyze_competitor_amazon_reviews(
        self,
        competitor_id: UUID,
        limit: int = 500
    ) -> Optional[Dict[str, Any]]:
        """
        Analyze stored competitor reviews with Claude to extract persona signals.

        Uses the same analysis prompt as AmazonReviewService for consistency.

        Args:
            competitor_id: Competitor UUID
            limit: Maximum reviews to analyze

        Returns:
            Analysis results dictionary or None if no reviews
        """
        from anthropic import Anthropic
        from .amazon_review_service import REVIEW_ANALYSIS_PROMPT
        import re

        # Fetch reviews
        result = self.supabase.table("competitor_amazon_reviews").select(
            "rating, title, body, author"
        ).eq("competitor_id", str(competitor_id)).limit(limit).execute()

        if not result.data:
            logger.info(f"No reviews found for competitor {competitor_id}")
            return None

        reviews = result.data
        logger.info(f"Analyzing {len(reviews)} reviews for competitor {competitor_id}")

        # Format reviews for prompt
        reviews_text = self._format_reviews_for_prompt(reviews)

        # Get competitor info
        competitor = self.get_competitor(competitor_id)
        brand_id = competitor['brand_id']

        # Call Claude for analysis
        client = Anthropic()

        try:
            response = client.messages.create(
                model="claude-sonnet-4-20250514",
                max_tokens=4096,
                messages=[{
                    "role": "user",
                    "content": REVIEW_ANALYSIS_PROMPT.format(reviews_text=reviews_text)
                }]
            )

            # Parse response
            analysis_text = response.content[0].text

            # Extract JSON from response
            json_match = re.search(r'\{[\s\S]*\}', analysis_text)
            if json_match:
                analysis = json.loads(json_match.group())
            else:
                logger.error("Could not parse analysis JSON")
                return None

            # Save analysis to database
            self._save_competitor_review_analysis(
                competitor_id=competitor_id,
                brand_id=UUID(brand_id),
                reviews_count=len(reviews),
                analysis=analysis
            )

            return analysis

        except Exception as e:
            logger.error(f"Error analyzing competitor reviews: {e}")
            return None

    def _format_reviews_for_prompt(self, reviews: List[Dict]) -> str:
        """Format reviews for Claude prompt with author attribution."""
        lines = []
        for review in reviews:
            rating = review.get("rating", "?")
            title = review.get("title", "No title")
            body = review.get("body", "No content")
            author = review.get("author", "Anonymous")

            # Format author
            author_formatted = self._format_author_name(author)

            # Truncate long reviews
            if len(body) > 500:
                body = body[:500] + "..."

            lines.append(f"[{rating}★] {author_formatted} | {title}\n{body}\n")

        return "\n---\n".join(lines)

    def _format_author_name(self, author: str) -> str:
        """Format author name as 'First L.' for attribution."""
        if not author or author.lower() in ["anonymous", "a customer", "amazon customer"]:
            return "Verified Buyer"

        author = author.strip()
        if len(author) <= 15:
            return author

        parts = author.split()
        if len(parts) >= 2:
            first = parts[0]
            last_initial = parts[-1][0].upper() + "."
            return f"{first} {last_initial}"

        return author[:15]

    def _save_competitor_review_analysis(
        self,
        competitor_id: UUID,
        brand_id: UUID,
        reviews_count: int,
        analysis: Dict[str, Any]
    ):
        """Save competitor review analysis to database."""
        try:
            # Extract quotes for legacy columns
            transformation_quotes = [
                q.get("text", "") for q in
                analysis.get("transformation", {}).get("quotes", [])
            ]
            pain_quotes = [
                q.get("text", "") for q in
                analysis.get("pain_points", {}).get("quotes", [])
            ]

            # Combine objection categories
            combined_objections = {
                "past_failures": analysis.get("past_failures", {}),
                "buying_objections": analysis.get("buying_objections", {}),
                "familiar_promises": analysis.get("familiar_promises", {})
            }

            # Build purchase triggers
            triggers = []
            for cat in ["transformation", "desired_features"]:
                insights = analysis.get(cat, {}).get("insights", [])
                triggers.extend(insights[:3])

            self.supabase.table("competitor_amazon_review_analysis").upsert({
                "competitor_id": str(competitor_id),
                "brand_id": str(brand_id),
                "total_reviews_analyzed": reviews_count,
                "sentiment_distribution": analysis.get("sentiment_summary", {}),
                "pain_points": analysis.get("pain_points", {}),
                "desires": analysis.get("desired_features", {}),
                "language_patterns": analysis.get("language_patterns", {}),
                "objections": combined_objections,
                "purchase_triggers": triggers,
                "transformation": analysis.get("transformation", {}),
                "transformation_quotes": transformation_quotes,
                "top_positive_quotes": transformation_quotes[:5],
                "top_negative_quotes": pain_quotes[:5],
                "model_used": "claude-sonnet-4-20250514",
                "analyzed_at": datetime.utcnow().isoformat()
            }, on_conflict="competitor_id").execute()

            logger.info(f"Saved competitor review analysis for {competitor_id}")

        except Exception as e:
            logger.error(f"Error saving competitor review analysis: {e}")

    def get_competitor_amazon_stats(self, competitor_id: UUID) -> Dict[str, Any]:
        """Get Amazon review statistics for a competitor."""
        # Get amazon URL info
        url_result = self.supabase.table("competitor_amazon_urls").select(
            "id, asin, last_scraped_at, total_reviews_scraped, scrape_cost_estimate"
        ).eq("competitor_id", str(competitor_id)).execute()

        # Get review count
        review_result = self.supabase.table("competitor_amazon_reviews").select(
            "id", count="exact"
        ).eq("competitor_id", str(competitor_id)).execute()

        # Check if analysis exists
        analysis_result = self.supabase.table("competitor_amazon_review_analysis").select(
            "analyzed_at, total_reviews_analyzed"
        ).eq("competitor_id", str(competitor_id)).execute()

        url_data = url_result.data[0] if url_result.data else {}
        analysis_data = analysis_result.data[0] if analysis_result.data else {}

        return {
            "has_amazon_url": bool(url_result.data),
            "asin": url_data.get("asin"),
            "reviews_scraped": url_data.get("total_reviews_scraped", 0),
            "reviews_in_db": review_result.count or 0,
            "last_scraped": url_data.get("last_scraped_at"),
            "cost_estimate": url_data.get("scrape_cost_estimate", 0),
            "has_analysis": bool(analysis_result.data),
            "analyzed_at": analysis_data.get("analyzed_at"),
            "reviews_analyzed": analysis_data.get("total_reviews_analyzed", 0)
        }

    def get_competitor_amazon_analysis(self, competitor_id: UUID) -> Optional[Dict[str, Any]]:
        """Get the full Amazon review analysis for a competitor.

        Args:
            competitor_id: UUID of the competitor

        Returns:
            Full analysis dict with pain_points, desires, language_patterns, quotes, etc.
            Returns None if no analysis exists.
        """
        result = self.supabase.table("competitor_amazon_review_analysis").select(
            "*"
        ).eq("competitor_id", str(competitor_id)).execute()

        if not result.data:
            return None

        return result.data[0]


# Convenience function
def get_competitor_service() -> CompetitorService:
    """Get a CompetitorService instance."""
    return CompetitorService()
