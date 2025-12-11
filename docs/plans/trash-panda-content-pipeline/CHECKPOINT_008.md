# Checkpoint 008: MVP 3 - ELS & Audio Integration

**Date**: 2025-12-11
**Context**: MVP 3 complete - ELS conversion and Audio tab integration
**Branch**: `feature/trash-panda-content-pipeline`
**Working Directory**: `/Users/ryemckenzie/projects/viraltracker/viraltracker-planning`

---

## Session Summary

This session accomplished:
1. Documented MVP 3 plan in PLAN.md
2. Added ELS conversion to ScriptGenerationService
3. Added ELS database operations
4. Created Audio tab in Content Pipeline UI
5. Integrated with existing Audio Production system
6. Added workflow state management for audio

---

## What Was Built (MVP 3)

### ScriptGenerationService Additions

**ELS Conversion (Deterministic)**:
```python
def convert_to_els(self, script_data: Dict, project_name: str = "trash-panda") -> str:
    """Convert script beats to ELS format."""

def _convert_beat_to_els(self, beat: Dict) -> str:
    """Convert single beat with CHARACTER, DIRECTION, PACE, PAUSE tags."""

def _infer_pace_from_beat(self, beat: Dict) -> str:
    """Smart pace inference from beat context and character."""
```

**Database Operations**:
```python
async def save_els_to_db(project_id, script_version_id, els_content) -> UUID
async def get_els_version(project_id, source_type='video') -> Dict
async def link_audio_session(project_id, els_version_id, audio_session_id) -> None
```

### Pace Inference Logic

| Context | Inferred Pace |
|---------|---------------|
| Hook beats | fast |
| Climax beats | chaos |
| Setup/Explain beats | normal |
| Summary beats | deliberate |
| Boomer character | slow |
| Fed character | deliberate |
| Wojak character | fast |
| Chad character | quick |
| "chaos" in notes | chaos |
| Default | normal |

### Audio Tab UI

**Step 1: ELS Conversion**
- "Convert to ELS" button (if no ELS exists)
- View ELS in expandable code block
- "Regenerate ELS" option

**Step 2: Audio Generation**
- "Generate Audio" button
- Beat-by-beat generation with progress
- Auto-links session to project

**Step 3: Playback & Selection**
- Audio player per beat
- Take selection buttons
- Duration display

**Step 4: Export**
- "Export Selected Takes (ZIP)" button
- Download button for ZIP file

### Session State Added

```python
st.session_state.els_converting = False
st.session_state.audio_generating = False
st.session_state.current_els = None
```

### Workflow States Added

| State | Description |
|-------|-------------|
| `els_ready` | After ELS conversion |
| `audio_production` | During audio generation |
| `audio_complete` | All beats generated |

---

## ELS Format Generated

```
[META]
video_title: {script title}
project: trash-panda
default_character: every-coon
default_pace: normal

[BEAT: 01_hook]
name: Hook
---
[CHARACTER: every-coon]
[DIRECTION: {visual_notes or audio_notes}]
[PACE: fast]
{script text}
[PAUSE: 100ms]
[END_BEAT]

[BEAT: 02_setup]
...
```

---

## Integration Points

### Audio Production System
- Uses existing `AudioProductionService`
- Uses existing `ELSParserService`
- Uses existing `ElevenLabsService`
- Links via `audio_session_id` FK on both:
  - `content_projects.audio_session_id`
  - `els_versions.audio_session_id`

### Database Tables Used
- `els_versions` - Stores converted ELS content
- `audio_production_sessions` - Audio workflow state
- `audio_takes` - Individual audio files

---

## Files Modified

```
viraltracker/services/content_pipeline/services/script_service.py
  + convert_to_els()
  + _convert_beat_to_els()
  + _infer_pace_from_beat()
  + save_els_to_db()
  + get_els_version()
  + link_audio_session()
  + VALID_PACES constant
  + VALID_CHARACTERS constant

viraltracker/ui/pages/30_📝_Content_Pipeline.py
  + Audio tab in render_script_view()
  + render_audio_tab()
  + render_audio_session_details()
  + render_audio_take()
  + run_els_conversion()
  + run_audio_generation()
  + get_audio_production_service()
  + get_els_parser_service()
  + get_elevenlabs_service()
  + Session state: els_converting, audio_generating, current_els
  + Workflow states: els_ready, audio_production, audio_complete

docs/plans/trash-panda-content-pipeline/PLAN.md
  + Phase 1-3 marked complete
  + Phase 4 detailed with technical design
```

---

## Commits This Session

1. `e58f039` - docs: Add checkpoint 007 - Revision UX complete, merged to main
2. `9f9dabe` - feat: Add MVP 3 - ELS conversion and Audio tab integration

---

## Full Flow (MVP 3)

```
Approved Script
    ↓
[Audio Tab] Convert to ELS (deterministic)
    ↓
Save to els_versions table
    ↓
[Audio Tab] Generate Audio
    ↓
Parse ELS → Create audio session → Link to project
    ↓
For each beat:
    Generate audio via ElevenLabs
    Add pause via FFmpeg
    Upload to Supabase Storage
    Save take to database
    Auto-select take
    ↓
[Audio Tab] Playback & Selection
    ↓
[Audio Tab] Export ZIP
```

---

## Next Steps

### Immediate
- Test MVP 3 on Railway deployment
- Verify ELS conversion produces valid format
- Test audio generation end-to-end

### Future MVPs
- **MVP 4**: Asset Management (Phase 5)
- **MVP 5**: Asset Generation (Phase 6)
- **MVP 6**: Editor Handoff (Phase 7)
- **MVP 7+**: Comic Path (Phases 8-9)

---

## Commands to Resume

```bash
cd /Users/ryemckenzie/projects/viraltracker/viraltracker-planning
git checkout feature/trash-panda-content-pipeline

# Local testing
source ../venv/bin/activate
streamlit run viraltracker/ui/Home.py
```

---

**Status**: MVP 3 Complete, Ready for Testing
