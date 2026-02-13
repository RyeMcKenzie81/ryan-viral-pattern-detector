# Checkpoint: Landing Page → Offer Variant Promotion + Persona Synthesis Improvements

**Date**: 2026-02-12
**Branch**: `main`
**Commits**: `7d744cd` (main feature), `8561a1a` (meta fix), `e43f4ce` (tech debt), `c95f599` (parse_llm_json fix)

## Summary

Implemented a 6-phase plan enabling users to create offer variants directly from landing pages discovered during research, and improved persona synthesis to incorporate landing page data. The work spans three UI surfaces (Brand Manager, Brand Research, URL Mapping) and adds a Meta-only "Discover Variants" flow that groups Meta ads by destination URL and synthesizes variant data from ad copy.

Post-implementation, three bugs were discovered and fixed: incorrect column/table names in Meta variant discovery queries, a silent exception swallow in Brand Manager, and an `UnboundLocalError` in the shared `parse_llm_json` utility.

70 unit tests were added across 4 new test files, all passing.

## Commits

| Hash | Type | Description |
|------|------|-------------|
| `7d744cd` | feat | Landing Page to Offer Variant promotion + Persona Synthesis improvements |
| `8561a1a` | fix | Meta variant discovery - wrong column/table names + silent exception swallow |
| `e43f4ce` | docs | Mark #25 complete, add #26 - filter existing variants from Meta discovery |
| `c95f599` | fix | UnboundLocalError in parse_llm_json when first parse raises non-JSONDecodeError |

## Changes by Phase

### Phase 1: Service Layer Foundations

**File**: `viraltracker/services/product_offer_variant_service.py`

- Added slug collision retry logic (appends `-2`, `-3`, etc. on `UniqueViolation`)
- Added `create_or_update_offer_variant()` -- upsert method that matches on product_id + slug
- Added `extract_variant_from_landing_page()` -- uses LLM to extract variant attributes (name, price, ingredients, mechanism) from landing page HTML/text
- Added `_normalize_to_string_list()` -- normalizes comma-separated strings, JSON arrays, and mixed formats into clean `List[str]`
- Added `SynthesisDataSources` dataclass to structure inputs for persona synthesis

### Phase 2: Shared Offer Variant Form

**File**: `viraltracker/ui/offer_variant_form.py` (NEW)

- Extracted offer variant creation/edit form into a shared component usable across pages
- Includes `sync_url_to_landing_pages()` -- when a user sets an offer URL, the function ensures it exists in the `brand_landing_pages` table (creates the record if missing)
- Handles all field types: text, textarea, price, URL, ingredients list, JSON arrays

**File**: `viraltracker/ui/pages/02_Brand_Manager.py`

- Refactored Brand Manager variant form to use the shared `offer_variant_form.py`
- Fixed silent exception swallow that was hiding errors during Meta variant discovery

### Phase 3: Brand Research "Create Variant" Button

**File**: `viraltracker/ui/pages/05_Brand_Research.py`

- Added a "Create Variant" button next to each landing page discovered during brand research
- Calls `extract_variant_from_landing_page()` to pre-fill form fields from page content
- Variant is created with the landing page URL automatically linked

### Phase 4: Persona Synthesis Improvements

**File**: `viraltracker/services/persona_service.py`

- Integrated landing page data into persona synthesis -- LP content (headlines, CTAs, value props) is now included as a data source
- Added product-scoped filtering so synthesis only uses data relevant to the selected product
- Removed early-return guard that was blocking LP-only synthesis (previously required Amazon or Reddit data to proceed)
- Amazon integration gated by toggle -- Amazon review data is only pulled when the Amazon data source toggle is enabled

**File**: `viraltracker/services/brand_research_service.py`

- Added `SynthesisDataSources` usage for structured data passing to persona synthesis

### Phase 5: URL Mapping "Create Variant" Action

**File**: `viraltracker/ui/pages/04_URL_Mapping.py`

- Added "Create Variant" action button in the assigned URLs section
- When clicked, extracts variant data from the landing page and creates an offer variant linked to that URL
- Provides inline feedback on success/failure

### Phase 6: Meta-Only Discover Variants

**File**: `viraltracker/services/ad_analysis_service.py`

- Added `group_meta_ads_by_destination()` -- groups Meta ads by their destination URL, aggregating spend, impressions, and click metrics per URL
- Added `fetch_meta_analyses_for_group()` -- retrieves existing ad copy analyses for a group of ads sharing a destination
- Added `synthesize_from_raw_copy()` -- uses LLM to synthesize offer variant attributes (name, price, ingredients, mechanism, value propositions) from raw Meta ad copy text when no prior analysis exists

**File**: `viraltracker/ui/pages/02_Brand_Manager.py`

- Added "Discover Variants" flow that groups Meta ads by destination URL and presents each group as a potential variant
- User can review synthesized data and create variants with one click

## Bugs Found and Fixed

### 1. Meta Variant Discovery Wrong Column/Table Names (`8561a1a`)

**Symptom**: "Discover Variants" button produced empty results or errors.

**Root cause**: Two issues in `ad_analysis_service.py`:
- Used `purchase_roas` column name instead of `purchase_value` (the actual column in the schema)
- Referenced `meta_ads` table instead of `meta_ads_performance` (the correct table)

**Fix**: Corrected column and table names to match the actual database schema.

### 2. Silent Exception Swallow in Brand Manager (`8561a1a`)

**Symptom**: Meta variant discovery failures were silently ignored, giving users no feedback.

**Root cause**: A bare `except: pass` block in the Brand Manager variant discovery code was catching and discarding all errors.

**Fix**: Added proper error handling with `st.error()` display and logging.

### 3. parse_llm_json UnboundLocalError (`c95f599`)

**Symptom**: Persona generation crashed with `UnboundLocalError: local variable 'cleaned' referenced before assignment` when the LLM returned non-JSON content.

**Root cause**: In `parse_llm_json()`, when the initial `json.loads()` raised a non-`JSONDecodeError` exception (e.g., `TypeError`), the code fell through to the cleanup path which referenced a `cleaned` variable that had not yet been assigned.

**Fix**: Ensured `cleaned` is initialized before the try block, so the fallback cleanup path always has a valid string to work with.

## Test Coverage

| Test File | Tests | Coverage Area |
|-----------|-------|---------------|
| `tests/test_product_offer_variant_service.py` (NEW) | ~20 | Slug collision retry, create_or_update, extract_variant, _normalize_to_string_list |
| `tests/test_brand_research_synthesis.py` (NEW) | ~15 | SynthesisDataSources, LP data integration, product-scoped filtering |
| `tests/test_ad_analysis_grouping.py` (NEW) | ~20 | group_meta_ads_by_destination, fetch_meta_analyses_for_group, synthesize_from_raw_copy |
| `tests/test_offer_variant_form.py` (NEW) | ~15 | sync_url_to_landing_pages, form field handling, shared component behavior |
| **Total** | **~70** | All passing |

## Files Changed

### New Files (5)

| File | Purpose |
|------|---------|
| `viraltracker/ui/offer_variant_form.py` | Shared offer variant create/edit form |
| `tests/test_product_offer_variant_service.py` | Unit tests for variant service extensions |
| `tests/test_brand_research_synthesis.py` | Unit tests for synthesis data sources |
| `tests/test_ad_analysis_grouping.py` | Unit tests for Meta ad grouping/synthesis |
| `tests/test_offer_variant_form.py` | Unit tests for shared form component |

### Modified Files (8)

| File | Changes |
|------|---------|
| `viraltracker/services/product_offer_variant_service.py` | Slug retry, create_or_update, extract_variant, _normalize_to_string_list |
| `viraltracker/services/brand_research_service.py` | SynthesisDataSources integration |
| `viraltracker/services/ad_analysis_service.py` | Meta ad grouping, analysis fetching, copy synthesis |
| `viraltracker/services/persona_service.py` | LP data integration, product-scoped filtering, Amazon toggle gating |
| `viraltracker/ui/pages/02_Brand_Manager.py` | Shared form refactor, Discover Variants flow, exception fix |
| `viraltracker/ui/pages/04_URL_Mapping.py` | Create Variant action in assigned URLs |
| `viraltracker/ui/pages/05_Brand_Research.py` | Create Variant button per landing page |
| `docs/TECH_DEBT.md` | #25 marked complete, #26 added |

## Tech Debt Updates

- **#25 (COMPLETE)**: Landing page to offer variant promotion -- all three surfaces implemented
- **#26 (NEW)**: Filter existing variants from Meta discovery -- currently the "Discover Variants" flow shows all destination URLs including ones that already have variants created; should filter or badge these

## Known Issues

1. **Meta Discover Variants shows existing variants** -- If a variant has already been created for a destination URL, it still appears in the discovery list. Tracked as tech debt #26.
2. **No deduplication across surfaces** -- Creating a variant from Brand Research and then from URL Mapping for the same LP URL could create duplicates. The `create_or_update_offer_variant()` method mitigates this via slug matching, but edge cases may exist with different slug generation.

## Next Steps

1. **Implement tech debt #26** -- Filter or badge already-created variants in Meta discovery flow
2. **End-to-end testing** -- Manually test the full flow: research brand, discover LPs, create variant, run persona synthesis with LP data
3. **Cross-surface dedup hardening** -- Ensure the slug-based upsert is robust across all three creation surfaces
4. **Persona synthesis quality review** -- Verify that LP data integration actually improves persona quality compared to Amazon/Reddit-only synthesis
