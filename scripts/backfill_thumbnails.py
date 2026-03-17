#!/usr/bin/env python3
"""One-shot script to backfill missing thumbnails for a brand.

Usage:
    python scripts/backfill_thumbnails.py <brand_id> [--limit 200]

Calls MetaAdsService.update_missing_thumbnails() which:
1. Finds ads with NULL/empty thumbnail_url in meta_ads_performance
2. Fetches creative metadata from Meta API
3. Updates all daily rows for each ad
"""
import argparse
import asyncio
import sys
import os

# Add project root to path
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


async def main():
    parser = argparse.ArgumentParser(description="Backfill missing ad thumbnails")
    parser.add_argument("brand_id", help="Brand UUID")
    parser.add_argument("--limit", type=int, default=200, help="Max ads to process (default: 200)")
    args = parser.parse_args()

    from uuid import UUID
    from viraltracker.services.meta_ads_service import MetaAdsService

    service = MetaAdsService()
    print(f"Backfilling thumbnails for brand {args.brand_id} (limit: {args.limit})...")

    updated = await service.update_missing_thumbnails(
        brand_id=UUID(args.brand_id),
        limit=args.limit
    )

    print(f"Done — updated {updated} ads with thumbnails")


if __name__ == "__main__":
    asyncio.run(main())
