from viraltracker.core.database import get_supabase_client
import json

supabase = get_supabase_client()

# Get one TikTok analysis
result = supabase.table("video_analysis")\
    .select("*")\
    .eq("post_id", "155dce45-2c04-4911-9067-efa8450f231d")\
    .execute()

if result.data:
    analysis = result.data[0]
    
    print("CHECKING WHAT GEMINI RETURNED:\n")
    
    # Check if fields have data
    for field in ['transcript', 'text_overlays', 'storyboard', 'key_moments']:
        value = analysis.get(field)
        if value:
            print(f"\n{field.upper()}:")
            try:
                parsed = json.loads(value)
                print(json.dumps(parsed, indent=2))
            except:
                print(value)
        else:
            print(f"\n{field.upper()}: NULL")

