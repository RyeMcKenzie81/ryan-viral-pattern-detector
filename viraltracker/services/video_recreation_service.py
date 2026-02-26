"""
VideoRecreationService - Video recreation pipeline orchestrator.

Scores analyzed Instagram content, adapts storyboards for a brand,
generates audio-first video content, and stitches clips into final output.

Audio-first workflow:
1. Score & approve candidates
2. Adapt storyboard for brand (LLM)
3. Generate audio segments (ElevenLabs)
4. Route scenes: talking-head → Kling Avatar, B-roll → VEO 3.1
5. Generate video clips (one per scene, duration matched to audio)
6. Concatenate clips (FFmpeg concat filter)
7. Output: final video + text overlay instructions + cost report

Scoring weights (v1):
- Engagement:             0.30  (outlier_score from posts)
- Hook quality:           0.25  (eval scores from analysis)
- Recreation feasibility: 0.25  (penalizes complex scenes)
- Avatar compatibility:   0.20  (talking-head + matching avatar)
"""

import asyncio
import json
import logging
import shutil
import tempfile
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from ..core.config import Config
from ..core.database import get_supabase_client

logger = logging.getLogger(__name__)

# Scoring weights (v1)
SCORING_WEIGHTS = {
    "engagement": 0.30,
    "hook_quality": 0.25,
    "recreation_feasibility": 0.25,
    "avatar_compatibility": 0.20,
}
SCORING_VERSION = "v1"

# Scene type constants
SCENE_TALKING_HEAD = "talking_head"
SCENE_BROLL = "broll"
SCENE_ACTION = "action"

# Engine routing
ENGINE_KLING = "kling"
ENGINE_VEO = "veo"
ENGINE_MIXED = "mixed"

# Clip duration constraints (seconds)
VEO_DURATIONS = [4, 6, 8]          # VEO supports 4, 6, 8s
KLING_DURATIONS = ["5", "10"]       # Kling supports 5s or 10s (strings)
KLING_AVATAR_MIN_SEC = 2
KLING_AVATAR_MAX_SEC = 300
MAX_SCENE_BEFORE_SPLIT = 16         # Split scenes longer than this

# Candidate statuses
STATUS_CANDIDATE = "candidate"
STATUS_APPROVED = "approved"
STATUS_REJECTED = "rejected"
STATUS_GENERATING = "generating"
STATUS_COMPLETED = "completed"
STATUS_FAILED = "failed"

# Storage
STORAGE_BUCKET = "video-recreation"

# LLM model for storyboard adaptation
ADAPTATION_MODEL = "gemini-3-flash-preview"

STORYBOARD_ADAPTATION_PROMPT = """You are a video production expert. Adapt the following Instagram video storyboard for our brand.

**Original storyboard:**
{original_storyboard}

**Original script/transcript:**
{original_transcript}

**Original hook:**
{original_hook}

**Our brand context:**
- Brand name: {brand_name}
- Product: {product_name}
- Tone: {brand_tone}
- Avatar: {avatar_description}

**Instructions:**
1. Rewrite the script/dialogue to promote our brand while keeping the effective structure
2. Adapt visual descriptions for our brand's avatar and product
3. Keep the hook style but customize the content
4. Maintain scene timing and pacing from the original
5. Classify each scene as "talking_head" (person speaking to camera) or "broll" (product shots, B-roll, action)
6. For each scene, write a VEO/Kling-ready prompt (specific, continuous tense for actions)

**Return JSON:**
```json
{{
    "adapted_hook": "<our version of the hook>",
    "adapted_script": "<full adapted script/dialogue>",
    "scenes": [
        {{
            "scene_idx": 0,
            "start_sec": 0.0,
            "end_sec": 3.5,
            "duration_sec": 3.5,
            "scene_type": "talking_head|broll",
            "dialogue": "<spoken text for this scene, or null for B-roll>",
            "visual_prompt": "<detailed prompt for video generation>",
            "camera_shot": "<close_up|medium|wide>",
            "transition": "<cut|dissolve|none>"
        }}
    ],
    "text_overlay_instructions": [
        {{
            "scene_idx": 0,
            "text": "<text to display>",
            "position": "top|center|bottom",
            "style": "bold|regular",
            "start_sec": 0.0,
            "end_sec": 3.0
        }}
    ]
}}
```

Return ONLY valid JSON, no additional text.
"""


def _normalize_score(value: Optional[float], min_val: float = 0.0, max_val: float = 1.0) -> float:
    """Normalize a value to 0-1 range."""
    if value is None:
        return 0.0
    return max(0.0, min(1.0, (float(value) - min_val) / (max_val - min_val) if max_val > min_val else 0.0))


def compute_engagement_score(outlier_score: Optional[float]) -> float:
    """Compute engagement component from outlier z-score.

    Args:
        outlier_score: Z-score from outlier detection (typically 0-5+).

    Returns:
        Normalized score 0-1. Z-score >= 3 maps to 1.0.
    """
    if outlier_score is None:
        return 0.0
    return _normalize_score(outlier_score, min_val=0.0, max_val=3.0)


def compute_hook_quality_score(eval_scores: Optional[Dict]) -> float:
    """Compute hook quality from analysis eval scores.

    Uses VA-6 (hook window) and VA-7 (JSON completeness) as proxies
    for analysis quality, plus the overall eval score.

    Args:
        eval_scores: Dict from ad_video_analysis.eval_scores.

    Returns:
        Normalized score 0-1.
    """
    if not eval_scores:
        return 0.0

    overall = eval_scores.get("overall_score", 0.0)
    hook_window = eval_scores.get("va6_hook_window", 0.0)

    # Weighted combination: 60% overall quality, 40% hook specifically
    return min(1.0, (float(overall) * 0.6 + float(hook_window or 0) * 0.4))


def compute_recreation_feasibility(analysis: Optional[Dict]) -> float:
    """Compute recreation feasibility score.

    Penalizes: multiple people, complex interactions, animals, text-heavy.
    Rewards: single person, clear storyboard, good eval scores.

    Args:
        analysis: Full analysis dict from ad_video_analysis.

    Returns:
        Normalized score 0-1.
    """
    if not analysis:
        return 0.0

    score = 0.7  # Base score

    # People count penalty
    people = analysis.get("people_detected", 0) or 0
    if people == 0:
        score += 0.1  # No people = easy B-roll recreation
    elif people == 1:
        score += 0.2  # Single person = ideal for avatar
    elif people == 2:
        score -= 0.1
    else:
        score -= 0.3  # Multiple people = hard to recreate

    # Storyboard quality bonus
    storyboard = analysis.get("storyboard") or []
    if len(storyboard) >= 3:
        score += 0.1  # Well-segmented

    # Format penalty for hard-to-recreate types
    fmt = analysis.get("format_type", "")
    if fmt in ("skit", "animation"):
        score -= 0.2
    elif fmt in ("ugc", "talking_head", "tutorial"):
        score += 0.1

    return max(0.0, min(1.0, score))


def compute_avatar_compatibility(analysis: Optional[Dict], has_avatar: bool) -> float:
    """Compute avatar compatibility score.

    High score when: video has talking-head AND brand has a matching avatar.

    Args:
        analysis: Full analysis dict.
        has_avatar: Whether the brand has an active avatar.

    Returns:
        Normalized score 0-1.
    """
    if not analysis:
        return 0.0

    has_talking_head = analysis.get("has_talking_head", False)

    if has_talking_head and has_avatar:
        return 1.0
    elif has_talking_head and not has_avatar:
        return 0.3  # Could recreate but no avatar
    elif not has_talking_head:
        return 0.6  # B-roll only, avatar not needed
    return 0.5


def compute_composite_score(
    outlier_score: Optional[float],
    eval_scores: Optional[Dict],
    analysis: Optional[Dict],
    has_avatar: bool,
) -> Tuple[float, Dict[str, float]]:
    """Compute weighted composite score for a recreation candidate.

    Args:
        outlier_score: Z-score from outlier detection.
        eval_scores: Eval scores dict from analysis.
        analysis: Full analysis dict.
        has_avatar: Whether brand has an active avatar.

    Returns:
        Tuple of (composite_score, component_dict).
    """
    components = {
        "engagement": compute_engagement_score(outlier_score),
        "hook_quality": compute_hook_quality_score(eval_scores),
        "recreation_feasibility": compute_recreation_feasibility(analysis),
        "avatar_compatibility": compute_avatar_compatibility(analysis, has_avatar),
    }

    composite = sum(
        components[k] * SCORING_WEIGHTS[k] for k in SCORING_WEIGHTS
    )

    return round(composite, 4), {k: round(v, 4) for k, v in components.items()}


def classify_scenes(storyboard: List[Dict], has_talking_head: bool) -> List[str]:
    """Classify each storyboard scene as talking_head or broll.

    Args:
        storyboard: List of scene dicts from analysis.
        has_talking_head: Whether the original video has talking-head.

    Returns:
        List of scene type strings matching storyboard length.
    """
    if not storyboard:
        return []

    types = []
    for scene in storyboard:
        desc = (scene.get("scene_description") or "").lower()
        elements = scene.get("key_elements") or []
        elements_str = " ".join(str(e).lower() for e in elements)

        # Heuristic classification
        is_talking = any(kw in desc or kw in elements_str for kw in [
            "speaking", "talking", "camera", "direct", "person",
            "host", "narrator", "face", "presenter",
        ])

        if is_talking and has_talking_head:
            types.append(SCENE_TALKING_HEAD)
        else:
            types.append(SCENE_BROLL)

    return types


def route_scene_to_engine(scene_type: str, duration_sec: float) -> str:
    """Route a scene to the best generation engine.

    Rules:
    - talking_head → Kling Avatar (handles long talking-head natively)
    - broll/action → VEO 3.1 (better quality for non-character scenes)

    Args:
        scene_type: "talking_head" or "broll".
        duration_sec: Scene duration in seconds.

    Returns:
        "kling" or "veo".
    """
    if scene_type == SCENE_TALKING_HEAD:
        return ENGINE_KLING
    return ENGINE_VEO


def compute_nearest_veo_duration(target_sec: float) -> int:
    """Pick the nearest valid VEO duration (4, 6, or 8 seconds).

    Args:
        target_sec: Target duration in seconds.

    Returns:
        Nearest VEO duration (4, 6, or 8).
    """
    return min(VEO_DURATIONS, key=lambda d: abs(d - target_sec))


def compute_nearest_kling_duration(target_sec: float) -> str:
    """Pick the nearest valid Kling duration ("5" or "10").

    Args:
        target_sec: Target duration in seconds.

    Returns:
        Nearest Kling duration as string.
    """
    if target_sec <= 7.5:
        return "5"
    return "10"


def split_scene_if_needed(
    scene: Dict, max_duration: float = MAX_SCENE_BEFORE_SPLIT
) -> List[Dict]:
    """Split a scene into sub-scenes if it exceeds max duration.

    Never splits mid-sentence for talking-head scenes.

    Args:
        scene: Scene dict with duration_sec, dialogue, scene_type.
        max_duration: Maximum duration before splitting.

    Returns:
        List of scene dicts (1 if no split needed, 2 if split).
    """
    duration = scene.get("duration_sec", 0)
    if duration <= max_duration:
        return [scene]

    # Split into 2 roughly equal parts
    half = duration / 2.0
    scene_a = {**scene, "duration_sec": half, "scene_idx": scene.get("scene_idx", 0)}
    scene_b = {
        **scene,
        "duration_sec": duration - half,
        "scene_idx": scene.get("scene_idx", 0),
        "_is_split_part": True,
    }

    # For talking-head: try to split dialogue at sentence boundary
    dialogue = scene.get("dialogue") or ""
    if dialogue and scene.get("scene_type") == SCENE_TALKING_HEAD:
        sentences = [s.strip() for s in dialogue.replace(".", ".\n").split("\n") if s.strip()]
        if len(sentences) >= 2:
            mid = len(sentences) // 2
            scene_a["dialogue"] = " ".join(sentences[:mid])
            scene_b["dialogue"] = " ".join(sentences[mid:])

    return [scene_a, scene_b]


def estimate_generation_cost(scenes: List[Dict]) -> Dict[str, float]:
    """Estimate generation cost for a set of scenes.

    Args:
        scenes: List of scene dicts with scene_type, duration_sec.

    Returns:
        Dict with per-engine and total estimated costs.
    """
    kling_cost = 0.0
    veo_cost = 0.0

    for scene in scenes:
        engine = route_scene_to_engine(
            scene.get("scene_type", SCENE_BROLL),
            scene.get("duration_sec", 5),
        )
        duration = scene.get("duration_sec", 5)

        if engine == ENGINE_KLING:
            # Kling avatar: per-second pricing (std mode default)
            kling_cost += duration * Config.get_unit_cost("kling_avatar_std_seconds")
        else:
            # VEO: per-second pricing
            veo_cost += duration * Config.get_unit_cost("google_veo_seconds")

    # Add ElevenLabs audio estimate (rough: ~100 chars per 5s of speech)
    talking_head_duration = sum(
        s.get("duration_sec", 0)
        for s in scenes
        if s.get("scene_type") == SCENE_TALKING_HEAD
    )
    # ~20 chars/sec average speaking rate
    estimated_chars = int(talking_head_duration * 20)
    elevenlabs_cost = estimated_chars * Config.get_unit_cost("elevenlabs_characters")

    return {
        "kling_cost": round(kling_cost, 2),
        "veo_cost": round(veo_cost, 2),
        "elevenlabs_cost": round(elevenlabs_cost, 2),
        "total_estimated": round(kling_cost + veo_cost + elevenlabs_cost, 2),
    }


class VideoRecreationService:
    """Orchestrates the full video recreation pipeline.

    Workflow:
    1. score_candidates() — Score all analyzed outlier videos
    2. approve_candidate() — Move to approved status
    3. adapt_storyboard() — LLM adapts storyboard for brand
    4. generate_audio_segments() — ElevenLabs audio for dialogue scenes
    5. generate_video_clips() — Scene-by-scene Kling/VEO generation
    6. concatenate_clips() — FFmpeg final assembly
    """

    def __init__(self, supabase=None):
        """Initialize VideoRecreationService.

        Args:
            supabase: Optional Supabase client. Creates one if not provided.
        """
        self.supabase = supabase or get_supabase_client()

    # ========================================================================
    # Scoring
    # ========================================================================

    def score_candidates(
        self,
        brand_id: str,
        organization_id: str,
        limit: int = 50,
    ) -> List[Dict]:
        """Score all analyzed outlier videos and create/update candidate records.

        Queries analyzed outlier posts, computes composite scores, and upserts
        into video_recreation_candidates.

        Args:
            brand_id: Brand UUID.
            organization_id: Organization UUID.
            limit: Max candidates to score.

        Returns:
            List of scored candidate dicts.
        """
        # Get analyzed posts for this brand (Instagram scrape source)
        query = (
            self.supabase.table("ad_video_analysis")
            .select("*, posts:source_post_id(id, outlier_score, is_outlier, media_type, views, likes, comments)")
            .eq("source_type", "instagram_scrape")
            .eq("brand_id", brand_id)
        )
        if organization_id != "all":
            query = query.eq("organization_id", organization_id)
        analyses = (
            query
            .eq("status", "ok")
            .order("analyzed_at", desc=True)
            .limit(limit)
            .execute()
        )

        if not analyses.data:
            return []

        # Check if brand has an active avatar
        avatars = (
            self.supabase.table("brand_avatars")
            .select("id")
            .eq("brand_id", brand_id)
            .eq("is_active", True)
            .limit(1)
            .execute()
        )
        has_avatar = bool(avatars.data)

        scored = []
        for analysis in analyses.data:
            post = analysis.get("posts") or {}
            post_id = analysis.get("source_post_id")
            if not post_id:
                continue

            outlier_score = post.get("outlier_score")
            eval_scores = analysis.get("eval_scores")

            composite, components = compute_composite_score(
                outlier_score=outlier_score,
                eval_scores=eval_scores,
                analysis=analysis,
                has_avatar=has_avatar,
            )

            # Classify scenes
            storyboard = analysis.get("storyboard") or []
            has_talking_head = analysis.get("has_talking_head", False)
            scene_types = classify_scenes(storyboard, has_talking_head)

            candidate_data = {
                "organization_id": organization_id,
                "brand_id": brand_id,
                "post_id": post_id,
                "analysis_id": analysis["id"],
                "composite_score": composite,
                "score_components": components,
                "scoring_version": SCORING_VERSION,
                "has_talking_head": has_talking_head,
                "scene_types": scene_types,
                "status": STATUS_CANDIDATE,
                "updated_at": datetime.now(timezone.utc).isoformat(),
            }

            # Upsert: check if candidate exists for this post+analysis
            existing = (
                self.supabase.table("video_recreation_candidates")
                .select("id")
                .eq("post_id", post_id)
                .eq("analysis_id", analysis["id"])
                .limit(1)
                .execute()
            )

            if existing.data:
                cid = existing.data[0]["id"]
                self.supabase.table("video_recreation_candidates").update(
                    candidate_data
                ).eq("id", cid).execute()
                candidate_data["id"] = cid
            else:
                candidate_data["created_at"] = datetime.now(timezone.utc).isoformat()
                result = self.supabase.table("video_recreation_candidates").insert(
                    candidate_data
                ).execute()
                if result.data:
                    candidate_data["id"] = result.data[0]["id"]

            scored.append(candidate_data)

        logger.info(
            f"Scored {len(scored)} candidates for brand {brand_id}: "
            f"avg score {sum(c['composite_score'] for c in scored) / len(scored):.3f}"
        )
        return scored

    def approve_candidate(self, candidate_id: str) -> Optional[Dict]:
        """Approve a candidate for recreation.

        Args:
            candidate_id: Candidate UUID.

        Returns:
            Updated candidate dict, or None if not found.
        """
        result = (
            self.supabase.table("video_recreation_candidates")
            .update({
                "status": STATUS_APPROVED,
                "updated_at": datetime.now(timezone.utc).isoformat(),
            })
            .eq("id", candidate_id)
            .execute()
        )
        if result.data:
            logger.info(f"Approved candidate {candidate_id}")
            return result.data[0]
        return None

    def reject_candidate(self, candidate_id: str) -> Optional[Dict]:
        """Reject a candidate.

        Args:
            candidate_id: Candidate UUID.

        Returns:
            Updated candidate dict, or None if not found.
        """
        result = (
            self.supabase.table("video_recreation_candidates")
            .update({
                "status": STATUS_REJECTED,
                "updated_at": datetime.now(timezone.utc).isoformat(),
            })
            .eq("id", candidate_id)
            .execute()
        )
        if result.data:
            logger.info(f"Rejected candidate {candidate_id}")
            return result.data[0]
        return None

    def get_candidate(self, candidate_id: str) -> Optional[Dict]:
        """Get a single candidate with its analysis.

        Args:
            candidate_id: Candidate UUID.

        Returns:
            Candidate dict or None.
        """
        result = (
            self.supabase.table("video_recreation_candidates")
            .select("*, posts:post_id(id, post_url, caption, views, likes, comments, media_type, outlier_score, accounts(platform_username))")
            .eq("id", candidate_id)
            .single()
            .execute()
        )
        return result.data if result.data else None

    def list_candidates(
        self,
        brand_id: str,
        organization_id: str,
        status: Optional[str] = None,
        min_score: Optional[float] = None,
        limit: int = 50,
    ) -> List[Dict]:
        """List candidates with optional filters.

        Args:
            brand_id: Brand UUID.
            organization_id: Organization UUID.
            status: Optional status filter.
            min_score: Optional minimum composite score.
            limit: Max results.

        Returns:
            List of candidate dicts.
        """
        query = (
            self.supabase.table("video_recreation_candidates")
            .select("*, posts:post_id(id, post_url, caption, views, likes, comments, media_type, outlier_score, accounts(platform_username))")
            .eq("brand_id", brand_id)
        )
        if organization_id != "all":
            query = query.eq("organization_id", organization_id)

        if status:
            query = query.eq("status", status)
        if min_score is not None:
            query = query.gte("composite_score", min_score)

        result = query.order("composite_score", desc=True).limit(limit).execute()
        return result.data or []

    # ========================================================================
    # Storyboard Adaptation
    # ========================================================================

    async def adapt_storyboard(
        self,
        candidate_id: str,
        brand_name: str = "",
        product_name: str = "",
        brand_tone: str = "professional, friendly",
        avatar_description: str = "",
    ) -> Optional[Dict]:
        """Adapt the original storyboard for the brand using LLM.

        Args:
            candidate_id: Candidate UUID.
            brand_name: Brand name for context.
            product_name: Product name.
            brand_tone: Tone descriptor.
            avatar_description: Description of brand avatar.

        Returns:
            Updated candidate dict with adapted_storyboard, or None on failure.
        """
        import os
        try:
            from google import genai
        except ImportError:
            logger.error("google-genai not installed")
            return None

        candidate = self.get_candidate(candidate_id)
        if not candidate:
            logger.error(f"Candidate {candidate_id} not found")
            return None

        # Get the analysis
        analysis_id = candidate.get("analysis_id")
        if not analysis_id:
            logger.error(f"Candidate {candidate_id} has no analysis_id")
            return None

        analysis = (
            self.supabase.table("ad_video_analysis")
            .select("storyboard, full_transcript, hook_transcript_spoken, production_storyboard")
            .eq("id", analysis_id)
            .single()
            .execute()
        )
        if not analysis.data:
            logger.error(f"Analysis {analysis_id} not found")
            return None

        row = analysis.data

        # Build the prompt
        prompt = STORYBOARD_ADAPTATION_PROMPT.format(
            original_storyboard=json.dumps(row.get("storyboard") or [], indent=2),
            original_transcript=row.get("full_transcript") or "(no transcript)",
            original_hook=row.get("hook_transcript_spoken") or "(no hook)",
            brand_name=brand_name or "Our Brand",
            product_name=product_name or "Our Product",
            brand_tone=brand_tone,
            avatar_description=avatar_description or "Professional spokesperson",
        )

        api_key = os.getenv("GEMINI_API_KEY")
        if not api_key:
            logger.error("GEMINI_API_KEY not set")
            return None

        client = genai.Client(api_key=api_key)
        response = client.models.generate_content(
            model=ADAPTATION_MODEL,
            contents=[prompt],
        )

        result_text = response.text.strip() if response.text else ""

        # Parse JSON response
        from .instagram_analysis_service import _parse_json_response
        parsed = _parse_json_response(result_text)

        if not parsed or "scenes" not in parsed:
            logger.error(f"Failed to parse storyboard adaptation for {candidate_id}")
            return None

        # Update candidate
        update_data = {
            "adapted_storyboard": parsed.get("scenes"),
            "adapted_hook": parsed.get("adapted_hook"),
            "adapted_script": parsed.get("adapted_script"),
            "text_overlay_instructions": parsed.get("text_overlay_instructions"),
            "scene_types": [s.get("scene_type", SCENE_BROLL) for s in parsed["scenes"]],
            "updated_at": datetime.now(timezone.utc).isoformat(),
        }

        result = (
            self.supabase.table("video_recreation_candidates")
            .update(update_data)
            .eq("id", candidate_id)
            .execute()
        )

        logger.info(
            f"Adapted storyboard for {candidate_id}: "
            f"{len(parsed['scenes'])} scenes, "
            f"hook='{(parsed.get('adapted_hook') or '')[:50]}...'"
        )
        return result.data[0] if result.data else None

    # ========================================================================
    # Audio Generation
    # ========================================================================

    async def generate_audio_segments(
        self,
        candidate_id: str,
        voice_id: str,
        voice_settings: Optional[Dict] = None,
    ) -> Optional[Dict]:
        """Generate ElevenLabs audio for each dialogue scene.

        Audio-first workflow: audio durations determine video clip durations.

        Args:
            candidate_id: Candidate UUID.
            voice_id: ElevenLabs voice ID for the brand's voice.
            voice_settings: Optional voice settings override.

        Returns:
            Updated candidate dict with audio_segments, or None on failure.
        """
        from .elevenlabs_service import ElevenLabsService
        from .audio_models import VoiceSettings

        candidate = self.get_candidate(candidate_id)
        if not candidate:
            return None

        adapted = candidate.get("adapted_storyboard")
        if not adapted:
            logger.error(f"Candidate {candidate_id} has no adapted storyboard")
            return None

        elevenlabs = ElevenLabsService()
        if not elevenlabs.enabled:
            logger.error("ElevenLabs service not configured")
            return None

        settings = VoiceSettings(**(voice_settings or {}))

        audio_segments = []
        total_duration = 0.0
        temp_dir = Path(tempfile.mkdtemp(prefix="vr_audio_"))

        try:
            for scene in adapted:
                scene_idx = scene.get("scene_idx", len(audio_segments))
                dialogue = scene.get("dialogue")

                if not dialogue or scene.get("scene_type") != SCENE_TALKING_HEAD:
                    # No audio for B-roll scenes
                    audio_segments.append({
                        "scene_idx": scene_idx,
                        "audio_storage_path": None,
                        "duration_sec": scene.get("duration_sec", 5.0),
                        "has_audio": False,
                    })
                    total_duration += scene.get("duration_sec", 5.0)
                    continue

                # Generate audio
                output_path = temp_dir / f"scene_{scene_idx:03d}.mp3"
                await elevenlabs.generate_speech(
                    text=dialogue,
                    voice_id=voice_id,
                    settings=settings,
                    output_path=output_path,
                )

                # Get actual duration via ffprobe
                duration_sec = await self._get_audio_duration(output_path)
                if duration_sec is None:
                    duration_sec = scene.get("duration_sec", 5.0)

                # Upload to Supabase storage
                storage_path = f"{candidate_id}/audio/scene_{scene_idx:03d}.mp3"
                audio_data = output_path.read_bytes()
                self.supabase.storage.from_(STORAGE_BUCKET).upload(
                    storage_path, audio_data, {"content-type": "audio/mpeg"}
                )

                audio_segments.append({
                    "scene_idx": scene_idx,
                    "audio_storage_path": f"{STORAGE_BUCKET}/{storage_path}",
                    "duration_sec": round(duration_sec, 2),
                    "has_audio": True,
                })
                total_duration += duration_sec

            # Update candidate
            update_data = {
                "audio_segments": audio_segments,
                "total_audio_duration_sec": round(total_duration, 2),
                "updated_at": datetime.now(timezone.utc).isoformat(),
            }

            result = (
                self.supabase.table("video_recreation_candidates")
                .update(update_data)
                .eq("id", candidate_id)
                .execute()
            )

            logger.info(
                f"Generated audio for {candidate_id}: "
                f"{sum(1 for s in audio_segments if s['has_audio'])} segments, "
                f"{total_duration:.1f}s total"
            )
            return result.data[0] if result.data else None

        except Exception as e:
            logger.error(f"Audio generation failed for {candidate_id}: {e}", exc_info=True)
            return None

        finally:
            # Cleanup temp directory
            shutil.rmtree(temp_dir, ignore_errors=True)

    # ========================================================================
    # Video Clip Generation
    # ========================================================================

    async def generate_video_clips(
        self,
        candidate_id: str,
        avatar_id: Optional[str] = None,
        engine_override: Optional[str] = None,
        mode: str = "std",
    ) -> Optional[Dict]:
        """Generate video clips for each scene (audio-first durations).

        Routes each scene to the appropriate engine:
        - talking_head → Kling Avatar (image + audio)
        - broll → VEO 3.1 or Kling text-to-video

        Args:
            candidate_id: Candidate UUID.
            avatar_id: Brand avatar UUID for talking-head scenes.
            engine_override: Force engine ("veo" or "kling") for all scenes.
            mode: Kling quality mode ("std" or "pro").

        Returns:
            Updated candidate with generated_clips, or None on failure.
        """
        candidate = self.get_candidate(candidate_id)
        if not candidate:
            return None

        adapted = candidate.get("adapted_storyboard")
        audio_segments = candidate.get("audio_segments")
        if not adapted:
            logger.error(f"Candidate {candidate_id} has no adapted storyboard")
            return None

        # Update status to generating
        self.supabase.table("video_recreation_candidates").update({
            "status": STATUS_GENERATING,
            "updated_at": datetime.now(timezone.utc).isoformat(),
        }).eq("id", candidate_id).execute()

        org_id = candidate["organization_id"]
        brand_id = candidate["brand_id"]
        target_aspect = candidate.get("target_aspect_ratio", "9:16")

        # Get avatar image URL if needed
        avatar_image_url = None
        if avatar_id:
            avatar = (
                self.supabase.table("brand_avatars")
                .select("reference_image_1")
                .eq("id", avatar_id)
                .single()
                .execute()
            )
            if avatar.data and avatar.data.get("reference_image_1"):
                ref_path = avatar.data["reference_image_1"]
                parts = ref_path.split("/", 1)
                bucket = parts[0]
                path = parts[1] if len(parts) > 1 else ref_path
                signed = self.supabase.storage.from_(bucket).create_signed_url(path, 3600)
                avatar_image_url = signed.get("signedURL")

        generated_clips = []
        total_cost = 0.0
        engines_used = set()

        for i, scene in enumerate(adapted):
            scene_idx = scene.get("scene_idx", i)
            scene_type = scene.get("scene_type", SCENE_BROLL)

            # Get audio duration (audio-first: audio determines video duration)
            audio_seg = None
            if audio_segments:
                audio_seg = next(
                    (s for s in audio_segments if s.get("scene_idx") == scene_idx),
                    None,
                )

            duration_sec = (
                audio_seg["duration_sec"] if audio_seg and audio_seg.get("has_audio")
                else scene.get("duration_sec", 5.0)
            )

            # Route to engine
            engine = engine_override or route_scene_to_engine(scene_type, duration_sec)
            engines_used.add(engine)

            prompt = scene.get("visual_prompt", scene.get("scene_description", ""))

            clip_result = {
                "scene_idx": scene_idx,
                "engine": engine,
                "duration_sec": duration_sec,
                "status": "pending",
            }

            try:
                if engine == ENGINE_KLING:
                    if scene_type == SCENE_TALKING_HEAD and avatar_image_url and audio_seg and audio_seg.get("has_audio"):
                        # Kling Avatar: talking-head with audio
                        gen_result = await self._generate_kling_avatar_clip(
                            org_id=org_id,
                            brand_id=brand_id,
                            candidate_id=candidate_id,
                            avatar_image_url=avatar_image_url,
                            audio_storage_path=audio_seg["audio_storage_path"],
                            prompt=prompt,
                            mode=mode,
                            avatar_id=avatar_id,
                        )
                    else:
                        # Kling text-to-video for B-roll
                        kling_duration = compute_nearest_kling_duration(duration_sec)
                        gen_result = await self._generate_kling_text_clip(
                            org_id=org_id,
                            brand_id=brand_id,
                            candidate_id=candidate_id,
                            prompt=prompt,
                            duration=kling_duration,
                            aspect_ratio=target_aspect,
                            mode=mode,
                        )

                    clip_result.update(gen_result)

                elif engine == ENGINE_VEO:
                    veo_duration = compute_nearest_veo_duration(duration_sec)
                    gen_result = await self._generate_veo_clip(
                        brand_id=brand_id,
                        prompt=prompt,
                        duration_sec=veo_duration,
                        aspect_ratio=target_aspect,
                    )
                    clip_result.update(gen_result)

            except Exception as e:
                logger.error(f"Clip generation failed for scene {scene_idx}: {e}")
                clip_result["status"] = "failed"
                clip_result["error"] = str(e)[:500]

            if clip_result.get("estimated_cost_usd"):
                total_cost += clip_result["estimated_cost_usd"]

            generated_clips.append(clip_result)

        # Determine overall engine
        if len(engines_used) > 1:
            overall_engine = ENGINE_MIXED
        elif engines_used:
            overall_engine = engines_used.pop()
        else:
            overall_engine = None

        # Update candidate
        update_data = {
            "generated_clips": generated_clips,
            "generation_engine": overall_engine,
            "avatar_id": avatar_id,
            "total_generation_cost_usd": round(total_cost, 2),
            "updated_at": datetime.now(timezone.utc).isoformat(),
        }

        # Check if all clips succeeded
        all_done = all(c.get("status") == "succeed" for c in generated_clips)
        any_failed = any(c.get("status") == "failed" for c in generated_clips)

        if any_failed:
            update_data["status"] = STATUS_FAILED
        elif not all_done:
            # Some clips might still be pending/processing
            update_data["status"] = STATUS_GENERATING

        result = (
            self.supabase.table("video_recreation_candidates")
            .update(update_data)
            .eq("id", candidate_id)
            .execute()
        )

        logger.info(
            f"Generated {len(generated_clips)} clips for {candidate_id}: "
            f"engine={overall_engine}, cost=${total_cost:.2f}"
        )
        return result.data[0] if result.data else None

    # ========================================================================
    # Clip Concatenation
    # ========================================================================

    async def concatenate_clips(
        self,
        candidate_id: str,
        background_music_path: Optional[str] = None,
    ) -> Optional[Dict]:
        """Concatenate all generated clips into final video using FFmpeg.

        Uses the concat filter (not demuxer) for reliable audio sync,
        matching the pattern from comic_render_service.py.

        Args:
            candidate_id: Candidate UUID.
            background_music_path: Optional local path to background music.

        Returns:
            Updated candidate with final_video_path, or None on failure.
        """
        ffmpeg_path = shutil.which("ffmpeg")
        ffprobe_path = shutil.which("ffprobe")
        if not ffmpeg_path:
            logger.error("FFmpeg not found")
            return None

        candidate = self.get_candidate(candidate_id)
        if not candidate:
            return None

        clips = candidate.get("generated_clips") or []
        if not clips:
            logger.error(f"Candidate {candidate_id} has no generated clips")
            return None

        # Filter to successful clips with storage paths
        valid_clips = [
            c for c in clips
            if c.get("status") == "succeed" and c.get("storage_path")
        ]
        if not valid_clips:
            logger.error(f"No successful clips for {candidate_id}")
            return None

        # Sort by scene index
        valid_clips.sort(key=lambda c: c.get("scene_idx", 0))

        temp_dir = Path(tempfile.mkdtemp(prefix="vr_concat_"))

        try:
            # Download all clips to temp dir
            local_paths = []
            for i, clip in enumerate(valid_clips):
                storage_path = clip["storage_path"]
                parts = storage_path.split("/", 1)
                bucket = parts[0]
                path = parts[1] if len(parts) > 1 else storage_path

                video_data = self.supabase.storage.from_(bucket).download(path)
                local_path = temp_dir / f"clip_{i:03d}.mp4"
                local_path.write_bytes(video_data)
                local_paths.append(local_path)

            if not local_paths:
                return None

            # Ensure all clips have audio tracks (required for concat filter)
            for path in local_paths:
                has_audio = await self._has_audio_stream(path, ffprobe_path)
                if not has_audio:
                    await self._add_silent_audio(path, ffmpeg_path, ffprobe_path)

            # Build FFmpeg concat filter command
            output_path = temp_dir / "final.mp4"
            n = len(local_paths)

            cmd = [ffmpeg_path, "-y"]
            for path in local_paths:
                cmd.extend(["-i", str(path)])

            # SAR normalization + concat filter (from comic_render_service pattern)
            sar_filters = []
            concat_inputs = []
            for i in range(n):
                sar_filters.append(f"[{i}:v]setsar=1:1[v{i}]")
                concat_inputs.append(f"[v{i}][{i}:a]")

            filter_complex = (
                ";".join(sar_filters)
                + ";"
                + "".join(concat_inputs)
                + f"concat=n={n}:v=1:a=1[outv][outa]"
            )

            cmd.extend([
                "-filter_complex", filter_complex,
                "-map", "[outv]",
                "-map", "[outa]",
                "-c:v", "libx264",
                "-preset", "medium",
                "-crf", "23",
                "-pix_fmt", "yuv420p",
                "-c:a", "aac",
                "-b:a", "192k",
                str(output_path),
            ])

            # Run FFmpeg
            process = await asyncio.create_subprocess_exec(
                *cmd,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )
            stdout, stderr = await asyncio.wait_for(
                process.communicate(), timeout=600
            )

            if process.returncode != 0:
                error_msg = stderr.decode()[-1500:] if stderr else "Unknown error"
                logger.error(f"FFmpeg concat failed: {error_msg}")
                return None

            # Mix background music if provided
            if background_music_path and Path(background_music_path).exists():
                music_output = temp_dir / "final_with_music.mp4"
                await self._mix_background_music(
                    ffmpeg_path, output_path, Path(background_music_path), music_output
                )
                if music_output.exists():
                    output_path = music_output

            # Upload to Supabase storage
            final_storage_path = f"{candidate_id}/final/video.mp4"
            final_data = output_path.read_bytes()
            self.supabase.storage.from_(STORAGE_BUCKET).upload(
                final_storage_path, final_data, {"content-type": "video/mp4"}
            )
            full_storage_path = f"{STORAGE_BUCKET}/{final_storage_path}"

            # Get final duration
            final_duration = await self._get_audio_duration(output_path)

            # Update candidate
            update_data = {
                "final_video_path": full_storage_path,
                "final_video_duration_sec": final_duration,
                "status": STATUS_COMPLETED,
                "updated_at": datetime.now(timezone.utc).isoformat(),
            }

            result = (
                self.supabase.table("video_recreation_candidates")
                .update(update_data)
                .eq("id", candidate_id)
                .execute()
            )

            logger.info(
                f"Concatenated {n} clips for {candidate_id}: "
                f"duration={final_duration}s, path={full_storage_path}"
            )
            return result.data[0] if result.data else None

        except Exception as e:
            logger.error(f"Concatenation failed for {candidate_id}: {e}", exc_info=True)
            self.supabase.table("video_recreation_candidates").update({
                "status": STATUS_FAILED,
                "updated_at": datetime.now(timezone.utc).isoformat(),
            }).eq("id", candidate_id).execute()
            return None

        finally:
            shutil.rmtree(temp_dir, ignore_errors=True)

    # ========================================================================
    # Cost Estimation
    # ========================================================================

    def get_cost_estimate(self, candidate_id: str) -> Optional[Dict]:
        """Estimate generation cost before committing.

        Args:
            candidate_id: Candidate UUID.

        Returns:
            Cost estimate dict, or None if candidate not found.
        """
        candidate = self.get_candidate(candidate_id)
        if not candidate:
            return None

        adapted = candidate.get("adapted_storyboard")
        if not adapted:
            # Use original analysis storyboard for estimation
            analysis_id = candidate.get("analysis_id")
            if analysis_id:
                analysis = (
                    self.supabase.table("ad_video_analysis")
                    .select("storyboard, has_talking_head")
                    .eq("id", analysis_id)
                    .single()
                    .execute()
                )
                if analysis.data:
                    storyboard = analysis.data.get("storyboard") or []
                    has_th = analysis.data.get("has_talking_head", False)
                    scenes = [
                        {
                            "scene_type": SCENE_TALKING_HEAD if has_th else SCENE_BROLL,
                            "duration_sec": 5.0,
                        }
                        for _ in storyboard
                    ]
                    return estimate_generation_cost(scenes)
            return None

        return estimate_generation_cost(adapted)

    # ========================================================================
    # Internal: Generation Helpers
    # ========================================================================

    async def _generate_kling_avatar_clip(
        self,
        org_id: str,
        brand_id: str,
        candidate_id: str,
        avatar_image_url: str,
        audio_storage_path: str,
        prompt: Optional[str],
        mode: str,
        avatar_id: Optional[str],
    ) -> Dict:
        """Generate a Kling avatar (talking-head) clip.

        Returns dict with generation_id, status, storage_path, estimated_cost_usd.
        """
        from .kling_video_service import KlingVideoService
        from .kling_models import KlingEndpoint

        kling = KlingVideoService()

        # Get signed URL for audio
        parts = audio_storage_path.split("/", 1)
        bucket = parts[0]
        path = parts[1] if len(parts) > 1 else audio_storage_path
        audio_signed = self.supabase.storage.from_(bucket).create_signed_url(path, 3600)
        audio_url = audio_signed.get("signedURL", "")

        gen_result = await kling.generate_avatar_video(
            organization_id=org_id,
            brand_id=brand_id,
            image=avatar_image_url,
            sound_file=audio_url,
            prompt=prompt,
            mode=mode,
            avatar_id=avatar_id,
            candidate_id=candidate_id,
        )

        # Poll for completion
        kling_task_id = gen_result.get("kling_task_id")
        generation_id = gen_result.get("generation_id")

        if kling_task_id:
            completed = await kling.poll_and_complete(
                generation_id=generation_id,
                kling_task_id=kling_task_id,
                endpoint_type=KlingEndpoint.AVATAR,
            )
            await kling.close()
            return {
                "generation_id": generation_id,
                "status": completed.get("status", "failed"),
                "storage_path": completed.get("video_storage_path"),
                "estimated_cost_usd": gen_result.get("estimated_cost_usd", 0),
            }

        await kling.close()
        return {"generation_id": generation_id, "status": "failed"}

    async def _generate_kling_text_clip(
        self,
        org_id: str,
        brand_id: str,
        candidate_id: str,
        prompt: str,
        duration: str,
        aspect_ratio: str,
        mode: str,
    ) -> Dict:
        """Generate a Kling text-to-video clip.

        Returns dict with generation_id, status, storage_path, estimated_cost_usd.
        """
        from .kling_video_service import KlingVideoService
        from .kling_models import KlingEndpoint

        kling = KlingVideoService()

        gen_result = await kling.generate_text_to_video(
            organization_id=org_id,
            brand_id=brand_id,
            prompt=prompt,
            duration=duration,
            aspect_ratio=aspect_ratio,
            mode=mode,
            candidate_id=candidate_id,
        )

        kling_task_id = gen_result.get("kling_task_id")
        generation_id = gen_result.get("generation_id")

        if kling_task_id:
            completed = await kling.poll_and_complete(
                generation_id=generation_id,
                kling_task_id=kling_task_id,
                endpoint_type=KlingEndpoint.TEXT2VIDEO,
            )
            await kling.close()
            return {
                "generation_id": generation_id,
                "status": completed.get("status", "failed"),
                "storage_path": completed.get("video_storage_path"),
                "estimated_cost_usd": gen_result.get("estimated_cost_usd", 0),
            }

        await kling.close()
        return {"generation_id": generation_id, "status": "failed"}

    async def _generate_veo_clip(
        self,
        brand_id: str,
        prompt: str,
        duration_sec: int,
        aspect_ratio: str,
    ) -> Dict:
        """Generate a VEO clip.

        Returns dict with generation_id, status, storage_path, estimated_cost_usd.
        """
        from .veo_service import VeoService
        from .veo_models import (
            VeoGenerationRequest,
            VeoConfig,
            AspectRatio as VeoAspectRatio,
            ModelVariant,
        )

        veo = VeoService()

        veo_aspect = (
            VeoAspectRatio.PORTRAIT if "9:16" in aspect_ratio
            else VeoAspectRatio.LANDSCAPE
        )

        request = VeoGenerationRequest(
            brand_id=brand_id,
            prompt=prompt,
            config=VeoConfig(
                aspect_ratio=veo_aspect,
                duration_seconds=duration_sec,
                model_variant=ModelVariant.STANDARD,
            ),
        )

        result = await veo.generate_video(request)

        return {
            "generation_id": str(result.generation_id),
            "status": "succeed" if result.is_success else "failed",
            "storage_path": result.video_storage_path,
            "estimated_cost_usd": result.estimated_cost_usd,
            "error": result.error_message,
        }

    # ========================================================================
    # Internal: FFmpeg Helpers
    # ========================================================================

    async def _get_audio_duration(self, file_path: Path) -> Optional[float]:
        """Get file duration in seconds via ffprobe."""
        ffprobe = shutil.which("ffprobe")
        if not ffprobe:
            return None

        cmd = [
            ffprobe, "-v", "error",
            "-show_entries", "format=duration",
            "-of", "csv=p=0",
            str(file_path),
        ]

        try:
            process = await asyncio.create_subprocess_exec(
                *cmd,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )
            stdout, _ = await process.communicate()
            if process.returncode == 0:
                return float(stdout.decode().strip())
        except Exception as e:
            logger.warning(f"Failed to get duration for {file_path}: {e}")
        return None

    async def _has_audio_stream(self, video_path: Path, ffprobe_path: str) -> bool:
        """Check if a video file has an audio stream."""
        cmd = [
            ffprobe_path, "-v", "error",
            "-select_streams", "a",
            "-show_entries", "stream=codec_type",
            "-of", "csv=p=0",
            str(video_path),
        ]
        try:
            process = await asyncio.create_subprocess_exec(
                *cmd,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )
            stdout, _ = await process.communicate()
            return bool(stdout.decode().strip())
        except Exception:
            return False

    async def _add_silent_audio(
        self, video_path: Path, ffmpeg_path: str, ffprobe_path: str
    ) -> None:
        """Add a silent audio track to a video that's missing one."""
        # Get duration
        duration = await self._get_audio_duration(video_path)
        if duration is None:
            duration = 5.0

        output_path = video_path.with_suffix(".with_audio.mp4")
        cmd = [
            ffmpeg_path, "-y",
            "-i", str(video_path),
            "-f", "lavfi", "-i", f"anullsrc=r=44100:cl=stereo",
            "-t", str(duration),
            "-c:v", "copy",
            "-c:a", "aac",
            "-b:a", "128k",
            "-shortest",
            str(output_path),
        ]

        process = await asyncio.create_subprocess_exec(
            *cmd,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        await process.communicate()

        if output_path.exists():
            video_path.unlink()
            output_path.rename(video_path)

    async def _mix_background_music(
        self,
        ffmpeg_path: str,
        video_path: Path,
        music_path: Path,
        output_path: Path,
        music_volume: float = 0.15,
    ) -> None:
        """Mix background music under the video audio."""
        cmd = [
            ffmpeg_path, "-y",
            "-i", str(video_path),
            "-i", str(music_path),
            "-filter_complex",
            f"[1:a]volume={music_volume}[music];"
            f"[0:a][music]amix=inputs=2:duration=first[aout]",
            "-map", "0:v",
            "-map", "[aout]",
            "-c:v", "copy",
            "-c:a", "aac",
            "-b:a", "192k",
            str(output_path),
        ]

        process = await asyncio.create_subprocess_exec(
            *cmd,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        await process.communicate()
