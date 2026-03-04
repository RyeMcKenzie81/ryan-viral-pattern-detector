# Checkpoint: Video & Iframe Preservation in Sanitizer

- **Date**: 2026-02-25
- **Branch**: `feat/ad-creator-v2-phase0`
- **Commit**: (pending)
- **Status**: COMPLETE

---

## Problem Solved

The S0 sanitizer stripped `<video>` and `<iframe>` tags entirely via `_STRIP_TAGS_WITH_CONTENT`, causing missing visuals and lost semantic information:

### Issue 1: Missing Product "Photo" — Actually a Video
- The NordBench "product photo" (woman using bench) is actually a `<video autoplay muted loop>` element — a common Shopify/Replo pattern of using looping muted video as a hero visual
- Sanitizer stripped `<video>` entirely, leaving an empty `<div class="r-th2tet"></div>` container
- Result: blank gap where the product visual should be

### Issue 2: Missing Testimonial Video Thumbnail
- The testimonial section contained a `<video poster="...">` element
- Stripping the video also lost the poster thumbnail image
- Result: missing visual in testimonial section

### Issue 3: Missing YouTube Embeds (4 total)
- The page had 4 YouTube `<iframe>` embeds including "Watch: How the NordBench Pro Works"
- Sanitizer stripped all iframes, leaving empty whitespace with no indication of what was there
- Result: large blank areas with no semantic information preserved

---

## Fixes Applied

### Fix 1: Video → Poster/Placeholder Conversion
- Removed `"video"` from `_STRIP_TAGS_WITH_CONTENT`
- Added `_convert_videos_to_posters()` method in sanitizer
- `<video poster="URL">` → `<img src="{poster}" data-was-video="true" loading="eager">`
- `<video autoplay muted loop>` (no poster) → `<div data-was-video="true" data-video-src="..." style="background:#e5e7eb">` (gray placeholder preserving layout)

### Fix 2: Iframe → Thumbnail/Placeholder Conversion
- Removed `"iframe"` from `_STRIP_TAGS_WITH_CONTENT`
- Added `_convert_iframes_to_placeholders()` method in sanitizer
- YouTube iframes → `<img src="https://img.youtube.com/vi/{id}/hqdefault.jpg" data-was-iframe="youtube" data-video-id="{id}">` (thumbnail filling parent container)
- Other iframes → `<div data-was-iframe="true" data-iframe-src="...">` (labeled dark placeholder)

### Key Design Decisions
- YouTube thumbnails inherit parent container sizing (`width:100%;height:100%;object-fit:cover`) rather than forcing their own `aspect-ratio`, since the iframe's parent container already defines the space
- Autoplay muted loop videos without poster get gray placeholders (no way to extract a frame without ffmpeg)
- All placeholders carry `data-was-video` / `data-was-iframe` attributes for downstream pipeline awareness
- YouTube placeholders include `data-video-id` and thumbnail URL for blueprint generation

---

## Results

### SSIM Scores (Playwright reference screenshots)

| Page | Previous S0 | New S0 | Previous S3 | New S3 | S0 Change |
|------|-------------|--------|-------------|--------|-----------|
| NordStick | 0.7373 | **0.7245** | 0.7373 | **0.7245** | -0.0128 |
| InfiniteAge | 0.8512 | **0.8512** | 0.7408 | **0.7408** | 0.0000 |
| Boba | 0.6807 | **0.6807** | 0.6366 | **0.6366** | 0.0000 |

### NordStick SSIM Note
The -0.0128 SSIM drop on NordStick is because YouTube thumbnails are now visible content filling space that's blank in the original Playwright screenshot (cross-origin iframes don't render in `page.content()`). The user reviewed the visual output and confirmed the recreation is very good — the thumbnails correctly represent what's on the actual page. **Regression floor adjusted from 0.73 to 0.72.**

### Visual Improvements
- NordBench product area: gray placeholder visible instead of empty gap
- Testimonial video: poster thumbnail now renders
- YouTube embeds: 4 thumbnails now visible with proper sizing
- All semantic data preserved for downstream blueprint generation

---

## Files Changed

| File | Change |
|------|--------|
| `surgery/sanitizer.py` | Removed `video`/`iframe` from strip list; added `_convert_videos_to_posters()` and `_convert_iframes_to_placeholders()` |

---

## Verification Commands

```bash
# Unit tests (387 pass)
python3 -m pytest tests/test_multipass_v4.py -x -q

# NordStick (S0 = S3 = 0.7245)
MULTIPASS_PHASE1_MODE=v2 MULTIPASS_PIPELINE_MODE=surgery PYTHONPATH=. \
  python3 scripts/test_multipass_local.py \
  --url "thenordstick.com/pages/nordbench-founder-story-solve-body-pain" --playwright-dom --visual

# InfiniteAge (S3: 0.7408)
MULTIPASS_PHASE1_MODE=v2 MULTIPASS_PIPELINE_MODE=surgery PYTHONPATH=. \
  python3 scripts/test_multipass_local.py \
  --url "infiniteage.com/pages/sea-moss-for-hair-growth" --playwright-dom --visual

# Boba (S3: 0.6366)
MULTIPASS_PHASE1_MODE=v2 MULTIPASS_PIPELINE_MODE=surgery PYTHONPATH=. \
  python3 scripts/test_multipass_local.py \
  --url "bobanutrition.co" --playwright-dom --visual
```

---

## Regression Thresholds (Updated)

| Metric | Floor | Notes |
|--------|-------|-------|
| NordStick S3 SSIM | >= 0.72 | Adjusted from 0.73 — YouTube thumbnails add content not in reference screenshot |
| InfiniteAge S3 SSIM | >= 0.74 | Unchanged |
| Boba S3 SSIM | >= 0.63 | Unchanged |
| Unit tests | 387 pass | No regression |
