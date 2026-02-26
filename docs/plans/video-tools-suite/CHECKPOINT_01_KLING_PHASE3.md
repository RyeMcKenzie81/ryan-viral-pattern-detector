# Video Tools Suite - Checkpoint 01: Kling Phase 3 Implementation

**Date:** 2026-02-25
**Branch:** `feat/chainlit-agent-chat` (worktree: `worktree-feat/chainlit-agent-chat`)
**Status:** Phase 3 core implementation complete, post-plan review PASS

---

## What Was Done

### Summary

Implemented Phase 3 (Kling Video Service) of the Video Tools Suite plan. This was a ground-up implementation using the **official Kling API documentation** from `app.klingai.com/global/dev/document-api/`, correcting all assumptions made in the original plan that was written before the API docs were available.

### Key Corrections from Original Plan

| Area | Original (Wrong) | Corrected |
|------|------------------|-----------|
| Base URL | `api.klingai.com` | `api-singapore.klingai.com` |
| Integration | `fal.ai` gateway | Native API with JWT auth |
| Task statuses | 5-step: CREATED/QUEUED/RUNNING/FINALIZING/SUCCEEDED | 4-step: submitted/processing/succeed/failed |
| Model naming | `kling-v2.6-pro` (combined) | `kling-v2-6` + `mode: "pro"` (separate) |
| Duration type | Integer | String `Literal["5", "10"]` |
| Query endpoints | Single shared `/v1/videos/{task_id}` | Per-type: `/v1/videos/text2video/{task_id}`, etc. |
| Lip-sync | Deferred to V2 | Included in MVP (2-step: identify-face + advanced-lip-sync) |
| Avatar endpoint | `POST /v1/videos/avatar` | `POST /v1/videos/avatar/image2video` |

### Files Created (6 new)

| File | Lines | Purpose |
|------|-------|---------|
| `viraltracker/services/kling_models.py` | ~450 | Pydantic models: 5 enums (KlingEndpoint, KlingTaskStatus, KlingGenerationType, KlingMode, KlingAspectRatio), 7 request models, 6 response models, 1 DB record model |
| `viraltracker/services/kling_video_service.py` | ~770 | Full Kling API integration: JWT auth with caching, 6 generation methods, polling with exponential backoff, retry logic (5 error code types), concurrency control, Supabase download/storage, usage tracking |
| `viraltracker/services/video_generation_protocol.py` | ~100 | `@runtime_checkable` Protocol for VEO/Kling/Sora interop: `generate_from_prompt()`, `generate_talking_head()`, `get_status()`, `download_and_store()` |
| `migrations/2026-02-25_kling_generations.sql` | ~60 | `kling_video_generations` table with 38 columns, 6 indexes. Covers all generation types, lip-sync session data, multi-shot images, cost tracking |
| `tests/test_kling_models.py` | ~340 | 49 tests for all enums, request model validation, response models, DB record defaults |
| `tests/test_video_generation_protocol.py` | ~130 | 12 tests for VideoGenStatus, VideoGenerationResult properties, @runtime_checkable |
| `tests/test_kling_video_service.py` | ~680 | 74 tests covering validation helpers, JWT caching, retry logic, all generation methods, polling, poll_and_complete, download/storage, query methods, usage tracking, config costs, service constants |

### Files Modified (1)

| File | Change |
|------|--------|
| `viraltracker/core/config.py` | Added `KLING_ACCESS_KEY`, `KLING_SECRET_KEY`, `KLING_MAX_CONCURRENT` env vars. Added 6 Kling unit cost entries to `UNIT_COSTS` dict. |

### Plan Document Updated (1)

| File | Change |
|------|--------|
| `docs/plans/video-tools-suite/PLAN.md` | Complete rewrite of Phase 3 section with correct API details, endpoint paths, status enums, model names, error handling, lip-sync workflow, multi-shot storage design. Updated architecture diagram, files table, sprint references, deferred items list. |

---

## Technical Design Decisions

### 1. JWT Auth with Caching
- Token cached with 25-min TTL (30-min expiry minus 5-min buffer)
- 30-second `nbf` buffer for clock skew
- Auto-invalidation on 1004 error code, retry once

### 2. Endpoint-Specific Query Paths
Each endpoint type has its own GET path for polling. `KlingEndpoint` enum maps to both POST (create) and GET (query) paths. `poll_task()` takes `endpoint_type: KlingEndpoint` to construct the correct URL.

### 3. Retry Strategy
| Error Code | Meaning | Retries | Backoff |
|-----------|---------|---------|---------|
| 1301 | Content safety | 0 | Immediate fail |
| 1004 | JWT expired | 1 | Regenerate + retry |
| 1303 | Concurrent limit | 5 | Exponential (2s base, 60s cap) |
| 1302 | Rate limit | 5 | Exponential (2s base, 60s cap) |
| 5xx | Server error | 3 | Exponential (2s base, 60s cap) |

### 4. Lip-Sync Two-Step Workflow
1. `identify_faces(video_id/video_url)` -> synchronous, returns `session_id` + `face_data[]` -> stored as `awaiting_face_selection` status
2. UI presents face thumbnails with time ranges
3. `apply_lip_sync(session_id, face_id, sound_file/audio_id)` -> wraps into `face_choose` array per API spec -> async task with polling
4. Two separate DB records linked via `parent_generation_id`

### 5. Concurrency Control
`asyncio.Semaphore` (default 3, configurable via `KLING_MAX_CONCURRENT`) wraps all generation methods. Prevents exceeding Kling's account-level concurrent task limit.

### 6. Base64 Prefix Stripping
Kling API requires raw base64 only. `_strip_base64_prefix()` removes `data:image/...;base64,` prefixes on all image/audio parameters.

### 7. VideoGenerationProtocol Scope
Only generic video operations go on the Protocol (generate_from_prompt, generate_talking_head, get_status, download_and_store). Kling-specific features (lip-sync, multi-shot, video-extend) are called directly on `KlingVideoService`.

### 8. Cost Estimation
Cost calculated before API call and stored in DB record. Actual Kling units (`final_unit_deduction`) captured on completion for reconciliation.

---

## Post-Plan Review Results

### Graph Invariants Checker: PASS
| Check | Status |
|-------|--------|
| G1: Validation consistency | PASS |
| G2: Error handling | PASS |
| G3: Service boundary | PASS |
| G4: Schema drift | PASS |
| G5: Security | PASS |
| G6: Import hygiene | PASS |
| P1-P8 | SKIP (no graph/pipeline files) |

### Test/Evals Gatekeeper: PASS
| Check | Status |
|-------|--------|
| T1: Unit tests | PASS (135 tests across 3 files) |
| T2: Syntax verification | PASS (all files compile) |
| T3: Integration tests | PASS (service-layer only, no cross-boundary) |
| T4: No regressions | PASS (0 failures) |
| A1-A5 | SKIP (no agent/pipeline files) |

### Issues Fixed During Review
1. **G6 violation**: 8 unused imports in kling_video_service.py -> removed
2. **G2 violation**: Bare `except Exception: pass` in `set_tracking_context` -> added `logger.debug()`
3. **G2 violation**: Redundant `except (KlingAPIError, Exception)` (6 occurrences) -> simplified to `except Exception`
4. **Missing usage tracking**: `generate_avatar_video` lacked `_track_usage()` call -> added
5. **T1 violation**: 6 methods missing tests (poll_and_complete, download_and_store, etc.) -> added 15 tests

---

## Test Coverage Summary

| Source File | Test File | Tests | Coverage |
|-------------|-----------|-------|----------|
| `kling_models.py` | `test_kling_models.py` | 49 | All enums, validators, bounds, required fields, defaults |
| `video_generation_protocol.py` | `test_video_generation_protocol.py` | 12 | All properties, enum values, runtime_checkable |
| `kling_video_service.py` | `test_kling_video_service.py` | 74 | All public methods, validation, JWT, retry logic, polling, download, queries |
| **Total** | | **135** | |

---

## What's NOT Done Yet (Remaining Plan Items)

### Phase 3 Remaining Work
- [ ] **Pre-sprint checklist items**: Kling developer account, env vars in `.env`, `kling-videos` Supabase bucket, run migration
- [ ] **Smoke tests against live API**: Generate one avatar video, one text-to-video, one image-to-video
- [ ] **Smoke test lip-sync**: identify-face on generated video, then apply lip-sync

### Other Phases (Not Started)
- [ ] **Phase 1**: Instagram Content Research (Apify scraping, outlier detection, media download)
- [ ] **Phase 2**: Content Analysis (Gemini two-pass analysis, structural extraction, shot sheets)
- [ ] **Phase 4**: Video Recreation Pipeline (scene decomposition, audio-first workflow, clip stitching)
- [ ] **Phase 5**: Streamlit UI (50_Instagram_Content, 51_Video_Studio pages)

### Deferred to V2
- Video Extension (only works with v1.x models, our default is v2.6)
- Omni Video (`kling-video-o1`)
- Motion Control endpoint
- Multi-Elements (session-based editing)
- Video Effects (222 effects)
- Custom Voice / TTS via Kling (using ElevenLabs for MVP)
- Callback URL integration (using polling for MVP)
- Static/dynamic masks for image2video
- Storyboard editor UI
- Agent tools for video generation

---

## Environment Setup Required Before Next Phase

```bash
# Add to .env:
KLING_ACCESS_KEY=<from app.klingai.com/global/dev>
KLING_SECRET_KEY=<from app.klingai.com/global/dev>
KLING_MAX_CONCURRENT=3

# Create Supabase storage bucket:
# Name: kling-videos
# Public: false

# Run migration:
# Execute migrations/2026-02-25_kling_generations.sql against Supabase
```

---

## Commit History for This Checkpoint

Single commit containing all Phase 3 files (see git log after push).
