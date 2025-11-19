"""
Analyze masculinity accounts to filter out meme/edit accounts.

Identifies meme accounts by:
- Captions containing edit/meme keywords
- Hashtags like #edit, #meme, #fyp
- Low caption-to-post ratios (reposts with minimal captions)
- Username patterns (edit, meme, etc.)
"""
from datetime import datetime
from viraltracker.core.config import Config
from supabase import create_client, Client
from collections import defaultdict, Counter
import re

Config.validate()
supabase: Client = create_client(Config.SUPABASE_URL, Config.SUPABASE_SERVICE_KEY)

def analyze_content_patterns():
    """Analyze qualifying accounts to identify meme/edit patterns."""

    # Get the project
    project_response = supabase.table("projects").select("id, name").eq("slug", "masculinity-tiktok").execute()
    project = project_response.data[0]
    project_id = project["id"]

    # Get all posts with captions
    posts_response = supabase.table("project_posts")\
        .select("post_id, posts(id, account_id, caption, views, likes, comments, accounts(id, platform_username, display_name, follower_count))")\
        .eq("project_id", project_id)\
        .execute()

    # Organize by account with caption analysis
    accounts_data = defaultdict(lambda: {
        "username": None,
        "display_name": None,
        "follower_count": 0,
        "posts": [],
        "meme_indicators": {
            "edit_keywords": 0,
            "meme_keywords": 0,
            "short_captions": 0,
            "edit_hashtags": 0,
            "username_is_edit": False
        }
    })

    # Meme/edit detection patterns
    edit_keywords = [
        r'\bedit\b', r'\bedits\b', r'\bediting\b', r'\beditor\b',
        r'\bae\b', r'\bamv\b', r'\bclips\b', r'\bcompilation\b',
        r'\brepost\b', r'\bvideo\s*edit', r'\bquick\s*edit'
    ]

    meme_keywords = [
        r'\bmeme\b', r'\bmemes\b', r'\bshitpost\b', r'\bfunny\b',
        r'\bviral\b', r'\btrending\b', r'\bfyp\b', r'\bforyou\b'
    ]

    edit_hashtags = [
        '#edit', '#edits', '#editing', '#editor', '#videoeditor',
        '#ae', '#amv', '#clips', '#meme', '#memes', '#fyp'
    ]

    for item in posts_response.data:
        post = item.get("posts")
        if post and post.get("accounts"):
            account = post["accounts"]
            account_id = account["id"]
            username = account["platform_username"]

            # Store account metadata
            if accounts_data[account_id]["username"] is None:
                accounts_data[account_id]["username"] = username
                accounts_data[account_id]["display_name"] = account.get("display_name", "")
                accounts_data[account_id]["follower_count"] = account.get("follower_count", 0)

                # Check username for edit/meme patterns
                username_lower = username.lower()
                if any(word in username_lower for word in ['edit', 'meme', 'clips', 'viral', 'fyp']):
                    accounts_data[account_id]["meme_indicators"]["username_is_edit"] = True

            # Analyze caption
            caption = post.get("caption", "")
            caption_lower = caption.lower()

            # Count edit keywords
            for pattern in edit_keywords:
                if re.search(pattern, caption_lower):
                    accounts_data[account_id]["meme_indicators"]["edit_keywords"] += 1
                    break

            # Count meme keywords
            for pattern in meme_keywords:
                if re.search(pattern, caption_lower):
                    accounts_data[account_id]["meme_indicators"]["meme_keywords"] += 1
                    break

            # Check for short captions (likely reposts)
            if len(caption.strip()) < 20:
                accounts_data[account_id]["meme_indicators"]["short_captions"] += 1

            # Count edit hashtags
            for hashtag in edit_hashtags:
                if hashtag in caption_lower:
                    accounts_data[account_id]["meme_indicators"]["edit_hashtags"] += 1
                    break

            # Store post data
            accounts_data[account_id]["posts"].append({
                "caption": caption,
                "views": post.get("views", 0),
                "likes": post.get("likes", 0),
                "comments": post.get("comments", 0)
            })

    print("=" * 100)
    print("MEME/EDIT ACCOUNT ANALYSIS")
    print("=" * 100)
    print()

    # Classify accounts
    meme_accounts = []
    original_content_accounts = []

    for account_id, data in accounts_data.items():
        username = data["username"]
        indicators = data["meme_indicators"]
        total_posts = len(data["posts"])

        if total_posts == 0:
            continue

        # Calculate meme score
        meme_score = 0
        reasons = []

        # Username contains edit/meme
        if indicators["username_is_edit"]:
            meme_score += 3
            reasons.append("Username contains edit/meme keywords")

        # High percentage of posts with edit keywords
        edit_ratio = indicators["edit_keywords"] / total_posts
        if edit_ratio > 0.3:
            meme_score += 2
            reasons.append(f"{edit_ratio:.0%} of posts mention editing")

        # High percentage of posts with meme keywords
        meme_ratio = indicators["meme_keywords"] / total_posts
        if meme_ratio > 0.4:
            meme_score += 2
            reasons.append(f"{meme_ratio:.0%} of posts mention memes/viral/fyp")

        # High percentage of short captions (reposts)
        short_ratio = indicators["short_captions"] / total_posts
        if short_ratio > 0.5:
            meme_score += 1
            reasons.append(f"{short_ratio:.0%} of posts have very short captions")

        # Edit hashtags present
        hashtag_ratio = indicators["edit_hashtags"] / total_posts
        if hashtag_ratio > 0.3:
            meme_score += 2
            reasons.append(f"{hashtag_ratio:.0%} of posts use edit/meme hashtags")

        account_info = {
            "username": username,
            "display_name": data["display_name"],
            "follower_count": data["follower_count"],
            "total_posts": total_posts,
            "meme_score": meme_score,
            "reasons": reasons,
            "indicators": indicators
        }

        # Classify: meme_score >= 3 is likely a meme/edit account
        if meme_score >= 3:
            meme_accounts.append(account_info)
        else:
            original_content_accounts.append(account_info)

    # Sort by meme score (descending) and follower count
    meme_accounts.sort(key=lambda x: (x["meme_score"], x["follower_count"]), reverse=True)
    original_content_accounts.sort(key=lambda x: x["follower_count"], reverse=True)

    print("=" * 100)
    print(f"MEME/EDIT ACCOUNTS: {len(meme_accounts)}")
    print("=" * 100)
    print()

    for i, acc in enumerate(meme_accounts, 1):
        print(f"{i}. @{acc['username']}")
        print(f"   Display Name: {acc['display_name']}")
        print(f"   Followers: {acc['follower_count']:,}")
        print(f"   Posts Analyzed: {acc['total_posts']}")
        print(f"   Meme Score: {acc['meme_score']}/10")
        print(f"   Reasons:")
        for reason in acc['reasons']:
            print(f"     - {reason}")
        print()

    print("=" * 100)
    print(f"ORIGINAL CONTENT ACCOUNTS: {len(original_content_accounts)}")
    print("=" * 100)
    print()

    for i, acc in enumerate(original_content_accounts, 1):
        print(f"{i}. @{acc['username']}")
        print(f"   Display Name: {acc['display_name']}")
        print(f"   Followers: {acc['follower_count']:,}")
        print(f"   Posts Analyzed: {acc['total_posts']}")
        print(f"   Meme Score: {acc['meme_score']}/10")
        if acc['reasons']:
            print(f"   Minor indicators:")
            for reason in acc['reasons']:
                print(f"     - {reason}")
        print()

    # Export original content accounts
    output_file = "original_masculinity_accounts.txt"
    with open(output_file, 'w') as f:
        f.write("Original Content Masculinity TikTok Accounts\n")
        f.write("=" * 100 + "\n")
        f.write(f"Filtered to remove meme/edit accounts\n")
        f.write(f"Generated: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\n")
        f.write("=" * 100 + "\n\n")

        for i, acc in enumerate(original_content_accounts, 1):
            f.write(f"{i}. @{acc['username']}\n")
            f.write(f"   Display Name: {acc['display_name']}\n")
            f.write(f"   Followers: {acc['follower_count']:,}\n")
            f.write(f"   Posts: {acc['total_posts']}\n")
            f.write(f"   URL: https://www.tiktok.com/@{acc['username']}\n")
            f.write("\n")

    print(f"✅ Original content accounts exported to: {output_file}")

if __name__ == "__main__":
    analyze_content_patterns()
