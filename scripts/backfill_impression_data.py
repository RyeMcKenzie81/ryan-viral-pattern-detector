#!/usr/bin/env python3
"""
Backfill script for Fix 10 Phase 1: Parse impressions + Queue dedup cleanup.

Tasks:
1. Parse existing `impressions` TEXT column on facebook_ads into
   impression_lower, impression_upper, impression_text.
2. Clean up template_queue duplicates sharing the same collation_id
   (keep earliest per group, archive the rest).

Usage:
    python scripts/backfill_impression_data.py [--dry-run]
"""

import argparse
import logging
import sys

# Add project root to path
sys.path.insert(0, ".")

from viraltracker.core.database import get_supabase_client
from viraltracker.services.ad_scraping_service import parse_impression_data

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
logger = logging.getLogger(__name__)


def backfill_impressions(supabase, dry_run: bool = False):
    """Parse existing impressions TEXT column into structured fields."""
    logger.info("=== Backfilling impression data ===")

    updated = 0
    skipped = 0
    batch_size = 1000

    while True:
        result = supabase.table("facebook_ads").select(
            "id, impressions"
        ).not_.is_("impressions", "null").is_("impression_lower", "null").limit(batch_size).execute()

        if not result.data:
            break

        for row in result.data:
            raw = row["impressions"]
            lower, upper, text = parse_impression_data(raw)

            if lower is None:
                skipped += 1
                continue

            if dry_run:
                logger.info(f"  [DRY RUN] Would update ad {row['id']}: {raw} -> lower={lower}, upper={upper}, text={text}")
            else:
                supabase.table("facebook_ads").update({
                    "impression_lower": lower,
                    "impression_upper": upper,
                    "impression_text": text,
                }).eq("id", row["id"]).execute()

            updated += 1

        logger.info(f"  Batch: processed {len(result.data)} rows ({updated} updated so far)")

        # In dry-run mode, rows aren't updated so the same batch would return forever
        if dry_run or len(result.data) < batch_size:
            break

    logger.info(f"Impression backfill: {updated} updated, {skipped} unparseable")
    return updated


def dedup_template_queue(supabase, dry_run: bool = False):
    """Archive duplicate template_queue items sharing the same collation_id.

    Keeps the earliest (first created) item per collation group, archives the rest.
    Only affects items in 'pending' status.
    """
    logger.info("=== Deduplicating template queue by collation_id ===")

    # Find pending queue items that have a collation_id via the join chain:
    # template_queue -> scraped_ad_assets -> facebook_ads
    # Supabase doesn't support complex joins directly, so we do it in steps.

    # Step 1: Get all pending queue items with their facebook_ad_id
    queue_result = supabase.table("template_queue").select(
        "id, asset_id, created_at"
    ).eq("status", "pending").order("created_at").execute()

    if not queue_result.data:
        logger.info("No pending queue items found")
        return 0

    logger.info(f"Found {len(queue_result.data)} pending queue items")

    # Step 2: Get asset -> facebook_ad mapping
    asset_ids = [item["asset_id"] for item in queue_result.data if item.get("asset_id")]
    if not asset_ids:
        logger.info("No asset_ids found on queue items")
        return 0

    # Fetch in batches (Supabase has limits on IN clause)
    asset_to_fb_ad = {}
    batch_size = 100
    for i in range(0, len(asset_ids), batch_size):
        batch = asset_ids[i:i + batch_size]
        assets_result = supabase.table("scraped_ad_assets").select(
            "id, facebook_ad_id"
        ).in_("id", batch).execute()
        if assets_result.data:
            for asset in assets_result.data:
                asset_to_fb_ad[asset["id"]] = asset["facebook_ad_id"]

    # Step 3: Get facebook_ad -> collation_id mapping
    fb_ad_ids = list(set(asset_to_fb_ad.values()))
    if not fb_ad_ids:
        logger.info("No facebook_ad_ids found for queue assets")
        return 0

    fb_ad_to_collation = {}
    for i in range(0, len(fb_ad_ids), batch_size):
        batch = fb_ad_ids[i:i + batch_size]
        fb_result = supabase.table("facebook_ads").select(
            "id, collation_id"
        ).in_("id", batch).not_.is_("collation_id", "null").execute()
        if fb_result.data:
            for fb_ad in fb_result.data:
                fb_ad_to_collation[fb_ad["id"]] = fb_ad["collation_id"]

    # Step 4: Group queue items by collation_id
    collation_groups = {}  # collation_id -> [queue_item, ...]
    for item in queue_result.data:
        fb_ad_id = asset_to_fb_ad.get(item.get("asset_id"))
        if not fb_ad_id:
            continue
        collation_id = fb_ad_to_collation.get(fb_ad_id)
        if not collation_id:
            continue
        if collation_id not in collation_groups:
            collation_groups[collation_id] = []
        collation_groups[collation_id].append(item)

    # Step 5: For each group with >1 item, archive all but the first (earliest)
    archived_count = 0
    groups_with_dupes = 0

    for collation_id, items in collation_groups.items():
        if len(items) <= 1:
            continue

        groups_with_dupes += 1
        # Items are already ordered by created_at (from the query), keep first
        to_archive = [item["id"] for item in items[1:]]

        if dry_run:
            logger.info(f"  [DRY RUN] collation {collation_id}: keep 1, would archive {len(to_archive)}")
        else:
            for qid in to_archive:
                supabase.table("template_queue").update(
                    {"status": "archived"}
                ).eq("id", qid).execute()

        archived_count += len(to_archive)

    logger.info(f"Queue dedup: {archived_count} archived across {groups_with_dupes} collation groups")
    return archived_count


def main():
    parser = argparse.ArgumentParser(description="Backfill impression data and dedup template queue")
    parser.add_argument("--dry-run", action="store_true", help="Preview changes without writing")
    args = parser.parse_args()

    supabase = get_supabase_client()

    impression_count = backfill_impressions(supabase, dry_run=args.dry_run)
    dedup_count = dedup_template_queue(supabase, dry_run=args.dry_run)

    logger.info(f"\n=== Complete ===")
    logger.info(f"Impressions backfilled: {impression_count}")
    logger.info(f"Queue items archived: {dedup_count}")

    if args.dry_run:
        logger.info("(DRY RUN — no changes written)")


if __name__ == "__main__":
    main()
