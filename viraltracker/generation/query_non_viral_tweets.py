"""
Query non-viral tweets with matched follower counts for comparison analysis.

This script finds average-performing tweets (z-score between -0.5 and 0.5)
with follower count distributions matching the viral tweets,
allowing for proper controlled comparisons.
"""

import json
import sys
from datetime import datetime
from typing import List, Dict, Any
import numpy as np

from viraltracker.generation.outlier_detector import OutlierDetector


def load_viral_outliers(outliers_path: str) -> List[Dict]:
    """Load viral outliers from JSON file."""
    with open(outliers_path, 'r') as f:
        data = json.load(f)
    return data['outliers']


def get_follower_ranges(outliers: List[Dict], num_bins: int = 5) -> List[tuple]:
    """
    Determine follower count ranges from viral tweets.

    Returns list of (min_followers, max_followers, target_count) tuples.
    """
    follower_counts = [o['author_followers'] for o in outliers]

    # Create bins based on percentiles
    percentiles = np.linspace(0, 100, num_bins + 1)
    bin_edges = np.percentile(follower_counts, percentiles)

    ranges = []
    for i in range(len(bin_edges) - 1):
        min_followers = int(bin_edges[i])
        max_followers = int(bin_edges[i + 1])
        # Count how many viral tweets in this range
        count_in_range = sum(1 for fc in follower_counts
                            if min_followers <= fc <= max_followers)
        ranges.append((min_followers, max_followers, count_in_range))

    return ranges


def export_to_json(tweets_data: List[Dict], output_path: str, project_slug: str):
    """Export tweets to JSON in same format as outliers.json."""

    # Sort by z-score (ascending for non-viral, showing closest to baseline first)
    tweets_sorted = sorted(tweets_data, key=lambda t: abs(t['z_score']))

    outliers_data = []
    for rank, tweet in enumerate(tweets_sorted, 1):
        outlier_entry = {
            'rank': rank,
            'tweet_id': tweet['id'],
            'text': tweet['text'],
            'url': tweet['url'],
            'author': tweet['author'],
            'author_followers': tweet['author_followers'],
            'created_at': tweet['created_at'],
            'metrics': {
                'views': tweet['views'],
                'likes': tweet['likes'],
                'replies': tweet['replies'],
                'reposts': tweet['reposts'],
                'bookmarks': tweet.get('bookmarks', 0),
                'engagement_rate': round(tweet['engagement_rate'], 4)
            },
            'outlier_metrics': {
                'z_score': round(tweet['z_score'], 2),
                'percentile': 50.0  # By definition, around median
            }
        }
        outliers_data.append(outlier_entry)

    output = {
        'project': project_slug,
        'generated_at': datetime.utcnow().isoformat() + 'Z',
        'total_outliers': len(outliers_data),
        'z_score_range': {
            'min': round(min(t['z_score'] for t in tweets_data), 2),
            'max': round(max(t['z_score'] for t in tweets_data), 2)
        },
        'outliers': outliers_data
    }

    with open(output_path, 'w') as f:
        json.dump(output, f, indent=2)

    print(f"\n✓ Exported {len(outliers_data)} non-viral tweets to {output_path}")


def main():
    if len(sys.argv) < 3:
        print("Usage: python query_non_viral_tweets.py <outliers.json> <output.json>")
        print("\nExample:")
        print("  python query_non_viral_tweets.py ~/Downloads/outliers.json ~/Downloads/non_viral_tweets.json")
        sys.exit(1)

    outliers_path = sys.argv[1]
    output_path = sys.argv[2]

    print(f"\n{'='*80}")
    print("NON-VIRAL TWEET QUERY - Control Group Selection")
    print(f"{'='*80}\n")

    # Load viral outliers
    print("Loading viral outliers...")
    viral_outliers = load_viral_outliers(outliers_path)
    print(f"✓ Loaded {len(viral_outliers)} viral tweets (z-score >= 2.0)")

    # Analyze follower distribution (use ALL viral outliers)
    print("\nAnalyzing follower distribution...")
    num_outliers = len(viral_outliers)
    follower_ranges = get_follower_ranges(viral_outliers, num_bins=5)

    # Adjust target counts based on actual sample size
    total_target = num_outliers
    follower_ranges = [(min_f, max_f, int(count * total_target / 100))
                       for min_f, max_f, count in follower_ranges]
    print("✓ Follower ranges:")
    for min_f, max_f, count in follower_ranges:
        print(f"  {min_f:,} - {max_f:,} followers: {count} tweets")

    # Use outlier detector to get ALL tweets (not just outliers)
    print("\nQuerying all tweets from last 60 days...")
    detector = OutlierDetector(project_slug='yakety-pack-instagram')

    # Get all tweets using percentile method with very low threshold
    # This will give us ALL tweets sorted by engagement
    all_results = detector.find_outliers(
        days_back=60,
        min_views=100,
        min_likes=0,
        method="percentile",
        threshold=100.0,  # Top 100% = all tweets
        text_only=True
    )

    print(f"✓ Found {len(all_results)} total tweets")

    # Extract z-scores and other metrics
    all_tweets_with_z = []
    for result in all_results:
        tweet = result.tweet
        all_tweets_with_z.append({
            'id': tweet.tweet_id,
            'text': tweet.text,
            'url': f"https://twitter.com/{tweet.author_handle}/status/{tweet.tweet_id}",
            'author': tweet.author_handle,
            'author_followers': tweet.author_followers,
            'created_at': tweet.posted_at.isoformat(),
            'views': tweet.views,
            'likes': tweet.likes,
            'replies': tweet.replies,
            'reposts': tweet.retweets,
            'engagement_rate': tweet.engagement_rate,
            'z_score': result.z_score
        })

    # Filter to non-viral range (-0.5 to 0.5)
    non_viral = [t for t in all_tweets_with_z
                 if -0.5 <= t['z_score'] <= 0.5]

    print(f"Found {len(non_viral)} tweets with z-score between -0.5 and 0.5")

    if len(non_viral) < 50:
        print(f"\n⚠️  Warning: Only found {len(non_viral)} non-viral tweets")
        print("    Using all available tweets in this range")
        sampled_tweets = non_viral
    else:
        # Sample from each follower range to match viral distribution
        sampled_tweets = []

        for min_followers, max_followers, target_count in follower_ranges:
            # Get tweets in this follower range
            candidates = [t for t in non_viral
                         if min_followers <= t['author_followers'] <= max_followers]

            print(f"  Follower range {min_followers:,}-{max_followers:,}: "
                  f"{len(candidates)} candidates, target {target_count}")

            # Sample randomly
            if len(candidates) >= target_count:
                selected = list(np.random.choice(candidates, target_count, replace=False))
            else:
                selected = candidates

            sampled_tweets.extend(selected)

        print(f"\nTotal sampled: {len(sampled_tweets)} non-viral tweets")

    # Export
    export_to_json(sampled_tweets, output_path, 'yakety-pack-instagram')

    # Summary stats
    print(f"\n{'='*80}")
    print("SUMMARY")
    print(f"{'='*80}")
    print(f"Viral tweets:     {len(viral_outliers)} (z >= 2.0)")
    print(f"Non-viral tweets: {len(sampled_tweets)} (-0.5 <= z <= 0.5)")
    print(f"\nFollower count distribution:")
    viral_followers = [o['author_followers'] for o in viral_outliers[:100]]
    nonviral_followers = [t['author_followers'] for t in sampled_tweets]
    print(f"  Viral median:     {int(np.median(viral_followers)):,}")
    print(f"  Non-viral median: {int(np.median(nonviral_followers)):,}")
    print(f"\nZ-score range:")
    z_scores = [t['z_score'] for t in sampled_tweets]
    print(f"  Min: {min(z_scores):.2f}")
    print(f"  Max: {max(z_scores):.2f}")
    print(f"  Mean: {np.mean(z_scores):.2f}")


if __name__ == "__main__":
    main()
