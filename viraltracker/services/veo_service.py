"""
VeoService - Google Veo 3.1 Video Generation Service.

Handles video generation using Google's Veo 3.1 API via the Gemini SDK.
Supports reference images for character consistency (Nano Banana pattern).

API Pricing:
- Standard: $0.40/second
- Fast: $0.15/second

Documentation: https://ai.google.dev/gemini-api/docs/video
"""

import logging
import asyncio
import time
from typing import Optional, List, Dict, Any
from uuid import UUID
import uuid
from datetime import datetime
from io import BytesIO

from google import genai
from google.genai import types

from ..core.config import Config
from ..core.database import get_supabase_client
from .usage_tracker import UsageTracker, UsageRecord
from .veo_models import (
    VeoConfig,
    VeoGenerationRequest,
    VeoGenerationResult,
    VeoGenerationSummary,
    AspectRatio,
    Resolution,
    ModelVariant,
    GenerationStatus
)

logger = logging.getLogger(__name__)


class VeoService:
    """
    Service for Google Veo 3.1 video generation.

    Features:
    - Text-to-video generation with audio
    - Reference images for character/product consistency (up to 3)
    - Multiple resolutions (720p, 1080p, 4k)
    - Configurable duration (4, 6, 8 seconds)
    - Automatic storage to Supabase
    """

    STORAGE_BUCKET = "veo-videos"

    # Pricing per second (USD)
    PRICING = {
        ModelVariant.STANDARD: 0.40,
        ModelVariant.FAST: 0.15
    }

    def __init__(self, api_key: Optional[str] = None):
        """
        Initialize Veo service.

        Args:
            api_key: Gemini API key (if None, uses Config.GEMINI_API_KEY)

        Raises:
            ValueError: If API key not found
        """
        self.api_key = api_key or Config.GEMINI_API_KEY
        if not self.api_key:
            raise ValueError("GEMINI_API_KEY not found in environment")

        self.client = genai.Client(api_key=self.api_key)
        self.supabase = get_supabase_client()

        # Usage tracking (optional)
        self._usage_tracker = None
        self._user_id = None
        self._organization_id = None

        logger.info("VeoService initialized")

    def set_tracking_context(
        self,
        usage_tracker: UsageTracker,
        user_id: Optional[str] = None,
        organization_id: Optional[str] = None
    ) -> None:
        """
        Set usage tracking context.

        Args:
            usage_tracker: UsageTracker instance
            user_id: User ID for tracking
            organization_id: Organization ID for billing
        """
        self._usage_tracker = usage_tracker
        self._user_id = user_id
        self._organization_id = organization_id
        logger.debug(f"VeoService usage tracking enabled for org: {organization_id}")

    def _track_usage(
        self,
        operation: str,
        model: str,
        duration_seconds: int,
        cost_usd: float,
        metadata: dict = None
    ) -> None:
        """Track video generation usage (fire-and-forget)."""
        if not self._usage_tracker or not self._organization_id:
            return

        try:
            record = UsageRecord(
                provider="google",
                model=model,
                tool_name="veo_service",
                operation=operation,
                units=float(duration_seconds),
                unit_type="video_seconds",
                cost_usd=cost_usd,
                request_metadata=metadata,
            )

            self._usage_tracker.track(
                user_id=self._user_id,
                organization_id=self._organization_id,
                record=record
            )
        except Exception as e:
            logger.warning(f"Usage tracking failed (non-fatal): {e}")

    def _get_model_name(self, variant: ModelVariant) -> str:
        """Get Veo model name for variant."""
        if variant == ModelVariant.FAST:
            return "veo-3.1-fast-generate-preview"
        return "veo-3.1-generate-preview"

    def _build_full_prompt(
        self,
        prompt: str,
        action_description: Optional[str] = None,
        dialogue: Optional[str] = None,
        background_description: Optional[str] = None
    ) -> str:
        """
        Build a comprehensive prompt for Veo generation.

        Args:
            prompt: Base prompt describing the scene/subject
            action_description: What the subject should do
            dialogue: What the subject should say
            background_description: Background scene description

        Returns:
            Full prompt string optimized for Veo 3.1
        """
        parts = [prompt]

        if action_description:
            parts.append(f"Action: {action_description}")

        if background_description:
            parts.append(f"Setting: {background_description}")

        if dialogue:
            # Veo 3.1 supports native dialogue generation
            parts.append(f'The subject says: "{dialogue}"')

        return " ".join(parts)

    def _validate_config(self, config: VeoConfig) -> VeoConfig:
        """
        Validate and adjust configuration as needed.

        Args:
            config: Video generation configuration

        Returns:
            Validated/adjusted configuration
        """
        # 1080p and 4k require 8s duration
        if config.resolution in [Resolution.FULL_HD, Resolution.UHD]:
            if config.duration_seconds != 8:
                logger.warning(
                    f"Resolution {config.resolution.value} requires 8s duration. Adjusting..."
                )
                config = config.model_copy(update={"duration_seconds": 8})

        return config

    async def _upload_to_storage(
        self,
        path: str,
        data: bytes,
        content_type: str
    ) -> str:
        """
        Upload file to Supabase storage.

        Args:
            path: Storage path within bucket
            data: File bytes
            content_type: MIME type

        Returns:
            Full storage path
        """
        await asyncio.to_thread(
            lambda: self.supabase.storage.from_(self.STORAGE_BUCKET).upload(
                path,
                data,
                {"content-type": content_type}
            )
        )
        return f"{self.STORAGE_BUCKET}/{path}"

    async def _download_from_storage(self, storage_path: str) -> bytes:
        """
        Download file from Supabase storage.

        Args:
            storage_path: Full storage path (bucket/path)

        Returns:
            File bytes
        """
        parts = storage_path.split("/", 1)
        bucket = parts[0]
        path = parts[1] if len(parts) > 1 else storage_path

        data = await asyncio.to_thread(
            lambda: self.supabase.storage.from_(bucket).download(path)
        )
        return data

    def _cleanup_temp_files(self, temp_files: list) -> None:
        """Clean up temporary files."""
        import os
        for path in temp_files:
            try:
                if path and os.path.exists(path):
                    os.unlink(path)
            except Exception as e:
                logger.warning(f"Failed to clean up temp file {path}: {e}")

    async def generate_video(
        self,
        request: VeoGenerationRequest,
        reference_image_bytes: Optional[List[bytes]] = None
    ) -> VeoGenerationResult:
        """
        Generate a video using Veo 3.1.

        Args:
            request: Video generation request with all parameters
            reference_image_bytes: Optional pre-loaded reference images

        Returns:
            VeoGenerationResult with generation status and video path

        Raises:
            ValueError: If invalid parameters provided
            Exception: If video generation fails
        """
        # Validate and adjust config
        config = self._validate_config(request.config)

        # Reference images require 8s duration
        if reference_image_bytes and len(reference_image_bytes) > 0:
            if config.duration_seconds != 8:
                logger.warning("Reference images require 8s duration. Adjusting...")
                config = config.model_copy(update={"duration_seconds": 8})

        # Create generation record
        generation_id = uuid.uuid4()
        now = datetime.utcnow()

        # Build full prompt
        full_prompt = self._build_full_prompt(
            prompt=request.prompt,
            action_description=request.action_description,
            dialogue=request.dialogue,
            background_description=request.background_description
        )

        # Create initial database record
        await asyncio.to_thread(
            lambda: self.supabase.table("veo_video_generations").insert({
                "id": str(generation_id),
                "brand_id": str(request.brand_id),
                "avatar_id": str(request.avatar_id) if request.avatar_id else None,
                "product_id": str(request.product_id) if request.product_id else None,
                "prompt": full_prompt,
                "action_description": request.action_description,
                "dialogue": request.dialogue,
                "background_description": request.background_description,
                "aspect_ratio": config.aspect_ratio.value,
                "resolution": config.resolution.value,
                "duration_seconds": config.duration_seconds,
                "negative_prompt": config.negative_prompt,
                "seed": config.seed,
                "model_name": self._get_model_name(config.model_variant),
                "model_variant": config.model_variant.value,
                "reference_images": [],
                "status": GenerationStatus.GENERATING.value
            }).execute()
        )

        # Track temp files for cleanup
        temp_files_to_cleanup = []

        try:
            start_time = time.time()

            # Build generation config for Veo API
            veo_config = types.GenerateVideosConfig(
                aspect_ratio=config.aspect_ratio.value,
                resolution=config.resolution.value,
                duration_seconds=str(config.duration_seconds)
            )

            if config.negative_prompt:
                veo_config.negative_prompt = config.negative_prompt

            # Prepare reference images if provided
            reference_paths = []
            if reference_image_bytes:
                reference_image_objects = []
                for i, img_bytes in enumerate(reference_image_bytes[:3]):
                    # Detect mime type from image bytes
                    mime_type = "image/png"  # default
                    if img_bytes[:2] == b'\xff\xd8':
                        mime_type = "image/jpeg"
                    elif img_bytes[:4] == b'\x89PNG':
                        mime_type = "image/png"
                    elif img_bytes[:4] == b'RIFF' and img_bytes[8:12] == b'WEBP':
                        mime_type = "image/webp"

                    # Get image dimensions for logging
                    try:
                        from PIL import Image
                        img = Image.open(BytesIO(img_bytes))
                        width, height = img.size
                        size_kb = len(img_bytes) / 1024
                        logger.info(
                            f"Reference image {i+1}: {width}x{height}px, "
                            f"{size_kb:.1f}KB, {mime_type}"
                        )
                        # Warn if image is small (less than 720p)
                        if width < 1280 or height < 720:
                            logger.warning(
                                f"Reference image {i+1} is low resolution ({width}x{height}). "
                                f"Recommend 1280x720 or higher for text clarity."
                            )
                    except Exception as e:
                        logger.warning(f"Could not read image dimensions: {e}")

                    # Create Image with raw bytes and correct mime type
                    image_obj = types.Image(
                        image_bytes=img_bytes,
                        mime_type=mime_type
                    )

                    # Create VideoGenerationReferenceImage
                    ref_image = types.VideoGenerationReferenceImage(
                        image=image_obj,
                        reference_type="asset"
                    )
                    reference_image_objects.append(ref_image)

                    # Also upload to Supabase for record keeping
                    ref_path = f"{generation_id}/reference_{i+1}.png"
                    await self._upload_to_storage(ref_path, img_bytes, "image/png")
                    reference_paths.append(ref_path)

                if reference_image_objects:
                    veo_config.reference_images = reference_image_objects
                    logger.info(f"Added {len(reference_image_objects)} reference images")

            # Call Veo 3.1 API
            logger.info(f"Starting Veo generation: {generation_id}")
            operation = await asyncio.to_thread(
                lambda: self.client.models.generate_videos(
                    model=self._get_model_name(config.model_variant),
                    prompt=full_prompt,
                    config=veo_config
                )
            )

            # Poll for completion
            while not operation.done:
                logger.debug(f"Waiting for video generation... {generation_id}")
                await asyncio.sleep(10)
                operation = await asyncio.to_thread(
                    lambda: self.client.operations.get(operation)
                )

            generation_time = time.time() - start_time

            # Process result
            if operation.response and operation.response.generated_videos:
                video = operation.response.generated_videos[0]

                # Download video from Gemini
                video_data = await asyncio.to_thread(
                    lambda: self.client.files.download(file=video.video)
                )

                # Upload to Supabase storage
                video_path = f"{generation_id}/video.mp4"
                full_video_path = await self._upload_to_storage(
                    video_path, video_data, "video/mp4"
                )

                # Calculate cost
                cost_usd = config.duration_seconds * self.PRICING[config.model_variant]
                completed_at = datetime.utcnow()

                # Update record with success
                await asyncio.to_thread(
                    lambda: self.supabase.table("veo_video_generations").update({
                        "status": GenerationStatus.COMPLETED.value,
                        "video_storage_path": full_video_path,
                        "reference_images": reference_paths,
                        "generation_time_seconds": round(generation_time, 2),
                        "estimated_cost_usd": cost_usd,
                        "completed_at": completed_at.isoformat()
                    }).eq("id", str(generation_id)).execute()
                )

                logger.info(
                    f"Video generation completed: {generation_id} "
                    f"({generation_time:.1f}s, ${cost_usd:.2f})"
                )

                # Track usage (fire-and-forget)
                self._track_usage(
                    operation="generate_video",
                    model=self._get_model_name(config.model_variant),
                    duration_seconds=config.duration_seconds,
                    cost_usd=cost_usd,
                    metadata={
                        "generation_id": str(generation_id),
                        "brand_id": str(request.brand_id),
                        "resolution": config.resolution.value,
                        "aspect_ratio": config.aspect_ratio.value,
                    }
                )

                # Clean up temp files
                self._cleanup_temp_files(temp_files_to_cleanup)

                return VeoGenerationResult(
                    generation_id=generation_id,
                    status=GenerationStatus.COMPLETED,
                    video_storage_path=full_video_path,
                    generation_time_seconds=round(generation_time, 2),
                    estimated_cost_usd=cost_usd,
                    created_at=now,
                    completed_at=completed_at
                )

            else:
                raise Exception("No video returned from Veo API")

        except Exception as e:
            logger.error(f"Video generation failed: {generation_id} - {e}")

            # Clean up temp files
            self._cleanup_temp_files(temp_files_to_cleanup)

            # Update record with failure
            await asyncio.to_thread(
                lambda: self.supabase.table("veo_video_generations").update({
                    "status": GenerationStatus.FAILED.value,
                    "error_message": str(e),
                    "completed_at": datetime.utcnow().isoformat()
                }).eq("id", str(generation_id)).execute()
            )

            return VeoGenerationResult(
                generation_id=generation_id,
                status=GenerationStatus.FAILED,
                error_message=str(e),
                created_at=now,
                completed_at=datetime.utcnow()
            )

    async def get_video_url(self, storage_path: str, expires_in: int = 3600) -> str:
        """
        Get a signed URL for video playback.

        Args:
            storage_path: Full storage path (e.g., "veo-videos/gen-id/video.mp4")
            expires_in: URL expiry in seconds (default 1 hour)

        Returns:
            Signed URL for video playback
        """
        parts = storage_path.split("/", 1)
        bucket = parts[0]
        path = parts[1] if len(parts) > 1 else storage_path

        result = await asyncio.to_thread(
            lambda: self.supabase.storage.from_(bucket).create_signed_url(
                path, expires_in
            )
        )

        return result.get("signedURL", "")

    async def get_generation(self, generation_id: UUID) -> Optional[VeoGenerationResult]:
        """
        Get a video generation record.

        Args:
            generation_id: Generation UUID

        Returns:
            VeoGenerationResult or None if not found
        """
        result = await asyncio.to_thread(
            lambda: self.supabase.table("veo_video_generations")
                .select("*")
                .eq("id", str(generation_id))
                .single()
                .execute()
        )

        if not result.data:
            return None

        data = result.data
        return VeoGenerationResult(
            generation_id=UUID(data["id"]),
            status=GenerationStatus(data["status"]),
            video_storage_path=data.get("video_storage_path"),
            thumbnail_storage_path=data.get("thumbnail_storage_path"),
            generation_time_seconds=data.get("generation_time_seconds"),
            estimated_cost_usd=data.get("estimated_cost_usd"),
            error_message=data.get("error_message"),
            created_at=datetime.fromisoformat(
                data["created_at"].replace('Z', '+00:00')
            ),
            completed_at=datetime.fromisoformat(
                data["completed_at"].replace('Z', '+00:00')
            ) if data.get("completed_at") else None
        )

    async def list_generations(
        self,
        brand_id: Optional[UUID] = None,
        avatar_id: Optional[UUID] = None,
        status: Optional[GenerationStatus] = None,
        limit: int = 20
    ) -> List[VeoGenerationSummary]:
        """
        List video generations with optional filters.

        Args:
            brand_id: Filter by brand
            avatar_id: Filter by avatar
            status: Filter by status
            limit: Max results

        Returns:
            List of VeoGenerationSummary
        """
        query = self.supabase.table("veo_video_generations").select(
            "id, brand_id, avatar_id, prompt, status, video_storage_path, "
            "estimated_cost_usd, created_at"
        )

        if brand_id:
            query = query.eq("brand_id", str(brand_id))
        if avatar_id:
            query = query.eq("avatar_id", str(avatar_id))
        if status:
            query = query.eq("status", status.value)

        result = await asyncio.to_thread(
            lambda: query.order("created_at", desc=True).limit(limit).execute()
        )

        summaries = []
        for data in result.data:
            summaries.append(VeoGenerationSummary(
                id=UUID(data["id"]),
                brand_id=UUID(data["brand_id"]),
                avatar_id=UUID(data["avatar_id"]) if data.get("avatar_id") else None,
                prompt=data["prompt"],
                status=GenerationStatus(data["status"]),
                video_storage_path=data.get("video_storage_path"),
                estimated_cost_usd=data.get("estimated_cost_usd"),
                created_at=datetime.fromisoformat(
                    data["created_at"].replace('Z', '+00:00')
                )
            ))

        return summaries

    async def delete_generation(self, generation_id: UUID) -> bool:
        """
        Delete a video generation and its files.

        Args:
            generation_id: Generation UUID to delete

        Returns:
            True if deleted, False if not found
        """
        # Get the generation first
        gen = await self.get_generation(generation_id)
        if not gen:
            return False

        # Delete files from storage
        if gen.video_storage_path:
            try:
                parts = gen.video_storage_path.split("/", 1)
                bucket = parts[0]
                path = parts[1] if len(parts) > 1 else gen.video_storage_path
                await asyncio.to_thread(
                    lambda: self.supabase.storage.from_(bucket).remove([path])
                )
            except Exception as e:
                logger.warning(f"Failed to delete video file: {e}")

        # Delete database record
        await asyncio.to_thread(
            lambda: self.supabase.table("veo_video_generations")
                .delete()
                .eq("id", str(generation_id))
                .execute()
        )

        logger.info(f"Deleted generation: {generation_id}")
        return True
