from viraltracker.core.database import get_supabase_client
import json

supabase = get_supabase_client()

# Get one Instagram analysis to check data structure
result = supabase.table("video_analysis")\
    .select("*, posts(post_url, accounts(platform_id, platforms(slug)))")\
    .limit(1)\
    .execute()

if result.data:
    analysis = result.data[0]
    platform_slug = analysis['posts']['accounts']['platforms']['slug']
    
    print(f"Platform: {platform_slug}")
    print(f"Post URL: {analysis['posts']['post_url']}")
    print("\nField Check:")
    print(f"  hook_transcript: {'✓ HAS DATA' if analysis.get('hook_transcript') else '✗ EMPTY'}")
    print(f"  hook_visual_storyboard: {'✓ HAS DATA' if analysis.get('hook_visual_storyboard') else '✗ EMPTY'}")
    print(f"  transcript: {'✓ HAS DATA' if analysis.get('transcript') else '✗ EMPTY'}")
    print(f"  storyboard: {'✓ HAS DATA' if analysis.get('storyboard') else '✗ EMPTY'}")
    print(f"  text_overlays: {'✓ HAS DATA' if analysis.get('text_overlays') else '✗ EMPTY'}")
    print(f"  key_moments: {'✓ HAS DATA' if analysis.get('key_moments') else '✗ EMPTY'}")
    
    print("\n" + "="*80)
    print("SAMPLE DATA:")
    print("="*80)
    
    if analysis.get('transcript'):
        print("\nTRANSCRIPT:")
        print(json.dumps(analysis['transcript'], indent=2)[:500])
    
    if analysis.get('storyboard'):
        print("\nSTORYBOARD:")
        print(json.dumps(analysis['storyboard'], indent=2)[:500])
    
    if analysis.get('text_overlays'):
        print("\nTEXT OVERLAYS:")
        print(json.dumps(analysis['text_overlays'], indent=2)[:500])

