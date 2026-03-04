# Checkpoint 09: Avatar 4-Angle Workflow + Kling Element Creation

**Date**: 2026-02-26
**Branch**: `feat/chainlit-agent-chat`
**Status**: Implemented, pending manual QA

---

## Summary

Upgraded the Veo Avatars page to a generic "Avatars" page with a guided 4-angle generation workflow using Gemini and integrated Kling element creation directly into the avatar management flow.

### What Changed

The existing Avatars page had generic "Ref 1/2/3" image slots with no angle guidance. For Kling AI's element creation to produce consistent characters across video scenes, it needs specific reference angles: **frontal, 3/4 view, side profile, and full body**.

This upgrade:
- Renames the page from "Veo Avatars" to "Avatars" (engine-agnostic)
- Adds a guided 4-angle generation workflow using Gemini
- Integrates Kling element creation directly into the avatar management flow
- Keeps existing Veo video generation as a secondary tab
- DRYs up element creation logic shared with Video Studio

**Estimated cost per avatar**: ~$0.08 (4 Gemini images) + ~$0.05 one-time element creation.

---

## Files Changed

| File | Change | Lines |
|------|--------|-------|
| `migrations/2026-02-26_avatar_reference_image_4.sql` | New migration: `reference_image_4` column | 10 |
| `viraltracker/services/veo_models.py` | Added `reference_image_4`, `kling_element_id` fields; updated `reference_images` property | ~15 |
| `viraltracker/services/avatar_service.py` | Slot validation 3→4, `generate_angle_image()`, `create_kling_element()`, stale element invalidation, row mapping | ~200 |
| `viraltracker/ui/pages/47_🎭_Avatars.py` | Renamed from `47_🎬_Veo_Avatars.py`; rewritten Avatar Manager tab | ~530 |
| `viraltracker/ui/nav.py` | Updated page reference + title | 1 |
| `viraltracker/ui/pages/51_🎬_Video_Studio.py` | DRYed element creation → `AvatarService.create_kling_element()` | ~-35 |
| `viraltracker/services/video_recreation_service.py` | Added `reference_image_4` to keyframe SELECT + iteration | 2 |

---

## Key Design Decisions

### 1. Two Paths to Avatar Creation

**Path A: Upload a seed image** — User uploads a photo as slot 1 (Frontal), then generates remaining angles using it as reference. Best for specific looks or real photos.

**Path B: Generate from scratch** — All 4 angles generated sequentially from the `generation_prompt`. Each subsequent angle uses all prior angles as references.

Both paths are supported per-slot: each has Upload AND Generate buttons. Users can mix and match.

### 2. Sequential Reference Chaining

Each angle generation feeds all prior slot images as `reference_images` to Gemini, plus identity-anchoring prompts ("SAME person, same outfit"). Temperature set to 0.3 for consistency.

### 3. Stale Element Auto-Invalidation

When any reference image is added or removed, `kling_element_id` is automatically cleared. This prevents using stale elements that don't match the current reference images.

### 4. Safety Filter Handling

`generate_angle_image()` catches safety filter errors and returns None. The UI skips that slot and continues to the next, showing a warning.

### 5. Feature Key Backward Compatibility

Feature key stays `"veo_avatars"` in `require_feature()` for backward compatibility with the `org_features` table.

---

## Angle-Specific Prompt Templates

| Slot | Angle | Prompt Focus |
|------|-------|-------------|
| 1 | Frontal | Passport-style, neutral expression, direct camera gaze, square composition |
| 2 | 3/4 View | Face turned ~45 degrees, same outfit/hairstyle, maintain exact features |
| 3 | Side Profile | Pure side view, jawline/ear/hair, same outfit and lighting |
| 4 | Full Body | Standing straight, head to feet, portrait orientation, same outfit |

---

## UI Structure

```
Tabs: [Avatar Manager] [Veo Video] [History]
```

**Avatar Manager tab:**
- Create avatar form (with generation prompt guidance)
- Per-avatar expandable card:
  - Info row (description, prompt, settings)
  - 4-column angle grid (image preview, Upload, Generate per slot)
  - "Generate All Missing Angles" button with progress bar
  - Visual verification strip (side-by-side comparison of all 4 angles)
  - Kling Element section (create/view element)
- Veo Video and History tabs: unchanged

---

## Verification Checklist

- [x] Migration file created
- [x] All files compile (`python3 -m py_compile`)
- [x] No references to old filename in functional code
- [ ] Run migration on Supabase
- [ ] Manual UI test: create avatar, generate 4 angles, create element
- [ ] Manual UI test: upload seed image, generate remaining angles
- [ ] Manual UI test: regenerate single angle, verify element cleared
- [ ] Video Studio: verify element creation still works via DRYed code
- [ ] Existing tests pass: `pytest tests/test_kling_models.py tests/test_kling_video_service.py tests/test_video_recreation_service.py`

---

## Dependencies

- Gemini 3 Pro Image Preview (for angle generation)
- Kling AI API (for element creation)
- Supabase storage `avatars` bucket (existing)
