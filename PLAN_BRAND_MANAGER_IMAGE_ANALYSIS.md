# Plan: Brand Manager & Product Image Analysis

**Date:** 2025-11-29
**Status:** Planning
**Estimated Scope:** Medium-Large

## Overview

Two interconnected features:
1. **Product Image Analysis** - One-time vision analysis of product images, stored for reuse
2. **Brand Manager UI** - Central page to manage brands, products, images, and hooks

## Goals

- Eliminate repeated vision API calls for product image selection
- Provide smart auto-selection of product images matching reference ad style
- Create central management UI for all brand/product data
- Follow pydantic-ai best practices with proper schemas

---

## Part 1: Product Image Analysis

### 1.1 Pydantic Schemas

```python
# viraltracker/agent/schemas/image_analysis.py

from pydantic import BaseModel, Field
from typing import List, Optional
from enum import Enum
from datetime import datetime


class LightingType(str, Enum):
    NATURAL_SOFT = "natural_soft"
    NATURAL_BRIGHT = "natural_bright"
    STUDIO = "studio"
    DRAMATIC = "dramatic"
    FLAT = "flat"
    UNKNOWN = "unknown"


class BackgroundType(str, Enum):
    TRANSPARENT = "transparent"
    SOLID_WHITE = "solid_white"
    SOLID_COLOR = "solid_color"
    GRADIENT = "gradient"
    LIFESTYLE = "lifestyle"
    TEXTURED = "textured"
    UNKNOWN = "unknown"


class ProductAngle(str, Enum):
    FRONT = "front"
    THREE_QUARTER = "three_quarter"
    SIDE = "side"
    BACK = "back"
    TOP_DOWN = "top_down"
    ANGLED = "angled"
    MULTIPLE = "multiple"


class ImageUseCase(str, Enum):
    HERO = "hero"              # Main product shot
    TESTIMONIAL = "testimonial" # Good for quote-style ads
    LIFESTYLE = "lifestyle"     # In-context/scene shots
    DETAIL = "detail"          # Close-up/ingredient focus
    COMPARISON = "comparison"   # Before/after style
    PACKAGING = "packaging"     # Box/container focus


class ProductImageAnalysis(BaseModel):
    """Analysis of a product image for ad generation matching."""

    # Quality metrics
    quality_score: float = Field(
        ge=0.0, le=1.0,
        description="Overall image quality score"
    )
    resolution_adequate: bool = Field(
        description="Whether resolution is sufficient for ads"
    )

    # Visual characteristics
    lighting_type: LightingType = Field(
        description="Type of lighting in the image"
    )
    background_type: BackgroundType = Field(
        description="Type of background"
    )
    background_color: Optional[str] = Field(
        default=None,
        description="Hex color if solid background"
    )
    product_angle: ProductAngle = Field(
        description="Angle of product in image"
    )

    # Composition
    product_coverage: float = Field(
        ge=0.0, le=1.0,
        description="How much of frame product occupies (0-1)"
    )
    product_centered: bool = Field(
        description="Whether product is centered in frame"
    )
    has_shadows: bool = Field(
        description="Whether image has natural shadows"
    )
    has_reflections: bool = Field(
        description="Whether image has reflections"
    )

    # Use case matching
    best_use_cases: List[ImageUseCase] = Field(
        description="Best ad formats for this image"
    )

    # Color information
    dominant_colors: List[str] = Field(
        description="Dominant colors in image as hex codes"
    )

    # Issues/warnings
    detected_issues: List[str] = Field(
        default_factory=list,
        description="Any quality issues detected"
    )

    # Metadata
    analysis_model: str = Field(
        description="Model used for analysis"
    )
    analysis_prompt_version: str = Field(
        default="v1",
        description="Version of analysis prompt"
    )

    class Config:
        use_enum_values = True


class ImageSelectionCriteria(BaseModel):
    """Criteria for selecting product images."""

    preferred_lighting: Optional[LightingType] = None
    preferred_background: Optional[BackgroundType] = None
    preferred_angle: Optional[ProductAngle] = None
    preferred_use_case: Optional[ImageUseCase] = None
    min_quality_score: float = Field(default=0.7, ge=0.0, le=1.0)
    require_centered: bool = False


class ImageSelectionResult(BaseModel):
    """Result of image selection with reasoning."""

    selected_path: str
    match_score: float = Field(ge=0.0, le=1.0)
    match_reasons: List[str]
    analysis: ProductImageAnalysis
```

### 1.2 SQL Migration

```sql
-- sql/add_image_analysis.sql

-- Add image analysis column to product_images table
ALTER TABLE product_images
ADD COLUMN IF NOT EXISTS image_analysis JSONB DEFAULT NULL;

ALTER TABLE product_images
ADD COLUMN IF NOT EXISTS analyzed_at TIMESTAMP WITH TIME ZONE DEFAULT NULL;

ALTER TABLE product_images
ADD COLUMN IF NOT EXISTS analysis_model VARCHAR(100) DEFAULT NULL;

-- Index for querying by analysis status
CREATE INDEX IF NOT EXISTS idx_product_images_analyzed
ON product_images(analyzed_at)
WHERE analyzed_at IS NOT NULL;

-- Comment
COMMENT ON COLUMN product_images.image_analysis IS 'Vision AI analysis of image for ad matching (ProductImageAnalysis schema)';
```

### 1.3 New Pydantic-AI Tool

```python
# In ad_creation_agent.py

@ad_creation_agent.tool(
    metadata={
        'category': 'Analysis',
        'platform': 'Facebook',
        'rate_limit': '10/minute',
        'use_cases': [
            'Analyze product image for ad generation matching',
            'Extract visual characteristics for smart selection',
            'One-time analysis stored for future use'
        ]
    }
)
async def analyze_product_image(
    ctx: RunContext[AgentDependencies],
    image_storage_path: str,
    force_reanalyze: bool = False
) -> ProductImageAnalysis:
    """
    Analyze a product image using Vision AI and store results.

    This tool performs one-time analysis of product images to enable
    smart auto-selection for ad generation. Results are cached in the
    database and reused for future ad runs.

    Args:
        ctx: Run context with AgentDependencies
        image_storage_path: Storage path to product image
        force_reanalyze: If True, re-analyze even if cached

    Returns:
        ProductImageAnalysis with all visual characteristics
    """
    # Implementation details in code
```

### 1.4 Updated Selection Tool

```python
@ad_creation_agent.tool(...)
async def select_product_images(
    ctx: RunContext[AgentDependencies],
    product_id: str,
    ad_analysis: Dict,
    selection_mode: str = "auto",  # "auto" | "manual"
    manual_selection: Optional[List[str]] = None,
    count: int = 1
) -> List[ImageSelectionResult]:
    """
    Select best product images for ad generation.

    In auto mode, uses stored image analysis to match against
    reference ad characteristics. In manual mode, returns
    user-selected images with their analysis.

    Args:
        ctx: Run context with AgentDependencies
        product_id: Product UUID
        ad_analysis: Reference ad analysis for matching
        selection_mode: "auto" for smart selection, "manual" for user choice
        manual_selection: List of paths if manual mode
        count: Number of images to select

    Returns:
        List of ImageSelectionResult with match scores and reasoning
    """
```

---

## Part 2: Brand Manager UI

### 2.1 Page Structure

```
viraltracker/ui/pages/7_🏢_Brand_Manager.py
```

### 2.2 UI Layout

```
┌─────────────────────────────────────────────────────────────────┐
│  🏢 Brand Manager                                               │
├─────────────────────────────────────────────────────────────────┤
│                                                                 │
│  Brand: [Wonder Paws ▼]                      [+ Add Brand]      │
│                                                                 │
│  ══════════════════════════════════════════════════════════════ │
│                                                                 │
│  BRAND SETTINGS                                    [Edit]       │
│  ┌────────────────────────────────────────────────────────────┐ │
│  │  Colors     ■ Purple (#4747C9)                             │ │
│  │             ■ Marigold (#FDBE2D)                           │ │
│  │             ■ Dove Grey (#F5F5F5)                          │ │
│  │                                                            │ │
│  │  Fonts      Primary: Larsseit (Bold, Medium, Regular)      │ │
│  │             Secondary: Uomo Bold                           │ │
│  │                                                            │ │
│  │  Guidelines "Friendly, modern. Use tonal gradients..."     │ │
│  └────────────────────────────────────────────────────────────┘ │
│                                                                 │
│  ══════════════════════════════════════════════════════════════ │
│                                                                 │
│  PRODUCTS (3)                                  [+ Add Product]  │
│                                                                 │
│  ┌────────────────────────────────────────────────────────────┐ │
│  │ ▼ Collagen Chews 3X                         [Create Ads]   │ │
│  │   ──────────────────────────────────────────────────────── │ │
│  │                                                            │ │
│  │   DETAILS                                       [Edit]     │ │
│  │   Target: Dog owners 35-65, concerned about joint health   │ │
│  │   Benefits: Joint support, Mobility, Coat health           │ │
│  │   USPs: Vet-formulated, 3X strength, Made in USA           │ │
│  │   Offer: "Buy 2, Get 1 Free"                               │ │
│  │   Founders: Sarah & Mike Johnson                           │ │
│  │                                                            │ │
│  │   IMAGES (4)                    [Upload] [Analyze All]     │ │
│  │   ┌─────────┐ ┌─────────┐ ┌─────────┐ ┌─────────┐         │ │
│  │   │  [img]  │ │  [img]  │ │  [img]  │ │  [img]  │         │ │
│  │   │ ⭐ 0.95 │ │ ⭐ 0.88 │ │ ⭐ 0.82 │ │   ❓    │         │ │
│  │   │  Hero   │ │  Side   │ │ Lifestl │ │Unanalyzd│         │ │
│  │   │ [View]  │ │ [View]  │ │ [View]  │ │[Analyze]│         │ │
│  │   └─────────┘ └─────────┘ └─────────┘ └─────────┘         │ │
│  │                                                            │ │
│  │   HOOKS (47)                              [Manage Hooks]   │ │
│  │   Categories: skepticism_overcome (12), transformation (8) │ │
│  │   Avg Impact: 18.3                                         │ │
│  │                                                            │ │
│  │   AD HISTORY                              [View All]       │ │
│  │   12 runs • 89 ads generated • 76% approval rate           │ │
│  │                                                            │ │
│  └────────────────────────────────────────────────────────────┘ │
│                                                                 │
│  │ ▶ Yakety Pack                                              │ │
│  │ ▶ Joint Supplement Pro                                     │ │
│                                                                 │
└─────────────────────────────────────────────────────────────────┘
```

### 2.3 Image Analysis Detail Modal

When clicking [View] on an analyzed image:

```
┌─────────────────────────────────────────────────────────────────┐
│  Image Analysis: main_product.png                    [X Close]  │
├─────────────────────────────────────────────────────────────────┤
│                                                                 │
│  ┌──────────────┐    ANALYSIS RESULTS                          │
│  │              │                                               │
│  │   [IMAGE]    │    Quality Score:  ⭐⭐⭐⭐⭐ 0.95            │
│  │              │    Resolution:     ✅ Adequate                │
│  │              │                                               │
│  │              │    Lighting:       Natural Soft               │
│  │              │    Background:     Transparent                │
│  │   300x300    │    Product Angle:  Front                      │
│  │              │    Coverage:       72% of frame               │
│  │              │    Centered:       ✅ Yes                     │
│  └──────────────┘                                               │
│                                                                 │
│  BEST FOR                                                       │
│  [Hero Ads] [Testimonial] [Product Showcase]                    │
│                                                                 │
│  DOMINANT COLORS                                                │
│  ■ #8B4513  ■ #F5F5F5  ■ #2D4A3E                               │
│                                                                 │
│  ISSUES                                                         │
│  None detected ✅                                               │
│                                                                 │
│  Analyzed: Nov 29, 2025 using Claude Opus 4.5                   │
│                                                                 │
│                              [Re-Analyze] [Use in Ad Creator]   │
└─────────────────────────────────────────────────────────────────┘
```

---

## Part 3: Ad Creator Integration

### 3.1 New Section in Ad Creator

```
6. Product Image

○ 🤖 Auto-Select - Best match for this template
○ 🖼️ Choose Image - Select specific image

[If Choose Image is selected, show grid of product images with analysis]
```

### 3.2 Auto-Selection Logic

```python
def calculate_image_match_score(
    image_analysis: ProductImageAnalysis,
    ad_analysis: Dict
) -> float:
    """
    Calculate how well a product image matches reference ad style.

    Factors:
    - Lighting compatibility (40%)
    - Background compatibility (30%)
    - Use case match (20%)
    - Quality score (10%)
    """
    score = 0.0

    # Lighting match
    ref_lighting = ad_analysis.get('lighting_style', 'natural')
    if image_analysis.lighting_type.value in ref_lighting:
        score += 0.4
    elif image_analysis.lighting_type == LightingType.STUDIO:
        score += 0.3  # Studio is versatile

    # Background match
    ref_has_lifestyle = 'lifestyle' in ad_analysis.get('format_type', '')
    if ref_has_lifestyle and image_analysis.background_type == BackgroundType.LIFESTYLE:
        score += 0.3
    elif not ref_has_lifestyle and image_analysis.background_type in [
        BackgroundType.TRANSPARENT, BackgroundType.SOLID_WHITE
    ]:
        score += 0.3

    # Use case match
    ref_format = ad_analysis.get('format_type', 'product_showcase')
    format_to_use_case = {
        'testimonial': ImageUseCase.TESTIMONIAL,
        'product_showcase': ImageUseCase.HERO,
        'before_after': ImageUseCase.COMPARISON
    }
    if format_to_use_case.get(ref_format) in image_analysis.best_use_cases:
        score += 0.2

    # Quality bonus
    score += image_analysis.quality_score * 0.1

    return min(score, 1.0)
```

---

## Implementation Order

### Phase 1: Schema & Database
1. Create `viraltracker/agent/schemas/image_analysis.py`
2. Create SQL migration `sql/add_image_analysis.sql`
3. Run migration

### Phase 2: Analysis Tool
4. Add `analyze_product_image` tool to agent
5. Create analysis prompt for Vision AI
6. Test on sample images

### Phase 3: Selection Update
7. Update `select_product_images` with new logic
8. Add match scoring function
9. Test auto-selection

### Phase 4: Brand Manager UI
10. Create `7_🏢_Brand_Manager.py`
11. Implement brand/product display
12. Add image gallery with analysis status
13. Add "Analyze" buttons

### Phase 5: Ad Creator Integration
14. Add image selection mode to Ad Creator
15. Show image grid when manual mode selected
16. Wire up auto-selection to workflow

---

## Files to Create/Modify

| File | Action |
|------|--------|
| `viraltracker/agent/schemas/image_analysis.py` | CREATE |
| `sql/add_image_analysis.sql` | CREATE |
| `viraltracker/agent/agents/ad_creation_agent.py` | MODIFY - add tools |
| `viraltracker/ui/pages/7_🏢_Brand_Manager.py` | CREATE |
| `viraltracker/ui/pages/5_🎨_Ad_Creator.py` | MODIFY - add image selection |

---

## Success Criteria

- [ ] Product images can be analyzed once and results stored
- [ ] Auto-selection picks appropriate image for reference ad style
- [ ] Brand Manager shows all brand/product data in one place
- [ ] Image analysis visible with quality scores and characteristics
- [ ] Users can trigger analysis from Brand Manager
- [ ] Ad Creator offers auto vs manual image selection
