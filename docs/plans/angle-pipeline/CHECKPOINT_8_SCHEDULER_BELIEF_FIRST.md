# Checkpoint 8: Scheduler Belief-First Support

**Date:** 2026-01-05
**Phase:** 8 of 10
**Status:** Complete

## Summary

Added belief-first scheduling support to the Ad Scheduler, enabling users to schedule ad generation jobs that automatically loop through belief angles from plans or direct selections.

## Changes Made

### 1. Ad Scheduler UI (`viraltracker/ui/pages/24_📅_Ad_Scheduler.py`)

**New Features:**
- Extended `content_source` radio with 4 options:
  - `hooks` - Traditional hook-based generation (default)
  - `recreate_template` - Vary by product benefits
  - `plan` - Use a pre-configured belief plan
  - `angles` - Select specific angles directly

**Belief Plan Mode (`content_source='plan'`):**
- Dropdown to select a belief plan for the product
- Plan preview showing angles, templates, and ads_per_angle
- Estimated ads calculation with warning if >50
- Stores `plan_id` in job parameters

**Direct Angles Mode (`content_source='angles'`):**
- Cascading selection: Persona -> JTBD -> Angles
- Multi-select checkboxes for angle selection
- Status indicators for angle testing status (winner/loser/testing/untested)
- Stores `angle_ids`, `belief_persona_id`, `belief_jtbd_id` in parameters

**New Helper Functions:**
```python
def get_belief_plans_for_product(product_id: str)
def get_jtbd_for_persona_product(persona_id: str, product_id: str)
def get_angles_for_jtbd(jtbd_id: str)
def get_plan_details(plan_id: str)
```

**New Session State Variables:**
- `sched_content_source`
- `sched_selected_plan_id`
- `sched_selected_persona_id`
- `sched_selected_jtbd_id`
- `sched_selected_angle_ids`

### 2. Scheduler Worker (`viraltracker/worker/scheduler_worker.py`)

**New Constant:**
```python
MAX_ADS_PER_SCHEDULED_RUN = 50
```

**New Helper Functions:**
```python
def get_belief_plan(plan_id: str) -> Optional[Dict]
def get_angles_by_ids(angle_ids: List[str]) -> List[Dict]
```

**Modified `execute_ad_creation_job()`:**
- Added support for `content_source='plan'` and `content_source='angles'`
- Angle loop logic: For each angle -> For each template -> Generate N variations
- Angle context injected as additional instructions
- MAX_ADS_PER_SCHEDULED_RUN limit enforcement
- Tracks `angles_used` in job run data
- Summary logging with ads generated count

**Flow for Belief-First Modes:**
```
1. Load angles (from plan or by IDs)
2. Calculate potential ads: angles × templates × variations
3. Warn if exceeds 50 ad limit
4. For each angle:
   - For each template:
     - Generate variations with angle as context
     - Track progress against limit
     - Record template usage
```

## Database Schema

No schema changes required. Belief-first parameters stored in existing `parameters` JSONB column:

```json
// content_source='plan'
{
  "content_source": "plan",
  "plan_id": "uuid-of-belief-plan",
  ...
}

// content_source='angles'
{
  "content_source": "angles",
  "angle_ids": ["uuid-1", "uuid-2"],
  "belief_persona_id": "persona-uuid",
  "belief_jtbd_id": "jtbd-uuid",
  ...
}
```

## Files Modified

| File | Changes |
|------|---------|
| `viraltracker/ui/pages/24_📅_Ad_Scheduler.py` | Added belief-first UI, helper functions, session state |
| `viraltracker/worker/scheduler_worker.py` | Added angle loop logic, MAX limit, helper functions |

## Testing Notes

### Manual Testing Steps:
1. Navigate to Ad Scheduler page
2. Create new schedule with "Belief Plan" content source
3. Verify plan selection and preview work
4. Create schedule with "Direct Angles" content source
5. Verify persona -> JTBD -> angles cascade works
6. Verify angle checkboxes and selection tracking
7. Save job and verify parameters in database
8. (Optional) Run scheduler worker and verify angle looping

### Expected Behavior:
- Plan mode: Worker loads plan angles, loops through each
- Angles mode: Worker loads selected angles by ID
- Both: Each angle × template combination runs ad creation
- Limit: Stops after 50 ads generated per run
- Logs: Shows angle context and progress

## Integration Points

### Belief Planning System:
- Uses `PlanningService.get_plan()` for plan data
- Accesses `belief_angles` table for angle data
- Respects plan's persona_id and jtbd configuration

### Ad Creation Workflow:
- Angle context passed via `additional_instructions`
- Format: `ANGLE: {name}\nBELIEF: {belief_statement}`
- Uses hooks mode for content generation with angle guidance

## Next Phase

**Phase 9: Feedback Loop Foundation**
- Add angle performance tracking tables
- Connect ad performance to angles
- Build winner/loser analysis queries
- Create feedback UI component

## Notes

- No migration required - uses existing JSONB parameters field
- Backward compatible - existing jobs continue to work
- Plan mode uses job's template configuration, not plan's templates
- Direct angles mode requires full cascade selection
