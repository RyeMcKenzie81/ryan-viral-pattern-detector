# Checkpoint 11: Video Avatar with Voice

**Date**: 2026-02-27
**Branch**: `feat/chainlit-agent-chat`
**Status**: Implemented, pending empirical testing

---

## Summary

Added video-based Kling element creation with voice binding to the Avatar Builder. When generating multi-scene Omni Videos, each scene previously got a random voice despite using the same avatar element. Video elements auto-extract voice from the reference video and bind it to the element, ensuring voice consistency across scenes.

### Problem

Image-based elements (`reference_type: "image_refer"`) cannot carry voice data. Kling's Omni-Video endpoint does not support `voice_list`, so voice must come through the element itself. Only `reference_type: "video_refer"` elements support voice binding.

### Solution

Three options added to each avatar card in the UI:

1. **Option 1 (Primary)**: Generate calibration video from frontal reference image, create video element with auto-extracted voice
2. **Option 2**: Upload voice sample video to extract `voice_id`, then generate calibration video and bind the known voice
3. **Option 3**: Upload a video directly for both visual appearance and voice

### Core Untested Assumption

Whether `sound: "on"` + `element_list` on Omni-Video actually uses the element's bound voice vs. generating a random voice is not explicitly documented. This must be verified empirically.

---

## Files Changed

| File | Change |
|------|--------|
| `migrations/2026-02-27_avatar_video_element.sql` | **NEW** — Add `kling_voice_id`, `calibration_video_path`, `avatar_setup_mode` columns to `brand_avatars` |
| `viraltracker/services/veo_models.py` | Add 3 fields to `BrandAvatar`: `kling_voice_id`, `calibration_video_path`, `avatar_setup_mode` |
| `viraltracker/services/kling_video_service.py` | Add `create_video_element()`, `query_element()`, `delete_element()` methods |
| `viraltracker/services/avatar_service.py` | Add `generate_calibration_video()`, `extract_voice_from_video()`, `create_kling_video_element()`, `_upload_video()`, `_get_video_signed_url()`, update `_row_to_avatar()` |
| `viraltracker/ui/pages/47_🎭_Avatars.py` | Add `render_video_avatar_section()` with voice extraction, calibration video gen, and upload options |
| `scripts/test_two_scene_video.py` | Add `--video-element <element_id>` flag for voice consistency testing |

---

## Architecture

### New KlingVideoService Methods

```
create_video_element()  → POST /v1/general/advanced-custom-elements (reference_type: "video_refer")
query_element()         → GET  /v1/general/advanced-custom-elements/{task_id}
delete_element()        → POST /v1/general/delete-elements
```

### New AvatarService Methods

```
generate_calibration_video()    → Omni-Video 8s from frontal image → Supabase storage
extract_voice_from_video()      → Upload video → temp element → extract voice_id → delete temp element
create_kling_video_element()    → Full pipeline: calibration/upload → video element → voice binding
```

### Database Schema Addition

```sql
brand_avatars.kling_voice_id       TEXT     -- Voice ID from element_voice_info
brand_avatars.calibration_video_path TEXT   -- Storage path for calibration video
brand_avatars.avatar_setup_mode    TEXT     -- 'multi_image' or 'video_element'
```

### UI Flow

```
Avatar Card
├── [Existing] 4-angle reference images
├── [Existing] Kling Element (image-based)
└── [NEW] Video Avatar (with Voice)
    ├── Status display (mode + voice_id)
    ├── Step 1 (Optional): Upload voice sample → extract voice_id
    ├── Step 2: Generate Video Avatar (calibration video → video element)
    └── Alternative: Upload video (visual + voice from upload)
```

---

## Key Decisions

- **Video element replaces image element** — `kling_element_id` is overwritten when creating a video element. Original images remain for potential rollback.
- **`element_voice_id` binds existing voice at creation time** — If avatar already has a `kling_voice_id`, it's passed to the new element via `element_voice_id`.
- **Temp element cleanup** — Voice extraction creates a temporary element that is deleted after `voice_id` is extracted.
- **Calibration video reuse** — If a calibration video already exists, it's reused for subsequent element creations.

### API Constraints (from Kling 3.0 docs)

1. Omni-Video does NOT support `voice_list` — voice must come through the element
2. Only `reference_type: "video_refer"` elements support voice binding
3. Video elements auto-extract voice from speech in the reference video
4. `element_voice_id` can bind an existing voice to a new element at creation time
5. Video constraints: .mp4/.mov, 1080p, 3-8s, 16:9 or 9:16, max 200MB

### Cost Estimates

| Operation | Cost |
|-----------|------|
| Calibration video (Omni-Video, pro, 8s, audio) | ~$1.57 |
| Video element creation | Free |
| Option 1 (generate from images) | ~$1.57 |
| Option 2 (upload voice + generate from images) | ~$1.57 |
| Option 3 (upload video for both) | Free |

---

## Verification Checklist

- [x] Migration SQL created
- [x] BrandAvatar model updated with 3 new fields
- [x] KlingVideoService: `create_video_element()`, `query_element()`, `delete_element()`
- [x] AvatarService: full video avatar pipeline
- [x] UI: Video Avatar section in avatar cards
- [x] Test script: `--video-element` flag for voice consistency testing
- [x] All files pass `python3 -m py_compile`
- [ ] **CRITICAL**: Run migration against Supabase
- [ ] **CRITICAL**: Empirical test — video element + `sound: "on"` → verify same voice across scenes
- [ ] Option 1 test: Generate calibration video → create video element → verify element_id + voice_id stored
- [ ] Option 2 test: Upload voice video → extract voice_id → generate calibration video with bound voice
- [ ] Option 3 test: Upload video directly → verify element_id + voice_id
- [ ] Run `scripts/test_two_scene_video.py --video-element <id>` → confirm consistent voice
- [ ] Backwards compatibility: existing image element workflow still works

---

## Script Usage

```bash
# Standard test (image element)
railway run python3 scripts/test_two_scene_video.py

# Test with video element (voice consistency)
railway run python3 scripts/test_two_scene_video.py --video-element <element_id>

# Reuse anchor images from previous run
railway run python3 scripts/test_two_scene_video.py --video-element <element_id> --reuse-images <run_id>
```
