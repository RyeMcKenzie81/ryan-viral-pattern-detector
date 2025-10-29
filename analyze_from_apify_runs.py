#!/usr/bin/env python3
"""
Analyze search terms using exact tweets from Apify run IDs.
This bypasses the analyzer bug by directly fetching tweets from Apify datasets.
"""

import json
import os
from datetime import datetime
from pathlib import Path
from typing import List, Dict

from apify_client import ApifyClient
from viraltracker.core.database import get_supabase_client
from viraltracker.core.config import load_finder_config
from viraltracker.core.embeddings import Embedder, load_taxonomy_embeddings_incremental
from viraltracker.generation.comment_finder import score_tweet, TweetMetrics

# Apify run IDs mapped to search terms
APIFY_RUNS = {
    "screen time kids": "YqleEGE20sNu46TGs",
    "parenting tips": "g4ymQGCjwQ0TBnSwN",
    "digital wellness": "Ady8Dc5RcfjhvZsil",
    "kids screen time": "f2MIVR30lesa5QTBH",
    "parenting advice": "c0pV3PgvUd9nG5ULN",
    "toddler behavior": "ifD7rGfvLTzYmMUXN",
    "device limits": "msR19adwf31yNEBn6",
    "screen time rules": "f9zehxmr9Df26QFpu",
    "family routines": "CBT5zXDx1UmlhcelJ",
    "digital parenting": "wpcFa0UIZa3ubb5XT",
    "kids social media": "ZvquL8H7rH8faTsBJ",
    "online safety kids": "QCit77nHwnSDvXL1S",
    "tech boundaries": "ecqcxnsWAWAnMY7dL",
    "kids technology": "QW6BeINrjcN3nA0hD",
    "mindful parenting": "JWsIlL9i3zB8NKALO",
}

def fetch_apify_dataset(run_id: str) -> List[Dict]:
    """Fetch tweets from an Apify run dataset."""
    client = ApifyClient(os.getenv('APIFY_API_TOKEN'))

    # Get run details to find dataset ID
    run = client.run(run_id).get()
    dataset_id = run['defaultDatasetId']

    # Fetch all items from dataset
    items = list(client.dataset(dataset_id).iterate_items())

    return items

def fetch_tweets_from_db(tweet_ids: List[str], project_id: str) -> List[Dict]:
    """Fetch specific tweets from database by tweet IDs."""
    db = get_supabase_client()

    # Get Twitter platform ID
    platform_result = db.table('platforms').select('id').eq('slug', 'twitter').single().execute()
    platform_id = platform_result.data['id']

    # Query tweets by post_id (which contains Twitter tweet ID)
    result = db.table('posts')\
        .select('post_id, caption, posted_at, views, likes, comments, shares, accounts(platform_username, follower_count)')\
        .eq('platform_id', platform_id)\
        .in_('post_id', tweet_ids)\
        .execute()

    return result.data if result.data else []

def convert_to_tweet_metrics(db_tweets: List[Dict]) -> List[TweetMetrics]:
    """Convert database tweets to TweetMetrics objects."""
    tweets = []

    for row in db_tweets:
        account_data = row.get('accounts', {}) or {}

        tweet = TweetMetrics(
            tweet_id=row['post_id'],
            text=row['caption'] or '',
            author_handle=account_data.get('platform_username', 'unknown'),
            author_followers=account_data.get('follower_count', 0) or 0,
            tweeted_at=datetime.fromisoformat(row['posted_at'].replace('Z', '+00:00')),
            likes=row.get('likes', 0) or 0,
            replies=row.get('comments', 0) or 0,
            retweets=row.get('shares', 0) or 0,
            lang='en'
        )
        tweets.append(tweet)

    return tweets

def analyze_search_term(
    search_term: str,
    tweets: List[TweetMetrics],
    config,
    embedder: Embedder,
    project_slug: str
) -> Dict:
    """Analyze tweets for a search term."""

    if not tweets:
        return None

    print(f"\nAnalyzing {len(tweets)} tweets for '{search_term}'...")

    # Load taxonomy embeddings
    taxonomy_embeddings = load_taxonomy_embeddings_incremental(
        project_slug,
        config.taxonomy,
        embedder
    )

    # Embed tweets
    print("  Generating embeddings...")
    tweet_texts = [t.text for t in tweets]
    tweet_embeddings = embedder.embed_texts(tweet_texts)

    # Score tweets
    print("  Scoring tweets...")
    scored_results = []
    for tweet, embedding in zip(tweets, tweet_embeddings):
        result = score_tweet(tweet, embedding, taxonomy_embeddings, config)
        scored_results.append(result)

    # Calculate metrics using LABELS (not similarity scores)
    green = [r for r in scored_results if r.label == 'green']
    yellow = [r for r in scored_results if r.label == 'yellow']
    red = [r for r in scored_results if r.label == 'red']

    # Calculate relevance-only distribution (semantic similarity)
    # Green: >=0.55, Yellow: 0.45-0.54, Red: <0.45
    relevance_green = [r for r in scored_results if r.best_topic_similarity >= 0.55]
    relevance_yellow = [r for r in scored_results if 0.45 <= r.best_topic_similarity < 0.55]
    relevance_red = [r for r in scored_results if r.best_topic_similarity < 0.45]

    # Calculate component score averages for each label
    def avg_component(results, component):
        """Calculate average of a specific component for a list of results."""
        if not results:
            return 0.0
        return round(sum(getattr(r, component) for r in results) / len(results), 3)

    component_scores = {
        "all": {
            "velocity": avg_component(scored_results, 'velocity'),
            "relevance": avg_component(scored_results, 'relevance'),
            "openness": avg_component(scored_results, 'openness'),
            "author_quality": avg_component(scored_results, 'author_quality')
        },
        "green": {
            "velocity": avg_component(green, 'velocity'),
            "relevance": avg_component(green, 'relevance'),
            "openness": avg_component(green, 'openness'),
            "author_quality": avg_component(green, 'author_quality')
        },
        "yellow": {
            "velocity": avg_component(yellow, 'velocity'),
            "relevance": avg_component(yellow, 'relevance'),
            "openness": avg_component(yellow, 'openness'),
            "author_quality": avg_component(yellow, 'author_quality')
        },
        "red": {
            "velocity": avg_component(red, 'velocity'),
            "relevance": avg_component(red, 'relevance'),
            "openness": avg_component(red, 'openness'),
            "author_quality": avg_component(red, 'author_quality')
        }
    }

    # Build scored_tweets for topic distribution
    scored_tweets = []
    for tweet, result in zip(tweets, scored_results):
        tweet.score = result.total_score
        tweet.best_topic = result.best_topic
        scored_tweets.append(tweet)

    # Topic distribution
    topic_dist = {}
    for tweet in scored_tweets:
        topic_dist[tweet.best_topic] = topic_dist.get(tweet.best_topic, 0) + 1

    # Freshness and volume calculation
    now = datetime.now(scored_tweets[0].tweeted_at.tzinfo)
    last_48h = [t for t in scored_tweets if (now - t.tweeted_at).total_seconds() < 48 * 3600]

    # Calculate time span and tweets per 24h
    if scored_tweets:
        tweet_times = [t.tweeted_at for t in scored_tweets]
        oldest_tweet = min(tweet_times)
        newest_tweet = max(tweet_times)
        time_span_hours = (newest_tweet - oldest_tweet).total_seconds() / 3600
        tweets_per_24h = round(len(scored_tweets) / (time_span_hours / 24), 1) if time_span_hours > 0 else len(scored_tweets)
    else:
        tweets_per_24h = 0

    metrics = {
        "project": project_slug,
        "search_term": search_term,
        "analyzed_at": datetime.now().isoformat(),
        "tweets_analyzed": len(scored_tweets),
        "metrics": {
            "score_distribution": {
                "green": {
                    "count": len(green),
                    "percentage": round(len(green) / len(scored_tweets) * 100, 1),
                    "avg_score": round(sum(r.total_score for r in green) / len(green), 3) if green else 0
                },
                "yellow": {
                    "count": len(yellow),
                    "percentage": round(len(yellow) / len(scored_tweets) * 100, 1),
                    "avg_score": round(sum(r.total_score for r in yellow) / len(yellow), 3) if yellow else 0
                },
                "red": {
                    "count": len(red),
                    "percentage": round(len(red) / len(scored_tweets) * 100, 1),
                    "avg_score": round(sum(r.total_score for r in red) / len(red), 3) if red else 0
                }
            },
            "freshness": {
                "last_48h_count": len(last_48h),
                "last_48h_percentage": round(len(last_48h) / len(scored_tweets) * 100, 1),
                "conversations_per_day": round(len(last_48h) / 2, 1),
                "tweets_per_24h": tweets_per_24h
            },
            "relevance_only_distribution": {
                "green": {
                    "count": len(relevance_green),
                    "percentage": round(len(relevance_green) / len(scored_tweets) * 100, 1),
                    "avg_similarity": round(sum(r.best_topic_similarity for r in relevance_green) / len(relevance_green), 3) if relevance_green else 0
                },
                "yellow": {
                    "count": len(relevance_yellow),
                    "percentage": round(len(relevance_yellow) / len(scored_tweets) * 100, 1),
                    "avg_similarity": round(sum(r.best_topic_similarity for r in relevance_yellow) / len(relevance_yellow), 3) if relevance_yellow else 0
                },
                "red": {
                    "count": len(relevance_red),
                    "percentage": round(len(relevance_red) / len(scored_tweets) * 100, 1),
                    "avg_similarity": round(sum(r.best_topic_similarity for r in relevance_red) / len(relevance_red), 3) if relevance_red else 0
                }
            },
            "virality": {
                "avg_views": 0,
                "median_views": 0,
                "top_10_percent_avg_views": 0,
                "tweets_with_10k_plus_views": 0
            },
            "component_scores": component_scores,
            "topic_distribution": topic_dist,
            "cost_efficiency": {
                "total_cost_usd": 0.0,
                "cost_per_green_tweet": 0.0,
                "greens_per_dollar": 0
            }
        }
    }

    # Add recommendation
    green_pct = metrics["metrics"]["score_distribution"]["green"]["percentage"]

    if green_pct >= 15:
        rating = "Excellent"
        confidence = "High"
        reasoning = f"{green_pct}% green (target: 15%+). High volume. Use this term regularly."
    elif green_pct >= 8:
        rating = "Good"
        confidence = "High"
        reasoning = f"{green_pct}% green (target: 8%+). Good quality. Recommended for regular use."
    elif green_pct >= 5:
        rating = "Okay"
        confidence = "Medium"
        reasoning = f"{green_pct}% green. Moderate quality. Consider for supplemental sourcing."
    else:
        rating = "Poor"
        confidence = "High"
        reasoning = f"Only {green_pct}% green (target: 8%+). Consider other terms."

    metrics["recommendation"] = {
        "rating": rating,
        "confidence": confidence,
        "reasoning": reasoning
    }

    return metrics

def main():
    """Main analysis function."""
    print("=" * 80)
    print("CORRECTED SEARCH TERM ANALYSIS - Using Apify Run IDs")
    print("=" * 80)
    print()

    # Setup
    project_slug = "yakety-pack-instagram"
    config = load_finder_config(project_slug)
    embedder = Embedder()

    db = get_supabase_client()
    project_result = db.table('projects').select('id').eq('slug', project_slug).single().execute()
    project_id = project_result.data['id']

    output_dir = Path.home() / "Downloads" / "term_analysis_corrected"
    output_dir.mkdir(exist_ok=True)

    # Process each search term
    all_results = []

    for search_term, run_id in APIFY_RUNS.items():
        print(f"\n{'=' * 80}")
        print(f"Processing: {search_term}")
        print(f"Apify run ID: {run_id}")
        print(f"{'=' * 80}")

        try:
            # Fetch Apify dataset
            print(f"Fetching Apify dataset...")
            apify_tweets = fetch_apify_dataset(run_id)
            print(f"Found {len(apify_tweets)} tweets in Apify dataset")

            # Extract tweet IDs
            tweet_ids = [t['id'] for t in apify_tweets if 'id' in t]
            print(f"Extracted {len(tweet_ids)} tweet IDs")

            # Fetch from database
            print(f"Fetching tweets from database...")
            db_tweets = fetch_tweets_from_db(tweet_ids, project_id)
            print(f"Found {len(db_tweets)} tweets in database")

            # Convert to TweetMetrics
            tweets = convert_to_tweet_metrics(db_tweets)

            # Analyze
            metrics = analyze_search_term(search_term, tweets, config, embedder, project_slug)

            if metrics:
                # Save to JSON
                filename = search_term.replace(' ', '_') + '_analysis.json'
                filepath = output_dir / filename
                with open(filepath, 'w') as f:
                    json.dump(metrics, f, indent=2)

                print(f"✅ Saved: {filepath}")
                print(f"   {metrics['tweets_analyzed']} tweets analyzed")
                print(f"   {metrics['metrics']['freshness']['tweets_per_24h']} tweets/24h")
                print(f"   Composite: {metrics['metrics']['score_distribution']['green']['percentage']}% green")
                print(f"   Relevance-only: {metrics['metrics']['relevance_only_distribution']['green']['percentage']}% green")
                print(f"   Rating: {metrics['recommendation']['rating']}")

                all_results.append(metrics)

        except Exception as e:
            print(f"❌ Error processing {search_term}: {e}")
            import traceback
            traceback.print_exc()
            continue

    print(f"\n{'=' * 80}")
    print(f"COMPLETE!")
    print(f"{'=' * 80}")
    print(f"Analyzed {len(all_results)}/{len(APIFY_RUNS)} search terms")
    print(f"Results saved to: {output_dir}")
    print(f"{'=' * 80}")

if __name__ == '__main__':
    main()
