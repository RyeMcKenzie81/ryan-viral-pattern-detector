# Checkpoint 010: MVP 4 - Asset Management Started

**Date**: 2025-12-11
**Context**: MVP 4 planning complete, ready to implement AssetManagementService
**Branch**: `feature/trash-panda-content-pipeline`

---

## Session Summary

MVP 3 was merged to main. MVP 4 (Asset Management) planning is complete.

---

## What Was Done This Session

1. **Merged MVP 3 to main** - Audio pipeline complete
2. **Synced feature branch** with latest main (includes competitor products feature)
3. **Updated PLAN.md** - Phase 4 marked COMPLETE, Phase 5 marked IN PROGRESS
4. **Planned MVP 4** - Asset Management implementation

---

## MVP 4 Plan: Asset Management

### User Preferences (from this session)
- **Extraction method**: Gemini AI parsing (not simple regex)
- **Asset library**: User has core assets + other assets to import

### What Exists
- DB tables: `comic_assets`, `project_asset_requirements` (schema ready in migration)
- Script structure: `visual_notes` per beat contains asset references
- State: `ContentPipelineState` has asset fields
- UI: 4 tabs (Generate, Review, Approve, Audio)
- GeminiService: Has `analyze_text()` method for AI parsing

### What to Build

**1. AssetManagementService** (`viraltracker/services/content_pipeline/services/asset_service.py`)
```python
class AssetManagementService:
    """Manage visual assets for content pipeline."""

    async def extract_requirements(self, script_version_id: UUID) -> List[Dict]:
        """Parse visual_notes with Gemini to identify assets needed."""

    def match_existing_assets(self, requirements: List[Dict], brand_id: UUID) -> Tuple[List, List]:
        """Split into matched and unmatched requirements."""

    async def save_requirements(self, project_id: UUID, requirements: List[Dict]) -> None:
        """Save to project_asset_requirements table."""

    async def get_requirements(self, project_id: UUID) -> List[Dict]:
        """Fetch requirements from DB."""

    async def get_asset_library(self, brand_id: UUID, asset_type: str = None) -> List[Dict]:
        """List assets from comic_assets table."""

    async def upload_asset(self, brand_id: UUID, asset_data: Dict, image_file) -> UUID:
        """Upload new asset to library."""
```

**2. Assets Tab in UI** (add to `30_📝_Content_Pipeline.py`)
- "Extract Assets" button → calls service with Gemini
- Display extracted requirements (matched vs unmatched)
- Asset library browser with filters
- Upload/import existing assets
- "Mark Assets Complete" button

**3. Integration**
- Wire service into `ContentPipelineService`
- Update workflow state transitions

---

## Key Files to Modify

```
viraltracker/services/content_pipeline/services/asset_service.py  # CREATE
viraltracker/services/content_pipeline/content_pipeline_service.py  # Wire up service
viraltracker/ui/pages/30_📝_Content_Pipeline.py  # Add Assets tab
```

---

## Database Tables (Already Created)

**comic_assets**:
- id, brand_id, asset_type (character|prop|background|effect)
- name, description, tags[]
- prompt_template, style_suffix
- image_url, thumbnail_url, is_core_asset

**project_asset_requirements**:
- id, project_id, asset_id (FK, nullable)
- asset_name, asset_description, suggested_prompt
- script_reference, status (needed|matched|generating|generated|approved|rejected)
- generated_image_url, human_approved, rejection_reason

---

## Gemini Asset Extraction Prompt (Draft)

```python
ASSET_EXTRACTION_PROMPT = """Analyze these visual notes from a video script and identify all visual assets needed.

For each asset, classify it as:
- character: Named characters (Every-Coon, Fed, Boomer, etc.)
- prop: Objects, items, tools
- background: Scene backgrounds, environments
- effect: Visual effects, overlays, animations

Return JSON:
{
    "assets": [
        {
            "name": "Asset name (lowercase-hyphenated)",
            "type": "character|prop|background|effect",
            "description": "Visual description",
            "script_reference": "Which beat/scene needs this",
            "suggested_prompt": "Image generation prompt if needed"
        }
    ]
}
"""
```

---

## Next Steps (for new session)

1. Create `asset_service.py` with Gemini extraction
2. Add Assets tab to UI
3. Add asset upload/import capability
4. Test extraction on existing approved script
5. Verify syntax with `python3 -m py_compile`

---

## Commands to Resume

```bash
cd /Users/ryemckenzie/projects/viraltracker/viraltracker-planning
git checkout feature/trash-panda-content-pipeline
source ../venv/bin/activate

# Verify branch state
git status
git log --oneline -3
```

---

**Status**: MVP 4 Planning Complete, Ready to Implement
