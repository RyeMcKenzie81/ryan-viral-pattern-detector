#!/usr/bin/env python3
"""
Re-analyze existing keyword analysis runs with the new 0.50 green threshold.
This will show which keywords perform best with the updated threshold.
"""
from collections import defaultdict
from viraltracker.core.database import get_supabase_client
from viraltracker.core.config import load_finder_config
from viraltracker.core.embeddings import Embedder, load_taxonomy_embeddings_incremental
from viraltracker.generation.comment_finder import score_tweet, TweetMetrics
from apify_client import ApifyClient
import os
from datetime import datetime
from dotenv import load_dotenv

# Load environment variables
load_dotenv()

def main():
    print("🔄 Re-analyzing keywords with 0.50 green threshold...")
    print("=" * 80)
    print()

    # Load config with new threshold
    config = load_finder_config('yakety-pack-instagram')
    print(f"Green threshold: {config.thresholds['green_min']}")
    print(f"Yellow threshold: {config.thresholds['yellow_min']}")
    print()

    # Initialize embedder and taxonomy
    embedder = Embedder()
    taxonomy_embeddings = load_taxonomy_embeddings_incremental(
        'yakety-pack-instagram',
        config.taxonomy,
        embedder
    )

    # Get database connection
    db = get_supabase_client()

    # Get all completed analysis runs
    runs_result = db.table('analysis_runs')\
        .select('id, search_term, apify_dataset_id, tweets_analyzed')\
        .eq('project_id', '8fe8c0bc-e294-486c-8502-c0ade86de5a5')\
        .eq('status', 'completed')\
        .execute()

    print(f"Found {len(runs_result.data)} completed analysis runs")
    print()

    # Initialize Apify client
    apify_token = os.getenv('APIFY_TOKEN')
    if not apify_token:
        print("❌ Error: APIFY_TOKEN not set")
        return

    apify = ApifyClient(apify_token)

    # Aggregate by search term
    term_stats = defaultdict(lambda: {
        'tweets': [],
        'datasets': [],
        'total_tweets': 0
    })

    # Collect all datasets by search term
    for run in runs_result.data:
        term = run['search_term']
        dataset_id = run['apify_dataset_id']

        if dataset_id:
            term_stats[term]['datasets'].append(dataset_id)
            term_stats[term]['total_tweets'] += run['tweets_analyzed'] or 0

    print(f"Processing {len(term_stats)} unique search terms...")
    print()

    # Process each search term
    results = []

    for term, data in sorted(term_stats.items()):
        print(f"📊 Processing: {term}")
        print(f"   Datasets: {len(data['datasets'])}, Expected tweets: {data['total_tweets']}")

        tweets = []

        # Fetch tweets from all datasets for this term
        for dataset_id in data['datasets']:
            try:
                dataset = apify.dataset(dataset_id)
                items = list(dataset.iterate_items())

                for item in items:
                    # Convert to TweetMetrics-like object
                    tweet = type('Tweet', (), {
                        'tweet_id': item.get('id'),
                        'author_handle': item.get('author', {}).get('userName', 'unknown'),
                        'author_followers': item.get('author', {}).get('followers', 0),
                        'text': item.get('text', ''),
                        'likes': item.get('likeCount', 0),
                        'replies': item.get('replyCount', 0),
                        'retweets': item.get('retweetCount', 0),
                        'views': item.get('viewCount', 0),
                        'tweeted_at': datetime.fromisoformat(item.get('createdAt', '').replace('Z', '+00:00'))
                    })()
                    tweets.append(tweet)

            except Exception as e:
                print(f"   ⚠️  Error fetching dataset {dataset_id}: {e}")
                continue

        print(f"   Fetched: {len(tweets)} tweets")

        if not tweets:
            print(f"   ⚠️  No tweets found, skipping")
            print()
            continue

        # Embed and score all tweets
        texts = [t.text for t in tweets]
        embeddings = embedder.embed_texts(texts)

        green_count = 0
        yellow_count = 0
        red_count = 0

        for tweet, embedding in zip(tweets, embeddings):
            result = score_tweet(tweet, embedding, taxonomy_embeddings, config)

            if result.label == 'green':
                green_count += 1
            elif result.label == 'yellow':
                yellow_count += 1
            else:
                red_count += 1

        total = len(tweets)
        green_pct = (green_count / total * 100) if total > 0 else 0
        yellow_pct = (yellow_count / total * 100) if total > 0 else 0
        red_pct = (red_count / total * 100) if total > 0 else 0

        results.append({
            'term': term,
            'green': green_count,
            'yellow': yellow_count,
            'red': red_count,
            'total': total,
            'green_pct': green_pct,
            'yellow_pct': yellow_pct,
            'red_pct': red_pct,
            'datasets': len(data['datasets'])
        })

        print(f"   ✓ Green: {green_count} ({green_pct:.2f}%), Yellow: {yellow_count} ({yellow_pct:.2f}%), Red: {red_count} ({red_pct:.2f}%)")
        print()

    # Sort by green percentage
    results.sort(key=lambda x: x['green_pct'], reverse=True)

    # Print summary
    print()
    print("=" * 80)
    print("RESULTS: Keywords Re-analyzed with 0.50 Threshold")
    print("=" * 80)
    print()
    print(f"{'Search Term':<35} {'Green %':>8} {'Yellow %':>8} {'Red %':>8} {'Total':>7}")
    print("-" * 80)

    for r in results:
        print(f"{r['term']:<35} {r['green_pct']:>7.2f}% {r['yellow_pct']:>7.2f}% {r['red_pct']:>7.2f}% {r['total']:>7}")

    print()
    print("Summary:")
    print(f"  Total search terms: {len(results)}")
    print(f"  Total tweets analyzed: {sum(r['total'] for r in results)}")
    print(f"  Total greens: {sum(r['green'] for r in results)}")
    print(f"  Overall green rate: {(sum(r['green'] for r in results) / sum(r['total'] for r in results) * 100):.2f}%")
    print()
    print(f"  OLD threshold (0.55): 0.38% green rate")
    print(f"  NEW threshold (0.50): {(sum(r['green'] for r in results) / sum(r['total'] for r in results) * 100):.2f}% green rate")
    print(f"  Improvement: {(sum(r['green'] for r in results) / sum(r['total'] for r in results) * 100) / 0.38:.1f}x")
    print()

if __name__ == '__main__':
    main()
