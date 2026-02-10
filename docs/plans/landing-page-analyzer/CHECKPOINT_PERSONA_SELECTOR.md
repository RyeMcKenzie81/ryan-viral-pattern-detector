# Checkpoint: Persona Selector for Blueprint Generation

**Date:** 2026-02-10
**Status:** Complete and deployed

## What Was Built

Added an optional "Target Persona" dropdown to the Blueprint tab. When a persona is selected, a targeting directive is injected into the LLM prompt so the blueprint optimizes all copy direction, emotional hooks, and brand mappings for that specific persona. When "Auto" is selected (default), existing behavior is preserved — the LLM picks the best-fit persona.

## Changes (3 files + 2 migrations)

### Service Layer

**`brand_profile_service.py`**
- Added `get_personas_for_product(product_id)` — public wrapper around `_fetch_personas()` returning `id`, `name`, `snapshot` for UI dropdowns

**`blueprint_service.py`**
- `generate_blueprint()` — new optional `persona_id` param
- `_lookup_persona(product_id, persona_id)` — fetches full persona from `personas_4d` for the directive
- `_run_reconstruction()` — new optional `target_persona` dict param, passed to both chunk builders
- `_build_chunk_user_prompt()` — when `target_persona` provided:
  - Chunk 1: appends `## TARGET PERSONA (REQUIRED)` with full persona data (name, snapshot, pain points, desires, buying objections, activation events)
  - Chunk 2: appends `## TARGET PERSONA REMINDER` with persona name
- `_create_blueprint_record()` — now persists `persona_id` to the DB for traceability

### UI Layer

**`33_🏗️_Landing_Page_Analyzer.py`**
- Added `_get_personas_for_product()` helper (follows existing `_get_products_for_brand` / `_get_offer_variants` pattern)
- Added persona dropdown in `render_blueprint_tab()` below Product/Offer Variant selectors
  - Hidden when no personas exist for the product
  - "Auto (let AI choose)" default with persona name + snapshot preview
- Threaded `persona_id` through `_run_blueprint_generation()` to the service call

### Migrations

- `2026-02-09_landing_page_blueprints_add_persona_id.sql` — adds nullable `persona_id UUID` column
- `2026-02-10_landing_page_blueprints_add_partial_status.sql` — fixes pre-existing bug: adds `'partial'` to the status CHECK constraint (was missing, caused constraint violation when chunk 2 failed)

## Edge Cases Handled

| Case | Behavior |
|------|----------|
| No personas for product | Dropdown hidden, `persona_id=None`, auto behavior |
| "Auto" selected | `persona_id=None`, no directive added, LLM picks |
| Persona selected | Full persona data injected as directive in prompts |
| Persona ID not found | Log warning, fall back to auto (no crash) |

## Data Flow

```
UI: persona dropdown → persona_id
  ↓
generate_blueprint(persona_id=...)
  → _lookup_persona() fetches full persona from personas_4d
  → _create_blueprint_record(persona_id=...) persists to DB
  ↓
_run_reconstruction(target_persona={name, snapshot, pain_points, ...})
  ↓
_build_chunk_user_prompt(target_persona=...)
  → Chunk 1: "## TARGET PERSONA (REQUIRED)" directive
  → Chunk 2: "## TARGET PERSONA REMINDER" directive
```

## Verified

- All 3 files pass `python3 -m py_compile`
- Post-plan review: PASS (all G1-G6 checks clean)
- Blueprint generates successfully with persona selected
- Persona dropdown renders with snapshot previews
- "Partial" status now saves correctly (constraint fix)
