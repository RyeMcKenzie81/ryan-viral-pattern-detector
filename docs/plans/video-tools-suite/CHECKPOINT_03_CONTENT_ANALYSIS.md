# Video Tools Suite - Phase 2: Content Analysis Checkpoint

**Date:** 2026-02-25
**Branch:** `feat/chainlit-agent-chat` (worktree: `worktree-feat/chainlit-agent-chat`)
**Plan:** `docs/plans/video-tools-suite/PLAN.md` (Phase 2 section)
**Previous Checkpoints:** `CHECKPOINT_01`, `CHECKPOINT_02`, `CHECKPOINT_02B_CONTEXT_HANDOFF`

---

## Phase 2 Deliverables (DONE)

### 1. Database Migration: `migrations/2026-02-25_video_analysis_extensions.sql`
- ALTER `ad_video_analysis`: added `source_type` (default 'meta_ad'), `source_post_id` (FK to posts), `production_storyboard` (JSONB), `people_detected`, `has_talking_head`, `eval_scores` (JSONB)
- Made `meta_ad_id` nullable for Instagram-sourced analyses
- Added partial unique index for Instagram content (`source_post_id, prompt_version, input_hash`)
- CREATE `instagram_image_analysis` table (immutable versioned rows)
- **STATUS: Migration file created. Needs to be run via Supabase SQL Editor.**

### 2. Service: `viraltracker/services/instagram_analysis_service.py` (~580 lines)
- **Pass 1 (Gemini Flash `gemini-3-flash-preview`)**: Structural extraction
  - Full transcript with timestamps
  - Text overlays with position/style/confidence
  - Storyboard with scene descriptions
  - Hook analysis (spoken + visual + type)
  - People detection (count, has_talking_head boolean)
  - Production quality and format type classification
- **Pass 2 (Gemini Pro `gemini-3.1-pro-preview`)**: Production shot sheet
  - Per-beat: camera_shot_type, camera_movement, camera_angle, duration_sec
  - subject_action (continuous tense for VEO prompts)
  - subject_emotion, subject_framing, lighting, background
  - audio_type, transition_to_next, pacing
- **VA-1 through VA-8 automated consistency checks** (run on every analysis)
  - VA-1: Duration match vs post metadata (abs diff <= 2s)
  - VA-2: Transcript non-empty (>20 chars, partial pass for animation)
  - VA-3: Storyboard coverage (last_ts >= 0.7 * duration)
  - VA-4: Timestamp monotonicity (no reversals)
  - VA-5: Segment coverage (sum segments / duration >= 0.6)
  - VA-6: Hook window (hook fields present when transcript exists)
  - VA-7: JSON completeness (all required keys present)
  - VA-8: Overlay coherence (empty overlays = 0 confidence)
  - Overall score = mean of all checks; flag for review if < 0.6
- **Key methods**: `analyze_video()`, `analyze_image()`, `analyze_carousel()`, `deep_production_analysis()`, `batch_analyze_outliers()`, `get_analysis()`, `get_analyses_for_brand()`
- Follows existing `VideoAnalysisService` pattern: Gemini Files API upload, temp file cleanup, input hashing, immutable versioned rows, duplicate key handling

### 3. UI: Analysis tab added to `viraltracker/ui/pages/50_📸_Instagram_Content.py`
- 4th tab "Analysis" added to existing page
- "Analyze All Outliers" batch button (runs Pass 1 on all outlier media)
- Per-post "Analyze Video" / "Analyze Images" buttons
- Analysis results display with expandable sections:
  - Transcript (full + segments)
  - Hook analysis (spoken, overlay, visual, type, effectiveness signals)
  - Storyboard timeline
  - Production shot sheet (Pass 2)
  - Eval scores (VA-1 through VA-8 breakdown)
- "Deep Analysis" button per analysis (triggers Pass 2 with Pro model)
- Status filtering (ok / validation_failed / error)
- Talking-head detection flag per analysis
- Async helper `_run_async()` for calling async service methods from sync Streamlit

### 4. Tests: `tests/test_instagram_analysis_service.py` (45 tests, all passing)
- `TestComputeInputHash` (5 tests): hash computation, determinism, different inputs
- `TestParseJsonResponse` (7 tests): plain JSON, code blocks, edge cases
- `TestEvalChecks` (22 tests): comprehensive VA-1 through VA-8 checks
- `TestEvalScores` (2 tests): dataclass serialization
- `TestGetAnalysis` (3 tests): video/image fallback, not found
- `TestInternalHelpers` (4 tests): media record lookup, storage download
- `TestConstants` (2 tests): model and version string verification

---

## Files Created/Modified

| File | Action | Lines |
|------|--------|-------|
| `migrations/2026-02-25_video_analysis_extensions.sql` | Created | ~80 |
| `viraltracker/services/instagram_analysis_service.py` | Created | ~580 |
| `viraltracker/ui/pages/50_📸_Instagram_Content.py` | Modified | +250 |
| `tests/test_instagram_analysis_service.py` | Created | ~350 |
| `docs/plans/video-tools-suite/CHECKPOINT_03_CONTENT_ANALYSIS.md` | Created | This file |

---

## Test Results

```
tests/test_instagram_analysis_service.py ............................................. 45 passed
tests/test_instagram_content_service.py ...................................... 37 passed
tests/test_kling_video_service.py ............................................ 83 passed
Total: 165 tests passing
```

---

## Migration Status

**Needs manual execution via Supabase SQL Editor:**
- `migrations/2026-02-25_video_analysis_extensions.sql`

The migration adds columns to `ad_video_analysis` and creates `instagram_image_analysis`. All ALTERs use `IF NOT EXISTS` so it's safe to re-run.

---

## Architecture Notes

- Service follows thin-tools pattern (business logic in service, not UI)
- Multi-tenant: all queries filter by `organization_id`
- Brand resolution: `post -> account -> instagram_watched_accounts -> brand_id`
- Immutable rows: new analyses create new rows, existing never overwritten
- Input hashing: `SHA256(storage_path:file_size)` for change detection
- Duplicate handling: catches `23505` (unique violation) and returns existing record

---

## Next Up: Phase 4 - Video Recreation Pipeline

### What needs to be built:
1. **Migration**: `migrations/2026-02-25_video_candidates.sql` - Recreation candidates table
2. **Service**: `viraltracker/services/video_recreation_service.py` - Scoring, storyboard adaptation, audio-first generation, clip stitching
3. **End-to-end test**: scrape -> analyze -> score -> adapt -> generate

### Then Phase 5: Video Studio UI
4. **UI**: `viraltracker/ui/pages/51_🎬_Video_Studio.py` - Candidates, Recreation, History tabs

---

## Environment State
- Push command: `git push origin worktree-feat/chainlit-agent-chat:feat/chainlit-agent-chat`
- All 165 tests passing (83 Phase 3 + 37 Phase 1 + 45 Phase 2)
- Migration file ready for manual execution
