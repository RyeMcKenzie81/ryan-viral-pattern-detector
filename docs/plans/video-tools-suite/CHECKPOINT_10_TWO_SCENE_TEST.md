# Checkpoint 10: Two-Scene Seamless Cut Test

**Date**: 2026-02-27
**Branch**: `feat/chainlit-agent-chat`
**Status**: Partially working — video generation succeeds, **audio missing** (needs investigation)

---

## Summary

Created a standalone test script (`scripts/test_two_scene_video.py`) that generates two 8-second Kling Omni Video scenes sharing a "transition image" at the cut point for seamless visual continuity. Both scenes generated successfully, but output videos are **silent** despite `sound: "on"` being set and Kling charging audio pricing.

### What Was Built

The test script implements this pipeline:
1. **Gemini image generation** — 2 images (scene start + transition) using avatar reference images for character consistency
2. **Supabase upload** — Images uploaded to `kling-videos` bucket with signed URLs
3. **Scene 1**: Kling Omni Video with scene start image (`first_frame`) → transition image (`end_frame`)
4. **Scene 2**: Kling Omni Video with transition image (`first_frame`) — seamless cut from Scene 1's end
5. **Polling + download** — Both videos polled to completion and stored in Supabase

### Test Run Results

- **Run ID**: `20260227_071842`
- **Scene 1**: Succeeded in 678s, stored at `kling-videos/805f0d39-58db-491d-86be-02e2dd3647ea/video.mp4`
- **Scene 2**: Succeeded in 689s, stored at `kling-videos/ac79df85-8424-4f11-a85b-20cad6dab4ac/video.mp4`
- **Images**: `kling-videos/two_scene_test/20260227_071842/scene_start.png` and `transition.png`
- **Cost**: ~$2.24 total ($1.12 per scene — $0.20/sec × 8s audio pricing)
- **Audio**: SILENT — both videos have no audible audio despite `sound: "on"` and audio-rate pricing

---

## Files Changed

| File | Change |
|------|--------|
| `scripts/test_two_scene_video.py` | **NEW** — Full two-scene test pipeline |

---

## Key Configuration

```python
AVATAR_ID = "2fb823c6-47a8-4c85-9715-7923ab008a25"
BRAND_ID = "bc8461a8-232d-4765-8775-c75eaafc5503"
ELEMENT_ID = "856253468745531453"
STORAGE_BUCKET = "kling-videos"
```

### Script Usage

```bash
# Full run (generates new images via Gemini)
railway run python3 scripts/test_two_scene_video.py

# Reuse previously generated images (skip Gemini, just run Kling)
railway run python3 scripts/test_two_scene_video.py --reuse-images 20260227_071842
```

**Note**: Must use `railway run` to inject Kling API keys (`KLING_ACCESS_KEY`, `KLING_SECRET_KEY`) from Railway environment.

---

## Issues Encountered & Fixes

| Issue | Fix |
|-------|-----|
| `python` not found on macOS | Use `python3` |
| Kling auth error "iss is null" | Local `.env` missing Kling keys; use `railway run` to inject |
| Scene 1 poll timeout at 600s | Bumped to 900s (15 min); 8s pro+audio+element takes ~11 min |
| Scene 1 Supabase download failure | Empty error; httpx timeout on large upload. Re-downloaded manually |
| `datetime.utcnow()` deprecation | Changed to `datetime.now(timezone.utc)` |

---

## UNRESOLVED: No Audio on Generated Videos

### Symptoms
- `sound: "on"` correctly sent in API payload
- Kling charged audio pricing ($0.20/sec vs $0.14/sec for no-audio)
- Output `.mp4` files play video correctly but are completely silent

### Hypothesis
Kling's `sound: "on"` parameter generates **ambient/environmental audio** — background sounds matched to the visual scene. It does NOT generate **spoken dialogue** from quoted text in the prompt.

For speech audio, the Kling API may require:
- A `voice_ids` parameter (seen in some API references)
- A `voice_id` field on the element
- A separate TTS step (generate speech audio separately, then combine)

### Investigation Needed
See the prompt below for next steps.

---

## Where to Find Kling API Documentation

The Kling API docs website (`https://app.klingai.com/global/dev/document-api/`) is a SPA that doesn't render for web scraping. Local knowledge lives in:

1. **`viraltracker/services/kling_models.py`** — Pydantic models with field constraints, docstrings documenting API behavior
2. **`viraltracker/services/kling_video_service.py`** — Implementation with API endpoints and payload construction
3. **`docs/plans/video-tools-suite/PLAN.md`** — Lines 370-430 document Kling Omni API fields including `sound`, `voice_ids`
4. **`docs/plans/video-tools-suite/CHECKPOINT_08_KLING_OMNI_IMPLEMENTED.md`** — Implementation details

**Note**: The user mentioned having API docs "downloaded locally" but they were not found as standalone files. The knowledge is distributed across the files above.

---

## Prompt for Next Context Window

Use the following prompt to continue investigating the audio issue:

```
I'm working on a two-scene video generation pipeline using the Kling AI Omni Video API.
The videos generate successfully but have NO AUDIO despite `sound: "on"` being set.

**Context:**
- Test script: `scripts/test_two_scene_video.py`
- Latest successful run with `--reuse-images 20260227_071842`
- Videos stored in Supabase `kling-videos` bucket
- Kling charged audio pricing ($0.20/sec) but output is silent
- Using `kling-v3-omni` model, `mode: "pro"`, `duration: "8"`, `sound: "on"`

**Key files to read first:**
1. `viraltracker/services/kling_models.py` — Look for `voice_ids`, `voice_id`, or other audio params
2. `viraltracker/services/kling_video_service.py` — How the API payload is constructed
3. `docs/plans/video-tools-suite/PLAN.md` — Lines 370-430, Kling Omni API spec
4. `docs/plans/video-tools-suite/CHECKPOINT_10_TWO_SCENE_TEST.md` — Full context

**Investigation tasks:**
1. Search the codebase for any `voice_id` or `voice_ids` references
2. Check if the Kling Omni API has a voice/speech parameter we're not sending
3. Try fetching the Kling API docs at https://app.klingai.com/global/dev/document-api/
4. Research online: "Kling AI Omni video voice_id speech audio API"
5. Determine whether Kling's native audio is ambient-only or supports speech
6. If speech requires a separate step (TTS + audio overlay), identify the best approach
7. Update the test script or service code with the fix

**Goal:** Get the avatar to actually SPEAK the dialogue in the video scenes.
```
