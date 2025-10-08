from viraltracker.core.database import get_supabase_client

supabase = get_supabase_client()

# Get Wonder Paws project
project_result = supabase.table("projects").select("id").eq("slug", "wonder-paws-tiktok").execute()
project_id = project_result.data[0]['id']

# Get TikTok post IDs
project_posts = supabase.table("project_posts").select("post_id").eq("project_id", project_id).execute()
post_ids = [p['post_id'] for p in project_posts.data]

print(f"Deleting analyses for {len(post_ids)} posts...")

# Delete existing analyses
result = supabase.table("video_analysis").delete().in_("post_id", post_ids).execute()
print(f"✓ Deleted analyses")

# Delete product adaptations  
adapt_result = supabase.table("product_adaptations").delete().in_("post_id", post_ids).execute()
print(f"✓ Deleted product adaptations")

print("\n✓ Ready to re-analyze with models/gemini-flash-latest!")

