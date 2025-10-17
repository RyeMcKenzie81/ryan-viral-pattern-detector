#!/usr/bin/env python3
"""Inspect platform_specific_metrics to see what fields exist"""
import json
from viraltracker.core.config import Config
from supabase import create_client

# Initialize Supabase
supabase = create_client(Config.SUPABASE_URL, Config.SUPABASE_SERVICE_KEY)

# Get project
project_response = supabase.table('projects').select('id').eq('slug', 'wonder-paws-tiktok').execute()
project_id = project_response.data[0]['id']

# Get posts
posts_response = supabase.table('project_posts').select('post_id').eq('project_id', project_id).execute()
post_ids = [p['post_id'] for p in posts_response.data]

# Get one v1.1.0 analysis as sample
analysis = supabase.table('video_analysis')\
    .select('platform_specific_metrics,analysis_model,analysis_version')\
    .in_('post_id', post_ids)\
    .eq('analysis_version', 'vid-1.1.0')\
    .limit(1)\
    .execute()

if analysis.data:
    sample = analysis.data[0]
    print(f"Model: {sample['analysis_model']}")
    print(f"Version: {sample['analysis_version']}")
    print(f"\nplatform_specific_metrics type: {type(sample['platform_specific_metrics'])}")

    psm = sample['platform_specific_metrics']
    if isinstance(psm, str):
        psm = json.loads(psm)

    print(f"\nKeys in platform_specific_metrics:")
    for key in sorted(psm.keys()):
        value = psm[key]
        print(f"  {key}: {value} (type: {type(value).__name__})")
else:
    print("No v1.1.0 analyses found")
