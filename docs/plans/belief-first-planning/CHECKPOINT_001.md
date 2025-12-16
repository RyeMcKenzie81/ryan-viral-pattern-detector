# Checkpoint 001 - Belief-First Planning

**Date**: 2025-12-15
**Status**: Phase 4 BUILD - Complete, Phase 5 Ready
**Branch**: `main`

---

## Completed

### Phase 1-3: Planning
- Requirements gathered via Q&A
- Architecture decision: Direct service calls (not pydantic-graph)
- Inventory complete: Identified reusable components

### Phase 4: BUILD (Partial)

#### 1. Database Migration
**File**: `sql/2025-12-15_belief_planning.sql`

Created 8 tables:
- `belief_offers` - Versioned offers (vs products.current_offer string)
- `belief_sublayers` - 6 canonical sub-layer types
- `belief_jtbd_framed` - Persona-framed JTBDs
- `belief_angles` - **Main new entity** - angle beliefs
- `belief_plans` - Plan config + compiled payload
- `belief_plan_angles` - Plan ↔ Angles junction
- `belief_plan_templates` - Plan ↔ Templates junction
- `belief_plan_runs` - Phase run tracking

**Status**: SQL written, not yet run on database

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

Also added enums:
- `SubLayerType`
- `AngleStatus`
- `PlanStatus`
- `TemplateStrategy`

**Status**: Syntax verified

#### 3. PlanningService
**File**: `viraltracker/services/planning_service.py`

Complete service with:
- **Brand/Product Helpers**: `get_brands()`, `get_products_for_brand()`, `get_product()`
- **Persona Helpers**: `get_personas_for_product()`, `get_persona()`
- **Offer CRUD**: `create_offer()`, `get_offers_for_product()`
- **JTBD CRUD**: `create_jtbd_framed()`, `get_jtbd_for_persona_product()`, `extract_jtbd_from_persona()`
- **Angle CRUD**: `create_angle()`, `get_angles_for_jtbd()`, `update_angle_status()`
- **Template Helpers**: `get_templates_for_brand()`
- **Plan CRUD**: `create_plan()`, `get_plan()`, `list_plans()`, `update_plan_status()`
- **Plan Compilation**: `compile_plan()`, `get_compiled_plan()`
- **Phase Validation**: `validate_phase()` - returns warnings
- **AI Suggestions**: `suggest_offers()`, `suggest_jtbd()`, `suggest_angles()` (Claude Opus 4.5)

**Status**: Syntax verified

#### 4. Service Export
**File**: `viraltracker/services/__init__.py`

Added exports for PlanningService and all planning models.

**Status**: Syntax verified

#### 5. Streamlit Wizard UI
**File**: `viraltracker/ui/pages/32_📋_Ad_Planning.py`

Complete 8-step wizard with:
- Session state management for wizard navigation
- Progress bar showing all 8 steps
- Brand → Product → Offer → Persona → JTBD → Angles → Templates → Review
- AI suggestion buttons at each step (Claude Opus 4.5)
- Validation warnings (Phase enforcement as warnings only)
- Plan compilation with JSON payload output

**Status**: Syntax verified

---

## Phase 5: Integration & Test

### Pending

1. **Run database migration**
   - SQL file: `sql/2025-12-15_belief_planning.sql`
   - Run via Supabase Dashboard SQL Editor
   - Creates 8 tables with RLS policies

2. **Test wizard flow end-to-end**
   - Run Streamlit app
   - Walk through all 8 steps with Wonder Paws
   - Verify AI suggestions work (requires valid Anthropic API key)
   - Test plan compilation

3. **Optional: Update AgentDependencies**
   - Add PlanningService to agent deps if needed later
   - Not required for UI-only workflow

---

## Key Decisions

1. **Architecture**: Direct service calls (not pydantic-graph) - wizard is user-driven
2. **AI Model**: Claude Opus 4.5 (`claude-opus-4-5-20251101`) for suggestions
3. **Sub-Layer Types**: 6 canonical types only (schema for future PHASE_3)
4. **Existing Data**: Reuse `products`, `personas_4d`, `ad_brief_templates` tables
5. **RLS**: Basic "all authenticated users" policy for MVP

---

## Files Changed

```
NEW:
- sql/2025-12-15_belief_planning.sql
- viraltracker/services/planning_service.py
- viraltracker/ui/pages/32_📋_Ad_Planning.py
- docs/plans/belief-first-planning/PLAN.md
- docs/plans/belief-first-planning/CHECKPOINT_001.md

MODIFIED:
- viraltracker/services/models.py (added planning models)
- viraltracker/services/__init__.py (added exports)
```

---

## Next Steps

1. **Run database migration** - Copy SQL from `sql/2025-12-15_belief_planning.sql` to Supabase Dashboard SQL Editor
2. **Test wizard end-to-end** - Run Streamlit UI and walk through all 8 steps
3. **Verify AI suggestions** - Test Claude Opus 4.5 integration for offers, JTBDs, and angles
4. **Test plan compilation** - Ensure compiled JSON payload is correct
5. **Commit and push changes**
