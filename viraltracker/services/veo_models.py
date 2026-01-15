"""
Pydantic models for Veo video generation and brand avatars.

These models provide type-safe, validated data structures for:
- Brand avatar management (BrandAvatar)
- Veo video generation requests and results (VeoGenerationRequest, VeoGenerationResult)
- Video generation configuration (VeoConfig)
"""

from pydantic import BaseModel, Field, field_validator
from datetime import datetime
from typing import List, Optional, Dict, Any, Literal
from uuid import UUID
from enum import Enum


# ============================================================================
# Enums
# ============================================================================

class AspectRatio(str, Enum):
    """Valid aspect ratios for Veo video generation."""
    LANDSCAPE = "16:9"
    PORTRAIT = "9:16"


class Resolution(str, Enum):
    """Valid resolutions for Veo video generation."""
    HD = "720p"
    FULL_HD = "1080p"
    UHD = "4k"


class ModelVariant(str, Enum):
    """Veo model variants with different price/speed tradeoffs."""
    STANDARD = "standard"  # $0.40/sec - higher quality
    FAST = "fast"          # $0.15/sec - faster generation


class GenerationStatus(str, Enum):
    """Status of a video generation job."""
    PENDING = "pending"
    GENERATING = "generating"
    COMPLETED = "completed"
    FAILED = "failed"


# ============================================================================
# Configuration Models
# ============================================================================

class VeoConfig(BaseModel):
    """
    Configuration for Veo video generation.

    Contains all settings that can be adjusted for video generation.
    """
    aspect_ratio: AspectRatio = Field(
        default=AspectRatio.LANDSCAPE,
        description="Video aspect ratio: 16:9 (landscape) or 9:16 (portrait)"
    )
    resolution: Resolution = Field(
        default=Resolution.FULL_HD,
        description="Output resolution: 720p, 1080p, or 4k"
    )
    duration_seconds: Literal[4, 6, 8] = Field(
        default=8,
        description="Video duration in seconds: 4, 6, or 8"
    )
    negative_prompt: Optional[str] = Field(
        default="blurry, low quality, distorted, deformed, ugly, bad anatomy",
        description="Content to avoid in generation"
    )
    seed: Optional[int] = Field(
        default=None,
        description="Random seed for reproducibility"
    )
    model_variant: ModelVariant = Field(
        default=ModelVariant.STANDARD,
        description="Model variant: standard ($0.40/sec) or fast ($0.15/sec)"
    )

    @field_validator('duration_seconds')
    @classmethod
    def validate_duration_for_resolution(cls, v, info):
        """1080p and 4k require 8s duration."""
        # Note: Full validation happens in service
        return v

    model_config = {
        "json_schema_extra": {
            "example": {
                "aspect_ratio": "16:9",
                "resolution": "1080p",
                "duration_seconds": 8,
                "negative_prompt": "blurry, low quality",
                "seed": 12345,
                "model_variant": "standard"
            }
        }
    }


# ============================================================================
# Brand Avatar Models
# ============================================================================

class BrandAvatar(BaseModel):
    """
    Brand avatar model for character consistency in video generation.

    Avatars store reference images and generation settings for
    creating consistent character appearances across videos.
    """
    id: UUID = Field(..., description="Avatar UUID")
    brand_id: UUID = Field(..., description="Brand UUID this avatar belongs to")
    name: str = Field(..., description="Avatar name (e.g., 'Sarah - Brand Ambassador')")
    description: Optional[str] = Field(None, description="Avatar description and personality")

    # Reference images for character consistency (up to 3)
    reference_image_1: Optional[str] = Field(None, description="Primary reference image storage path")
    reference_image_2: Optional[str] = Field(None, description="Secondary reference image storage path")
    reference_image_3: Optional[str] = Field(None, description="Tertiary reference image storage path")

    # Generation prompt used to create the avatar
    generation_prompt: Optional[str] = Field(
        None,
        description="Prompt used to generate avatar via Gemini (Nano Banana)"
    )

    # Default video generation settings
    default_negative_prompt: str = Field(
        default="blurry, low quality, distorted, deformed, ugly, bad anatomy",
        description="Default negative prompt for video generation"
    )
    default_aspect_ratio: AspectRatio = Field(
        default=AspectRatio.LANDSCAPE,
        description="Default aspect ratio for videos"
    )
    default_resolution: Resolution = Field(
        default=Resolution.FULL_HD,
        description="Default resolution for videos"
    )
    default_duration_seconds: Literal[4, 6, 8] = Field(
        default=8,
        description="Default video duration"
    )

    # Metadata
    is_active: bool = Field(default=True, description="Whether avatar is active")
    created_at: datetime = Field(..., description="When avatar was created")
    updated_at: datetime = Field(..., description="When avatar was last updated")

    @property
    def reference_images(self) -> List[str]:
        """Return list of non-null reference image paths."""
        images = []
        if self.reference_image_1:
            images.append(self.reference_image_1)
        if self.reference_image_2:
            images.append(self.reference_image_2)
        if self.reference_image_3:
            images.append(self.reference_image_3)
        return images

    @property
    def reference_image_count(self) -> int:
        """Number of reference images."""
        return len(self.reference_images)

    model_config = {
        "json_schema_extra": {
            "example": {
                "id": "550e8400-e29b-41d4-a716-446655440000",
                "brand_id": "550e8400-e29b-41d4-a716-446655440001",
                "name": "Sarah - Brand Ambassador",
                "description": "Friendly, professional woman in her 30s",
                "reference_image_1": "avatars/brand-id/avatar-id/ref1.png",
                "generation_prompt": "Professional woman, 30s, friendly smile...",
                "is_active": True
            }
        }
    }


class BrandAvatarCreate(BaseModel):
    """Input model for creating a new brand avatar."""
    brand_id: UUID = Field(..., description="Brand UUID")
    name: str = Field(..., min_length=1, max_length=255, description="Avatar name")
    description: Optional[str] = Field(None, description="Avatar description")
    generation_prompt: Optional[str] = Field(None, description="Prompt for generating avatar images")

    # Default settings
    default_negative_prompt: str = Field(
        default="blurry, low quality, distorted, deformed, ugly, bad anatomy"
    )
    default_aspect_ratio: AspectRatio = Field(default=AspectRatio.LANDSCAPE)
    default_resolution: Resolution = Field(default=Resolution.FULL_HD)
    default_duration_seconds: Literal[4, 6, 8] = Field(default=8)


# ============================================================================
# Video Generation Models
# ============================================================================

class VeoGenerationRequest(BaseModel):
    """
    Request model for Veo video generation.

    Contains all information needed to generate a video.
    """
    brand_id: UUID = Field(..., description="Brand UUID for organization")

    # Optional references
    avatar_id: Optional[UUID] = Field(None, description="Avatar UUID for character consistency")
    product_id: Optional[UUID] = Field(None, description="Product UUID for product showcase")

    # Prompt components
    prompt: str = Field(..., min_length=10, description="Main video generation prompt")
    action_description: Optional[str] = Field(
        None,
        description="What the subject should do (e.g., 'walks toward camera while smiling')"
    )
    dialogue: Optional[str] = Field(
        None,
        description="What the subject should say (Veo 3.1 supports native dialogue)"
    )
    background_description: Optional[str] = Field(
        None,
        description="Background scene description (e.g., 'modern office with plants')"
    )

    # Configuration
    config: VeoConfig = Field(default_factory=VeoConfig, description="Video generation settings")

    # Additional reference images (besides avatar references)
    additional_reference_images: Optional[List[str]] = Field(
        None,
        max_length=3,
        description="Additional reference image paths (storage paths)"
    )

    model_config = {
        "json_schema_extra": {
            "example": {
                "brand_id": "550e8400-e29b-41d4-a716-446655440001",
                "avatar_id": "550e8400-e29b-41d4-a716-446655440000",
                "prompt": "A professional woman presenting a product",
                "action_description": "holds up product and smiles at camera",
                "dialogue": "This amazing product will change your life!",
                "background_description": "clean white studio with soft lighting",
                "config": {
                    "aspect_ratio": "16:9",
                    "resolution": "1080p",
                    "duration_seconds": 8
                }
            }
        }
    }


class VeoGenerationResult(BaseModel):
    """
    Result model for Veo video generation.

    Contains the generated video information and metadata.
    """
    generation_id: UUID = Field(..., description="Unique ID for this generation")
    status: GenerationStatus = Field(..., description="Generation status")

    # Output
    video_storage_path: Optional[str] = Field(None, description="Storage path for generated video")
    thumbnail_storage_path: Optional[str] = Field(None, description="Storage path for thumbnail")

    # Timing and cost
    generation_time_seconds: Optional[float] = Field(None, description="Time taken to generate")
    estimated_cost_usd: Optional[float] = Field(None, description="Estimated cost in USD")

    # Error info
    error_message: Optional[str] = Field(None, description="Error message if failed")

    # Metadata
    created_at: datetime = Field(..., description="When generation started")
    completed_at: Optional[datetime] = Field(None, description="When generation completed")

    @property
    def is_complete(self) -> bool:
        """Check if generation is complete (success or failure)."""
        return self.status in [GenerationStatus.COMPLETED, GenerationStatus.FAILED]

    @property
    def is_success(self) -> bool:
        """Check if generation was successful."""
        return self.status == GenerationStatus.COMPLETED

    model_config = {
        "json_schema_extra": {
            "example": {
                "generation_id": "550e8400-e29b-41d4-a716-446655440002",
                "status": "completed",
                "video_storage_path": "veo-videos/gen-id/video.mp4",
                "generation_time_seconds": 45.2,
                "estimated_cost_usd": 3.20,
                "created_at": "2025-01-15T10:00:00Z",
                "completed_at": "2025-01-15T10:00:45Z"
            }
        }
    }


class VeoGenerationSummary(BaseModel):
    """Summary of a video generation for list views."""
    id: UUID
    brand_id: UUID
    avatar_id: Optional[UUID]
    prompt: str
    status: GenerationStatus
    video_storage_path: Optional[str]
    estimated_cost_usd: Optional[float]
    created_at: datetime
