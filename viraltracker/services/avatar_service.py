"""
AvatarService - Brand Avatar Management Service.

Handles CRUD operations for brand avatars and integration with
Gemini for avatar image generation (Nano Banana pattern).
"""

import logging
import asyncio
from typing import Optional, List
from uuid import UUID
import uuid
from datetime import datetime
from io import BytesIO

from ..core.config import Config
from ..core.database import get_supabase_client
from .veo_models import (
    BrandAvatar,
    BrandAvatarCreate,
    AspectRatio,
    Resolution
)
from .gemini_service import GeminiService

logger = logging.getLogger(__name__)


class AvatarService:
    """
    Service for managing brand avatars.

    Features:
    - CRUD operations for avatars
    - Reference image upload/download
    - Avatar image generation via Gemini (Nano Banana)
    - Integration with VeoService for video generation
    """

    STORAGE_BUCKET = "avatars"

    def __init__(self, gemini_service: Optional[GeminiService] = None):
        """
        Initialize avatar service.

        Args:
            gemini_service: Optional GeminiService for image generation
        """
        self.supabase = get_supabase_client()
        self.gemini = gemini_service or GeminiService()
        logger.info("AvatarService initialized")

    def set_tracking_context(
        self,
        usage_tracker,
        user_id: Optional[str] = None,
        organization_id: Optional[str] = None
    ) -> None:
        """
        Set usage tracking context (passed through to GeminiService).

        Args:
            usage_tracker: UsageTracker instance
            user_id: User ID for tracking
            organization_id: Organization ID for billing
        """
        self.gemini.set_tracking_context(usage_tracker, user_id, organization_id)
        logger.debug(f"AvatarService usage tracking enabled for org: {organization_id}")

    # =========================================================================
    # CRUD Operations
    # =========================================================================

    async def create_avatar(
        self,
        data: BrandAvatarCreate,
        reference_images: Optional[List[bytes]] = None
    ) -> BrandAvatar:
        """
        Create a new brand avatar.

        Args:
            data: Avatar creation data
            reference_images: Optional list of reference image bytes (up to 4)

        Returns:
            Created BrandAvatar
        """
        avatar_id = uuid.uuid4()
        now = datetime.utcnow()

        # Upload reference images if provided
        ref_paths = [None, None, None, None]
        if reference_images:
            for i, img_bytes in enumerate(reference_images[:4]):
                path = f"{data.brand_id}/{avatar_id}/ref{i+1}.png"
                await self._upload_image(path, img_bytes)
                ref_paths[i] = f"{self.STORAGE_BUCKET}/{path}"

        # Insert into database
        record = {
            "id": str(avatar_id),
            "brand_id": str(data.brand_id),
            "name": data.name,
            "description": data.description,
            "reference_image_1": ref_paths[0],
            "reference_image_2": ref_paths[1],
            "reference_image_3": ref_paths[2],
            "reference_image_4": ref_paths[3],
            "generation_prompt": data.generation_prompt,
            "default_negative_prompt": data.default_negative_prompt,
            "default_aspect_ratio": data.default_aspect_ratio.value,
            "default_resolution": data.default_resolution.value,
            "default_duration_seconds": data.default_duration_seconds,
            "is_active": True
        }

        await asyncio.to_thread(
            lambda: self.supabase.table("brand_avatars").insert(record).execute()
        )

        logger.info(f"Created avatar: {avatar_id} for brand {data.brand_id}")

        return BrandAvatar(
            id=avatar_id,
            brand_id=data.brand_id,
            name=data.name,
            description=data.description,
            reference_image_1=ref_paths[0],
            reference_image_2=ref_paths[1],
            reference_image_3=ref_paths[2],
            reference_image_4=ref_paths[3],
            generation_prompt=data.generation_prompt,
            default_negative_prompt=data.default_negative_prompt,
            default_aspect_ratio=data.default_aspect_ratio,
            default_resolution=data.default_resolution,
            default_duration_seconds=data.default_duration_seconds,
            is_active=True,
            created_at=now,
            updated_at=now
        )

    async def get_avatar(self, avatar_id: UUID) -> Optional[BrandAvatar]:
        """
        Get an avatar by ID.

        Args:
            avatar_id: Avatar UUID

        Returns:
            BrandAvatar or None if not found
        """
        result = await asyncio.to_thread(
            lambda: self.supabase.table("brand_avatars")
                .select("*")
                .eq("id", str(avatar_id))
                .single()
                .execute()
        )

        if not result.data:
            return None

        return self._row_to_avatar(result.data)

    async def list_avatars(
        self,
        brand_id: Optional[UUID] = None,
        active_only: bool = True,
        limit: int = 50
    ) -> List[BrandAvatar]:
        """
        List avatars with optional filters.

        Args:
            brand_id: Filter by brand
            active_only: Only return active avatars
            limit: Max results

        Returns:
            List of BrandAvatar
        """
        query = self.supabase.table("brand_avatars").select("*")

        if brand_id:
            query = query.eq("brand_id", str(brand_id))
        if active_only:
            query = query.eq("is_active", True)

        result = await asyncio.to_thread(
            lambda: query.order("created_at", desc=True).limit(limit).execute()
        )

        return [self._row_to_avatar(row) for row in result.data]

    async def update_avatar(
        self,
        avatar_id: UUID,
        name: Optional[str] = None,
        description: Optional[str] = None,
        generation_prompt: Optional[str] = None,
        default_negative_prompt: Optional[str] = None,
        default_aspect_ratio: Optional[AspectRatio] = None,
        default_resolution: Optional[Resolution] = None,
        default_duration_seconds: Optional[int] = None,
        is_active: Optional[bool] = None
    ) -> Optional[BrandAvatar]:
        """
        Update an avatar's properties.

        Args:
            avatar_id: Avatar UUID to update
            name: New name
            description: New description
            generation_prompt: New generation prompt
            default_negative_prompt: New default negative prompt
            default_aspect_ratio: New default aspect ratio
            default_resolution: New default resolution
            default_duration_seconds: New default duration
            is_active: New active status

        Returns:
            Updated BrandAvatar or None if not found
        """
        updates = {}
        if name is not None:
            updates["name"] = name
        if description is not None:
            updates["description"] = description
        if generation_prompt is not None:
            updates["generation_prompt"] = generation_prompt
        if default_negative_prompt is not None:
            updates["default_negative_prompt"] = default_negative_prompt
        if default_aspect_ratio is not None:
            updates["default_aspect_ratio"] = default_aspect_ratio.value
        if default_resolution is not None:
            updates["default_resolution"] = default_resolution.value
        if default_duration_seconds is not None:
            updates["default_duration_seconds"] = default_duration_seconds
        if is_active is not None:
            updates["is_active"] = is_active

        if not updates:
            return await self.get_avatar(avatar_id)

        await asyncio.to_thread(
            lambda: self.supabase.table("brand_avatars")
                .update(updates)
                .eq("id", str(avatar_id))
                .execute()
        )

        logger.info(f"Updated avatar: {avatar_id}")
        return await self.get_avatar(avatar_id)

    async def delete_avatar(self, avatar_id: UUID) -> bool:
        """
        Delete an avatar and its reference images.

        Args:
            avatar_id: Avatar UUID to delete

        Returns:
            True if deleted, False if not found
        """
        avatar = await self.get_avatar(avatar_id)
        if not avatar:
            return False

        # Delete reference images from storage
        for path in avatar.reference_images:
            try:
                parts = path.split("/", 1)
                bucket = parts[0]
                file_path = parts[1] if len(parts) > 1 else path
                await asyncio.to_thread(
                    lambda p=file_path: self.supabase.storage.from_(bucket).remove([p])
                )
            except Exception as e:
                logger.warning(f"Failed to delete reference image: {e}")

        # Delete database record
        await asyncio.to_thread(
            lambda: self.supabase.table("brand_avatars")
                .delete()
                .eq("id", str(avatar_id))
                .execute()
        )

        logger.info(f"Deleted avatar: {avatar_id}")
        return True

    # =========================================================================
    # Reference Image Operations
    # =========================================================================

    async def add_reference_image(
        self,
        avatar_id: UUID,
        image_bytes: bytes,
        slot: int = 1
    ) -> Optional[str]:
        """
        Add or replace a reference image for an avatar.

        Args:
            avatar_id: Avatar UUID
            image_bytes: Image data
            slot: Image slot (1, 2, 3, or 4)

        Returns:
            Storage path of uploaded image, or None if avatar not found
        """
        if slot not in [1, 2, 3, 4]:
            raise ValueError("Slot must be 1, 2, 3, or 4")

        avatar = await self.get_avatar(avatar_id)
        if not avatar:
            return None

        # Upload image
        path = f"{avatar.brand_id}/{avatar_id}/ref{slot}.png"
        await self._upload_image(path, image_bytes)
        full_path = f"{self.STORAGE_BUCKET}/{path}"

        # Update database
        column = f"reference_image_{slot}"
        await asyncio.to_thread(
            lambda: self.supabase.table("brand_avatars")
                .update({column: full_path})
                .eq("id", str(avatar_id))
                .execute()
        )

        # Clear stale Kling element (references changed)
        await asyncio.to_thread(
            lambda: self.supabase.table("brand_avatars")
                .update({"kling_element_id": None})
                .eq("id", str(avatar_id))
                .not_.is_("kling_element_id", "null")
                .execute()
        )

        logger.info(f"Added reference image {slot} for avatar: {avatar_id}")
        return full_path

    async def remove_reference_image(self, avatar_id: UUID, slot: int) -> bool:
        """
        Remove a reference image from an avatar.

        Args:
            avatar_id: Avatar UUID
            slot: Image slot (1, 2, 3, or 4)

        Returns:
            True if removed
        """
        if slot not in [1, 2, 3, 4]:
            raise ValueError("Slot must be 1, 2, 3, or 4")

        avatar = await self.get_avatar(avatar_id)
        if not avatar:
            return False

        # Get current path
        current_path = getattr(avatar, f"reference_image_{slot}")
        if current_path:
            try:
                parts = current_path.split("/", 1)
                bucket = parts[0]
                file_path = parts[1] if len(parts) > 1 else current_path
                await asyncio.to_thread(
                    lambda: self.supabase.storage.from_(bucket).remove([file_path])
                )
            except Exception as e:
                logger.warning(f"Failed to delete reference image: {e}")

        # Update database
        column = f"reference_image_{slot}"
        await asyncio.to_thread(
            lambda: self.supabase.table("brand_avatars")
                .update({column: None})
                .eq("id", str(avatar_id))
                .execute()
        )

        # Clear stale Kling element (references changed)
        await asyncio.to_thread(
            lambda: self.supabase.table("brand_avatars")
                .update({"kling_element_id": None})
                .eq("id", str(avatar_id))
                .not_.is_("kling_element_id", "null")
                .execute()
        )

        logger.info(f"Removed reference image {slot} for avatar: {avatar_id}")
        return True

    async def get_reference_image_bytes(
        self,
        avatar_id: UUID,
        slot: int
    ) -> Optional[bytes]:
        """
        Download a reference image.

        Args:
            avatar_id: Avatar UUID
            slot: Image slot (1, 2, 3, or 4)

        Returns:
            Image bytes or None
        """
        avatar = await self.get_avatar(avatar_id)
        if not avatar:
            return None

        path = getattr(avatar, f"reference_image_{slot}")
        if not path:
            return None

        return await self._download_image(path)

    async def get_all_reference_images(self, avatar_id: UUID) -> List[bytes]:
        """
        Download all reference images for an avatar.

        Args:
            avatar_id: Avatar UUID

        Returns:
            List of image bytes (only non-null images)
        """
        avatar = await self.get_avatar(avatar_id)
        if not avatar:
            return []

        images = []
        for path in avatar.reference_images:
            try:
                img_bytes = await self._download_image(path)
                images.append(img_bytes)
            except Exception as e:
                logger.warning(f"Failed to download reference image: {e}")

        return images

    # =========================================================================
    # Avatar Image Generation (Nano Banana)
    # =========================================================================

    async def generate_avatar_image(
        self,
        prompt: str,
        reference_images: Optional[List[bytes]] = None,
        temperature: float = 0.4,
        image_size: str = "2K"
    ) -> bytes:
        """
        Generate an avatar image using Gemini (Nano Banana pattern).

        Uses Gemini 3 Pro Image Preview for character-consistent image generation.

        Args:
            prompt: Description of the avatar to generate
            reference_images: Optional existing reference images for consistency (as bytes)
            temperature: Generation temperature (0.0-1.0)
            image_size: Output size ("1K", "2K", "4K")

        Returns:
            Generated image bytes (PNG)
        """
        import base64

        # Build prompt for character consistency
        full_prompt = f"""Generate a high-quality portrait image of a person for use as a brand avatar.

{prompt}

Requirements:
- Professional, friendly appearance
- Clear face with good lighting
- Suitable for video generation
- High detail on facial features
- Neutral or professional background
"""

        # Convert reference images from bytes to base64 (GeminiService expects base64)
        ref_images_b64 = None
        if reference_images:
            ref_images_b64 = [
                base64.b64encode(img_bytes).decode('utf-8')
                for img_bytes in reference_images
            ]

        # Generate image via Gemini
        result = await self.gemini.generate_image(
            prompt=full_prompt,
            reference_images=ref_images_b64,
            temperature=temperature,
            image_size=image_size
        )

        # Convert base64 to bytes
        return base64.b64decode(result)

    async def generate_and_save_avatar_image(
        self,
        avatar_id: UUID,
        prompt: str,
        slot: int = 1,
        use_existing_refs: bool = True
    ) -> Optional[str]:
        """
        Generate a new avatar image and save it to a reference slot.

        Args:
            avatar_id: Avatar UUID
            prompt: Generation prompt
            slot: Slot to save to (1-4)
            use_existing_refs: Use existing reference images for consistency

        Returns:
            Storage path of generated image, or None if avatar not found
        """
        avatar = await self.get_avatar(avatar_id)
        if not avatar:
            return None

        # Get existing references for consistency
        existing_refs = []
        if use_existing_refs:
            existing_refs = await self.get_all_reference_images(avatar_id)

        # Generate new image
        image_bytes = await self.generate_avatar_image(
            prompt=prompt,
            reference_images=existing_refs if existing_refs else None
        )

        # Save to slot
        return await self.add_reference_image(avatar_id, image_bytes, slot)

    # =========================================================================
    # Angle-Based Generation (Kling Element Workflow)
    # =========================================================================

    ANGLE_PROMPTS = {
        1: "Frontal passport-style portrait. Face directly facing camera, neutral expression, "
           "clean solid-color background, even studio lighting, square composition.",
        2: "3/4 view portrait of the SAME person. Face turned ~45 degrees to the right, "
           "same outfit and hairstyle, clean background, same lighting. "
           "Maintain exact facial features, skin tone, and hair.",
        3: "Side profile portrait of the SAME person. Pure side view facing right, "
           "showing jawline, ear, and hair. Same outfit, clean background, same lighting.",
        4: "Full-body front-facing photo of the SAME person. Standing straight, facing camera, "
           "full body visible head to feet, portrait orientation. Same outfit and hairstyle, "
           "clean background, even studio lighting.",
    }

    ANGLE_LABELS = {1: "Frontal", 2: "3/4 View", 3: "Side Profile", 4: "Full Body"}

    async def generate_angle_image(
        self, avatar_id: UUID, slot: int, custom_prompt_suffix: Optional[str] = None
    ) -> Optional[str]:
        """Generate an angle-specific reference image and save it to a slot.

        Uses angle-specific prompt templates with sequential reference chaining:
        each subsequent angle uses all prior slot images as references for consistency.

        Args:
            avatar_id: Avatar UUID.
            slot: Target slot (1-4).
            custom_prompt_suffix: Optional extra prompt text to append.

        Returns:
            Storage path of generated image, or None on failure.
        """
        import base64

        if slot not in self.ANGLE_PROMPTS:
            raise ValueError(f"Slot must be 1-4, got {slot}")

        avatar = await self.get_avatar(avatar_id)
        if not avatar:
            return None

        # Build prompt: character description + angle instruction
        char_desc = avatar.generation_prompt or "A person"
        angle_prompt = self.ANGLE_PROMPTS[slot]
        full_prompt = f"{char_desc}\n\n{angle_prompt}"
        if custom_prompt_suffix:
            full_prompt += f"\n\n{custom_prompt_suffix}"

        # Collect prior slot images as references for consistency
        reference_images = []
        for prior_slot in range(1, slot):
            ref_path = getattr(avatar, f"reference_image_{prior_slot}")
            if ref_path:
                try:
                    img_bytes = await self._download_image(ref_path)
                    reference_images.append(img_bytes)
                except Exception as e:
                    logger.warning(f"Failed to load ref slot {prior_slot}: {e}")

        # Generate with low temperature for consistency
        try:
            image_bytes = await self.generate_avatar_image(
                prompt=full_prompt,
                reference_images=reference_images if reference_images else None,
                temperature=0.3,
            )
        except Exception as e:
            # Check for safety filter errors
            error_str = str(e).lower()
            if "safety" in error_str or "blocked" in error_str or "filter" in error_str:
                logger.warning(f"Safety filter blocked generation for avatar {avatar_id} slot {slot}: {e}")
                return None
            raise

        # Save to slot
        return await self.add_reference_image(avatar_id, image_bytes, slot)

    async def create_kling_element(
        self, avatar_id: UUID, organization_id: str, brand_id: str
    ) -> Optional[str]:
        """Create a Kling element from the avatar's reference images.

        Validates frontal image (slot 1) exists, gets signed URLs for all
        reference images, and calls Kling's element creation API.

        Args:
            avatar_id: Avatar UUID.
            organization_id: Organization UUID for billing.
            brand_id: Brand UUID.

        Returns:
            Kling element_id string, or None on failure.
        """
        # Resolve real org_id for superuser "all" mode
        if organization_id == "all":
            try:
                brand_row = await asyncio.to_thread(
                    lambda: self.supabase.table("brands")
                        .select("organization_id")
                        .eq("id", brand_id)
                        .single()
                        .execute()
                )
                organization_id = brand_row.data["organization_id"]
            except Exception as e:
                logger.error(f"Failed to resolve org_id from brand {brand_id}: {e}")
                return None

        avatar = await self.get_avatar(avatar_id)
        if not avatar:
            logger.error(f"Avatar {avatar_id} not found")
            return None

        if not avatar.reference_image_1:
            logger.error(f"Avatar {avatar_id} has no frontal image (slot 1)")
            return None

        # Get signed URL for frontal image
        frontal_url = await self.get_reference_image_url(avatar_id, 1)
        if not frontal_url:
            logger.error(f"Failed to get frontal image URL for avatar {avatar_id}")
            return None

        # Get signed URLs for additional reference images (slots 2-4)
        refer_images = []
        for slot in [2, 3, 4]:
            ref_path = getattr(avatar, f"reference_image_{slot}")
            if ref_path:
                url = await self.get_reference_image_url(avatar_id, slot)
                if url:
                    refer_images.append(url)

        from .kling_video_service import KlingVideoService
        from .kling_models import KlingEndpoint

        kling = KlingVideoService()
        try:
            gen_result = await kling.create_element(
                organization_id=organization_id,
                brand_id=brand_id,
                element_name=avatar.name[:20],
                element_description=f"Brand avatar: {avatar.name}"[:100],
                frontal_image=frontal_url,
                refer_images=refer_images if refer_images else None,
            )

            task_id = gen_result.get("kling_task_id")
            if not task_id:
                logger.error(f"No task_id returned for avatar {avatar_id} element creation")
                return None

            poll_result = await kling.poll_task(
                task_id=task_id,
                endpoint_type=KlingEndpoint.ADVANCED_CUSTOM_ELEMENTS,
                timeout_seconds=600,
            )

            task_data = poll_result.get("data", {})
            task_status = task_data.get("task_status", "")
            task_result = task_data.get("task_result", {})

            if task_status == "succeed":
                elements = task_result.get("elements", [])
                element_id = elements[0].get("element_id") if elements else None
                if element_id:
                    await asyncio.to_thread(
                        lambda: self.supabase.table("brand_avatars")
                            .update({"kling_element_id": element_id})
                            .eq("id", str(avatar_id))
                            .execute()
                    )
                    logger.info(f"Created Kling element {element_id} for avatar {avatar_id}")
                    return element_id
                else:
                    logger.warning(f"Element created but no element_id in response for avatar {avatar_id}")
                    return None
            else:
                error_msg = task_data.get("task_status_msg", "Unknown error")
                logger.error(f"Element creation failed for avatar {avatar_id}: {error_msg}")
                return None

        except Exception as e:
            logger.error(f"Element creation failed for avatar {avatar_id}: {e}")
            return None
        finally:
            await kling.close()

    # =========================================================================
    # Video Avatar Methods (Video Element + Voice)
    # =========================================================================

    async def _upload_video(
        self, brand_id: str, avatar_id: str, video_bytes: bytes, filename: str = "calibration_video.mp4"
    ) -> str:
        """Upload video to Supabase storage.

        Args:
            brand_id: Brand UUID string.
            avatar_id: Avatar UUID string.
            video_bytes: Video file bytes.
            filename: Target filename.

        Returns:
            Full storage path (bucket/path).
        """
        path = f"{brand_id}/{avatar_id}/{filename}"
        await asyncio.to_thread(
            lambda: self.supabase.storage.from_(self.STORAGE_BUCKET).upload(
                path, video_bytes, {"content-type": "video/mp4", "upsert": "true"}
            )
        )
        return f"{self.STORAGE_BUCKET}/{path}"

    async def _get_video_signed_url(self, storage_path: str, expires_in: int = 86400) -> str:
        """Get a signed URL for a video in storage.

        Args:
            storage_path: Full storage path (bucket/path).
            expires_in: URL expiry in seconds (default 24h for Kling async workers).

        Returns:
            Signed URL string.
        """
        parts = storage_path.split("/", 1)
        bucket = parts[0]
        file_path = parts[1] if len(parts) > 1 else storage_path

        result = await asyncio.to_thread(
            lambda: self.supabase.storage.from_(bucket).create_signed_url(
                file_path, expires_in
            )
        )
        return result.get("signedURL", "")

    async def generate_calibration_video(
        self, avatar_id: UUID, organization_id: str, brand_id: str
    ) -> dict:
        """Generate an 8-second calibration video from the avatar's image element.

        Uses Kling Omni-Video to create a comprehensive all-angle showcase
        with natural speech, suitable for creating a video element with voice.
        If the avatar has a Kling image element (created from all reference images),
        it is used via element_list for better angle consistency. Otherwise falls
        back to using the frontal image as first_frame.

        Args:
            avatar_id: Avatar UUID.
            organization_id: Organization UUID.
            brand_id: Brand UUID.

        Returns:
            Dict with calibration_video_path and signed_url.

        Raises:
            ValueError: If avatar has no element and no frontal image.
        """
        avatar = await self.get_avatar(avatar_id)
        if not avatar:
            raise ValueError(f"Avatar {avatar_id} not found")

        # Resolve org_id for superuser mode
        if organization_id == "all":
            try:
                brand_row = await asyncio.to_thread(
                    lambda: self.supabase.table("brands")
                        .select("organization_id")
                        .eq("id", brand_id)
                        .single()
                        .execute()
                )
                organization_id = brand_row.data["organization_id"]
            except Exception as e:
                raise ValueError(f"Failed to resolve org_id from brand {brand_id}: {e}")

        from .kling_video_service import KlingVideoService
        from .kling_models import KlingEndpoint

        # Prefer using the image element (built from all reference angles)
        if avatar.kling_element_id:
            calibration_prompt = (
                "<<<element_1>>> Close-up of the person's face, looking directly at camera, speaking naturally. "
                "They slowly turn their head to the left, then to the right, then back to center. "
                "Camera smoothly pulls back to reveal their full body from head to toe. "
                "They slowly turn around 360 degrees to show all angles, then face the camera again. "
                "Neutral background, steady camera, warm professional lighting throughout."
            )
            element_list = [{"element_id": avatar.kling_element_id}]
            image_list = None
            logger.info(f"Using image element {avatar.kling_element_id} for calibration video")
        else:
            # Fallback: use frontal image as first_frame
            if not avatar.reference_image_1:
                raise ValueError(f"Avatar {avatar_id} has no element or frontal image (slot 1)")
            frontal_url = await self.get_reference_image_url(avatar_id, 1)
            if not frontal_url:
                raise ValueError(f"Failed to get frontal image URL for avatar {avatar_id}")
            calibration_prompt = (
                "Close-up of the person's face, looking directly at camera, speaking naturally. "
                "They slowly turn their head to the left, then to the right, then back to center. "
                "Camera smoothly pulls back to reveal their full body from head to toe. "
                "They slowly turn around 360 degrees to show all angles, then face the camera again. "
                "Neutral background, steady camera, warm professional lighting throughout."
            )
            element_list = None
            image_list = [{"image_url": frontal_url, "type": "first_frame"}]
            logger.info(f"No image element found, using frontal image for calibration video")

        kling = KlingVideoService()
        try:
            gen_result = await kling.generate_omni_video(
                organization_id=organization_id,
                brand_id=brand_id,
                prompt=calibration_prompt,
                duration="8",
                mode="pro",
                sound="on",
                image_list=image_list,
                element_list=element_list,
                aspect_ratio="9:16",
            )

            task_id = gen_result.get("kling_task_id")
            generation_id = gen_result.get("generation_id")
            if not task_id:
                raise ValueError("No task_id returned for calibration video generation")

            # Poll to completion (up to 15 min)
            completion = await kling.poll_and_complete(
                generation_id=generation_id,
                kling_task_id=task_id,
                endpoint_type=KlingEndpoint.OMNI_VIDEO,
                timeout_seconds=900,
            )

            if completion.get("status") != "succeed":
                error_msg = completion.get("error_message", "Unknown error")
                raise ValueError(f"Calibration video generation failed: {error_msg}")

            video_storage_path = completion.get("video_storage_path")
            if not video_storage_path:
                raise ValueError("Calibration video completed but no storage path returned")

            # Update avatar with calibration video path
            await asyncio.to_thread(
                lambda: self.supabase.table("brand_avatars")
                    .update({"calibration_video_path": video_storage_path})
                    .eq("id", str(avatar_id))
                    .execute()
            )

            signed_url = await self._get_video_signed_url(video_storage_path)

            logger.info(f"Generated calibration video for avatar {avatar_id}: {video_storage_path}")
            return {
                "calibration_video_path": video_storage_path,
                "signed_url": signed_url,
            }

        finally:
            await kling.close()

    async def _verify_video_url(self, url: str) -> None:
        """Verify a video URL is fetchable by Kling's workers.

        Checks that the URL returns 200, has Content-Type video/mp4,
        has Content-Length, and supports Range requests. Logs warnings
        for any issues but does not raise (Kling may still succeed).

        Args:
            url: Signed video URL to verify.
        """
        import httpx

        try:
            async with httpx.AsyncClient(timeout=10) as client:
                # HEAD request to check basic fetchability
                head = await client.head(url, follow_redirects=True)
                status = head.status_code
                content_type = head.headers.get("content-type", "")
                content_length = head.headers.get("content-length", "")
                accept_ranges = head.headers.get("accept-ranges", "")

                logger.info(
                    f"Video URL check: status={status}, "
                    f"content-type={content_type}, "
                    f"content-length={content_length}, "
                    f"accept-ranges={accept_ranges}"
                )

                if status != 200:
                    logger.warning(f"Video URL returned {status} (expected 200)")
                if "video" not in content_type:
                    logger.warning(f"Video URL content-type is '{content_type}' (expected video/mp4)")
                if not content_length:
                    logger.warning("Video URL missing Content-Length header")

                # Range request to check partial content support
                range_resp = await client.head(
                    url, headers={"Range": "bytes=0-1023"}, follow_redirects=True
                )
                if range_resp.status_code == 206:
                    logger.info("Video URL supports Range requests (206)")
                else:
                    logger.warning(
                        f"Video URL Range request returned {range_resp.status_code} "
                        f"(expected 206 Partial Content)"
                    )

        except Exception as e:
            logger.warning(f"Video URL verification failed: {e}")

    async def _poll_for_voice_completion(
        self, kling, task_id: str, max_attempts: int = 40, interval_seconds: int = 15
    ) -> str:
        """Poll custom voice creation task until it completes and returns voice_id.

        Uses the dedicated custom-voices query endpoint (3-51) which returns
        task_result.voices[0].voice_id on success.

        Args:
            kling: KlingVideoService instance.
            task_id: Kling task_id from create_custom_voice response.
            max_attempts: Max number of query attempts (default 40 = ~10 minutes).
            interval_seconds: Seconds between attempts (default 15).

        Returns:
            voice_id string.

        Raises:
            ValueError: If voice creation fails or times out.
        """
        for attempt in range(1, max_attempts + 1):
            query_result = await kling.query_custom_voice(task_id)
            query_data = query_result.get("data", {})
            task_status = query_data.get("task_status", "")

            # Log periodically for debugging
            if attempt == 1 or attempt % 5 == 0:
                import json as _json
                logger.info(
                    f"Voice query (attempt {attempt}/{max_attempts}): "
                    f"status={task_status}, "
                    f"response={_json.dumps(query_result, indent=2, default=str)}"
                )

            if task_status == "failed":
                error_msg = query_data.get("task_status_msg", "Unknown error")
                raise ValueError(f"Custom voice creation failed: {error_msg}")

            if task_status == "succeed":
                task_result = query_data.get("task_result", {})
                voices = task_result.get("voices", [])
                if voices:
                    voice_id = str(voices[0].get("voice_id", ""))
                    voice_name = voices[0].get("voice_name", "")
                    trial_url = voices[0].get("trial_url", "")
                    logger.info(
                        f"Custom voice created on attempt {attempt}: "
                        f"voice_id={voice_id}, voice_name={voice_name}, "
                        f"trial_url={trial_url}"
                    )
                    return voice_id
                raise ValueError("Voice creation succeeded but no voices in response")

            if attempt < max_attempts:
                logger.info(
                    f"Voice creation in progress (attempt {attempt}/{max_attempts}, "
                    f"status={task_status}), waiting {interval_seconds}s..."
                )
                await asyncio.sleep(interval_seconds)

        raise ValueError(
            f"Voice creation timed out after {max_attempts} attempts "
            f"(~{max_attempts * interval_seconds}s)"
        )

    async def _poll_for_element_id(
        self, kling, task_id: str, max_attempts: int = 40, interval_seconds: int = 15
    ) -> str:
        """Poll element query endpoint until element completes and returns element_id.

        Args:
            kling: KlingVideoService instance.
            task_id: Kling task_id from element creation.
            max_attempts: Max number of query attempts.
            interval_seconds: Seconds between attempts.

        Returns:
            element_id string.

        Raises:
            ValueError: If element creation fails or times out.
        """
        for attempt in range(1, max_attempts + 1):
            query_result = await kling.query_element(task_id)
            query_data = query_result.get("data", {})
            task_status = query_data.get("task_status", "")
            task_result = query_data.get("task_result", {})
            elements = task_result.get("elements", [])

            if attempt == 1 or attempt % 5 == 0:
                import json as _json
                logger.info(
                    f"Element query (attempt {attempt}/{max_attempts}): "
                    f"status={task_status}, "
                    f"response={_json.dumps(query_result, indent=2, default=str)}"
                )

            if task_status == "failed":
                error_msg = query_data.get("task_status_msg", "Unknown error")
                raise ValueError(f"Element creation failed: {error_msg}")

            if task_status == "succeed" and elements:
                element_id = str(elements[0].get("element_id", ""))
                logger.info(f"Element created on attempt {attempt}: element_id={element_id}")
                return element_id

            if attempt < max_attempts:
                await asyncio.sleep(interval_seconds)

        raise ValueError(
            f"Element creation timed out after {max_attempts} attempts "
            f"(~{max_attempts * interval_seconds}s)"
        )

    async def extract_voice_from_video(
        self, avatar_id: UUID, organization_id: str, brand_id: str, video_bytes: bytes
    ) -> str:
        """Upload a voice sample video and create a custom voice from it.

        Uses the dedicated Create Custom Voice endpoint (POST /v1/general/custom-voices)
        which accepts video files directly for voice cloning. This replaces the previous
        approach of creating a video element and hoping for auto-extraction.

        Args:
            avatar_id: Avatar UUID.
            organization_id: Organization UUID.
            brand_id: Brand UUID.
            video_bytes: Voice sample video bytes (.mp4/.mov, 5-30s with clear speech).

        Returns:
            Created voice_id string.

        Raises:
            ValueError: If voice creation fails or avatar not found.
        """
        avatar = await self.get_avatar(avatar_id)
        if not avatar:
            raise ValueError(f"Avatar {avatar_id} not found")

        # Resolve org_id for superuser mode
        if organization_id == "all":
            try:
                brand_row = await asyncio.to_thread(
                    lambda: self.supabase.table("brands")
                        .select("organization_id")
                        .eq("id", brand_id)
                        .single()
                        .execute()
                )
                organization_id = brand_row.data["organization_id"]
            except Exception as e:
                raise ValueError(f"Failed to resolve org_id from brand {brand_id}: {e}")

        # Normalize video to exact Kling specs (resolution, codec, audio)
        from .ffmpeg_service import FFmpegService
        ffmpeg_svc = FFmpegService()
        video_bytes = await asyncio.to_thread(ffmpeg_svc.normalize_video_for_kling, video_bytes)

        # Upload voice video to storage
        voice_path = await self._upload_video(
            str(avatar.brand_id), str(avatar_id), video_bytes, "voice_sample.mp4"
        )
        voice_url = await self._get_video_signed_url(voice_path)
        await self._verify_video_url(voice_url)

        from .kling_video_service import KlingVideoService

        kling = KlingVideoService()
        try:
            # Create custom voice directly from video URL
            voice_result = await kling.create_custom_voice(
                organization_id=organization_id,
                brand_id=brand_id,
                voice_name=f"{avatar.name[:14]}_voice",
                voice_url=voice_url,
            )

            task_id = voice_result.get("kling_task_id")
            if not task_id:
                raise ValueError("No task_id returned for custom voice creation")

            logger.info(
                f"Custom voice creation submitted: task_id={task_id}, "
                f"avatar={avatar_id}, name={avatar.name}"
            )

            # Poll for voice creation completion (~2-5 minutes typical)
            voice_id = await self._poll_for_voice_completion(
                kling, task_id, max_attempts=40, interval_seconds=15
            )

            if not voice_id:
                raise ValueError(
                    "Voice creation completed but no voice_id returned. "
                    "Please upload a video with clear speech (5-30s, one speaker)."
                )

            voice_id = str(voice_id)

            # Store voice_id on avatar
            await asyncio.to_thread(
                lambda: self.supabase.table("brand_avatars")
                    .update({"kling_voice_id": voice_id})
                    .eq("id", str(avatar_id))
                    .execute()
            )

            logger.info(f"Created custom voice {voice_id} for avatar {avatar_id}")
            return voice_id

        finally:
            await kling.close()

    async def combine_video_with_voice(
        self, calibration_video_path: str, voice_audio_bytes: bytes
    ) -> bytes:
        """Download calibration video and replace its audio with voice sample audio.

        Args:
            calibration_video_path: Supabase storage path for the calibration video.
            voice_audio_bytes: Audio bytes extracted from the user's voice sample.

        Returns:
            Combined video bytes (calibration visuals + voice audio).

        Raises:
            ValueError: If download or FFmpeg processing fails.
        """
        # Download calibration video (reuse _download_image — it's content-agnostic)
        video_bytes = await self._download_image(calibration_video_path)

        from .ffmpeg_service import FFmpegService
        ffmpeg_svc = FFmpegService()
        combined = await asyncio.to_thread(
            ffmpeg_svc.replace_audio, video_bytes, voice_audio_bytes
        )
        logger.info(
            f"Combined calibration video ({len(video_bytes)} bytes) with voice audio "
            f"({len(voice_audio_bytes)} bytes) -> {len(combined)} bytes"
        )
        return combined

    async def create_kling_video_element(
        self,
        avatar_id: UUID,
        organization_id: str,
        brand_id: str,
        video_bytes: Optional[bytes] = None,
        voice_embedded_video_bytes: Optional[bytes] = None,
    ) -> dict:
        """Create a video-based Kling element with voice.

        Two modes:
        1. voice_embedded_video_bytes provided: Upload directly, skip normalization
           and skip separate voice creation (voice is already in the video).
        2. video_bytes provided: Normalize, upload, create voice separately.
        3. Neither: Generate calibration video, create voice separately.

        Args:
            avatar_id: Avatar UUID.
            organization_id: Organization UUID.
            brand_id: Brand UUID.
            video_bytes: Optional raw video file bytes (will be normalized).
            voice_embedded_video_bytes: Optional pre-combined video with voice
                embedded. Skips normalization and voice creation.

        Returns:
            Dict with element_id, voice_id, calibration_video_path.

        Raises:
            ValueError: If avatar not found or missing frontal image.
        """
        avatar = await self.get_avatar(avatar_id)
        if not avatar:
            raise ValueError(f"Avatar {avatar_id} not found")

        # Resolve org_id for superuser mode
        if organization_id == "all":
            try:
                brand_row = await asyncio.to_thread(
                    lambda: self.supabase.table("brands")
                        .select("organization_id")
                        .eq("id", brand_id)
                        .single()
                        .execute()
                )
                organization_id = brand_row.data["organization_id"]
            except Exception as e:
                raise ValueError(f"Failed to resolve org_id from brand {brand_id}: {e}")

        if voice_embedded_video_bytes:
            # Mode: Voice already embedded — skip normalization to preserve audio quality
            video_path = await self._upload_video(
                str(avatar.brand_id), str(avatar_id),
                voice_embedded_video_bytes, "video_element_source.mp4"
            )
            video_url = await self._get_video_signed_url(video_path)
            calibration_path = video_path
            skip_voice_creation = True
            logger.info(f"Using voice-embedded video for avatar {avatar_id} (skipping normalization)")

        elif video_bytes:
            # Normalize video to exact Kling specs (resolution, codec, audio)
            from .ffmpeg_service import FFmpegService
            ffmpeg_svc = FFmpegService()
            video_bytes = await asyncio.to_thread(ffmpeg_svc.normalize_video_for_kling, video_bytes)

            # Mode: Upload video directly (visual + voice from upload)
            video_path = await self._upload_video(
                str(avatar.brand_id), str(avatar_id), video_bytes, "video_element_source.mp4"
            )
            video_url = await self._get_video_signed_url(video_path)
            calibration_path = video_path
            skip_voice_creation = False
        else:
            # Mode: Generate calibration video from frontal image
            if not avatar.reference_image_1:
                raise ValueError(f"Avatar {avatar_id} has no frontal image (slot 1) for calibration video")

            # Check if calibration video already exists
            if avatar.calibration_video_path:
                calibration_path = avatar.calibration_video_path
                video_url = await self._get_video_signed_url(calibration_path)
                logger.info(f"Reusing existing calibration video: {calibration_path}")
            else:
                cal_result = await self.generate_calibration_video(
                    avatar_id, organization_id, brand_id
                )
                calibration_path = cal_result["calibration_video_path"]
                video_url = cal_result["signed_url"]
            skip_voice_creation = False

        # Verify the video URL is fetchable by Kling's workers
        await self._verify_video_url(video_url)

        from .kling_video_service import KlingVideoService
        from .kling_models import KlingEndpoint

        kling = KlingVideoService()
        try:
            # Step 1: Create custom voice from the video if needed
            voice_id = None
            if skip_voice_creation:
                # Voice is embedded in the video — Kling will auto-extract it
                logger.info(f"Skipping voice creation for avatar {avatar_id} (voice embedded in video)")
            else:
                voice_id = avatar.kling_voice_id
                if not voice_id:
                    logger.info(
                        f"No existing voice_id for avatar {avatar_id}, "
                        f"creating custom voice from video..."
                    )
                    voice_result = await kling.create_custom_voice(
                        organization_id=organization_id,
                        brand_id=brand_id,
                        voice_name=f"{avatar.name[:14]}_voice",
                        voice_url=video_url,
                    )
                    voice_task_id = voice_result.get("kling_task_id")
                    if not voice_task_id:
                        logger.warning("No task_id returned for voice creation, proceeding without voice")
                    else:
                        try:
                            voice_id = await self._poll_for_voice_completion(
                                kling, voice_task_id, max_attempts=40, interval_seconds=15
                            )
                            logger.info(f"Custom voice created: voice_id={voice_id}")
                        except ValueError as e:
                            logger.warning(
                                f"Voice creation failed ({e}), proceeding without voice. "
                                f"Element will be created for visual only."
                            )
                            voice_id = None
                else:
                    logger.info(f"Reusing existing voice_id={voice_id} for avatar {avatar_id}")

            # Step 2: Create video element
            # When voice is embedded, don't pass element_voice_id (Kling auto-extracts)
            gen_result = await kling.create_video_element(
                organization_id=organization_id,
                brand_id=brand_id,
                element_name=avatar.name[:20],
                element_description=f"Video avatar: {avatar.name}"[:100],
                video_url=video_url,
                element_voice_id=voice_id if not skip_voice_creation else None,
            )

            task_id = gen_result.get("kling_task_id")
            if not task_id:
                raise ValueError("No task_id returned for video element creation")

            # Poll for element completion
            poll_result = await kling.poll_task(
                task_id=task_id,
                endpoint_type=KlingEndpoint.ADVANCED_CUSTOM_ELEMENTS,
                timeout_seconds=600,
            )

            task_data = poll_result.get("data", {})
            task_status = task_data.get("task_status", "")

            if task_status != "succeed":
                error_msg = task_data.get("task_status_msg", "Unknown error")
                raise ValueError(f"Video element creation failed: {error_msg}")

            # Extract element_id and element_voice_info from the completed task
            task_result = task_data.get("task_result", {})
            elements = task_result.get("elements", [])
            if not elements:
                raise ValueError("Element creation succeeded but no elements in response")

            element_data = elements[0]
            element_id = str(element_data.get("element_id", ""))

            # Extract auto-generated voice info (Kling auto-extracts voice
            # from videos with speech audio during element creation)
            element_voice_info = element_data.get("element_voice_info", {})
            auto_voice_id = element_voice_info.get("voice_id") if element_voice_info else None
            auto_voice_name = element_voice_info.get("voice_name", "") if element_voice_info else ""
            auto_trial_url = element_voice_info.get("trial_url", "") if element_voice_info else ""

            logger.info(
                f"Element creation response for avatar {avatar_id}: "
                f"element_id={element_id}, "
                f"element_voice_info={element_voice_info}, "
                f"auto_voice_id={auto_voice_id}, "
                f"auto_voice_name={auto_voice_name}, "
                f"trial_url={auto_trial_url}"
            )

            # Use auto-extracted voice_id if we don't already have one
            # (i.e., voice was embedded in the video rather than created separately)
            if not voice_id and auto_voice_id:
                voice_id = str(auto_voice_id)
                logger.info(
                    f"Using auto-extracted voice_id={voice_id} from element creation "
                    f"(voice_name={auto_voice_name})"
                )

            # Update avatar with new element info
            updates = {
                "kling_element_id": element_id,
                "calibration_video_path": calibration_path,
                "avatar_setup_mode": "video_element",
            }
            if voice_id:
                updates["kling_voice_id"] = str(voice_id)

            await asyncio.to_thread(
                lambda: self.supabase.table("brand_avatars")
                    .update(updates)
                    .eq("id", str(avatar_id))
                    .execute()
            )

            logger.info(
                f"Created video element {element_id} for avatar {avatar_id} "
                f"(voice_id: {voice_id or 'none'}, source: {'auto-extracted' if auto_voice_id else 'separate' if voice_id else 'none'})"
            )

            return {
                "element_id": element_id,
                "voice_id": str(voice_id) if voice_id else None,
                "calibration_video_path": calibration_path,
                "element_voice_info": element_voice_info,
            }

        finally:
            await kling.close()

    # =========================================================================
    # Image URL Operations
    # =========================================================================

    async def get_reference_image_url(
        self,
        avatar_id: UUID,
        slot: int,
        expires_in: int = 3600
    ) -> Optional[str]:
        """
        Get a signed URL for a reference image.

        Args:
            avatar_id: Avatar UUID
            slot: Image slot (1, 2, 3, or 4)
            expires_in: URL expiry in seconds

        Returns:
            Signed URL or None
        """
        avatar = await self.get_avatar(avatar_id)
        if not avatar:
            return None

        path = getattr(avatar, f"reference_image_{slot}")
        if not path:
            return None

        parts = path.split("/", 1)
        bucket = parts[0]
        file_path = parts[1] if len(parts) > 1 else path

        result = await asyncio.to_thread(
            lambda: self.supabase.storage.from_(bucket).create_signed_url(
                file_path, expires_in
            )
        )

        return result.get("signedURL", "")

    # =========================================================================
    # Helper Methods
    # =========================================================================

    async def _upload_image(self, path: str, data: bytes) -> None:
        """Upload image to storage."""
        await asyncio.to_thread(
            lambda: self.supabase.storage.from_(self.STORAGE_BUCKET).upload(
                path,
                data,
                {"content-type": "image/png"}
            )
        )

    async def _download_image(self, storage_path: str) -> bytes:
        """Download image from storage."""
        parts = storage_path.split("/", 1)
        bucket = parts[0]
        path = parts[1] if len(parts) > 1 else storage_path

        return await asyncio.to_thread(
            lambda: self.supabase.storage.from_(bucket).download(path)
        )

    def _row_to_avatar(self, row: dict) -> BrandAvatar:
        """Convert database row to BrandAvatar model."""
        return BrandAvatar(
            id=UUID(row["id"]),
            brand_id=UUID(row["brand_id"]),
            name=row["name"],
            description=row.get("description"),
            reference_image_1=row.get("reference_image_1"),
            reference_image_2=row.get("reference_image_2"),
            reference_image_3=row.get("reference_image_3"),
            reference_image_4=row.get("reference_image_4"),
            kling_element_id=row.get("kling_element_id"),
            kling_voice_id=row.get("kling_voice_id"),
            calibration_video_path=row.get("calibration_video_path"),
            voice_sample_path=row.get("voice_sample_path"),
            avatar_setup_mode=row.get("avatar_setup_mode", "multi_image"),
            generation_prompt=row.get("generation_prompt"),
            default_negative_prompt=row.get(
                "default_negative_prompt",
                "blurry, low quality, distorted, deformed, ugly, bad anatomy"
            ),
            default_aspect_ratio=AspectRatio(
                row.get("default_aspect_ratio", "16:9")
            ),
            default_resolution=Resolution(
                row.get("default_resolution", "1080p")
            ),
            default_duration_seconds=row.get("default_duration_seconds", 8),
            is_active=row.get("is_active", True),
            created_at=datetime.fromisoformat(
                row["created_at"].replace('Z', '+00:00')
            ),
            updated_at=datetime.fromisoformat(
                row["updated_at"].replace('Z', '+00:00')
            )
        )
