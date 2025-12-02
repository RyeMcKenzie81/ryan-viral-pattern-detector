# Secondary Product Image Support - Implementation Plan

**Version**: 1.0.0
**Date**: 2025-12-02
**Status**: Planning
**Estimated Effort**: Medium (6-8 changes across 3 layers)

---

## Table of Contents
1. [Overview](#overview)
2. [Current State](#current-state)
3. [Target State](#target-state)
4. [Implementation Steps](#implementation-steps)
5. [Technical Details](#technical-details)
6. [Testing Strategy](#testing-strategy)

---

## Overview

### Problem Statement
Currently, the ad creation workflow only supports **one product image** per ad generation. For products like Yakety Pack, the hero image shows just the box, but ads often need to show what's inside (the cards). The AI struggles to create compelling visuals when it only sees packaging.

### Solution
Add support for selecting **up to 2 product images** that are both passed to Nano Banana as reference images:
- **Auto-select mode**: AI picks the best 1-2 images based on analysis
- **Manual select mode**: User can select 1 or 2 images in Ad Creator Step 2

### Key Design Decisions
1. **No database changes needed** - Uses existing `product_images` table
2. **Conditional prompting** - Only describe secondary image when present
3. **Backwards compatible** - Single image still works as before

---

## Current State

### Data Flow (Single Image)
```
Ad Creator UI                    Agent Layer                      Gemini Service
┌─────────────┐                 ┌────────────────────┐           ┌──────────────┐
│ Manual:     │  ──────────────▶│ complete_ad_       │           │              │
│ selected_   │  image_path     │ workflow()         │           │ generate_    │
│ image_path  │  (str)          │                    │           │ image()      │
│             │                 │  ▼                 │           │              │
│ OR          │                 │ select_product_    │           │ reference_   │
│             │                 │ images(count=1)    │──────────▶│ images: [    │
│ Auto:       │                 │                    │           │   template,  │
│ AI picks 1  │                 │  ▼                 │           │   product1   │
└─────────────┘                 │ generate_nano_     │           │ ]            │
                                │ banana_prompt()    │           │              │
                                │ product_image_path │           │ (2 images)   │
                                │ (single str)       │           └──────────────┘
                                │                    │
                                │  ▼                 │
                                │ execute_nano_      │
                                │ banana()           │
                                │ downloads 1 image  │
                                └────────────────────┘
```

### Current Parameters
| Function | Parameter | Type | Current |
|----------|-----------|------|---------|
| `complete_ad_workflow` | `selected_image_path` | `Optional[str]` | Single path |
| `select_product_images` | `count` | `int` | Always 1 |
| `generate_nano_banana_prompt` | `product_image_path` | `str` | Single path |
| `execute_nano_banana` | downloads | internal | 1 product image |

---

## Target State

### Data Flow (1-2 Images)
```
Ad Creator UI                    Agent Layer                      Gemini Service
┌─────────────┐                 ┌────────────────────┐           ┌──────────────┐
│ Manual:     │  ──────────────▶│ complete_ad_       │           │              │
│ selected_   │  image_paths    │ workflow()         │           │ generate_    │
│ image_paths │  (List[str])    │                    │           │ image()      │
│ [img1,img2] │  max 2          │  ▼                 │           │              │
│             │                 │ select_product_    │           │ reference_   │
│ OR          │                 │ images(count=2)    │──────────▶│ images: [    │
│             │                 │                    │           │   template,  │
│ Auto:       │                 │  ▼                 │           │   product1,  │
│ AI picks 2  │                 │ generate_nano_     │           │   product2   │
└─────────────┘                 │ banana_prompt()    │           │ ]            │
                                │ product_image_paths│           │              │
                                │ (List[str])        │           │ (up to 3)    │
                                │                    │           └──────────────┘
                                │  ▼                 │
                                │ execute_nano_      │
                                │ banana()           │
                                │ downloads 1-2 imgs │
                                └────────────────────┘
```

### Updated Parameters
| Function | Parameter | Type | New |
|----------|-----------|------|-----|
| `complete_ad_workflow` | `selected_image_paths` | `Optional[List[str]]` | List (max 2) |
| `select_product_images` | `count` | `int` | 1 or 2 |
| `generate_nano_banana_prompt` | `product_image_paths` | `List[str]` | List (1-2) |
| `execute_nano_banana` | downloads | internal | 1-2 product images |

---

## Implementation Steps

### Step 1: Update Ad Creator UI (Manual Selection)
**File**: `viraltracker/ui/pages/01_🎨_Ad_Creator.py`

Changes:
1. Rename session state: `selected_image_path` → `selected_image_paths` (list)
2. Update manual selection UI to allow selecting up to 2 images
3. Show clear visual feedback for selected images (1st, 2nd)
4. Validate: must select at least 1 when in manual mode

```python
# Session state
if 'selected_image_paths' not in st.session_state:
    st.session_state.selected_image_paths = []

# UI: Allow selecting up to 2 images
# Use multiselect or toggle checkboxes with max 2 validation
```

### Step 2: Update `run_workflow` Function (UI)
**File**: `viraltracker/ui/pages/01_🎨_Ad_Creator.py`

Changes:
1. Change parameter: `selected_image_path` → `selected_image_paths`
2. Pass list to `complete_ad_workflow`

```python
async def run_workflow(
    ...
    image_selection_mode: str = "auto",
    selected_image_paths: List[str] = None,  # Changed from str to List[str]
    ...
):
```

### Step 3: Update `complete_ad_workflow` Tool
**File**: `viraltracker/agent/agents/ad_creation_agent.py`

Changes:
1. Change parameter: `selected_image_path` → `selected_image_paths`
2. Update Stage 7 to:
   - Auto mode: Use `count=2` instead of `count=1`
   - Manual mode: Pass list of paths instead of single path
3. Update Stage 8-10 to pass list to `generate_nano_banana_prompt`

```python
async def complete_ad_workflow(
    ...
    image_selection_mode: str = "auto",
    selected_image_paths: Optional[List[str]] = None,  # Changed
) -> Dict:
```

### Step 4: Update `select_product_images` Tool
**File**: `viraltracker/agent/agents/ad_creation_agent.py`

Changes:
1. Update auto-select logic to intelligently pick 1 or 2 images
2. Consider image diversity (e.g., one hero, one contents/lifestyle)
3. Already supports `count` parameter - just call with `count=2`

Selection Logic for Auto Mode:
- If only 1 image exists: return 1
- If 2+ images exist:
  - Score all by match quality
  - Consider image type diversity (packaging vs contents)
  - Return top 2 diverse images if scores are close

### Step 5: Update `generate_nano_banana_prompt` Tool
**File**: `viraltracker/agent/agents/ad_creation_agent.py`

Changes:
1. Change parameter: `product_image_path` → `product_image_paths`
2. Update spec construction for multiple images
3. Add conditional prompt section for secondary image

```python
async def generate_nano_banana_prompt(
    ...
    product_image_paths: List[str],  # Changed from str
    ...
) -> Dict:
    # Conditional prompting
    if len(product_image_paths) == 1:
        # Current single-image behavior
        product_prompt = "Use uploaded product image EXACTLY..."
    else:
        # Two-image behavior with labeling
        product_prompt = """
        **PRIMARY PRODUCT IMAGE (Image 1):**
        Use this as the main product representation - this shows the packaging/hero view.
        Reproduce EXACTLY - no modifications to product appearance.

        **SECONDARY PRODUCT IMAGE (Image 2):**
        This shows the product contents, interior, or alternate view.
        Use this to show what's inside or to add context when appropriate.
        The AI should decide the best way to incorporate this based on the ad layout.
        """
```

### Step 6: Update `execute_nano_banana` Tool
**File**: `viraltracker/agent/agents/ad_creation_agent.py`

Changes:
1. Download all product images (1-2)
2. Add all as reference images to Gemini call

```python
async def execute_nano_banana(
    ctx: RunContext[AgentDependencies],
    nano_banana_prompt: Dict
) -> Dict:
    # Download reference images
    template_data = await ctx.deps.ad_creation.download_image(
        nano_banana_prompt['template_reference_path']
    )

    # Download all product images
    product_images = []
    for path in nano_banana_prompt['product_image_paths']:
        product_data = await ctx.deps.ad_creation.download_image(path)
        product_images.append(product_data)

    # Call Gemini with all reference images
    reference_images = [template_data] + product_images  # 2-3 images total

    generation_result = await ctx.deps.gemini.generate_image(
        prompt=nano_banana_prompt['full_prompt'],
        reference_images=reference_images,
        return_metadata=True
    )
```

---

## Technical Details

### Prompt Engineering for Secondary Image

When 2 images are provided, add this to the prompt:

```
**REFERENCE IMAGES PROVIDED:**

1. **Reference Ad Template**: The style/layout to follow
2. **Primary Product Image**: Main product packaging/hero shot - reproduce EXACTLY
3. **Secondary Product Image**: Product contents/interior/alternate view - use for context

**SECONDARY IMAGE GUIDANCE:**
- The secondary image shows what's inside or an alternate view of the product
- Consider showing a subtle glimpse of the contents if it enhances the ad
- The secondary image provides context - use your judgment on incorporation
- If the ad layout doesn't suit two product views, prioritize the primary image
```

### Gemini API Capacity
- Gemini `generate_image()` supports up to **14 reference images**
- Current usage: 2 (template + 1 product)
- New usage: 3 (template + 2 products)
- Plenty of headroom

### Backwards Compatibility
All changes maintain backwards compatibility:
- Single image still works (list with 1 element)
- `selected_image_paths` defaults to `None` for auto mode
- Prompt conditionally adapts based on image count

---

## Testing Strategy

### Step 7: Create Test Script for Prompt Verification
**File**: `test_secondary_image.py` (new file in project root)

This test script will:
1. Verify prompt construction with 1 and 2 images
2. Log the exact prompt sent to Nano Banana
3. Verify reference images are correctly passed
4. Run a real generation to confirm end-to-end flow

```python
"""
Test script to verify secondary product image feature.

Run with: python test_secondary_image.py

Tests:
1. Prompt construction (1 image vs 2 images)
2. Reference images passed to Gemini
3. Full workflow with Yakety Pack (box + cards)
"""

import asyncio
import logging
from pydantic_ai import RunContext
from pydantic_ai.usage import RunUsage
from viraltracker.agent.dependencies import AgentDependencies
from viraltracker.agent.agents.ad_creation_agent import (
    generate_nano_banana_prompt,
    execute_nano_banana,
    select_product_images,
)

# Enable detailed logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

async def test_prompt_construction():
    """Test that prompts are correctly constructed for 1 and 2 images."""
    deps = AgentDependencies.create(project_name="default")
    ctx = RunContext(deps=deps, model=None, usage=RunUsage())

    # Mock data
    selected_hook = {
        "hook_id": "test-hook-id",
        "text": "Test hook text",
        "adapted_text": "Adapted hook for ad",
        "category": "skepticism_overcome"
    }
    product = {
        "name": "Test Product",
        "benefits": ["Benefit 1", "Benefit 2"],
        "brand_id": "test-brand"
    }
    ad_analysis = {
        "format_type": "testimonial",
        "canvas_size": "1080x1080px",
        "color_palette": ["#FFFFFF", "#000000"]
    }

    # Test 1: Single image
    print("\n=== TEST 1: Single Image ===")
    prompt_1 = await generate_nano_banana_prompt(
        ctx=ctx,
        prompt_index=1,
        selected_hook=selected_hook,
        product=product,
        ad_analysis=ad_analysis,
        ad_brief_instructions="Test instructions",
        reference_ad_path="reference-ads/test.png",
        product_image_paths=["products/test/main.png"]  # Single image
    )

    print(f"Product image paths: {prompt_1['product_image_paths']}")
    print(f"Full prompt contains 'SECONDARY': {'SECONDARY' in prompt_1['full_prompt']}")
    assert len(prompt_1['product_image_paths']) == 1
    assert "SECONDARY" not in prompt_1['full_prompt'], "Single image should NOT have SECONDARY in prompt"
    print("✅ Single image prompt correct - no secondary image instructions")

    # Test 2: Two images
    print("\n=== TEST 2: Two Images ===")
    prompt_2 = await generate_nano_banana_prompt(
        ctx=ctx,
        prompt_index=1,
        selected_hook=selected_hook,
        product=product,
        ad_analysis=ad_analysis,
        ad_brief_instructions="Test instructions",
        reference_ad_path="reference-ads/test.png",
        product_image_paths=["products/test/main.png", "products/test/contents.png"]  # Two images
    )

    print(f"Product image paths: {prompt_2['product_image_paths']}")
    print(f"Full prompt contains 'SECONDARY': {'SECONDARY' in prompt_2['full_prompt']}")
    assert len(prompt_2['product_image_paths']) == 2
    assert "SECONDARY" in prompt_2['full_prompt'], "Two images SHOULD have SECONDARY in prompt"
    print("✅ Two image prompt correct - includes secondary image instructions")

    # Print prompt excerpt for verification
    print("\n=== PROMPT EXCERPT (Two Images) ===")
    # Find and print the product image section
    prompt_text = prompt_2['full_prompt']
    if "PRIMARY PRODUCT IMAGE" in prompt_text:
        start = prompt_text.find("PRIMARY PRODUCT IMAGE")
        end = prompt_text.find("**", start + 50)
        print(prompt_text[start:end+100])

    return True

async def test_full_workflow_with_logging():
    """
    Run actual workflow with detailed logging to verify prompts.
    Uses a real product (Yakety Pack) with 2 images.
    """
    # This will be filled in after implementation
    pass

if __name__ == "__main__":
    print("=" * 60)
    print("SECONDARY PRODUCT IMAGE - TEST SUITE")
    print("=" * 60)

    asyncio.run(test_prompt_construction())
    print("\n✅ All prompt construction tests passed!")
```

### Step 8: Add Logging to Verify Prompt in Generation
**File**: `viraltracker/agent/agents/ad_creation_agent.py`

Add logging in `execute_nano_banana` to verify:
- Number of reference images being passed
- Prompt excerpt for debugging

```python
# In execute_nano_banana, add after downloading images:
logger.info(f"Reference images for Nano Banana: {1 + len(product_images)} total")
logger.info(f"  - 1 template image")
logger.info(f"  - {len(product_images)} product image(s)")

# Log prompt excerpt
prompt_excerpt = nano_banana_prompt['full_prompt'][:500]
if "SECONDARY" in nano_banana_prompt['full_prompt']:
    logger.info("Prompt includes SECONDARY image instructions ✓")
else:
    logger.info("Prompt uses single image mode (no SECONDARY)")
```

### Unit Tests
1. `generate_nano_banana_prompt` with 1 image - no "SECONDARY" in prompt
2. `generate_nano_banana_prompt` with 2 images - "SECONDARY" present in prompt
3. `select_product_images` with `count=2` returns 2 images
4. `execute_nano_banana` downloads correct number of images

### Integration Tests
1. **Regression**: Full workflow with 1 image (ensure backwards compatible)
2. **New Feature**: Full workflow with 2 images (manual selection)
3. **Auto Mode**: Full workflow with auto-select (should pick up to 2 diverse images)

### Verification Checklist
After implementation, run these checks:

```bash
# 1. Run unit test for prompt construction
python test_secondary_image.py

# 2. Run workflow with verbose logging
# Check logs for:
#   - "Reference images for Nano Banana: 3 total" (when 2 product images)
#   - "Prompt includes SECONDARY image instructions ✓"

# 3. Verify in generated_ads table
# Check that prompt_text column includes secondary image instructions

# 4. Visual verification
# Check generated ad shows evidence of both images
```

### Manual Testing Procedure
1. **Ad Creator UI** - Select product with 2+ images
2. **Step 2** - Choose "Manual" and select 2 images
3. **Generate** - Run workflow with 1 variation
4. **Verify Logs** - Check terminal output for:
   - `"Reference images for Nano Banana: 3 total"`
   - `"Prompt includes SECONDARY image instructions ✓"`
5. **Verify Database** - Query `generated_ads.prompt_text` for "SECONDARY"
6. **Visual Check** - Review generated ad for evidence of both images

### Test Cases by Product
| Product | Hero Image | Secondary Image | Expected Result |
|---------|------------|-----------------|-----------------|
| Yakety Pack | Box | Cards inside | Ad shows box AND glimpse of cards |
| Wonder Paws | Bottle | Dog using product | Ad shows bottle in lifestyle context |
| (1 image product) | Main | N/A | Works as before, no SECONDARY in prompt |

---

## Files to Modify

| File | Changes |
|------|---------|
| `viraltracker/ui/pages/01_🎨_Ad_Creator.py` | Session state, UI multiselect, `run_workflow` params |
| `viraltracker/agent/agents/ad_creation_agent.py` | 3 tools: `complete_ad_workflow`, `generate_nano_banana_prompt`, `execute_nano_banana` |
| `viraltracker/agent/agents/ad_creation_agent.py` | Update `select_product_images` to pick 2 diverse images |

**Total: 2 files, ~6 function signatures**

---

## Rollout Plan

### Phase 1: Backend Implementation
1. Update `generate_nano_banana_prompt` - add `product_image_paths` list support
2. Update `execute_nano_banana` - download multiple images
3. Update `complete_ad_workflow` - pass list through workflow
4. Add logging for verification

### Phase 2: Testing - Prompt Verification
1. Create `test_secondary_image.py` test script
2. Run prompt construction tests (1 image vs 2 images)
3. Verify "SECONDARY" keyword appears only when 2 images
4. Check logs show correct reference image count

### Phase 3: Testing - Full Workflow
1. Run workflow with 1 image (regression test)
2. Run workflow with 2 images (manual selection)
3. Verify `generated_ads.prompt_text` contains correct instructions
4. Visual check: generated ad uses both images

### Phase 4: UI Implementation
1. Update session state for multi-select
2. Add UI for selecting up to 2 images
3. Update `run_workflow` to pass list

### Phase 5: End-to-End Testing
1. Test Yakety Pack (box + cards)
2. Test Wonder Paws (bottle + lifestyle)
3. Test product with only 1 image (backwards compatibility)

### Phase 6: Production Deployment
1. Deploy to Railway
2. Monitor logs for any issues
3. Create checkpoint document

---

## Open Questions

None - all decisions made per user input:
- ✅ Auto-select can pick 1-2 images
- ✅ Manual select allows up to 2
- ✅ Conditional prompting when secondary present
- ✅ No database changes needed

---

**Created**: 2025-12-02
**Author**: Claude Code
