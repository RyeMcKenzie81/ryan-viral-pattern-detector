#!/usr/bin/env python3
"""Test Clockworks actor with 100 search query results (not hashtag)"""
from apify_client import ApifyClient
from viraltracker.core.config import Config

client = ApifyClient(Config.APIFY_TOKEN)

print("Testing Clockworks actor with 100 search query results...")
print("Search term: 'dog health tips' (not a hashtag)")
print("=" * 70)

run_input = {
    "searchQueries": ["dog health tips"],
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
    print("\nFirst result:")
    first = items[0]
    print(f"  ID: {first.get('id')}")
    print(f"  Author: {first.get('authorMeta', {}).get('name')}")
    print(f"  Followers: {first.get('authorMeta', {}).get('fans')}")
    print(f"  Views: {first.get('playCount')}")
    print(f"  Likes: {first.get('diggCount')}")
    print(f"  Comments: {first.get('commentCount')}")
    print(f"  Shares: {first.get('shareCount')}")
    print(f"  Duration: {first.get('videoMeta', {}).get('duration')}s")
    print(f"  Created: {first.get('createTimeISO')}")
    print(f"  URL: {first.get('webVideoUrl')}")
    print(f"  Caption: {first.get('text', '')[:100]}...")
    
    # Check for critical fields
    print("\nField availability check:")
    critical_checks = {
        'id': lambda x: x.get('id'),
        'author_name': lambda x: x.get('authorMeta', {}).get('name'),
        'author_followers': lambda x: x.get('authorMeta', {}).get('fans'),
        'playCount': lambda x: x.get('playCount'),
        'diggCount': lambda x: x.get('diggCount'),
        'commentCount': lambda x: x.get('commentCount'),
        'shareCount': lambda x: x.get('shareCount'),
        'duration': lambda x: x.get('videoMeta', {}).get('duration'),
        'createTimeISO': lambda x: x.get('createTimeISO'),
        'webVideoUrl': lambda x: x.get('webVideoUrl'),
        'text': lambda x: x.get('text'),
    }
    
    for field, extractor in critical_checks.items():
        present_count = sum(1 for item in items if extractor(item) is not None)
        print(f"  {field}: {present_count}/{len(items)} ({present_count/len(items)*100:.1f}%)")
    
    # Check views distribution
    views = [item.get('playCount', 0) for item in items if item.get('playCount')]
    if views:
        print(f"\nViews distribution:")
        print(f"  Min: {min(views):,}")
        print(f"  Max: {max(views):,}")
        print(f"  Mean: {sum(views)/len(views):,.0f}")
        print(f"  Median: {sorted(views)[len(views)//2]:,}")
    
    # Check follower distribution
    followers = [item.get('authorMeta', {}).get('fans', 0) for item in items if item.get('authorMeta', {}).get('fans')]
    if followers:
        print(f"\nFollower distribution:")
        print(f"  Min: {min(followers):,}")
        print(f"  Max: {max(followers):,}")
        print(f"  Mean: {sum(followers)/len(followers):,.0f}")
        print(f"  Median: {sorted(followers)[len(followers)//2]:,}")
else:
    print("❌ No results returned!")

print("\n" + "=" * 70)
print("✅ Test complete!")
