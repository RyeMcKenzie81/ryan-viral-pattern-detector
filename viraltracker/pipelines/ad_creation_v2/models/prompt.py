"""
Pydantic models for V2 ad generation prompts.

Replaces the raw dict literal in V1 generation_service.py with validated,
typed models. Each field maps 1:1 to the V1 dict keys.

Use model_dump(exclude_none=True) for serialization to JSON prompt.
"""

from typing import Dict, List, Optional, Any
from pydantic import BaseModel, Field


# ============================================================================
# Sub-models
# ============================================================================

class TaskConfig(BaseModel):
    """Top-level task configuration."""
    action: str = "create_facebook_ad"
    variation_index: int = Field(..., ge=1, le=15)
    total_variations: int = Field(..., ge=1, le=15)
    product_name: str
    canvas_size: str = "1080x1080px"
    color_mode: str = "original"
    prompt_version: str = "v2.1.0"


class SpecialInstructions(BaseModel):
    """Override instructions with highest priority."""
    priority: str = "HIGHEST"
    text: str
    note: str = "These instructions override all other guidelines when there is a conflict"


class ProductContext(BaseModel):
    """Product information for prompt context."""
    id: Optional[str] = None
    name: str
    display_name: str
    target_audience: str = "general audience"
    benefits: List[str] = Field(default_factory=list)
    unique_selling_points: List[str] = Field(default_factory=list)
    current_offer: Optional[str] = None
    brand_voice_notes: Optional[str] = None
    prohibited_claims: List[str] = Field(default_factory=list)
    required_disclaimers: Optional[str] = None
    founders: Optional[str] = None
    product_dimensions: Optional[str] = None
    variant: Optional[str] = None
    offer_variant: Optional[str] = None
    offer_pain_points: Optional[List[str]] = None


class HeadlineConfig(BaseModel):
    """Headline content configuration."""
    text: Optional[str] = None
    source: str = "hook"
    hook_id: Optional[str] = None
    persuasion_type: Optional[str] = None


class SubheadlineConfig(BaseModel):
    """Subheadline content configuration."""
    text: Optional[str] = None
    source: str = "matched_benefit"


class ContentConfig(BaseModel):
    """Content section of prompt."""
    headline: HeadlineConfig
    subheadline: SubheadlineConfig


class ColorConfig(BaseModel):
    """Color scheme configuration."""
    mode: str = "original"
    palette: Optional[List[str]] = None
    primary: Optional[Dict[str, str]] = None
    secondary: Optional[Dict[str, str]] = None
    background: Optional[Dict[str, str]] = None
    instruction: str = "Use the exact colors from the reference template"


class FontEntry(BaseModel):
    """Single font configuration."""
    family: str = "System default"
    weights: List[str] = Field(default_factory=list)
    style_notes: Optional[str] = None


class FontConfig(BaseModel):
    """Font configuration for heading and body."""
    heading: FontEntry
    body: FontEntry


class StyleConfig(BaseModel):
    """Style section of prompt."""
    format_type: Optional[str] = None
    layout_structure: Optional[str] = None
    canvas_size: str = "1080x1080px"
    text_placement: Dict[str, Any] = Field(default_factory=dict)
    colors: ColorConfig
    fonts: Optional[FontConfig] = None
    authenticity_markers: List[str] = Field(default_factory=list)


class TemplateImageConfig(BaseModel):
    """Template reference image."""
    path: str
    role: str = "style_reference"


class ProductImageEntry(BaseModel):
    """Single product image configuration."""
    path: str
    role: str = "primary"
    description: str = "Main product packaging"


class ImageConfig(BaseModel):
    """Images section of prompt."""
    template: TemplateImageConfig
    product: List[ProductImageEntry] = Field(default_factory=list)


class TemplateAnalysis(BaseModel):
    """Template analysis metadata."""
    format_type: Optional[str] = None
    layout_structure: Optional[str] = None
    has_founder_signature: bool = False
    has_founder_mention: bool = False
    detailed_description: str = ""


class AssetContext(BaseModel):
    """Asset context for template scoring integration (stub for Phase 1).

    Will be expanded in Phase 3+ to include detected asset types,
    required asset slots, and scoring breakdown.
    """
    template_requires_logo: bool = False
    brand_has_logo: bool = False
    template_requires_badge: bool = False
    brand_has_badge: bool = False
    asset_match_score: Optional[float] = None


class TextPreservation(BaseModel):
    """Text preservation rules for product images."""
    critical: bool = True
    requirement: str = "ALL text on packaging MUST be pixel-perfect legible"
    method: str = "composite_not_regenerate"
    rejection_condition: str = "blurry or illegible text"


class MultiImageHandling(BaseModel):
    """Multi-image handling rules."""
    primary_dominant: bool = True
    secondary_optional: bool = False
    secondary_usage: str = "contents, inset view, or background element"


class ProductImageRules(BaseModel):
    """Rules for product image handling."""
    preserve_exactly: bool = True
    no_modifications: bool = True
    text_preservation: TextPreservation = Field(default_factory=TextPreservation)
    multi_image_handling: Optional[MultiImageHandling] = None


class OfferRules(BaseModel):
    """Rules for offer handling."""
    use_only_provided: bool = True
    provided_offer: Optional[str] = None
    do_not_copy_from_template: bool = True
    max_count: int = 1
    prohibited_template_offers: List[str] = Field(
        default_factory=lambda: ["Free gift", "Buy 1 Get 1", "Bundle and save", "Autoship", "BOGO"]
    )


class LightingRules(BaseModel):
    """Lighting rules."""
    match_scene: bool = True
    shadow_direction: str = "match_scene_elements"
    color_temperature: str = "match_scene"
    ambient_occlusion: bool = True
    requirement: str = "Product must look naturally IN the scene, not pasted on"


class ScaleRules(BaseModel):
    """Scale rules."""
    realistic_sizing: bool = True
    relative_to: List[str] = Field(
        default_factory=lambda: ["hands", "countertops", "furniture", "pets"]
    )
    product_dimensions: Optional[str] = None
    requirement: str = "Product must appear proportionally correct"


class FoundersConfig(BaseModel):
    """Founders configuration."""
    template_has_signature: bool = False
    template_has_mention: bool = False
    product_founders: Optional[str] = None
    action: str = "omit"
    signature_style: Optional[str] = None
    signature_placement: Optional[str] = None


class GenerationRules(BaseModel):
    """Rules section of prompt."""
    product_image: ProductImageRules = Field(default_factory=ProductImageRules)
    offers: OfferRules = Field(default_factory=OfferRules)
    lighting: LightingRules = Field(default_factory=LightingRules)
    scale: ScaleRules = Field(default_factory=ScaleRules)
    founders: FoundersConfig = Field(default_factory=FoundersConfig)
    prohibited_claims: List[str] = Field(default_factory=list)
    required_disclaimers: Optional[str] = None


class AdBriefConfig(BaseModel):
    """Ad brief instructions."""
    instructions: str = ""


class PerformanceContext(BaseModel):
    """Performance context for scoring integration (stub for Phase 6+).

    Will include historical performance data, winning hooks,
    and optimization signals.
    """
    historical_approval_rate: Optional[float] = None
    winning_hooks: Optional[List[str]] = None
    optimization_notes: Optional[str] = None


# ============================================================================
# Top-level Prompt Model
# ============================================================================

class AdGenerationPrompt(BaseModel):
    """
    Complete Pydantic prompt model for V2 ad generation.

    Maps 1:1 to the V1 dict literal in generation_service.py:27-279.
    Use model_dump(exclude_none=True) for JSON serialization.
    """
    task: TaskConfig
    special_instructions: Optional[SpecialInstructions] = None
    product: ProductContext
    content: ContentConfig
    style: StyleConfig
    images: ImageConfig
    template_analysis: TemplateAnalysis
    asset_context: Optional[AssetContext] = None
    rules: GenerationRules
    ad_brief: AdBriefConfig = Field(default_factory=AdBriefConfig)
    performance_context: Optional[PerformanceContext] = None
