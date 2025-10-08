from viraltracker.core.database import get_supabase_client
import json

# Get Supabase client
supabase = get_supabase_client()

# Get Wonder Paws project ID
project_result = supabase.table("projects").select("id").eq("slug", "wonder-paws-tiktok").execute()
project_id = project_result.data[0]['id']

# Get posts for this project
project_posts = supabase.table("project_posts").select("post_id").eq("project_id", project_id).execute()
post_ids = [p['post_id'] for p in project_posts.data]

# Get video analyses for these posts
analyses_result = supabase.table("video_analysis")\
    .select("*, posts(post_url, caption, views, accounts(platform_username))")\
    .in_("post_id", post_ids)\
    .execute()

analyses = analyses_result.data

print(f"WONDER PAWS - TIKTOK VIRAL ANALYSIS RESULTS")
print(f"Found {len(analyses)} video analyses\n")
print("="*100)

for i, analysis in enumerate(analyses, 1):
    post = analysis['posts']
    username = post['accounts']['platform_username']
    
    print(f"\n{'='*100}")
    print(f"VIDEO {i}: @{username}")
    print(f"{'='*100}")
    print(f"URL: {post['post_url']}")
    print(f"Views: {post['views']:,}")
    print(f"Caption: {post['caption']}")
    print(f"\n{'-'*100}")
    print(f"FULL ANALYSIS")
    print(f"{'-'*100}\n")
    
    # Hook Analysis
    if analysis.get('hook_transcript'):
        print("═══ HOOK TRANSCRIPT ═══")
        print(analysis['hook_transcript'])
        print()
    
    if analysis.get('hook_visual_storyboard'):
        print("═══ HOOK VISUAL STORYBOARD ═══")
        hook_visual = analysis['hook_visual_storyboard']
        if isinstance(hook_visual, dict):
            print(json.dumps(hook_visual, indent=2))
        print()
    
    if analysis.get('hook_type'):
        print(f"═══ HOOK TYPE ═══")
        print(f"{analysis['hook_type']}")
        print()
    
    # Full Transcript
    if analysis.get('transcript'):
        print("═══ FULL TRANSCRIPT ═══")
        transcript = analysis['transcript']
        if isinstance(transcript, dict):
            print(json.dumps(transcript, indent=2))
        print()
    
    # Text Overlays
    if analysis.get('text_overlays'):
        print("═══ TEXT OVERLAYS ═══")
        overlays = analysis['text_overlays']
        if isinstance(overlays, dict):
            print(json.dumps(overlays, indent=2))
        print()
    
    # Storyboard
    if analysis.get('storyboard'):
        print("═══ VISUAL STORYBOARD ═══")
        storyboard = analysis['storyboard']
        if isinstance(storyboard, dict):
            print(json.dumps(storyboard, indent=2))
        print()
    
    # Key Moments
    if analysis.get('key_moments'):
        print("═══ KEY MOMENTS ═══")
        moments = analysis['key_moments']
        if isinstance(moments, dict):
            print(json.dumps(moments, indent=2))
        print()
    
    # Viral Factors
    if analysis.get('viral_factors'):
        print("═══ VIRAL FACTORS ═══")
        viral = analysis['viral_factors']
        if isinstance(viral, dict):
            for key, value in viral.items():
                print(f"  • {key}: {value}")
        print()
    
    # Viral Explanation
    if analysis.get('viral_explanation'):
        print("═══ WHY IT WENT VIRAL ═══")
        print(analysis['viral_explanation'])
        print()
    
    # Improvement Suggestions
    if analysis.get('improvement_suggestions'):
        print("═══ IMPROVEMENT SUGGESTIONS ═══")
        print(analysis['improvement_suggestions'])
        print()

print(f"\n\n{'='*100}")
print("PRODUCT ADAPTATIONS FOR WONDER PAWS COLLAGEN 3X DROPS")
print(f"{'='*100}\n")

# Get product adaptations for Wonder Paws
product_result = supabase.table("products").select("id").eq("slug", "collagen-3x-drops").execute()
product_id = product_result.data[0]['id']

adaptations_result = supabase.table("product_adaptations")\
    .select("*, posts(post_url, caption, views, accounts(platform_username)), products(name)")\
    .eq("product_id", product_id)\
    .execute()

adaptations = adaptations_result.data

for i, adapt in enumerate(adaptations, 1):
    post = adapt['posts']
    product = adapt['products']
    username = post['accounts']['platform_username']
    
    print(f"\n{'='*100}")
    print(f"ADAPTATION {i}: @{username} → {product['name']}")
    print(f"{'='*100}")
    print(f"URL: {post['post_url']}")
    print(f"Views: {post['views']:,}")
    print(f"Caption: {post['caption']}")
    
    print(f"\n═══ ADAPTATION SCORES ═══")
    print(f"  • Hook Relevance: {adapt.get('hook_relevance_score', 'N/A')}/10")
    print(f"  • Audience Match: {adapt.get('audience_match_score', 'N/A')}/10")
    print(f"  • Transition Ease: {adapt.get('transition_ease_score', 'N/A')}/10")
    print(f"  • Viral Replicability: {adapt.get('viral_replicability_score', 'N/A')}/10")
    print(f"  • OVERALL SCORE: {adapt.get('overall_score', 'N/A')}/10")
    
    if adapt.get('adapted_hook'):
        print(f"\n═══ ADAPTED HOOK ═══")
        print(adapt['adapted_hook'])
    
    if adapt.get('adapted_script'):
        print(f"\n═══ ADAPTED SCRIPT ═══")
        print(adapt['adapted_script'])
    
    if adapt.get('storyboard'):
        print(f"\n═══ ADAPTATION STORYBOARD ═══")
        storyboard = adapt['storyboard']
        if isinstance(storyboard, dict):
            print(json.dumps(storyboard, indent=2))
    
    if adapt.get('text_overlays'):
        print(f"\n═══ ADAPTATION TEXT OVERLAYS ═══")
        overlays = adapt['text_overlays']
        if isinstance(overlays, dict):
            print(json.dumps(overlays, indent=2))
    
    if adapt.get('transition_strategy'):
        print(f"\n═══ TRANSITION STRATEGY ═══")
        print(adapt['transition_strategy'])
    
    if adapt.get('best_use_case'):
        print(f"\n═══ BEST USE CASE ═══")
        print(adapt['best_use_case'])
    
    if adapt.get('production_notes'):
        print(f"\n═══ PRODUCTION NOTES ═══")
        print(adapt['production_notes'])
    
    print()

print(f"\n{'='*100}")
print("END OF WONDER PAWS ANALYSIS")
print(f"{'='*100}\n")

