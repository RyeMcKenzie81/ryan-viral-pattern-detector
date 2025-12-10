# Checkpoint: Additional Instructions Feature

**Date**: 2025-12-09
**Branch**: `feature/comic-panel-video-system`

---

## Summary

Implemented hybrid brand defaults + run-specific instructions for ad generation. Allows brands to set persistent preferences (e.g., "white backdrops work best") while also supporting one-off instructions per run.

---

## What Was Completed

### 1. Database Migration

**File**: `migrations/2025-12-09_add_brand_ad_creation_notes.sql`

```sql
ALTER TABLE brands ADD COLUMN ad_creation_notes text;
COMMENT ON COLUMN brands.ad_creation_notes IS 'Default instructions/notes for ad generation';
```

### 2. Brand Manager UI

**File**: `viraltracker/ui/pages/05_🏢_Brand_Manager.py`

Added "Ad Creation Notes" section to brand details:
- Text area for persistent brand-level instructions
- Examples: "white backdrops work best", "always show product in use"
- Auto-saves on change

### 3. Ad Creator UI

**File**: `viraltracker/ui/pages/01_🎨_Ad_Creator.py`

Added "Additional Instructions (Optional)" section (Section 2.7):
- Shows brand's default notes as reference caption
- Text area for run-specific instructions
- Stored in session state as `additional_instructions`
- Passed to `run_workflow()` function

### 4. Ad Scheduler UI

**File**: `viraltracker/ui/pages/04_📅_Ad_Scheduler.py`

Added "Additional Instructions (Optional)" section (Section 5.7):
- Shows brand's default notes as reference
- Text area for job-specific instructions
- Stored in job `parameters` as `additional_instructions`
- Displayed in job detail view

### 5. Ad Creation Workflow

**File**: `viraltracker/agent/agents/ad_creation_agent.py`

Updated `complete_ad_workflow()`:
- Added `additional_instructions: Optional[str] = None` parameter
- Stage 2d: Fetches brand's `ad_creation_notes` from database
- Combines brand notes + run instructions into `combined_instructions`
- Stores in `product_dict['combined_instructions']`
- Logged in `run_parameters` for tracking

Updated `generate_nano_banana_prompt()`:
- Added "SPECIAL INSTRUCTIONS" section to prompt when `combined_instructions` exists
- Instructions appear after Critical Requirements section

### 6. Scheduler Worker

**File**: `viraltracker/worker/scheduler_worker.py`

Updated `complete_ad_workflow()` call:
- Added `additional_instructions=params.get('additional_instructions')`

---

## How It Works

### Flow:
1. Brand sets default `ad_creation_notes` in Brand Manager (e.g., "white backdrops work best")
2. User creates ad run in Ad Creator or schedules job in Ad Scheduler
3. User can optionally add run-specific instructions
4. Workflow fetches brand's `ad_creation_notes` from database
5. Combines: `{brand_notes}\n\n**Run-specific instructions:**\n{additional_instructions}`
6. Combined instructions injected into prompt as "SPECIAL INSTRUCTIONS"

### Prompt Injection:
```
**SPECIAL INSTRUCTIONS (FOLLOW CAREFULLY):**
White backdrops work best for this brand

**Run-specific instructions:**
Feature the Matcha flavor prominently
```

---

## Files Modified

| File | Changes |
|------|---------|
| `migrations/2025-12-09_add_brand_ad_creation_notes.sql` | New migration |
| `viraltracker/ui/pages/05_🏢_Brand_Manager.py` | Ad Creation Notes section |
| `viraltracker/ui/pages/01_🎨_Ad_Creator.py` | Additional Instructions UI + session state |
| `viraltracker/ui/pages/04_📅_Ad_Scheduler.py` | Additional Instructions UI + params |
| `viraltracker/agent/agents/ad_creation_agent.py` | Parameter + fetch + combine + inject |
| `viraltracker/worker/scheduler_worker.py` | Pass additional_instructions |

---

## Usage Example

### Setting Brand Defaults:
1. Go to Brand Manager
2. Select brand (e.g., Infi)
3. Find "Ad Creation Notes" section
4. Enter: "White backdrops work best. Always feature product prominently."
5. Click "Save Ad Creation Notes"

### Adding Run-Specific Instructions:
1. Go to Ad Creator
2. Select product
3. Find "Additional Instructions (Optional)" section
4. See brand defaults displayed as reference
5. Add: "Feature the Brown Sugar flavor. Include summer theme."
6. Run workflow

---

## Related Features

- **Product Variants** (same session): Allows selecting specific flavor/size/color
- **4D Personas** (Sprint 5): Persona targeting for ad copy
- **Variant Selector**: Added to both Ad Creator and Scheduler

---

## Next Steps

1. Run migration on production database
2. Set Infi's brand notes: "White backdrops work best"
3. Test ad generation with combined instructions
