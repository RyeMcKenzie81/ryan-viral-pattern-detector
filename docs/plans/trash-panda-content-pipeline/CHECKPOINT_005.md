# Checkpoint 005: MVP 2 Script Generation Complete

**Date**: 2025-12-10
**Context**: Script generation service and UI implemented
**Branch**: `feature/trash-panda-content-pipeline`
**Working Directory**: `/Users/ryemckenzie/projects/viraltracker/viraltracker-planning`

---

## Summary

Implemented MVP 2: Script Generation with Claude Opus 4.5 integration. Users can now generate full video scripts from selected topics, review against the bible checklist, and approve or request revisions.

---

## What Was Done

### 1. ScriptGenerationService (`script_service.py`)
- **generate_script()**: Creates full script with beats, thumbnails, ELS format
- **review_script()**: Reviews against PRE-FLIGHT CHECKLIST from Section 18
- **revise_script()**: Creates revised version based on feedback
- **get_full_bible_content()**: Injects complete bible (~35KB) for quality
- Database operations: save_script, save_review, approve_script

### 2. Orchestrator Node Updates
- Updated `TopicSelectionNode` to flow into `ScriptGenerationNode`
- Updated `ScriptGenerationNode` to use correct service API
- Updated `ScriptReviewNode` to use full script data
- Updated `ScriptApprovalNode` with Quick Approve logic

### 3. State Updates
- Added `current_script_data` field for script content in workflow

### 4. Content Pipeline UI
- **Generate Tab**: Generate script with Claude Opus 4.5, view beats
- **Review Tab**: Run bible checklist review, see pass/fail results
- **Approve Tab**: Approve script or request revision with notes

---

## Files Created

```
viraltracker/services/content_pipeline/services/script_service.py
```

## Files Modified

```
viraltracker/services/content_pipeline/orchestrator.py
  - Updated nodes to use correct service API
  - TopicSelection now flows to ScriptGeneration

viraltracker/services/content_pipeline/state.py
  - Added current_script_data field

viraltracker/services/content_pipeline/services/__init__.py
  - Export ScriptGenerationService

viraltracker/services/content_pipeline/services/content_pipeline_service.py
  - Wire in ScriptGenerationService

viraltracker/ui/pages/22_📝_Content_Pipeline.py
  - Add script generation/review/approval UI (~370 lines)
```

---

## Script Generation Flow

```
1. Topic Selected
   ↓
2. Generate Script (Claude Opus 4.5)
   - Full bible injected (~35KB context)
   - Returns beats, ELS, thumbnails
   ↓
3. Review Script (Claude Opus 4.5)
   - Checks PRE-FLIGHT CHECKLIST
   - Returns pass/fail for each item
   - Overall score and ready_for_approval
   ↓
4. Human Approval
   - Approve: Proceeds to ELS conversion (MVP 3)
   - Revise: Returns to generation with notes
```

---

## Script Output Format

```json
{
  "title": "Video title",
  "target_duration_seconds": 180,
  "hook_formula_used": "Heist|Mystery Trash|...",
  "beats": [
    {
      "beat_id": "01_hook",
      "beat_name": "Hook",
      "timestamp_start": "0:00",
      "timestamp_end": "0:06",
      "script": "Dialogue text",
      "character": "every-coon",
      "visual_notes": "Scene description",
      "audio_notes": "Music/SFX"
    }
  ],
  "els_script": "Full ELS format",
  "thumbnail_suggestions": [...],
  "cta_target": "Next video topic"
}
```

---

## Review Checklist Categories

| Category | Items Checked |
|----------|---------------|
| Voice & Style | Hook formula, banned words, caveman cadence, joke frequency, trash metaphors |
| Structure | Hook timing, re-hooks, visual escalation, trash pun, runtime, pacing |
| Characters | Every-Coon as proxy, contrast character, deployment rules |
| Editorial | No investment advice, accurate claims |
| Technical | CTA max 8 seconds |

---

## Commits

1. `194a480` - feat: Add ScriptGenerationService for MVP 2
2. `fbea5ec` - feat: Add script generation UI for MVP 2

---

## Next Steps (MVP 3: ELS & Audio)

1. ELS Conversion Node
2. Audio Production with ElevenLabs
3. Character voice mapping
4. Audio review UI

---

## Commands to Test

```bash
cd /Users/ryemckenzie/projects/viraltracker/viraltracker-planning

# Run the app locally
source ../venv/bin/activate
streamlit run viraltracker/ui/Home.py

# Navigate to Content Pipeline
# 1. Select a brand
# 2. Create new project OR open existing with selected topic
# 3. Click "Generate Script" to test
```

---

**Status**: MVP 2 Complete - Script Generation, Review, and Approval
