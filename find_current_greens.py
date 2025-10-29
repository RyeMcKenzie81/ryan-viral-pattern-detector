#!/usr/bin/env python3
"""
Find the 12 green tweets from current analysis by re-scoring
"""
import csv
from datetime import datetime
from viraltracker.core.config import load_finder_config
from viraltracker.core.embeddings import Embedder, load_taxonomy_embeddings_incremental
from viraltracker.generation.comment_finder import score_tweet
from viraltracker.generation.tweet_fetcher import fetch_recent_tweets

def main():
    print("🔍 Finding green tweets from last 14 days (10+ followers)...")

    # Fetch tweets (same parameters as running process)
    tweets = fetch_recent_tweets(
        project_slug='yakety-pack-instagram',
        hours_back=336,  # 14 days
        min_followers=10,
        min_likes=0,
        max_candidates=10000,
        require_english=True
    )

    print(f"📊 Fetched {len(tweets)} tweets")

    # Load config and embeddings
    config = load_finder_config('yakety-pack-instagram')
    embedder = Embedder()
    taxonomy_embeddings = load_taxonomy_embeddings_incremental(
        'yakety-pack-instagram',
        config.taxonomy,
        embedder
    )

    print(f"🔢 Embedding {len(tweets)} tweets...")
    texts = [t.text for t in tweets]
    embeddings = embedder.embed_texts(texts)

    print(f"🎯 Scoring {len(tweets)} tweets...")
    greens = []

    for tweet, embedding in zip(tweets, embeddings):
        result = score_tweet(tweet, embedding, taxonomy_embeddings, config)

        if result.label == 'green':
            greens.append({
                'tweet': tweet,
                'scores': result
            })

    print(f"\n✅ Found {len(greens)} green tweets")

    # Sort by score
    greens.sort(key=lambda x: x['scores'].total_score, reverse=True)

    # Export to CSV
    output_file = '/Users/ryemckenzie/Downloads/green_tweets_found.csv'

    with open(output_file, 'w', newline='', encoding='utf-8') as f:
        writer = csv.writer(f)

        writer.writerow([
            'tweet_id', 'author', 'followers', 'views', 'likes', 'replies', 'retweets',
            'tweet_text', 'posted_at',
            'score_total', 'score_velocity', 'score_relevance', 'score_openness', 'score_author_quality',
            'label', 'topic'
        ])

        for item in greens:
            tweet = item['tweet']
            scores = item['scores']

            writer.writerow([
                tweet.tweet_id,
                tweet.author_handle,
                tweet.author_followers,
                tweet.views,
                tweet.likes,
                tweet.replies,
                tweet.retweets,
                tweet.text.replace('\n', ' '),
                tweet.tweeted_at.isoformat(),
                scores.total_score,
                scores.velocity,
                scores.relevance,
                scores.openness,
                scores.author_quality,
                scores.label,
                scores.best_topic
            ])

    print(f"\n💾 Exported to: {output_file}")

    # Print summary
    print("\n" + "="*80)
    print(f"GREEN TWEETS ({len(greens)} total)")
    print("="*80)

    for i, item in enumerate(greens, 1):
        tweet = item['tweet']
        scores = item['scores']

        print(f"\n[{i}] @{tweet.author_handle} ({tweet.author_followers:,} followers)")
        print(f"Score: {scores.total_score:.3f} | Topic: {scores.best_topic}")
        print(f"Tweet ID: {tweet.tweet_id}")
        text = tweet.text[:200]
        print(f"Text: {text}{'...' if len(tweet.text) > 200 else ''}")
        print(f"Engagement: {tweet.views:,} views, {tweet.likes} likes, {tweet.replies} replies")
        print(f"Component scores: vel={scores.velocity:.3f}, rel={scores.relevance:.3f}, open={scores.openness:.3f}, auth={scores.author_quality:.3f}")

if __name__ == '__main__':
    main()
