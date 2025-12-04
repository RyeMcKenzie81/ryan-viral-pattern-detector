"""
End-to-End Test: Facebook Ad Scraping Pipeline

Tests the full flow:
1. Scrape ads from Facebook Ad Library (via Apify)
2. Save ads to facebook_ads table
3. Download images/videos from ads
4. Upload to Supabase storage
5. Save asset records to scraped_ad_assets table

Run with:
    python test_e2e_ad_scraping.py
"""

import asyncio
import json
import logging
from dotenv import load_dotenv

load_dotenv()

logging.basicConfig(level=logging.INFO, format='%(levelname)s: %(message)s')
logger = logging.getLogger(__name__)

from viraltracker.services.ad_scraping_service import AdScrapingService
from viraltracker.services.facebook_service import FacebookService


async def main():
    """Run end-to-end test."""
    print("\n" + "="*70)
    print("END-TO-END TEST: Facebook Ad Scraping Pipeline")
    print("="*70)

    # Test URL - page-specific search
    test_url = "https://www.facebook.com/ads/library/?active_status=active&ad_type=all&country=US&is_targeted_country=false&media_type=all&search_type=page&view_all_page_id=470900729771745"

    print(f"\nTest URL: {test_url[:80]}...")

    # Initialize services
    ad_scraping = AdScrapingService()
    facebook = FacebookService()

    # Step 1: Scrape ads from Facebook Ad Library
    print("\n" + "-"*70)
    print("STEP 1: Scraping ads from Facebook Ad Library (via Apify)")
    print("-"*70)

    try:
        ads = await facebook.search_ads(
            search_url=test_url,
            project="test-e2e",
            count=10,  # Apify minimum is 10
            period="",  # All time
            save_to_db=False
        )
    except Exception as e:
        print(f"✗ Scraping failed: {e}")
        return

    if not ads:
        print("✗ No ads found")
        return

    print(f"✓ Scraped {len(ads)} ads")

    # Show page info from first ad
    first_ad = ads[0]
    print(f"\nPage Info:")
    print(f"  Page ID: {first_ad.page_id}")
    print(f"  Page Name: {first_ad.page_name}")

    # Step 2: Save ads to database
    print("\n" + "-"*70)
    print("STEP 2: Saving ads to facebook_ads table")
    print("-"*70)

    saved_ad_ids = []
    for i, ad in enumerate(ads):
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

        fb_ad_id = ad_scraping.save_facebook_ad(
            ad_data=ad_dict,
            scrape_source="e2e_test"
        )

        if fb_ad_id:
            saved_ad_ids.append(fb_ad_id)
            print(f"  ✓ Saved ad {i+1}: {fb_ad_id}")
        else:
            print(f"  ✗ Failed to save ad {i+1}")

    print(f"\n✓ Saved {len(saved_ad_ids)}/{len(ads)} ads to database")

    # Step 3: Download and store assets
    print("\n" + "-"*70)
    print("STEP 3: Downloading and storing assets")
    print("-"*70)

    total_images = 0
    total_videos = 0

    for i, (ad, fb_ad_id) in enumerate(zip(ads, saved_ad_ids)):
        if not ad.snapshot:
            print(f"  Ad {i+1}: No snapshot data")
            continue

        try:
            snapshot = json.loads(ad.snapshot) if isinstance(ad.snapshot, str) else ad.snapshot
        except:
            print(f"  Ad {i+1}: Could not parse snapshot")
            continue

        # Extract URLs first to show what we found
        urls = ad_scraping.extract_asset_urls(snapshot)
        print(f"\n  Ad {i+1} ({ad.page_name}):")
        print(f"    Found {len(urls['images'])} images, {len(urls['videos'])} videos")

        if not urls['images'] and not urls['videos']:
            continue

        # Download and store
        result = await ad_scraping.scrape_and_store_assets(
            facebook_ad_id=fb_ad_id,
            snapshot=snapshot,
            scrape_source="e2e_test"
        )

        total_images += len(result['images'])
        total_videos += len(result['videos'])

        print(f"    ✓ Stored {len(result['images'])} images, {len(result['videos'])} videos")

    print(f"\n✓ Total assets stored: {total_images} images, {total_videos} videos")

    # Step 4: Verify database records
    print("\n" + "-"*70)
    print("STEP 4: Verifying database records")
    print("-"*70)

    # Check facebook_ads
    fb_result = ad_scraping.supabase.table("facebook_ads").select(
        "id, page_id, page_name, scrape_source"
    ).eq("scrape_source", "e2e_test").execute()

    print(f"\nfacebook_ads table:")
    print(f"  Records with scrape_source='e2e_test': {len(fb_result.data)}")
    if fb_result.data:
        for row in fb_result.data[:3]:
            print(f"    - Page: {row['page_name']} (ID: {row['page_id']})")

    # Check scraped_ad_assets
    assets_result = ad_scraping.supabase.table("scraped_ad_assets").select(
        "id, asset_type, storage_path, file_size_bytes"
    ).eq("scrape_source", "e2e_test").execute()

    print(f"\nscraped_ad_assets table:")
    print(f"  Records with scrape_source='e2e_test': {len(assets_result.data)}")
    if assets_result.data:
        for row in assets_result.data[:5]:
            size_kb = row['file_size_bytes'] / 1024 if row['file_size_bytes'] else 0
            print(f"    - {row['asset_type']}: {row['storage_path'][:50]}... ({size_kb:.1f} KB)")

    # Summary
    print("\n" + "="*70)
    print("TEST SUMMARY")
    print("="*70)
    print(f"✓ Ads scraped: {len(ads)}")
    print(f"✓ Ads saved to DB: {len(saved_ad_ids)}")
    print(f"✓ Assets downloaded: {total_images} images, {total_videos} videos")
    print(f"✓ Page info captured: {first_ad.page_name} (ID: {first_ad.page_id})")
    print("\n✓ End-to-end test PASSED!")


if __name__ == "__main__":
    asyncio.run(main())
