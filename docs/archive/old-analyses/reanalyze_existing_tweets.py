#!/usr/bin/env python3
"""
Re-analyze existing tweets in database with updated metrics.

This script queries tweets that were already scraped for each search term
and re-runs the analysis to add the new metrics:
- tweets_per_24h
- relevance-only scores (avg_relevance_score, green/yellow/red_avg_relevance)

No new scraping is performed - uses existing data.
"""

import sys
from pathlib import Path
from datetime import datetime, timedelta

from viraltracker.analysis.search_term_analyzer import SearchTermAnalyzer
from viraltracker.scrapers.twitter import TwitterScraper
from viraltracker.generation.comment_finder import TweetMetrics
from viraltracker.core.database import get_supabase_client


def get_existing_tweets_for_term(project_slug: str, search_term: str, limit: int = 1000):
    """
    Query existing tweets from database for a search term.

    Unlike the analyzer's _scrape_tweets which uses updated_at,
    this queries by the search term itself from the posts table.
    """
    db = get_supabase_client()

    # Get project ID
    project_result = db.table('projects').select('id').eq('slug', project_slug).single().execute()
    if not project_result.data:
        raise ValueError(f"Project '{project_slug}' not found")

    project_id = project_result.data['id']

    # Get Twitter platform ID
    platform_result = db.table('platforms').select('id').eq('slug', 'twitter').single().execute()
    if not platform_result.data:
        raise ValueError("Twitter platform not found")

    platform_id = platform_result.data['id']

    # Query posts that contain this search term in caption
    # This is approximate - ideally we'd have a search_terms table
    # For now, we'll just query recent posts from this project
    cutoff_date = datetime.now() - timedelta(days=14)

    result = db.table('posts')\
        .select('post_id, caption, posted_at, views, likes, comments, shares, accounts(platform_username, follower_count), project_posts!inner(project_id), updated_at')\
        .eq('platform_id', platform_id)\
        .eq('project_posts.project_id', project_id)\
        .gte('posted_at', cutoff_date.isoformat())\
        .order('posted_at', desc=True)\
        .limit(limit * 3)\
        .execute()

    if not result.data:
        return []

    # Filter by search term in caption
    # (This is a workaround since we don't store which search term fetched which tweet)
    search_words = set(search_term.lower().split())
    filtered_tweets = []

    for row in result.data:
        caption = (row.get('caption') or '').lower()
        # Check if most search words appear in caption
        matches = sum(1 for word in search_words if word in caption)
        if matches >= len(search_words) / 2:  # At least half the words match
            account_data = row.get('accounts', {})

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
            filtered_tweets.append(tweet)

            if len(filtered_tweets) >= limit:
                break

    return filtered_tweets


def reanalyze_term(project_slug: str, search_term: str, output_dir: Path):
    """Re-analyze a single search term using existing tweets."""
    print(f"\n{'='*60}")
    print(f"Re-analyzing: {search_term}")
    print(f"{'='*60}")

    # Get existing tweets
    print("Querying existing tweets from database...")
    tweets = get_existing_tweets_for_term(project_slug, search_term)

    if not tweets:
        print(f"⚠️  No tweets found for '{search_term}' in database")
        return None

    print(f"Found {len(tweets)} tweets")

    # Create analyzer
    analyzer = SearchTermAnalyzer(project_slug)

    # Embed tweets
    print("Generating embeddings...")
    tweet_embeddings = analyzer._embed_tweets(tweets)

    # Score tweets
    print("Scoring tweets...")
    scored_tweets = analyzer._score_tweets(tweets, tweet_embeddings)

    # Calculate metrics (skip comment generation)
    print("Calculating metrics...")
    generation_stats = {'total_cost_usd': 0.0}
    metrics = analyzer._calculate_metrics(
        search_term,
        tweets,
        scored_tweets,
        generation_stats
    )

    # Add recommendation
    metrics = analyzer._add_recommendation(metrics)

    # Export to JSON
    filename = search_term.replace(' ', '_') + '_analysis.json'
    output_path = output_dir / filename
    analyzer.export_json(metrics, str(output_path))

    print(f"✅ Complete: {metrics.green_percentage:.1f}% green ({metrics.green_count}/{len(tweets)})")
    print(f"   Tweets/24h: {metrics.tweets_per_24h:.1f}")
    print(f"   Avg Relevance: {metrics.avg_relevance_score:.3f}")
    print(f"   Saved to: {output_path}")

    return metrics


def main():
    project_slug = 'yakety-pack-instagram'

    # Search terms to re-analyze
    terms = [
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

    # Output directory
    output_dir = Path.home() / 'Downloads' / 'term_analysis_rerun'
    output_dir.mkdir(exist_ok=True)

    print("="*60)
    print("Re-analyzing Existing Tweets with New Metrics")
    print("="*60)
    print(f"Project: {project_slug}")
    print(f"Terms: {len(terms)}")
    print(f"Output: {output_dir}")
    print(f"New metrics: tweets_per_24h, relevance scores")
    print("="*60)

    # Re-analyze each term
    results = []
    for i, term in enumerate(terms, 1):
        print(f"\n[{i}/{len(terms)}]")
        try:
            metrics = reanalyze_term(project_slug, term, output_dir)
            if metrics:
                results.append(metrics)
        except Exception as e:
            print(f"❌ Error analyzing '{term}': {e}")
            import traceback
            traceback.print_exc()

    # Summary
    print("\n" + "="*60)
    print("Re-analysis Complete!")
    print("="*60)
    print(f"Successfully analyzed: {len(results)}/{len(terms)} terms")
    print(f"Results saved to: {output_dir}")
    print("\nNext step:")
    print(f"  cd /Users/ryemckenzie/projects/viraltracker")
    print(f"  python3 extract_results.py")
    print("="*60)


if __name__ == '__main__':
    main()
