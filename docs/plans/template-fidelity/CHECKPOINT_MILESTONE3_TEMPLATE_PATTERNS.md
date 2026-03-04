# Checkpoint: Milestone 3 — Template Pattern Improvements

**Date**: 2026-02-23
**Branch**: `feat/ad-creator-v2-phase0`
**Previous commit**: `9e44a8c` — Milestone 2 (markdown classifier)
**Status**: Complete — prose-to-structured mapping + always-fill-header

---

## What Was Done

### Problem Diagnosed

Phase 2 content assembly had a key mismatch bug: when `detect_content_pattern()` returned "prose" (no structured items detected), `split_content_for_template()` always produced a single key (`{{sec_N}}`). But for non-generic layouts (feature_grid, stats_row, hero_split, etc.), the template skeleton had sub-placeholders (`{{sec_N_header}}` + `{{sec_N_items}}` or `{{sec_N_text}}` + `{{sec_N_image}}`).

The single key didn't match any template placeholder → `html.replace()` was a no-op → sub-placeholders remained unfilled → stripped by `_strip_unresolved_placeholders()` → content lost.

Additionally, when sections had no leading heading, `header_key` was never set → `{{sec_N_header}}` stayed as a literal string in the output → counted as unfilled placeholder.

### Change 1: Always Fill Header Key
**File**: `content_patterns.py:325-327`

Changed from conditional (`if pattern.header_markdown:`) to unconditional:
```python
result[header_key] = md_renderer.render(pattern.header_markdown) if pattern.header_markdown else ""
```

This ensures `{{sec_N_header}}` is always replaced (with content or empty string), never left as an unfilled placeholder.

### Change 2: Prose Layout-Aware Key Mapping
**File**: `content_patterns.py:403-437`

The prose handling now checks the layout type and produces the correct keys:

| Layout Type | Keys Produced | Behavior |
|-------------|--------------|----------|
| `feature_grid`, `testimonial_cards`, `faq_list`, `pricing_table`, `logo_bar`, `stats_row` | `header` + `items` | Header from heading, body as items |
| `footer_columns` | `items` (full content) | Header + body combined |
| `hero_split` | Falls through to hero_split block | Produces `text` + `image` |
| `generic`, `hero_centered`, `cta_banner`, etc. | `single` key | Unchanged behavior |

### Tests Added
**File**: `tests/test_multipass_v4.py` — 11 new tests (B31: TestProseStructuredMapping)

| Test | What it verifies |
|------|------------------|
| `test_prose_with_feature_grid_produces_header_items` | Prose + feature_grid → header + items keys |
| `test_prose_with_stats_row_produces_header_items` | Prose + stats_row → header + items keys |
| `test_prose_with_hero_split_produces_text_image` | Prose + hero_split → text + image keys |
| `test_prose_with_generic_produces_single_key` | Prose + generic → single key (unchanged) |
| `test_prose_with_no_layout_produces_single_key` | Prose + no layout → single key |
| `test_prose_with_footer_columns_produces_items` | Prose + footer_columns → items key |
| `test_header_always_filled_even_when_empty` | No heading → header_key = "" not missing |
| `test_prose_feature_grid_no_heading` | Prose + feature_grid + no heading → empty header |
| `test_prose_feature_grid_assembly_fills_all_placeholders` | E2E: feature_grid template fully filled |
| `test_prose_hero_split_assembly_fills_all_placeholders` | E2E: hero_split template fully filled |
| `test_empty_header_doesnt_leave_unfilled_placeholder` | E2E: stats with no heading → no unfilled placeholders |

**All 279 tests pass (268 existing + 11 new).**

---

## Files Changed

| File | Change |
|------|--------|
| `viraltracker/services/landing_page_analysis/multipass/content_patterns.py` | Always-fill-header (1 line), prose-to-structured mapping (~30 lines) |
| `tests/test_multipass_v4.py` | 11 new tests (~180 lines) |
| `docs/plans/template-fidelity/CHECKPOINT_MILESTONE3_TEMPLATE_PATTERNS.md` | **NEW** — this file |

---

## Impact Analysis

### Before (Milestone 2)
- Prose content on structured templates → single key → no match → content lost
- Missing headers → `{{sec_N_header}}` unfilled → stripped → counted as unfilled placeholder
- InfiniteAge: 5 unfilled placeholders, text fidelity 0.62

### After (Milestone 3)
- Prose content → correct keys for every layout type → content fills template
- Headers always filled → zero unfilled `{{sec_N_header}}` placeholders
- Expected improvement: fewer unfilled placeholders, higher text fidelity

### What's Next
- Run `scripts/test_multipass_local.py --url "http://infiniteage.com/pages/sea-moss-for-hair-growth" --visual` to measure updated scores
- If fidelity still below 0.75, investigate remaining coverage gaps
- Potential Milestone 4: layout-aware coverage thresholds, detection accuracy improvements
