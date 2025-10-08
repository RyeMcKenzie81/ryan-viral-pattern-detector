from viraltracker.core.database import get_supabase_client
import json

# Get Supabase client
supabase = get_supabase_client()

# Get all video analyses for Wonder Paws project  
result = supabase.table("video_analysis")\
    .select("*, posts(post_url, caption, views, accounts(platform_username))")\
    .execute()

analyses = result.data

print(f"Found {len(analyses)} video analyses\n")
print("="*80)

for i, analysis in enumerate(analyses, 1):
    post = analysis['posts']
    username = post['accounts']['platform_username']
    
    print(f"\n{'='*80}")
    print(f"VIDEO {i}: @{username}")
    print(f"{'='*80}")
    print(f"URL: {post['post_url']}")
    print(f"Views: {post['views']:,}")
    print(f"Caption: {post['caption'][:150]}...")
    print(f"\n{'-'*80}")
    print(f"ANALYSIS")
    print(f"{'-'*80}\n")
    
    # Hook Analysis
    if analysis.get('hook_transcript'):
        print("HOOK TRANSCRIPT:")
        print(analysis['hook_transcript'])
        print()
    
    if analysis.get('hook_visual_storyboard'):
        print("HOOK VISUAL:")
        hook_visual = analysis['hook_visual_storyboard']
        if isinstance(hook_visual, dict):
            print(json.dumps(hook_visual, indent=2))
        else:
            print(hook_visual)
        print()
    
    if analysis.get('hook_type'):
        print(f"HOOK TYPE: {analysis['hook_type']}")
        print()
    
    # Viral Factors
    if analysis.get('viral_factors'):
        print("VIRAL FACTORS:")
        viral = analysis['viral_factors']
        if isinstance(viral, dict):
            for key, value in viral.items():
                print(f"  {key}: {value}")
        print()
    
    # Viral Explanation
    if analysis.get('viral_explanation'):
        print("WHY IT WENT VIRAL:")
        print(analysis['viral_explanation'])
        print()
    
    # Improvement Suggestions
    if analysis.get('improvement_suggestions'):
        print("IMPROVEMENT SUGGESTIONS:")
        print(analysis['improvement_suggestions'])
        print()

print(f"\n\n{'='*80}")
print("PRODUCT ADAPTATIONS FOR COLLAGEN 3X DROPS")
print(f"{'='*80}\n")

# Get product adaptations
adaptations_result = supabase.table("product_adaptations")\
    .select("*, posts(post_url, accounts(platform_username)), products(name)")\
    .execute()

adaptations = adaptations_result.data

for i, adapt in enumerate(adaptations, 1):
    post = adapt['posts']
    product = adapt['products']
    username = post['accounts']['platform_username']
    
    print(f"\n{'='*80}")
    print(f"ADAPTATION {i}: @{username} → {product['name']}")
    print(f"{'='*80}")
    print(f"URL: {post['post_url']}")
    
    print(f"\nSCORES:")
    print(f"  Hook Relevance: {adapt.get('hook_relevance_score', 'N/A')}/10")
    print(f"  Audience Match: {adapt.get('audience_match_score', 'N/A')}/10")
    print(f"  Transition Ease: {adapt.get('transition_ease_score', 'N/A')}/10")
    print(f"  Viral Replicability: {adapt.get('viral_replicability_score', 'N/A')}/10")
    print(f"  OVERALL: {adapt.get('overall_score', 'N/A')}/10")
    
    if adapt.get('adapted_hook'):
        print(f"\nADAPTED HOOK:")
        print(adapt['adapted_hook'])
    
    if adapt.get('adapted_script'):
        print(f"\nADAPTED SCRIPT:")
        print(adapt['adapted_script'])
    
    if adapt.get('transition_strategy'):
        print(f"\nTRANSITION STRATEGY:")
        print(adapt['transition_strategy'])
    
    if adapt.get('best_use_case'):
        print(f"\nBEST USE CASE:")
        print(adapt['best_use_case'])
    
    if adapt.get('production_notes'):
        print(f"\nPRODUCTION NOTES:")
        print(adapt['production_notes'])
    
    print()

