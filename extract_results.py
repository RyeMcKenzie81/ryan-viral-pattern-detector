#!/usr/bin/env python3
"""Extract and analyze results from all search term analysis files."""

import json
from pathlib import Path
from typing import List, Dict

def extract_metrics(file_path: Path) -> Dict:
    """Extract key metrics from a single analysis file."""
    with open(file_path) as f:
        data = json.load(f)

    metrics = data['metrics']
    score_dist = metrics['score_distribution']

    # Get top topic from topic_distribution dict
    topic_dist = metrics['topic_distribution']
    if topic_dist:
        top_topic_name = max(topic_dist, key=topic_dist.get)
        top_topic = {
            'topic': top_topic_name,
            'count': topic_dist[top_topic_name],
            'percentage': (topic_dist[top_topic_name] / data['tweets_analyzed']) * 100
        }
    else:
        top_topic = None

    # Handle both old and new format for relevance scores
    if 'relevance_only_distribution' in metrics:
        # New format from analyze_from_apify_runs.py
        relevance_dist = metrics['relevance_only_distribution']
        relevance_green_pct = relevance_dist['green']['percentage']
        relevance_yellow_pct = relevance_dist['yellow']['percentage']
        yellow_avg_similarity = relevance_dist['yellow']['avg_similarity']
    else:
        # Old format with relevance_only scores
        relevance_green_pct = None
        relevance_yellow_pct = None
        yellow_avg_similarity = metrics.get('relevance_only', {}).get('yellow_avg_relevance', 0)

    # Extract component scores if available
    component_scores = metrics.get('component_scores', {})

    return {
        'term': data['search_term'],
        'tweets': data['tweets_analyzed'],
        'green_count': score_dist['green']['count'],
        'green_pct': score_dist['green']['percentage'],
        'yellow_count': score_dist['yellow']['count'],
        'yellow_pct': score_dist['yellow']['percentage'],
        'red_count': score_dist['red']['count'],
        'red_pct': score_dist['red']['percentage'],
        'green_avg': score_dist['green']['avg_score'],
        'yellow_avg': score_dist['yellow']['avg_score'],
        'freshness_48h_pct': metrics['freshness']['last_48h_percentage'],
        'conversations_per_day': metrics['freshness']['conversations_per_day'],
        'tweets_per_24h': metrics['freshness']['tweets_per_24h'],
        'relevance_green_pct': relevance_green_pct,
        'relevance_yellow_pct': relevance_yellow_pct,
        'yellow_avg_similarity': yellow_avg_similarity,
        'component_scores': component_scores,
        'top_topic': top_topic,
        'total_cost': metrics['cost_efficiency']['total_cost_usd'],
        'rating': data['recommendation']['rating'],
        'reasoning': data['recommendation']['reasoning']
    }

def main():
    # Find all analysis files
    analysis_dir = Path.home() / 'Downloads' / 'term_analysis_corrected'
    files = sorted(analysis_dir.glob('*_analysis.json'))

    print(f"Found {len(files)} analysis files\n")

    # Extract metrics from all files
    results = []
    for file_path in files:
        try:
            metrics = extract_metrics(file_path)
            results.append(metrics)
        except Exception as e:
            print(f"Error processing {file_path.name}: {e}")

    # Sort by green percentage (descending)
    results.sort(key=lambda x: x['green_pct'], reverse=True)

    # Print summary table with composite vs relevance-only comparison
    print("=" * 150)
    print(f"{'SEARCH TERM':<25} {'TWEETS':>7} {'T/24H':>7} | {'COMPOSITE':^20} | {'RELEVANCE-ONLY':^20} | {'RATING':<12}")
    print(f"{'':25} {'':7} {'':7} | {'Green %':^20} | {'Green %':^20} | {'':12}")
    print("=" * 150)

    for r in results:
        composite_green = f"{r['green_pct']:.1f}%"
        relevance_green = f"{r['relevance_green_pct']:.1f}%" if r['relevance_green_pct'] is not None else "N/A"

        print(f"{r['term']:<25} {r['tweets']:>7} {r['tweets_per_24h']:>7.1f} | "
              f"{composite_green:^20} | {relevance_green:^20} | {r['rating']:<12}")

    print("=" * 120)
    print()

    # Print detailed analysis
    print("DETAILED RESULTS")
    print("=" * 120)
    print()

    for i, r in enumerate(results, 1):
        print(f"{i}. {r['term']}")
        print(f"   Tweets: {r['tweets']:,} | Rating: {r['rating']}")
        print(f"   Volume: {r['tweets_per_24h']:.1f} tweets/24h | Freshness: {r['freshness_48h_pct']:.1f}% in 48h")
        print(f"   ")
        print(f"   COMPOSITE SCORING (all factors):")
        print(f"     Green: {r['green_count']} ({r['green_pct']:.1f}%) | Yellow: {r['yellow_count']} ({r['yellow_pct']:.1f}%) | Red: {r['red_count']} ({r['red_pct']:.1f}%)")
        print(f"     Yellow avg score: {r['yellow_avg']:.3f}")

        # Show component breakdown for yellow tweets
        if r['component_scores'] and 'yellow' in r['component_scores']:
            yellow_comp = r['component_scores']['yellow']
            print(f"     Yellow component breakdown:")
            print(f"       Velocity: {yellow_comp['velocity']:.3f} | Relevance: {yellow_comp['relevance']:.3f} | Openness: {yellow_comp['openness']:.3f} | Author: {yellow_comp['author_quality']:.3f}")

        if r['relevance_green_pct'] is not None:
            print(f"   ")
            print(f"   RELEVANCE-ONLY SCORING (semantic similarity):")
            print(f"     Green: {r['relevance_green_pct']:.1f}% | Yellow: {r['relevance_yellow_pct']:.1f}%")
            print(f"     Yellow avg similarity: {r['yellow_avg_similarity']:.3f}")
        if r['top_topic']:
            print(f"   ")
            print(f"   Top Topic: {r['top_topic']['topic']} ({r['top_topic']['percentage']:.1f}%)")
        print(f"   → {r['reasoning']}")
        print()

    # Calculate summary statistics
    total_tweets = sum(r['tweets'] for r in results)
    total_green = sum(r['green_count'] for r in results)
    avg_green_pct = sum(r['green_pct'] for r in results) / len(results)
    total_cost = sum(r['total_cost'] for r in results)

    print("=" * 120)
    print("SUMMARY STATISTICS")
    print("=" * 120)
    print(f"Total terms tested: {len(results)}")
    print(f"Total tweets analyzed: {total_tweets:,}")
    print(f"Total green tweets: {total_green:,} ({total_green/total_tweets*100:.2f}% overall)")
    print(f"Average green percentage: {avg_green_pct:.2f}%")
    print(f"Total cost: ${total_cost:.2f}")
    print()

    # Rating breakdown
    ratings = {}
    for r in results:
        ratings[r['rating']] = ratings.get(r['rating'], 0) + 1

    print("Rating Distribution:")
    for rating, count in sorted(ratings.items()):
        print(f"  {rating}: {count} terms")
    print()

    # Top recommendations
    excellent_good = [r for r in results if r['rating'] in ['Excellent', 'Good']]
    okay = [r for r in results if r['rating'] == 'Okay']

    print("=" * 120)
    print("RECOMMENDATIONS")
    print("=" * 120)
    if excellent_good:
        print(f"✅ Found {len(excellent_good)} term(s) rated 'Good' or 'Excellent':")
        for r in excellent_good:
            print(f"   - {r['term']}: {r['green_pct']:.1f}% green ({r['green_count']} tweets)")
    else:
        print("❌ No terms rated 'Good' or 'Excellent'")

    print()

    if okay:
        print(f"⚠️  Found {len(okay)} term(s) rated 'Okay':")
        for r in okay:
            print(f"   - {r['term']}: {r['green_pct']:.1f}% green ({r['green_count']} tweets)")

    print()
    print("=" * 120)

if __name__ == '__main__':
    main()
