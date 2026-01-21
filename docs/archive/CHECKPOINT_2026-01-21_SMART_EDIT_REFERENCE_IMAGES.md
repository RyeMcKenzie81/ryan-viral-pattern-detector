# Checkpoint: Smart Edit Reference Images & Bug Fixes

**Date:** 2026-01-21
**Branch:** feat/veo-avatar-tool
**Status:** Complete (including brand logo feature)

## Features Implemented

### 1. Reference Image Selection for Smart Edit

Users can now select product images as references when using Smart Edit to fix issues like wrong logos.

**Service Changes** (`AdCreationService.create_edited_ad()`):
- Added `reference_image_ids: Optional[List[UUID]]` parameter
- Fetches selected images from `product_images` table
- Includes them in Gemini prompt with descriptions
- Updates prompt to instruct Gemini to use references for accurate reproduction

**UI Changes** (`Ad History page`):
- Added `get_product_images_for_ad(ad_id)` helper function
- Added expandable "📷 Add Reference Images" section in Smart Edit modal
- Shows product images in 4-column grid with checkboxes
- Main images labeled with ⭐, others numbered
- Analysis data shown in tooltips if available
- Selected images passed to `create_edited_ad()`

### 2. Bug Fixes

**Template Element Detection:**
- Fixed JSON parsing for vision analysis (Gemini returning double braces `{{`)
- Added 3-retry mechanism with Pydantic validation after parsing
- GoogleModel doesn't support structured outputs - reverted to manual JSON parsing
- Switched from `gemini-2.0-flash-exp` to `gemini-2.5-flash` for higher rate limits
- Updated people to be "optional_assets" (AI can generate them)

**Ad Creator:**
- Fixed `st.session_state.selected_product` not being set (badges now work)

**AdAnalysis Model:**
- Added missing fields: `has_social_proof`, `social_proof_style`, `social_proof_placement`
- Added missing fields: `has_founder_signature`, `founder_signature_style`, `founder_signature_placement`
- Added missing fields: `has_founder_mention`, `founder_mention_style`

## Files Modified

| File | Changes |
|------|---------|
| `viraltracker/services/ad_creation_service.py` | Added `reference_image_ids` param to `create_edited_ad()` |
| `viraltracker/services/models.py` | Added social proof and founder fields to `AdAnalysis` |
| `viraltracker/services/template_element_service.py` | Switched to gemini-2.5-flash, fixed JSON parsing |
| `viraltracker/agent/agents/ad_creation_agent.py` | Fixed vision analysis with 3 retries and Pydantic validation |
| `viraltracker/ui/pages/21_🎨_Ad_Creator.py` | Fixed `selected_product` session state |
| `viraltracker/ui/pages/22_📊_Ad_History.py` | Added reference image selection UI |

## Current State

**Working:**
- Smart Edit with reference images from product_images table
- Template element detection batch analysis (435 templates analyzed)
- Asset matching badges on template grid
- **Brand logos in Smart Edit reference images** (added in follow-up commit)
- **Logo upload UI in Brand Manager page** (added in follow-up commit)

**Not Working / Missing:**
- Logo upload in Client Onboarding has TODO comment - not implemented (separate feature)

## Brand Logo Feature (Implemented)

Added support for brand logos in Smart Edit reference images:

| File | Changes |
|------|---------|
| `migrations/2026-01-21_brand_assets.sql` | New table for brand logos |
| `viraltracker/ui/pages/02_🏢_Brand_Manager.py` | Logo upload UI in Brand Settings |
| `viraltracker/ui/pages/22_📊_Ad_History.py` | Brand logos section in reference images |
| `viraltracker/services/ad_creation_service.py` | Lookup images from both tables |

**Storage Pattern:** `brand-assets/{brand_id}/logo_{uuid}.png`

---

## Technical Details

### Reference Image Flow

```
User clicks Smart Edit
    ↓
get_product_images_for_ad(ad_id)
    ↓
ad_id → ad_run_id → product_id → product_images
    ↓
Display in 4-column grid with checkboxes
    ↓
User selects images, clicks Generate
    ↓
create_edited_ad(source_ad_id, edit_prompt, reference_image_ids=[...])
    ↓
Fetch images, build prompt with descriptions
    ↓
Gemini generates edit with reference images
```

### Database Schema Reference

```sql
-- Product images
product_images:
  id, product_id, storage_path, image_analysis, analyzed_at, is_main

-- Brand assets (logos, etc.) - NEW
brand_assets:
  id, brand_id, storage_path, asset_type, filename, is_primary,
  sort_order, image_analysis, analyzed_at, notes

-- Deprecated: brands.logo_storage_path (not used, logos now in brand_assets)
```
