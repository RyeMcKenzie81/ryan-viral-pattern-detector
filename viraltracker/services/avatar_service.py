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
            reference_images: Optional list of reference image bytes (up to 3)

        Returns:
            Created BrandAvatar
        """
        avatar_id = uuid.uuid4()
        now = datetime.utcnow()

        # Upload reference images if provided
        ref_paths = [None, None, None]
        if reference_images:
            for i, img_bytes in enumerate(reference_images[:3]):
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
            slot: Image slot (1, 2, or 3)

        Returns:
            Storage path of uploaded image, or None if avatar not found
        """
        if slot not in [1, 2, 3]:
            raise ValueError("Slot must be 1, 2, or 3")

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

        logger.info(f"Added reference image {slot} for avatar: {avatar_id}")
        return full_path

    async def remove_reference_image(self, avatar_id: UUID, slot: int) -> bool:
        """
        Remove a reference image from an avatar.

        Args:
            avatar_id: Avatar UUID
            slot: Image slot (1, 2, or 3)

        Returns:
            True if removed
        """
        if slot not in [1, 2, 3]:
            raise ValueError("Slot must be 1, 2, or 3")

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
            slot: Image slot (1, 2, or 3)

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
            slot: Slot to save to (1, 2, or 3)
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
            slot: Image slot (1, 2, or 3)
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
