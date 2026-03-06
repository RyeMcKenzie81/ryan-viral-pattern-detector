# Checkpoint 15: Clip-Based Lip Sync Tool + Manual Creator Project History

**Date**: 2026-03-05
**Branch**: `feat/chainlit-agent-chat`
**Status**: Implemented, pending deployment testing

---

## Summary

Two features added to the Video Studio:

1. **Clip-Based Lip Sync Tool** (Tab 5) - Upload a multi-face video, AI detects faces, clips per face range, lip-syncs each independently via Kling API, reassembles into final video.
2. **Manual Creator Project History** - Persistent projects with auto-save so work survives page refresh. Save/Load/New/Delete with project browser.

---

## Feature 1: Clip-Based Lip Sync Tool

### Problem

Users had a working script (`scripts/clip_lip_sync.py`) for multi-face lip-sync, but it was CLI-only with no UI, no persistence, and no progress tracking.

### Solution

Productized as a proper service + UI tab with:
- `LipSyncService` with granular methods for UI-driven progress
- 5-step processing pipeline: Load -> Normalize -> Detect Faces -> Process Clips -> Reassemble
- Per-clip face detection and lip-sync via Kling API
- Edge case handling: 0 faces, short clips, partial failures
- `lip_sync_jobs` DB table for orchestration tracking
- Individual Kling API generations linked back via `lip_sync_job_id` FK

### Architecture

```
UI (st.status)                    LipSyncService              KlingVideoService
     |                                  |                            |
     |-- create_job() ----------------->|                            |
     |-- normalize_video() ------------>|-- FFmpegService            |
     |-- detect_faces() --------------->|-- identify_faces() ------->|
     |-- plan_clips() ----------------->| (pure logic)               |
     |-- process_face_clip() x N ------>|-- clip_video/audio         |
     |                                  |-- upload clip              |
     |                                  |-- identify_faces() ------->|
     |                                  |-- apply_lip_sync() ------->|
     |                                  |-- poll_and_complete() ---->|
     |-- extract_gap_clip() x N ------->|-- clip_video, upload       |
     |-- reassemble() ----------------->|-- download all, concat     |
```

### Edge Cases Handled

| Scenario | Behavior |
|----------|----------|
| 0 faces detected | Returns original video with warning |
| Clip < 2 seconds | Padding extended symmetrically to meet Kling minimum |
| Per-clip failure | Original (un-synced) clip used as fallback |
| All clips fail | Job status = `failed`, original video as fallback |
| Single face covering full video | Normal clip processing (no special path needed since clipping works fine for 1 clip) |

---

## Feature 2: Manual Creator Project History

### Problem

All Manual Creator state was in Streamlit session state. Closing the tab or refreshing the browser lost all work (scenes, frames, generations).

### Solution

- `manual_video_projects` DB table stores full project state as JSONB
- **Strip on save**: Remove `signed_url` from frame gallery items (they expire in 1h)
- **Refresh on load**: Re-generate signed URLs from `storage_path` for all frames
- **Auto-save** at 6 completion points (frame gen, scene gen, batch gen, stitch, plus inline quick frame)
- **Project header UI**: Name input, Save Draft, New, Load buttons
- **Project browser**: Lists projects filtered by brand, sorted by most recently updated
- **"New" auto-saves** current project before clearing state

### Auto-Save Trigger Points (7 total)

| # | Trigger | Context |
|---|---------|---------|
| 1 | "Save Draft" button | Explicit save |
| 2 | "New" button | Auto-save before clearing |
| 3 | After "Generate Frame" | Main frame generation |
| 4 | After inline "Add Frame" | Quick frame per scene |
| 5 | After single scene generation | Individual scene |
| 6 | After "Generate All" batch | All draft scenes |
| 7 | After "Stitch Clips" | Final concatenation |

---

## Files Changed

| File | Action | Description |
|------|--------|-------------|
| `migrations/2026-03-05_lip_sync_and_projects.sql` | **NEW** | Both tables, indexes, RLS, triggers, FK |
| `viraltracker/services/ffmpeg_service.py` | **MODIFIED** | Added 5 methods + 2 private helpers; updated `normalize_video_for_kling()` signature |
| `viraltracker/services/lip_sync_service.py` | **NEW** | Full orchestration service (~400 lines) |
| `viraltracker/services/manual_video_service.py` | **MODIFIED** | Added 4 project persistence methods (~170 lines) |
| `viraltracker/ui/pages/51_🎬_Video_Studio.py` | **MODIFIED** | 5th tab, project header/browser, auto-save, bridge button (~350 lines added) |

---

## Database Changes

### `lip_sync_jobs` Table

```sql
CREATE TABLE lip_sync_jobs (
    id UUID PRIMARY KEY,
    organization_id UUID NOT NULL REFERENCES organizations(id),
    brand_id UUID NOT NULL REFERENCES brands(id),
    original_filename TEXT,
    video_duration_ms INTEGER,
    video_resolution TEXT,
    face_count INTEGER,
    face_data JSONB,
    clip_plan JSONB,
    face_clip_results JSONB,
    gap_clip_results JSONB,
    final_video_path TEXT,
    final_video_duration_ms INTEGER,
    status TEXT NOT NULL DEFAULT 'pending',
    error_message TEXT,
    original_audio_volume FLOAT DEFAULT 0.0,
    padding_ms INTEGER DEFAULT 500,
    total_cost_usd FLOAT,
    created_at TIMESTAMPTZ DEFAULT NOW(),
    updated_at TIMESTAMPTZ DEFAULT NOW(),
    completed_at TIMESTAMPTZ,
    CONSTRAINT status_check CHECK (status IN ('pending','normalizing','detecting_faces','processing_clips','reassembling','completed','failed'))
);
```

- Indexes: `brand_id+created_at DESC`, `organization_id`, `status`
- RLS: Enabled with open policy for authenticated users
- Trigger: `update_updated_at_column()` on updates
- FK: `kling_video_generations.lip_sync_job_id` added referencing this table

### `manual_video_projects` Table

```sql
CREATE TABLE manual_video_projects (
    id UUID PRIMARY KEY,
    organization_id UUID NOT NULL REFERENCES organizations(id),
    brand_id UUID NOT NULL REFERENCES brands(id),
    name TEXT NOT NULL DEFAULT 'Untitled Project',
    status TEXT NOT NULL DEFAULT 'draft',
    avatar_id UUID REFERENCES brand_avatars(id) ON DELETE SET NULL,
    quality_mode TEXT DEFAULT 'pro',
    aspect_ratio TEXT DEFAULT '9:16',
    frame_gallery JSONB DEFAULT '[]'::jsonb,
    scenes JSONB DEFAULT '[]'::jsonb,
    final_video_path TEXT,
    final_video_duration_sec FLOAT,
    total_generation_cost_usd FLOAT DEFAULT 0.0,
    scene_count INTEGER DEFAULT 0,
    created_at TIMESTAMPTZ DEFAULT now(),
    updated_at TIMESTAMPTZ DEFAULT now(),
    CONSTRAINT status_check CHECK (status IN ('draft','in_progress','completed'))
);
```

- Indexes: `brand_id+updated_at DESC`, `organization_id`, `status`
- RLS: Enabled with open policy for authenticated users
- Trigger: `update_updated_at_column()` on updates
- ON DELETE SET NULL for `avatar_id` (handles deleted avatars)

---

## New Service Methods

### FFmpegService (modified)

| Method | Type | Purpose |
|--------|------|---------|
| `probe_video_info(video_path)` | sync | Returns `{width, height, duration_ms, has_audio, codec_name}` |
| `clip_video(video_path, start_ms, end_ms, output_path)` | sync | Frame-accurate re-encode clip |
| `clip_audio(audio_path, start_ms, end_ms, output_path)` | sync | Audio segment extraction |
| `concatenate_video_files(input_paths, output_path)` | sync | Concat filter with SAR normalization |
| `validate_for_lip_sync(video_path)` | sync | Checks duration 2-60s, resolution, file size <= 100MB |
| `normalize_video_for_kling(video_bytes, max_duration_seconds=8.0)` | sync | Now accepts `None` to skip duration cap |
| `_file_has_audio(video_path)` | private | Sync audio stream check |
| `_add_silent_audio_sync(video_path)` | private | Sync silent audio addition |

### LipSyncService (new)

| Method | Type | Purpose |
|--------|------|---------|
| `create_job(org_id, brand_id, filename, video_info)` | async | Create DB record |
| `update_job(job_id, **kwargs)` | async | Update job fields |
| `normalize_video(video_bytes)` | async | Normalize via FFmpegService (no duration cap) |
| `detect_faces(org_id, brand_id, video_url)` | async | Call Kling identify_faces |
| `plan_clips(face_data, video_duration_ms, padding_ms)` | sync | Pure logic: face clips + gap clips |
| `process_face_clip(...)` | async | Full pipeline for ONE face clip |
| `extract_gap_clip(...)` | async | Extract and upload ONE gap clip |
| `reassemble(...)` | async | Sort, download, concat, upload final |
| `list_jobs(org_id, brand_id, limit)` | async | List past jobs |

### ManualVideoService (modified)

| Method | Type | Purpose |
|--------|------|---------|
| `save_project(...)` | sync | Upsert project; strips signed_urls, auto-computes status |
| `list_projects(brand_id, org_id, limit)` | sync | List by updated_at DESC |
| `load_project(project_id)` | sync | Load and re-sign all URLs; detect deleted avatars |
| `delete_project(project_id)` | sync | Hard delete (storage files remain) |

---

## UI Changes

### Tab Bar (5 tabs)

```python
tab_candidates, tab_recreation, tab_history, tab_manual, tab_lipsync = st.tabs([
    "Candidates", "Recreation", "History", "Manual Creator", "Lip Sync"
])
```

### Manual Creator - Project Header

```
[Project Name text_input]  [Save Draft] [New] [Load]
Last saved: 2 min ago
```

### Manual Creator - Project Browser (collapsible)

Lists past projects with Load/Delete buttons, filtered by brand.

### Manual Creator - Bridge Button

"Lip-Sync This Video" button in final video section sets `vs_ls_preloaded_path` and instructs user to switch to Lip Sync tab.

### Lip Sync Tab Layout

```
Upload Section
  Video uploader + optional audio uploader
  Audio preset selectbox (Mute/Blend/Keep)
  [Advanced Settings] expander with padding slider
  [Process Video] button

Progress Section (during processing)
  st.status(expanded=True) with per-step log and progress bar
  Warning about processing time

Results Section (after completion)
  Final video player (hero) + download button
  [Individual Segments] expander
  [Processing Summary] expander

Past Jobs (collapsible)
  Previous lip-sync jobs for this brand
```

### New Session State Keys

| Key | Purpose |
|-----|---------|
| `vs_manual_project_id` | Current project UUID (None for unsaved) |
| `vs_manual_project_name` | Editable project title |
| `vs_manual_show_history` | Toggle for project browser |
| `vs_manual_last_saved` | Timestamp of last save |
| `vs_manual_avatar_id_resolved` | Resolved avatar ID for auto-save |
| `vs_ls_video_bytes` | Uploaded video bytes |
| `vs_ls_audio_bytes` | Optional replacement audio bytes |
| `vs_ls_job_id` | Current lip-sync job UUID |
| `vs_ls_results` | Completed lip-sync results |
| `vs_ls_preloaded_path` | Bridge from Manual Creator |

---

## Multi-Tenancy Compliance

| Check | Status |
|-------|--------|
| Data isolation (org_id) | Both tables have `organization_id` FK and org-filtered queries |
| Feature gating | Uses existing `video_tools` feature key |
| RLS | Enabled on both tables |
| Superuser handling | org_id="all" resolution already handled at page level |

---

## Syntax Verification

```
python3 -m py_compile viraltracker/services/ffmpeg_service.py          # PASS
python3 -m py_compile viraltracker/services/lip_sync_service.py        # PASS
python3 -m py_compile viraltracker/services/manual_video_service.py    # PASS
python3 -m py_compile viraltracker/ui/pages/51_🎬_Video_Studio.py     # PASS
```

---

## Known Limitations / Tech Debt

1. **No usage tracking** for lip-sync jobs (Kling API calls are tracked individually via KlingVideoService, but no aggregate tracking at the lip-sync job level)
2. **No cost estimation** displayed in lip-sync UI (costs flow through KlingVideoService per-generation)
3. **Project browser** doesn't paginate (limited to 20 most recent)
4. **Auto-save** doesn't handle concurrent edits if user has multiple tabs open
5. **Lip-sync storage** cleanup not automated (old clips remain in Supabase)
