#!/usr/bin/env python3
"""
Export the most recent green tweets from generate-comments run
"""
import csv
from datetime import datetime
from viraltracker.core.database import get_supabase_client

def main():
    db = get_supabase_client()

    # Get recent green tweets from generated_comments
    # Order by created_at to get the most recent ones
    result = db.table('generated_comments')\
        .select('tweet_id, label, score_total, topic, why, suggestion_type, comment_text, created_at')\
        .eq('label', 'green')\
        .order('created_at', desc=True)\
        .limit(50)\
        .execute()

    print(f"Found {len(result.data)} green tweets")

    if not result.data:
        print("No green tweets found")
        return

    # Get the tweet IDs
    tweet_ids = [row['tweet_id'] for row in result.data]

    # Fetch corresponding posts with account data
    posts_result = db.table('posts')\
        .select('post_id, caption, posted_at, likes, comments, shares, views, post_url, accounts(platform_username, follower_count)')\
        .in_('post_id', tweet_ids)\
        .execute()

    # Create a lookup dict by post_id
    posts_by_id = {post['post_id']: post for post in posts_result.data}

    print(f"Fetched {len(posts_by_id)} corresponding posts")

    if not result.data:
        print("No green tweets found")
        return

    # Export to CSV
    output_file = '/Users/ryemckenzie/Downloads/green_tweets_latest.csv'

    with open(output_file, 'w', newline='', encoding='utf-8') as f:
        writer = csv.writer(f)

        # Header
        writer.writerow([
            'tweet_id', 'url', 'author', 'followers', 'views', 'likes', 'replies', 'retweets',
            'tweet_text', 'posted_at', 'created_at',
            'score_total', 'label', 'topic', 'why', 'suggested_response', 'suggested_type'
        ])

        # Data rows
        for row in result.data:
            tweet_id = row.get('tweet_id', '')
            post = posts_by_id.get(tweet_id)

            if not post:
                continue

            account = post.get('accounts', {})

            writer.writerow([
                tweet_id,
                post.get('post_url', ''),
                account.get('platform_username', '') if account else '',
                account.get('follower_count', 0) if account else 0,
                post.get('views', 0) or 0,
                post.get('likes', 0) or 0,
                post.get('comments', 0) or 0,
                post.get('shares', 0) or 0,
                (post.get('caption', '') or '').replace('\n', ' '),
                post.get('posted_at', ''),
                row.get('created_at', ''),
                row.get('score_total', 0),
                row.get('label', ''),
                row.get('topic', ''),
                (row.get('why', '') or '').replace('\n', ' '),
                (row.get('comment_text', '') or '').replace('\n', ' '),
                row.get('suggestion_type', '')
            ])

    print(f"\n✅ Exported {len(result.data)} green tweets to: {output_file}")

    # Also print summary
    print("\n" + "="*80)
    print("GREEN TWEET SUMMARY")
    print("="*80)

    for i, row in enumerate(result.data[:12], 1):  # Show first 12
        tweet_id = row.get('tweet_id', '')
        post = posts_by_id.get(tweet_id)

        if not post:
            continue

        account = post.get('accounts', {})

        print(f"\n[{i}] @{account.get('platform_username', 'unknown') if account else 'unknown'} ({account.get('follower_count', 0) if account else 0:,} followers)")
        print(f"Score: {row.get('score_total', 0):.3f} | Topic: {row.get('topic', 'unknown')}")
        print(f"URL: {post.get('post_url', '')}")
        text = (post.get('caption', '') or '')[:200]
        print(f"Text: {text}{'...' if len(post.get('caption', '') or '') > 200 else ''}")
        print(f"Engagement: {post.get('views', 0):,} views, {post.get('likes', 0)} likes, {post.get('comments', 0)} replies")

if __name__ == '__main__':
    main()
