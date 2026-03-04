"""
Pydantic models for Kling AI video generation.

These models provide type-safe, validated data structures for:
- Kling endpoint types and task statuses (KlingEndpoint, KlingTaskStatus)
- Generation requests for each endpoint type
- API response models
- Database record models

Official API docs: https://app.klingai.com/global/dev/document-api/
Base URL: https://api-singapore.klingai.com
"""

from pydantic import BaseModel, Field, field_validator
from datetime import datetime
from typing import List, Optional, Dict, Any, Literal
from uuid import UUID
from enum import Enum


# ============================================================================
# Enums
# ============================================================================

class KlingEndpoint(str, Enum):
    """Endpoint types for Kling API. Used for polling path resolution."""
    TEXT2VIDEO = "text2video"
    IMAGE2VIDEO = "image2video"
    AVATAR = "avatar"
    IDENTIFY_FACE = "identify_face"
    LIP_SYNC = "lip_sync"
    VIDEO_EXTEND = "video_extend"
    MULTI_SHOT = "multi_shot"
    OMNI_VIDEO = "omni_video"
    ADVANCED_CUSTOM_ELEMENTS = "advanced_custom_elements"
    CUSTOM_VOICES = "custom_voices"
    DELETE_VOICES = "delete_voices"
    PRESETS_VOICES = "presets_voices"


class KlingTaskStatus(str, Enum):
    """Task status values from the Kling API."""
    # App-level statuses (before API call)
    PENDING = "pending"
    CANCELLED = "cancelled"
    # API statuses (from Kling response)
    SUBMITTED = "submitted"
    PROCESSING = "processing"
    SUCCEED = "succeed"
    FAILED = "failed"
    # Lip-sync specific (between step 1 and step 2)
    AWAITING_FACE_SELECTION = "awaiting_face_selection"


class KlingGenerationType(str, Enum):
    """Types of Kling generation operations."""
    AVATAR = "avatar"
    TEXT_TO_VIDEO = "text_to_video"
    IMAGE_TO_VIDEO = "image_to_video"
    IDENTIFY_FACE = "identify_face"
    LIP_SYNC = "lip_sync"
    VIDEO_EXTEND = "video_extend"
    MULTI_SHOT = "multi_shot"
    OMNI_VIDEO = "omni_video"
    ADVANCED_CUSTOM_ELEMENTS = "advanced_custom_elements"
    CUSTOM_VOICE = "custom_voice"


class KlingAspectRatio(str, Enum):
    """Valid aspect ratios for Kling video generation."""
    LANDSCAPE = "16:9"
    PORTRAIT = "9:16"
    SQUARE = "1:1"


class KlingMode(str, Enum):
    """Quality modes for Kling generation."""
    STD = "std"
    PRO = "pro"


# ============================================================================
# Request Models
# ============================================================================

class AvatarVideoRequest(BaseModel):
    """Request for avatar (talking-head) video generation.

    Endpoint: POST /v1/videos/avatar/image2video
    """
    image: str = Field(
        ...,
        description="URL or Base64 image (jpg/jpeg/png, <=10MB, >=300px, ratio 1:2.5~2.5:1)"
    )
    sound_file: Optional[str] = Field(
        None,
        description="URL or Base64 audio (mp3/wav/m4a/aac, <=5MB, 2-300s). Mutually exclusive with audio_id."
    )
    audio_id: Optional[str] = Field(
        None,
        description="TTS-generated audio ID. Mutually exclusive with sound_file."
    )
    prompt: Optional[str] = Field(
        None,
        max_length=2500,
        description="Actions/emotions/camera movements (max 2500 chars)"
    )
    mode: KlingMode = Field(
        default=KlingMode.STD,
        description="Quality mode: std or pro"
    )
    callback_url: Optional[str] = Field(None, description="Callback URL (deferred to V2)")
    external_task_id: Optional[str] = Field(None, description="Custom task ID for tracking")

    @field_validator('sound_file')
    @classmethod
    def validate_audio_exclusion(cls, v, info):
        """Validate mutual exclusion is checked at service level."""
        return v


class TextToVideoRequest(BaseModel):
    """Request for text-to-video generation.

    Endpoint: POST /v1/videos/text2video
    """
    prompt: str = Field(
        ...,
        max_length=2500,
        description="Video generation prompt (max 2500 chars)"
    )
    model_name: str = Field(
        default="kling-v2-6",
        description="Model name: kling-v2-6, kling-v2-5-turbo"
    )
    mode: KlingMode = Field(
        default=KlingMode.PRO,
        description="Quality mode: std or pro"
    )
    duration: Literal["5", "10"] = Field(
        default="5",
        description="Duration in seconds (STRING: '5' or '10')"
    )
    aspect_ratio: KlingAspectRatio = Field(
        default=KlingAspectRatio.LANDSCAPE,
        description="Aspect ratio: 16:9, 9:16, 1:1"
    )
    negative_prompt: Optional[str] = Field(
        None,
        max_length=2500,
        description="Content to avoid (max 2500 chars)"
    )
    sound: Literal["on", "off"] = Field(
        default="off",
        description="Native audio generation (v2.6+ only)"
    )
    cfg_scale: Optional[float] = Field(
        default=None,
        ge=0,
        le=1,
        description="Prompt adherence 0-1. Only for v1.x models, auto-omitted for v2.x."
    )
    camera_control: Optional[Dict[str, Any]] = Field(
        None,
        description="Camera movement control configuration"
    )
    callback_url: Optional[str] = Field(None, description="Callback URL (deferred to V2)")
    external_task_id: Optional[str] = Field(None, description="Custom task ID for tracking")


class ImageToVideoRequest(BaseModel):
    """Request for image-to-video generation.

    Endpoint: POST /v1/videos/image2video
    """
    image: str = Field(
        ...,
        description="URL or Base64 image (required)"
    )
    prompt: Optional[str] = Field(
        None,
        max_length=2500,
        description="Animation prompt (max 2500 chars)"
    )
    model_name: str = Field(
        default="kling-v2-6",
        description="Model name: kling-v2-6, kling-v2-5-turbo"
    )
    mode: KlingMode = Field(
        default=KlingMode.PRO,
        description="Quality mode: std or pro"
    )
    duration: Literal["5", "10"] = Field(
        default="5",
        description="Duration in seconds (STRING: '5' or '10')"
    )
    image_tail: Optional[str] = Field(
        None,
        description="End frame image (mutually exclusive with camera_control)"
    )
    negative_prompt: Optional[str] = Field(
        None,
        max_length=2500,
        description="Content to avoid"
    )
    sound: Literal["on", "off"] = Field(
        default="off",
        description="Native audio generation (v2.6+ only)"
    )
    cfg_scale: Optional[float] = Field(
        default=None,
        ge=0,
        le=1,
        description="Prompt adherence 0-1. Only for v1.x models."
    )
    camera_control: Optional[Dict[str, Any]] = Field(
        None,
        description="Camera movement control (mutually exclusive with image_tail)"
    )
    callback_url: Optional[str] = Field(None, description="Callback URL (deferred to V2)")
    external_task_id: Optional[str] = Field(None, description="Custom task ID for tracking")


class IdentifyFacesRequest(BaseModel):
    """Request for face identification (lip-sync step 1).

    Endpoint: POST /v1/videos/identify-face
    This is a synchronous endpoint (not an async task).
    """
    video_id: Optional[str] = Field(
        None,
        description="Kling-generated video ID (mutually exclusive with video_url)"
    )
    video_url: Optional[str] = Field(
        None,
        description="External video URL (mp4/mov, <=100MB, 2-60s, 720p/1080p, 512-2160px)"
    )


class LipSyncRequest(BaseModel):
    """Request for lip-sync application (step 2).

    Endpoint: POST /v1/videos/advanced-lip-sync
    Uses session_id from identify-face step.
    """
    session_id: str = Field(
        ...,
        description="Session ID from identify-face (valid 24h)"
    )
    face_id: str = Field(
        ...,
        description="Selected face_id from identify-face results"
    )
    sound_file: Optional[str] = Field(
        None,
        description="Audio file URL or Base64 (mp3/wav/m4a, <=5MB, 2-60s). Mutually exclusive with audio_id."
    )
    audio_id: Optional[str] = Field(
        None,
        description="TTS audio ID. Mutually exclusive with sound_file."
    )
    sound_start_time: int = Field(
        default=0,
        ge=0,
        description="Audio crop start time in ms"
    )
    sound_end_time: Optional[int] = Field(
        None,
        ge=0,
        description="Audio crop end time in ms"
    )
    sound_insert_time: int = Field(
        default=0,
        ge=0,
        description="Insert point in video timeline in ms"
    )
    sound_volume: float = Field(
        default=1.0,
        ge=0,
        le=2,
        description="Audio volume multiplier (0-2)"
    )
    original_audio_volume: float = Field(
        default=1.0,
        ge=0,
        le=2,
        description="Original video audio volume (0-2)"
    )
    callback_url: Optional[str] = Field(None, description="Callback URL (deferred to V2)")
    external_task_id: Optional[str] = Field(None, description="Custom task ID for tracking")


class VideoExtendRequest(BaseModel):
    """Request for video extension.

    Endpoint: POST /v1/videos/video-extend
    IMPORTANT: Only works with V1.0, V1.5, V1.6 model outputs.
    Videos generated with kling-v2-x models CANNOT be extended.
    """
    video_id: str = Field(
        ...,
        description="Source video ID from text2video/image2video/video-extend"
    )
    prompt: Optional[str] = Field(
        None,
        description="Extension prompt"
    )
    negative_prompt: Optional[str] = Field(
        None,
        description="Content to avoid"
    )
    cfg_scale: float = Field(
        default=0.5,
        ge=0,
        le=1,
        description="Prompt adherence 0-1"
    )
    callback_url: Optional[str] = Field(None, description="Callback URL (deferred to V2)")
    external_task_id: Optional[str] = Field(None, description="Custom task ID for tracking")


class MultiShotRequest(BaseModel):
    """Request for AI Multi-Shot (3-angle image generation).

    Endpoint: POST /v1/general/ai-multi-shot
    Returns 3 images showing different angles of the element.
    """
    element_frontal_image: str = Field(
        ...,
        description="URL or Base64 frontal image of the element"
    )
    callback_url: Optional[str] = Field(None, description="Callback URL (deferred to V2)")
    external_task_id: Optional[str] = Field(None, description="Custom task ID for tracking")


class OmniVideoImageRef(BaseModel):
    """Image reference for Omni Video keyframes.

    Used in the image_list parameter of OmniVideoRequest.
    """
    image_url: str = Field(
        ...,
        description="URL or Base64 image (jpg/jpeg/png, <=10MB, >=300px, aspect 1:2.5~2.5:1)"
    )
    type: Literal["first_frame", "end_frame"] = Field(
        ...,
        description="Keyframe type: first_frame or end_frame. First frame required before end frame."
    )


class OmniVideoRequest(BaseModel):
    """Request for Omni Video generation (Kling 3.0).

    Endpoint: POST /v1/videos/omni-video

    Supports first/last frame keyframes for scene transitions,
    element references for character consistency, and native audio.

    Constraints:
    - First frame required before end frame
    - End frame NOT supported when >2 images in image_list
    - Total images + elements must be <=7 (no video ref) or <=4 (with video ref)
    - Prompt uses <<<element_1>>>, <<<image_1>>> syntax (triple angle brackets)
    """
    model_name: str = Field(
        default="kling-v3-omni",
        description="Model name: kling-v3-omni or kling-video-o1"
    )
    prompt: str = Field(
        ...,
        max_length=2500,
        description="Video prompt (max 2500 chars). Use <<<element_1>>> for element refs, <<<image_1>>> for image refs."
    )
    multi_shot: bool = Field(
        default=False,
        description="Enable multi-shot mode (up to 6 shots, 15s total)"
    )
    image_list: Optional[List[OmniVideoImageRef]] = Field(
        None,
        description="Keyframe images: first_frame and/or end_frame"
    )
    element_list: Optional[List[Dict[str, str]]] = Field(
        None,
        description="Pre-created element IDs for character consistency. Each: {element_id: str}"
    )
    video_list: Optional[List[Dict[str, str]]] = Field(
        None,
        description="Reference video IDs"
    )
    voice_list: Optional[List[Dict[str, str]]] = Field(
        None,
        description="Voice list for voice control. Each: {voice_id: str}. Max 2. "
                    "Referenced in prompt as <<<voice_1>>>, <<<voice_2>>>. "
                    "MUTUALLY EXCLUSIVE with element_list. Requires sound='on'."
    )
    sound: Literal["on", "off"] = Field(
        default="on",
        description="Native audio generation: on/off"
    )
    mode: Literal["std", "pro"] = Field(
        default="pro",
        description="Quality mode: std (720p) or pro (1080p)"
    )
    aspect_ratio: Optional[str] = Field(
        None,
        description="Aspect ratio: 16:9, 9:16, 1:1. Required when no first-frame image."
    )
    duration: str = Field(
        default="5",
        description="Duration in seconds as string: '3' through '15'"
    )
    callback_url: Optional[str] = Field(None, description="Callback URL")
    external_task_id: Optional[str] = Field(None, description="Custom task ID for tracking")

    @field_validator('duration')
    @classmethod
    def validate_duration(cls, v):
        """Validate duration is a string between '3' and '15'."""
        try:
            d = int(v)
        except (ValueError, TypeError):
            raise ValueError(f"Duration must be a numeric string, got '{v}'")
        if d < 3 or d > 15:
            raise ValueError(f"Duration must be between 3 and 15, got {d}")
        return str(d)


class CreateElementRequest(BaseModel):
    """Request for creating a custom element for character consistency.

    Endpoint: POST /v1/general/advanced-custom-elements

    Elements are created once per character/avatar and reused across all
    video generations via element_list in OmniVideoRequest.
    """
    element_name: str = Field(
        ...,
        max_length=20,
        description="Element name (max 20 chars)"
    )
    element_description: str = Field(
        ...,
        max_length=100,
        description="Element description (max 100 chars)"
    )
    reference_type: Literal["image_refer", "video_refer"] = Field(
        default="image_refer",
        description="Reference type: image_refer or video_refer"
    )
    element_image_list: Optional[Dict[str, Any]] = Field(
        None,
        description="Image references: {frontal_image: str, refer_images: [{image_url: str}]}"
    )
    callback_url: Optional[str] = Field(None, description="Callback URL")
    external_task_id: Optional[str] = Field(None, description="Custom task ID for tracking")


class CreateVoiceRequest(BaseModel):
    """Request for creating a custom voice clone.

    Endpoint: POST /v1/general/custom-voices

    Creates a voice from an audio/video file. The voice can then be bound
    to elements via element_voice_id for consistent character voice across
    Omni Video generations.
    """
    voice_name: str = Field(
        ...,
        max_length=20,
        description="Voice name (max 20 chars)"
    )
    voice_url: Optional[str] = Field(
        None,
        description="URL of voice data file (.mp3/.wav audio or .mp4/.mov video). "
        "5-30 seconds of clean speech with one speaker. "
        "Mutually exclusive with video_id."
    )
    video_id: Optional[str] = Field(
        None,
        description="Reference a previously generated Kling video ID for voice cloning. "
        "Only works with V2.6+ (sound=on), Avatar API, or Lip-Sync API outputs. "
        "Mutually exclusive with voice_url."
    )
    callback_url: Optional[str] = Field(None, description="Callback URL")
    external_task_id: Optional[str] = Field(None, description="Custom task ID for tracking")


# ============================================================================
# API Response Models
# ============================================================================

class KlingTaskInfo(BaseModel):
    """Task info from Kling create response."""
    external_task_id: Optional[str] = None


class KlingVideoResult(BaseModel):
    """Single video result from query response."""
    id: str = Field(..., description="Video ID (for use in video-extend, etc.)")
    url: str = Field(..., description="Video URL (expires in 30 days)")
    duration: str = Field(..., description="Video duration as string")


class KlingImageResult(BaseModel):
    """Single image result from multi-shot query response."""
    index: int = Field(..., description="Image index (0, 1, 2)")
    url: str = Field(..., description="Image URL")


class KlingVoiceResult(BaseModel):
    """Single voice result from custom voice query response."""
    voice_id: str = Field(..., description="Voice ID (globally unique)")
    voice_name: str = Field(..., description="Voice name")
    trial_url: Optional[str] = Field(None, description="Trial audio/video URL")
    owned_by: Optional[str] = Field(None, description="Voice source: 'kling' for official, creator ID otherwise")


class KlingFaceData(BaseModel):
    """Face data from identify-face response."""
    face_id: str = Field(..., description="Face identifier for lip-sync")
    face_image: str = Field(..., description="URL of cropped face image")
    start_time: int = Field(..., description="Face appearance start time (ms)")
    end_time: int = Field(..., description="Face appearance end time (ms)")


class KlingCreateResponse(BaseModel):
    """Parsed create response from any Kling generation endpoint."""
    code: int
    message: str
    request_id: str
    task_id: Optional[str] = None
    task_status: Optional[str] = None
    task_info: Optional[KlingTaskInfo] = None
    created_at: Optional[int] = None
    updated_at: Optional[int] = None


class KlingQueryResponse(BaseModel):
    """Parsed query response from any Kling status endpoint."""
    code: int
    message: Optional[str] = None
    request_id: Optional[str] = None
    task_id: Optional[str] = None
    task_status: Optional[str] = None
    task_status_msg: Optional[str] = None
    final_unit_deduction: Optional[str] = None
    # Video results
    videos: Optional[List[KlingVideoResult]] = None
    # Multi-shot image results
    images: Optional[List[KlingImageResult]] = None


class KlingIdentifyFaceResponse(BaseModel):
    """Parsed response from identify-face (synchronous endpoint)."""
    code: int
    message: Optional[str] = None
    request_id: Optional[str] = None
    session_id: Optional[str] = None
    face_data: Optional[List[KlingFaceData]] = None


# ============================================================================
# Database Record Models
# ============================================================================

class KlingGenerationRecord(BaseModel):
    """Represents a row in the kling_video_generations table."""
    id: UUID
    organization_id: UUID
    brand_id: UUID
    avatar_id: Optional[UUID] = None
    candidate_id: Optional[UUID] = None
    parent_generation_id: Optional[UUID] = None

    # Request
    generation_type: KlingGenerationType
    model_name: Optional[str] = None
    mode: KlingMode = KlingMode.STD
    prompt: Optional[str] = None
    negative_prompt: Optional[str] = None
    input_image_url: Optional[str] = None
    input_audio_url: Optional[str] = None
    duration: Optional[str] = None  # "5" or "10"
    aspect_ratio: Optional[str] = None
    cfg_scale: Optional[float] = None
    sound: str = "off"

    # Kling task tracking
    kling_task_id: Optional[str] = None
    kling_external_task_id: Optional[str] = None
    kling_request_id: Optional[str] = None
    status: str = "pending"

    # Lip-sync specific
    lip_sync_session_id: Optional[str] = None
    lip_sync_session_expires_at: Optional[datetime] = None
    lip_sync_face_id: Optional[str] = None
    lip_sync_face_data: Optional[List[Dict[str, Any]]] = None

    # Multi-shot specific
    multi_shot_images: Optional[List[Dict[str, Any]]] = None

    # Result
    video_url: Optional[str] = None
    video_storage_path: Optional[str] = None
    download_status: str = "pending"
    error_message: Optional[str] = None
    error_code: Optional[int] = None
    task_status_msg: Optional[str] = None

    # Cost
    estimated_cost_usd: Optional[float] = None
    actual_kling_units: Optional[str] = None
    generation_time_seconds: Optional[float] = None

    # Timestamps
    created_at: Optional[datetime] = None
    updated_at: Optional[datetime] = None
    completed_at: Optional[datetime] = None
