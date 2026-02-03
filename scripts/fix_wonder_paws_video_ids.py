#!/usr/bin/env python3
"""
Fix Wonder Paws video_ids in meta_ads_performance table.

The issue: Some video_ids were stored as the top-level video_id (published Reel),
but the correct ID for downloading source files is video_data.video_id (uploaded asset).

This script:
1. Gets all video ads for Wonder Paws
2. Fetches fresh creative data from Meta API
3. Updates meta_video_id where video_data.video_id differs from stored value
"""

import asyncio
import logging
import os
import sys

# Add project root to path
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from dotenv import load_dotenv
load_dotenv()

from supabase import create_client
from viraltracker.core.config import Config
from viraltracker.services.meta_ads_service import MetaAdsService

logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

WONDER_PAWS_BRAND_ID = "bc8461a8-232d-4765-8775-c75eaafc5503"


async def fix_video_ids():
    """Fix video_ids for Wonder Paws brand."""
    supabase = create_client(Config.SUPABASE_URL, Config.SUPABASE_SERVICE_KEY)
    service = MetaAdsService()

    # Step 1: Get ACTIVE video ads for Wonder Paws only (deduplicated by meta_ad_id)
    logger.info("Fetching ACTIVE video ads for Wonder Paws...")
    result = supabase.table("meta_ads_performance").select(
        "id, meta_ad_id, meta_video_id"
    ).eq("brand_id", WONDER_PAWS_BRAND_ID).eq("is_video", True).eq("ad_status", "ACTIVE").not_.is_("meta_video_id", "null").execute()

    # Deduplicate by meta_ad_id (keep first occurrence)
    seen = set()
    video_ads = []
    for ad in result.data:
        if ad["meta_ad_id"] not in seen:
            seen.add(ad["meta_ad_id"])
            video_ads.append(ad)

    logger.info(f"Found {len(video_ads)} unique video ads with meta_video_id set (from {len(result.data)} rows)")

    if not video_ads:
        logger.info("No video ads to fix")
        return

    # Step 2: Fetch fresh creative data
    ad_ids = [ad["meta_ad_id"] for ad in video_ads]
    logger.info(f"Fetching fresh creative data for {len(ad_ids)} ads...")

    thumbnails = await service.fetch_ad_thumbnails(ad_ids)

    # Step 3: Compare and update
    updates_made = 0
    for ad in video_ads:
        meta_ad_id = ad["meta_ad_id"]
        old_video_id = ad["meta_video_id"]

        fresh_data = thumbnails.get(meta_ad_id, {})
        new_video_id = fresh_data.get("video_id")

        if not new_video_id:
            logger.warning(f"Ad {meta_ad_id}: No video_id in fresh data, skipping")
            continue

        if old_video_id != new_video_id:
            logger.info(f"Ad {meta_ad_id}:")
            logger.info(f"  Old video_id: {old_video_id}")
            logger.info(f"  New video_id: {new_video_id}")
            logger.info(f"  -> Updating ALL rows for this ad!")

            # Update ALL rows with this meta_ad_id (not just one)
            supabase.table("meta_ads_performance").update({
                "meta_video_id": new_video_id
            }).eq("meta_ad_id", meta_ad_id).execute()

            updates_made += 1
        else:
            logger.info(f"Ad {meta_ad_id}: video_id already correct ({old_video_id})")

    logger.info(f"\nDone! Updated {updates_made} of {len(video_ads)} video ads")


if __name__ == "__main__":
    asyncio.run(fix_video_ids())
