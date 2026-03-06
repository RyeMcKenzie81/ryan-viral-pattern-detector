# Fix 9 Checkpoint: All 4 Phases Complete

**Date**: 2026-03-06
**Branch**: `feat/ad-creator-v2-phase0`
**Status**: All 4 phases complete. Full cross-phase QA passed. Pushed to GitHub.

## What Was Built

### Phase 1 (MVP): Core Auto-fill Infrastructure + LP Gap Filling

#### Task 1.1: Shared Auto-fill UI Component
**New file**: `viraltracker/ui/autofill_suggestions.py`

- `BM_LP_AUTOFILL_FIELDS` — 8 fields for full LP extraction (includes OV fields)
- `BM_PRODUCT_AUTOFILL_FIELDS` — 5 fields for product/brand-only extraction (safe when no OV exists)
- `_DISPLAY_NAMES` — contextual display names ("Product > Guarantee", "Variant > Pain Points")
- `scrape_and_extract(url, product_name, brand_name, target_fields)` — scrapes URL via WebScrapingService, extracts via ContentGapFillerService.extract_from_raw_content(), returns `(suggestions, warning)`
- `render_autofill_suggestions(suggestions, brand_id, product_id, ...)` — renders Accept/Skip/Undo UI
  - Accept: calls `apply_value()` to write directly to production DB with provenance
  - Skip: tracks skipped keys, removes from display
  - Accept All High+Medium: batch apply with partial failure reporting
  - Undo: stores old_value from ApplyResult, re-applies on undo
  - Dismiss: clears suggestions from session state
  - After Accept All: suggestions cleared automatically

#### Task 1.2: Auto-fill in Existing Offer Variant Detail
**Modified**: `02_Brand_Manager.py` — offer variant expanders

- Consolidated LP actions into a single button row after URL: `[URL | Synthesize | Auto-fill | Images]`
- "Auto-fill" button triggers scrape + extraction, shows suggestion panel
- Label changes to "Re-run" when suggestions are cached
- Passes `offer_variant_id` so OV-level fields target correct variant
- Errors/warnings stored in session state to survive reruns
- Short-content warning surfaced to UI

#### Task 1.3: Auto-fill in New Variant Creation Flow
**Modified**: `02_Brand_Manager.py` — new OV form

- After LP analysis + variant form, shows `st.info` prompt for product detail auto-fill
- Uses `BM_PRODUCT_AUTOFILL_FIELDS` (no OV fields — avoids writing to wrong variant)
- Session state cleared on successful OV form save

### Phase 2: Website Scraping + Brand Voice + Disallowed Claims

#### Task 2.1: Website URL + Brand Voice Auto-fill
**Modified**: `02_Brand_Manager.py` — Brand Settings section
**New migration**: `migrations/2026-03-06_brand_website_url.sql`

- Website URL field placed directly above Brand Voice section (minimal scroll distance)
- "Auto-fill from website" button next to Brand Voice input
  - Scrapes website, extracts `brand.voice_tone` via ContentGapFillerService
  - Shows current vs. suggested comparison
  - "Replace current voice" / "Use this voice" button labels
  - Dismiss to discard suggestion
- Stale auto-fill state cleared on brand change
- Graceful degradation if migration not yet run

#### Task 2.2: Brand-Level Disallowed Claims
**Modified**: `02_Brand_Manager.py` — Brand Settings section

- Disallowed Claims text area in Brand Settings
- "one per line" format with clear caption and placeholder examples
- Reads/writes `brands.disallowed_claims` TEXT[] column (already exists)

## QA Issues Found and Fixed

### Phase 1 QA
| Severity | Issue | Fix |
|----------|-------|-----|
| CRITICAL | `offer_variant_id=None` for new OV writes to wrong variant | Use `BM_PRODUCT_AUTOFILL_FIELDS` (excludes OV fields) |
| HIGH | Accept All hides partial failures | `_apply_batch()` tracks and reports failed items |
| HIGH | Error message lost on `st.rerun()` | Errors stored in session state |
| MEDIUM | Stale suggestions persist after OV save | Clear suggestion state on form save |
| MEDIUM | Skip button was a no-op | Now tracks skipped keys, removes from display |

### Phase 2 QA
| Severity | Issue | Fix |
|----------|-------|-----|
| MEDIUM | Stale voice auto-fill persists across brand change | Clear state when brand_id changes |
| UX HIGH | Website URL 200 lines from Brand Voice | Moved URL directly above Voice section |
| UX HIGH | "Accept" unclear about overwrite | Shows current/suggested comparison, "Replace current voice" label |
| UX MEDIUM | Hint implied URL must be saved first | Changed to "Enter website URL above to enable" |
| UX MEDIUM | "one per line" instruction hidden | Added to visible caption |

## Key Architecture Decisions

1. **Direct DB writes** (not session JSONB) — Brand Manager uses `ContentGapFillerService.apply_value()` which writes to canonical tables with provenance tracking via `content_field_events`
2. **Two field lists** — `BM_LP_AUTOFILL_FIELDS` (with OV fields, for existing variants) vs `BM_PRODUCT_AUTOFILL_FIELDS` (without OV fields, for new variant context)
3. **Session state pattern** — `{prefix}_running` / `{prefix}_suggestions` / `{prefix}_error` / `{prefix}_warning` / `{prefix}_skipped` for each auto-fill context
4. **Consolidated button row** — Synthesize / Auto-fill / Images in one row after URL (was scattered across expander)
5. **source_type provenance** — `render_autofill_suggestions()` accepts `source_type` param so Amazon reviews get `"amazon_review_analysis"` while LP scrapes get `"fresh_scrape"`

### Phase 3: Amazon Review Auto-fill + One-Click Setup

#### Task 3.1: Auto-fill from Amazon Reviews
**Modified**: `02_Brand_Manager.py` — Amazon Insights tab

- "Auto-fill from Reviews" button after Amazon analysis display
- OV selector dropdown (defaults to default/first OV) for OV-level fields
- When no OVs exist, restricts to product-only fields with explanatory caption
- Uses `extract_from_amazon_analysis()` with target fields:
  - `offer_variant.pain_points`, `product.results_timeline`, `offer_variant.mechanism.root_cause` (with OV)
  - `product.results_timeline` only (without OV)
- Provenance tracked as `source_type="amazon_review_analysis"` with Amazon URL as source

#### Task 3.2: One-Click Amazon Listing Setup
**Modified**: `02_Brand_Manager.py` — Details tab

- Amazon Listing Setup section with URL input + "Analyze Listing" button
- Parses ASIN from URL via `AmazonReviewService.parse_amazon_url()`
- Registers ASIN via `amazon_product_urls` upsert (with brand_id)
- Scrapes reviews via `scrape_reviews_for_product()`
- Analyzes reviews via `analyze_reviews_for_product()`
- Shows "Enter URL to analyze" hint when URL empty

### Phase 4: Product URL Auto-fill

#### Task 4.1: Product URL Field with Auto-fill
**Modified**: `02_Brand_Manager.py` — Details tab (top)

- Product Website URL field at top of Details tab
- Auto-fill button triggers `scrape_and_extract()` with `BM_PRODUCT_AUTOFILL_FIELDS`
- Label changes to "Re-run" when suggestions cached
- No OV fields — safe for product-level extraction only

### Phase 3-4 QA

| Severity | Issue | Fix |
|----------|-------|-----|
| HIGH | `source_type="fresh_scrape"` hardcoded for all callers including Amazon reviews | Added `source_type` param to `_apply_single`, `_apply_batch`, `render_autofill_suggestions` |
| HIGH | Auto-fill button shows even with 0 OVs — OV fields would fail | Restrict to `["product.results_timeline"]` when no OVs, show explanatory caption |
| UX-HIGH | Amazon one-click button hidden when URL empty, no hint | Added "Enter URL to analyze" caption |
| MEDIUM | Missing `source_url` in Amazon review auto-fill | Pass Amazon URL from `_amz_url_data` for provenance |
| UX-MEDIUM | Lambda closure in OV format_func | Fixed with `lambda x, opts=_ov_options: opts[x]` |

## Files Changed (All Phases)

| File | Type | Lines Changed |
|------|------|---------------|
| `viraltracker/ui/autofill_suggestions.py` | NEW | ~320 lines |
| `viraltracker/ui/pages/02_Brand_Manager.py` | MODIFIED | ~400 lines added/changed |
| `migrations/2026-03-06_brand_website_url.sql` | NEW | 7 lines |

## Migration Required

Run before deploying:
```sql
-- migrations/2026-03-06_brand_website_url.sql
ALTER TABLE brands ADD COLUMN IF NOT EXISTS website_url TEXT;
```
