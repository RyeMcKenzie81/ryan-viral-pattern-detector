# Checkpoint 021 - Comic Audio Voice Fix & Character Name Normalization

**Date:** 2025-12-15
**Branch:** `feature/trash-panda-content-pipeline`
**Status:** Phase 9 Extended - Comic Video Voice Issues Fully Resolved

---

## Summary

Fixed comic audio generation to use correct every-coon voice by:
1. Diagnosing voice selection flow with debug logging
2. Discovering comic condense was generating creative character names (e.g., "pile-of-raccoon-icons")
3. Implementing proper fix in `condense_to_comic` to preserve original character names
4. Adding post-processing normalization for both condensation and revision methods
5. Removed debug print statements after fix confirmed

**Root cause fixed:** The `condense_to_comic` method now extracts character names from the original script, passes them to the LLM with strong constraints, and post-processes responses to normalize any creative names.

---

## Issues Fixed This Session

### 1. Preview Video URL Error
**Problem:** `render_panel_preview` returned storage path instead of signed URL
**Fix:** Added `get_video_url()` call after upload to return signed URL

### 2. Duplicate Audio Upload Error (409)
**Problem:** Re-generating audio failed because file already existed in storage
**Fix:** Added upsert support with fallback delete+re-upload in `_upload_audio`

### 3. Duplicate Database Record Error
**Problem:** Re-generating audio failed on database insert
**Fix:** Added `on_conflict="project_id,panel_number"` to upsert

### 4. Wrong Voice (Rachel instead of Every-Coon)
**Problem:** Comic panels had character="pile-of-raccoon-icons" instead of "every-coon"
**Root Cause Fix:**
- Added `_extract_script_characters()` helper to extract characters from original script beats
- Added `_normalize_character_name()` helper for post-processing validation
- Updated `CONDENSATION_PROMPT` with `<character_mapping>` section requiring exact character names
- Added character normalization in both `condense_to_comic` and `revise_comic` methods
- Fallback normalization still exists in `comic_audio_service.py` as safety net

---

## Root Cause Fix Implementation

### 1. Character Extraction from Script
New helper method extracts unique character names from original script beats:
```python
def _extract_script_characters(self, script_data: Dict[str, Any]) -> List[str]:
    """Extract unique character names from the original script beats."""
    characters = set()
    beats = script_data.get("beats", [])
    if not beats and script_data.get("storyboard_json"):
        beats = script_data["storyboard_json"].get("beats", [])
    for beat in beats:
        character = beat.get("character", "")
        if character:
            characters.add(character.strip().lower())
    if not characters:
        characters.add("every-coon")
    return list(characters)
```

### 2. Updated Condensation Prompt
Added explicit character mapping section:
```xml
<character_mapping>
VALID CHARACTERS (you MUST use these exact names):
{script_characters}

These are the ONLY valid character names. Do NOT create variations or creative names.
Map any character references to these exact names.
</character_mapping>
```

And updated critical rules:
```
- CHARACTER NAMES MUST BE EXACT: Only use "{script_characters}" - no variations, no creative names
```

### 3. Post-Processing Normalization
Added `_normalize_character_name()` helper that:
- Checks for direct matches
- Checks for partial matches (valid name contained in input or vice versa)
- Falls back to any raccoon-related valid character for "raccoon"/"coon" variants
- Defaults to first valid character if no match found

Applied in both `condense_to_comic` and `revise_comic`:
```python
raw_character = p.get("character", "every-coon")
normalized_character = self._normalize_character_name(raw_character, script_characters)
if raw_character.lower() != normalized_character:
    logger.info(f"Normalized character '{raw_character}' -> '{normalized_character}'")
```

---

## Files Modified This Session

| File | Changes |
|------|---------|
| `comic_video_service.py` | Return signed URLs from preview methods |
| `comic_audio_service.py` | Upsert handling, character normalization fallback, removed debug prints |
| `comic_service.py` | Added `_extract_script_characters()`, `_normalize_character_name()`, updated prompt, post-processing |

---

## Remaining Safety Net (comic_audio_service.py)

The audio service still has character mapping as a fallback in case:
- Old comic data exists with creative names
- Edge cases slip through normalization

```python
character_map = {
    "every-coon": Character.EVERY_COON,
    "raccoon": Character.EVERY_COON,
    "pile-of-raccoon-icons": Character.EVERY_COON,  # Legacy support
    # ... other characters
}

# Also check if "raccoon" or "coon" is in the name
if speaker_lower not in character_map:
    if "raccoon" in speaker_lower or "coon" in speaker_lower:
        logger.info(f"Normalizing '{speaker_lower}' to every-coon")
        character_map[speaker_lower] = Character.EVERY_COON
```

---

## Remaining Issues

1. **Workflow state issue** - tabs showing "approve script first" even when script is approved
   - Needs investigation in UI workflow state management

---

## Quick Commands

```bash
# Activate venv
source /Users/ryemckenzie/projects/viraltracker/venv/bin/activate

# Verify syntax
python3 -m py_compile viraltracker/services/comic_video/comic_audio_service.py
python3 -m py_compile viraltracker/services/content_pipeline/services/comic_service.py

# Run Streamlit
cd /Users/ryemckenzie/projects/viraltracker/viraltracker-planning
streamlit run viraltracker/ui/Home.py
```

---

## Git Commits This Session

1. `fix: Return signed URLs for preview videos and improve voice logging`
2. `fix: Use ElevenLabsService for comic audio voice lookup`
3. `fix: Handle duplicate audio files in comic upload`
4. `fix: Add on_conflict to panel audio upsert`
5. `debug: Add print statements for comic audio voice selection`
6. `fix: Normalize creative character names to standard voices`
7. `fix: Implement proper character name preservation in comic condense`
