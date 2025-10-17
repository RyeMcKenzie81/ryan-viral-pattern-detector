#!/usr/bin/env python3
"""Test Clockworks actor with 100 hashtag results"""
from apify_client import ApifyClient
from viraltracker.core.config import Config

client = ApifyClient(Config.APIFY_TOKEN)

print("Testing Clockworks actor with 100 hashtag results (#doghealth)...")
print("=" * 70)

run_input = {
    "hashtags": ["doghealth"],
    "resultsPerPage": 100,
    "shouldDownloadVideos": False,
    "shouldDownloadCovers": False,
    "shouldDownloadSubtitles": False,
}

run = client.actor("clockworks/tiktok-scraper").call(run_input=run_input)

# Get results
items = []
for item in client.dataset(run["defaultDatasetId"]).iterate_items():
    items.append(item)

print(f"\nTotal results returned: {len(items)}")

if items:
    print("\nFirst result structure:")
    first = items[0]
    print(f"Keys: {sorted(first.keys())}")
    
    print("\nSample result:")
    print(f"  ID: {first.get('id')}")
    print(f"  Author: {first.get('authorMeta.name')}")
    print(f"  Views: {first.get('playCount')}")
    print(f"  Likes: {first.get('diggCount')}")
    print(f"  Comments: {first.get('commentCount')}")
    print(f"  Shares: {first.get('shareCount')}")
    print(f"  Duration: {first.get('videoMeta.duration')}s")
    print(f"  Created: {first.get('createTimeISO')}")
    print(f"  URL: {first.get('webVideoUrl')}")
    print(f"  Caption: {first.get('text', '')[:100]}...")
    
    # Check for critical fields
    print("\nField availability check:")
    critical_fields = ['id', 'authorMeta.name', 'playCount', 'diggCount', 'commentCount', 
                      'shareCount', 'videoMeta.duration', 'createTimeISO', 'webVideoUrl', 'text']
    
    for field in critical_fields:
        present_count = sum(1 for item in items if item.get(field) is not None)
        print(f"  {field}: {present_count}/{len(items)} ({present_count/len(items)*100:.1f}%)")
    
    # Check views distribution
    views = [item.get('playCount', 0) for item in items if item.get('playCount')]
    if views:
        print(f"\nViews distribution:")
        print(f"  Min: {min(views):,}")
        print(f"  Max: {max(views):,}")
        print(f"  Mean: {sum(views)/len(views):,.0f}")
        print(f"  Median: {sorted(views)[len(views)//2]:,}")
else:
    print("❌ No results returned!")

print("\n" + "=" * 70)
print("✅ Test complete!")
