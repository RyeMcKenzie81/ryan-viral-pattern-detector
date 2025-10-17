#!/usr/bin/env python3
"""Link recently scraped posts to wonder-paws-tiktok project"""
from viraltracker.core.config import Config
from supabase import create_client
from datetime import datetime, timezone, timedelta

supabase = create_client(Config.SUPABASE_URL, Config.SUPABASE_SERVICE_KEY)

# Get project ID
project_response = supabase.table('projects').select('id').eq('slug', 'wonder-paws-tiktok').execute()
if not project_response.data:
    print("❌ Project 'wonder-paws-tiktok' not found")
    exit(1)

project_id = project_response.data[0]['id']
print(f"Project ID: {project_id}")

# Get existing posts in project
existing_project_posts = supabase.table('project_posts').select('post_id').eq('project_id', project_id).execute()
existing_post_ids = {p['post_id'] for p in existing_project_posts.data}
print(f"Existing posts in project: {len(existing_post_ids)}")

# Get TikTok platform ID
platform_response = supabase.table('platforms').select('id').eq('slug', 'tiktok').execute()
platform_id = platform_response.data[0]['id']

# Find posts that were scraped in the last 24 hours and not yet in project
# These are the posts from the 6 search term scrapes
cutoff_time = datetime.now(timezone.utc) - timedelta(hours=24)

print(f"\nSearching for posts scraped after: {cutoff_time.isoformat()}")

# Get all TikTok posts with import_source='scrape' from last 24 hours
all_posts = supabase.table('posts')\
    .select('id,post_url,views,caption,created_at,import_source,accounts(platform_username,follower_count)')\
    .eq('platform_id', platform_id)\
    .eq('import_source', 'scrape')\
    .gte('created_at', cutoff_time.isoformat())\
    .execute()

print(f"Total TikTok posts scraped in last 24h: {len(all_posts.data)}")

# Filter to posts not already in project
posts_to_link = [p for p in all_posts.data if p['id'] not in existing_post_ids]
print(f"Posts NOT in project: {len(posts_to_link)}")

if not posts_to_link:
    print("\n✅ No new posts to link")
    exit(0)

# Show sample of posts
print("\nSample of posts to be linked:")
for i, post in enumerate(posts_to_link[:5], 1):
    username = post['accounts']['platform_username'] if post['accounts'] else 'unknown'
    views = post['views'] or 0
    caption_preview = (post['caption'] or '')[:60]
    print(f"  {i}. @{username} - {views:,} views")
    print(f"     {caption_preview}...")
    print(f"     {post['post_url']}")

# Ask for confirmation
print(f"\n⚠️  About to link {len(posts_to_link)} posts to wonder-paws-tiktok project")
response = input("Continue? (y/n): ")

if response.lower() != 'y':
    print("❌ Aborted")
    exit(0)

# Link posts to project
print("\n💾 Linking posts to project...")
project_posts_data = [
    {
        'project_id': project_id,
        'post_id': post['id']
    }
    for post in posts_to_link
]

# Batch upsert
result = supabase.table('project_posts').upsert(
    project_posts_data,
    on_conflict='project_id,post_id'
).execute()

print(f"✅ Successfully linked {len(posts_to_link)} posts to project")

# Verify
new_count_response = supabase.table('project_posts').select('post_id', count='exact').eq('project_id', project_id).execute()
print(f"\n📊 Project now has {new_count_response.count} total posts (was {len(existing_post_ids)})")
print(f"   Added: {new_count_response.count - len(existing_post_ids)} posts")

print("\n💡 Next steps:")
print("   1. Process videos: echo 'y' | vt process videos --project wonder-paws-tiktok")
print("   2. Analyze with Gemini: echo 'y' | vt analyze videos --project wonder-paws-tiktok --gemini-model models/gemini-2.5-pro")
print("   3. Run correlation: python analyze_v1_1_0_results.py")
