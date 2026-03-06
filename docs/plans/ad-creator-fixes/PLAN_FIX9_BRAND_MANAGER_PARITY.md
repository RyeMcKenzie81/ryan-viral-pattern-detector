# Fix 9: Brand Manager — LP Analysis, Gap Filling & Feature Parity with Onboarding

## Status: COMPLETE (All 4 Phases)

## Problem

Client Onboarding (`06_Client_Onboarding.py`, 2908 lines) has many features that Brand Manager (`02_Brand_Manager.py`, 2780 lines) is missing. If you skip gap-filling during onboarding, there's no way to do it later.

## Gap Analysis

| Feature | In Onboarding | In Brand Manager |
|---------|---------------|-----------------|
| Website scraping + brand voice auto-fill | Yes | No |
| LP auto-fill for offer variants (ContentGapFillerService) | Yes | No |
| Product image extraction from LP | Yes | Only after variant saved |
| Amazon listing analysis + one-click setup | Yes | Partial (re-scrape/re-analyze only) |
| Auto-fill from Amazon reviews | Yes | No |
| Product URL auto-fill | Yes | No |
| Auto-fill Accept/Skip/Undo UI pattern | Yes | No |
| Brand-level disallowed claims | Yes | No (per-product only) |

## Architecture Decision

Onboarding writes suggestions to session JSONB via `service.update_section()`.
Brand Manager must write to production DB tables directly.
`ContentGapFillerService.apply_value()` already supports this — reads/writes to canonical tables with provenance tracking via `content_field_events`.

## Implementation Plan

### Phase 1 (MVP): Core Auto-fill Infrastructure + LP Gap Filling

#### Task 1.1: Create Shared Auto-fill UI Component
- **File:** `viraltracker/ui/autofill_suggestions.py` (new)
- **Complexity:** Medium
- Extract and generalize auto-fill UI pattern from Onboarding
- Create `render_autofill_suggestions_for_brand_manager()` that:
  - Takes suggestions dict, product_id, brand_id, offer_variant_id
  - Renders confidence icons, Accept/Skip per suggestion, Accept All High+Medium
  - On Accept, calls `ContentGapFillerService.apply_value()` to write to production DB
  - Supports Undo by saving old_value from ApplyResult in session_state
- Define `BM_GAP_KEY_MAP` and `BM_LP_AUTOFILL_FIELDS` field lists

#### Task 1.2: Add "Auto-fill from LP" to Offer Variant Detail View
- **File:** `viraltracker/ui/pages/02_Brand_Manager.py` (tab_offers section)
- **Complexity:** Medium
- Add "Auto-fill from LP" button next to "Synthesize" in offer variant expander
- Flow: scrape LP URL -> ContentGapFillerService.extract_from_raw_content -> show suggestions -> apply_value on accept
- Add "Extract Images" button for LP image extraction

#### Task 1.3: Add "Auto-fill from LP" to New Variant Creation Flow
- **File:** `viraltracker/ui/pages/02_Brand_Manager.py` (new OV form)
- **Complexity:** Low-Medium
- After "Analyze Landing Page" button, add "Auto-fill" button
- Wire to same flow as Task 1.2

### Phase 2: Website Scraping + Brand Voice Auto-fill

#### Task 2.1: Website Scrape + Brand Voice Auto-fill in Brand Settings
- **File:** `viraltracker/ui/pages/02_Brand_Manager.py` (Brand Settings section)
- **Complexity:** Medium
- Add "Website URL" field + "Scrape Website" button
- Add "Auto-fill Voice/Tone" button using ContentGapFillerService

#### Task 2.2: Brand-level Disallowed Claims
- **File:** `viraltracker/ui/pages/02_Brand_Manager.py`
- **Complexity:** Low
- Add "Disallowed Claims" text_area to Brand Settings

### Phase 3: Amazon Review Auto-fill

#### Task 3.1: Auto-fill from Amazon Reviews
- **File:** `viraltracker/ui/pages/02_Brand_Manager.py` (tab_amazon)
- **Complexity:** Medium
- Add "Auto-fill from Reviews" button after displaying analysis results

#### Task 3.2: One-Click Amazon Listing Analysis
- **File:** `viraltracker/ui/pages/02_Brand_Manager.py` (tab_details)
- **Complexity:** Medium
- Add "Amazon URL" field + "Analyze Listing" button for product setup

### Phase 4: Product URL Auto-fill

#### Task 4.1: Product URL Field with Auto-fill
- **File:** `viraltracker/ui/pages/02_Brand_Manager.py` (tab_details)
- **Complexity:** Medium
- Add "Product URL" field + "Auto-fill from Website" button

## Task Summary

| # | Task | Phase | Complexity | Files |
|---|------|-------|------------|-------|
| 1.1 | Shared auto-fill UI component | 1 (MVP) | Medium | `ui/autofill_suggestions.py` (new) |
| 1.2 | LP auto-fill in variant detail | 1 (MVP) | Medium | `02_Brand_Manager.py` |
| 1.3 | LP auto-fill in new variant form | 1 (MVP) | Low-Med | `02_Brand_Manager.py` |
| 2.1 | Website scrape + brand voice | 2 | Medium | `02_Brand_Manager.py` |
| 2.2 | Brand-level disallowed claims | 2 | Low | `02_Brand_Manager.py` |
| 3.1 | Amazon review auto-fill | 3 | Medium | `02_Brand_Manager.py` |
| 3.2 | Amazon listing one-click | 3 | Medium | `02_Brand_Manager.py` |
| 4.1 | Product URL auto-fill | 4 | Medium | `02_Brand_Manager.py` |

## Risks

1. **DB schema gaps**: Verify `brands` has `website_url` and `disallowed_claims` columns before Phase 2
2. **File size**: Brand Manager already 2780 lines — extract auto-fill component to separate module (Task 1.1)
3. **Offer variant targeting**: When auto-filling from Amazon reviews, default to product's default offer variant
4. **Widget key collisions**: Use `{product_id}_{ov_id}` prefix convention consistently
5. **Session state accumulation**: Clear suggestions on page reload or brand change

## Key Files

- `viraltracker/ui/pages/02_Brand_Manager.py` — primary modification target
- `viraltracker/ui/pages/06_Client_Onboarding.py` — reference implementation
- `viraltracker/services/landing_page_analysis/content_gap_filler_service.py` — core service backend
- `viraltracker/ui/offer_variant_form.py` — existing shared component
- `viraltracker/services/web_scraping_service.py` — scraping backend
