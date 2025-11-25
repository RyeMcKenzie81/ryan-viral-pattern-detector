# Facebook Ad Creation Agent - Complete Implementation Plan
## Aligned with ViralTracker Pydantic AI Architecture

**Version**: 1.0.0
**Date**: 2025-01-24
**Status**: Planning Phase
**Target Completion**: Incremental (tool-by-tool testing)

---

## Table of Contents

1. [Executive Summary](#executive-summary)
2. [System Architecture Integration](#system-architecture-integration)
3. [Workflow Overview](#workflow-overview)
4. [Database Schema](#database-schema)
5. [Pydantic Models](#pydantic-models)
6. [Service Layer](#service-layer)
7. [Agent & Tools](#agent--tools)
8. [Implementation Phases](#implementation-phases)
9. [Testing Strategy](#testing-strategy)
10. [Hook Categories Reference](#hook-categories-reference)

---

## Executive Summary

This document provides a complete specification for building a **Facebook Ad Creation Agent** within the ViralTracker system using **Pydantic AI**. The agent analyzes reference ads, selects diverse hooks from a database, generates 5 ad variations using Gemini's Nano Banana Pro 3 image generation, and quality-reviews them using dual AI reviewers (Claude + Gemini).

### Key Improvements Over Original Plan

1. **Full Pydantic AI Integration**: Uses `@agent.tool()` decorator pattern following ViralTracker standards
2. **Proper Separation of Concerns**: Dedicated `AdCreationService` handles all database/storage operations
3. **Supabase Storage Integration**: Aligned with existing bucket structure
4. **Tool-Based Incremental Testing**: Test each tool independently before full workflow
5. **Comprehensive Error Handling**: Rate limiting, retries, validation at each step
6. **Multi-Brand Architecture**: Database schema extends existing brands/products structure

### System Requirements

- **Python**: 3.11+
- **Pydantic AI**: Latest version
- **Google Gemini API**: For Nano Banana Pro 3 image generation + Claude for vision analysis
- **Supabase**: PostgreSQL database + Storage for images
- **Rate Limits**:
  - Gemini Vision: 9 req/min (configurable)
  - Nano Banana: 5 req/min (expensive image generation)

---

## System Architecture Integration

### Agent Placement in Multi-Agent System

```
ViralTracker (Pydantic AI Multi-Agent System)
│
├── Orchestrator Agent (routes to specialists)
│   └── Routing Tools: route_to_{platform}_agent()
│
├── Platform Agents (specialists)
│   ├── Twitter Agent (8 tools)
│   ├── TikTok Agent (5 tools)
│   ├── YouTube Agent (1 tool)
│   ├── Facebook Agent (2 tools)
│   └── Analysis Agent (3 tools)
│
└── NEW: Ad Creation Agent (14 tools) ← CREATE THIS
    └── Specializes in Facebook ad creative generation
```

**Design Decision**: Create a **dedicated Ad Creation Agent** rather than expanding Facebook Agent because:
- Complex multi-step workflow (14 tools)
- Distinct responsibility (creative generation vs. data collection)
- Will eventually support multiple ad platforms (Facebook, Instagram, Google Display)
- Follows single-responsibility principle per Pydantic AI best practices

### Dependency Injection Updates

**File**: `viraltracker/agent/dependencies.py`

```python
# Add to AgentDependencies class
class AgentDependencies(BaseModel):
    # Existing services
    twitter: TwitterService
    gemini: GeminiService
    stats: StatsService
    scraping: ScrapingService
    comment: CommentService
    tiktok: TikTokService
    youtube: YouTubeService
    facebook: FacebookService

    # NEW: Add Ad Creation Service
    ad_creation: AdCreationService  # ← Add this

    project_name: str = "yakety-pack-instagram"
    result_cache: ResultCache = Field(default_factory=ResultCache)

# Update create() factory method
@classmethod
def create(cls, project_name: str = "yakety-pack-instagram", ...) -> "AgentDependencies":
    # ... existing service initialization

    # Initialize AdCreationService
    ad_creation = AdCreationService()
    logger.info("AdCreationService initialized")

    return cls(
        # ... existing services
        ad_creation=ad_creation,  # ← Add this
        project_name=project_name
    )
```

---

## Workflow Overview

### High-Level Workflow

```
User Request: "Create 5 Facebook ads for Wonder Paws using this reference ad"
        ↓
Step 1: Upload reference ad → Supabase Storage (reference-ads/)
        ↓
Step 2: Vision AI (Claude/Gemini) analyzes structure, style, layout
        ↓
Step 3: Select 5 diverse hooks from database
        - Mix persuasive categories (skepticism, timeline, authority, etc.)
        - Prioritize high impact scores (10+)
        - Adapt hook text to match ad style/tone
        ↓
Step 4: Select best product images from storage
        ↓
Step 5: Generate 5 Nano Banana prompts
        - Each includes: template reference + product image + hook + JSON spec
        ↓
Step 6: Execute Nano Banana SEQUENTIALLY (temp=0.20)
        For each of 5 prompts:
          ├─ Generate image via Gemini API
          ├─ Save immediately to Supabase (resilience)
          └─ Continue to next
        ↓
Step 7: Dual AI Review (Claude + Gemini)
        For each generated ad:
          ├─ Product accuracy ≥ 0.8?
          ├─ Text accuracy ≥ 0.8?
          └─ Either reviewer approves → approved
        ↓
Step 8: Return AdCreationResult
        - All 5 ads with review status
        - Approved count, rejected count, flagged count
        - Summary message
```

### Key Design Decisions

| Decision | Rationale |
|----------|-----------|
| **Sequential Generation** | Resilience. If generation fails mid-way, we don't lose all progress |
| **Save Immediately** | Each image saved to Supabase right after generation (not batched) |
| **Dual Review with OR Logic** | Either Claude OR Gemini approving = approved. Reduces false rejections |
| **Minimum Score Threshold** | 0.8 for product/text accuracy. Auto-approve if both scores ≥ 0.8 |
| **Temperature 0.20** | Low temperature for consistency across image generation |

---

## Database Schema

### Schema Design Philosophy

- Extend existing multi-brand architecture (don't break compatibility)
- Store metadata in PostgreSQL (Supabase)
- Store binary assets (images) in Supabase Storage buckets
- Enable multi-product, multi-brand workflows
- Use JSONB for flexible schema evolution

### SQL Migration

**File**: `sql/migration_ad_creation.sql`

```sql
-- ============================================
-- BRANDS & PRODUCTS (extend existing tables)
-- ============================================

-- Add ad-specific columns to brands
ALTER TABLE brands
ADD COLUMN IF NOT EXISTS default_ad_brief_id UUID REFERENCES ad_brief_templates(id);

-- Add ad-specific columns to products
ALTER TABLE products
ADD COLUMN IF NOT EXISTS benefits TEXT[],
ADD COLUMN IF NOT EXISTS key_ingredients TEXT[],
ADD COLUMN IF NOT EXISTS target_audience TEXT,
ADD COLUMN IF NOT EXISTS product_url TEXT,
ADD COLUMN IF NOT EXISTS main_image_storage_path TEXT,
ADD COLUMN IF NOT EXISTS reference_image_storage_paths TEXT[];

-- ============================================
-- AD BRIEF TEMPLATES
-- ============================================

CREATE TABLE IF NOT EXISTS ad_brief_templates (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    brand_id UUID REFERENCES brands(id) ON DELETE CASCADE,  -- NULL = global template
    name TEXT NOT NULL,
    instructions TEXT NOT NULL,
    active BOOLEAN DEFAULT true,
    created_at TIMESTAMPTZ DEFAULT NOW(),
    updated_at TIMESTAMPTZ DEFAULT NOW()
);

CREATE INDEX idx_ad_brief_brand ON ad_brief_templates(brand_id);
CREATE INDEX idx_ad_brief_active ON ad_brief_templates(active);

COMMENT ON TABLE ad_brief_templates IS 'Templates for ad creation instructions (brand-specific or global)';
COMMENT ON COLUMN ad_brief_templates.brand_id IS 'NULL = global template';

-- ============================================
-- HOOKS (product-specific persuasive hooks)
-- ============================================

CREATE TABLE IF NOT EXISTS hooks (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    product_id UUID REFERENCES products(id) ON DELETE CASCADE NOT NULL,
    text TEXT NOT NULL,
    category TEXT NOT NULL,  -- Universal persuasive principles
    framework TEXT,  -- Original framework name
    impact_score INT CHECK (impact_score >= 0 AND impact_score <= 21),
    emotional_score TEXT CHECK (emotional_score IN ('Very High', 'High', 'Medium', 'Low')),
    active BOOLEAN DEFAULT true,
    created_at TIMESTAMPTZ DEFAULT NOW(),
    updated_at TIMESTAMPTZ DEFAULT NOW()
);

CREATE INDEX idx_hooks_product ON hooks(product_id);
CREATE INDEX idx_hooks_active ON hooks(active);
CREATE INDEX idx_hooks_impact ON hooks(impact_score DESC);
CREATE INDEX idx_hooks_category ON hooks(category);

COMMENT ON TABLE hooks IS 'Persuasive hooks derived from reviews, scored by impact and emotional resonance';
COMMENT ON COLUMN hooks.category IS 'Universal persuasive principle: skepticism_overcome, timeline, authority_validation, value_contrast, bonus_discovery, specificity, transformation, failed_alternatives';
COMMENT ON COLUMN hooks.impact_score IS 'Score 0-21 based on persuasive framework scoring system';

-- ============================================
-- AD GENERATION RUNS
-- ============================================

CREATE TABLE IF NOT EXISTS ad_runs (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    project_id UUID REFERENCES projects(id),
    product_id UUID REFERENCES products(id) ON DELETE CASCADE NOT NULL,
    reference_ad_storage_path TEXT NOT NULL,
    status TEXT DEFAULT 'pending' CHECK (status IN (
        'pending', 'analyzing', 'generating', 'reviewing', 'complete', 'failed'
    )),

    -- Stage outputs (stored as JSONB for flexibility)
    ad_analysis JSONB,
    selected_hooks JSONB,
    selected_product_images TEXT[],

    -- Metadata
    created_at TIMESTAMPTZ DEFAULT NOW(),
    completed_at TIMESTAMPTZ,
    error_message TEXT
);

CREATE INDEX idx_ad_runs_product ON ad_runs(product_id);
CREATE INDEX idx_ad_runs_status ON ad_runs(status);
CREATE INDEX idx_ad_runs_created ON ad_runs(created_at DESC);

COMMENT ON TABLE ad_runs IS 'Tracks ad generation workflow runs from reference ad to final output';
COMMENT ON COLUMN ad_runs.ad_analysis IS 'JSON: AdAnalysis model (format_type, layout, colors, etc.)';
COMMENT ON COLUMN ad_runs.selected_hooks IS 'JSON array: SelectedHook models with adaptations';

-- ============================================
-- GENERATED ADS
-- ============================================

CREATE TABLE IF NOT EXISTS generated_ads (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    ad_run_id UUID REFERENCES ad_runs(id) ON DELETE CASCADE NOT NULL,
    prompt_index INT NOT NULL CHECK (prompt_index >= 1 AND prompt_index <= 5),

    -- Prompt details
    prompt_text TEXT NOT NULL,
    prompt_spec JSONB NOT NULL,
    hook_id UUID REFERENCES hooks(id),
    hook_text TEXT,

    -- Generated image
    storage_path TEXT NOT NULL,

    -- AI Reviews
    claude_review JSONB,
    gemini_review JSONB,
    reviewers_agree BOOLEAN,
    final_status TEXT DEFAULT 'pending' CHECK (final_status IN (
        'pending', 'approved', 'rejected', 'flagged'
    )),

    created_at TIMESTAMPTZ DEFAULT NOW()
);

CREATE INDEX idx_generated_ads_run ON generated_ads(ad_run_id);
CREATE INDEX idx_generated_ads_status ON generated_ads(final_status);
CREATE INDEX idx_generated_ads_hook ON generated_ads(hook_id);
CREATE UNIQUE INDEX idx_generated_ads_run_index ON generated_ads(ad_run_id, prompt_index);

COMMENT ON TABLE generated_ads IS 'Individual generated ad images with prompts and AI review results';
COMMENT ON COLUMN generated_ads.prompt_spec IS 'JSON spec passed to Nano Banana (canvas, colors, text elements)';
COMMENT ON COLUMN generated_ads.claude_review IS 'JSON: ReviewResult from Claude (product_accuracy, text_accuracy, etc.)';
COMMENT ON COLUMN generated_ads.gemini_review IS 'JSON: ReviewResult from Gemini';
COMMENT ON COLUMN generated_ads.final_status IS 'approved = either reviewer approved, rejected = both rejected, flagged = disagreement';

-- ============================================
-- SEED DATA: Global Ad Brief Template
-- ============================================

INSERT INTO ad_brief_templates (brand_id, name, instructions, active)
VALUES (
    NULL,  -- Global template
    'Default Ad Brief Template',
    '## How to Generate Social Media Ad Briefs

When creating social media ads based on user-provided examples, follow this approach:

### Core Concept
Analyze the uploaded ad example FIRST to understand its format, then create 5 variations using proven hooks from our database while maintaining the same visual structure.

### Process

1. **ANALYZE THE UPLOADED AD EXAMPLE**
   - Identify the format (testimonial, quote style, before/after, etc.)
   - Note the layout structure (single image, two-panel, carousel, etc.)
   - Extract visual elements (text placement, image sections, colors)
   - Identify authenticity markers (timestamps, usernames, emojis, etc.)
   - Determine what stays constant vs. what changes between variations

2. **Identify Production Efficiencies**
   - Look for elements that can be created once and reused
   - Example: If it has a product shot, make that fixed across all variations
   - Determine what MUST change for each variation (usually the main visual/photo)

3. **Select 5 Hooks**
   - Use diverse persuasive principles (mix categories for variety)
   - Prioritize "High" and "Very High" emotional scores
   - Mix frameworks (Cost Comparison, Skepticism Overcome, etc.)

4. **Transform Hooks to Match Ad Style**
   - Adapt hooks to match the tone/format of the example
   - If testimonial style: Add timeframes, names, emojis
   - If quote style: Keep it punchy and direct
   - If before/after: Focus on transformation
   - Match the language style of the original

5. **Define Visual Structure**
   - Use same dimensions as example (usually 1080x1080px)
   - Maintain same layout structure
   - Identify fixed elements (use across all 5)
   - Identify variable elements (change for each)

### Remember
- Start by analyzing what they upload - don''t assume format
- Find ways to reuse elements across all 5 variations
- Use actual customer language from reviews
- Match the authenticity level of the example',
    true
) ON CONFLICT DO NOTHING;
```

### Supabase Storage Buckets

```
Bucket Structure (public buckets for easy access):

├── products/                          (existing)
│   └── {product_id}/
│       ├── main.png                   (main product image)
│       └── reference_*.png            (additional product angles)
│
├── reference-ads/                     (NEW)
│   └── {ad_run_id}_reference.png     (uploaded reference ad)
│
└── generated-ads/                     (NEW)
    └── {ad_run_id}/
        ├── 1.png                      (hook variation 1)
        ├── 2.png                      (hook variation 2)
        ├── 3.png                      (hook variation 3)
        ├── 4.png                      (hook variation 4)
        └── 5.png                      (hook variation 5)
```

**Bucket Configuration** (run in Supabase Dashboard → Storage):
```sql
-- Create buckets
INSERT INTO storage.buckets (id, name, public)
VALUES
    ('reference-ads', 'reference-ads', true),
    ('generated-ads', 'generated-ads', true);

-- Set policies for public read access
CREATE POLICY "Public read access for reference-ads"
ON storage.objects FOR SELECT
USING (bucket_id = 'reference-ads');

CREATE POLICY "Public read access for generated-ads"
ON storage.objects FOR SELECT
USING (bucket_id = 'generated-ads');

-- Allow authenticated users to upload
CREATE POLICY "Authenticated upload to reference-ads"
ON storage.objects FOR INSERT
TO authenticated
WITH CHECK (bucket_id = 'reference-ads');

CREATE POLICY "Authenticated upload to generated-ads"
ON storage.objects FOR INSERT
TO authenticated
WITH CHECK (bucket_id = 'generated-ads');
```

---

## Pydantic Models

**File**: `viraltracker/services/models.py` (add these models)

```python
from typing import Optional, List, Dict, Any
from pydantic import BaseModel, Field
from datetime import datetime
from uuid import UUID

# ============================================
# DATABASE MODELS
# ============================================

class Product(BaseModel):
    """Product information with images and metadata"""
    id: UUID
    brand_id: UUID
    name: str
    benefits: List[str] = Field(default_factory=list, description="Product benefits for ad copy")
    key_ingredients: Optional[List[str]] = Field(None, description="Key ingredients to highlight")
    target_audience: Optional[str] = Field(None, description="Target demographic")
    product_url: Optional[str] = Field(None, description="Product landing page URL")
    main_image_storage_path: Optional[str] = Field(None, description="Storage path to main product image")
    reference_image_storage_paths: List[str] = Field(default_factory=list, description="Additional product images")

class Hook(BaseModel):
    """Persuasive hook for ad copywriting"""
    id: UUID
    product_id: UUID
    text: str = Field(..., description="Hook text derived from reviews or created manually")
    category: str = Field(..., description="Universal persuasive principle category")
    framework: Optional[str] = Field(None, description="Original framework name")
    impact_score: int = Field(ge=0, le=21, description="Impact score 0-21 based on persuasive framework")
    emotional_score: str = Field(..., description="Emotional intensity: Very High, High, Medium, Low")
    active: bool = True

class AdBriefTemplate(BaseModel):
    """Template for ad creation instructions"""
    id: UUID
    brand_id: Optional[UUID] = Field(None, description="NULL = global template")
    name: str
    instructions: str = Field(..., description="Markdown instructions for ad creation workflow")
    active: bool = True

# ============================================
# ANALYSIS MODELS
# ============================================

class AdAnalysis(BaseModel):
    """Result of analyzing a reference ad using Vision AI"""
    format_type: str = Field(..., description="Ad format: testimonial, quote_style, before_after, product_showcase")
    layout_structure: str = Field(..., description="Layout: single_image, two_panel, carousel")
    fixed_elements: List[str] = Field(default_factory=list, description="Elements to reuse across all 5 ads")
    variable_elements: List[str] = Field(default_factory=list, description="Elements that change per variation")
    text_placement: Dict[str, Any] = Field(default_factory=dict, description="Text positioning details")
    color_palette: List[str] = Field(default_factory=list, description="Hex color codes")
    authenticity_markers: List[str] = Field(default_factory=list, description="Timestamps, usernames, emojis")
    canvas_size: str = Field(..., description="Image dimensions e.g. 1080x1080px")
    detailed_description: str = Field(..., description="Comprehensive description for prompt engineering")

class SelectedHook(BaseModel):
    """Hook selected for ad generation with style adaptations"""
    hook_id: UUID
    text: str = Field(..., description="Original hook text")
    category: str = Field(..., description="Persuasive category")
    framework: Optional[str] = None
    impact_score: int
    reasoning: str = Field(..., description="Why this hook was selected (diversity, impact, etc.)")
    adapted_text: str = Field(..., description="Hook text adapted to match reference ad style/tone")

# ============================================
# GENERATION MODELS
# ============================================

class NanoBananaPrompt(BaseModel):
    """Prompt for Gemini Nano Banana image generation"""
    prompt_index: int = Field(ge=1, le=5, description="Index 1-5 for this variation")
    hook: SelectedHook
    instruction_text: str = Field(..., description="Human-readable instructions for image generation")
    spec: Dict[str, Any] = Field(..., description="JSON spec with canvas, product, text_elements")
    full_prompt: str = Field(..., description="Complete prompt sent to Nano Banana API")
    template_reference_path: str = Field(..., description="Storage path to reference ad image")
    product_image_path: str = Field(..., description="Storage path to product image")

class GeneratedAd(BaseModel):
    """Generated ad image with metadata"""
    prompt_index: int = Field(ge=1, le=5)
    image_base64: Optional[str] = Field(None, description="Temporary base64 before saving to storage")
    storage_path: Optional[str] = Field(None, description="Set after saving to Supabase Storage")

# ============================================
# REVIEW MODELS
# ============================================

class ReviewResult(BaseModel):
    """AI review of generated ad quality"""
    reviewer: str = Field(..., description="Reviewer name: 'claude' or 'gemini'")
    product_accuracy: float = Field(ge=0.0, le=1.0, description="Product image fidelity score")
    text_accuracy: float = Field(ge=0.0, le=1.0, description="Text readability and correctness score")
    layout_accuracy: float = Field(ge=0.0, le=1.0, description="Layout adherence to template score")
    overall_quality: float = Field(ge=0.0, le=1.0, description="Overall production-ready quality score")
    product_issues: List[str] = Field(default_factory=list, description="Product image issues found")
    text_issues: List[str] = Field(default_factory=list, description="Text issues (gibberish, spelling, etc.)")
    ai_artifacts: List[str] = Field(default_factory=list, description="AI generation artifacts detected")
    status: str = Field(..., description="Review status: approved, needs_revision, rejected")
    notes: str = Field(..., description="Additional review notes")

class GeneratedAdWithReviews(BaseModel):
    """Generated ad with dual AI reviews and final decision"""
    prompt_index: int
    prompt: NanoBananaPrompt
    storage_path: str
    claude_review: Optional[ReviewResult] = None
    gemini_review: Optional[ReviewResult] = None
    reviewers_agree: bool = Field(..., description="True if both reviewers gave same status")
    final_status: str = Field(..., description="approved, rejected, or flagged (disagreement)")

# ============================================
# FINAL OUTPUT
# ============================================

class AdCreationResult(BaseModel):
    """Complete result of ad creation workflow"""
    ad_run_id: UUID
    product: Product
    reference_ad_path: str
    ad_analysis: AdAnalysis
    selected_hooks: List[SelectedHook]
    generated_ads: List[GeneratedAdWithReviews]
    approved_count: int = Field(..., description="Number of ads approved by AI reviewers")
    rejected_count: int = Field(..., description="Number of ads rejected by both reviewers")
    flagged_count: int = Field(..., description="Number of ads with reviewer disagreement")
    summary: str = Field(..., description="Human-readable summary of workflow results")
    created_at: datetime = Field(default_factory=datetime.now)
```

---

**Continue in next section...**
