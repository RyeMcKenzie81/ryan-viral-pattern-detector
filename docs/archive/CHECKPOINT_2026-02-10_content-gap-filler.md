# Checkpoint: Content Gap Filler for Landing Page Blueprints

**Date**: 2026-02-10
**Branch**: `main`
**Commits**: `d994477` (initial), `e65d9e3`, `dee43df`, `19fca89`, `38c3294`, `8f477aa`
**Plan**: `~/.claude/plans/lazy-riding-tulip.md`

## Summary

After a blueprint runs, sections get marked `CONTENT_NEEDED` because the brand profile is missing data (guarantee, testimonials, FAQ, pain points, etc.). The Content Gap Filler provides an inline workflow within the Blueprint tab to fill these gaps — via manual entry, pulling from existing data sources, or AI-powered extraction — and saves directly to the canonical database tables so all future blueprints benefit.

## What Was Built

### New Files

- **`viraltracker/services/landing_page_analysis/content_gap_filler_service.py`** (~1,750 lines)
  - `GapFieldSpec` dataclass — first-class gap objects with table, column, entity, value_type, auto_fillable, needs_setup, write_policy, sources
  - `SourceCandidate` dataclass — pre-extracted values from cached data sources with snippets, confidence, provenance
  - `ApplyResult` dataclass — save result with action taken, old/new values, confirmation status
  - `GAP_FIELD_REGISTRY` — 13 registered gap fields using `<entity>.<field_path>` convention
  - `resolve_gap_key()` — maps BrandProfileService gap dicts to registry keys
  - `ContentGapFillerService` class with full implementation:
    - **Source checking**: `check_available_sources()` queries Amazon reviews, brand landing pages, Reddit quotes
    - **Validation**: `_normalize_and_validate()` with per-type validators (text, text_list, qa_list, timeline_list, json_array, json)
    - **Write policies**: `allow_if_empty`, `confirm_overwrite`, `append` with near-duplicate detection (SequenceMatcher > 0.87)
    - **Apply with provenance**: `apply_value()` saves to canonical table + records event in `content_field_events`
    - **Not applicable**: `mark_not_applicable()` / `undo_not_applicable()` — dismisses gaps per blueprint without touching canonical data
    - **AI extraction**: `generate_suggestion()` / `generate_all_suggestions()` — batched by source type (LP batch + review batch), strict JSON schema, evidence-required, temperature 0.2
    - **Fresh scrape**: `scrape_and_extract_from_lp()` with SSRF protection, URL ranking, cooldown, keyword verification, cache to `brand_landing_pages`
    - **Source hash**: `_compute_source_hash()` — SHA-256 of canonical evidence JSON for staleness detection

- **`migrations/2026-02-10_content_field_events.sql`** — Append-only provenance table with dedup unique index, dismiss lookup index, request_id grouping

- **`tests/test_content_gap_filler.py`** — 80 unit tests covering registry, gap key resolution, normalization, validation, merge/append, values_equal, is_empty, SSRF, source hash

### Modified Files

- **`viraltracker/services/landing_page_analysis/__init__.py`** — Added exports for `ContentGapFillerService`, `GapFieldSpec`, `GAP_FIELD_REGISTRY`, `SourceCandidate`, `resolve_gap_key`

- **`viraltracker/ui/pages/33_🏗️_Landing_Page_Analyzer.py`** (~850 lines added)
  - Session state: `lpa_gap_suggestions`, `lpa_gap_sources`, `lpa_gaps_saved`, `lpa_gap_dismissed`, `lpa_gap_overwrite_confirmed`
  - `_render_gap_fixer()` — main orchestrator: resolves gaps, checks dismissals, renders Fix All button, active gaps, dismissed section, needs setup section, apply & regenerate CTA
  - `_render_single_gap_control()` — per-gap expander with current value, source candidates with "Use This", fresh scrape with URL selector, AI suggestion, manual entry, save/overwrite/not-applicable
  - `_render_suggestion_evidence()` — confidence badge + evidence panel
  - `_render_fresh_scrape_option()` — scrape UI with URL ranking, cooldown, custom URL input
  - `_run_fix_all()` — batched AI for all auto-fillable gaps
  - Apply & Regenerate sticky CTA after first save

- **`docs/TECH_DEBT.md`** — Added two entries:
  - #18: Brand Voice/Tone per-offer-variant and per-persona overrides (precedence chain)
  - Content Gap Filler integration with brand ingestion tools

## Bugs Found & Fixed During Testing

### 1. AI Suggestion Not Populating Text Area (`19fca89`)

**Symptom**: AI generated reasoning and confidence but the text area stayed empty.

**Root cause**: Classic Streamlit widget key gotcha. `_prefill_from_suggestion()` stored the value in `st.session_state[usethis_key]`, but the `st.text_area` widget had its own `key=widget_key`. After first render, Streamlit stores the widget's value under `widget_key` and ignores the `value` parameter on subsequent reruns — so it always read `""` from its own key.

**Fix**: Before the widget renders, if there's a prefill value, copy it directly to `st.session_state[widget_key]` and clear the intermediate key to avoid overwriting user edits.

### 2. AI Returning Empty Value for Inferred Fields (`dee43df`)

**Symptom**: Brand voice/tone suggestion had reasoning describing the tone but `value` was null.

**Root cause**: The extraction prompt said "Only extract factual information — do not invent or hallucinate data" and the confidence rules emphasized exact-match patterns. For brand voice/tone, there's never an explicit heading — it must be synthesized from copy style. The AI put its analysis in reasoning but left value empty.

**Fix**: Added prompt instructions telling the AI to synthesize values for inferred fields and to always populate the `value` field even at low confidence. Added UI fallback message when value is still empty.

### 3. URL Selector Hidden During Scrape Cooldown (`8f477aa`)

**Symptom**: After scraping a URL, user couldn't select a different page to scrape (e.g., a dedicated ingredients page). Only "Force Scrape" button was visible.

**Root cause**: The URL selectbox was inside an `if/else` on cooldown status — it showed either the cooldown caption OR the selectbox, never both. Within 24h of a scrape, only the caption appeared.

**Fix**: URL selector now always renders alongside the cooldown message. Added "Enter a custom URL..." option for scraping pages not in the known LP list. Deduplicated URLs between offer variant and brand_landing_pages sources.

## Architecture Decisions

| Decision | Rationale |
|----------|-----------|
| GapKey as `<entity>.<field_path>` | First-class objects avoid loose strings, enable registry lookup, clear entity scoping |
| Three field categories (auto-fillable, manual-only, needs_setup) | Different fields need different UX — some can be AI-filled, some need manual entry, some need entire workflows |
| Append-only `content_field_events` | Full audit trail, no data loss, supports undo via event replay, dedup via unique index |
| `request_id` grouping | Groups all events from a single "Fix All" action for batch provenance |
| Source hash on events | Enables staleness detection — if evidence changes, badge shows "Source updated since last save" |
| Write policies per field | Different fields have different conflict semantics — guarantee is set-once, pain_points are appended, voice_tone requires confirmation |
| Batched AI by source type | LP-derived fields (guarantee, ingredients, FAQ, mechanism, voice_tone) in one call, review-derived (pain_points, results_timeline) in another — max 2 LLM calls for Fix All |

## Data Model

### Gap Field Registry (13 fields)

| Key | Table | Entity | Type | Auto-Fill | Write Policy |
|-----|-------|--------|------|-----------|-------------|
| `brand.voice_tone` | brands | brand | text | Yes | confirm_overwrite |
| `product.guarantee` | products | product | text | Yes | allow_if_empty |
| `product.ingredients` | products | product | json_array | Yes | allow_if_empty |
| `product.results_timeline` | products | product | timeline_list | Yes | allow_if_empty |
| `product.faq_items` | products | product | qa_list | Yes | allow_if_empty |
| `offer_variant.mechanism.name` | product_offer_variants | offer_variant | text | Yes | confirm_overwrite |
| `offer_variant.mechanism.root_cause` | product_offer_variants | offer_variant | text | Yes | confirm_overwrite |
| `offer_variant.pain_points` | product_offer_variants | offer_variant | text_list | Yes | append |
| `product.top_positive_quotes` | amazon_review_analysis | product | quote_list | No | allow_if_empty |
| `product.review_platforms` | products | product | json | No | confirm_overwrite |
| `product.pricing` | product_variants | product | complex | No (needs_setup) | confirm_overwrite |
| `product.personas` | personas_4d | product | complex | No (needs_setup) | confirm_overwrite |
| `product.name` | products | product | text | No (needs_setup) | confirm_overwrite |

### Provenance Table: `content_field_events`

| Column | Purpose |
|--------|---------|
| `gap_key` | Registry key (e.g., `product.guarantee`) |
| `target_table` / `target_id` / `target_column` | What was changed |
| `action` | `set`, `overwrite`, `append`, `skip_not_applicable`, `undo_skip` |
| `source_type` | `manual`, `cached_source`, `ai_suggestion`, `fresh_scrape`, `system` |
| `source_detail` | JSONB with source table, snippet, URL, confidence |
| `request_id` | Groups events from a single Fix All batch |
| `source_hash` | SHA-256 of evidence for staleness detection |
| `blueprint_id` | Which blueprint triggered this (nullable) |

## Verified Working

- Manual entry → Save → check DB row updated + event in `content_field_events`
- Source candidates with "Use This" → populates text area → save with `source_type="cached_source"`
- AI suggestion → generates value + evidence + reasoning → populates text area
- Fix All batched → progress bar → all auto-fillable gaps populated
- Fresh scrape with URL selector + custom URL option
- Conflict resolution (overwrite confirmation for existing values)
- Not Applicable → gap dismissed, canonical field unchanged
- Needs Setup fields → deep links only, excluded from Fix All
- Apply & Regenerate CTA after saves
- Brand voice/tone saved to `brands.brand_voice_tone` (Wonder Paws)
- Guarantee saved to `products.guarantee` (Collagen 3X Drops)
- Both provenance events recorded with correct `source_type` and timestamps
