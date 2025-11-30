"""
Pydantic schemas for product image analysis.

These schemas define the structure for:
- Vision AI analysis results (stored in database)
- Image selection criteria (for matching to reference ads)
- Selection results (with match scores and reasoning)
"""

from pydantic import BaseModel, Field
from typing import List, Optional
from enum import Enum
from datetime import datetime


class LightingType(str, Enum):
    """Types of lighting detected in product images."""
    NATURAL_SOFT = "natural_soft"       # Window light, diffused
    NATURAL_BRIGHT = "natural_bright"   # Direct sunlight, harsh
    STUDIO = "studio"                   # Professional studio lighting
    DRAMATIC = "dramatic"               # High contrast, moody
    FLAT = "flat"                       # Even, shadowless
    WARM = "warm"                       # Golden/warm tones
    COOL = "cool"                       # Blue/cool tones
    UNKNOWN = "unknown"


class BackgroundType(str, Enum):
    """Types of backgrounds in product images."""
    TRANSPARENT = "transparent"         # PNG with alpha
    SOLID_WHITE = "solid_white"         # Clean white background
    SOLID_COLOR = "solid_color"         # Single color (not white)
    GRADIENT = "gradient"               # Color gradient
    LIFESTYLE = "lifestyle"             # In-context scene
    TEXTURED = "textured"               # Wood, marble, fabric, etc.
    OUTDOOR = "outdoor"                 # Nature/outdoor setting
    UNKNOWN = "unknown"


class ProductAngle(str, Enum):
    """Angle of product in the image."""
    FRONT = "front"                     # Straight-on front view
    THREE_QUARTER = "three_quarter"     # 45-degree angle
    SIDE = "side"                       # Profile view
    BACK = "back"                       # Rear view
    TOP_DOWN = "top_down"               # Bird's eye view
    ANGLED = "angled"                   # Dynamic angle
    HERO = "hero"                       # Slightly elevated, dramatic
    MULTIPLE = "multiple"               # Multiple angles in one image


class ImageUseCase(str, Enum):
    """Best use cases for the product image in ads."""
    HERO = "hero"                       # Main product showcase
    TESTIMONIAL = "testimonial"         # Quote-style ads
    LIFESTYLE = "lifestyle"             # In-context/scene ads
    DETAIL = "detail"                   # Feature/ingredient focus
    COMPARISON = "comparison"           # Before/after style
    PACKAGING = "packaging"             # Box/container focus
    SOCIAL_PROOF = "social_proof"       # Trust badge style
    MINIMAL = "minimal"                 # Clean, simple ads


class ProductImageAnalysis(BaseModel):
    """
    Complete analysis of a product image for ad generation matching.

    This schema is stored in the database as JSONB and used to
    intelligently select product images that match reference ad styles.
    """

    # Quality metrics
    quality_score: float = Field(
        ge=0.0, le=1.0,
        description="Overall image quality score (0-1)"
    )
    resolution_adequate: bool = Field(
        description="Whether resolution is sufficient for 1080x1080 ads"
    )
    sharpness_score: float = Field(
        default=1.0,
        ge=0.0, le=1.0,
        description="Image sharpness/clarity score"
    )

    # Visual characteristics
    lighting_type: LightingType = Field(
        description="Primary type of lighting in the image"
    )
    lighting_notes: Optional[str] = Field(
        default=None,
        description="Additional lighting observations"
    )

    background_type: BackgroundType = Field(
        description="Type of background"
    )
    background_color: Optional[str] = Field(
        default=None,
        description="Hex color code if solid/gradient background"
    )
    background_removable: bool = Field(
        default=True,
        description="Whether background can be easily removed/replaced"
    )

    product_angle: ProductAngle = Field(
        description="Primary angle of product in image"
    )

    # Composition analysis
    product_coverage: float = Field(
        ge=0.0, le=1.0,
        description="Percentage of frame occupied by product (0-1)"
    )
    product_centered: bool = Field(
        description="Whether product is centered in frame"
    )
    product_position: str = Field(
        default="center",
        description="Position in frame: center, left, right, top, bottom"
    )
    has_shadows: bool = Field(
        description="Whether image has visible shadows"
    )
    shadow_direction: Optional[str] = Field(
        default=None,
        description="Direction of shadows if present"
    )
    has_reflections: bool = Field(
        description="Whether image has reflections"
    )

    # Use case matching
    best_use_cases: List[ImageUseCase] = Field(
        description="Ranked list of best ad formats for this image"
    )

    # Color information
    dominant_colors: List[str] = Field(
        description="Top 3-5 dominant colors as hex codes"
    )
    color_mood: Optional[str] = Field(
        default=None,
        description="Overall color mood: warm, cool, neutral, vibrant, muted"
    )

    # Product visibility
    product_fully_visible: bool = Field(
        default=True,
        description="Whether entire product is visible (not cropped)"
    )
    label_readable: bool = Field(
        default=True,
        description="Whether product label/text is readable"
    )

    # Issues/warnings
    detected_issues: List[str] = Field(
        default_factory=list,
        description="Any quality issues detected"
    )

    # Recommendations
    recommended_crops: List[str] = Field(
        default_factory=list,
        description="Suggested crop ratios: 1:1, 4:5, 9:16"
    )

    # Metadata
    analysis_model: str = Field(
        description="Model used for analysis (e.g., claude-opus-4-5)"
    )
    analysis_version: str = Field(
        default="v1",
        description="Version of analysis prompt/logic"
    )

    class Config:
        use_enum_values = True


class ImageSelectionCriteria(BaseModel):
    """
    Criteria for selecting product images to match a reference ad.

    Derived from reference ad analysis to find the best product
    image for the ad style.
    """

    # Preferred characteristics (None = no preference)
    preferred_lighting: Optional[LightingType] = Field(
        default=None,
        description="Lighting type that matches reference ad"
    )
    preferred_background: Optional[BackgroundType] = Field(
        default=None,
        description="Background type that matches reference ad"
    )
    preferred_angle: Optional[ProductAngle] = Field(
        default=None,
        description="Product angle that matches reference ad"
    )
    preferred_use_cases: List[ImageUseCase] = Field(
        default_factory=list,
        description="Use cases that match reference ad format"
    )

    # Minimum requirements
    min_quality_score: float = Field(
        default=0.7,
        ge=0.0, le=1.0,
        description="Minimum acceptable quality score"
    )
    require_centered: bool = Field(
        default=False,
        description="Whether product must be centered"
    )
    require_full_visibility: bool = Field(
        default=True,
        description="Whether product must be fully visible"
    )
    require_readable_label: bool = Field(
        default=False,
        description="Whether label must be readable"
    )

    # Color matching
    target_colors: List[str] = Field(
        default_factory=list,
        description="Target color palette to match"
    )


class ImageSelectionResult(BaseModel):
    """
    Result of image selection with match reasoning.

    Returned by select_product_images tool to explain
    why an image was selected.
    """

    # Selected image
    storage_path: str = Field(
        description="Storage path of selected image"
    )
    image_id: Optional[str] = Field(
        default=None,
        description="Database ID of the image"
    )

    # Match scoring
    match_score: float = Field(
        ge=0.0, le=1.0,
        description="How well image matches criteria (0-1)"
    )
    match_breakdown: dict = Field(
        default_factory=dict,
        description="Score breakdown by factor"
    )
    match_reasons: List[str] = Field(
        description="Human-readable reasons for selection"
    )

    # The analysis used for matching
    analysis: ProductImageAnalysis = Field(
        description="Full analysis of the selected image"
    )

    # Warnings
    warnings: List[str] = Field(
        default_factory=list,
        description="Any concerns about using this image"
    )
