# CHECKPOINT: Size Variants Feature

**Date**: December 2, 2025
**Status**: Implementation Complete - Pending SQL Migration
**Feature**: Create size variants of approved ads for different Meta ad placements

---

## Overview

Added ability to create different aspect ratio versions of approved ads. Users can select an approved ad, choose target Meta sizes (1:1, 4:5, 9:16, 16:9), and generate new versions that match the original ad's content but fit the new canvas dimensions.

---

## Database Migration (User Must Run)

```sql
-- Add parent reference to track variants
ALTER TABLE generated_ads ADD COLUMN parent_ad_id UUID REFERENCES generated_ads(id);
ALTER TABLE generated_ads ADD COLUMN variant_size TEXT;

-- Add index for efficient lookups
CREATE INDEX idx_generated_ads_parent_ad_id ON generated_ads(parent_ad_id);
```

---

## Meta Ad Sizes Supported

| Name | Ratio | Dimensions | Use Case |
|------|-------|------------|----------|
| Square | 1:1 | 1080x1080 | Feed posts |
| Portrait | 4:5 | 1080x1350 | Feed (optimal) |
| Story | 9:16 | 1080x1920 | Stories, Reels |
| Landscape | 16:9 | 1920x1080 | Video, links |

---

## Files Modified

### 1. `viraltracker/services/ad_creation_service.py`

Added three new methods:

```python
async def get_ad_for_variant(self, ad_id: UUID) -> Optional[Dict]:
    """Get ad data needed for creating size variants."""

async def save_size_variant(
    self,
    parent_ad_id: UUID,
    ad_run_id: UUID,
    variant_size: str,
    storage_path: str,
    prompt_text: str,
    prompt_spec: Dict,
    hook_text: str,
    hook_id: Optional[UUID] = None,
    model_used: Optional[str] = None,
    generation_time_ms: Optional[int] = None
) -> UUID:
    """Save a size variant of an existing ad."""

async def get_existing_variants(self, parent_ad_id: UUID) -> List[str]:
    """Get list of variant sizes that already exist for an ad."""
```

### 2. `viraltracker/ui/pages/02_📊_Ad_History.py`

- Added `META_AD_SIZES` constant
- Added session state for size variant creation
- Added helper functions:
  - `get_existing_variants()` - check which sizes already exist
  - `get_ad_image_base64()` - download source image
  - `create_size_variants_async()` - async variant generation
- Added "📐 Create Sizes" button for each approved ad
- Added size selection modal with checkboxes
- Added generation progress and results display
- Updated ads query to include `parent_ad_id` and `variant_size`
- Added variant badge display ("4:5 Variant" instead of "Variation X")

### 3. `viraltracker/ui/pages/03_🖼️_Ad_Gallery.py`

- Added `META_AD_SIZES` constant
- Added session state for size variant creation
- Added helper functions (similar to Ad History)
- Added "📐 Create Size Variants" button at top of gallery
- Added expandable panel with:
  - Dropdown to select from approved ads (last 100)
  - Preview of selected ad
  - Size checkboxes with "exists" indicators
  - Generate and Cancel buttons
- Updated gallery query to include variant info
- Added variant badge display in gallery HTML (📐 1:1 badge)

---

## User Flow

### Ad History:
1. Expand an ad run
2. Find an approved ad
3. Click "📐 Create Sizes" button on that ad
4. Select target sizes (disabled if already exists)
5. Click "🚀 Generate Variants"
6. Wait for generation (uses Gemini with low temperature)
7. See results and refresh to view new variants

### Ad Gallery:
1. Click "📐 Create Size Variants" button at top
2. Panel expands with dropdown of approved ads
3. Select an ad (see preview)
4. Select target sizes
5. Click "🚀 Generate Variants"
6. Gallery refreshes with new variants

---

## Technical Implementation

### Generation Approach
- Uses approved ad as reference image
- Sends to Gemini 2.0 Flash with temperature=0.1 for consistency
- Explicit prompt: "Recreate this EXACT ad at {dimensions}"
- Preserves hook text and all visual elements
- Only repositions/resizes elements for new canvas

### Prompt Template
```
Recreate this EXACT ad at {dimensions} ({ratio} aspect ratio).

CRITICAL INSTRUCTIONS:
- Keep ALL text exactly the same (same words, same fonts)
- Keep ALL colors exactly the same
- Keep the product image(s) exactly the same
- Keep the overall visual style and layout matching the original
- Only reposition/resize elements as needed to fit the new {ratio} canvas
- The hook text is: "{hook_text}"

This is a SIZE VARIANT - the content should be IDENTICAL, only the canvas dimensions change.
```

### Storage
- Variants stored in same bucket as originals: `generated-ads/{ad_run_id}/variant_{size}_{uuid}.png`
- Linked via `parent_ad_id` in database
- Same ad_run_id as parent

---

## Data Model

**Size variant ad record:**
```json
{
  "id": "uuid",
  "ad_run_id": "same as parent",
  "parent_ad_id": "uuid of source ad",
  "variant_size": "4:5",
  "prompt_index": 0,
  "prompt_text": "Recreate this EXACT ad...",
  "prompt_spec": {"canvas": {"dimensions": "1080x1350", "aspect_ratio": "4:5"}},
  "hook_text": "same as parent",
  "hook_id": "same as parent",
  "storage_path": "generated-ads/{ad_run_id}/variant_4x5_{uuid}.png",
  "model_used": "gemini-2.0-flash-exp",
  "generation_time_ms": 12000,
  "final_status": "pending"
}
```

---

## Edge Cases Handled

- Source ad image not in storage: Shows error message
- Size already exists: Checkbox disabled with "✓ exists" label
- Generation fails: Shows error with specific failure reason
- Nested variants: Allowed (variant of a variant)

---

## Next Steps (User Action Required)

1. Run the SQL migration above
2. Test by:
   - Opening Ad History
   - Expanding a run with approved ads
   - Clicking "📐 Create Sizes" on an approved ad
   - Selecting sizes and generating

---

## Plan Reference

See: `~/.claude/plans/size-variants-feature.md`
