"""
Brand Onboarding Pipeline - Pydantic Graph workflow.

Pipeline: ScrapeAds → DownloadAssets → AnalyzeImages → AnalyzeVideos → Synthesize

This pipeline automates brand research by:
1. Scraping ads from Facebook Ad Library
2. Downloading images and videos
3. Analyzing images with Claude Vision
4. Analyzing videos with Gemini (optional)
5. Synthesizing insights into a brand research summary

Part of the Brand Research Pipeline (Phase 2A).
"""

import logging
from dataclasses import dataclass
from typing import ClassVar, Union
from uuid import UUID

from pydantic_graph import BaseNode, End, Graph, GraphRunContext

from .metadata import NodeMetadata
from .states import BrandOnboardingState
from ..agent.dependencies import AgentDependencies

logger = logging.getLogger(__name__)


@dataclass
class ScrapeAdsNode(BaseNode[BrandOnboardingState]):
    """
    Step 1: Scrape ads from Ad Library URL.

    Uses FacebookService to scrape ads via Apify, saving them
    to the facebook_ads table.
    """

    metadata: ClassVar[NodeMetadata] = NodeMetadata(
        inputs=["ad_library_url", "brand_id", "max_ads"],
        outputs=["ad_ids", "total_ads_scraped"],
        services=["facebook.search_ads", "ad_scraping.save_facebook_ad"],
    )

    async def run(
        self,
        ctx: GraphRunContext[BrandOnboardingState, AgentDependencies]
    ) -> "DownloadAssetsNode":
        logger.info(f"Step 1: Scraping ads from {ctx.state.ad_library_url[:60]}...")
        ctx.state.current_step = "scraping"

        try:
            # Use FacebookService to scrape ads
            ads = await ctx.deps.facebook.search_ads(
                search_url=ctx.state.ad_library_url,
                project="brand_research",
                count=ctx.state.max_ads,
                save_to_db=False  # We'll save manually with brand_id
            )

            if not ads:
                logger.warning("No ads found from search")
                ctx.state.current_step = "complete"
                return End({"status": "no_ads", "message": "No ads found at the provided URL"})

            # Save ads to database with brand_id
            saved_ids = []
            for ad in ads:
                ad_dict = {
                    "id": ad.id,
                    "ad_archive_id": ad.ad_archive_id,
                    "page_id": ad.page_id,
                    "page_name": ad.page_name,
                    "is_active": ad.is_active,
                    "start_date": ad.start_date.isoformat() if ad.start_date else None,
                    "end_date": ad.end_date.isoformat() if ad.end_date else None,
                    "currency": ad.currency,
                    "spend": ad.spend,
                    "impressions": ad.impressions,
                    "reach_estimate": ad.reach_estimate,
                    "snapshot": ad.snapshot,
                    "categories": ad.categories,
                    "publisher_platform": ad.publisher_platform,
                    "political_countries": ad.political_countries,
                    "entity_type": ad.entity_type,
                }

                ad_id = ctx.deps.ad_scraping.save_facebook_ad(
                    ad_data=ad_dict,
                    brand_id=ctx.state.brand_id,
                    scrape_source="brand_research_pipeline"
                )
                if ad_id:
                    saved_ids.append(ad_id)

            ctx.state.ad_ids = saved_ids
            ctx.state.total_ads_scraped = len(saved_ids)
            ctx.state.current_step = "scraped"

            logger.info(f"Scraped and saved {len(saved_ids)} ads")
            return DownloadAssetsNode()

        except Exception as e:
            ctx.state.error = str(e)
            ctx.state.current_step = "failed"
            logger.error(f"Scrape failed: {e}")
            return End({"status": "error", "error": str(e), "step": "scrape"})


@dataclass
class DownloadAssetsNode(BaseNode[BrandOnboardingState]):
    """
    Step 2: Download images and videos from scraped ads.

    Uses AdScrapingService to download assets from Facebook CDN
    and store them in Supabase storage.
    """

    metadata: ClassVar[NodeMetadata] = NodeMetadata(
        inputs=["ad_ids", "brand_id"],
        outputs=["image_asset_ids", "video_asset_ids", "total_images", "total_videos"],
        services=["ad_scraping.scrape_and_store_assets"],
    )

    async def run(
        self,
        ctx: GraphRunContext[BrandOnboardingState, AgentDependencies]
    ) -> "AnalyzeImagesNode":
        logger.info(f"Step 2: Downloading assets from {len(ctx.state.ad_ids)} ads")
        ctx.state.current_step = "downloading"

        try:
            # Get ads and download assets
            for ad_id in ctx.state.ad_ids:
                # Get snapshot from database
                result = ctx.deps.ad_scraping.supabase.table("facebook_ads").select(
                    "id, snapshot"
                ).eq("id", str(ad_id)).execute()

                if not result.data:
                    continue

                snapshot = result.data[0].get("snapshot", {})
                if not snapshot:
                    continue

                # Download and store assets
                assets = await ctx.deps.ad_scraping.scrape_and_store_assets(
                    facebook_ad_id=ad_id,
                    snapshot=snapshot,
                    brand_id=ctx.state.brand_id,
                    scrape_source="brand_research_pipeline"
                )

                # Collect asset IDs
                ctx.state.image_asset_ids.extend(assets.get("images", []))
                ctx.state.video_asset_ids.extend(assets.get("videos", []))

            ctx.state.total_images = len(ctx.state.image_asset_ids)
            ctx.state.total_videos = len(ctx.state.video_asset_ids)
            ctx.state.current_step = "downloaded"

            logger.info(
                f"Downloaded {ctx.state.total_images} images, "
                f"{ctx.state.total_videos} videos"
            )
            return AnalyzeImagesNode()

        except Exception as e:
            ctx.state.error = str(e)
            ctx.state.current_step = "failed"
            logger.error(f"Download failed: {e}")
            return End({"status": "error", "error": str(e), "step": "download"})


@dataclass
class AnalyzeImagesNode(BaseNode[BrandOnboardingState]):
    """
    Step 3: Analyze images with Claude Vision.

    Uses BrandResearchService to analyze each image,
    extracting hooks, benefits, USPs, and visual style.
    """

    metadata: ClassVar[NodeMetadata] = NodeMetadata(
        inputs=["image_asset_ids", "brand_id", "analyze_videos", "video_asset_ids"],
        outputs=["image_analyses"],
        services=["brand_research.analyze_images_batch"],
        llm="Claude Vision",
        llm_purpose="Extract hooks, benefits, USPs, and visual style from images",
    )

    async def run(
        self,
        ctx: GraphRunContext[BrandOnboardingState, AgentDependencies]
    ) -> Union["AnalyzeVideosNode", "SynthesizeNode"]:
        logger.info(f"Step 3: Analyzing {len(ctx.state.image_asset_ids)} images")
        ctx.state.current_step = "analyzing_images"

        try:
            if ctx.state.image_asset_ids:
                analyses = await ctx.deps.brand_research.analyze_images_batch(
                    asset_ids=ctx.state.image_asset_ids,
                    brand_id=ctx.state.brand_id
                )
                ctx.state.image_analyses = analyses

            ctx.state.current_step = "images_analyzed"
            logger.info(f"Analyzed {len(ctx.state.image_analyses)} images")

            # Skip video analysis if not requested or no videos
            if ctx.state.analyze_videos and ctx.state.video_asset_ids:
                return AnalyzeVideosNode()
            else:
                return SynthesizeNode()

        except Exception as e:
            ctx.state.error = str(e)
            ctx.state.current_step = "failed"
            logger.error(f"Image analysis failed: {e}")
            return End({"status": "error", "error": str(e), "step": "analyze_images"})


@dataclass
class AnalyzeVideosNode(BaseNode[BrandOnboardingState]):
    """
    Step 4: Analyze videos with Gemini.

    Uses BrandResearchService to analyze videos,
    extracting transcripts, hooks, and storyboards.
    """

    metadata: ClassVar[NodeMetadata] = NodeMetadata(
        inputs=["video_asset_ids"],
        outputs=["video_analyses"],
        services=["brand_research.analyze_videos_batch"],
        llm="Gemini",
        llm_purpose="Extract transcripts, hooks, and storyboards from videos (placeholder)",
    )

    async def run(
        self,
        ctx: GraphRunContext[BrandOnboardingState, AgentDependencies]
    ) -> "SynthesizeNode":
        logger.info(f"Step 4: Analyzing {len(ctx.state.video_asset_ids)} videos")
        ctx.state.current_step = "analyzing_videos"

        try:
            # Video analysis is optional - skip if not implemented
            # For Phase 2A, we'll just log and continue
            if ctx.state.video_asset_ids:
                logger.info("Video analysis not yet implemented - skipping")
                # TODO: Implement in Phase 2A.4
                # analyses = await ctx.deps.brand_research.analyze_videos_batch(...)
                # ctx.state.video_analyses = analyses

            ctx.state.current_step = "videos_analyzed"
            logger.info(f"Video analysis step complete (pending implementation)")
            return SynthesizeNode()

        except Exception as e:
            ctx.state.error = str(e)
            ctx.state.current_step = "failed"
            logger.error(f"Video analysis failed: {e}")
            return End({"status": "error", "error": str(e), "step": "analyze_videos"})


@dataclass
class SynthesizeNode(BaseNode[BrandOnboardingState]):
    """
    Step 5: Synthesize all insights into brand research summary.

    Uses BrandResearchService to combine all analyses into
    a comprehensive brand research summary with:
    - Top benefits and USPs
    - Common pain points
    - Recommended hooks
    - Persona profile
    - Brand voice summary
    - Visual style guide
    """

    metadata: ClassVar[NodeMetadata] = NodeMetadata(
        inputs=["image_analyses", "video_analyses", "brand_id"],
        outputs=["summary", "product_data"],
        services=["brand_research.synthesize_insights", "brand_research.export_to_product_data"],
        llm="Claude",
        llm_purpose="Synthesize all analyses into comprehensive brand research summary",
    )

    async def run(
        self,
        ctx: GraphRunContext[BrandOnboardingState, AgentDependencies]
    ) -> End[dict]:
        logger.info("Step 5: Synthesizing brand insights")
        ctx.state.current_step = "synthesizing"

        try:
            # Need at least some analyses to synthesize
            if not ctx.state.image_analyses and not ctx.state.video_analyses:
                logger.warning("No analyses to synthesize")
                ctx.state.current_step = "complete"
                return End({
                    "status": "no_analyses",
                    "message": "No images or videos could be analyzed",
                    "metrics": {
                        "ads_scraped": ctx.state.total_ads_scraped,
                        "images_downloaded": ctx.state.total_images,
                        "videos_downloaded": ctx.state.total_videos
                    }
                })

            # Synthesize insights
            if ctx.state.brand_id:
                summary = await ctx.deps.brand_research.synthesize_insights(
                    brand_id=ctx.state.brand_id,
                    image_analyses=ctx.state.image_analyses,
                    video_analyses=ctx.state.video_analyses,
                    copy_data=[]  # TODO: Add copy extraction
                )
            else:
                # Without brand_id, still run synthesis but don't save
                summary = await ctx.deps.brand_research.synthesize_insights(
                    brand_id=UUID("00000000-0000-0000-0000-000000000000"),  # Placeholder
                    image_analyses=ctx.state.image_analyses,
                    video_analyses=ctx.state.video_analyses,
                    copy_data=[]
                )

            ctx.state.summary = summary
            ctx.state.product_data = ctx.deps.brand_research.export_to_product_data(summary)
            ctx.state.current_step = "complete"

            logger.info("Brand research complete")
            return End({
                "status": "success",
                "summary": summary,
                "product_data": ctx.state.product_data,
                "metrics": {
                    "ads_scraped": ctx.state.total_ads_scraped,
                    "images_analyzed": len(ctx.state.image_analyses),
                    "videos_analyzed": len(ctx.state.video_analyses)
                }
            })

        except Exception as e:
            ctx.state.error = str(e)
            ctx.state.current_step = "failed"
            logger.error(f"Synthesis failed: {e}")
            return End({"status": "error", "error": str(e), "step": "synthesize"})


# Build the graph
brand_onboarding_graph = Graph(
    nodes=(
        ScrapeAdsNode,
        DownloadAssetsNode,
        AnalyzeImagesNode,
        AnalyzeVideosNode,
        SynthesizeNode
    ),
    name="brand_onboarding"
)


# Convenience function for running the pipeline
async def run_brand_onboarding(
    ad_library_url: str,
    brand_id: UUID = None,
    max_ads: int = 50,
    analyze_videos: bool = True
) -> dict:
    """
    Run the brand onboarding pipeline.

    This is a convenience function that creates dependencies
    and runs the full pipeline.

    Args:
        ad_library_url: Facebook Ad Library search URL
        brand_id: Optional brand UUID to link research to
        max_ads: Maximum ads to scrape (default 50)
        analyze_videos: Whether to analyze video ads (default True)

    Returns:
        Pipeline result with summary and product data

    Example:
        >>> result = await run_brand_onboarding(
        ...     ad_library_url="https://www.facebook.com/ads/library/?...",
        ...     brand_id=UUID("..."),
        ...     max_ads=20
        ... )
        >>> print(result["status"])  # "success"
        >>> print(result["product_data"]["benefits"])
    """
    from ..agent.dependencies import AgentDependencies

    deps = AgentDependencies.create()

    result = await brand_onboarding_graph.run(
        ScrapeAdsNode(),
        state=BrandOnboardingState(
            ad_library_url=ad_library_url,
            brand_id=brand_id,
            max_ads=max_ads,
            analyze_videos=analyze_videos
        ),
        deps=deps
    )

    return result.output
