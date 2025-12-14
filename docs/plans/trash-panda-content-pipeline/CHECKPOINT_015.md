# Checkpoint 015 - SFX Tab Complete, Multiple Fixes

**Date:** 2025-12-13
**Branch:** `feature/trash-panda-content-pipeline`
**Status:** MVP 4, 5, 6 Complete + SFX Tab Added - Testing in progress

---

## Summary

Added full SFX (Sound Effects) tab with extract, generate, and review workflow. Fixed multiple issues discovered during testing including asset status filtering, workflow state routing, and storage bucket configuration.

---

## What Was Built This Session

### SFX Tab (New Feature)
- **Extract Sub-tab**: Extracts SFX cues from script audio/visual notes
- **Generate Sub-tab**: Generate SFX with ElevenLabs API
  - Adjustable duration per SFX (0.5-22 seconds)
  - Individual Generate/Skip buttons
  - Generate All batch button
  - Retry Failed button
- **Review Sub-tab**: Listen, approve, reject, or regenerate
  - Audio player for each SFX
  - Approve/Reject & Redo/Regenerate buttons
  - Adjust duration on regenerate
  - Bulk Approve All / Reject All

### Bug Fixes
1. **Handoff only shows approved/matched assets** - Fixed to filter out generated/needed/failed
2. **Workflow state routing** - Added handoff_ready/handoff_generated to routing
3. **Script approved checks** - Added handoff states to Audio/Assets tab checks
4. **Asset organization in handoff** - Assets grouped by type (Background, Character, Prop, Effect)
5. **Download audio link** - Added per-beat audio download in handoff page
6. **Reject flow** - Changed to reset to 'needed' instead of permanent 'rejected'
7. **Skip option for assets** - Added 'skipped' status for editor-handled assets
8. **Props exclude characters** - Updated prompt to prevent stick figures in props
9. **Effects exclude characters** - Updated prompt for isolated effects
10. **Temperature set to 0.4** - Changed from 0.1 for better variety
11. **Retry All Failed button** - Added for asset generation
12. **Storage upsert** - Fixed 409 Duplicate error on regeneration
13. **SFX storage bucket** - Fixed to use audio-production bucket

---

## Known Issues / TODO

### SFX Duration Intelligence
- All SFX default to 2 seconds
- Music cues should be longer (based on beat duration or scene context)
- Need smarter duration extraction from script

### Handoff Missing Data
1. **Backgrounds not showing in own category** - Need to verify asset_type is being passed correctly
2. **SFX not appearing in handoff** - Need to add SFX to handoff package from project_sfx_requirements
3. **Storyboard missing** - Visual notes shown but not storyboard images; should include storyboard per beat

---

## Files Modified This Session

### New Files:
- `migrations/2025-12-13_add_skipped_status.sql`
- `migrations/2025-12-13_sfx_requirements.sql`

### Modified Files:
- `viraltracker/ui/pages/30_📝_Content_Pipeline.py` (SFX tab, many fixes)
- `viraltracker/ui/pages/31_🎬_Editor_Handoff.py` (asset organization, download links)
- `viraltracker/services/content_pipeline/services/handoff_service.py` (filter approved only)
- `viraltracker/services/content_pipeline/services/asset_generation_service.py` (prompts, temp)
- `viraltracker/services/content_pipeline/services/asset_service.py` (extraction prompt)
- `viraltracker/services/gemini_service.py` (temperature parameter)

---

## Database Changes

### Migrations to Run:

```sql
-- 1. Add 'skipped' status for assets
ALTER TABLE project_asset_requirements
DROP CONSTRAINT IF EXISTS project_asset_requirements_status_check;

ALTER TABLE project_asset_requirements
ADD CONSTRAINT project_asset_requirements_status_check
CHECK (status IN ('needed', 'matched', 'generating', 'generated', 'approved', 'rejected', 'generation_failed', 'skipped'));

-- 2. Create SFX requirements table
CREATE TABLE IF NOT EXISTS project_sfx_requirements (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    project_id UUID NOT NULL REFERENCES content_projects(id) ON DELETE CASCADE,
    sfx_name TEXT NOT NULL,
    description TEXT NOT NULL,
    script_reference JSONB DEFAULT '[]',
    duration_seconds FLOAT DEFAULT 2.0,
    status TEXT NOT NULL DEFAULT 'needed' CHECK (status IN ('needed', 'generating', 'generated', 'approved', 'rejected', 'skipped')),
    generated_audio_url TEXT,
    storage_path TEXT,
    rejection_reason TEXT,
    created_at TIMESTAMPTZ DEFAULT NOW(),
    updated_at TIMESTAMPTZ DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_sfx_requirements_project ON project_sfx_requirements(project_id);
CREATE INDEX IF NOT EXISTS idx_sfx_requirements_status ON project_sfx_requirements(status);
```

---

## Commits This Session

1. `fix: Fix gen_description reference error in generate_single`
2. `fix: Use green chroma key background for effect assets`
3. `fix: Rejected assets now reset to 'needed' for regeneration`
4. `fix: Skip standard video editor effects during asset extraction`
5. `fix: Enable upsert for generated image storage upload`
6. `feat: Add 'Retry All Failed' button for asset generation`
7. `feat: Add 'Skip' option for assets editor will create`
8. `fix: Props exclude characters, temperature set to 0.4`
9. `fix: Add handoff workflow states to UI routing`
10. `fix: Add handoff states to script_approved checks`
11. `fix: Add handoff states + organize assets by type in handoff page`
12. `fix: Only include approved/matched assets in handoff package`
13. `feat: Add SFX tab with extract, generate, and review workflow`
14. `fix: Use correct column names for script query in SFX tab`
15. `fix: Cast duration_seconds to float for number_input`
16. `fix: Use audio-production bucket for SFX storage`

---

## Architecture Reference

```
viraltracker/ui/pages/30_📝_Content_Pipeline.py
├── Tabs: Generate, Review, Approve, Audio, Assets, SFX, Handoff
│
├── Assets Tab Sub-tabs:
│   ├── Extract - Extract assets from script
│   ├── Generate - Generate missing assets
│   ├── Review - Approve/reject generated assets
│   ├── Library - View brand asset library
│   └── Upload - Add new assets
│
└── SFX Tab Sub-tabs:
    ├── Extract - Extract SFX from script
    ├── Generate - Generate SFX with ElevenLabs
    └── Review - Approve/reject generated SFX

viraltracker/services/content_pipeline/services/
├── asset_service.py        # Asset extraction & matching
├── asset_generation_service.py  # Image & SFX generation
├── handoff_service.py      # Editor handoff packages
└── ...
```

---

## Next Steps

1. **Smart SFX Duration** - Detect music cues and set longer duration based on beat/scene
2. **Fix Handoff Backgrounds** - Debug why backgrounds aren't categorized separately
3. **Add SFX to Handoff** - Include approved SFX in handoff package
4. **Add Storyboard to Handoff** - Include storyboard images per beat
5. **Test full end-to-end flow** - Generate handoff with all assets/audio/SFX

---

## Quick Commands

```bash
# Activate venv
source /Users/ryemckenzie/projects/viraltracker/venv/bin/activate

# Run Streamlit (local)
cd /Users/ryemckenzie/projects/viraltracker/viraltracker-planning
streamlit run viraltracker/ui/Home.py

# Verify syntax
python3 -m py_compile viraltracker/ui/pages/30_📝_Content_Pipeline.py
python3 -m py_compile viraltracker/ui/pages/31_🎬_Editor_Handoff.py
```
