#!/usr/bin/env python3
"""Delete Gemini Flash analyses to re-run with Gemini 2.5 Pro"""
from viraltracker.core.config import Config
from supabase import create_client

# Initialize Supabase
supabase = create_client(Config.SUPABASE_URL, Config.SUPABASE_SERVICE_KEY)

# Get project
project_response = supabase.table('projects').select('id,name').eq('slug', 'wonder-paws-tiktok').execute()
project_id = project_response.data[0]['id']
print(f"Project: {project_response.data[0]['name']} ({project_id})")

# Get all posts in project
posts_response = supabase.table('project_posts').select('post_id').eq('project_id', project_id).execute()
post_ids = [p['post_id'] for p in posts_response.data]
print(f"Total posts in project: {len(post_ids)}")

# Get all analyses for these posts
analyses = supabase.table('video_analysis').select('id,post_id,analysis_model,analysis_version').in_('post_id', post_ids).execute()

# Group by model
flash_analyses = [a for a in analyses.data if a.get('analysis_model') and 'flash' in a['analysis_model'].lower()]
pro_analyses = [a for a in analyses.data if a.get('analysis_model') and ('pro' in a['analysis_model'].lower() or '2.5' in a['analysis_model'])]

print(f"\nCurrent state:")
print(f"  Total analyses: {len(analyses.data)}")
print(f"  Gemini Flash analyses: {len(flash_analyses)}")
print(f"  Gemini 2.5 Pro analyses: {len(pro_analyses)}")

if flash_analyses:
    print(f"\nDeleting {len(flash_analyses)} Gemini Flash analyses...")
    flash_ids = [a['id'] for a in flash_analyses]

    # Delete in batches of 100
    batch_size = 100
    for i in range(0, len(flash_ids), batch_size):
        batch = flash_ids[i:i+batch_size]
        result = supabase.table('video_analysis').delete().in_('id', batch).execute()
        print(f"  Deleted batch {i//batch_size + 1}: {len(batch)} records")

    print(f"\n✅ Deleted {len(flash_analyses)} Flash analyses")
    print(f"✅ Ready to re-analyze all videos with Gemini 2.5 Pro")
else:
    print("\nNo Flash analyses found to delete")
