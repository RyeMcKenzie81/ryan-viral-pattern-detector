# Checkpoint: Phase 2 (Reconstruction Blueprint)

**Date:** 2026-02-09
**Status:** Complete

## What Was Built

### Phase 2A — Brand Profile + Blueprint Service

**BrandProfileService (`brand_profile_service.py`):**
- Aggregates data from 8+ tables into a unified brand profile
- Data sources: brands, products, product_offer_variants, product_mechanisms, personas_4d, product_variants (pricing), amazon_review_analysis, competitors
- Gap detection: `_identify_gaps()` checks each profile section for missing data, returns structured list with severity (critical/moderate/low) and human-readable instructions
- Offer variant support: defaults to `is_default=True` variant, falls back to first active variant
- Pattern follows `product_context_service.py`: graceful fallbacks when tables/data don't exist

**ReconstructionBlueprintService (`blueprint_service.py`):**
- Orchestrates Skill 5: analysis + brand profile → reconstruction blueprint
- Pipeline: load analysis → aggregate brand profile → run LLM → save to DB
- 4-step progress callback for UI integration
- Partial failure handling: creates record first, updates on completion/failure
- Extracts metadata: sections_count, elements_mapped, content_needed_count
- Stores brand_profile_snapshot for audit trail
- Query methods: `get_blueprint()`, `list_blueprints(org_id, analysis_id, brand_id)`

**Skill 5 Prompt (`prompts/reconstruction.py`):**
- Comprehensive system prompt for section-by-section creative brief generation
- Maps each competitor element to brand equivalent with specific data references
- Content status logic: populated / partial / CONTENT_NEEDED
- Awareness level adaptation rules
- Compliance integration: checks disallowed_claims for every section
- Gap analysis bonus sections: adds elements the competitor missed but should have
- Output schema: strategy_summary, sections[], bonus_sections[], content_needed_summary[], metadata

**Database Migration (`2026-02-09_landing_page_blueprints.sql`):**
- `landing_page_blueprints` table with org_id, analysis_id, brand_id, product_id, offer_variant_id
- Blueprint JSONB storage with denormalized counts (sections, mapped, content_needed)
- Brand profile snapshot and content gaps for audit
- RLS policies, updated_at trigger, indexes

### Phase 2B — Blueprint UI (Tab 3)

**Tab 3 "Blueprint" on page 33:**
- Product selector dropdown (from brand's products)
- Offer variant selector (defaults to default variant, shows "(default)" label)
- Analysis selector (completed/partial analyses with URL + grade + date)
- "Generate Blueprint" button with 4-step progress bar
- Strategy summary card (awareness adaptation, tone, architecture, differentiators)
- Section-by-section accordion:
  - Status badges: 🟢 Populated / 🟡 Partial / 🔴 CONTENT NEEDED
  - Each section shows: competitor approach, brand mapping, copy direction, improvements, compliance notes
  - CONTENT NEEDED sections auto-expanded with action items
- Bonus sections (from gap analysis) displayed separately
- Content needed summary with priority levels
- Brand profile gaps displayed in collapsible section
- Export: JSON download + Markdown download
- Past blueprints history with expandable detail
- Unique Streamlit keys prevent collisions when multiple blueprints rendered

## New Files

| File | Purpose |
|------|---------|
| `migrations/2026-02-09_landing_page_blueprints.sql` | Blueprint table schema |
| `viraltracker/services/landing_page_analysis/brand_profile_service.py` | Brand data aggregation + gap detection + lookup helpers |
| `viraltracker/services/landing_page_analysis/blueprint_service.py` | Skill 5 orchestration + persistence |
| `viraltracker/services/landing_page_analysis/prompts/reconstruction.py` | Skill 5 system prompt |
| `viraltracker/services/landing_page_analysis/utils.py` | Shared `parse_llm_json()` utility |
| `docs/plans/landing-page-analyzer/CHECKPOINT_PHASE_2.md` | This checkpoint |

## Modified Files

| File | Changes |
|------|---------|
| `viraltracker/services/landing_page_analysis/__init__.py` | Added BrandProfileService, ReconstructionBlueprintService exports |
| `viraltracker/ui/pages/33_🏗️_Landing_Page_Analyzer.py` | Added Tab 3 Blueprint with full generation/display/export UI |

## Decisions Made

1. **Model selection:** Skill 5 uses `Config.get_model("complex")` (Claude Opus 4.5) since it requires deep reasoning about element mapping and brand data integration.
2. **Brand profile snapshot:** The full brand profile is saved as a JSONB snapshot on the blueprint record for audit trail — so you can see exactly what data was available when the blueprint was generated.
3. **Offer variant handling:** If no offer variant is selected, the service tries `is_default=True` first, then falls back to the first active variant. If no variants exist, the blueprint still works with just product-level data.
4. **Export approach:** JSON for machine consumption + Markdown for human readability. Deferred formatted doc export to tech debt since markdown renders well in most editors.
5. **Key collision prevention:** Download button keys use blueprint ID suffix to prevent Streamlit DuplicateWidgetID errors when multiple blueprints are rendered in history.

## The Power Move

The architecture supports the key use case from the plan: analyze a competitor page ONCE (Skills 1-4), then generate blueprints for MULTIPLE brands from the same analysis. Tab 2 stores analyses, Tab 3 lets you pick any analysis + any brand/product combination.

## What Works

- All Python files compile cleanly (`python3 -m py_compile`)
- Service follows established patterns (analysis_service.py, product_context_service.py)
- Multi-tenancy: org_id filtering on blueprints, org_id stored on records
- Usage tracking: Skill 5 LLM call goes through `run_agent_with_tracking`
- Graceful degradation: BrandProfileService returns partial profiles when data is missing

## How to Test

1. **Run migration** against Supabase:
   ```sql
   -- Run: migrations/2026-02-09_landing_page_blueprints.sql
   ```

2. **Prerequisite:** Have a completed analysis from Tab 1/2

3. **Test blueprint generation:**
   - Navigate to Landing Page Analyzer → Blueprint tab
   - Select a product and offer variant
   - Select a completed analysis
   - Click "Generate Blueprint"
   - Watch 4-step progress
   - Review section-by-section accordion
   - Check CONTENT NEEDED highlighting
   - Test JSON and Markdown exports

4. **Test multi-brand:**
   - Switch to a different brand
   - Select the same analysis
   - Generate a new blueprint for the second brand
   - Verify different brand data is used

5. **Test gap detection:**
   - Use a brand with minimal data (missing guarantee, ingredients, etc.)
   - Verify CONTENT NEEDED sections appear with specific action items
   - Verify brand profile gaps are shown in the collapsible section

## Post-Review Cleanup (completed)

- Extracted `_parse_llm_json()` → shared `utils.py` (was duplicated in analysis_service.py and blueprint_service.py)
- Moved `_get_products_for_brand()` and `_get_offer_variants()` from UI direct DB queries → `BrandProfileService.get_products_for_brand()` / `.get_offer_variants()`
- Post-plan review verdict: **PASS**

## What's Left

- Formatted doc export (docx) — deferred to tech debt
- "Re-run failed steps" button for partial blueprints
- Blueprint comparison view (side-by-side two brands from same analysis)
- Screenshot storage in Supabase storage (currently base64 passed directly)
