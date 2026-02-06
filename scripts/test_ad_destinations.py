#!/usr/bin/env python3
"""Test script for Phase 3: Ad Destination URL Fetching & LP Matching.

Usage:
    python scripts/test_ad_destinations.py

Tests:
1. Fetch destination URLs from Meta API for Wonder Paws ads
2. Store in meta_ad_destinations with canonicalization
3. Match to brand_landing_pages
"""

import asyncio
import os
import sys

# Add project root to path
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from uuid import UUID


async def main():
    from viraltracker.core.database import get_supabase_client
    from viraltracker.services.meta_ads_service import MetaAdsService
    from viraltracker.services.url_canonicalizer import canonicalize_url

    supabase = get_supabase_client()
    meta_service = MetaAdsService()

    # Wonder Paws brand ID
    brand_id = UUID("bc8461a8-232d-4765-8775-c75eaafc5503")

    # Get org_id for Wonder Paws
    brand_result = supabase.table("brands").select("organization_id, name").eq(
        "id", str(brand_id)
    ).limit(1).execute()

    if not brand_result.data:
        print("ERROR: Wonder Paws brand not found")
        return

    org_id = UUID(brand_result.data[0]["organization_id"])
    brand_name = brand_result.data[0]["name"]
    print(f"Brand: {brand_name}")
    print(f"Brand ID: {brand_id}")
    print(f"Org ID: {org_id}")

    # Get sample ad IDs
    ads_result = supabase.table("meta_ads_performance").select(
        "meta_ad_id, ad_name"
    ).eq(
        "brand_id", str(brand_id)
    ).limit(10).execute()

    if not ads_result.data:
        print("ERROR: No ads found for Wonder Paws")
        return

    ad_ids = list(set(r["meta_ad_id"] for r in ads_result.data))
    print(f"\nFound {len(ad_ids)} unique ads to test")

    # Test 1: Fetch destination URLs
    print(f"\n{'='*60}")
    print("TEST 1: Fetch Destination URLs from Meta API")
    print(f"{'='*60}")

    destinations = await meta_service.fetch_ad_destination_urls(ad_ids[:5])
    print(f"Fetched {len(destinations)} destination URLs")

    for ad_id, url in list(destinations.items())[:3]:
        canonical = canonicalize_url(url)
        print(f"\n  Ad: {ad_id}")
        print(f"  Original:   {url[:80]}...")
        print(f"  Canonical:  {canonical}")

    # Test 2: Sync to database
    print(f"\n{'='*60}")
    print("TEST 2: Sync Destinations to Database")
    print(f"{'='*60}")

    stats = await meta_service.sync_ad_destinations_to_db(
        brand_id=brand_id,
        organization_id=org_id,
        ad_ids=ad_ids[:10],
    )
    print(f"Sync stats: {stats}")

    # Check what's in the database
    db_result = supabase.table("meta_ad_destinations").select(
        "meta_ad_id, destination_url, canonical_url"
    ).eq(
        "brand_id", str(brand_id)
    ).limit(5).execute()

    print(f"\nStored in meta_ad_destinations: {len(db_result.data or [])} rows")
    for row in (db_result.data or [])[:3]:
        print(f"  {row['meta_ad_id']}: {row['canonical_url']}")

    # Test 3: Check brand_landing_pages
    print(f"\n{'='*60}")
    print("TEST 3: Brand Landing Pages")
    print(f"{'='*60}")

    lp_result = supabase.table("brand_landing_pages").select(
        "id, url, canonical_url"
    ).eq(
        "brand_id", str(brand_id)
    ).execute()

    print(f"Found {len(lp_result.data or [])} landing pages for {brand_name}")
    for lp in (lp_result.data or [])[:5]:
        print(f"  {lp['canonical_url'] or lp['url']}")

    # Test 4: Match destinations to landing pages
    print(f"\n{'='*60}")
    print("TEST 4: Match Destinations to Landing Pages")
    print(f"{'='*60}")

    match_result = await meta_service.match_destinations_to_landing_pages(brand_id)
    print(f"Total destinations: {match_result['total_destinations']}")
    print(f"Matched: {len(match_result['matches'])}")
    print(f"Unmatched: {match_result['unmatched_count']}")

    if match_result['matches']:
        print("\nSample matches:")
        for match in match_result['matches'][:3]:
            print(f"  Ad {match['meta_ad_id']}:")
            print(f"    Destination: {match['canonical_url']}")
            print(f"    LP ID: {match['landing_page_id']}")

    # Test 5: Populate landing_page_id in classifications
    print(f"\n{'='*60}")
    print("TEST 5: Populate landing_page_id in Classifications")
    print(f"{'='*60}")

    populate_stats = await meta_service.populate_classification_landing_page_ids(brand_id)
    print(f"Updated: {populate_stats['updated']}")
    print(f"Already set: {populate_stats['already_set']}")
    print(f"No match: {populate_stats['no_match']}")

    # Check classifications table
    class_result = supabase.table("ad_creative_classifications").select(
        "meta_ad_id, landing_page_id"
    ).eq(
        "brand_id", str(brand_id)
    ).not_.is_(
        "landing_page_id", "null"
    ).limit(5).execute()

    print(f"\nClassifications with landing_page_id: {len(class_result.data or [])}")
    for row in (class_result.data or [])[:3]:
        print(f"  Ad {row['meta_ad_id']}: LP {row['landing_page_id']}")

    # Test 6: Get unmatched URLs for backfill
    print(f"\n{'='*60}")
    print("TEST 6: Get Unmatched URLs for Backfill")
    print(f"{'='*60}")

    unmatched = await meta_service.get_unmatched_destination_urls(brand_id)
    print(f"Unmatched URLs needing scraping: {len(unmatched)}")
    for item in unmatched[:5]:
        print(f"  {item['canonical_url']}")

    # Test 7: Backfill unmatched landing pages (dry run - no scraping)
    print(f"\n{'='*60}")
    print("TEST 7: Backfill Unmatched Landing Pages (Dry Run)")
    print(f"{'='*60}")

    # First, show what would be created (scrape=False for dry run)
    backfill_result = await meta_service.backfill_unmatched_landing_pages(
        brand_id=brand_id,
        organization_id=org_id,
        scrape=False,  # Don't actually scrape in test
        limit=5,
    )
    print(f"Pending LP records created: {backfill_result['pending_created']}")
    print(f"Pages scraped: {backfill_result['pages_scraped']}")
    print(f"New matches: {backfill_result['new_matches']}")

    # Check pending records in brand_landing_pages
    pending_result = supabase.table("brand_landing_pages").select(
        "url, canonical_url, scrape_status"
    ).eq(
        "brand_id", str(brand_id)
    ).eq(
        "scrape_status", "pending"
    ).limit(5).execute()

    print(f"\nPending LP records in database: {len(pending_result.data or [])}")
    for row in (pending_result.data or [])[:3]:
        print(f"  {row['canonical_url']}")

    # Summary
    print(f"\n{'='*60}")
    print("SUMMARY")
    print(f"{'='*60}")
    print(f"✓ Destination URLs fetched: {len(destinations)}")
    print(f"✓ Stored in database: {stats['stored']}")
    print(f"✓ Matched to LPs: {len(match_result['matches'])}")
    print(f"✓ Classifications updated: {populate_stats['updated']}")
    print(f"✓ Unmatched (need LP scraping): {len(unmatched)}")


if __name__ == "__main__":
    asyncio.run(main())
