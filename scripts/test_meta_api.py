#!/usr/bin/env python3
"""
Quick test script for Meta Ads API connection.

Usage:
    python scripts/test_meta_api.py

Requires:
    - META_GRAPH_API_TOKEN env var (or pass as argument)
    - META_AD_ACCOUNT_ID env var (or pass as argument)
    - pip install facebook-business
"""

import os
import sys
import asyncio

# Add project root to path
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


async def test_connection():
    """Test basic Meta API connection."""
    from viraltracker.services.meta_ads_service import MetaAdsService

    # Check env vars
    token = os.getenv('META_GRAPH_API_TOKEN')
    ad_account_id = os.getenv('META_AD_ACCOUNT_ID')

    if not token:
        print("❌ META_GRAPH_API_TOKEN not set")
        print("   Get one from: https://developers.facebook.com/tools/explorer/")
        print("   Then: export META_GRAPH_API_TOKEN='your_token'")
        return False

    if not ad_account_id:
        print("❌ META_AD_ACCOUNT_ID not set")
        print("   Format: act_123456789")
        print("   Then: export META_AD_ACCOUNT_ID='act_123456789'")
        return False

    print(f"✓ Token found (length: {len(token)})")
    print(f"✓ Ad Account ID: {ad_account_id}")

    # Initialize service
    print("\n--- Initializing MetaAdsService ---")
    service = MetaAdsService(access_token=token, ad_account_id=ad_account_id)

    # Test API connection
    print("\n--- Testing API Connection (last 7 days) ---")
    try:
        insights = await service.get_ad_insights(
            ad_account_id=ad_account_id,
            days_back=7,
            level="ad"
        )

        print(f"✓ API call successful!")
        print(f"  Found {len(insights)} ad insights")

        if insights:
            # Find an ad with actual metrics (link_clicks or purchases)
            sample = insights[0]
            for insight in insights:
                if insight.get('link_clicks') or insight.get('purchases'):
                    sample = insight
                    break

            print("\n--- Sample Data (ad with metrics if available) ---")
            print(f"  Ad ID: {sample.get('meta_ad_id', 'N/A')}")
            print(f"  Ad Name: {sample.get('ad_name', 'N/A')}")
            print(f"  Spend: ${sample.get('spend', 0)}")
            print(f"  Impressions: {sample.get('impressions', 0)}")

            # Show raw fields available
            print("\n--- Raw API Fields ---")
            print(f"  Available keys: {list(sample.keys())}")
            # Show actual values for key metrics
            print(f"  Raw link_clicks value: {sample.get('link_clicks')}")
            print(f"  Raw roas value: {sample.get('roas')}")
            print(f"  Raw raw_actions: {sample.get('raw_actions')}")

            # Show normalized metrics (already normalized by get_ad_insights)
            print("\n--- Normalized Metrics (from get_ad_insights) ---")
            print(f"  Link clicks: {sample.get('link_clicks', 'N/A')}")
            print(f"  Link CTR: {sample.get('link_ctr', 'N/A')}")
            print(f"  Add to carts: {sample.get('add_to_carts', 'N/A')}")
            print(f"  Purchases: {sample.get('purchases', 'N/A')}")
            print(f"  ROAS: {sample.get('roas', 'N/A')}")
            print(f"  Conversion rate: {sample.get('conversion_rate', 'N/A')}")

            # Test ID extraction
            ad_name = sample.get('ad_name', '')
            print(f"\n--- Testing find_matching_generated_ad_id() ---")
            print(f"  Ad name: '{ad_name}'")
            match = service.find_matching_generated_ad_id(ad_name)
            if match:
                print(f"  ✓ Found ID pattern: {match}")
            else:
                print(f"  No 8-char ID found (expected for non-ViralTracker ads)")
        else:
            print("\n  No ads found in last 7 days. Try a longer date range.")

        return True

    except Exception as e:
        print(f"❌ API Error: {e}")

        # Common error hints
        error_str = str(e).lower()
        if "invalid oauth" in error_str or "token" in error_str:
            print("\n   Hint: Your token may be expired. Get a new one from Graph API Explorer.")
        elif "permission" in error_str:
            print("\n   Hint: Token needs 'ads_read' permission.")
        elif "account" in error_str:
            print("\n   Hint: Check ad account ID format (should be act_123456789)")

        return False


async def test_rate_limiting():
    """Test that rate limiting is working."""
    from viraltracker.services.meta_ads_service import MetaAdsService

    print("\n--- Testing Rate Limiter ---")
    service = MetaAdsService()

    # Check rate limiter state
    print(f"  Requests per minute limit: {service._requests_per_minute}")
    print(f"  Min delay between calls: {service._min_delay:.2f}s")
    print("  ✓ Rate limiter initialized")


if __name__ == "__main__":
    print("=" * 50)
    print("Meta Ads API Connection Test")
    print("=" * 50)

    asyncio.run(test_connection())
    asyncio.run(test_rate_limiting())

    print("\n" + "=" * 50)
    print("Test complete!")
    print("=" * 50)
