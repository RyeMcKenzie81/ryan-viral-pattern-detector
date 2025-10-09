"""
Data Adapter for TikTok Scoring Engine

Converts database records to scorer input JSON format.
"""

import json
import logging
import re
from typing import Dict, List, Optional, Any
from datetime import datetime

from supabase import Client


logger = logging.getLogger(__name__)


def prepare_scorer_input(post_id: str, supabase: Client) -> Dict[str, Any]:
    """
    Prepare scorer input JSON from database records.

    Args:
        post_id: UUID of the post to score
        supabase: Supabase client

    Returns:
        Scorer input JSON matching ScorerInputSchema

    Raises:
        ValueError: If required data is missing
    """
    logger.info(f"Preparing scorer input for post {post_id}")

    # Fetch post with account info
    post_result = supabase.table("posts").select(
        "id, created_at, caption, views, likes, comments, account_id, accounts(follower_count)"
    ).eq("id", post_id).single().execute()

    if not post_result.data:
        raise ValueError(f"Post not found: {post_id}")

    post = post_result.data

    # Fetch video_analysis
    analysis_result = supabase.table("video_analysis").select("*").eq("post_id", post_id).single().execute()

    if not analysis_result.data:
        raise ValueError(f"Video analysis not found for post: {post_id}")

    analysis = analysis_result.data

    # Fetch video duration
    duration_result = supabase.table("video_processing_log").select(
        "video_duration_sec"
    ).eq("post_id", post_id).single().execute()

    length_sec = duration_result.data.get('video_duration_sec', 0) if duration_result.data else 0

    # Parse JSON fields
    transcript = _parse_json_field(analysis.get('transcript'))
    storyboard = _parse_json_field(analysis.get('storyboard'))
    text_overlays = _parse_json_field(analysis.get('text_overlays'))
    key_moments = _parse_json_field(analysis.get('key_moments'))
    hook_visual = _parse_json_field(analysis.get('hook_visual_storyboard'))

    # Extract meta
    meta = {
        "video_id": post_id,
        "post_time_iso": post.get('created_at', datetime.utcnow().isoformat()),
        "followers": post.get('accounts', {}).get('follower_count', 0) if post.get('accounts') else 0,
        "length_sec": length_sec or 0
    }

    # Build measures
    measures = {
        "hook": _build_hook_measures(analysis, hook_visual),
        "story": _build_story_measures(storyboard, key_moments),
        "visuals": _build_visuals_measures(text_overlays, storyboard, length_sec),
        "audio": _build_audio_measures(analysis),
        "watchtime": _build_watchtime_measures(length_sec, post),
        "engagement": _build_engagement_measures(post),
        "shareability": _build_shareability_measures(post),
        "algo": _build_algo_measures(post)
    }

    # Build raw data
    raw = {
        "transcript": _convert_transcript(transcript),
        "hook_span": {
            "t_start": 0,
            "t_end": analysis.get('hook_timestamp', 5.0) or 5.0
        }
    }

    return {
        "meta": meta,
        "measures": measures,
        "raw": raw
    }


def _parse_json_field(field_value: Optional[str]) -> Dict:
    """Parse JSON string field, return empty dict on error."""
    if not field_value:
        return {}

    if isinstance(field_value, dict):
        return field_value

    try:
        return json.loads(field_value)
    except (json.JSONDecodeError, TypeError):
        return {}


def _build_hook_measures(analysis: Dict, hook_visual: Dict) -> Dict:
    """Build hook measures from analysis data."""
    return {
        "duration_sec": analysis.get('hook_timestamp', 5.0) or 5.0,
        "text": analysis.get('hook_transcript', '') or '',
        "type": analysis.get('hook_type', 'curiosity'),
        "visual_description": hook_visual.get('visual_description', ''),
        "effectiveness_score": hook_visual.get('effectiveness_score', 7.0) or 7.0
    }


def _build_story_measures(storyboard: Dict, key_moments: Dict) -> Dict:
    """Build story measures from storyboard and key moments."""
    scenes = storyboard.get('scenes', []) if storyboard else []

    # Convert storyboard format
    converted_storyboard = []
    for scene in scenes:
        converted_storyboard.append({
            "timestamp": scene.get('timestamp', 0),
            "duration": scene.get('duration', 0),
            "description": scene.get('description', '')
        })

    # Detect story arc
    arc_detected = _detect_story_arc(storyboard, key_moments)

    return {
        "storyboard": converted_storyboard,
        "beats_count": len(scenes),
        "arc_detected": arc_detected
    }


def _build_visuals_measures(text_overlays: Dict, storyboard: Dict, length_sec: float) -> Dict:
    """Build visuals measures from overlays and storyboard."""
    overlays = text_overlays.get('overlays', []) if text_overlays else []

    # Convert overlays format
    converted_overlays = []
    for overlay in overlays:
        converted_overlays.append({
            "timestamp": overlay.get('timestamp', 0),
            "text": overlay.get('text', ''),
            "style": overlay.get('style', 'normal')
        })

    # Estimate edit rate from storyboard scene count
    scenes = storyboard.get('scenes', []) if storyboard else []
    edit_rate = (len(scenes) / (length_sec / 10)) if length_sec > 0 else 0

    return {
        "overlays": converted_overlays,
        "edit_rate_per_10s": edit_rate,
        "text_overlay_present": len(overlays) > 0
    }


def _build_audio_measures(analysis: Dict) -> Dict:
    """Build audio measures (placeholder for now)."""
    # Note: We don't currently track audio data in video_analysis
    # Using conservative defaults
    return {
        "trending_sound_used": False,
        "original_sound_created": False,
        "beat_sync_score": 5.0
    }


def _build_watchtime_measures(length_sec: float, post: Dict) -> Dict:
    """Build watchtime measures from video duration and engagement."""
    # Note: We don't have actual watch time data
    # Estimate based on engagement ratio
    views = post.get('views', 0) or 1
    likes = post.get('likes', 0) or 0

    # Higher engagement suggests better watch time
    engagement_ratio = likes / views if views > 0 else 0

    # Rough estimate: high engagement = high completion rate
    estimated_completion = min(100, engagement_ratio * 1000)
    estimated_avg_watch = min(100, estimated_completion * 0.9)

    return {
        "length_sec": length_sec or 0,
        "avg_watch_pct": estimated_avg_watch,
        "completion_rate": estimated_completion
    }


def _build_engagement_measures(post: Dict) -> Dict:
    """Build engagement measures from post stats."""
    views = post.get('views', 0) or 0
    likes = post.get('likes', 0) or 0
    comments = post.get('comments', 0) or 0

    # Estimate shares/saves if not available (typically 10-20% of likes)
    shares = post.get('shares', int(likes * 0.15)) or int(likes * 0.15)
    saves = post.get('saves', int(likes * 0.10)) or int(likes * 0.10)

    return {
        "views": views,
        "likes": likes,
        "comments": comments,
        "shares": shares,
        "saves": saves
    }


def _build_shareability_measures(post: Dict) -> Dict:
    """Build shareability measures from caption."""
    caption = post.get('caption', '') or ''

    return {
        "caption_length_chars": len(caption),
        "has_cta": _detect_cta(caption),
        "save_worthy_signals": _estimate_save_signals(post)
    }


def _build_algo_measures(post: Dict) -> Dict:
    """Build algorithm measures from caption and posting metadata."""
    caption = post.get('caption', '') or ''

    return {
        "caption_length_chars": len(caption),
        "hashtag_count": _count_hashtags(caption),
        "hashtag_niche_mix_ok": _check_hashtag_mix(caption),
        "post_time_optimal": _check_optimal_post_time(post)
    }


def _convert_transcript(transcript: Dict) -> List[Dict]:
    """Convert transcript to scorer format."""
    segments = transcript.get('segments', []) if transcript else []

    converted = []
    for seg in segments:
        converted.append({
            "timestamp": seg.get('timestamp', 0),
            "speaker": seg.get('speaker', 'narrator'),
            "text": seg.get('text', '')
        })

    return converted


def _detect_story_arc(storyboard: Dict, key_moments: Dict) -> bool:
    """Detect if video has a clear story arc."""
    if not storyboard or not key_moments:
        return False

    scenes = storyboard.get('scenes', [])
    moments = key_moments.get('moments', [])

    # Look for key moment types that indicate story structure
    moment_types = [m.get('type', '') for m in moments]

    # Has reveal/climax/cta = likely has arc
    has_reveal = any('reveal' in t or 'climax' in t for t in moment_types)
    has_multiple_scenes = len(scenes) >= 3

    return has_reveal and has_multiple_scenes


def _detect_cta(caption: str) -> bool:
    """Detect call-to-action in caption."""
    cta_patterns = [
        r'\bfollow\b',
        r'\blike\b',
        r'\bcomment\b',
        r'\bshare\b',
        r'\bsave\b',
        r'\bclick\b',
        r'\blink in bio\b',
        r'\bcheck out\b',
        r'\btag\b',
        r'\bDM\b',
    ]

    caption_lower = caption.lower()
    return any(re.search(pattern, caption_lower) for pattern in cta_patterns)


def _estimate_save_signals(post: Dict) -> float:
    """Estimate save-worthiness based on engagement patterns."""
    saves = post.get('saves', 0) or 0
    views = post.get('views', 0) or 1

    # High save rate = 1%, average = 0.3%
    save_rate = (saves / views) * 100 if views > 0 else 0

    # Scale to 0-10
    if save_rate >= 1.0:
        return 10.0
    elif save_rate >= 0.5:
        return 8.0
    elif save_rate >= 0.3:
        return 6.0
    elif save_rate >= 0.1:
        return 4.0
    else:
        return 2.0


def _count_hashtags(caption: str) -> int:
    """Count hashtags in caption."""
    return len(re.findall(r'#\w+', caption))


def _check_hashtag_mix(caption: str) -> bool:
    """Check if hashtag mix is reasonable (3-6 hashtags)."""
    count = _count_hashtags(caption)
    return 3 <= count <= 6


def _check_optimal_post_time(post: Dict) -> bool:
    """Check if post was published at optimal time."""
    # Note: Without timezone data, this is a rough estimate
    # Optimal TikTok times: 6-10am, 7-11pm EST
    try:
        created_at = post.get('created_at', '')
        if not created_at:
            return False

        dt = datetime.fromisoformat(created_at.replace('Z', '+00:00'))
        hour = dt.hour

        # Convert to EST (rough: UTC-5)
        est_hour = (hour - 5) % 24

        # Check if in optimal windows
        is_morning = 6 <= est_hour <= 10
        is_evening = 19 <= est_hour <= 23

        return is_morning or is_evening
    except:
        return False
