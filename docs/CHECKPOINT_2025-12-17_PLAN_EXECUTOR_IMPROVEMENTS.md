# Checkpoint: Plan Executor Improvements

**Date:** 2025-12-17
**Branch:** feature/copy-scaffolds-template-eval
**Status:** Ready for Testing (blocked by rate limit)

---

## Summary

Implemented four key improvements to the Phase 1-2 Belief Plan Executor:

1. **Text Rendering Fix** - Restructured prompts to Nano Banana format
2. **Organization** - Link ads to angles, templates, and copy scaffolds
3. **Progress Updates** - Real-time database updates during execution
4. **Results Display** - UI shows ads grouped by angle with meta copy

---

## Problem Statement

After initial testing of the Plan Executor, several issues were identified:

| Issue | Description |
|-------|-------------|
| No text on images | Generated ads had no anchor text despite templates having text |
| No organization | Couldn't tell which angle/copy goes with which ad |
| No progress feedback | UI showed spinner with no updates during execution |
| No results display | Plan Executor didn't show generated ads after completion |

---

## Solution Details

### 1. Text Rendering Fix

**Root Cause:** The JSON prompt structure was too simple for Gemini Nano Banana. The model needs structured configs for proper text rendering.

**Fix:** Restructured `build_phase12_prompt()` to match the proven Nano Banana format:

```python
json_prompt = {
    "task": {
        "action": "create_phase12_belief_ad",
        "variation_index": variation_index,
        "template_type": template_type
    },
    "content": {
        "headline": {
            "text": anchor_text,
            "placement": "match_template",
            "render_requirement": "MUST render this text exactly, pixel-perfect legible"
        },
        "situation": situation,
        "belief_being_tested": angle.get("belief_statement")
    },
    "style": {
        "canvas_size": canvas_size,
        "text_placement": text_placement,
        "fonts": {
            "body": {
                "family": "sans-serif",
                "weights": ["400", "600", "700"],
                "style_notes": "Match template text style exactly"
            }
        },
        "colors": {
            "mode": "original",
            "palette": template_colors
        }
    },
    "rules": {
        "text": {
            "render_exactly": anchor_text,
            "position": "match_template_text_position",
            "requirement": "Text MUST be pixel-perfect legible"
        },
        "product": {
            "show_product": False,
            "requirement": "ABSOLUTELY NO product bottles, supplements, pills"
        }
    },
    "instructions": {
        "CRITICAL": [
            f"RENDER TEXT EXACTLY: '{anchor_text}'",
            "Match template STYLE - same composition, colors, text placement",
            "Show the SITUATION (recognition moment), NOT a product"
        ]
    }
}
```

### 2. Organization (Belief Metadata)

**Database Migration:** `sql/migration_generated_ads_belief_metadata.sql`

```sql
ALTER TABLE generated_ads ADD COLUMN IF NOT EXISTS angle_id UUID REFERENCES belief_angles(id);
ALTER TABLE generated_ads ADD COLUMN IF NOT EXISTS template_id UUID;
ALTER TABLE generated_ads ADD COLUMN IF NOT EXISTS belief_plan_id UUID REFERENCES belief_plans(id);
ALTER TABLE generated_ads ADD COLUMN IF NOT EXISTS meta_headline TEXT;
ALTER TABLE generated_ads ADD COLUMN IF NOT EXISTS meta_primary_text TEXT;

CREATE INDEX IF NOT EXISTS idx_generated_ads_angle ON generated_ads(angle_id);
CREATE INDEX IF NOT EXISTS idx_generated_ads_belief_plan ON generated_ads(belief_plan_id);
CREATE INDEX IF NOT EXISTS idx_generated_ads_template ON generated_ads(template_id);
```

**Service Update:** Added params to `AdCreationService.save_generated_ad()`:
- `angle_id` - Which belief angle this ad tests
- `template_id` - Which template was used as style reference
- `belief_plan_id` - Which belief plan this ad belongs to
- `meta_headline` - Headline for Meta ad (below image)
- `meta_primary_text` - Primary text for Meta ad (above image)

### 3. Progress Updates

**State Change:** Added `pipeline_run_id` to `BeliefPlanExecutionState`

**Pipeline Update:** `GenerateImagesNode` now updates database after each image:

```python
if ctx.state.pipeline_run_id:
    db.table("pipeline_runs").update({
        "current_node": "GenerateImagesNode",
        "state_snapshot": {
            "current_step": "generating",
            "ads_generated": ctx.state.ads_generated,
            "total_ads_planned": ctx.state.total_ads_planned,
            "current_prompt": i + 1,
            "current_angle": prompt.get("angle_name", ""),
            "current_template": prompt.get("template_name", "")
        }
    }).eq("id", ctx.state.pipeline_run_id).execute()
```

### 4. Results Display

**Pipeline Return:** `ReviewAdsNode` now returns `ads_by_angle` dict:

```python
ads_by_angle = {
    "angle_id": {
        "angle_name": "Angle Name",
        "belief_statement": "...",
        "ads": [
            {
                "ad_id": "...",
                "storage_path": "...",
                "template_name": "...",
                "meta_headline": "...",
                "meta_primary_text": "...",
                "final_status": "approved"
            }
        ],
        "approved": 2,
        "rejected": 1,
        "failed": 0
    }
}
```

**UI Component:** Added `render_results_by_angle()` function that displays:
- Expandable sections per angle with approval stats
- 3-column grid of generated images
- Status badges (approved/rejected/failed)
- Copy scaffolds in expandable "Meta Copy" sections

---

## Files Modified

| File | Changes |
|------|---------|
| `sql/migration_generated_ads_belief_metadata.sql` | NEW - Add belief metadata columns |
| `viraltracker/pipelines/belief_plan_execution.py` | Restructured prompt, progress updates, grouped results |
| `viraltracker/pipelines/states.py` | Added `pipeline_run_id` field |
| `viraltracker/services/ad_creation_service.py` | Added belief metadata params to `save_generated_ad()` |
| `viraltracker/ui/pages/35_🎯_Plan_Executor.py` | Added results display UI |

---

## Testing Checklist

- [ ] Run migration (DONE)
- [ ] Execute plan with 1 angle × 1 template × 1 variation
- [ ] Verify text appears on generated image
- [ ] Verify progress updates in pipeline_runs during execution
- [ ] Verify results display grouped by angle in UI
- [ ] Verify generated_ads has angle_id, template_id, meta_headline, meta_primary_text
- [ ] Check Ad History shows ads with belief metadata

---

## Known Issues

- **Rate Limiting:** Gemini API daily quota can be exhausted quickly when generating many images
- **Testing Blocked:** Need to wait for rate limit reset to verify text rendering fix

---

## Related Files

- Previous checkpoint: `docs/CHECKPOINT_2025-12-16_PLAN_EXECUTOR.md`
- Plan document: `~/.claude/plans/logical-sparking-lemur.md`
- Architecture: `docs/architecture.md`
