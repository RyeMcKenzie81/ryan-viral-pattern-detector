#!/usr/bin/env python3
"""
Get top 20 tweets by views from yakety-pack-instagram project
"""

import os
import sys
from datetime import datetime
import pandas as pd
from dotenv import load_dotenv
from supabase import create_client, Client

# Load environment
load_dotenv()

# Initialize Supabase
supabase: Client = create_client(
    os.getenv("SUPABASE_URL"),
    os.getenv("SUPABASE_SERVICE_KEY")
)

def get_yakety_tweets():
    """Fetch all tweets from yakety-pack-instagram project"""

    print("Fetching tweets from yakety-pack-instagram project...")

    # Get project ID
    project_result = supabase.table("projects").select("id").eq("slug", "yakety-pack-instagram").execute()

    if not project_result.data:
        print("Error: Project 'yakety-pack-instagram' not found")
        sys.exit(1)

    project_id = project_result.data[0]['id']

    # Get all posts linked to this project (paginated)
    all_project_posts = []
    offset = 0
    limit = 1000

    while True:
        posts_result = supabase.table("project_posts")\
            .select("post_id")\
            .eq("project_id", project_id)\
            .range(offset, offset + limit - 1)\
            .execute()

        all_project_posts.extend(posts_result.data)

        if len(posts_result.data) < limit:
            break

        offset += limit

    post_ids = [p['post_id'] for p in all_project_posts]

    print(f"Found {len(post_ids)} tweets in project")

    # Fetch post data in smaller chunks (Supabase IN clause has limits)
    all_posts = []
    chunk_size = 100

    print(f"Fetching post data...")

    for i in range(0, len(post_ids), chunk_size):
        chunk_ids = post_ids[i:i+chunk_size]

        posts = supabase.table("posts")\
            .select("*, accounts(*)")\
            .in_("id", chunk_ids)\
            .execute()

        all_posts.extend(posts.data)

    print(f"Retrieved {len(all_posts)} tweet records")

    return pd.DataFrame(all_posts)


def main():
    # Get tweets
    df = get_yakety_tweets()

    if len(df) == 0:
        print("No tweets found!")
        sys.exit(1)

    # Fill NaN values with 0 for sorting
    df['views'] = df['views'].fillna(0)
    df['likes'] = df['likes'].fillna(0)
    df['shares'] = df['shares'].fillna(0)
    df['comments'] = df['comments'].fillna(0)

    # Filter for Twitter only (exclude Instagram)
    twitter_df = df[df['post_url'].str.contains('x.com|twitter.com', case=False, na=False)].copy()

    print(f"\nFiltered to Twitter only: {len(twitter_df):,} tweets (from {len(df):,} total posts)")

    # Filter out tweets with video/media (tweets with t.co links typically have attached media)
    text_only_df = twitter_df[~twitter_df['caption'].str.contains('https://t.co/', case=False, na=False)].copy()

    print(f"Filtered to text-only (no video/media): {len(text_only_df):,} tweets (from {len(twitter_df):,} Twitter posts)")

    # Sort by views and get top 20
    top_20 = text_only_df.nlargest(20, 'views')

    print(f"\nText-only Twitter dataset: {len(text_only_df):,} tweets")
    print(f"Top 20 by views:")
    print(f"  Views range: {top_20['views'].min():,.0f} - {top_20['views'].max():,.0f}")

    # Generate markdown report
    markdown = f"""# Yakety Pack - Top 20 Text-Only Twitter Posts by Views

**Analysis Date:** {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}
**Dataset Size:** {len(text_only_df):,} text-only Twitter posts (filtered from {len(twitter_df):,} Twitter posts, {len(df):,} total posts)
**Metric:** Views (impressions)
**Platform:** Twitter/X only (text posts without video/media attachments)
**Filter:** Excludes tweets with embedded media (video, images, etc.)

---

## Top 20 Most Viewed Tweets

"""

    for idx, (i, row) in enumerate(top_20.iterrows(), 1):
        account = row.get('accounts') or {}
        username = account.get('platform_username', 'unknown')
        display_name = account.get('display_name', '')
        followers = account.get('follower_count', 0)

        views = int(row['views']) if pd.notna(row['views']) else 0
        likes = int(row['likes']) if pd.notna(row['likes']) else 0
        shares = int(row['shares']) if pd.notna(row['shares']) else 0
        comments = int(row['comments']) if pd.notna(row['comments']) else 0

        caption = row.get('caption', '')[:300]
        if len(row.get('caption', '')) > 300:
            caption += "..."

        post_url = row.get('post_url', '')
        posted_at = row.get('posted_at', '')

        # Calculate engagement rate
        engagement_rate = 0
        if views > 0:
            engagement_rate = ((likes + shares + comments) / views) * 100

        markdown += f"""### {idx}. {views:,} views

**Account:** {display_name} (@{username})
**Followers:** {followers:,}
**Posted:** {posted_at}

**Engagement Metrics:**
- **Views:** {views:,}
- **Likes:** {likes:,}
- **Retweets:** {shares:,}
- **Replies:** {comments:,}
- **Engagement Rate:** {engagement_rate:.2f}%

**Tweet:**
> {caption}

**URL:** {post_url}

---

"""

    # Write to file
    output_file = "/Users/ryemckenzie/projects/viraltracker/yakety_pack_top_20_twitter_text_only.md"
    with open(output_file, 'w') as f:
        f.write(markdown)

    print(f"\n✅ Report saved to: {output_file}")

    # Summary stats
    print(f"\nTop 20 Summary:")
    print(f"  Total Views: {top_20['views'].sum():,.0f}")
    print(f"  Avg Views: {top_20['views'].mean():,.0f}")
    print(f"  Avg Likes: {top_20['likes'].mean():,.0f}")
    print(f"  Avg Retweets: {top_20['shares'].mean():,.0f}")
    print(f"  Avg Replies: {top_20['comments'].mean():,.0f}")


if __name__ == "__main__":
    main()
