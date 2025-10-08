from viraltracker.core.database import get_supabase_client
import json

supabase = get_supabase_client()

# Get Wonder Paws project
project_result = supabase.table("projects").select("id").eq("slug", "wonder-paws-tiktok").execute()
project_id = project_result.data[0]['id']

# Get posts for this project
project_posts = supabase.table("project_posts").select("post_id").eq("project_id", project_id).execute()
post_ids = [p['post_id'] for p in project_posts.data]

# Get video analyses
analyses_result = supabase.table("video_analysis")\
    .select("*, posts(post_url, caption, views, accounts(platform_username))")\
    .in_("post_id", post_ids)\
    .execute()

analyses = analyses_result.data

print("# WONDER PAWS - COMPLETE TIKTOK VIRAL ANALYSIS\n")
print(f"**Total Videos Analyzed:** {len(analyses)}")
print(f"**Total Views:** {sum(a['posts']['views'] for a in analyses):,}\n")
print("="*100 + "\n")

for i, analysis in enumerate(analyses, 1):
    post = analysis['posts']
    username = post['accounts']['platform_username']
    
    print(f"\n{'='*100}")
    print(f"## VIDEO {i}: @{username}")
    print(f"{'='*100}\n")
    print(f"**URL:** {post['post_url']}")
    print(f"**Views:** {post['views']:,}")
    print(f"**Caption:** {post['caption']}\n")
    
    # Hook Analysis
    print("### HOOK ANALYSIS\n")
    if analysis.get('hook_transcript'):
        print(f"**Transcript:** \"{analysis['hook_transcript']}\"")
    if analysis.get('hook_type'):
        print(f"**Type:** {analysis['hook_type']}")
    if analysis.get('hook_timestamp'):
        print(f"**Duration:** {analysis['hook_timestamp']} seconds")
    
    if analysis.get('hook_visual_storyboard'):
        try:
            hook_visual = json.loads(analysis['hook_visual_storyboard'])
            if hook_visual.get('visual_description'):
                print(f"\n**Visual Description:** {hook_visual['visual_description']}")
            if hook_visual.get('effectiveness_score'):
                print(f"**Effectiveness Score:** {hook_visual['effectiveness_score']}/10")
        except:
            pass
    
    # Full Transcript
    print("\n### FULL TRANSCRIPT\n")
    if analysis.get('transcript'):
        try:
            transcript = json.loads(analysis['transcript'])
            if transcript.get('segments'):
                for seg in transcript['segments']:
                    speaker = seg.get('speaker', 'unknown')
                    text = seg.get('text', '')
                    ts = seg.get('timestamp', 0.0)
                    print(f"[{ts:.1f}s] **{speaker.upper()}:** {text}")
        except Exception as e:
            print(f"Error parsing transcript: {e}")
    
    # Text Overlays
    print("\n### TEXT OVERLAYS\n")
    if analysis.get('text_overlays'):
        try:
            overlays = json.loads(analysis['text_overlays'])
            if overlays.get('overlays'):
                for overlay in overlays['overlays']:
                    ts = overlay.get('timestamp', 0.0)
                    text = overlay.get('text', '')
                    style = overlay.get('style', 'normal')
                    print(f"[{ts:.1f}s] **{text}** _(style: {style})_")
        except:
            pass
    
    # Visual Storyboard
    print("\n### VISUAL STORYBOARD\n")
    if analysis.get('storyboard'):
        try:
            storyboard = json.loads(analysis['storyboard'])
            if storyboard.get('scenes'):
                for scene in storyboard['scenes']:
                    ts = scene.get('timestamp', 0.0)
                    duration = scene.get('duration', 0.0)
                    desc = scene.get('description', '')
                    end_ts = ts + duration
                    print(f"**[{ts:.1f}s - {end_ts:.1f}s] ({duration:.1f}s)**")
                    print(f"{desc}\n")
        except:
            pass
    
    # Key Moments
    print("### KEY MOMENTS\n")
    if analysis.get('key_moments'):
        try:
            moments = json.loads(analysis['key_moments'])
            if moments.get('moments'):
                for moment in moments['moments']:
                    ts = moment.get('timestamp', 0.0)
                    mtype = moment.get('type', '')
                    desc = moment.get('description', '')
                    print(f"**[{ts:.1f}s] {mtype.upper()}:** {desc}\n")
        except:
            pass
    
    # Viral Factors
    print("### VIRAL FACTORS\n")
    if analysis.get('viral_factors'):
        try:
            factors = json.loads(analysis['viral_factors'])
            for key, value in factors.items():
                print(f"- **{key.replace('_', ' ').title()}:** {value}")
        except:
            pass
    
    # Why It Went Viral
    print("\n### WHY IT WENT VIRAL\n")
    if analysis.get('viral_explanation'):
        print(analysis['viral_explanation'])
    
    # Improvement Suggestions
    print("\n### IMPROVEMENT SUGGESTIONS\n")
    if analysis.get('improvement_suggestions'):
        try:
            suggestions = json.loads(analysis['improvement_suggestions'])
            for idx, sug in enumerate(suggestions, 1):
                print(f"{idx}. {sug}")
        except:
            print(analysis['improvement_suggestions'])
    
    print("\n" + "="*100 + "\n")

# Get product adaptations
print("\n\n" + "="*100)
print("# PRODUCT ADAPTATIONS FOR COLLAGEN 3X DROPS")
print("="*100 + "\n")

product_result = supabase.table("products").select("id").eq("slug", "collagen-3x-drops").execute()
if product_result.data:
    product_id = product_result.data[0]['id']
    
    adaptations_result = supabase.table("product_adaptations")\
        .select("*, posts(post_url, caption, views, accounts(platform_username))")\
        .eq("product_id", product_id)\
        .execute()
    
    for i, adapt in enumerate(adaptations_result.data, 1):
        post = adapt['posts']
        username = post['accounts']['platform_username']
        
        print(f"\n{'='*100}")
        print(f"## ADAPTATION {i}: @{username}")
        print(f"{'='*100}\n")
        print(f"**Original URL:** {post['post_url']}")
        print(f"**Views:** {post['views']:,}\n")
        
        print("### ADAPTATION SCORES\n")
        print(f"- **Hook Relevance:** {adapt.get('hook_relevance_score', 'N/A')}/10")
        print(f"- **Audience Match:** {adapt.get('audience_match_score', 'N/A')}/10")
        print(f"- **Transition Ease:** {adapt.get('transition_ease_score', 'N/A')}/10")
        print(f"- **Viral Replicability:** {adapt.get('viral_replicability_score', 'N/A')}/10")
        print(f"- **OVERALL SCORE:** {adapt.get('overall_score', 'N/A')}/10\n")
        
        if adapt.get('adapted_hook'):
            print(f"### ADAPTED HOOK\n\n{adapt['adapted_hook']}\n")
        
        if adapt.get('adapted_script'):
            print(f"### ADAPTED SCRIPT\n\n{adapt['adapted_script']}\n")
        
        if adapt.get('storyboard'):
            print(f"### ADAPTED STORYBOARD\n")
            try:
                storyboard = json.loads(adapt['storyboard'])
                if storyboard.get('scenes'):
                    for scene in storyboard['scenes']:
                        ts = scene.get('timestamp', 0.0)
                        duration = scene.get('duration', 0.0)
                        desc = scene.get('description', '')
                        end_ts = ts + duration
                        print(f"**[{ts:.1f}s - {end_ts:.1f}s] ({duration:.1f}s)**")
                        print(f"{desc}\n")
            except:
                print(adapt['storyboard'])
        
        if adapt.get('text_overlays'):
            print(f"\n### ADAPTED TEXT OVERLAYS\n")
            try:
                overlays = json.loads(adapt['text_overlays'])
                if overlays.get('overlays'):
                    for overlay in overlays['overlays']:
                        ts = overlay.get('timestamp', 0.0)
                        text = overlay.get('text', '')
                        style = overlay.get('style', 'normal')
                        print(f"[{ts:.1f}s] **{text}** _(style: {style})_")
            except:
                print(adapt['text_overlays'])
        
        if adapt.get('transition_strategy'):
            print(f"\n### TRANSITION STRATEGY\n\n{adapt['transition_strategy']}\n")
        
        if adapt.get('best_use_case'):
            print(f"### BEST USE CASE\n\n{adapt['best_use_case']}\n")
        
        if adapt.get('production_notes'):
            print(f"### PRODUCTION NOTES\n\n{adapt['production_notes']}\n")
        
        print("="*100 + "\n")

print("\n\n**END OF ANALYSIS**")

