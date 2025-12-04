"""
Template Ingestion Pipeline - Pydantic Graph workflow.

Pipeline: ScrapeAds → DownloadAssets → QueueForReview → [PAUSE for human review]

This pipeline automates template ingestion by:
1. Scraping ads from Facebook Ad Library
2. Downloading images (optionally videos)
3. Adding to template queue for human review
4. Pipeline pauses - human reviews in Streamlit UI
5. After approval, templates are available in library

Part of the Brand Research Pipeline (Phase 2B).
"""

import logging
from dataclasses import dataclass
from uuid import UUID

from pydantic_graph import BaseNode, End, Graph, GraphRunContext

from .states import TemplateIngestionState
from ..agent.dependencies import AgentDependencies

logger = logging.getLogger(__name__)


@dataclass
class ScrapeAdsNode(BaseNode[TemplateIngestionState]):
    """
    Step 1: Scrape ads from Ad Library URL.

    Uses FacebookService to scrape ads via Apify.
    """

    async def run(
        self,
        ctx: GraphRunContext[TemplateIngestionState, AgentDependencies]
    ) -> "DownloadAssetsNode":
        logger.info(f"Step 1: Scraping ads from {ctx.state.ad_library_url[:60]}...")
        ctx.state.current_step = "scraping"

        try:
            # Use FacebookService to scrape ads
            ads = await ctx.deps.facebook.search_ads(
                search_url=ctx.state.ad_library_url,
                project="template_ingestion",
                count=ctx.state.max_ads,
                save_to_db=False
            )

            if not ads:
                logger.warning("No ads found from search")
                ctx.state.current_step = "complete"
                return End({"status": "no_ads", "message": "No ads found at the provided URL"})

            # Save ads to database
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
                    scrape_source="template_ingestion_pipeline"
                )
                if ad_id:
                    saved_ids.append(ad_id)

            ctx.state.ad_ids = saved_ids
            ctx.state.current_step = "scraped"

            logger.info(f"Scraped and saved {len(saved_ids)} ads")
            return DownloadAssetsNode()

        except Exception as e:
            ctx.state.error = str(e)
            ctx.state.current_step = "failed"
            logger.error(f"Scrape failed: {e}")
            return End({"status": "error", "error": str(e), "step": "scrape"})


@dataclass
class DownloadAssetsNode(BaseNode[TemplateIngestionState]):
    """
    Step 2: Download assets (images only by default for templates).

    Uses AdScrapingService to download and store assets.
    """

    async def run(
        self,
        ctx: GraphRunContext[TemplateIngestionState, AgentDependencies]
    ) -> "QueueForReviewNode":
        logger.info(f"Step 2: Downloading assets from {len(ctx.state.ad_ids)} ads")
        ctx.state.current_step = "downloading"

        try:
            all_asset_ids = []

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
                    scrape_source="template_ingestion_pipeline"
                )

                # Filter to images only if requested
                if ctx.state.images_only:
                    all_asset_ids.extend(assets.get("images", []))
                else:
                    all_asset_ids.extend(assets.get("images", []))
                    all_asset_ids.extend(assets.get("videos", []))

            ctx.state.asset_ids = all_asset_ids
            ctx.state.current_step = "downloaded"

            logger.info(f"Downloaded {len(all_asset_ids)} assets")
            return QueueForReviewNode()

        except Exception as e:
            ctx.state.error = str(e)
            ctx.state.current_step = "failed"
            logger.error(f"Download failed: {e}")
            return End({"status": "error", "error": str(e), "step": "download"})


@dataclass
class QueueForReviewNode(BaseNode[TemplateIngestionState]):
    """
    Step 3: Add assets to template queue and PAUSE for human review.

    The pipeline ends here - human reviews in Streamlit UI.
    After approval, templates appear in the library.
    """

    async def run(
        self,
        ctx: GraphRunContext[TemplateIngestionState, AgentDependencies]
    ) -> End[dict]:
        logger.info(f"Step 3: Queueing {len(ctx.state.asset_ids)} assets for review")
        ctx.state.current_step = "queueing"

        try:
            if not ctx.state.asset_ids:
                ctx.state.current_step = "complete"
                return End({
                    "status": "no_assets",
                    "message": "No assets to queue for review"
                })

            # Add to queue
            count = await ctx.deps.template_queue.add_to_queue(
                asset_ids=ctx.state.asset_ids,
                run_ai_analysis=ctx.state.run_ai_analysis
            )

            ctx.state.queue_ids = ctx.state.asset_ids  # Track what was queued
            ctx.state.current_step = "queued"
            ctx.state.awaiting_approval = True

            logger.info(f"Queued {count} items for review")

            # Pipeline pauses here - human reviews in Streamlit UI
            return End({
                "status": "awaiting_approval",
                "queued_count": count,
                "ads_scraped": len(ctx.state.ad_ids),
                "assets_downloaded": len(ctx.state.asset_ids),
                "message": "Items added to template queue. Review in Template Queue UI."
            })

        except Exception as e:
            ctx.state.error = str(e)
            ctx.state.current_step = "failed"
            logger.error(f"Queue failed: {e}")
            return End({"status": "error", "error": str(e), "step": "queue"})


# Build the graph
template_ingestion_graph = Graph(
    nodes=(
        ScrapeAdsNode,
        DownloadAssetsNode,
        QueueForReviewNode
    ),
    name="template_ingestion"
)


# Convenience function
async def run_template_ingestion(
    ad_library_url: str,
    max_ads: int = 50,
    images_only: bool = True,
    run_ai_analysis: bool = True
) -> dict:
    """
    Run the template ingestion pipeline.

    Scrapes ads, downloads assets, and queues them for human review.
    The pipeline pauses after queueing - human reviews in Streamlit UI.

    Args:
        ad_library_url: Facebook Ad Library search URL
        max_ads: Maximum ads to scrape (default 50)
        images_only: Only queue images, not videos (default True)
        run_ai_analysis: Run AI pre-analysis for reviewers (default True)

    Returns:
        Pipeline result with queue status

    Example:
        >>> result = await run_template_ingestion(
        ...     ad_library_url="https://www.facebook.com/ads/library/?...",
        ...     max_ads=20
        ... )
        >>> print(result["status"])  # "awaiting_approval"
        >>> print(result["queued_count"])  # 15
    """
    from ..agent.dependencies import AgentDependencies

    deps = AgentDependencies.create()

    result = await template_ingestion_graph.run(
        ScrapeAdsNode(),
        state=TemplateIngestionState(
            ad_library_url=ad_library_url,
            max_ads=max_ads,
            images_only=images_only,
            run_ai_analysis=run_ai_analysis
        ),
        deps=deps
    )

    return result.output
