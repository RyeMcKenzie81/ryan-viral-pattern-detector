#!/usr/bin/env python3
"""Export Wonder Paws TikTok analysis to markdown file."""

from viraltracker.core.database import get_supabase_client
import json
import sys

supabase = get_supabase_client()

# Get Wonder Paws project
project_result = supabase.table("projects").select("id, name").eq("slug", "wonder-paws-tiktok").execute()
if not project_result.data:
    print("Error: wonder-paws-tiktok project not found")
    sys.exit(1)

project_id = project_result.data[0]['id']
project_name = project_result.data[0]['name']

# Get posts for this project
project_posts = supabase.table("project_posts").select("post_id").eq("project_id", project_id).execute()
post_ids = [p['post_id'] for p in project_posts.data]

print(f"Found {len(post_ids)} posts in {project_name}")

# Get video analyses
analyses_result = supabase.table("video_analysis")\
    .select("*, posts(post_url, caption, views, accounts(platform_username))")\
    .in_("post_id", post_ids)\
    .execute()

analyses = analyses_result.data
print(f"Found {len(analyses)} analyzed videos")

# Create markdown output
output = []
output.append(f"# {project_name.upper()} - COMPLETE TIKTOK VIRAL ANALYSIS\n")
output.append(f"**Total Videos Analyzed:** {len(analyses)}")
output.append(f"**Total Views:** {sum(a['posts']['views'] for a in analyses):,}\n")
output.append("="*100 + "\n")

for i, analysis in enumerate(analyses, 1):
    post = analysis['posts']
    username = post['accounts']['platform_username']

    output.append(f"\n{'='*100}")
    output.append(f"## VIDEO {i}: @{username}")
    output.append(f"{'='*100}\n")
    output.append(f"**URL:** {post['post_url']}")
    output.append(f"**Views:** {post['views']:,}")
    output.append(f"**Caption:** {post['caption']}\n")

    # Hook Analysis
    output.append("### HOOK ANALYSIS\n")
    if analysis.get('hook_transcript'):
        output.append(f"**Transcript:** \"{analysis['hook_transcript']}\"")
    if analysis.get('hook_type'):
        output.append(f"**Type:** {analysis['hook_type']}")
    if analysis.get('hook_timestamp'):
        output.append(f"**Duration:** {analysis['hook_timestamp']} seconds")

    if analysis.get('hook_visual_storyboard'):
        try:
            hook_visual = json.loads(analysis['hook_visual_storyboard'])
            if hook_visual.get('visual_description'):
                output.append(f"\n**Visual Description:** {hook_visual['visual_description']}")
            if hook_visual.get('effectiveness_score'):
                output.append(f"**Effectiveness Score:** {hook_visual['effectiveness_score']}/10")
        except:
            pass

    # Full Transcript
    output.append("\n### FULL TRANSCRIPT\n")
    if analysis.get('transcript'):
        try:
            transcript = json.loads(analysis['transcript'])
            if transcript.get('segments'):
                for seg in transcript['segments']:
                    speaker = seg.get('speaker', 'unknown')
                    text = seg.get('text', '')
                    ts = seg.get('timestamp', 0.0)
                    output.append(f"[{ts:.1f}s] **{speaker.upper()}:** {text}")
        except Exception as e:
            output.append(f"Error parsing transcript: {e}")

    # Text Overlays
    output.append("\n### TEXT OVERLAYS\n")
    if analysis.get('text_overlays'):
        try:
            overlays = json.loads(analysis['text_overlays'])
            if overlays.get('overlays'):
                for overlay in overlays['overlays']:
                    ts = overlay.get('timestamp', 0.0)
                    text = overlay.get('text', '')
                    style = overlay.get('style', 'normal')
                    output.append(f"[{ts:.1f}s] **{text}** _(style: {style})_")
        except:
            pass

    # Visual Storyboard
    output.append("\n### VISUAL STORYBOARD\n")
    if analysis.get('storyboard'):
        try:
            storyboard = json.loads(analysis['storyboard'])
            if storyboard.get('scenes'):
                for scene in storyboard['scenes']:
                    ts = scene.get('timestamp', 0.0)
                    duration = scene.get('duration', 0.0)
                    desc = scene.get('description', '')
                    end_ts = ts + duration
                    output.append(f"**[{ts:.1f}s - {end_ts:.1f}s] ({duration:.1f}s)**")
                    output.append(f"{desc}\n")
        except:
            pass

    # Key Moments
    output.append("### KEY MOMENTS\n")
    if analysis.get('key_moments'):
        try:
            moments = json.loads(analysis['key_moments'])
            if moments.get('moments'):
                for moment in moments['moments']:
                    ts = moment.get('timestamp', 0.0)
                    mtype = moment.get('type', '')
                    desc = moment.get('description', '')
                    output.append(f"**[{ts:.1f}s] {mtype.upper()}:** {desc}\n")
        except:
            pass

    # Viral Factors
    output.append("### VIRAL FACTORS\n")
    if analysis.get('viral_factors'):
        try:
            factors = json.loads(analysis['viral_factors'])
            for key, value in factors.items():
                output.append(f"- **{key.replace('_', ' ').title()}:** {value}")
        except:
            pass

    # Why It Went Viral
    output.append("\n### WHY IT WENT VIRAL\n")
    if analysis.get('viral_explanation'):
        output.append(analysis['viral_explanation'])

    # Improvement Suggestions
    output.append("\n### IMPROVEMENT SUGGESTIONS\n")
    if analysis.get('improvement_suggestions'):
        try:
            suggestions = json.loads(analysis['improvement_suggestions'])
            for idx, sug in enumerate(suggestions, 1):
                output.append(f"{idx}. {sug}")
        except:
            output.append(analysis['improvement_suggestions'])

    output.append("\n" + "="*100 + "\n")

# Write to file
output_text = "\n".join(output)
filename = "WONDER_PAWS_COMPLETE_ANALYSIS.md"
with open(filename, 'w') as f:
    f.write(output_text)

print(f"\n✅ Analysis exported to {filename}")
print(f"   Total lines: {len(output)}")
