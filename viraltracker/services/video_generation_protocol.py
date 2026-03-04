"""
VideoGenerationProtocol - Shared interface for video generation engines.

Defines a common interface that VEO 3.1, Kling, and future engines (Sora, etc.)
can implement. This enables engine-agnostic scene routing in the video recreation
workflow (e.g., Kling for talking-head, VEO for B-roll).

Kling-specific operations (lip-sync, multi-shot, video-extend) are NOT on this
protocol. They are called directly on KlingVideoService.
"""

from typing import Protocol, Optional, List, runtime_checkable
from dataclasses import dataclass
from enum import Enum


class VideoGenStatus(str, Enum):
    """Unified status for video generation across engines."""
    PENDING = "pending"
    GENERATING = "generating"
    COMPLETED = "completed"
    FAILED = "failed"


@dataclass
class VideoGenerationResult:
    """Result from any video generation engine."""
    generation_id: str
    status: VideoGenStatus
    video_storage_path: Optional[str] = None
    video_url: Optional[str] = None  # CDN URL (may expire)
    duration_seconds: Optional[float] = None
    generation_time_seconds: Optional[float] = None
    estimated_cost_usd: Optional[float] = None
    error_message: Optional[str] = None

    @property
    def is_complete(self) -> bool:
        """Check if generation is complete (success or failure)."""
        return self.status in (VideoGenStatus.COMPLETED, VideoGenStatus.FAILED)

    @property
    def is_success(self) -> bool:
        """Check if generation succeeded."""
        return self.status == VideoGenStatus.COMPLETED


@runtime_checkable
class VideoGenerationProtocol(Protocol):
    """Shared interface for VEO 3.1, Kling, and Sora.

    Covers the two core generation patterns used in video recreation:
    1. Prompt-based generation (B-roll, scenes) via generate_from_prompt()
    2. Talking-head generation (avatar + audio) via generate_talking_head()

    Engine-specific operations (lip-sync, multi-shot, video-extend) should be
    called directly on the engine's service class.
    """

    async def generate_from_prompt(
        self,
        prompt: str,
        duration_sec: int,
        aspect_ratio: str,
        reference_images: Optional[List[str]] = None,
        negative_prompt: Optional[str] = None,
    ) -> VideoGenerationResult:
        """Generate video from a text prompt.

        Used for B-roll, action scenes, and general video generation.

        Args:
            prompt: Video generation prompt (max 2500 chars for Kling).
            duration_sec: Target duration in seconds.
            aspect_ratio: Target aspect ratio (e.g., "16:9", "9:16", "1:1").
            reference_images: Optional reference image URLs for consistency.
            negative_prompt: Content to avoid in generation.

        Returns:
            VideoGenerationResult with status and output paths.
        """
        ...

    async def generate_talking_head(
        self,
        avatar_image_url: str,
        audio_url: str,
        prompt: Optional[str] = None,
    ) -> VideoGenerationResult:
        """Generate talking-head video from avatar image + audio.

        Used for avatar/spokesperson scenes with dialogue.

        Args:
            avatar_image_url: URL or storage path to avatar image.
            audio_url: URL or storage path to audio file.
            prompt: Optional actions/emotions/camera description.

        Returns:
            VideoGenerationResult with status and output paths.
        """
        ...

    async def get_status(
        self,
        generation_id: str,
    ) -> VideoGenerationResult:
        """Get current status of a generation.

        Implementation looks up generation_type from DB to determine
        the correct query endpoint (for Kling) or polling method (for VEO).

        Args:
            generation_id: Internal generation UUID.

        Returns:
            VideoGenerationResult with current status.
        """
        ...

    async def download_and_store(
        self,
        generation_id: str,
    ) -> str:
        """Download generated video and store persistently.

        Downloads from provider CDN (e.g., Kling CDN, Google storage) and
        uploads to Supabase storage for persistent access.

        Args:
            generation_id: Internal generation UUID.

        Returns:
            Supabase storage path for the downloaded video.
        """
        ...
