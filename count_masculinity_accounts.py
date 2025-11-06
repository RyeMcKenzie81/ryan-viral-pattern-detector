"""
Count unique accounts discovered in the masculinity-tiktok project.
"""
from viraltracker.core.config import Config
from supabase import create_client, Client

# Validate and initialize Supabase client
Config.validate()
supabase: Client = create_client(Config.SUPABASE_URL, Config.SUPABASE_SERVICE_KEY)

def count_unique_accounts():
    """Count unique accounts in the masculinity-tiktok project."""

    # First, get the project ID
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
        .select("post_id, posts(id, account_id, accounts(id, platform_username, display_name, follower_count))")\
        .eq("project_id", project_id)\
        .execute()

    if not posts_response.data:
        print("No posts found in this project")
        return

    # Extract unique accounts
    accounts = {}
    for item in posts_response.data:
        post = item.get("posts")
        if post:
            account = post.get("accounts")
            if account:
                account_id = account["id"]
                if account_id not in accounts:
                    accounts[account_id] = {
                        "username": account["platform_username"],
                        "display_name": account.get("display_name", ""),
                        "follower_count": account.get("follower_count", 0)
                    }

    # Count total posts
    total_posts = len(posts_response.data)

    # Print results
    print(f"Total unique accounts: {len(accounts)}")
    print(f"Total posts: {total_posts}")
    print(f"Average posts per account: {total_posts / len(accounts):.1f}")
    print()

    # Show top 10 accounts by follower count
    sorted_accounts = sorted(accounts.items(), key=lambda x: x[1]["follower_count"], reverse=True)

    print("Top 10 accounts by follower count:")
    print("-" * 80)
    for i, (account_id, data) in enumerate(sorted_accounts[:10], 1):
        username = data["username"]
        display_name = data["display_name"]
        followers = data["follower_count"]
        print(f"{i:2}. @{username:<25} {followers:>10,} followers  {display_name}")

    print()

if __name__ == "__main__":
    count_unique_accounts()
