#!/usr/bin/env python3
"""
Verify Hook Intelligence v1.2.0 analysis completion for wonder-paws-tiktok project.
"""

from supabase import create_client
import os
from dotenv import load_dotenv

load_dotenv()

# Initialize Supabase client
supabase = create_client(
    os.getenv("SUPABASE_URL"),
    os.getenv("SUPABASE_SERVICE_KEY")
)

# Get project ID
project_response = supabase.table("projects").select("id, name").eq("slug", "wonder-paws-tiktok").execute()
if not project_response.data:
    print("❌ Project not found")
    exit(1)

project_id = project_response.data[0]["id"]
project_name = project_response.data[0]["name"]

print(f"📊 Analysis Completion Report: {project_name}")
print("=" * 70)

# Get total project posts
project_posts_response = supabase.table("project_posts").select("post_id").eq("project_id", project_id).execute()
total_project_posts = len(project_posts_response.data)

# Get total videos with completed processing
processing_response = supabase.table("video_processing_log").select("post_id").eq("status", "completed").execute()
completed_videos = {row["post_id"] for row in processing_response.data}

# Filter to only project videos
project_post_ids = {row["post_id"] for row in project_posts_response.data}
project_completed_videos = completed_videos & project_post_ids

# Get total video analyses
analysis_response = supabase.table("video_analysis").select("post_id, analysis_version").execute()
all_analyses = {row["post_id"]: row["analysis_version"] for row in analysis_response.data}

# Filter to only project videos
project_analyses = {post_id: version for post_id, version in all_analyses.items() if post_id in project_post_ids}

# Count v1.2.0 analyses
v1_2_0_count = sum(1 for version in project_analyses.values() if version == "vid-1.2.0")

# Calculate stats
processing_success_rate = (len(project_completed_videos) / total_project_posts * 100) if total_project_posts > 0 else 0
analysis_success_rate = (len(project_analyses) / len(project_completed_videos) * 100) if len(project_completed_videos) > 0 else 0

print(f"\n📦 Project Posts: {total_project_posts}")
print(f"✅ Videos Processed: {len(project_completed_videos)} ({processing_success_rate:.1f}%)")
print(f"🤖 Videos Analyzed: {len(project_analyses)} ({analysis_success_rate:.1f}%)")
print(f"🎯 Hook Intelligence v1.2.0: {v1_2_0_count}")
print()

# Check for unanalyzed videos
unanalyzed = project_completed_videos - set(project_analyses.keys())
if unanalyzed:
    print(f"⚠️  Unanalyzed videos: {len(unanalyzed)}")
else:
    print("✨ All processed videos have been analyzed!")

print()
print("=" * 70)

# Success criteria
if processing_success_rate >= 95 and analysis_success_rate >= 95:
    print("✅ SUCCESS: >95% completion rate achieved on both processing and analysis!")
elif processing_success_rate >= 95:
    print("⚠️  Processing: ✅ >95% | Analysis: ⚠️  <95%")
elif analysis_success_rate >= 95:
    print("⚠️  Processing: ⚠️  <95% | Analysis: ✅ >95%")
else:
    print("❌ INCOMPLETE: <95% completion rate")

print()
print(f"📈 Total analyzed dataset size: n={len(project_analyses)}")
