# Workflow Plan: Comic Panel Video System

**Branch**: `feature/comic-panel-video-system`
**Created**: 2025-12-08
**Status**: Phase 1 - Intake

---

## Phase 1: INTAKE

### 1.1 Original Request

Transform static comic grid images into dynamic, cinematic vertical videos (1080×1920) with:
- Ken Burns camera movement across pre-rendered comic panels
- **Integrated audio generation** - system extracts text from comic JSON and generates voiceover using ElevenLabs
- Synchronized voiceover audio (one audio file per panel)
- Atmospheric effects (color grading, vignette, shake, pulse)
- Smooth transitions between panels
- **Parallel audio+video preview workflow** - review both audio AND video per panel together before final render

### 1.2 Clarifying Questions

| # | Question | Answer |
|---|----------|--------|
| 1 | What is the desired end result? | MP4 video (1080×1920) with cinematic camera movement over comic panels, synced with AI-generated voiceover |
| 2 | Who/what triggers this? | Streamlit UI - user uploads comic grid image + JSON |
| 3 | What inputs are required? | Comic grid image (PNG/JPG ~4000×6000), Comic JSON (panel metadata with dialogue text) |
| 4 | What outputs are expected? | Final MP4 video + ability to preview individual panel segments with audio |
| 5 | Error cases to handle? | Layout parsing errors, ElevenLabs API failures, FFmpeg render failures, empty dialogue panels |
| 6 | Should this be chat-routable? | No - UI only for Phase 1 |
| 7 | Existing services to integrate? | ElevenLabsService, AudioProductionService, FFmpegService, Supabase storage |
| 8 | Audio generation? | **Yes** - extract text from comic JSON, generate voiceover via ElevenLabs (integrated, not separate upload) |
| 9 | UI pattern preference? | **Parallel view** - show audio player AND video preview together per panel |

### 1.3 Desired Outcome

**User Story**: As a content creator, I want to upload my comic grid image and JSON, have the system generate voiceover and cinematic video, and review audio+video together per panel before final render.

**Success Criteria**:
- [ ] User can upload comic grid image + JSON in Streamlit UI
- [ ] System parses layout (grid positions) from JSON
- [ ] System extracts dialogue text and generates voiceover per panel (ElevenLabs)
- [ ] System generates camera/effects instructions per panel
- [ ] User sees **parallel view** per panel: audio player + video preview
- [ ] User can regenerate audio (different voice settings) or video (different camera/effects)
- [ ] User can approve each panel before final render
- [ ] Final render concatenates all approved panels into vertical video (1080×1920)
- [ ] Phase 1 effects: color tint, vignette, shake, pulse (FFmpeg-only, no external assets)

### 1.4 Key UI/UX Requirement: Parallel Audio+Video Review

```
┌─────────────────────────────────────────────────────────────────┐
│  Panel 1: TITLE                                                 │
│  ┌──────────────────────┐  ┌─────────────────────────────────┐ │
│  │                      │  │ 🎵 Audio                        │ │
│  │   Video Preview      │  │ ▶ 00:00 ━━━━━━━━━━ 03:24       │ │
│  │   (Ken Burns +       │  │ Voice: Rachel | Speed: 1.0x     │ │
│  │    Effects)          │  │ [🔄 Regenerate Audio]           │ │
│  │                      │  ├─────────────────────────────────┤ │
│  │   [▶ Play Video]     │  │ 📹 Camera & Effects             │ │
│  │                      │  │ Zoom: 1.0 → 1.2                 │ │
│  └──────────────────────┘  │ Effects: golden_glow, vignette  │ │
│                            │ Mood: CELEBRATION               │ │
│                            │ [🔄 Adjust Settings]            │ │
│                            └─────────────────────────────────┘ │
│  Dialogue: "Welcome to Inflation Island..."                    │
│  Duration: 3.4s                                                │
│                                           [✓ Approve Panel]    │
├─────────────────────────────────────────────────────────────────┤
│  Panel 2: SETUP                                                 │
│  ... (same layout) ...                                         │
├─────────────────────────────────────────────────────────────────┤
│                            ...                                  │
├─────────────────────────────────────────────────────────────────┤
│  All Panels Approved: 15/15  ✓                                 │
│  [🎬 Render Final Video]                                       │
└─────────────────────────────────────────────────────────────────┘
```

**Key features:**
- Video and audio preview visible together per panel
- Can play video (with audio) to see sync
- Can regenerate audio independently (new voice/settings)
- Can adjust camera/effects independently
- Approve panel when both audio and video look good
- Final render only enabled when all panels approved

### 1.5 Phase 1 Approval

- [ ] User confirmed requirements are complete
- [ ] No assumptions made - all questions answered

---

## Phase 2: ARCHITECTURE DECISION

### 2.1 Workflow Type Decision

**Chosen**: [x] Python workflow (service-driven with UI control)

**Reasoning**:

| Question | Answer |
|----------|--------|
| Who decides what happens next - AI or user? | **User** - reviews audio+video per panel, regenerates if needed, approves |
| Autonomous or interactive? | **Interactive** - panel-by-panel preview and approval |
| Needs pause/resume capability? | Yes - user can work on project across sessions |
| Complex branching logic? | No - linear with user-controlled iteration per panel |

This is a **user-driven, interactive workflow**. The user controls the flow by:
1. Reviewing audio+video together
2. Regenerating either independently
3. Approving when satisfied

This does NOT need pydantic-graph.

### 2.2 High-Level Flow

```
Step 1: Project Setup
    ├─ Upload comic grid image + JSON
    └─ Parse layout (grid positions from JSON)
        ↓
Step 2: Audio Generation (using existing ElevenLabs integration)
    ├─ Extract dialogue text from each panel in JSON
    ├─ Generate voiceover per panel via ElevenLabsService
    └─ Store audio files with duration metadata
        ↓
Step 3: Direction Generation (per panel)
    ├─ Generate camera instructions (rule-based Phase 1)
    ├─ Select effects based on mood (from comic JSON color_coding)
    └─ Calculate durations from audio
        ↓
Step 4: Parallel Review & Approval (INTERACTIVE)
    ├─ User sees audio player + video preview per panel
    ├─ User can:
    │   ├─ Play video with audio to check sync
    │   ├─ Regenerate audio (different voice/settings)
    │   └─ Adjust camera/effects and regenerate video preview
    └─ Approve panel when satisfied
        ↓
Step 5: Final Render
    ├─ Concatenate all approved panel video segments
    ├─ Mix approved audio track
    └─ Output final MP4
        ↓
Result: Vertical video (1080×1920) with synced voiceover
```

### 2.3 Service Architecture

**4 Core Services** (consolidated for Phase 1):

| Service | Purpose | Integrates With |
|---------|---------|-----------------|
| **ComicVideoService** | Project CRUD, layout parsing, orchestration | Supabase, all other services |
| **ComicAudioService** | Audio generation, file management, duration | ElevenLabsService, FFmpegService |
| **ComicDirectorService** | Camera/effects instruction generation | - |
| **ComicRenderService** | FFmpeg video rendering (panels + final) | FFmpegService |

**Existing Services to Leverage**:
| Service | How Used |
|---------|----------|
| ElevenLabsService | Text-to-speech for voiceover generation |
| FFmpegService | Get audio duration, base for video rendering |
| AudioProductionService | Reference for storage patterns, possibly reuse upload methods |

### 2.4 Phase 2 Approval

- [ ] User confirmed architecture approach

---

## Phase 3: INVENTORY & GAP ANALYSIS

### 3.1 Existing Components to Reuse

| Component | Type | Location | How We'll Use It |
|-----------|------|----------|------------------|
| **ElevenLabsService** | Service | `services/elevenlabs_service.py` | `generate_speech()` for voiceover. Already handles voice profiles, settings, API calls |
| **FFmpegService** | Service | `services/ffmpeg_service.py` | `get_duration_ms()` for audio timing. Will extend for video (zoompan, filters) |
| **AudioProductionService** | Service | `services/audio_production_service.py` | Reference pattern. Reuse `upload_audio()`, `get_audio_url()` storage methods |
| **audio_models.py** | Models | `services/audio_models.py` | Reference for VoiceSettings, Character enum patterns |
| **Supabase storage** | Integration | Via services | Bucket pattern: `audio-production/{session_id}/` |

### 3.2 Existing Service Details

**ElevenLabsService key methods:**
```python
generate_speech(text, voice_id, settings, output_path) -> Dict
generate_beat_audio(beat, output_dir, session_id) -> AudioTake
get_voice_profile(character) -> CharacterVoiceProfile
```

**FFmpegService key methods:**
```python
get_duration_ms(audio_path) -> int  # Reuse directly
concatenate_with_pauses(segments, output_path) -> bool  # Useful for final audio mix
# NEED TO ADD: zoompan filters, video rendering
```

**AudioProductionService patterns to follow:**
- Storage bucket pattern: `STORAGE_BUCKET = "audio-production"`
- Async Supabase calls: `await asyncio.to_thread(lambda: ...)`
- Session-based file organization: `{session_id}/{filename}`

### 3.3 Database Evaluation

**Existing Tables (no naming collisions):**
- Searched all SQL migrations - no `comic_*` tables exist
- Related tables for reference: `audio_production_sessions`, `audio_takes`

**New Tables Needed:**

| Table | Purpose | Similar To |
|-------|---------|------------|
| `comic_video_projects` | Project metadata, status, layout | `audio_production_sessions` |
| `comic_panel_audio` | Audio per panel (URL, duration, voice) | `audio_takes` |
| `comic_panel_instructions` | Camera/effects per panel | New (JSONB) |
| `comic_render_jobs` | Render queue, progress | `pipeline_runs` pattern |

### 3.4 New Components to Build

| Component | Type | Purpose | Extends/Uses |
|-----------|------|---------|--------------|
| **models.py** | Models | All Pydantic models (enums, data classes) | Pattern from `audio_models.py` |
| **ComicVideoService** | Service | Project CRUD, layout parsing, orchestration | Pattern from `AudioProductionService` |
| **ComicAudioService** | Service | Audio generation, wraps ElevenLabsService | Uses `ElevenLabsService.generate_speech()` |
| **ComicDirectorService** | Service | Camera/effects instruction generation | New (rule-based Phase 1) |
| **ComicRenderService** | Service | FFmpeg video rendering | Extends `FFmpegService` patterns |
| **Migration** | SQL | New tables | IF NOT EXISTS guards |
| **Streamlit UI** | UI | Panel preview workflow | Pattern from audio UI |

### 3.5 File Structure

```
viraltracker/
├── services/
│   └── comic_video/
│       ├── __init__.py
│       ├── models.py                  # PanelMood, EffectType, ComicLayout, etc.
│       ├── comic_video_service.py     # Project CRUD, layout parsing
│       ├── comic_audio_service.py     # Wraps ElevenLabsService for panel audio
│       ├── comic_director_service.py  # Camera/effects instructions
│       └── comic_render_service.py    # FFmpeg video rendering
├── ui/
│   └── pages/
│       └── 08_🎬_Comic_Video.py       # Streamlit UI
└── sql/
    └── 2025-12-08_comic_video_tables.sql
```

### 3.6 Integration Points

```
┌─────────────────────────────────────────────────────────────────┐
│                     ComicVideoService                           │
│  (orchestrates all other services, handles project lifecycle)   │
└─────────────────┬───────────────────────────────────────────────┘
                  │
    ┌─────────────┼─────────────┬─────────────────┐
    ▼             ▼             ▼                 ▼
┌─────────┐ ┌───────────┐ ┌───────────┐ ┌─────────────────┐
│ Comic   │ │ Comic     │ │ Comic     │ │ Supabase        │
│ Audio   │ │ Director  │ │ Render    │ │ Storage         │
│ Service │ │ Service   │ │ Service   │ │ (via parent)    │
└────┬────┘ └───────────┘ └─────┬─────┘ └─────────────────┘
     │                          │
     ▼                          ▼
┌─────────────┐           ┌─────────────┐
│ ElevenLabs  │           │ FFmpeg      │
│ Service     │           │ Service     │
│ (existing)  │           │ (existing)  │
└─────────────┘           └─────────────┘
```

### 3.7 Phase 3 Approval

- [ ] User confirmed component list
- [ ] Database schema approved (4 new tables)
- [ ] Integration approach approved

---

## Phase 4: BUILD

### 4.1 Build Order

1. [ ] **models.py** - All Pydantic models (enums, data classes)
2. [ ] **Database migration** - New tables
3. [ ] **comic_audio_service.py** - Audio generation, duration extraction
4. [ ] **comic_director_service.py** - Camera/effects instruction generation
5. [ ] **comic_render_service.py** - FFmpeg video rendering
6. [ ] **comic_video_service.py** - Main orchestration service
7. [ ] **Streamlit UI page** - Parallel audio+video preview workflow

### 4.2 Component Details

*(To be filled in during Phase 4 execution)*

---

## Phase 5: INTEGRATION & TEST

### 5.1 Shared Files to Modify

| File | Change |
|------|--------|
| `services/__init__.py` | Export comic_video services |
| `ui/pages/` | Add Comic Video page |
| `agent/dependencies.py` | Add services (for future chat routing) |

### 5.2 Testing Plan

1. **Unit tests** for each service method
2. **Integration test**: Upload sample comic JSON + grid, generate audio, render preview
3. **UI test**: Full workflow through Streamlit

---

## Phase 6: MERGE & CLEANUP

*(To be filled in during Phase 6)*

---

## Questions Log

| Date | Question | Answer |
|------|----------|--------|
| 2025-12-08 | Existing services? | ElevenLabsService, AudioProductionService, FFmpegService exist |
| 2025-12-08 | Upload flow? | User uploads comic grid image + JSON |
| 2025-12-08 | Chat routing? | UI only for Phase 1 |
| 2025-12-08 | Audio generation? | Yes - integrated, extract text from JSON, generate via ElevenLabs |
| 2025-12-08 | UI pattern? | Parallel view - audio player + video preview together per panel |

---

## Change Log

| Date | Phase | Change |
|------|-------|--------|
| 2025-12-08 | 1 | Initial plan created from user's comprehensive spec |
| 2025-12-08 | 1 | Added integrated audio generation (ElevenLabs) |
| 2025-12-08 | 1 | Added parallel audio+video review UI requirement |
| 2025-12-08 | 2 | Architecture decision: Python workflow (user-driven) |
| 2025-12-08 | 2 | Consolidated to 4 services |
| 2025-12-08 | 3 | Component inventory and gap analysis |
