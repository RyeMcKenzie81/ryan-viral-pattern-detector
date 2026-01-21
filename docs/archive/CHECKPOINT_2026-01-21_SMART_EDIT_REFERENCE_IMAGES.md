# Checkpoint: Smart Edit Reference Images & Brand Logo Support

**Date:** 2026-01-21
**Branch:** feat/veo-avatar-tool
**Status:** Complete

---

## Summary

This session implemented brand logo support for Smart Edit reference images, allowing users to select their brand logos when fixing logo issues in generated ads.

---

## Features Implemented

### 1. Reference Image Selection for Smart Edit (Previous Session)

Users can select product images as references when using Smart Edit to fix issues like wrong logos.

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

### 2. Brand Logo Support (This Session)

Full implementation of brand logo storage and integration with Smart Edit.

#### Database Migration
**File:** `migrations/2026-01-21_brand_assets.sql`

```sql
CREATE TABLE IF NOT EXISTS brand_assets (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    brand_id UUID NOT NULL REFERENCES brands(id) ON DELETE CASCADE,
    storage_path TEXT NOT NULL,
    asset_type VARCHAR(50) NOT NULL DEFAULT 'logo',
    filename TEXT,
    is_primary BOOLEAN DEFAULT FALSE,
    sort_order INTEGER DEFAULT 0,
    created_at TIMESTAMPTZ DEFAULT NOW(),
    updated_at TIMESTAMPTZ DEFAULT NOW(),
    image_analysis JSONB DEFAULT NULL,
    analyzed_at TIMESTAMPTZ,
    notes TEXT
);
```

**Storage:** Private bucket `brand-assets` (uses signed URLs)
**Pattern:** `brand-assets/{brand_id}/{uuid}.png`

#### Brand Manager UI
**File:** `viraltracker/ui/pages/02_🏢_Brand_Manager.py`

Added to Brand Settings section:
- Logo upload with file picker (PNG, JPG, JPEG, WebP - no SVG)
- Grid display of existing logos
- Primary logo selection (⭐ button)
- Delete functionality
- First uploaded logo automatically set as primary
- Image processing preserves transparency for logos

Helper functions added:
- `get_brand_assets(brand_id, asset_type)` - Fetch brand assets
- `upload_brand_logo(brand_id, file, asset_type)` - Upload with processing
- `process_logo_image(file_bytes, max_size)` - Resize, preserve transparency
- `delete_brand_asset(asset_id, storage_path)` - Delete from storage + DB
- `set_primary_brand_logo(brand_id, asset_id)` - Set primary flag

#### Smart Edit Reference Images
**File:** `viraltracker/ui/pages/22_📊_Ad_History.py`

- Added `get_brand_logos_for_ad(ad_id)` function
- Brand Logos section appears at TOP of reference images (before product images)
- Shows primary logo with ⭐ label
- Checkboxes to select logos as reference images

**Data Flow (Fixed):**
```
ad_id → ad_run_id (generated_ads)
      → product_id (ad_runs)
      → brand_id (products)
      → logos (brand_assets)
```

#### Service Update
**File:** `viraltracker/services/ad_creation_service.py`

Updated `create_edited_ad()` to lookup reference images from both tables:
1. First checks `product_images` table
2. If not found, checks `brand_assets` table
3. Includes appropriate description in prompt (e.g., "primary brand logo")

---

## Bug Fixes (This Session)

### 1. Brand Logo Not Showing in Reference Images
**Problem:** `get_brand_logos_for_ad()` tried to get `brand_id` from `ad_runs`, but that column doesn't exist.

**Solution:** Added extra step to get brand via product:
- `ad_runs` has `product_id`, not `brand_id`
- Query path: ad → ad_run → product → brand → logos

**Commit:** `5262c6e`

---

## Files Modified/Created

| File | Action | Description |
|------|--------|-------------|
| `migrations/2026-01-21_brand_assets.sql` | CREATE | New table for brand logos |
| `viraltracker/ui/pages/02_🏢_Brand_Manager.py` | MODIFY | Logo upload UI + helper functions |
| `viraltracker/ui/pages/22_📊_Ad_History.py` | MODIFY | Brand logos in reference images + bug fix |
| `viraltracker/services/ad_creation_service.py` | MODIFY | Lookup from both product_images and brand_assets |

---

## Database Changes

### New Table: `brand_assets`
```sql
brand_assets:
  id              UUID PRIMARY KEY
  brand_id        UUID NOT NULL (FK → brands)
  storage_path    TEXT NOT NULL
  asset_type      VARCHAR(50) DEFAULT 'logo'
  filename        TEXT
  is_primary      BOOLEAN DEFAULT FALSE
  sort_order      INTEGER DEFAULT 0
  created_at      TIMESTAMPTZ
  updated_at      TIMESTAMPTZ
  image_analysis  JSONB
  analyzed_at     TIMESTAMPTZ
  notes           TEXT
```

### New Storage Bucket
- **Name:** `brand-assets`
- **Public:** No (private, uses signed URLs)

### Deleted Brands (User Request)
- Ecom
- Test Brand
- Masculinity Research

---

## Setup Instructions

To use brand logos in Smart Edit:

1. **Run migration** (if not done):
   ```sql
   -- See migrations/2026-01-21_brand_assets.sql
   ```

2. **Create storage bucket** in Supabase Dashboard:
   - Name: `brand-assets`
   - Public: No (private)

3. **Upload logos:**
   - Brand Manager → Select Brand → Brand Settings → Brand Logos
   - Upload PNG (recommended for transparency) or JPG/WebP
   - First logo auto-set as primary

4. **Use in Smart Edit:**
   - Ad History → Click ad → Smart Edit
   - Expand "Add Reference Images"
   - Brand Logos section at top
   - Select logo checkbox → Generate Edit

---

## Technical Notes

### Why `brand_assets` Table vs `brands.logo_storage_path`?
- **Flexible:** Supports multiple logo variants (primary, white, dark, horizontal)
- **Consistent:** Follows `product_images` pattern
- **Extensible:** Can add other brand assets later (guidelines images, etc.)

### Image Processing
- Logos preserve transparency (PNG output if RGBA/P mode)
- Max dimension: 1000px (configurable)
- Product images convert to JPEG; logos stay PNG when transparent

### Data Flow for Reference Images
```
Smart Edit Modal
    ↓
get_brand_logos_for_ad(ad_id)
    ↓
ad_id → generated_ads.ad_run_id
      → ad_runs.product_id
      → products.brand_id
      → brand_assets (WHERE asset_type='logo')
    ↓
Display with signed URLs
    ↓
User selects → reference_image_ids[]
    ↓
create_edited_ad() looks up from:
  1. product_images
  2. brand_assets (fallback)
    ↓
Include in Gemini prompt as reference
```

---

## Commits

| Hash | Description |
|------|-------------|
| `8651475` | feat: Add brand logos support for Smart Edit reference images |
| `56b4f99` | docs: Update checkpoint to reflect brand logo feature implementation |
| `5262c6e` | fix: Get brand_id via product_id in get_brand_logos_for_ad |
