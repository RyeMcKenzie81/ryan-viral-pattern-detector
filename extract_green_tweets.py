#!/usr/bin/env python3
"""
Extract and display all green tweets from V3 batch analysis
"""
import asyncio
from datetime import datetime
from viraltracker.core.database import get_supabase_client
from viraltracker.core.config import load_finder_config
from viraltracker.core.embeddings import Embedder, load_taxonomy_embeddings_incremental
from viraltracker.generation.comment_finder import score_tweet, TweetMetrics

async def main():
    db = get_supabase_client()

    # Get all V3 analysis runs with green tweets
    runs = db.table('analysis_runs')\
        .select('id, search_term, apify_run_id, green_count, started_at, completed_at')\
        .gt('green_count', 0)\
        .gte('started_at', '2025-10-27T13:00:00')\
        .order('started_at')\
        .execute()

    print(f"Found {len(runs.data)} analysis runs with green tweets")
    print("=" * 80)

    # Load config and embeddings for scoring
    config = load_finder_config('yakety-pack-instagram')
    embedder = Embedder()
    taxonomy_embeddings = load_taxonomy_embeddings_incremental(
        'yakety-pack-instagram',
        config.taxonomy,
        embedder
    )

    platform_result = db.table('platforms').select('id').eq('slug', 'twitter').single().execute()
    platform_id = platform_result.data['id']

    # Instead of per-run, get ALL tweets from the V3 batch period
    # This is simpler since analysis_run_id isn't being populated
    print("\n📥 Fetching all tweets from V3 batch period (Oct 20-27)...")

    result = db.table('posts')\
        .select('post_id, caption, posted_at, views, likes, comments, shares, post_url, accounts(platform_username, follower_count), project_posts!inner(project_id)')\
        .eq('platform_id', platform_id)\
        .eq('project_posts.project_id', '8fe8c0bc-e294-486c-8502-c0ade86de5a5')\
        .gte('posted_at', '2025-10-20T00:00:00')\
        .lte('posted_at', '2025-10-27T23:59:59')\
        .order('posted_at', desc=True)\
        .limit(10000)\
        .execute()

    print(f"Found {len(result.data)} tweets to score")

    # Convert to TweetMetrics objects
    tweets = []
    urls = []
    for row in result.data:
        account = row.get('accounts', {})
        if not account:
            continue

        tweet = TweetMetrics(
            tweet_id=row['post_id'],
            text=row['caption'] or '',
            author_handle=account.get('platform_username', 'unknown'),
            author_followers=account.get('follower_count', 0) or 0,
            tweeted_at=datetime.fromisoformat(row['posted_at'].replace('Z', '+00:00')),
            likes=row.get('likes', 0) or 0,
            replies=row.get('comments', 0) or 0,
            retweets=row.get('shares', 0) or 0,
            views=row.get('views', 0) or 0,
            lang='en'
        )
        tweets.append(tweet)
        urls.append(row['post_url'])

    print(f"📊 Embedding {len(tweets)} tweets (in batches of 100)...")
    texts = [t.text for t in tweets]

    # Embed in smaller batches to avoid API limits
    embeddings = []
    batch_size = 100
    for i in range(0, len(texts), batch_size):
        batch = texts[i:i+batch_size]
        batch_embeddings = embedder.embed_texts(batch)
        embeddings.extend(batch_embeddings)
        print(f"  Embedded {min(i+batch_size, len(texts))}/{len(texts)} tweets")
        if i + batch_size < len(texts):
            import time
            time.sleep(2)  # Brief pause between batches

    print(f"🎯 Scoring {len(tweets)} tweets...")
    all_greens = []

    for i, (tweet, embedding, url) in enumerate(zip(tweets, embeddings, urls)):
        if i % 100 == 0:
            print(f"  Scored {i}/{len(tweets)} tweets... ({len(all_greens)} greens so far)")

        # Score it
        result_obj = score_tweet(tweet, embedding, taxonomy_embeddings, config)

        if result_obj.label == 'green':
            all_greens.append({
                'tweet': tweet,
                'scores': result_obj,
                'url': url
            })

    print(f"\n✅ Scoring complete! Found {len(all_greens)} green tweets total")

    print("\n" + "=" * 80)
    print(f"\n🟢 ALL GREEN TWEETS ({len(all_greens)} total)\n")
    print("=" * 80)

    for i, item in enumerate(all_greens, 1):
        tweet = item['tweet']
        scores = item['scores']

        print(f"\n[{i}]")
        print(f"Author: @{tweet.author_handle} ({tweet.author_followers:,} followers)")
        print(f"Posted: {tweet.tweeted_at.strftime('%Y-%m-%d %H:%M')}")
        print(f"URL: {item['url']}")
        print(f"\nTweet text:")
        print(f"  {tweet.text[:300]}{'...' if len(tweet.text) > 300 else ''}")
        print(f"\nEngagement:")
        print(f"  Views: {tweet.views:,} | Likes: {tweet.likes} | Replies: {tweet.replies} | Retweets: {tweet.retweets}")
        print(f"\nScores:")
        print(f"  Velocity:       {scores.velocity:.3f}")
        print(f"  Relevance:      {scores.relevance:.3f} → Topic: {scores.best_topic}")
        print(f"  Openness:       {scores.openness:.3f}")
        print(f"  Author Quality: {scores.author_quality:.3f}")
        print(f"  TOTAL:          {scores.total_score:.3f} ({scores.label})")
        print("-" * 80)

if __name__ == '__main__':
    asyncio.run(main())
