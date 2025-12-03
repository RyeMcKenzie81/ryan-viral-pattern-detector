# CHECKPOINT: Size Variants Improvements

**Date**: December 3, 2025
**Status**: Complete

---

## Summary

Fixed and improved the size variants feature for creating different aspect ratio versions of approved ads. Multiple bug fixes, UX improvements, and prompt enhancements.

---

## Commits This Session

| Commit | Description |
|--------|-------------|
| `d79c50c` | fix: Use Nano Banana Pro 3 for size variant generation |
| `cc36fbe` | feat: Add no-duplicate-text rule and delete functionality |
| `f5fe5f6` | feat: Add letterboxing instructions for 9:16 size variants |
| `e60c075` | fix: Hide source ad's current size from size variant options |
| `db27267` | fix: Auto-approve size variants from approved source ads |

---

## Changes Made

### 1. Fixed Image Generation Model (d79c50c)

**Problem**: Size variants were coming out as 1:1 with artifacts regardless of selected size.

**Cause**: Was using `gemini-2.0-flash-exp` which doesn't respect dimension instructions.

**Fix**: Switched to `GeminiService.generate_image()` which uses `models/gemini-3-pro-image-preview` (Nano Banana Pro 3) - same model as main ad generation.

**File**: `viraltracker/services/ad_creation_service.py`

---

### 2. Added Delete Functionality (cc36fbe)

**Features**:
- Added `delete_generated_ad()` method to AdCreationService
- Deletes ad from database AND storage
- Optionally deletes all size variants of the ad
- Added "Delete" button to each ad in Ad History
- Confirmation dialog before deletion
- Shows variant count that will be deleted

**Files**:
- `viraltracker/services/ad_creation_service.py` - Added `delete_generated_ad()` method
- `viraltracker/ui/pages/02_Ad_History.py` - Added delete UI

---

### 3. No Duplicate Text Rule (cc36fbe)

**Problem**: AI was sometimes duplicating text elements in variants.

**Fix**: Added explicit instructions to prompt:
- "DO NOT duplicate any text - each text element should appear only ONCE"
- "The hook text MUST be: {hook_text} (appear exactly ONCE, not repeated)"

---

### 4. Letterboxing for 9:16 (f5fe5f6)

**Problem**: Stretching 1:1 or 4:5 ads to 9:16 creates ugly distortion.

**Fix**: Added conditional letterboxing instructions for 9:16 variants:
```
**LETTERBOXING FOR TALL FORMAT (CRITICAL):**
- DO NOT stretch or distort the original ad content
- Use LETTERBOXING: place content in center/upper portion
- Fill extra vertical space with colors from ad's palette
- Keep all original content at proper proportions
```

**File**: `viraltracker/services/ad_creation_service.py`

---

### 5. Hide Current Size Option (e60c075)

**Problem**: If resizing a 1:1 ad, 1:1 was still shown as an option.

**Fix**:
- Added `get_ad_current_size()` function to detect source ad's aspect ratio
- Size selection now skips the source ad's current size
- Checks: `variant_size`, `prompt_spec.canvas.aspect_ratio`, dimension strings

**File**: `viraltracker/ui/pages/02_Ad_History.py`

---

### 6. Auto-Approve Variants (db27267)

**Problem**: Variants were created with `final_status = 'pending'`, causing confusing counts like "2/7 approved".

**Fix**: Variants now inherit `approved` status since they're created from approved source ads.

**Future**: Add variant review system for QA.

**File**: `viraltracker/services/ad_creation_service.py`

---

## Database Migrations Required

None - all changes are code-only.

To fix existing pending variants:
```sql
UPDATE generated_ads
SET final_status = 'approved'
WHERE parent_ad_id IS NOT NULL AND final_status = 'pending';
```

---

## Architecture

Size variant generation follows the project's layered architecture:

```
┌─────────────────────────────────────────┐
│         SERVICE LAYER (Core)            │
│  AdCreationService.create_size_variant()│
│  - Uses GeminiService.generate_image()  │
│  - Same model as main ad generation     │
│  - Storage upload                       │
│  - Database save                        │
└─────────────┬───────────────────────────┘
              │
   ┌──────────┴──────────┐
   │                     │
   ▼                     ▼
┌──────────┐      ┌────────────┐
│  Agent   │      │    UI      │
│  Tool    │      │ (Streamlit)│
│ (wrapper)│      │            │
└──────────┘      └────────────┘
```

---

## Files Modified

| File | Changes |
|------|---------|
| `viraltracker/services/ad_creation_service.py` | Fixed model, added delete, improved prompts, auto-approve |
| `viraltracker/ui/pages/02_Ad_History.py` | Added delete UI, size detection, hide current size |

---

## How to Use

**Create Size Variants:**
1. Open Ad History
2. Expand a run with approved ads
3. Click "Create Sizes" on an approved ad
4. Select target sizes (source size is hidden)
5. Click "Generate Variants"
6. Wait 30-60 seconds per variant

**Delete Ads:**
1. Click "Delete" on any ad
2. Confirm deletion
3. Variants are deleted with parent ad

---

## Known Limitations

- Generation takes 30-60 seconds per variant (Gemini API)
- No variant review system yet (variants auto-approved)
- Letterboxing only implemented for 9:16 (most extreme ratio change)
