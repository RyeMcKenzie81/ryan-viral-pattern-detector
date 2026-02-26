"""
InstagramAnalysisService - Two-pass Gemini analysis of Instagram content.

Pass 1 (Gemini Flash): Structural extraction - transcript, text overlays,
    storyboard, hook analysis, people detection.
Pass 2 (Gemini Pro, approved candidates only): Production shot sheet -
    per-beat camera, subject, lighting, transition details.

Results stored in:
- ad_video_analysis (source_type='instagram_scrape') for video posts
- instagram_image_analysis for image/carousel posts

Automated consistency checks VA-1 through VA-8 run on every analysis.
"""

import hashlib
import json
import logging
import os
import re
import tempfile
import time as time_module
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple
from uuid import UUID

from supabase import Client

from ..core.config import Config
from ..core.database import get_supabase_client

logger = logging.getLogger(__name__)

# Prompt versions
PASS1_PROMPT_VERSION = "ig_v1"
PASS2_PROMPT_VERSION = "ig_prod_v1"
IMAGE_PROMPT_VERSION = "ig_img_v1"

# Models
FLASH_MODEL = "gemini-3-flash-preview"
PRO_MODEL = "gemini-3.1-pro-preview"

# ============================================================================
# Prompts
# ============================================================================

PASS1_VIDEO_PROMPT = """Analyze this Instagram video and extract detailed structured data.

**CRITICAL REQUIREMENTS:**
1. Watch the ENTIRE video, not just the first few seconds
2. Provide accurate timestamps as floating-point seconds (e.g., 3.5, 12.0)
3. Transcripts are MANDATORY - even if approximate
4. Text overlays are BEST EFFORT - include confidence score

**EXTRACT THE FOLLOWING (return as JSON):**

```json
{{
  "video_duration_sec": <float seconds>,

  "full_transcript": "<complete spoken text from the video>",

  "transcript_segments": [
    {{"start_sec": 0.0, "end_sec": 3.5, "text": "...", "speaker": "narrator|host|other"}}
  ],

  "text_overlays": [
    {{"start_sec": 0.0, "end_sec": 5.0, "text": "...", "position": "top|center|bottom", "style": "bold|regular"}}
  ],
  "text_overlay_confidence": 0.8,

  "hook_transcript_spoken": "<exact words spoken in first 3-5 seconds>",
  "hook_transcript_overlay": "<text overlay in first 3-5 seconds, or null if none>",
  "hook_type": "<question|claim|story|callout|transformation|shock|relatable|statistic|before_after|authority|other>",
  "hook_effectiveness_signals": {{
    "spoken_present": true,
    "overlay_present": false,
    "spoken_hook": "<assessment of spoken hook effectiveness>",
    "visual_hook": "<assessment of visual hook, or null if absent>",
    "combination_score": 0.7
  }},

  "hook_visual_description": "<describe what is visually happening in the first 3-5 seconds>",
  "hook_visual_elements": ["person", "product", "text_overlay", "hand_gesture"],
  "hook_visual_type": "<unboxing|transformation|demonstration|testimonial|lifestyle|problem_agitation|authority|social_proof|product_hero|curiosity|other>",

  "storyboard": [
    {{"timestamp_sec": 0.0, "scene_description": "...", "key_elements": ["..."], "text_overlay": "..."}},
    {{"timestamp_sec": 5.0, "scene_description": "...", "key_elements": ["..."], "text_overlay": null}}
  ],

  "people_detected": <integer>,
  "has_talking_head": <boolean - true if someone speaks directly to camera>,
  "people_details": [
    {{"description": "...", "role": "host|guest|other", "screen_time_pct": 0.8}}
  ],

  "production_quality": "<raw|polished|professional>",
  "format_type": "<ugc|professional|testimonial|demo|animation|mixed|talking_head|skit|tutorial>"
}}
```

**IMPORTANT:**
- Scene changes in storyboard: mark when visual context significantly changes, or every 5 seconds minimum
- Timestamps must be ordered and non-overlapping for transcript_segments
- If you can't detect text overlays reliably, set text_overlays to [] and text_overlay_confidence to 0.0
- Hook analysis: evaluate first 3-5 seconds for both spoken and visual hooks
- has_talking_head: true ONLY if a person speaks directly to camera (not just appears)
- Return ONLY valid JSON, no additional text
"""

PASS2_PRODUCTION_PROMPT = """You are a professional video production analyst. Analyze this Instagram video and produce a detailed production shot sheet.

For EACH distinct scene/beat in the video, extract:

```json
{{
  "production_storyboard": [
    {{
      "beat_index": 0,
      "timestamp_start_sec": 0.0,
      "timestamp_end_sec": 3.5,
      "duration_sec": 3.5,

      "camera_shot_type": "<extreme_close_up|close_up|medium_close_up|medium|medium_wide|wide|extreme_wide>",
      "camera_movement": "<static|pan_left|pan_right|tilt_up|tilt_down|zoom_in|zoom_out|tracking|handheld|dolly|crane|whip_pan|orbital>",
      "camera_angle": "<eye_level|high_angle|low_angle|birds_eye|worms_eye|dutch_angle|over_shoulder|pov>",

      "subject_action": "<specific continuous-tense verb phrase for VEO prompt, e.g. 'speaking directly to camera while gesturing with hands'>",
      "subject_emotion": "<neutral|happy|excited|concerned|serious|surprised|thoughtful|determined|playful>",
      "subject_framing": "<description of how subject is positioned in frame>",

      "lighting_description": "<description of lighting setup and mood>",
      "background_description": "<description of background/setting>",

      "audio_type": "<voiceover|direct_to_camera|music_only|sfx|silence|mixed>",
      "audio_description": "<brief description of what's heard>",

      "transition_to_next": "<cut|dissolve|whip_pan|jump_cut|fade|swipe|zoom_transition|none>",
      "pacing": "<fast|medium|slow>",

      "text_overlay": "<any on-screen text during this beat, or null>",
      "key_visual_elements": ["element1", "element2"]
    }}
  ],

  "overall_pacing": "<fast|medium|slow|variable>",
  "overall_style": "<description of the overall production style>",
  "color_grade": "<warm|cool|neutral|high_contrast|desaturated|vibrant>",
  "aspect_ratio": "<9:16|16:9|1:1|4:5>",
  "estimated_total_duration_sec": <float>
}}
```

**CRITICAL:**
- Every second of the video must be covered by exactly one beat
- Beats must be contiguous (no gaps or overlaps)
- subject_action must use continuous tense (e.g., "walking", "speaking", "holding")
- Be specific enough that a video generation AI could recreate each beat
- Return ONLY valid JSON, no additional text
"""

IMAGE_ANALYSIS_PROMPT = """Analyze this Instagram image for content recreation potential.

**EXTRACT THE FOLLOWING (return as JSON):**

```json
{{
  "image_description": "<comprehensive description of the image>",
  "image_style": "<art style, color palette, composition description>",
  "image_elements": [
    {{"element": "...", "position": "top_left|top_center|top_right|center_left|center|center_right|bottom_left|bottom_center|bottom_right", "description": "..."}}
  ],
  "image_text_content": "<any text visible in the image, or null>",
  "recreation_notes": "<notes on how this image could be recreated with AI>",

  "people_detected": <integer>,
  "has_talking_head": false,
  "people_details": [
    {{"description": "...", "position": "...", "emotion": "...", "action": "..."}}
  ],

  "color_palette": ["#hex1", "#hex2", "#hex3"],
  "composition_type": "<rule_of_thirds|centered|symmetrical|diagonal|frame_within_frame|leading_lines|other>",
  "mood": "<description of emotional mood>"
}}
```

**IMPORTANT:**
- Be specific enough for AI image generation prompts
- Note any brand logos, products, or identifiable elements
- Return ONLY valid JSON, no additional text
"""


# ============================================================================
# Data classes
# ============================================================================

@dataclass
class VideoAnalysisInput:
    """Input for video analysis."""
    post_id: UUID
    media_id: UUID
    organization_id: UUID
    storage_path: str
    media_type: str = "video"  # video or image


@dataclass
class EvalScores:
    """VA-1 through VA-8 consistency check results."""
    va1_duration_match: Optional[float] = None   # 1.0 = pass, 0.0 = fail
    va2_transcript_present: Optional[float] = None
    va3_storyboard_coverage: Optional[float] = None
    va4_timestamp_monotonicity: Optional[float] = None
    va5_segment_coverage: Optional[float] = None
    va6_hook_window: Optional[float] = None
    va7_json_completeness: Optional[float] = None
    va8_overlay_coherence: Optional[float] = None
    overall_score: float = 0.0

    def to_dict(self) -> Dict:
        return {
            "va1_duration_match": self.va1_duration_match,
            "va2_transcript_present": self.va2_transcript_present,
            "va3_storyboard_coverage": self.va3_storyboard_coverage,
            "va4_timestamp_monotonicity": self.va4_timestamp_monotonicity,
            "va5_segment_coverage": self.va5_segment_coverage,
            "va6_hook_window": self.va6_hook_window,
            "va7_json_completeness": self.va7_json_completeness,
            "va8_overlay_coherence": self.va8_overlay_coherence,
            "overall_score": self.overall_score,
        }


# ============================================================================
# Helper functions
# ============================================================================

def compute_input_hash(storage_path: str, file_size: Optional[int] = None) -> str:
    """Compute deterministic input hash for analysis versioning.

    Args:
        storage_path: Supabase storage path.
        file_size: File size in bytes (for change detection).

    Returns:
        SHA256 hash string.
    """
    source = f"{storage_path}:{file_size or 'unknown'}"
    return hashlib.sha256(source.encode()).hexdigest()


def _parse_json_response(text: str) -> Optional[Dict]:
    """Parse JSON response from Gemini, handling markdown code blocks.

    Args:
        text: Raw response text.

    Returns:
        Parsed dict or None if parsing fails.
    """
    if not text:
        return None

    # Extract JSON from markdown code block
    json_match = re.search(r'```(?:json)?\s*([\s\S]*?)\s*```', text)
    if json_match:
        text = json_match.group(1)

    try:
        return json.loads(text)
    except json.JSONDecodeError as e:
        logger.warning(f"Failed to parse JSON response: {e}")
        return None


def run_eval_checks(
    parsed: Dict,
    actual_duration_sec: Optional[float] = None,
) -> EvalScores:
    """Run VA-1 through VA-8 consistency checks on analysis output.

    Args:
        parsed: Parsed Gemini response dict.
        actual_duration_sec: Known duration from media metadata (for VA-1).

    Returns:
        EvalScores with individual and overall scores.
    """
    scores = EvalScores()
    check_count = 0
    total_score = 0.0

    reported_duration = parsed.get("video_duration_sec")

    # VA-1: Duration match vs known duration
    if actual_duration_sec is not None and reported_duration is not None:
        try:
            diff = abs(float(reported_duration) - float(actual_duration_sec))
            scores.va1_duration_match = 1.0 if diff <= 2.0 else 0.0
            check_count += 1
            total_score += scores.va1_duration_match
        except (ValueError, TypeError):
            scores.va1_duration_match = 0.0
            check_count += 1

    # VA-2: Transcript non-empty
    transcript = parsed.get("full_transcript", "")
    if transcript and len(str(transcript).strip()) > 20:
        scores.va2_transcript_present = 1.0
    else:
        # If it's a music-only or silent video, this isn't necessarily a failure
        # Check if format suggests no speech expected
        fmt = parsed.get("format_type", "")
        if fmt in ("animation", "music_only"):
            scores.va2_transcript_present = 0.5  # Partial pass
        else:
            scores.va2_transcript_present = 0.0
    check_count += 1
    total_score += scores.va2_transcript_present

    # VA-3: Storyboard coverage (last timestamp >= 0.7 * duration)
    storyboard = parsed.get("storyboard") or []
    if storyboard and reported_duration:
        try:
            last_ts = max(float(s.get("timestamp_sec", 0)) for s in storyboard if isinstance(s, dict))
            coverage = last_ts / float(reported_duration) if float(reported_duration) > 0 else 0
            scores.va3_storyboard_coverage = 1.0 if coverage >= 0.7 else coverage / 0.7
            check_count += 1
            total_score += scores.va3_storyboard_coverage
        except (ValueError, TypeError):
            scores.va3_storyboard_coverage = 0.0
            check_count += 1

    # VA-4: Timestamp monotonicity (no reversals in storyboard)
    if storyboard:
        monotonic = True
        last_ts_val = -1.0
        for s in storyboard:
            if not isinstance(s, dict):
                continue
            ts = s.get("timestamp_sec")
            if ts is not None:
                try:
                    ts_float = float(ts)
                    if ts_float < last_ts_val:
                        monotonic = False
                        break
                    last_ts_val = ts_float
                except (ValueError, TypeError):
                    pass
        scores.va4_timestamp_monotonicity = 1.0 if monotonic else 0.0
        check_count += 1
        total_score += scores.va4_timestamp_monotonicity

    # VA-5: Segment coverage (sum of segment durations / total duration >= 0.6)
    segments = parsed.get("transcript_segments") or []
    if segments and reported_duration:
        try:
            seg_total = sum(
                float(s.get("end_sec", 0)) - float(s.get("start_sec", 0))
                for s in segments
                if isinstance(s, dict) and s.get("end_sec") is not None and s.get("start_sec") is not None
            )
            coverage = seg_total / float(reported_duration) if float(reported_duration) > 0 else 0
            scores.va5_segment_coverage = min(1.0, coverage / 0.6) if coverage < 0.6 else 1.0
            check_count += 1
            total_score += scores.va5_segment_coverage
        except (ValueError, TypeError):
            scores.va5_segment_coverage = 0.0
            check_count += 1

    # VA-6: Hook window (hook fields non-null when transcript exists)
    has_transcript = bool(transcript and len(str(transcript).strip()) > 20)
    hook_spoken = parsed.get("hook_transcript_spoken")
    hook_type = parsed.get("hook_type")
    if has_transcript:
        hook_fields_present = sum([
            bool(hook_spoken),
            bool(hook_type),
            bool(parsed.get("hook_visual_description")),
        ])
        scores.va6_hook_window = hook_fields_present / 3.0
    else:
        scores.va6_hook_window = 1.0  # N/A when no transcript
    check_count += 1
    total_score += scores.va6_hook_window

    # VA-7: JSON completeness (all required top-level keys present)
    required_keys = [
        "video_duration_sec", "full_transcript", "storyboard",
        "people_detected", "has_talking_head", "production_quality", "format_type",
    ]
    present = sum(1 for k in required_keys if parsed.get(k) is not None)
    scores.va7_json_completeness = present / len(required_keys)
    check_count += 1
    total_score += scores.va7_json_completeness

    # VA-8: Overlay coherence (if text_overlays empty, confidence should be 0.0)
    overlays = parsed.get("text_overlays") or []
    overlay_conf = parsed.get("text_overlay_confidence")
    if not overlays:
        # No overlays — confidence should be 0 or null
        if overlay_conf is None or float(overlay_conf or 0) == 0.0:
            scores.va8_overlay_coherence = 1.0
        else:
            scores.va8_overlay_coherence = 0.0
    else:
        # Has overlays — confidence should be > 0
        if overlay_conf is not None and float(overlay_conf) > 0:
            scores.va8_overlay_coherence = 1.0
        else:
            scores.va8_overlay_coherence = 0.5
    check_count += 1
    total_score += scores.va8_overlay_coherence

    # Overall score
    scores.overall_score = round(total_score / check_count, 3) if check_count > 0 else 0.0

    return scores


# ============================================================================
# Service
# ============================================================================

class InstagramAnalysisService:
    """Two-pass Gemini analysis of Instagram content.

    Pass 1 (Flash): structural extraction — transcript, overlays, storyboard,
        hook analysis, people detection.
    Pass 2 (Pro, approved candidates only): production shot sheet — per-beat
        camera, subject, lighting, transition details.

    Video analysis stored in ad_video_analysis (source_type='instagram_scrape').
    Image analysis stored in instagram_image_analysis.
    """

    STORAGE_BUCKET = "instagram-media"

    # Gemini Files API limits
    MAX_VIDEO_DURATION_SEC = 90  # Gemini processes up to ~90s reliably
    GEMINI_UPLOAD_TIMEOUT = 180  # seconds to wait for processing

    def __init__(self, supabase: Optional[Client] = None):
        """Initialize InstagramAnalysisService.

        Args:
            supabase: Optional Supabase client. Creates one if not provided.
        """
        self.supabase = supabase or get_supabase_client()

    # ========================================================================
    # Public API
    # ========================================================================

    async def analyze_video(
        self,
        media_id: str,
        organization_id: str,
    ) -> Optional[Dict]:
        """Pass 1: Structural extraction of a video using Gemini Flash.

        Downloads the video from Supabase storage, uploads to Gemini Files API,
        runs Flash analysis, validates with VA-1 through VA-8 checks, and
        stores results in ad_video_analysis.

        Args:
            media_id: UUID of the instagram_media record.
            organization_id: Organization UUID for multi-tenant isolation.

        Returns:
            Dict with analysis results and eval scores, or None on failure.
        """
        temp_path = None
        gemini_file = None
        client = None

        try:
            from google import genai

            # 1. Get media record
            media = self._get_media_record(media_id)
            if not media:
                logger.error(f"Media record {media_id} not found")
                return None

            if media.get("media_type") != "video":
                logger.warning(f"Media {media_id} is not a video (type={media.get('media_type')})")
                return None

            storage_path = media.get("storage_path")
            if not storage_path:
                logger.error(f"Media {media_id} has no storage_path")
                return None

            post_id = media["post_id"]

            # Resolve real org_id for superuser "all" mode
            if organization_id == "all":
                organization_id = self._resolve_org_id_from_post(post_id) or organization_id

            # 2. Compute input hash
            input_hash = compute_input_hash(
                storage_path,
                file_size=media.get("file_size_bytes"),
            )

            # 3. Check for existing analysis (idempotent)
            existing = self._check_existing_video_analysis(
                post_id, input_hash, PASS1_PROMPT_VERSION
            )
            if existing:
                logger.info(f"Analysis already exists for media {media_id}")
                return existing

            # 4. Download video from storage
            video_content = self._download_from_storage(storage_path)
            if not video_content:
                return self._save_error_analysis(
                    post_id, media_id, organization_id, input_hash,
                    "Failed to download video from storage"
                )

            logger.info(f"Downloaded video for media {media_id}: {len(video_content) / 1024 / 1024:.1f}MB")

            # 5. Write to temp file
            ext = ".mp4" if "mp4" in storage_path else ".mov"
            temp_file = tempfile.NamedTemporaryFile(suffix=ext, delete=False)
            temp_file.write(video_content)
            temp_file.close()
            temp_path = temp_file.name

            # 6. Upload to Gemini Files API
            api_key = os.getenv("GEMINI_API_KEY")
            if not api_key:
                return self._save_error_analysis(
                    post_id, media_id, organization_id, input_hash,
                    "GEMINI_API_KEY not set"
                )

            client = genai.Client(api_key=api_key)
            logger.info(f"Uploading video to Gemini Files API (media {media_id})")
            gemini_file = client.files.upload(file=str(temp_path))

            # 7. Wait for processing
            wait_time = 0
            while gemini_file.state.name == "PROCESSING" and wait_time < self.GEMINI_UPLOAD_TIMEOUT:
                time_module.sleep(3)
                wait_time += 3
                gemini_file = client.files.get(name=gemini_file.name)

            if gemini_file.state.name == "FAILED":
                return self._save_error_analysis(
                    post_id, media_id, organization_id, input_hash,
                    "Gemini video processing failed"
                )
            if gemini_file.state.name == "PROCESSING":
                return self._save_error_analysis(
                    post_id, media_id, organization_id, input_hash,
                    "Gemini video processing timed out"
                )

            # 8. Run Pass 1 analysis (Flash)
            response = client.models.generate_content(
                model=FLASH_MODEL,
                contents=[gemini_file, PASS1_VIDEO_PROMPT],
            )

            # 9. Parse response
            result_text = response.text.strip() if response.text else ""
            parsed = _parse_json_response(result_text)

            if not parsed:
                return self._save_error_analysis(
                    post_id, media_id, organization_id, input_hash,
                    "Failed to parse Gemini response",
                    raw_text=result_text[:5000],
                )

            # 10. Get actual duration from post metadata for VA-1
            post = self._get_post_record(post_id)
            actual_duration = float(post.get("length_sec")) if post and post.get("length_sec") else None

            # 11. Run eval checks
            eval_scores = run_eval_checks(parsed, actual_duration_sec=actual_duration)

            # 12. Compute hook fingerprint
            hook_fingerprint = None
            hook_spoken = parsed.get("hook_transcript_spoken")
            hook_overlay = parsed.get("hook_transcript_overlay")
            hook_visual = parsed.get("hook_visual_description")
            if hook_spoken or hook_overlay or hook_visual:
                from .video_analysis_service import compute_hook_fingerprint
                hook_fingerprint = compute_hook_fingerprint(hook_spoken, hook_overlay, hook_visual)

            # 13. Determine status
            status = "ok" if eval_scores.overall_score >= 0.6 else "validation_failed"

            # 14. Save to ad_video_analysis
            analysis_data = {
                "organization_id": organization_id,
                "brand_id": self._get_brand_id_for_post(post_id, organization_id),
                "meta_ad_id": None,
                "source_type": "instagram_scrape",
                "source_post_id": post_id,
                "input_hash": input_hash,
                "prompt_version": PASS1_PROMPT_VERSION,
                "storage_path": storage_path,
                "status": status,
                "model_used": FLASH_MODEL,
                # Transcript
                "full_transcript": parsed.get("full_transcript"),
                "transcript_segments": parsed.get("transcript_segments"),
                # Overlays
                "text_overlays": parsed.get("text_overlays", []),
                "text_overlay_confidence": parsed.get("text_overlay_confidence"),
                # Hooks
                "hook_transcript_spoken": hook_spoken,
                "hook_transcript_overlay": hook_overlay,
                "hook_fingerprint": hook_fingerprint,
                "hook_type": parsed.get("hook_type"),
                "hook_effectiveness_signals": parsed.get("hook_effectiveness_signals"),
                "hook_visual_description": hook_visual,
                "hook_visual_elements": parsed.get("hook_visual_elements", []),
                "hook_visual_type": parsed.get("hook_visual_type"),
                # Storyboard
                "storyboard": parsed.get("storyboard"),
                # People
                "people_detected": parsed.get("people_detected", 0),
                "has_talking_head": parsed.get("has_talking_head", False),
                # Production
                "video_duration_sec": parsed.get("video_duration_sec"),
                "production_quality": parsed.get("production_quality"),
                "format_type": parsed.get("format_type"),
                # Eval scores
                "eval_scores": eval_scores.to_dict(),
                # Raw
                "raw_response": parsed,
            }

            result = self._insert_video_analysis(analysis_data)

            logger.info(
                f"Pass 1 analysis complete for media {media_id}: "
                f"status={status}, eval={eval_scores.overall_score:.2f}, "
                f"duration={parsed.get('video_duration_sec')}s, "
                f"talking_head={parsed.get('has_talking_head')}"
            )

            return result

        except Exception as e:
            logger.error(f"Video analysis failed for media {media_id}: {e}", exc_info=True)
            return None

        finally:
            if gemini_file and client:
                try:
                    client.files.delete(name=gemini_file.name)
                except Exception:
                    pass
            if temp_path and Path(temp_path).exists():
                try:
                    Path(temp_path).unlink()
                except Exception:
                    pass

    async def analyze_image(
        self,
        media_id: str,
        organization_id: str,
    ) -> Optional[Dict]:
        """Analyze a single image using Gemini Flash.

        Args:
            media_id: UUID of the instagram_media record.
            organization_id: Organization UUID.

        Returns:
            Dict with analysis results, or None on failure.
        """
        temp_path = None

        try:
            from google import genai
            from google.genai import types

            # 1. Get media record
            media = self._get_media_record(media_id)
            if not media:
                return None

            storage_path = media.get("storage_path")
            if not storage_path:
                return None

            post_id = media["post_id"]

            # Resolve real org_id for superuser "all" mode
            if organization_id == "all":
                organization_id = self._resolve_org_id_from_post(post_id) or organization_id

            # 2. Compute input hash
            input_hash = compute_input_hash(
                storage_path, file_size=media.get("file_size_bytes")
            )

            # 3. Check existing
            existing = self._check_existing_image_analysis(
                post_id, media_id, input_hash, IMAGE_PROMPT_VERSION
            )
            if existing:
                return existing

            # 4. Download image
            image_content = self._download_from_storage(storage_path)
            if not image_content:
                return None

            # 5. Write temp file
            ext = Path(storage_path).suffix or ".jpg"
            temp_file = tempfile.NamedTemporaryFile(suffix=ext, delete=False)
            temp_file.write(image_content)
            temp_file.close()
            temp_path = temp_file.name

            # 6. Upload to Gemini
            api_key = os.getenv("GEMINI_API_KEY")
            if not api_key:
                return None

            client = genai.Client(api_key=api_key)
            gemini_file = client.files.upload(file=str(temp_path))

            # Wait for processing
            wait_time = 0
            while gemini_file.state.name == "PROCESSING" and wait_time < 60:
                time_module.sleep(2)
                wait_time += 2
                gemini_file = client.files.get(name=gemini_file.name)

            if gemini_file.state.name != "ACTIVE":
                logger.error(f"Gemini image processing failed for media {media_id}")
                return None

            # 7. Analyze
            response = client.models.generate_content(
                model=FLASH_MODEL,
                contents=[gemini_file, IMAGE_ANALYSIS_PROMPT],
            )

            result_text = response.text.strip() if response.text else ""
            parsed = _parse_json_response(result_text)

            if not parsed:
                logger.error(f"Failed to parse image analysis for media {media_id}")
                return None

            # 8. Save to instagram_image_analysis
            analysis_data = {
                "organization_id": organization_id,
                "post_id": post_id,
                "media_id": media_id,
                "status": "ok",
                "image_description": parsed.get("image_description"),
                "image_style": parsed.get("image_style"),
                "image_elements": parsed.get("image_elements"),
                "image_text_content": parsed.get("image_text_content"),
                "recreation_notes": parsed.get("recreation_notes"),
                "people_detected": parsed.get("people_detected", 0),
                "has_talking_head": parsed.get("has_talking_head", False),
                "people_details": parsed.get("people_details"),
                "model_used": FLASH_MODEL,
                "prompt_version": IMAGE_PROMPT_VERSION,
                "input_hash": input_hash,
                "raw_response": parsed,
                "analyzed_at": datetime.now(timezone.utc).isoformat(),
            }

            result = self.supabase.table("instagram_image_analysis").insert(
                analysis_data
            ).execute()

            saved = result.data[0] if result.data else analysis_data

            # Cleanup Gemini file
            try:
                client.files.delete(name=gemini_file.name)
            except Exception:
                pass

            logger.info(f"Image analysis complete for media {media_id}")
            return saved

        except Exception as e:
            logger.error(f"Image analysis failed for media {media_id}: {e}", exc_info=True)
            return None

        finally:
            if temp_path and Path(temp_path).exists():
                try:
                    Path(temp_path).unlink()
                except Exception:
                    pass

    async def analyze_carousel(
        self,
        post_id: str,
        organization_id: str,
    ) -> List[Dict]:
        """Analyze all images in a carousel post.

        Args:
            post_id: UUID of the post.
            organization_id: Organization UUID.

        Returns:
            List of analysis results for each carousel item.
        """
        media_records = (
            self.supabase.table("instagram_media")
            .select("id, media_type")
            .eq("post_id", post_id)
            .eq("download_status", "downloaded")
            .order("media_index")
            .execute()
        )

        if not media_records.data:
            return []

        results = []
        for media in media_records.data:
            if media["media_type"] == "image":
                result = await self.analyze_image(media["id"], organization_id)
            elif media["media_type"] == "video":
                result = await self.analyze_video(media["id"], organization_id)
            else:
                continue

            if result:
                results.append(result)

        return results

    async def deep_production_analysis(
        self,
        analysis_id: str,
    ) -> Optional[Dict]:
        """Pass 2: Production shot sheet analysis using Gemini Pro.

        Only for approved candidates. Takes an existing Pass 1 analysis and
        adds detailed per-beat production information.

        Args:
            analysis_id: UUID of the ad_video_analysis record (from Pass 1).

        Returns:
            Updated analysis dict with production_storyboard, or None on failure.
        """
        temp_path = None
        gemini_file = None
        client = None

        try:
            from google import genai

            # 1. Get existing analysis
            analysis = self.supabase.table("ad_video_analysis").select(
                "id, storage_path, source_post_id, organization_id, production_storyboard"
            ).eq("id", analysis_id).single().execute()

            if not analysis.data:
                logger.error(f"Analysis {analysis_id} not found")
                return None

            row = analysis.data

            # Skip if already has production storyboard
            if row.get("production_storyboard"):
                logger.info(f"Analysis {analysis_id} already has production storyboard")
                return row

            storage_path = row.get("storage_path")
            if not storage_path:
                logger.error(f"Analysis {analysis_id} has no storage_path")
                return None

            # 2. Download video
            video_content = self._download_from_storage(storage_path)
            if not video_content:
                return None

            ext = ".mp4" if "mp4" in storage_path else ".mov"
            temp_file = tempfile.NamedTemporaryFile(suffix=ext, delete=False)
            temp_file.write(video_content)
            temp_file.close()
            temp_path = temp_file.name

            # 3. Upload and analyze with Pro model
            api_key = os.getenv("GEMINI_API_KEY")
            if not api_key:
                return None

            client = genai.Client(api_key=api_key)
            gemini_file = client.files.upload(file=str(temp_path))

            wait_time = 0
            while gemini_file.state.name == "PROCESSING" and wait_time < self.GEMINI_UPLOAD_TIMEOUT:
                time_module.sleep(3)
                wait_time += 3
                gemini_file = client.files.get(name=gemini_file.name)

            if gemini_file.state.name != "ACTIVE":
                logger.error(f"Gemini processing failed for Pass 2 analysis {analysis_id}")
                return None

            response = client.models.generate_content(
                model=PRO_MODEL,
                contents=[gemini_file, PASS2_PRODUCTION_PROMPT],
            )

            result_text = response.text.strip() if response.text else ""
            parsed = _parse_json_response(result_text)

            if not parsed or not parsed.get("production_storyboard"):
                logger.error(f"Failed to parse Pass 2 response for {analysis_id}")
                return None

            # 4. Update the existing analysis row with production storyboard
            update_data = {
                "production_storyboard": parsed.get("production_storyboard"),
            }

            self.supabase.table("ad_video_analysis").update(
                update_data
            ).eq("id", analysis_id).execute()

            logger.info(
                f"Pass 2 production analysis complete for {analysis_id}: "
                f"{len(parsed.get('production_storyboard', []))} beats"
            )

            # Return updated record
            updated = self.supabase.table("ad_video_analysis").select("*").eq(
                "id", analysis_id
            ).single().execute()
            return updated.data if updated.data else None

        except Exception as e:
            logger.error(f"Pass 2 analysis failed for {analysis_id}: {e}", exc_info=True)
            return None

        finally:
            if gemini_file and client:
                try:
                    client.files.delete(name=gemini_file.name)
                except Exception:
                    pass
            if temp_path and Path(temp_path).exists():
                try:
                    Path(temp_path).unlink()
                except Exception:
                    pass

    async def batch_analyze_outliers(
        self,
        brand_id: str,
        organization_id: str,
        limit: int = 20,
    ) -> Dict:
        """Batch analyze all outlier posts that have downloaded media.

        Runs Pass 1 (Flash) analysis on each video/image that hasn't been
        analyzed yet.

        Args:
            brand_id: Brand UUID.
            organization_id: Organization UUID.
            limit: Maximum number of posts to analyze.

        Returns:
            Dict with batch results.
        """
        # Get outlier posts with downloaded media
        from .instagram_content_service import InstagramContentService
        content_service = InstagramContentService(supabase=self.supabase)

        watched = content_service.list_watched_accounts(brand_id, organization_id)
        if not watched:
            return {"analyzed": 0, "skipped": 0, "failed": 0, "errors": []}

        account_ids = [w["account_id"] for w in watched]

        # Find outlier posts
        outlier_posts = []
        batch_size = 50
        for i in range(0, len(account_ids), batch_size):
            batch = account_ids[i:i + batch_size]
            result = (
                self.supabase.table("posts")
                .select("id, media_type, video_type")
                .in_("account_id", batch)
                .eq("is_outlier", True)
                .order("outlier_score", desc=True)
                .limit(limit)
                .execute()
            )
            if result.data:
                outlier_posts.extend(result.data)

        results = {"analyzed": 0, "skipped": 0, "failed": 0, "errors": []}

        for post in outlier_posts[:limit]:
            post_id = post["id"]

            # Get downloaded media for this post
            media_records = (
                self.supabase.table("instagram_media")
                .select("id, media_type, storage_path")
                .eq("post_id", post_id)
                .eq("download_status", "downloaded")
                .order("media_index")
                .execute()
            )

            if not media_records.data:
                results["skipped"] += 1
                continue

            for media in media_records.data:
                try:
                    if media["media_type"] == "video":
                        result = await self.analyze_video(media["id"], organization_id)
                    elif media["media_type"] == "image":
                        result = await self.analyze_image(media["id"], organization_id)
                    else:
                        continue

                    if result:
                        results["analyzed"] += 1
                    else:
                        results["failed"] += 1
                except Exception as e:
                    logger.error(f"Batch analysis failed for media {media['id']}: {e}")
                    results["failed"] += 1
                    results["errors"].append({
                        "media_id": media["id"],
                        "post_id": post_id,
                        "error": str(e)[:200],
                    })

        logger.info(
            f"Batch analysis for brand {brand_id}: "
            f"{results['analyzed']} analyzed, {results['skipped']} skipped, "
            f"{results['failed']} failed"
        )
        return results

    def get_analysis(self, post_id: str) -> Optional[Dict]:
        """Get the latest analysis for a post (video or image).

        Args:
            post_id: UUID of the post.

        Returns:
            Dict with analysis data, or None if not analyzed.
        """
        # Try video analysis first
        video = (
            self.supabase.table("ad_video_analysis")
            .select("*")
            .eq("source_post_id", post_id)
            .eq("source_type", "instagram_scrape")
            .order("analyzed_at", desc=True)
            .limit(1)
            .execute()
        )
        if video.data:
            return {**video.data[0], "_analysis_type": "video"}

        # Try image analysis
        image = (
            self.supabase.table("instagram_image_analysis")
            .select("*")
            .eq("post_id", post_id)
            .order("analyzed_at", desc=True)
            .limit(1)
            .execute()
        )
        if image.data:
            return {**image.data[0], "_analysis_type": "image"}

        return None

    def get_analyses_for_brand(
        self,
        brand_id: str,
        organization_id: str,
        status_filter: Optional[str] = None,
        limit: int = 50,
    ) -> List[Dict]:
        """Get all video analyses for a brand's Instagram content.

        Args:
            brand_id: Brand UUID.
            organization_id: Organization UUID.
            status_filter: Optional status filter ('ok', 'validation_failed', 'error').
            limit: Maximum results.

        Returns:
            List of analysis records.
        """
        query = (
            self.supabase.table("ad_video_analysis")
            .select("*, posts:source_post_id(id, post_url, caption, views, likes, comments, media_type, accounts(platform_username))")
            .eq("source_type", "instagram_scrape")
        )

        # Multi-tenant filter (unless superuser "all" mode)
        if organization_id != "all":
            query = query.eq("organization_id", organization_id)

        # Brand filter via the post's account chain isn't direct,
        # so we filter by brand_id on the analysis itself
        if brand_id:
            query = query.eq("brand_id", brand_id)

        if status_filter:
            query = query.eq("status", status_filter)

        query = query.order("analyzed_at", desc=True).limit(limit)
        result = query.execute()
        return result.data or []

    # ========================================================================
    # Internal helpers
    # ========================================================================

    def _get_media_record(self, media_id: str) -> Optional[Dict]:
        """Get a single instagram_media record."""
        result = (
            self.supabase.table("instagram_media")
            .select("*")
            .eq("id", media_id)
            .single()
            .execute()
        )
        return result.data if result.data else None

    def _get_post_record(self, post_id: str) -> Optional[Dict]:
        """Get a single post record."""
        result = (
            self.supabase.table("posts")
            .select("id, length_sec, views, likes, comments, media_type, account_id")
            .eq("id", str(post_id))
            .single()
            .execute()
        )
        return result.data if result.data else None

    def _get_brand_id_for_post(self, post_id: str, organization_id: str) -> Optional[str]:
        """Resolve brand_id for a post via watched accounts chain.

        post -> account -> instagram_watched_accounts -> brand_id
        """
        try:
            post = self._get_post_record(post_id)
            if not post or not post.get("account_id"):
                return None

            watched_query = (
                self.supabase.table("instagram_watched_accounts")
                .select("brand_id")
                .eq("account_id", post["account_id"])
            )
            if organization_id != "all":
                watched_query = watched_query.eq("organization_id", organization_id)
            watched = (
                watched_query
                .eq("is_active", True)
                .limit(1)
                .execute()
            )
            if watched.data:
                return watched.data[0]["brand_id"]
            return None
        except Exception as e:
            logger.warning(f"Could not resolve brand_id for post {post_id}: {e}")
            return None

    def _resolve_org_id_from_post(self, post_id: str) -> Optional[str]:
        """Resolve the real organization_id for a post via watched accounts."""
        try:
            brand_id = self._get_brand_id_for_post(post_id, "all")
            if not brand_id:
                return None
            brand = (
                self.supabase.table("brands")
                .select("organization_id")
                .eq("id", brand_id)
                .limit(1)
                .execute()
            )
            if brand.data:
                return brand.data[0]["organization_id"]
            return None
        except Exception as e:
            logger.warning(f"Could not resolve org_id for post {post_id}: {e}")
            return None

    def _download_from_storage(self, storage_path: str) -> Optional[bytes]:
        """Download a file from Supabase storage.

        Args:
            storage_path: Path within the instagram-media bucket.

        Returns:
            File contents as bytes, or None on failure.
        """
        try:
            content = self.supabase.storage.from_(self.STORAGE_BUCKET).download(storage_path)
            return content
        except Exception as e:
            logger.error(f"Error downloading from storage {storage_path}: {e}")
            return None

    def _check_existing_video_analysis(
        self, post_id: str, input_hash: str, prompt_version: str
    ) -> Optional[Dict]:
        """Check if video analysis already exists."""
        try:
            result = (
                self.supabase.table("ad_video_analysis")
                .select("*")
                .eq("source_post_id", post_id)
                .eq("input_hash", input_hash)
                .eq("prompt_version", prompt_version)
                .limit(1)
                .execute()
            )
            return result.data[0] if result.data else None
        except Exception:
            return None

    def _check_existing_image_analysis(
        self, post_id: str, media_id: str, input_hash: str, prompt_version: str
    ) -> Optional[Dict]:
        """Check if image analysis already exists."""
        try:
            result = (
                self.supabase.table("instagram_image_analysis")
                .select("*")
                .eq("post_id", post_id)
                .eq("media_id", media_id)
                .eq("input_hash", input_hash)
                .eq("prompt_version", prompt_version)
                .limit(1)
                .execute()
            )
            return result.data[0] if result.data else None
        except Exception:
            return None

    def _insert_video_analysis(self, data: Dict) -> Optional[Dict]:
        """Insert a new video analysis row (immutable)."""
        try:
            result = self.supabase.table("ad_video_analysis").insert(data).execute()
            return result.data[0] if result.data else None
        except Exception as e:
            error_str = str(e)
            if "23505" in error_str or "duplicate key" in error_str.lower():
                logger.info("Duplicate video analysis — returning existing")
                return self._check_existing_video_analysis(
                    data.get("source_post_id", ""),
                    data.get("input_hash", ""),
                    data.get("prompt_version", ""),
                )
            logger.error(f"Error inserting video analysis: {e}")
            return None

    def _save_error_analysis(
        self,
        post_id: str,
        media_id: str,
        organization_id: str,
        input_hash: str,
        error_message: str,
        raw_text: Optional[str] = None,
    ) -> Optional[Dict]:
        """Save an error analysis record."""
        data = {
            "organization_id": organization_id,
            "brand_id": self._get_brand_id_for_post(post_id, organization_id),
            "meta_ad_id": None,
            "source_type": "instagram_scrape",
            "source_post_id": post_id,
            "input_hash": input_hash,
            "prompt_version": PASS1_PROMPT_VERSION,
            "status": "error",
            "error_message": error_message,
            "model_used": FLASH_MODEL,
        }
        if raw_text:
            data["raw_response"] = {"raw_text": raw_text}

        return self._insert_video_analysis(data)
