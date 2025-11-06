"""
Show breakdown of how accounts filter through each criterion.
"""
from datetime import datetime, timedelta
from viraltracker.core.config import Config
from supabase import create_client, Client
from collections import defaultdict
import statistics

Config.validate()
supabase: Client = create_client(Config.SUPABASE_URL, Config.SUPABASE_SERVICE_KEY)

def analyze_with_breakdown():
    """Show how many accounts pass each filter stage."""

    # Get the project
    project_response = supabase.table("projects").select("id, name").eq("slug", "masculinity-tiktok").execute()
    project = project_response.data[0]
    project_id = project["id"]

    # Get all posts
    posts_response = supabase.table("project_posts")\
        .select("post_id, posts(id, account_id, posted_at, views, accounts(id, platform_username, display_name, follower_count))")\
        .eq("project_id", project_id)\
        .execute()

    # Organize by account
    accounts_data = defaultdict(lambda: {
        "username": None,
        "display_name": None,
        "follower_count": 0,
        "posts": []
    })

    for item in posts_response.data:
        post = item.get("posts")
        if post and post.get("accounts"):
            account = post["accounts"]
            account_id = account["id"]

            if accounts_data[account_id]["username"] is None:
                accounts_data[account_id]["username"] = account["platform_username"]
                accounts_data[account_id]["display_name"] = account.get("display_name", "")
                accounts_data[account_id]["follower_count"] = account.get("follower_count", 0)

            accounts_data[account_id]["posts"].append({
                "posted_at": post.get("posted_at"),
                "views": post.get("views", 0)
            })

    now = datetime.utcnow()
    seven_days_ago = now - timedelta(days=7)

    print(f"Total accounts: {len(accounts_data)}")
    print()

    # Track filtering
    passed_recent = []
    passed_frequency = []
    passed_views = []
    passed_all = []

    for account_id, data in accounts_data.items():
        username = data["username"]
        posts = data["posts"]

        if not posts:
            continue

        # Parse dates
        posts_with_dates = []
        for post in posts:
            if post["posted_at"]:
                try:
                    posted_at = datetime.fromisoformat(post["posted_at"].replace('Z', '+00:00'))
                    posts_with_dates.append({
                        "date": posted_at,
                        "views": post["views"]
                    })
                except:
                    pass

        if not posts_with_dates:
            continue

        posts_with_dates.sort(key=lambda x: x["date"])

        # Filter 1: Recent post (last 7 days)
        most_recent_post = posts_with_dates[-1]["date"].replace(tzinfo=None)
        has_recent_post = most_recent_post >= seven_days_ago
        days_since = (now - most_recent_post).days

        if has_recent_post:
            passed_recent.append({
                "username": username,
                "followers": data["follower_count"],
                "days_since": days_since
            })

        # Filter 2: Posting frequency
        oldest_post = posts_with_dates[0]["date"].replace(tzinfo=None)
        time_span = (most_recent_post - oldest_post).days

        if time_span == 0:
            posts_per_week = len(posts_with_dates)
        else:
            posts_per_week = (len(posts_with_dates) / time_span) * 7

        if posts_per_week >= 5:
            passed_frequency.append({
                "username": username,
                "followers": data["follower_count"],
                "posts_per_week": posts_per_week,
                "days_since": days_since
            })

        # Filter 3: Views stable/growing
        all_views = [p["views"] for p in posts_with_dates]
        avg_views = statistics.mean(all_views)

        recent_count = max(1, len(posts_with_dates) // 3)
        recent_views = [p["views"] for p in posts_with_dates[-recent_count:]]
        avg_recent_views = statistics.mean(recent_views)

        view_health_ratio = avg_recent_views / avg_views if avg_views > 0 else 0
        views_stable = view_health_ratio >= 0.8

        if views_stable:
            passed_views.append({
                "username": username,
                "followers": data["follower_count"],
                "view_ratio": view_health_ratio,
                "days_since": days_since
            })

        # All three
        if has_recent_post and posts_per_week >= 5 and views_stable:
            passed_all.append({
                "username": username,
                "followers": data["follower_count"],
                "posts_per_week": posts_per_week,
                "days_since": days_since,
                "view_ratio": view_health_ratio
            })

    print("=" * 80)
    print("FILTER BREAKDOWN")
    print("=" * 80)
    print()
    print(f"Starting accounts: {len(accounts_data)}")
    print()
    print(f"✓ Posted within last 7 days: {len(passed_recent)} accounts")
    print(f"✓ Posting >= 5 times/week: {len(passed_frequency)} accounts")
    print(f"✓ Views stable/growing: {len(passed_views)} accounts")
    print()
    print(f"✓✓✓ Passed ALL criteria: {len(passed_all)} accounts")
    print()

    # Show who passed what
    print("=" * 80)
    print("ACCOUNTS THAT POSTED RECENTLY (last 7 days)")
    print("=" * 80)
    passed_recent.sort(key=lambda x: x["followers"], reverse=True)
    for i, acc in enumerate(passed_recent[:10], 1):
        print(f"{i}. @{acc['username']} ({acc['followers']:,} followers) - {acc['days_since']} days ago")
    if len(passed_recent) > 10:
        print(f"... and {len(passed_recent) - 10} more")
    print()

    print("=" * 80)
    print("ACCOUNTS WITH HIGH FREQUENCY (>=5 posts/week)")
    print("=" * 80)
    passed_frequency.sort(key=lambda x: x["posts_per_week"], reverse=True)
    for i, acc in enumerate(passed_frequency[:10], 1):
        print(f"{i}. @{acc['username']} - {acc['posts_per_week']:.1f} posts/week ({acc['followers']:,} followers)")
    if len(passed_frequency) > 10:
        print(f"... and {len(passed_frequency) - 10} more")
    print()

    print("=" * 80)
    print("ACCOUNTS WITH STABLE/GROWING VIEWS")
    print("=" * 80)
    passed_views.sort(key=lambda x: x["view_ratio"], reverse=True)
    for i, acc in enumerate(passed_views[:10], 1):
        print(f"{i}. @{acc['username']} - {acc['view_ratio']:.0%} of avg ({acc['followers']:,} followers)")
    if len(passed_views) > 10:
        print(f"... and {len(passed_views) - 10} more")

if __name__ == "__main__":
    analyze_with_breakdown()
