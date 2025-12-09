# Workflow Plan: Comic Panel Video System

**Branch**: `feature/comic-panel-video-system`
**Created**: 2025-12-08
**Status**: Phase 5 Complete - Planning Phase 5.5 (Manual Adjustments) & Phase 6 (Particles/SFX)

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

## Phase 4: BUILD ✅ COMPLETE

### 4.1 Build Order (All Complete)

1. [x] **models.py** - All Pydantic models (enums, data classes)
2. [x] **Database migration** - 4 new tables
3. [x] **comic_audio_service.py** - Audio generation via ElevenLabs
4. [x] **comic_director_service.py** - Camera/effects instruction generation
5. [x] **comic_render_service.py** - FFmpeg video rendering
6. [x] **comic_video_service.py** - Main orchestration service
7. [x] **Streamlit UI page** - Parallel audio+video preview workflow

### 4.2 Component Details

#### Checkpoint 1: models.py
- **Commit**: `72b9e49`
- PanelMood, EffectType, TransitionType, CameraEasing enums
- ComicLayout, PanelBounds, FocusPoint data classes
- PanelCamera, PanelEffects, PanelTransition cinematography models
- PanelInstruction, PanelAudio, ComicVideoProject main models
- MOOD_EFFECT_PRESETS for Phase 1 FFmpeg effects

#### Checkpoint 2: Database Migration
- **Commit**: `721df23`
- **File**: `sql/2025-12-08_comic_video_tables.sql`
- comic_video_projects, comic_panel_audio, comic_panel_instructions, comic_render_jobs

#### Checkpoint 3: ComicAudioService
- **Commit**: `ecef6f4`
- Wraps ElevenLabsService for comic TTS
- extract_panel_text(), generate_panel_audio(), generate_all_audio()
- Supabase storage integration

#### Checkpoint 4: ComicDirectorService
- **Commit**: `402ee53`
- parse_layout_from_json(), calculate_panel_bounds()
- infer_panel_mood() from content and color_coding
- generate_panel_instruction() with camera, effects, transition
- Rule-based cinematography (Phase 1)

#### Checkpoint 5: ComicRenderService
- **Commit**: `26ef09a`
- render_panel_preview(), render_full_video()
- Ken Burns zoompan filter builder
- FFmpeg effect filters (vignette, color tint, shake, pulse)
- Segment-based rendering, audio mixing

#### Checkpoint 6: ComicVideoService
- **Commit**: `ff9477c`
- Main orchestration service
- Project CRUD, layout parsing, audio/instruction generation
- Panel preview rendering, approval workflow
- Final video rendering

#### Checkpoint 7: Streamlit UI
- **Commit**: `b3ed787`
- **File**: `ui/pages/20_🎬_Comic_Video.py`
- Upload step, audio generation step, parallel review step
- Per-panel audio+video preview, approval, final render

---

## Phase 5: INTEGRATION & TEST ✅ COMPLETE

### 5.1 Real-World Testing

Tested with actual comic: "Inflation Explained by Raccoons" (15 panels, 4-4-4-3 grid)

#### JSON Format Adaptations

The real comic JSON differed from initial spec. Services updated to handle:

| Field | Expected | Actual | Fix |
|-------|----------|--------|-----|
| TTS text | `dialogue` | `script_for_audio` | Priority order in `extract_panel_text()` |
| Layout | `grid: "4x4"` | `grid_structure: [{row:1, panels:[1,2,3,4]}...]` | Added `_parse_grid_structure()` |
| Mood | Inferred from keywords | Explicit `mood` field | Priority check in `infer_panel_mood()` |
| Colors | `panel_1_2: {...}` | `panel_1: {...}`, `panels_5_6_7: {...}` | Updated color_coding parser |

#### Ken Burns Zoom Fix

**Problem**: Camera showed entire canvas instead of zooming into individual panels.

**Root Cause**: Zoom calculation was inverted (`base_zoom / camera.zoom` instead of multiplying).

**Fix** (`comic_render_service.py`):
```python
# Calculate zoom to fill output with single panel
panel_width = canvas_w / layout.grid_cols
panel_zoom = (canvas_w / panel_width) * 0.85  # = grid_cols * 0.85

z_start = panel_zoom * camera.start_zoom  # e.g., 4 * 0.85 * 1.0 = 3.4x
z_end = panel_zoom * camera.end_zoom      # e.g., 4 * 0.85 * 1.1 = 3.74x
```

**Result**: 4-column grid now zooms ~3.4x to show individual panel with slight margin.

#### Panel-to-Panel Transitions

**Problem**: No camera panning between panels after audio finishes.

**Solution**: Two-phase animation in zoompan filter:
1. **Content phase**: Ken Burns within current panel (duration = audio length)
2. **Transition phase**: Animate camera to next panel center

**Implementation** (`comic_render_service.py`):
```python
def _build_zoompan_with_transition(
    self, camera, next_camera, transition, layout,
    content_frames, transition_frames, output_size, fps
) -> str:
    # Conditional expressions: if(lt(on,content_frames), content_expr, transition_expr)
    z_expr = f"'if(lt(on,{content_frames})," \
             f"{curr_z_start}+({curr_z_end-curr_z_start})*on/{content_frames}," \
             f"{curr_z_end}+({next_z_start-curr_z_end})*(on-{content_frames})/{transition_frames})'"
    # Similar for x_expr, y_expr...
```

#### Bug Fixes

| Issue | Cause | Fix |
|-------|-------|-----|
| Wrong panel targeting | Estimated image dimensions | Added `_get_image_dimensions()` using ffprobe |
| Duplicate concat paths | Relative paths in concat list | Use `path.resolve()` for absolute paths |
| 409 Duplicate upload error | Re-uploading existing file | Catch error, delete existing, re-upload |

### 5.2 Test Results

All 5 integration tests pass (`scripts/test_comic_video_real.py`):
- ✅ Parse layout from real JSON (grid_structure format)
- ✅ Extract panel texts (script_for_audio field)
- ✅ Infer panel moods (explicit mood field)
- ✅ Generate panel instructions
- ✅ Calculate panel bounds

### 5.3 Files Modified in Phase 5

| File | Changes |
|------|---------|
| `comic_audio_service.py` | Priority: `script_for_audio` → `dialogue` → legacy |
| `comic_director_service.py` | `_parse_grid_structure()`, explicit mood handling, color_coding parser |
| `comic_render_service.py` | Image dimension detection, zoom calculation fix, transition rendering, path fixes, duplicate handling |
| `test_comic_video_real.py` | Created with real comic JSON data |

---

## Phase 5.5: MANUAL PANEL ADJUSTMENTS (Planned)

### 5.5.1 Problem Statement

Auto-generated effects aren't always appropriate:
- Vignette can obscure panel text
- Wrong mood inference leads to inappropriate effects
- Ken Burns direction may not suit panel composition

### 5.5.2 Requirements

Users need ability to:
1. **Override camera settings** per panel (zoom level, start/end position, easing)
2. **Toggle individual effects** on/off (vignette, color tint, shake, pulse)
3. **Adjust effect intensity** (0-100% slider)
4. **Preview changes** before committing
5. **Bulk actions** for efficiency:
   - Render All Panels - generate video previews for all panels at once
   - Approve All Panels - mark all panels as approved in one click

### 5.5.3 UI Design

#### Global Actions Bar (Top of Page)

```
┌─────────────────────────────────────────────────────────────────┐
│  Comic Video: "Inflation Explained by Raccoons"                 │
│  15 panels | 4-4-4-3 grid | Audio: ✓ Generated                  │
├─────────────────────────────────────────────────────────────────┤
│  Output Format: [9:16 ▼]  ←── Aspect ratio selector             │
│                                                                 │
│  [🎬 Render All Panels]  [✓ Approve All]  [🎥 Render Final]    │
│                                                                 │
│  Progress: ████████░░░░░░░░ 8/15 rendered | 5/15 approved      │
└─────────────────────────────────────────────────────────────────┘
```

#### Output Aspect Ratios

| Ratio | Resolution | Use Case |
|-------|------------|----------|
| **9:16** | 1080×1920 | TikTok, Instagram Reels, YouTube Shorts (default) |
| **16:9** | 1920×1080 | YouTube, Twitter/X, LinkedIn |
| **1:1** | 1080×1080 | Instagram Feed, Facebook |
| **4:5** | 1080×1350 | Instagram Feed (portrait) |

**Behavior:**
- Changing aspect ratio re-renders all panel previews
- Ken Burns zoom calculations adjust to new frame dimensions
- Comic grid image is cropped/positioned to fit new aspect ratio
- Final video uses selected ratio

**Render All Panels:**
- Queues all panels for video preview rendering
- Shows progress bar with panel count
- Renders sequentially (FFmpeg resource limits)
- Can be cancelled mid-way
- Skips panels that already have renders (unless "Force Re-render" checked)

**Approve All Panels:**
- Marks all panels as approved in one click
- Only enabled when all panels have been rendered
- Confirmation dialog: "Approve all 15 panels?"
- Enables "Render Final Video" button

#### Per-Panel Controls

```
┌─────────────────────────────────────────────────────────────────┐
│  Panel 3: "The Fed Showed Up"                          [✓ ☐]   │
│  ┌──────────────────────┐  ┌─────────────────────────────────┐ │
│  │                      │  │ 🎥 Camera Settings              │ │
│  │   Video Preview      │  │ Start Zoom: [1.0] ─────○─── 2.0 │ │
│  │                      │  │ End Zoom:   [1.1] ─────○─── 2.0 │ │
│  │   [▶ Play]           │  │ Easing: [Ease In-Out ▼]         │ │
│  │                      │  │ Focus: [Center ▼] Auto/Custom   │ │
│  └──────────────────────┘  ├─────────────────────────────────┤ │
│                            │ ✨ Effects                       │ │
│  Current Mood: DRAMATIC    │ ☑ Vignette      [████░░] 70%    │ │
│  [Override: ▼ Select]      │ ☐ Color Tint    [██░░░░] 30%    │ │
│                            │ ☐ Shake         [░░░░░░] 0%     │ │
│                            │ ☐ Pulse         [░░░░░░] 0%     │ │
│                            │ ☑ Golden Glow   [███░░░] 50%    │ │
│                            ├─────────────────────────────────┤ │
│                            │ [🔄 Reset to Auto] [💾 Apply]   │ │
│                            └─────────────────────────────────┘ │
└─────────────────────────────────────────────────────────────────┘
```

Note: `[✓ ☐]` checkbox in top-right for individual panel approval

### 5.5.4 Data Model Changes

```python
from enum import Enum

class AspectRatio(str, Enum):
    """Supported output aspect ratios."""
    VERTICAL = "9:16"      # 1080×1920 - TikTok, Reels, Shorts
    HORIZONTAL = "16:9"    # 1920×1080 - YouTube, Twitter
    SQUARE = "1:1"         # 1080×1080 - Instagram Feed
    PORTRAIT = "4:5"       # 1080×1350 - Instagram Portrait

    @property
    def dimensions(self) -> tuple[int, int]:
        """Return (width, height) for this ratio."""
        return {
            "9:16": (1080, 1920),
            "16:9": (1920, 1080),
            "1:1": (1080, 1080),
            "4:5": (1080, 1350),
        }[self.value]

    @property
    def label(self) -> str:
        """Human-readable label."""
        return {
            "9:16": "Vertical (TikTok/Reels)",
            "16:9": "Horizontal (YouTube)",
            "1:1": "Square (Instagram)",
            "4:5": "Portrait (Instagram)",
        }[self.value]


class PanelOverrides(BaseModel):
    """User overrides for auto-generated panel settings."""
    panel_number: int

    # Camera overrides (None = use auto)
    camera_start_zoom: float | None = None
    camera_end_zoom: float | None = None
    camera_easing: CameraEasing | None = None
    camera_focus_x: float | None = None  # 0.0-1.0 custom focus point
    camera_focus_y: float | None = None

    # Mood override
    mood_override: PanelMood | None = None

    # Effect toggles (None = use auto, True/False = force on/off)
    vignette_enabled: bool | None = None
    vignette_intensity: float | None = None  # 0.0-1.0

    color_tint_enabled: bool | None = None
    color_tint_color: str | None = None  # hex color
    color_tint_opacity: float | None = None

    shake_enabled: bool | None = None
    shake_intensity: float | None = None

    pulse_enabled: bool | None = None
    pulse_intensity: float | None = None

    golden_glow_enabled: bool | None = None
    golden_glow_intensity: float | None = None
```

### 5.5.5 Database Changes

```sql
-- Add overrides column to comic_panel_instructions
ALTER TABLE comic_panel_instructions
ADD COLUMN IF NOT EXISTS user_overrides JSONB DEFAULT NULL;

-- Add aspect_ratio to comic_video_projects
ALTER TABLE comic_video_projects
ADD COLUMN IF NOT EXISTS aspect_ratio TEXT DEFAULT '9:16';

-- Example user_overrides stored value:
-- {
--   "vignette_enabled": false,
--   "camera_end_zoom": 1.3,
--   "mood_override": "positive"
-- }
```

### 5.5.6 Service Changes

```python
# comic_director_service.py
def apply_overrides(
    self,
    instruction: PanelInstruction,
    overrides: PanelOverrides
) -> PanelInstruction:
    """Apply user overrides to auto-generated instruction."""
    # Clone instruction
    updated = instruction.model_copy(deep=True)

    # Apply camera overrides
    if overrides.camera_start_zoom is not None:
        updated.camera.start_zoom = overrides.camera_start_zoom
    if overrides.camera_end_zoom is not None:
        updated.camera.end_zoom = overrides.camera_end_zoom
    # ... etc

    # Apply effect overrides
    if overrides.vignette_enabled is False:
        updated.effects.ambient_effects = [
            e for e in updated.effects.ambient_effects
            if e.effect_type != EffectType.VIGNETTE
        ]
    elif overrides.vignette_enabled is True:
        # Add or update vignette
        ...

    return updated
```

### 5.5.7 Implementation Order

1. [ ] Add `user_overrides` and `aspect_ratio` columns to database
2. [ ] Create `AspectRatio` enum and `PanelOverrides` model
3. [ ] Add `apply_overrides()` to ComicDirectorService
4. [ ] **Update ComicRenderService for aspect ratio support:**
   - [ ] Accept aspect ratio parameter in render methods
   - [ ] Calculate output dimensions from AspectRatio enum
   - [ ] Adjust Ken Burns zoom for different frame sizes
5. [ ] Add override UI controls to Streamlit page
6. [ ] **Add aspect ratio selector to UI:**
   - [ ] Dropdown with 9:16, 16:9, 1:1, 4:5 options
   - [ ] Re-render previews when ratio changes
   - [ ] Store selected ratio in project
7. [ ] Add "Reset to Auto" functionality
8. [ ] **Add bulk action buttons:**
   - [ ] "Render All Panels" with progress tracking
   - [ ] "Approve All" with confirmation dialog
   - [ ] Progress bar showing rendered/approved counts
9. [ ] Test with problematic panels (vignette over text)
10. [ ] Test all aspect ratios render correctly

---

## Phase 6: PARTICLES, SFX & MUSIC

### 6.1 Overview

Add particle overlays, sound effects, and background music to enhance comic videos.

**Prerequisites:** Phase 5 complete (Ken Burns camera, FFmpeg effects, transitions)

### 6.2 Rendering Pipeline (Phase 6)

```
Panel Image (Ken Burns)
        ↓
+ Color Effects (Phase 1)
        ↓
+ Particle Overlay (Phase 6)  ← WebM with alpha
        ↓
+ Audio Mix (VO + SFX + Music)
        ↓
Final Frame
```

### 6.3 Particle Effects System

#### Required Particle Assets

| Effect | Filename | Use Case | Source |
|--------|----------|----------|--------|
| Sparkles | `sparkles.webm` | Positive moments, value, magic | Mixkit, Pixabay |
| Confetti | `confetti.webm` | Celebration, outro, wins | Mixkit, Pexels |
| Coins Falling | `coins_falling.webm` | Money scenes, wealth | Pixabay, Videezy |
| Embers | `embers.webm` | Fire scenes, destruction | Mixkit, Pexels |
| Dust | `dust.webm` | Atmosphere, subtle life | Pexels, Pixabay |
| Smoke | `smoke.webm` | Fire aftermath, chaos | Mixkit, Videezy |
| Rain | `rain.webm` | Sad moments, despair | Pexels, Pixabay |
| Light Rays | `light_rays.webm` | Hope, revelation, divine | Mixkit, Videezy |
| Glitch | `glitch.webm` | System break, chaos | Mixkit, Videezy |
| Bokeh | `bokeh.webm` | Dreamy, positive, soft | Pexels, Pixabay |

#### Asset Requirements

| Property | Requirement |
|----------|-------------|
| Format | WebM (preferred) or MOV with ProRes 4444 |
| Alpha | **Must have transparency** (or use screen blend) |
| Resolution | 1080x1920 or higher (vertical) |
| Duration | 5-10 seconds (will loop) |
| Frame Rate | 30fps |

#### Sourcing Links

**Free (Royalty-Free):**
- **Mixkit** — https://mixkit.co/free-video-effects/
- **Pexels** — https://www.pexels.com/search/videos/particles/
- **Pixabay** — https://pixabay.com/videos/search/particles/
- **Videezy** — https://www.videezy.com/free-video/particles

### 6.4 Sound Effects via ElevenLabs

Use ElevenLabs Sound Effects API to generate SFX on-demand:

**API Endpoint:** `POST https://api.elevenlabs.io/v1/sound-generation`

#### SFX Generation & Caching Workflow

```
User requests SFX
       ↓
Check sfx_assets table (cached?)
       ↓
   ┌───┴───┐
   Yes      No
   ↓        ↓
Return   Generate via ElevenLabs API
cached      ↓
URL      Preview in UI
            ↓
        User approves?
        ┌───┴───┐
        Yes     No
        ↓       ↓
      Upload  Regenerate
      to      with new
      storage prompt
        ↓
      Save to sfx_assets
      (cached for reuse)
        ↓
      Return URL
```

**Key Features:**
- Generated SFX are saved to Supabase storage for reuse
- Once approved, SFX cached in `sfx_assets` table
- Future requests for same SFX type return cached version
- User can regenerate with different prompt if not satisfied
- Saves ElevenLabs API credits on repeat usage

#### SFX Presets

| SFX | Prompt | Duration |
|-----|--------|----------|
| cha_ching | "cash register cha-ching, coins, money sound" | 1.0s |
| sad_trombone | "sad trombone wah wah wah, comedic failure" | 1.5s |
| whoosh | "fast whoosh swoosh transition sound" | 0.5s |
| fire_crackle | "fire crackling, campfire burning, flames" | 3.0s |
| printer_brrr | "money printer printing, mechanical whirring" | 2.0s |
| alarm | "warning alarm siren, danger alert" | 1.5s |
| glass_break | "glass shattering, breaking, crash" | 0.8s |
| crowd_murmur | "crowd murmuring, people talking background" | 4.0s |
| celebration | "celebration party, cheering, confetti pop" | 2.0s |
| coin_drop | "coins dropping, metal clinking" | 1.0s |
| explosion | "explosion boom, impact blast" | 1.5s |
| record_scratch | "vinyl record scratch, DJ stop" | 0.5s |
| pop | "pop sound, bubble pop, appear" | 0.3s |

### 6.5 Database Schema (Phase 6)

```sql
-- Particle effect assets
CREATE TABLE particle_assets (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    effect_type TEXT NOT NULL UNIQUE,
    file_url TEXT NOT NULL,
    has_alpha BOOLEAN DEFAULT true,
    blend_mode TEXT DEFAULT 'over',  -- 'over' (alpha), 'screen', 'add'
    duration_ms INT NOT NULL,
    default_opacity FLOAT DEFAULT 0.7,
    default_scale FLOAT DEFAULT 1.0,
    metadata JSONB DEFAULT '{}',
    created_at TIMESTAMPTZ DEFAULT NOW()
);

-- SFX assets (generated via ElevenLabs, cached for reuse)
CREATE TABLE sfx_assets (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    sfx_type TEXT NOT NULL UNIQUE,      -- e.g., 'cha_ching', 'sad_trombone'
    file_url TEXT NOT NULL,             -- Supabase storage URL
    duration_ms INT NOT NULL,

    -- Generation info
    prompt TEXT NOT NULL,               -- ElevenLabs prompt used
    source TEXT DEFAULT 'elevenlabs',   -- 'elevenlabs', 'manual', 'freesound'

    -- Approval workflow
    is_approved BOOLEAN DEFAULT false,  -- Only approved SFX cached for reuse
    approved_at TIMESTAMPTZ,
    approved_by TEXT,                   -- User who approved

    -- Usage hints
    default_volume FLOAT DEFAULT 0.8,
    category TEXT,                      -- 'money', 'emotion', 'action', 'transition'

    -- Stats
    usage_count INT DEFAULT 0,          -- Track how often used

    metadata JSONB DEFAULT '{}',
    created_at TIMESTAMPTZ DEFAULT NOW()
);

-- Index for fast lookup by type
CREATE INDEX idx_sfx_assets_type ON sfx_assets(sfx_type);
CREATE INDEX idx_sfx_assets_approved ON sfx_assets(is_approved) WHERE is_approved = true;
```

### 6.6 Data Models (Phase 6)

```python
class ParticleEffect(BaseModel):
    """A particle overlay effect."""
    effect_type: str  # 'sparkles', 'confetti', etc.
    start_ms: int = 0
    duration_ms: int | None = None  # None = full panel
    opacity: float = 0.7
    scale: float = 1.0
    position: str = "full"  # 'full', 'top', 'bottom', 'center'
    loop: bool = True

class SFXTrigger(BaseModel):
    """A sound effect trigger."""
    sfx_type: str
    trigger_ms: int  # When to play (relative to panel start)
    volume: float = 0.8

class BackgroundMusic(BaseModel):
    """Background music configuration."""
    track_url: str
    volume: float = 0.3
    duck_during_vo: bool = True
    duck_level: float = 0.15
    fade_in_ms: int = 1000
    fade_out_ms: int = 2000

class PanelEffectsV2(BaseModel):
    """Extended effects model for Phase 6."""
    # Phase 1 effects
    ambient_effects: list[EffectInstance] = []
    triggered_effects: list[EffectInstance] = []
    color_tint: str | None = None
    tint_opacity: float = 0.0

    # Phase 6 additions
    particles: list[ParticleEffect] = []
    sfx: list[SFXTrigger] = []
```

### 6.7 Effect Presets (Updated)

```python
MOOD_EFFECT_PRESETS_V2: dict[PanelMood, PanelEffectsV2] = {
    PanelMood.NEUTRAL: PanelEffectsV2(
        particles=[ParticleEffect(effect_type="dust", opacity=0.3)]
    ),
    PanelMood.POSITIVE: PanelEffectsV2(
        ambient_effects=[EffectInstance(effect_type=EffectType.GOLDEN_GLOW, intensity=0.3)],
        particles=[ParticleEffect(effect_type="sparkles", opacity=0.5)],
        color_tint="#FFD700",
        tint_opacity=0.1
    ),
    PanelMood.DANGER: PanelEffectsV2(
        ambient_effects=[
            EffectInstance(effect_type=EffectType.RED_GLOW, intensity=0.4),
            EffectInstance(effect_type=EffectType.VIGNETTE, intensity=0.5),
            EffectInstance(effect_type=EffectType.SHAKE, intensity=0.3)
        ],
        particles=[ParticleEffect(effect_type="embers", opacity=0.6)],
        color_tint="#FF0000",
        tint_opacity=0.15
    ),
    PanelMood.CELEBRATION: PanelEffectsV2(
        ambient_effects=[
            EffectInstance(effect_type=EffectType.GOLDEN_GLOW, intensity=0.4),
            EffectInstance(effect_type=EffectType.PULSE, intensity=0.3)
        ],
        particles=[
            ParticleEffect(effect_type="confetti", opacity=0.7),
            ParticleEffect(effect_type="sparkles", opacity=0.4)
        ],
        color_tint="#FFD700",
        tint_opacity=0.15
    ),
    # ... other moods
}

# Content-triggered particles and SFX
CONTENT_TRIGGERS_V2: dict[str, dict] = {
    "fire": {
        "particles": [ParticleEffect(effect_type="embers", opacity=0.6)],
        "sfx": [SFXTrigger(sfx_type="fire_crackle", trigger_ms=0)]
    },
    "money": {
        "particles": [ParticleEffect(effect_type="coins_falling", opacity=0.5)],
        "sfx": [SFXTrigger(sfx_type="cha_ching", trigger_ms=500)]
    },
    "print": {
        "particles": [ParticleEffect(effect_type="coins_falling", opacity=0.6)],
        "sfx": [SFXTrigger(sfx_type="printer_brrr", trigger_ms=0)]
    },
    "break": {
        "particles": [ParticleEffect(effect_type="glitch", opacity=0.5)],
        "sfx": [SFXTrigger(sfx_type="glass_break", trigger_ms=0)]
    },
    "win": {
        "particles": [ParticleEffect(effect_type="confetti", opacity=0.6)],
        "sfx": [SFXTrigger(sfx_type="celebration", trigger_ms=0)]
    },
    "sad": {
        "particles": [],
        "sfx": [SFXTrigger(sfx_type="sad_trombone", trigger_ms=500)]
    },
    # ... other triggers
}
```

### 6.8 FFmpeg Implementation

#### Particle Overlay

```python
def build_particle_overlay_filter(
    particle: ParticleEffect,
    particle_asset: dict,
    panel_duration_ms: int
) -> tuple[str, str]:
    """Build FFmpeg filter for particle overlay."""
    loops_needed = (panel_duration_ms // particle_asset["duration_ms"]) + 1
    input_args = f'-stream_loop {loops_needed} -i "{particle_asset["file_url"]}"'

    if particle_asset.get("has_alpha", True):
        blend = f"overlay=0:0:format=auto"
    else:
        blend = f"overlay=0:0:format=auto:blend=screen"

    opacity_filter = f"colorchannelmixer=aa={particle.opacity}," if particle.opacity < 1.0 else ""
    filter_expr = f"{opacity_filter}{blend}"

    return input_args, filter_expr
```

#### Background Music with Ducking

```python
def build_music_duck_filter(music: BackgroundMusic, vo_duration_ms: int) -> tuple[str, str]:
    """Build FFmpeg filter for background music that ducks during voiceover."""
    input_args = f'-i "{music.track_url}"'

    filter_expr = (
        f"[music_in]volume={music.volume}[music_vol];"
        f"[music_vol][vo]sidechaincompress="
        f"threshold=0.02:ratio=10:attack=50:release=500[music_ducked];"
        f"[music_ducked]afade=t=in:st=0:d={music.fade_in_ms/1000},"
        f"afade=t=out:st={vo_duration_ms/1000 - music.fade_out_ms/1000}:d={music.fade_out_ms/1000}"
        f"[music_final]"
    )

    return input_args, filter_expr
```

### 6.9 New Services (Phase 6)

| Service | Purpose |
|---------|---------|
| `ComicParticleService` | Manage particle WebM assets |
| `ElevenLabsSFXService` | Generate SFX via ElevenLabs API |
| `ComicSFXService` | Manage cached SFX assets |
| `ComicMusicService` | Background music with ducking |

### 6.10 Files to Create (Phase 6)

```
services/
  comic_video/
    comic_particle_service.py     # Particle asset management
    elevenlabs_sfx_service.py     # ElevenLabs Sound Effects API
    comic_sfx_service.py          # SFX asset management & caching
    comic_music_service.py        # Background music management

sql/
  2025-XX-XX_comic_video_phase2.sql  # particle_assets, sfx_assets tables

assets/
  particles/                      # Downloaded particle WebM files
    sparkles.webm
    confetti.webm
    coins_falling.webm
    embers.webm
    dust.webm
```

### 6.11 Implementation Order

1. **Asset Setup**
   - [ ] Source and download particle videos (5 high-priority)
   - [ ] Implement ElevenLabsSFXService
   - [ ] Pre-generate all SFX using ElevenLabs Sound Effects API
   - [ ] Upload assets to Supabase storage
   - [ ] Create database tables and seed data

2. **Particle Overlay System**
   - [ ] Implement ComicParticleService
   - [ ] Build FFmpeg particle overlay filters
   - [ ] Update render pipeline to include particles
   - [ ] Test with single panel

3. **SFX System**
   - [ ] Integrate ElevenLabsSFXService with render pipeline
   - [ ] Build FFmpeg audio mixing filters
   - [ ] Content-triggered SFX detection
   - [ ] Test audio sync

4. **Background Music**
   - [ ] Implement ComicMusicService
   - [ ] Ducking during voiceover
   - [ ] Full video render tests

---

## Phase 7: MERGE & CLEANUP

*(To be filled in during Phase 7)*

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
| 2025-12-08 | 4 | All services implemented (models, audio, director, render, orchestration, UI) |
| 2025-12-08 | 5 | Real-world testing with "Inflation Explained by Raccoons" comic |
| 2025-12-08 | 5 | JSON format adaptations (script_for_audio, grid_structure, explicit mood) |
| 2025-12-08 | 5 | Ken Burns zoom fix (panel_zoom = grid_cols * 0.85) |
| 2025-12-08 | 5 | Panel-to-panel transitions with two-phase zoompan animation |
| 2025-12-08 | 5 | Bug fixes: image dimensions, concat paths, duplicate uploads |
| 2025-12-08 | 5.5 | Planned: Manual panel adjustments (camera, effects overrides) |
| 2025-12-08 | 6 | Planned: Particle overlays, SFX via ElevenLabs (with caching), background music |
