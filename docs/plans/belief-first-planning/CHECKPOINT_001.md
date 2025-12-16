# Checkpoint 001 - Belief-First Planning

**Date**: 2025-12-15
**Status**: Phase 6 POLISH - Complete
**Branch**: `feature/belief-first-planning`

---

## Completed

### Phase 1-3: Planning
- Requirements gathered via Q&A
- Architecture decision: Direct service calls (not pydantic-graph)
- Inventory complete: Identified reusable components

### Phase 4: BUILD

#### 1. Database Migration
**Files**:
- `sql/2025-12-15_belief_planning.sql` - Main tables
- `sql/2025-12-15_belief_planning_fix_templates.sql` - FK fix for scraped templates

Created 8 tables:
- `belief_offers` - Versioned offers (vs products.current_offer string)
- `belief_sublayers` - 6 canonical sub-layer types
- `belief_jtbd_framed` - Persona-framed JTBDs
- `belief_angles` - **Main new entity** - angle beliefs
- `belief_plans` - Plan config + compiled payload
- `belief_plan_angles` - Plan ↔ Angles junction
- `belief_plan_templates` - Plan ↔ Templates junction (+ template_source column)
- `belief_plan_runs` - Phase run tracking

**Status**: Deployed to production

#### 2. Pydantic Models
**File**: `viraltracker/services/models.py` (appended)

Added models:
- `BeliefOffer`
- `BeliefSubLayer`
- `BeliefJTBDFramed`
- `BeliefAngle`
- `BeliefPlan`
- `BeliefPlanRun`
- `CompiledPlanPayload`

**Status**: Complete

#### 3. PlanningService
**File**: `viraltracker/services/planning_service.py`

Complete service with:
- **Brand/Product Helpers**: `get_brands()`, `get_products_for_brand()`, `get_product()`
- **Persona Helpers**: `get_personas_for_product()`, `get_persona()`
- **Offer CRUD**: `create_offer()`, `get_offers_for_product()`
- **JTBD CRUD**: `create_jtbd_framed()`, `get_jtbd_for_persona_product()`, `extract_jtbd_from_persona()`
- **Angle CRUD**: `create_angle()`, `get_angles_for_jtbd()`, `update_angle_status()`
- **Template Helpers**: `get_templates_for_brand()` - queries both ad_brief_templates and scraped_templates
- **Plan CRUD**: `create_plan()`, `get_plan()`, `list_plans()`, `update_plan_status()`
- **Plan Compilation**: `compile_plan()`, `get_compiled_plan()`
- **Phase Validation**: `validate_phase()` - returns warnings
- **AI Suggestions**: `suggest_offers()`, `suggest_jtbd()`, `suggest_angles()` (Claude Opus 4.5)

**Status**: Complete

#### 4. Service Export
**File**: `viraltracker/services/__init__.py`

Added exports for PlanningService and all planning models.

**Status**: Complete

#### 5. Streamlit Wizard UI
**File**: `viraltracker/ui/pages/32_📋_Ad_Planning.py`

Complete 8-step wizard with:
- Session state management for wizard navigation
- Progress bar showing all 8 steps
- Brand → Product → Offer → Persona → JTBD → Angles → Templates → Review
- AI suggestion buttons at each step (Claude Opus 4.5)
- Extracted JTBDs from persona with "Use" buttons
- Both manual and scraped templates displayed
- Validation warnings (Phase enforcement as warnings only)
- Plan save with summary display

**Status**: Complete

### Phase 5: Integration & Test

#### Bugs Fixed During Testing
1. **Persona query**: Fixed to query both `product_id` on `personas_4d` and `product_personas` junction table
2. **domain_sentiment column**: Removed non-existent column from persona query
3. **JTBD extraction**: Fixed to read `outcomes_jtbd` as top-level field (not nested in domain_sentiment)
4. **JTBD selection**: Made "Use" buttons create and select JTBDs directly
5. **Template FK constraint**: Added migration to allow scraped_templates, added `template_source` column
6. **Template selection**: Updated to track source (ad_brief_templates vs scraped_templates)
7. **Validate button**: Fixed to show feedback inline without page rerun
8. **Save plan**: Simplified to skip compile step (RLS read-back issue)

#### Test Results
- Successfully created plan with Wonder Paws / Collagen 3X Drops
- 5 angles, 3 templates, 15 total ads configured
- Plan ID: `90bff4aa-180b-49d7-af9e-a5e6cbde0e08`

---

## Key Decisions

1. **Architecture**: Direct service calls (not pydantic-graph) - wizard is user-driven
2. **AI Model**: Claude Opus 4.5 (`claude-opus-4-5-20251101`) for suggestions
3. **Sub-Layer Types**: 6 canonical types only (schema for future PHASE_3)
4. **Existing Data**: Reuse `products`, `personas_4d`, `ad_brief_templates`, `scraped_templates` tables
5. **RLS**: Basic "all authenticated users" policy for MVP
6. **Template Sources**: Support both manual (`ad_brief_templates`) and scraped (`scraped_templates`)

---

## Files Changed

```
NEW:
- sql/2025-12-15_belief_planning.sql
- sql/2025-12-15_belief_planning_fix_templates.sql
- viraltracker/services/planning_service.py
- viraltracker/ui/pages/32_📋_Ad_Planning.py
- docs/plans/belief-first-planning/PLAN.md
- docs/plans/belief-first-planning/CHECKPOINT_001.md

MODIFIED:
- viraltracker/services/models.py (added planning models)
- viraltracker/services/__init__.py (added exports)
```

---

## What's Next

### Phase 6: Polish - COMPLETE

1. ✅ **Fix compile_plan template source issue** - Updated `get_plan()` to query both `ad_brief_templates` and `scraped_templates` based on `template_source` column
2. ✅ **Add template preview** - Shows template images and text in selection UI
3. ✅ **Plan list view** - Added `33_📊_Plan_List.py` page to view and manage existing plans

### Future (Integration with Ad Creator)
1. **Connect to Ad Creator** - Feed compiled plan payload to ad generation
2. **Track results** - Store performance data in `belief_plan_runs`
3. **Implement PHASE_2+** - Confirmation testing, sub-layers, etc.

---

## Commits

- `d7dad72` - feat: Add belief-first ad planning system
- `2ac9db5` - fix: Query personas from both direct product_id and junction table
- `0bed41b` - fix: Remove non-existent domain_sentiment column from persona query
- `718d5df` - fix: Extract JTBDs from top-level outcomes_jtbd field
- `8d33a63` - fix: Make JTBD selection buttons create and select directly
- `d660bd8` - feat: Include both manual and scraped templates in planning wizard
- `79858ba` - fix: Support both manual and scraped templates in plans
- `d50e420` - fix: Validate button shows inline feedback, simplify save
- `4c41f8e` - feat: Add template preview with images and text
- `1357b04` - feat: Add plan list page to view/manage plans
- `f1c1e43` - fix: Handle both template sources in compile_plan
