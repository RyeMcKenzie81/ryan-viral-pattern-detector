# Checkpoint 020 - Voice Selection Fix & Preview Verification

**Date:** 2025-12-14
**Branch:** `feature/trash-panda-content-pipeline`
**Status:** Phase 9 Extended - Comic Video Integration Refinements

---

## Summary

Fixed voice selection for comic audio generation to use character voices (e.g., every-coon) instead of defaulting to Rachel. Verified panel preview rendering supports effects and transitions.

---

## What Was Fixed This Session

### Voice Selection for Character Audio

**Problem:** Audio was being generated with the default "Rachel" voice instead of the every-coon character voice.

**Root Cause:** The `generate_all_audio` method in `comic_audio_service.py` wasn't checking for `character` field in panel data for single-speaker panels.

**Solution:**

1. **Added `character` field to comic JSON export** (`comic_service.py`)
   - Panels now include `character` and `expression` fields for voice lookup

2. **Updated `generate_all_audio` to use character voice** (`comic_audio_service.py`)
   - For single-speaker panels, checks for `character` field
   - Calls `get_voice_for_speaker()` which looks up every-coon voice from `character_voice_profiles` table

### Files Modified

| File | Changes |
|------|---------|
| `comic_service.py` | Added `character` and `expression` fields to panel JSON export |
| `comic_audio_service.py` | Updated single-speaker audio generation to use character voice lookup |

---

## Code Changes

### comic_service.py - Panel JSON Export

```python
# Build panels array
panels = []
for panel in comic_script.panels:
    panel_json = {
        "panel_number": panel.panel_number,
        "panel_type": panel_type_map.get(panel.panel_type, "ACT 1 - CONTENT"),
        "header_text": comic_script.title if panel.panel_number == 1 else "",
        "dialogue": panel.dialogue,
        "character": panel.character,  # NEW: For audio voice lookup
        "expression": panel.expression,  # NEW: For visual context
        "mood": self._infer_mood_from_panel(panel, comic_script.emotional_payoff),
        "characters_needed": [f"{panel.character} ({panel.expression})"],
        "prompt": panel.visual_description
    }
    panels.append(panel_json)
```

### comic_audio_service.py - Voice Lookup for Single-Speaker

```python
else:
    # Single speaker - check for character field to use proper voice
    text = self.extract_panel_text(panel)
    if text:
        # Check for character field and use proper voice lookup
        character = panel.get("character", "").strip().lower()
        if character:
            # Look up voice for character (e.g., every-coon, raccoon)
            panel_voice_id, panel_voice_name = await self.get_voice_for_speaker(
                speaker=character,
                narrator_voice_id=voice_id,
                narrator_voice_name=voice_name
            )
        else:
            # Fall back to provided voice or default
            panel_voice_id = voice_id
            panel_voice_name = voice_name

        audio = await self.generate_panel_audio(
            project_id=project_id,
            panel_number=panel_number,
            text=text,
            voice_id=panel_voice_id,
            voice_name=panel_voice_name
        )
        results.append(audio)
```

---

## Panel Preview Rendering (Verified)

The panel preview rendering already supports effects and transitions via:

1. **Camera/Ken Burns Effects** (`_build_zoompan_filter`)
   - Start position, end position, zoom levels
   - Pan/tilt movements

2. **Visual Effects** (`_build_effects_filter`)
   - Color tints with opacity
   - Ambient effects (applied throughout)
   - Triggered effects (with timing expressions)
   - Effect types: VIGNETTE, etc.

The render pipeline:
```
PanelInstruction (camera + effects)
        ↓
_build_panel_render_command()
        ↓
FFmpeg with zoompan + effects filters
        ↓
Rendered MP4 preview
```

---

## Voice Lookup Flow

```
Panel JSON with character: "every-coon"
        ↓
get_voice_for_speaker("every-coon")
        ↓
Query character_voice_profiles table
        ↓
Return voice_id for every-coon
        ↓
Generate audio with character voice
```

**Database Requirement:** The `character_voice_profiles` table must have an entry for "every-coon" with the correct ElevenLabs voice_id.

---

## Previous Session Issues Resolved

| Issue | Status |
|-------|--------|
| Wrong voice (Rachel instead of every-coon) | Fixed |
| Audio loading error in panel details | Fixed (Checkpoint 019 - signed URLs) |
| Panel not found in layout | Fixed (Checkpoint 019 - grid_structure) |

---

## Remaining Comic Path Steps (from PLAN.md)

| Step | Name | Status |
|------|------|--------|
| 25 | Comic Video | ✅ Integrated |
| 26 | Comic SEO/Metadata | Not built |
| 27 | Comic Metadata Selection | Not built |
| 28 | Comic Thumbnail Generation | Not built |
| 29 | Comic Thumbnail Selection | Not built |

**Note:** Video Path (steps 13-14c) also missing SEO/Metadata and Thumbnails.

---

## Quick Commands

```bash
# Activate venv
source /Users/ryemckenzie/projects/viraltracker/venv/bin/activate

# Verify syntax
python3 -m py_compile viraltracker/services/content_pipeline/services/comic_service.py
python3 -m py_compile viraltracker/services/comic_video/comic_audio_service.py

# Run Streamlit
cd /Users/ryemckenzie/projects/viraltracker/viraltracker-planning
streamlit run viraltracker/ui/Home.py
```

---

## Testing the Voice Fix

1. Delete existing video project (to clear old audio)
2. Re-create video project from comic JSON
3. Generate All Audio
4. Check that audio uses every-coon voice (listen for character voice vs Rachel)

**Important:** The `character_voice_profiles` table must have an every-coon entry:
```sql
SELECT * FROM character_voice_profiles WHERE character = 'every-coon';
```

If missing, add it:
```sql
INSERT INTO character_voice_profiles (character, voice_id, display_name)
VALUES ('every-coon', 'YOUR_ELEVENLABS_VOICE_ID', 'Every-Coon');
```

---

## Next Steps

1. **Test voice selection** - Regenerate audio and verify every-coon voice
2. **Build SEO/Metadata Service** - For both video and comic paths
3. **Build Thumbnail Service** - For both video and comic paths
4. **Phase 10: End-to-End Testing** - Full workflow tests
