"""
Analyze masculinity-tiktok accounts for activity and engagement trends.

Filters accounts based on:
- Posted within last 7 days
- Posting at least 5 times per week
- Views not declining (recent posts maintain or exceed average)
"""
from datetime import datetime, timedelta
from viraltracker.core.config import Config
from supabase import create_client, Client
from collections import defaultdict
import statistics

# Validate and initialize Supabase client
Config.validate()
supabase: Client = create_client(Config.SUPABASE_URL, Config.SUPABASE_SERVICE_KEY)

def analyze_accounts():
    """Analyze accounts for activity and engagement trends."""

    # Get the project ID
    project_response = supabase.table("projects").select("id, name").eq("slug", "masculinity-tiktok").execute()

    if not project_response.data:
        print("Project 'masculinity-tiktok' not found")
        return

    project = project_response.data[0]
    project_id = project["id"]

    print(f"Project: {project['name']} (ID: {project_id})")
    print()

    # Get all posts in the project with their account info
    posts_response = supabase.table("project_posts")\
        .select("post_id, posts(id, account_id, posted_at, views, accounts(id, platform_username, display_name, follower_count))")\
        .eq("project_id", project_id)\
        .execute()

    if not posts_response.data:
        print("No posts found in this project")
        return

    # Organize posts by account
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

            # Store account metadata
            if accounts_data[account_id]["username"] is None:
                accounts_data[account_id]["username"] = account["platform_username"]
                accounts_data[account_id]["display_name"] = account.get("display_name", "")
                accounts_data[account_id]["follower_count"] = account.get("follower_count", 0)

            # Store post data
            accounts_data[account_id]["posts"].append({
                "posted_at": post.get("posted_at"),
                "views": post.get("views", 0)
            })

    # Current time for calculations
    now = datetime.utcnow()
    seven_days_ago = now - timedelta(days=7)

    print(f"Analyzing {len(accounts_data)} accounts...")
    print(f"Criteria:")
    print(f"  - Posted within last 7 days")
    print(f"  - Posting frequency >= 3 posts/week")
    print(f"  - Views not declining (recent posts >= 80% of average)")
    print()

    qualifying_accounts = []

    for account_id, data in accounts_data.items():
        username = data["username"]
        posts = data["posts"]

        if not posts:
            continue

        # Parse dates and sort by date
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

        # Check 1: Posted within last 7 days
        most_recent_post = posts_with_dates[-1]["date"].replace(tzinfo=None)
        has_recent_post = most_recent_post >= seven_days_ago

        if not has_recent_post:
            continue

        # Check 2: Calculate posting frequency (posts per week)
        oldest_post = posts_with_dates[0]["date"].replace(tzinfo=None)
        time_span = (most_recent_post - oldest_post).days

        if time_span == 0:
            posts_per_week = len(posts_with_dates)
        else:
            posts_per_week = (len(posts_with_dates) / time_span) * 7

        if posts_per_week < 3:
            continue

        # Check 3: Views not declining
        # Compare average views of recent 1/3 of posts vs overall average
        all_views = [p["views"] for p in posts_with_dates]
        avg_views = statistics.mean(all_views)

        # Get recent third of posts
        recent_count = max(1, len(posts_with_dates) // 3)
        recent_views = [p["views"] for p in posts_with_dates[-recent_count:]]
        avg_recent_views = statistics.mean(recent_views)

        # Recent views should be at least 80% of average (allowing for some variance)
        view_health_ratio = avg_recent_views / avg_views if avg_views > 0 else 0
        views_stable = view_health_ratio >= 0.8

        if not views_stable:
            continue

        # Account qualifies!
        days_since_last_post = (now - most_recent_post).days

        qualifying_accounts.append({
            "username": username,
            "display_name": data["display_name"],
            "follower_count": data["follower_count"],
            "total_posts": len(posts_with_dates),
            "posts_per_week": posts_per_week,
            "days_since_last_post": days_since_last_post,
            "avg_views": int(avg_views),
            "avg_recent_views": int(avg_recent_views),
            "view_health_ratio": view_health_ratio,
            "time_span_days": time_span
        })

    # Sort by follower count
    qualifying_accounts.sort(key=lambda x: x["follower_count"], reverse=True)

    print("=" * 100)
    print(f"QUALIFYING ACCOUNTS: {len(qualifying_accounts)}/{len(accounts_data)}")
    print("=" * 100)
    print()

    if not qualifying_accounts:
        print("No accounts meet all criteria.")
        return

    for i, account in enumerate(qualifying_accounts, 1):
        print(f"{i}. @{account['username']}")
        print(f"   Display Name: {account['display_name']}")
        print(f"   Followers: {account['follower_count']:,}")
        print(f"   Posts Analyzed: {account['total_posts']} over {account['time_span_days']} days")
        print(f"   Posting Frequency: {account['posts_per_week']:.1f} posts/week")
        print(f"   Last Posted: {account['days_since_last_post']} days ago")
        print(f"   Avg Views: {account['avg_views']:,}")
        print(f"   Recent Views Avg: {account['avg_recent_views']:,} ({account['view_health_ratio']:.0%} of overall avg)")
        print()

    # Export to file
    output_file = "qualifying_masculinity_accounts.txt"
    with open(output_file, 'w') as f:
        f.write("Qualifying Masculinity TikTok Accounts\n")
        f.write("=" * 100 + "\n")
        f.write(f"Criteria: Posted in last 7 days, >=3 posts/week, views stable/growing\n")
        f.write(f"Generated: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\n")
        f.write("=" * 100 + "\n\n")

        for i, account in enumerate(qualifying_accounts, 1):
            f.write(f"{i}. @{account['username']}\n")
            f.write(f"   Display Name: {account['display_name']}\n")
            f.write(f"   Followers: {account['follower_count']:,}\n")
            f.write(f"   Posts: {account['total_posts']} ({account['posts_per_week']:.1f}/week)\n")
            f.write(f"   Last Posted: {account['days_since_last_post']} days ago\n")
            f.write(f"   Avg Views: {account['avg_views']:,} (recent: {account['avg_recent_views']:,})\n")
            f.write(f"   URL: https://www.tiktok.com/@{account['username']}\n")
            f.write("\n")

    print(f"✅ Results exported to: {output_file}")

if __name__ == "__main__":
    analyze_accounts()
