"""
VideoAnalysisService - Deep video analysis with Gemini Files API.

Provides comprehensive video analysis including:
- Full transcript with timestamps
- Text overlays with timestamps (best effort)
- Hook extraction (spoken + visual)
- Storyboard with scene changes
- Messaging extraction (benefits, features, angles, JTBDs)
- Awareness level classification

Results are stored in ad_video_analysis table with immutable, versioned rows.
"""

import hashlib
import json
import logging
import os
import re
import tempfile
import time as time_module
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple
from uuid import UUID

from supabase import Client

logger = logging.getLogger(__name__)

# Current prompt version - increment when prompt changes significantly
PROMPT_VERSION = "v1"

# Deep video analysis prompt - extracts comprehensive structured data
DEEP_VIDEO_ANALYSIS_PROMPT = """Analyze this video advertisement and extract detailed structured data.

**CRITICAL REQUIREMENTS:**
1. Watch the ENTIRE video, not just the first few seconds
2. Provide accurate timestamps as floating-point seconds (e.g., 3.5, 12.0)
3. Transcripts are MANDATORY - even if approximate
4. Text overlays are BEST EFFORT - include confidence score

**AD COPY (for context):**
{ad_copy}

**EXTRACT THE FOLLOWING (return as JSON):**

```json
{{
  "video_duration_sec": <integer seconds>,

  "full_transcript": "<complete spoken text from the video>",

  "transcript_segments": [
    {{"start_sec": 0.0, "end_sec": 3.5, "text": "...", "speaker": "narrator|testimonial|founder"}},
    ...
  ],

  "text_overlays": [
    {{"start_sec": 0.0, "end_sec": 5.0, "text": "...", "position": "top|center|bottom", "style": "bold|regular"}},
    ...
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

  "storyboard": [
    {{"timestamp_sec": 0.0, "scene_description": "...", "key_elements": ["..."], "text_overlay": "..."}},
    {{"timestamp_sec": 5.0, "scene_description": "...", "key_elements": ["..."], "text_overlay": null}},
    ...
  ],

  "benefits_shown": ["benefit 1", "benefit 2"],
  "features_demonstrated": ["feature 1", "feature 2"],
  "pain_points_addressed": ["pain point 1", "pain point 2"],
  "angles_used": ["angle 1", "angle 2"],
  "jobs_to_be_done": ["jtbd 1", "jtbd 2"],
  "claims_made": [
    {{"claim": "...", "timestamp_sec": 10.5, "proof_shown": true}}
  ],

  "awareness_level": "<unaware|problem_aware|solution_aware|product_aware|most_aware>",
  "awareness_confidence": 0.85,

  "target_persona": {{
    "demographic": "...",
    "psychographic": "...",
    "pain_points": ["..."]
  }},
  "emotional_drivers": ["curiosity", "fear of missing out", "desire for transformation"],

  "production_quality": "<raw|polished|professional>",
  "format_type": "<ugc|professional|testimonial|demo|animation|mixed>"
}}
```

**IMPORTANT:**
- Scene changes in storyboard: mark when visual context significantly changes, or every 30 seconds if no changes
- Timestamps must be ordered and non-overlapping for transcript_segments
- If you can't detect text overlays reliably, set text_overlays to [] and text_overlay_confidence to 0.0
- Hook analysis: evaluate first 3-5 seconds for both spoken and visual hooks
- Return ONLY valid JSON, no additional text
"""


@dataclass
class VideoAsset:
    """Video asset from meta_ad_assets table."""
    meta_ad_id: str
    brand_id: UUID
    storage_path: str
    video_id: Optional[str] = None
    creative_id: Optional[str] = None
    etag: Optional[str] = None
    updated_at: Optional[datetime] = None


@dataclass
class VideoAnalysisResult:
    """Result of deep video analysis."""
    meta_ad_id: str
    brand_id: UUID
    input_hash: str
    prompt_version: str
    storage_path: str

    # Status
    status: str = "ok"  # ok, validation_failed, error
    validation_errors: List[str] = field(default_factory=list)
    error_message: Optional[str] = None

    # Transcript
    full_transcript: Optional[str] = None
    transcript_segments: Optional[List[Dict]] = None

    # Overlays
    text_overlays: List[Dict] = field(default_factory=list)
    text_overlay_confidence: Optional[float] = None

    # Hooks
    hook_transcript_spoken: Optional[str] = None
    hook_transcript_overlay: Optional[str] = None
    hook_fingerprint: Optional[str] = None
    hook_type: Optional[str] = None
    hook_effectiveness_signals: Optional[Dict] = None

    # Storyboard
    storyboard: Optional[List[Dict]] = None

    # Messaging
    benefits_shown: List[str] = field(default_factory=list)
    features_demonstrated: List[str] = field(default_factory=list)
    pain_points_addressed: List[str] = field(default_factory=list)
    angles_used: List[str] = field(default_factory=list)
    jobs_to_be_done: List[str] = field(default_factory=list)
    claims_made: Optional[List[Dict]] = None

    # Psychology
    awareness_level: Optional[str] = None
    awareness_confidence: Optional[float] = None
    target_persona: Optional[Dict] = None
    emotional_drivers: List[str] = field(default_factory=list)

    # Production
    video_duration_sec: Optional[int] = None
    production_quality: Optional[str] = None
    format_type: Optional[str] = None

    # Provenance
    video_id: Optional[str] = None
    creative_id: Optional[str] = None
    raw_response: Optional[Dict] = None
    model_used: Optional[str] = None


def compute_input_hash(
    storage_path: str,
    etag: Optional[str] = None,
    updated_at: Optional[datetime] = None
) -> str:
    """Compute deterministic input hash for video analysis versioning.

    Uses etag if available (preferred), otherwise falls back to updated_at.
    This ensures we can detect when a video file has changed.

    Args:
        storage_path: Supabase storage path.
        etag: File ETag from storage metadata (preferred).
        updated_at: File updated_at timestamp (fallback).

    Returns:
        SHA256 hash string.

    Raises:
        ValueError: If neither etag nor updated_at is provided.
    """
    if etag:
        source = f"{storage_path}:{etag}"
    elif updated_at:
        source = f"{storage_path}:{updated_at.isoformat()}"
    else:
        raise ValueError("Either etag or updated_at required for input_hash")

    return hashlib.sha256(source.encode()).hexdigest()


def compute_hook_fingerprint(spoken: Optional[str], overlay: Optional[str]) -> str:
    """Compute normalized hook fingerprint for deduplication.

    Normalizes spoken + overlay text and computes SHA256 hash.

    Args:
        spoken: Spoken hook text (may be None).
        overlay: Text overlay hook (may be None).

    Returns:
        SHA256 hash string.
    """
    # 1. Lowercase
    spoken_norm = (spoken or "").lower()
    overlay_norm = (overlay or "").lower()

    # 2. Strip punctuation
    spoken_norm = re.sub(r'[^\w\s]', '', spoken_norm)
    overlay_norm = re.sub(r'[^\w\s]', '', overlay_norm)

    # 3. Collapse whitespace
    spoken_norm = ' '.join(spoken_norm.split())
    overlay_norm = ' '.join(overlay_norm.split())

    # 4. Concatenate with delimiters
    combined = f"spoken:{spoken_norm}|overlay:{overlay_norm}"

    # 5. SHA256 hash
    return hashlib.sha256(combined.encode()).hexdigest()


def validate_analysis_timestamps(data: Dict) -> Tuple[bool, List[str]]:
    """Validate timestamp ordering and required fields.

    Validates:
    - transcript_segments: ordered, non-overlapping, has required fields
    - text_overlays: has start_sec and text
    - storyboard: has timestamp_sec

    Args:
        data: Parsed analysis response.

    Returns:
        Tuple of (is_valid, errors list).
    """
    errors = []

    # Validate transcript_segments: ordered, non-overlapping
    segments = data.get("transcript_segments") or []
    last_end = 0.0
    for i, seg in enumerate(segments):
        if not isinstance(seg, dict):
            errors.append(f"transcript_segments[{i}] is not a dict")
            continue
        if "start_sec" not in seg or "end_sec" not in seg or "text" not in seg:
            errors.append(f"transcript_segments[{i}] missing required fields (start_sec, end_sec, text)")
        elif seg["start_sec"] < last_end - 0.1:  # Allow small overlap tolerance
            errors.append(f"transcript_segments[{i}] overlaps with previous (start={seg['start_sec']}, prev_end={last_end})")
        else:
            last_end = seg["end_sec"]

    # Validate text_overlays: has start_sec, text
    overlays = data.get("text_overlays") or []
    for i, ovl in enumerate(overlays):
        if not isinstance(ovl, dict):
            errors.append(f"text_overlays[{i}] is not a dict")
            continue
        if "start_sec" not in ovl or "text" not in ovl:
            errors.append(f"text_overlays[{i}] missing start_sec or text")
        # Normalize duration-only to start/end if needed
        if "duration_sec" in ovl and "end_sec" not in ovl:
            ovl["end_sec"] = ovl["start_sec"] + ovl.pop("duration_sec")

    # Validate storyboard
    boards = data.get("storyboard") or []
    for i, scene in enumerate(boards):
        if not isinstance(scene, dict):
            errors.append(f"storyboard[{i}] is not a dict")
            continue
        if "timestamp_sec" not in scene:
            errors.append(f"storyboard[{i}] missing timestamp_sec")

    return (len(errors) == 0, errors)


class VideoAnalysisService:
    """Service for deep video analysis using Gemini Files API.

    Analyzes entire videos (not just first few seconds) to extract:
    - Full transcript with timestamps
    - Text overlays with timestamps
    - Hook analysis (spoken + visual)
    - Storyboard with scene changes
    - Messaging extraction

    Results are stored as immutable, versioned rows in ad_video_analysis.
    """

    def __init__(self, supabase: Client):
        """Initialize VideoAnalysisService.

        Args:
            supabase: Supabase client instance.
        """
        self.supabase = supabase

    async def get_video_asset(
        self,
        meta_ad_id: str,
        brand_id: UUID,
    ) -> Optional[VideoAsset]:
        """Get video asset metadata from meta_ad_assets.

        Args:
            meta_ad_id: Meta ad ID.
            brand_id: Brand UUID.

        Returns:
            VideoAsset if found, None otherwise.
        """
        try:
            result = self.supabase.table("meta_ad_assets").select(
                "storage_path, meta_video_id, created_at"
            ).eq(
                "meta_ad_id", meta_ad_id
            ).eq(
                "brand_id", str(brand_id)
            ).eq(
                "asset_type", "video"
            ).eq(
                "status", "downloaded"
            ).limit(1).execute()

            if not result.data:
                return None

            row = result.data[0]
            return VideoAsset(
                meta_ad_id=meta_ad_id,
                brand_id=brand_id,
                storage_path=row["storage_path"],
                video_id=row.get("meta_video_id"),
                # Use created_at as fallback for updated_at (meta_ad_assets doesn't have etag)
                updated_at=datetime.fromisoformat(row["created_at"].replace("Z", "+00:00"))
                if row.get("created_at") else None,
            )

        except Exception as e:
            logger.error(f"Error fetching video asset for {meta_ad_id}: {e}")
            return None

    async def download_from_storage(self, storage_path: str) -> Optional[bytes]:
        """Download a file from Supabase storage.

        Args:
            storage_path: Full storage path (e.g. "meta-ad-assets/uuid/video.mp4").

        Returns:
            File contents as bytes, or None on failure.
        """
        try:
            parts = storage_path.split("/", 1)
            if len(parts) != 2:
                logger.warning(f"Invalid storage path format: {storage_path}")
                return None

            bucket, path = parts
            content = self.supabase.storage.from_(bucket).download(path)
            return content

        except Exception as e:
            logger.error(f"Error downloading from storage {storage_path}: {e}")
            return None

    async def check_existing_analysis(
        self,
        meta_ad_id: str,
        brand_id: UUID,
        input_hash: str,
        prompt_version: str = PROMPT_VERSION,
    ) -> Optional[UUID]:
        """Check if analysis already exists for this video + version + hash.

        Used for idempotent batch processing to avoid duplicate Gemini calls.

        Args:
            meta_ad_id: Meta ad ID.
            brand_id: Brand UUID.
            input_hash: Computed input hash.
            prompt_version: Prompt version string.

        Returns:
            Analysis ID if exists, None otherwise.
        """
        try:
            result = self.supabase.table("ad_video_analysis").select(
                "id"
            ).eq(
                "meta_ad_id", meta_ad_id
            ).eq(
                "brand_id", str(brand_id)
            ).eq(
                "prompt_version", prompt_version
            ).eq(
                "input_hash", input_hash
            ).limit(1).execute()

            if result.data:
                return UUID(result.data[0]["id"])
            return None

        except Exception as e:
            logger.warning(f"Error checking existing analysis for {meta_ad_id}: {e}")
            return None

    async def deep_analyze_video(
        self,
        meta_ad_id: str,
        brand_id: UUID,
        organization_id: UUID,
        ad_copy: Optional[str] = None,
    ) -> Optional[VideoAnalysisResult]:
        """Perform deep analysis of a video ad using Gemini Files API.

        Analyzes the entire video (not just first few seconds) and extracts
        comprehensive structured data including transcript, hooks, storyboard,
        and messaging.

        Args:
            meta_ad_id: Meta ad ID.
            brand_id: Brand UUID.
            organization_id: Organization UUID.
            ad_copy: Ad copy text for context.

        Returns:
            VideoAnalysisResult on success, None if video not found or analysis fails.
        """
        temp_path = None
        gemini_file = None
        client = None

        try:
            from google import genai

            # 1. Get video asset metadata
            asset = await self.get_video_asset(meta_ad_id, brand_id)
            if not asset:
                logger.info(f"Video not in storage for {meta_ad_id}")
                return None

            # 2. Compute input hash for versioning
            input_hash = compute_input_hash(
                asset.storage_path,
                etag=asset.etag,
                updated_at=asset.updated_at,
            )

            # 3. Check if already analyzed (idempotent)
            existing_id = await self.check_existing_analysis(
                meta_ad_id, brand_id, input_hash, PROMPT_VERSION
            )
            if existing_id:
                logger.info(f"Analysis already exists for {meta_ad_id} (id={existing_id})")
                # Return existing analysis (fetch from DB)
                return await self._fetch_existing_result(existing_id)

            # 4. Download video from storage
            video_content = await self.download_from_storage(asset.storage_path)
            if not video_content:
                return VideoAnalysisResult(
                    meta_ad_id=meta_ad_id,
                    brand_id=brand_id,
                    input_hash=input_hash,
                    prompt_version=PROMPT_VERSION,
                    storage_path=asset.storage_path,
                    status="error",
                    error_message="Failed to download video from storage",
                )

            logger.info(f"Downloaded video for {meta_ad_id}: {len(video_content) / 1024 / 1024:.1f}MB")

            # 5. Write to temp file
            temp_file = tempfile.NamedTemporaryFile(suffix=".mp4", delete=False)
            temp_file.write(video_content)
            temp_file.close()
            temp_path = temp_file.name

            # 6. Upload to Gemini Files API
            api_key = os.getenv("GEMINI_API_KEY")
            if not api_key:
                return VideoAnalysisResult(
                    meta_ad_id=meta_ad_id,
                    brand_id=brand_id,
                    input_hash=input_hash,
                    prompt_version=PROMPT_VERSION,
                    storage_path=asset.storage_path,
                    status="error",
                    error_message="GEMINI_API_KEY not set",
                )

            client = genai.Client(api_key=api_key)
            logger.info(f"Uploading video to Gemini Files API ({meta_ad_id})")
            gemini_file = client.files.upload(file=str(temp_path))
            logger.info(f"Uploaded to Gemini: {gemini_file.uri}")

            # 7. Wait for processing (up to 180s for longer videos)
            max_wait = 180
            wait_time = 0
            while gemini_file.state.name == "PROCESSING" and wait_time < max_wait:
                time_module.sleep(3)
                wait_time += 3
                gemini_file = client.files.get(name=gemini_file.name)

            if gemini_file.state.name == "FAILED":
                return VideoAnalysisResult(
                    meta_ad_id=meta_ad_id,
                    brand_id=brand_id,
                    input_hash=input_hash,
                    prompt_version=PROMPT_VERSION,
                    storage_path=asset.storage_path,
                    status="error",
                    error_message="Gemini video processing failed",
                )

            if gemini_file.state.name == "PROCESSING":
                return VideoAnalysisResult(
                    meta_ad_id=meta_ad_id,
                    brand_id=brand_id,
                    input_hash=input_hash,
                    prompt_version=PROMPT_VERSION,
                    storage_path=asset.storage_path,
                    status="error",
                    error_message="Gemini video processing timed out",
                )

            # 8. Generate deep analysis
            prompt = DEEP_VIDEO_ANALYSIS_PROMPT.format(
                ad_copy=ad_copy or "(no copy available)"
            )
            response = client.models.generate_content(
                model="gemini-2.5-flash",
                contents=[gemini_file, prompt],
            )

            # 9. Parse response
            result_text = response.text.strip() if response.text else ""
            parsed = self._parse_response(result_text)

            if not parsed:
                return VideoAnalysisResult(
                    meta_ad_id=meta_ad_id,
                    brand_id=brand_id,
                    input_hash=input_hash,
                    prompt_version=PROMPT_VERSION,
                    storage_path=asset.storage_path,
                    status="error",
                    error_message="Failed to parse Gemini response",
                    raw_response={"raw_text": result_text[:5000]},
                )

            # 10. Validate timestamps
            is_valid, validation_errors = validate_analysis_timestamps(parsed)

            # 11. Compute hook fingerprint
            hook_fingerprint = None
            if parsed.get("hook_transcript_spoken") or parsed.get("hook_transcript_overlay"):
                hook_fingerprint = compute_hook_fingerprint(
                    parsed.get("hook_transcript_spoken"),
                    parsed.get("hook_transcript_overlay"),
                )

            # 12. Build result
            result = VideoAnalysisResult(
                meta_ad_id=meta_ad_id,
                brand_id=brand_id,
                input_hash=input_hash,
                prompt_version=PROMPT_VERSION,
                storage_path=asset.storage_path,
                status="ok" if is_valid else "validation_failed",
                validation_errors=validation_errors,

                # Transcript
                full_transcript=parsed.get("full_transcript"),
                transcript_segments=parsed.get("transcript_segments") if is_valid else None,

                # Overlays
                text_overlays=parsed.get("text_overlays", []) if is_valid else [],
                text_overlay_confidence=parsed.get("text_overlay_confidence"),

                # Hooks
                hook_transcript_spoken=parsed.get("hook_transcript_spoken"),
                hook_transcript_overlay=parsed.get("hook_transcript_overlay"),
                hook_fingerprint=hook_fingerprint,
                hook_type=parsed.get("hook_type"),
                hook_effectiveness_signals=parsed.get("hook_effectiveness_signals"),

                # Storyboard
                storyboard=parsed.get("storyboard") if is_valid else None,

                # Messaging
                benefits_shown=parsed.get("benefits_shown", []),
                features_demonstrated=parsed.get("features_demonstrated", []),
                pain_points_addressed=parsed.get("pain_points_addressed", []),
                angles_used=parsed.get("angles_used", []),
                jobs_to_be_done=parsed.get("jobs_to_be_done", []),
                claims_made=parsed.get("claims_made"),

                # Psychology
                awareness_level=parsed.get("awareness_level"),
                awareness_confidence=parsed.get("awareness_confidence"),
                target_persona=parsed.get("target_persona"),
                emotional_drivers=parsed.get("emotional_drivers", []),

                # Production
                video_duration_sec=parsed.get("video_duration_sec"),
                production_quality=parsed.get("production_quality"),
                format_type=parsed.get("format_type"),

                # Provenance
                video_id=asset.video_id,
                creative_id=asset.creative_id,
                raw_response=parsed,
                model_used="gemini-2.5-flash",
            )

            logger.info(
                f"Deep analysis complete for {meta_ad_id}: "
                f"status={result.status}, "
                f"awareness={result.awareness_level}, "
                f"duration={result.video_duration_sec}s, "
                f"validation_errors={len(validation_errors)}"
            )

            return result

        except Exception as e:
            logger.error(f"Deep video analysis failed for {meta_ad_id}: {e}")
            # Try to return partial result with error
            try:
                return VideoAnalysisResult(
                    meta_ad_id=meta_ad_id,
                    brand_id=brand_id,
                    input_hash=input_hash if 'input_hash' in dir() else "error",
                    prompt_version=PROMPT_VERSION,
                    storage_path=asset.storage_path if asset else "",
                    status="error",
                    error_message=str(e)[:500],
                )
            except Exception:
                return None

        finally:
            # Cleanup: delete Gemini file
            if gemini_file and client:
                try:
                    client.files.delete(name=gemini_file.name)
                except Exception:
                    pass
            # Cleanup: delete temp file
            if temp_path and Path(temp_path).exists():
                try:
                    Path(temp_path).unlink()
                except Exception:
                    pass

    def _parse_response(self, text: str) -> Optional[Dict]:
        """Parse JSON response from Gemini.

        Handles markdown code blocks and extracts JSON.

        Args:
            text: Raw response text.

        Returns:
            Parsed dict or None if parsing fails.
        """
        if not text:
            return None

        # Try to extract JSON from markdown code block
        json_match = re.search(r'```(?:json)?\s*([\s\S]*?)\s*```', text)
        if json_match:
            text = json_match.group(1)

        try:
            return json.loads(text)
        except json.JSONDecodeError as e:
            logger.warning(f"Failed to parse JSON response: {e}")
            return None

    async def _fetch_existing_result(self, analysis_id: UUID) -> Optional[VideoAnalysisResult]:
        """Fetch existing analysis result from database.

        Args:
            analysis_id: Analysis UUID.

        Returns:
            VideoAnalysisResult or None if not found.
        """
        try:
            result = self.supabase.table("ad_video_analysis").select("*").eq(
                "id", str(analysis_id)
            ).limit(1).execute()

            if not result.data:
                return None

            row = result.data[0]
            return VideoAnalysisResult(
                meta_ad_id=row["meta_ad_id"],
                brand_id=UUID(row["brand_id"]),
                input_hash=row["input_hash"],
                prompt_version=row["prompt_version"],
                storage_path=row.get("storage_path", ""),
                status=row.get("status", "ok"),
                validation_errors=row.get("validation_errors", []),
                error_message=row.get("error_message"),
                full_transcript=row.get("full_transcript"),
                transcript_segments=row.get("transcript_segments"),
                text_overlays=row.get("text_overlays", []),
                text_overlay_confidence=row.get("text_overlay_confidence"),
                hook_transcript_spoken=row.get("hook_transcript_spoken"),
                hook_transcript_overlay=row.get("hook_transcript_overlay"),
                hook_fingerprint=row.get("hook_fingerprint"),
                hook_type=row.get("hook_type"),
                hook_effectiveness_signals=row.get("hook_effectiveness_signals"),
                storyboard=row.get("storyboard"),
                benefits_shown=row.get("benefits_shown", []),
                features_demonstrated=row.get("features_demonstrated", []),
                pain_points_addressed=row.get("pain_points_addressed", []),
                angles_used=row.get("angles_used", []),
                jobs_to_be_done=row.get("jobs_to_be_done", []),
                claims_made=row.get("claims_made"),
                awareness_level=row.get("awareness_level"),
                awareness_confidence=row.get("awareness_confidence"),
                target_persona=row.get("target_persona"),
                emotional_drivers=row.get("emotional_drivers", []),
                video_duration_sec=row.get("video_duration_sec"),
                production_quality=row.get("production_quality"),
                format_type=row.get("format_type"),
                video_id=row.get("video_id"),
                creative_id=row.get("creative_id"),
                raw_response=row.get("raw_response"),
                model_used=row.get("model_used"),
            )

        except Exception as e:
            logger.error(f"Error fetching existing analysis {analysis_id}: {e}")
            return None

    async def save_video_analysis(
        self,
        result: VideoAnalysisResult,
        organization_id: UUID,
    ) -> Optional[UUID]:
        """Save video analysis result to database.

        Creates a new row in ad_video_analysis. Does NOT update existing rows
        (immutable, versioned rows).

        Args:
            result: VideoAnalysisResult to save.
            organization_id: Organization UUID.

        Returns:
            Created analysis UUID, or None on failure.
        """
        try:
            data = {
                "organization_id": str(organization_id),
                "brand_id": str(result.brand_id),
                "meta_ad_id": result.meta_ad_id,
                "input_hash": result.input_hash,
                "prompt_version": result.prompt_version,
                "storage_path": result.storage_path,
                "status": result.status,
                "validation_errors": result.validation_errors,
                "error_message": result.error_message,
                "full_transcript": result.full_transcript,
                "transcript_segments": result.transcript_segments,
                "text_overlays": result.text_overlays,
                "text_overlay_confidence": result.text_overlay_confidence,
                "hook_transcript_spoken": result.hook_transcript_spoken,
                "hook_transcript_overlay": result.hook_transcript_overlay,
                "hook_fingerprint": result.hook_fingerprint,
                "hook_type": result.hook_type,
                "hook_effectiveness_signals": result.hook_effectiveness_signals,
                "storyboard": result.storyboard,
                "benefits_shown": result.benefits_shown,
                "features_demonstrated": result.features_demonstrated,
                "pain_points_addressed": result.pain_points_addressed,
                "angles_used": result.angles_used,
                "jobs_to_be_done": result.jobs_to_be_done,
                "claims_made": result.claims_made,
                "awareness_level": result.awareness_level,
                "awareness_confidence": result.awareness_confidence,
                "target_persona": result.target_persona,
                "emotional_drivers": result.emotional_drivers,
                "video_duration_sec": result.video_duration_sec,
                "production_quality": result.production_quality,
                "format_type": result.format_type,
                "video_id": result.video_id,
                "creative_id": result.creative_id,
                "raw_response": result.raw_response,
                "model_used": result.model_used,
            }

            response = self.supabase.table("ad_video_analysis").insert(data).execute()

            if response.data:
                created_id = UUID(response.data[0]["id"])
                logger.info(f"Saved video analysis for {result.meta_ad_id}: {created_id}")
                return created_id

            return None

        except Exception as e:
            logger.error(f"Error saving video analysis for {result.meta_ad_id}: {e}")
            return None

    async def get_latest_analysis(
        self,
        meta_ad_id: str,
        brand_id: UUID,
        prompt_version: str = PROMPT_VERSION,
    ) -> Optional[VideoAnalysisResult]:
        """Get the latest video analysis for an ad.

        Args:
            meta_ad_id: Meta ad ID.
            brand_id: Brand UUID.
            prompt_version: Prompt version to filter by (optional).

        Returns:
            Latest VideoAnalysisResult or None if not found.
        """
        try:
            query = self.supabase.table("ad_video_analysis").select("id").eq(
                "meta_ad_id", meta_ad_id
            ).eq(
                "brand_id", str(brand_id)
            ).eq(
                "prompt_version", prompt_version
            ).order(
                "analyzed_at", desc=True
            ).limit(1)

            result = query.execute()

            if result.data:
                return await self._fetch_existing_result(UUID(result.data[0]["id"]))

            return None

        except Exception as e:
            logger.error(f"Error fetching latest analysis for {meta_ad_id}: {e}")
            return None
