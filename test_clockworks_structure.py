#!/usr/bin/env python3
"""Inspect Clockworks output structure in detail"""
from apify_client import ApifyClient
from viraltracker.core.config import Config
import json

client = ApifyClient(Config.APIFY_TOKEN)

run_input = {
    "hashtags": ["dogs"],
    "resultsPerPage": 1,
    "shouldDownloadVideos": False,
}

run = client.actor("clockworks/tiktok-scraper").call(run_input=run_input)

for item in client.dataset(run["defaultDatasetId"]).iterate_items():
    print("Full item structure:")
    print(json.dumps(item, indent=2, default=str))
    
    print("\n" + "="*70)
    print("authorMeta structure:")
    print(json.dumps(item.get('authorMeta'), indent=2, default=str))
    
    print("\n" + "="*70)
    print("videoMeta structure:")
    print(json.dumps(item.get('videoMeta'), indent=2, default=str))
    break
