# Checkpoint: Phase 1-2 Plan Executor Pipeline

**Date:** 2025-12-16
**Status:** Ready for Testing
**Context Tokens:** ~40K

---

## Summary

Created a dedicated **Plan Executor** tool using pydantic-graph to execute Phase 1-2 belief testing plans. This replaces the `belief_plan` option that was previously in Ad Creator with a properly-designed workflow.

### Why This Change?

The original Ad Creator had issues for Phase 1-2 belief plans:
1. Product images were composited onto ads (violates Phase 1-2 rules)
2. Benefits appeared on generated ads (Phase 1-2 should only show situations)
3. Templates were used as final images, not style references

### Phase 1-2 Creative Rules

| Location | Content | Example |
|----------|---------|---------|
| ON Image | Anchor text only | "Noticing this?" |
| Below Image (Meta Headline) | Angle + reframe | "Joint stiffness isn't age..." |
| Above Image (Meta Primary) | Full copy scaffold | "If you've noticed..." |

**Key Principles:**
- Image shows the situation/recognition moment, NOT the solution
- No product images composited
- No benefits, claims, or mechanisms on the image
- Only observational anchor text from templates

---

## Files Created

### 1. Migration: `sql/migration_belief_plan_execution.sql`
```sql
ALTER TABLE pipeline_runs ADD COLUMN IF NOT EXISTS belief_plan_id UUID REFERENCES belief_plans(id);
CREATE INDEX IF NOT EXISTS idx_pipeline_runs_belief_plan ON pipeline_runs(belief_plan_id);
ALTER TABLE pipeline_runs ADD COLUMN IF NOT EXISTS product_id UUID REFERENCES products(id);
CREATE INDEX IF NOT EXISTS idx_pipeline_runs_product ON pipeline_runs(product_id);
```

### 2. Pipeline: `viraltracker/pipelines/belief_plan_execution.py`

Complete pydantic-graph pipeline with 4 nodes:

| Node | Purpose |
|------|---------|
| `LoadPlanNode` | Loads plan, validates Phase 1-2, loads persona/JTBD |
| `BuildPromptsNode` | Creates prompts for all angle × template × variation combos |
| `GenerateImagesNode` | Generates images with template as style reference only |
| `ReviewAdsNode` | Reviews with Phase 1-2 specific criteria |

**Helper Functions:**
- `build_phase12_prompt()` - Builds prompts using template as style reference
- `review_phase12_ad()` - Reviews ads with Phase 1-2 criteria (no product, situation only)

**Generation Math:** `angles × templates × variations_slider = total ads`

### 3. State: `viraltracker/pipelines/states.py` (modified)

Added `BeliefPlanExecutionState` dataclass:
```python
@dataclass
class BeliefPlanExecutionState:
    # Input parameters
    belief_plan_id: UUID
    variations_per_angle: int = 3
    canvas_size: str = "1080x1080px"

    # Populated by LoadPlanNode
    plan_data: Optional[Dict] = None
    phase_id: int = 1
    angles: List[Dict] = field(default_factory=list)
    templates: List[Dict] = field(default_factory=list)
    persona_data: Optional[Dict] = None
    jtbd_data: Optional[Dict] = None

    # Populated by BuildPromptsNode
    prompts: List[Dict] = field(default_factory=list)
    total_ads_planned: int = 0

    # Populated by GenerateImagesNode
    generated_ads: List[Dict] = field(default_factory=list)
    ad_run_id: Optional[UUID] = None

    # Populated by ReviewAdsNode
    approved_count: int = 0
    rejected_count: int = 0

    # Tracking
    current_step: str = "pending"
    error: Optional[str] = None
    ads_generated: int = 0
    ads_reviewed: int = 0
```

### 4. UI: `viraltracker/ui/pages/35_🎯_Plan_Executor.py`

Features:
- Brand → Product → Belief Plan selection cascade
- Plan summary showing angles, templates, persona, JTBD
- Configuration form (variations slider 1-5, canvas size)
- Generation math display: `X angles × Y templates × Z variations = N ads`
- Execute button that runs the graph pipeline
- Run history showing previous executions with status

---

## Files Modified

### 1. `viraltracker/pipelines/__init__.py`
Added exports for new pipeline:
```python
from .belief_plan_execution import (
    belief_plan_execution_graph,
    run_belief_plan_execution,
    LoadPlanNode,
    BuildPromptsNode,
    GenerateImagesNode,
    ReviewAdsNode,
)
```

### 2. `viraltracker/ui/pages/01_🎨_Ad_Creator.py`
- Removed `belief_plan` from content source options
- Removed all belief_plan UI sections (~400 lines)
- Removed belief_plan helper functions
- Added redirect message: "For Phase 1-2 belief plans, use the Plan Executor page instead"
- Cleaned up run_workflow() to remove belief_plan_id parameter

### 3. `viraltracker/agent/agents/ad_creation_agent.py`
- Removed `belief_plan_id` parameter from `complete_ad_workflow()`
- Removed `belief_plan` from valid_content_sources
- Removed Stage 3 belief_plan skip logic
- Removed Stage 6 belief_plan angle retrieval (~110 lines)
- Updated docstrings

---

## Testing Checklist

### Migration
- [ ] Run migration: `psql < sql/migration_belief_plan_execution.sql`
- [ ] Verify columns exist: `\d pipeline_runs`

### Plan Executor UI
- [ ] Navigate to Plan Executor page in Streamlit
- [ ] Select brand → product → belief plan
- [ ] Verify plan summary displays correctly
- [ ] Adjust variations slider
- [ ] Click Execute Plan
- [ ] Monitor progress

### Pipeline Execution
- [ ] Verify `LoadPlanNode` loads plan data
- [ ] Verify `BuildPromptsNode` creates correct number of prompts
- [ ] Verify `GenerateImagesNode` generates images without product compositing
- [ ] Verify `ReviewAdsNode` reviews with Phase 1-2 criteria
- [ ] Check `pipeline_runs` table for run record

### Ad Creator
- [ ] Verify belief_plan option is gone
- [ ] Verify redirect message appears
- [ ] Verify hooks and recreate_template still work

---

## Architecture

```
User selects plan in UI
        │
        ▼
┌─────────────────────────────────────────────────────────────┐
│                    Plan Executor UI                          │
│  - Brand/Product/Plan selection                              │
│  - Variations slider                                         │
│  - Execute button                                            │
└─────────────────────────────────────────────────────────────┘
        │
        ▼
┌─────────────────────────────────────────────────────────────┐
│              run_belief_plan_execution()                     │
│  - Creates BeliefPlanExecutionState                          │
│  - Runs belief_plan_execution_graph                          │
│  - Tracks in pipeline_runs table                             │
└─────────────────────────────────────────────────────────────┘
        │
        ▼
┌──────────────┐    ┌──────────────┐    ┌──────────────┐    ┌──────────────┐
│ LoadPlanNode │ -> │BuildPrompts  │ -> │GenerateImages│ -> │ ReviewAds    │
│              │    │   Node       │    │    Node      │    │    Node      │
│ - Validate   │    │ - angles ×   │    │ - Template   │    │ - No product │
│   Phase 1-2  │    │   templates  │    │   as style   │    │ - Situation  │
│ - Load JTBD  │    │   × vars     │    │   reference  │    │   only       │
│ - Load       │    │ - Build JSON │    │ - Anchor     │    │ - Text check │
│   persona    │    │   prompts    │    │   text only  │    │              │
└──────────────┘    └──────────────┘    └──────────────┘    └──────────────┘
```

---

## Dependencies

### Existing (already built)
- `copy_scaffolds` table
- `angle_copy_sets` table
- `template_evaluations` table
- `pipeline_runs` table
- `CopyScaffoldService`
- `TemplateEvaluationService`

### Services Used
- `AdCreationService` - For image upload, ad run tracking
- `GeminiService` - For image generation and review

---

## Next Steps

1. **Test the pipeline** - Execute a real belief plan through the UI
2. **Tune review criteria** - Adjust Phase 1-2 review prompts based on results
3. **Add progress tracking** - Real-time UI updates during generation
4. **Batch optimization** - Parallel generation for speed

---

## Related Files

- Plan document: `docs/plans/PLAN_belief_plan_executor.md` (in ~/.claude/plans/)
- Previous checkpoint: `docs/CHECKPOINT_2025-12-15_COPY_SCAFFOLDS.md`
- Architecture: `docs/architecture.md`
