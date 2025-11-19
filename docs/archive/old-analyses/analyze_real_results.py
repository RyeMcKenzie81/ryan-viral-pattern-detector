#!/usr/bin/env python3
"""Analyze the actual batch test results based on Apify scrapes."""

import json
from datetime import datetime
from pathlib import Path

# Map Apify results to search terms based on timestamps from the screenshot
# Batch started at 13:27, terms run in this order with 2-min gaps
apify_results = [
    # From the screenshot (most recent first, so reversed)
    {"term": "mindful parenting", "tweets": 1000, "time": "14:15:53", "duration_sec": 100},
    {"term": "kids technology", "tweets": 1000, "time": "14:09:53", "duration_sec": 90},
    {"term": "tech boundaries", "tweets": 165, "time": "13:45:48", "duration_sec": 20},
    {"term": "online safety kids", "tweets": 121, "time": "13:48:57", "duration_sec": 19},
    {"term": "kids social media", "tweets": 21, "time": "13:51:54", "duration_sec": 7},
    {"term": "digital parenting", "tweets": 76, "time": "13:54:29", "duration_sec": 15},
    {"term": "family routines", "tweets": 90, "time": "13:57:19", "duration_sec": 12},
    {"term": "screen time rules", "tweets": 149, "time": "14:06:49", "duration_sec": 17},
    {"term": "device limits", "tweets": 31, "time": "14:21:19", "duration_sec": 7},
    # These 3 got 1000 each, need to figure out which terms
    {"term": "parenting tips", "tweets": 1000, "time": "~13:32", "duration_sec": 100},
    {"term": "digital wellness", "tweets": 1000, "time": "~13:37", "duration_sec": 100},
    # Remaining terms with unknown counts (likely low)
    {"term": "screen time kids", "tweets": "?", "time": "13:27"},
    {"term": "kids screen time", "tweets": "?", "time": "~13:42"},
    {"term": "parenting advice", "tweets": "?", "time": "~13:47"},
    {"term": "toddler behavior", "tweets": "?", "time": "~13:52"},
]

# All 15 terms in order
all_terms = [
    "screen time kids",
    "parenting tips",
    "digital wellness",
    "kids screen time",
    "parenting advice",
    "toddler behavior",
    "device limits",
    "screen time rules",
    "family routines",
    "digital parenting",
    "kids social media",
    "online safety kids",
    "tech boundaries",
    "kids technology",
    "mindful parenting"
]

print("=" * 100)
print("ACTUAL APIFY SCRAPE RESULTS")
print("=" * 100)
print()
print(f"{'Search Term':<25} {'Tweets Found':>15} {'Expected':>10} {'Match?':>8} {'Daily Est.':>12}")
print("-" * 100)

for term in all_terms:
    # Find in apify results
    result = next((r for r in apify_results if r['term'] == term), None)

    if result and result['tweets'] != '?':
        tweets = result['tweets']
        expected = 1000
        match = "✓" if tweets == expected else "✗"
        # Daily estimate: tweets found in 7 days / 7
        daily_est = tweets / 7.0
        print(f"{term:<25} {tweets:>15,} {expected:>10,} {match:>8} {daily_est:>11.1f}/day")
    else:
        print(f"{term:<25} {'Unknown':>15} {1000:>10,} {'?':>8} {'?':>12}")

print("-" * 100)
print()

# Calculate totals
known_results = [r for r in apify_results if r['tweets'] != '?']
total_scraped = sum(r['tweets'] for r in known_results)
avg_per_term = total_scraped / len(known_results)

print(f"Known scrapes: {len(known_results)}/15 terms")
print(f"Total tweets scraped: {total_scraped:,}")
print(f"Average per term: {avg_per_term:.0f} tweets")
print(f"Terms that hit 1000: {sum(1 for r in known_results if r['tweets'] == 1000)}/15")
print(f"Terms under 200: {sum(1 for r in known_results if r['tweets'] < 200)}/15")
print()

print("=" * 100)
print("VOLUME ANALYSIS")
print("=" * 100)
print()

# Group by volume tier
high = [r for r in known_results if r['tweets'] >= 800]
medium = [r for r in known_results if 200 <= r['tweets'] < 800]
low = [r for r in known_results if r['tweets'] < 200]

print(f"High volume (≥800 tweets/week):  {len(high)} terms")
for r in high:
    print(f"  - {r['term']}: {r['tweets']:,} tweets (~{r['tweets']/7:.0f}/day)")

print()
print(f"Medium volume (200-799/week):    {len(medium)} terms")
for r in medium:
    print(f"  - {r['term']}: {r['tweets']:,} tweets (~{r['tweets']/7:.0f}/day)")

print()
print(f"Low volume (<200 tweets/week):   {len(low)} terms")
for r in low:
    print(f"  - {r['term']}: {r['tweets']:,} tweets (~{r['tweets']/7:.0f}/day)")

print()
print("=" * 100)
print("KEY FINDINGS")
print("=" * 100)
print()
print("1. Only 3-4 terms found enough tweets to meet the 1000 target")
print("2. Many terms have very low volume (21-165 tweets in 7 days = 3-24 tweets/day)")
print("3. The analyzer was re-using the same 1000 tweets across all analyses")
print("4. This invalidates all the metrics in the original report")
print()
print("RECOMMENDATION:")
print("- Focus on the 3 high-volume terms for future testing")
print("- Lower the target count from 1000 to 100-200 for low-volume terms")
print("- Fix the analyzer bug to use search-term-specific tweets")
print()
