"""
Search post captions for contact information (emails, Instagram handles, etc.)
"""
from viraltracker.core.config import Config
from supabase import create_client, Client
from collections import defaultdict
import re

Config.validate()
supabase: Client = create_client(Config.SUPABASE_URL, Config.SUPABASE_SERVICE_KEY)

def find_contact_info():
    """Search captions for contact information."""

    # Get the project
    project_response = supabase.table("projects").select("id, name").eq("slug", "masculinity-tiktok").execute()
    project = project_response.data[0]
    project_id = project["id"]

    # Get all posts with captions
    posts_response = supabase.table("project_posts")\
        .select("post_id, posts(id, caption, accounts(platform_username, display_name, follower_count))")\
        .eq("project_id", project_id)\
        .execute()

    # Contact info patterns
    email_pattern = r'\b[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Z|a-z]{2,}\b'
    instagram_pattern = r'(?:instagram\.com/|@)([a-zA-Z0-9._]+)'
    business_keywords = ['contact', 'email', 'dm', 'business inquiries', 'collab', 'sponsorship']

    # Organize by account
    accounts_with_contact = defaultdict(lambda: {
        "username": None,
        "display_name": None,
        "follower_count": 0,
        "contact_info": {
            "emails": set(),
            "instagram": set(),
            "business_mentions": []
        }
    })

    for item in posts_response.data:
        post = item.get("posts")
        if post and post.get("accounts"):
            account = post["accounts"]
            account_id = account["platform_username"]
            caption = post.get("caption", "")

            # Store account info
            if accounts_with_contact[account_id]["username"] is None:
                accounts_with_contact[account_id]["username"] = account["platform_username"]
                accounts_with_contact[account_id]["display_name"] = account.get("display_name", "")
                accounts_with_contact[account_id]["follower_count"] = account.get("follower_count", 0)

            # Search for emails
            emails = re.findall(email_pattern, caption)
            if emails:
                accounts_with_contact[account_id]["contact_info"]["emails"].update(emails)

            # Search for Instagram handles
            ig_handles = re.findall(instagram_pattern, caption, re.IGNORECASE)
            if ig_handles:
                accounts_with_contact[account_id]["contact_info"]["instagram"].update(ig_handles)

            # Search for business keywords
            caption_lower = caption.lower()
            for keyword in business_keywords:
                if keyword in caption_lower:
                    accounts_with_contact[account_id]["contact_info"]["business_mentions"].append(caption[:200])
                    break

    print("=" * 100)
    print("CONTACT INFORMATION FOUND IN POST CAPTIONS")
    print("=" * 100)
    print()

    # Filter to accounts with any contact info
    accounts_with_info = []
    for username, data in accounts_with_contact.items():
        contact = data["contact_info"]
        if contact["emails"] or contact["instagram"] or contact["business_mentions"]:
            accounts_with_info.append({
                "username": data["username"],
                "display_name": data["display_name"],
                "follower_count": data["follower_count"],
                "emails": list(contact["emails"]),
                "instagram": list(contact["instagram"]),
                "business_mentions": len(contact["business_mentions"])
            })

    # Sort by follower count
    accounts_with_info.sort(key=lambda x: x["follower_count"], reverse=True)

    if not accounts_with_info:
        print("❌ No contact information found in any post captions.")
        print()
        print("This is expected because:")
        print("- TikTok creators typically put contact info in their profile bio, not post captions")
        print("- The scraper didn't capture profile bios (only post data)")
        print()
        print("To get contact info, you would need to:")
        print("1. Visit each TikTok profile manually")
        print("2. Check their bio for email/business contact")
        print("3. Check their link-in-bio (often links to Instagram/Linktree)")
        return

    print(f"Found {len(accounts_with_info)} accounts with contact info in captions:")
    print()

    for i, acc in enumerate(accounts_with_info, 1):
        print(f"{i}. @{acc['username']}")
        print(f"   Display Name: {acc['display_name']}")
        print(f"   Followers: {acc['follower_count']:,}")

        if acc['emails']:
            print(f"   Emails: {', '.join(acc['emails'])}")

        if acc['instagram']:
            print(f"   Instagram: {', '.join(acc['instagram'])}")

        if acc['business_mentions']:
            print(f"   Business mentions: {acc['business_mentions']} posts mention contact/collab")

        print()

if __name__ == "__main__":
    find_contact_info()
