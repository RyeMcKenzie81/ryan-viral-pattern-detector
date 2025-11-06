"""
Export unique accounts from masculinity-tiktok project to a file.
"""
from viraltracker.core.config import Config
from supabase import create_client, Client

# Validate and initialize Supabase client
Config.validate()
supabase: Client = create_client(Config.SUPABASE_URL, Config.SUPABASE_SERVICE_KEY)

def export_accounts():
    """Export unique accounts to a text file."""

    # Get the project ID
    project_response = supabase.table("projects").select("id, name").eq("slug", "masculinity-tiktok").execute()

    if not project_response.data:
        print("Project 'masculinity-tiktok' not found")
        return

    project = project_response.data[0]
    project_id = project["id"]

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

    # Sort by follower count descending
    sorted_accounts = sorted(accounts.items(), key=lambda x: x[1]["follower_count"], reverse=True)

    # Write to file
    output_file = "masculinity_accounts.txt"
    with open(output_file, 'w') as f:
        for account_id, data in sorted_accounts:
            username = data["username"]
            f.write(f"{username}\n")

    print(f"Exported {len(accounts)} accounts to {output_file}")
    print(f"Sorted by follower count (highest to lowest)")

if __name__ == "__main__":
    export_accounts()
