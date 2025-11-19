"""
Debug script to inspect Facebook Ads Apify actor output format
"""

import os
import json
import requests
from dotenv import load_dotenv

# Load environment variables
load_dotenv()

# Get API token
apify_token = os.getenv("APIFY_API_TOKEN")

# Use dataset from previous run
dataset_id = "8OfW7QLqpe88QAR28"
print(f"\nFetching dataset {dataset_id}...")

# Fetch dataset using requests
url = f"https://api.apify.com/v2/datasets/{dataset_id}/items"
headers = {"Authorization": f"Bearer {apify_token}"}

response = requests.get(url, headers=headers)
response.raise_for_status()

items = response.json()

print(f"Fetched {len(items)} items")

if items:
    print("\n" + "="*80)
    print("FIRST ITEM STRUCTURE:")
    print("="*80)
    print(json.dumps(items[0], indent=2, default=str))

    print("\n" + "="*80)
    print("ALL KEYS IN FIRST ITEM:")
    print("="*80)
    for key in sorted(items[0].keys()):
        print(f"  - {key}")
