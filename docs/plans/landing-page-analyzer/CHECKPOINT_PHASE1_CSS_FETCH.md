# Checkpoint: Phase 1 CSS Fetch — Results & Phase 2 Decision

**Date**: 2026-02-26
**Branch**: `feat/ad-creator-v2-phase0`
**Last Commit**: `2248097` — fix: post-plan review fixes + 45 tests

---

## Phase 1 Results

### What Was Done
- Added `fetch_all_external=True` parameter to `CSSExtractor.extract()`
- Increased `_MAX_EXTERNAL_CSS_FETCHES` from 3 to 10 for surgery path
- Added `_FONT_ONLY_DOMAINS` to skip Google Fonts (browser loads via `<link>`)
- Added `_rewrite_css_urls()` to fix relative `url()` paths in fetched CSS
- Added `_is_css_content_type()` for content-type validation
- Updated `_safe_fetch_css()` with `first_party_only` flag
- Surgery pipeline now passes `fetch_all_external=True`
- 7 new tests (407 total, all passing)

### E2E Test Results (Hike Footwear)

| Stylesheet | Before | After |
|-----------|--------|-------|
| Webflow CDN (first-party) | Fetched (512KB truncated) | Fetched (512KB truncated) |
| Google Fonts | Skipped | Skipped (correct — font-only) |
| CommerceSpace workers.dev | Skipped | **Attempted → 404** |
| Swiper (jsdelivr) | Skipped | **Fetched** (new!) |
| Klaviyo tracking CSS | Skipped | **Fetched** (new!) |

**SSIM: 0.603** — unchanged from before Phase 1.

### Why Phase 1 Wasn't Enough

1. **CSS scoping is the real bottleneck** — regex-prefixing every rule with `.lp-mockup` mangles complex selectors, pseudo-elements, and media queries
2. **Webflow CSS truncated** — main stylesheet (>512KB) is cut mid-file
3. **CommerceSpace CSS returned 404** — page-specific styles no longer available from CDN
4. **SVGs render at full size** — without proper CSS, inline SVG icons expand uncontrolled
5. **S4 patches all failed** — PatchApplier can't handle `.lp-mockup .div-XX` selectors (0/10 applied)

### Visual Evidence

- S0 (sanitized): Looks great — original `<link>` tags load CSS from CDN
- S2 (classified): Looks great — same as S0 with `data-slot` attributes added
- S3 (scoped): **Completely broken** — layout destroyed, giant icons, no styling
- S4 (QA patches): Identical to S3 — all patches failed to apply

---

## Decision: Proceed with Phase 2

Phase 1 (fetch more CSS) is necessary but not sufficient. The CSS scoping approach is fundamentally broken. Phase 2 eliminates scoping entirely.

### Phase 2: Standalone HTML Document Architecture

**Core idea**: Stop scoping CSS. Keep full `<html>/<head>/<body>` document structure. Inline external CSS as `<style>` blocks. Serve as standalone page.

### Files to Change

1. `css_scoper.py` — Replace scoping with CSS consolidation (inline external CSS, keep document structure)
2. `surgery/pipeline.py` — S3 produces full doc, passes to S4
3. `html_extractor.py` — Already done (Phase 1)
4. `surgery/prompts.py` — Remove `.lp-mockup` from S4 patch prompt
5. `mockup_service.py` — Handle full document, increase CSS cap, add `link` to allowed tags
6. `api/app.py` — Fix double-wrapping bug in public preview
7. `phase_diagnostics.py` — Update `.lp-mockup` checks
8. `tests/test_multipass_v4.py` — Update CSS scoping tests

### Known Blockers (from deep analysis)

| # | Blocker | Mitigation |
|---|---------|------------|
| B1 | Bleach strips `<style>`/`<link>` tags | Already handled: `style` in allowed tags, add `link` for fonts |
| B2 | Non-surgery pipeline also uses `.lp-mockup` | Keep `.lp-mockup` for reconstruction path, only change surgery |
| B3 | `_strip_mockup_wrapper()` destroys `<style>` blocks | MockupService `_wrap_mockup()` is normalization boundary — safe |

### Known Traps (from deep analysis)

| # | Trap | Status |
|---|------|--------|
| T1 | Eval harness checks for `.lp-mockup` | Update phase_diagnostics.py |
| T2 | S4 prompt hardcodes `.lp-mockup` selectors | Update prompts.py |
| T3 | Public preview double-wraps documents | Fix in app.py |
| T4 | Containment CSS clips standalone pages | Remove `.lp-mockup` containment |
| T5 | `is_surgery_mode` CSS limit fallback | Keep `data-pipeline="surgery"` on `<body>` |

---

## Uncommitted Changes

### Modified Files
- `viraltracker/services/landing_page_analysis/multipass/html_extractor.py`
- `viraltracker/services/landing_page_analysis/multipass/surgery/pipeline.py`
- `viraltracker/services/landing_page_analysis/multipass/surgery/css_scoper.py`
- `tests/test_multipass_v4.py`

### Test Artifacts (gitignored)
- `test_hike_phase_s0_sanitized.html/png`
- `test_hike_phase_s2_classified.html/png`
- `test_hike_phase_s3_scoped.html/png`
- `test_hike_phase_s4_final.html/png`
- `test_hike_surgery_output.html`
