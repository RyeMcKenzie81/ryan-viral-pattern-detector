#!/usr/bin/env python3
"""
Test lowering green threshold to 0.50
Export all tweets >= 0.50 for quality review
"""
import csv
from datetime import datetime
from viraltracker.core.config import load_finder_config
from viraltracker.core.embeddings import Embedder, load_taxonomy_embeddings_incremental
from viraltracker.generation.comment_finder import score_tweet
from viraltracker.generation.tweet_fetcher import fetch_recent_tweets

def main():
    print("🔍 Testing threshold 0.50 (vs current 0.55)...")

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

    # Collect tweets by threshold
    threshold_050 = []  # >= 0.50
    current_greens = []  # >= 0.55 (current threshold)

    for tweet, embedding in zip(tweets, embeddings):
        result = score_tweet(tweet, embedding, taxonomy_embeddings, config)

        if result.total_score >= 0.50:
            threshold_050.append({
                'tweet': tweet,
                'scores': result
            })

        if result.total_score >= 0.55:
            current_greens.append({
                'tweet': tweet,
                'scores': result
            })

    # Sort by score
    threshold_050.sort(key=lambda x: x['scores'].total_score, reverse=True)

    print(f"\n📊 Results:")
    print(f"  Current greens (≥ 0.55): {len(current_greens)}")
    print(f"  With 0.50 threshold: {len(threshold_050)}")
    print(f"  Additional tweets: {len(threshold_050) - len(current_greens)}")

    # Export to CSV
    output_file = '/Users/ryemckenzie/Downloads/tweets_threshold_050.csv'

    with open(output_file, 'w', newline='', encoding='utf-8') as f:
        writer = csv.writer(f)

        writer.writerow([
            'score_total', 'current_label', 'new_label',
            'tweet_id', 'author', 'followers', 'views', 'likes', 'replies', 'retweets',
            'tweet_text', 'posted_at',
            'score_velocity', 'score_relevance', 'score_openness', 'score_author_quality',
            'topic'
        ])

        for item in threshold_050:
            tweet = item['tweet']
            scores = item['scores']

            # Label under current threshold (0.55)
            if scores.total_score >= 0.55:
                current_label = 'green'
            elif scores.total_score >= 0.40:
                current_label = 'yellow'
            else:
                current_label = 'red'

            # Label under new threshold (0.50)
            new_label = 'green'  # All are >= 0.50

            writer.writerow([
                scores.total_score,
                current_label,
                new_label,
                tweet.tweet_id,
                tweet.author_handle,
                tweet.author_followers,
                tweet.views,
                tweet.likes,
                tweet.replies,
                tweet.retweets,
                tweet.text.replace('\n', ' '),
                tweet.tweeted_at.isoformat(),
                scores.velocity,
                scores.relevance,
                scores.openness,
                scores.author_quality,
                scores.best_topic
            ])

    print(f"\n💾 Exported to: {output_file}")

    # Print summary by score band
    print("\n" + "="*80)
    print("SCORE DISTRIBUTION")
    print("="*80)

    bands = {
        '0.55-0.70': [x for x in threshold_050 if 0.55 <= x['scores'].total_score < 0.70],
        '0.52-0.55': [x for x in threshold_050 if 0.52 <= x['scores'].total_score < 0.55],
        '0.50-0.52': [x for x in threshold_050 if 0.50 <= x['scores'].total_score < 0.52],
    }

    for band_name, band_tweets in bands.items():
        print(f"\n{band_name}: {len(band_tweets)} tweets")
        if band_tweets:
            topics = {}
            for item in band_tweets:
                topic = item['scores'].best_topic
                topics[topic] = topics.get(topic, 0) + 1
            print(f"  Topics: {topics}")

    # Show NEW tweets in 0.50-0.55 range
    new_greens = [x for x in threshold_050 if 0.50 <= x['scores'].total_score < 0.55]

    print("\n" + "="*80)
    print(f"NEW 'GREEN' TWEETS (0.50-0.55 range) - {len(new_greens)} tweets")
    print("="*80)

    # Sort new greens by engagement (views)
    new_greens_sorted = sorted(new_greens, key=lambda x: x['tweet'].views, reverse=True)

    for i, item in enumerate(new_greens_sorted[:15], 1):  # Show top 15 by engagement
        tweet = item['tweet']
        scores = item['scores']

        print(f"\n[{i}] @{tweet.author_handle} ({tweet.author_followers:,} followers)")
        print(f"Score: {scores.total_score:.3f} | Topic: {scores.best_topic}")
        text = tweet.text[:150]
        print(f"Text: {text}{'...' if len(tweet.text) > 150 else ''}")
        print(f"Engagement: {tweet.views:,} views, {tweet.likes} likes, {tweet.replies} replies")
        print(f"Components: vel={scores.velocity:.3f}, rel={scores.relevance:.3f}, open={scores.openness:.3f}")

    if len(new_greens) > 15:
        print(f"\n... and {len(new_greens) - 15} more in the CSV")

    # Show engagement stats for 0.50-0.52 band specifically
    band_050_052 = [x for x in threshold_050 if 0.50 <= x['scores'].total_score < 0.52]
    if band_050_052:
        avg_views = sum(x['tweet'].views for x in band_050_052) / len(band_050_052)
        avg_likes = sum(x['tweet'].likes for x in band_050_052) / len(band_050_052)
        print(f"\n📊 0.50-0.52 band engagement stats:")
        print(f"  Count: {len(band_050_052)}")
        print(f"  Avg views: {avg_views:,.0f}")
        print(f"  Avg likes: {avg_likes:.1f}")

if __name__ == '__main__':
    main()
