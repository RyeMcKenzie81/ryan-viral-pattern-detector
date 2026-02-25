# Checkpoint: S3 CSS Scoping Fix

- **Date**: 2026-02-25
- **Branch**: `feat/ad-creator-v2-phase0`
- **Commit**: `9033c37`
- **Status**: COMPLETE (partial improvement — see remaining issues)

---

## Problem Solved

The surgery pipeline's S3 (CSS Isolation & Scoping) step caused SSIM regression on all test pages. Three bugs were found and fixed:

### Bug 1: @import Statements Silently Dropped
- `_split_top_level_blocks()` in `html_extractor.py` didn't handle semicolon-terminated at-rules (`@import`, `@charset`, `@namespace`)
- When it saw `@import url(...)`, it searched for `{` (found in the NEXT rule), consumed both the `@import` AND the next rule, then silently dropped them via `else: pass`
- Result: Google Fonts `@import` lost → fonts rendered as fallbacks
- **Fix**: Pre-extract `@import` statements in `CSSScoper` using a regex that handles URLs with `;` inside quotes/parens. Emit in a separate `<style>` block before the scoped CSS (required by CSS spec).

### Bug 2: `<!DOCTYPE>` and `<body>` Inside `.lp-mockup`
- Playwright-captured DOMs lack `</body>` closing tags
- `_extract_body_content()` regex `<body[^>]*>(.*)</body>` failed → fell back to stripping `<html>/<head>` but left `<!DOCTYPE>` and `<body>` tag inside the wrapper
- Browser encountering `<body>` inside `<div>` restructured the DOM
- **Fix**: Added a second path in `_extract_body_content()` that handles `<body>` without `</body>` by extracting everything after the opening `<body>` tag.

### Bug 3: `@media(` Without Space Dropped
- Parser read `@media(min-width:360px)` as at-rule name `@media(min-width:` (didn't stop at `(`)
- Fell into `else: pass` → 24+ media query blocks silently dropped
- **Fix**: Added `(` to the stop characters when reading at-rule names in `_split_top_level_blocks()`.

### Additional Fixes
- Body CSS classes (e.g., `gradient`, `page-replo-*`) transferred to `.lp-mockup` wrapper so CSS rules targeting `body.class-name` continue to work
- Phase diagnostics `_has_lp_mockup_wrapper()` now checks for `class="lp-mockup` prefix instead of exact match

---

## Results

### SSIM Scores (Playwright reference screenshots)

| Page | S0 SSIM | Old S3 | New S3 | Improvement | S0→S3 Delta |
|------|---------|--------|--------|-------------|-------------|
| NordStick | 0.7373 | 0.6994 | **0.7373** | **+0.0379** | **0.0000** |
| InfiniteAge | 0.8512 | 0.7195 | **0.7408** | +0.0213 | -0.1104 |
| Boba | 0.6807 | 0.6301 | **0.6366** | +0.0065 | -0.0441 |

### NordStick: Regression fully eliminated (S3 = S0)
### InfiniteAge: Remaining gap likely from Google Fonts rendering in scoped context
### Boba: Small improvement; fewer @import dependencies

### Known Issue: Missing Images on NordStick
The NordStick S3 render is missing some images compared to the original:
- The NordBench product photo (woman using the bench) in the "That's why we built the NordBench" section
- Testimonial video thumbnails (man exercising)
- Some testimonial card images

This is likely caused by the sanitizer's `background-image:none !important` rule or `loading="lazy"` images that aren't being converted to `loading="eager"`. **This should be investigated in the next step.**

---

## Files Changed

| File | Change |
|------|--------|
| `surgery/css_scoper.py` | @import extraction, body class transfer, body extraction fix |
| `html_extractor.py` | `(` added to at-rule name stop chars in `_split_top_level_blocks` |
| `phase_diagnostics.py` | `.lp-mockup` detection handles transferred body classes |

---

## Verification Commands

```bash
# Unit tests (387 pass)
python3 -m pytest tests/test_multipass_v4.py -x -q

# NordStick (S0 = S3 = 0.7373)
MULTIPASS_PHASE1_MODE=v2 MULTIPASS_PIPELINE_MODE=surgery PYTHONPATH=. \
  python3 scripts/test_multipass_local.py \
  --url "thenordstick.com/pages/nordbench-founder-story-solve-body-pain" --playwright-dom --visual

# InfiniteAge (S3: 0.7408)
MULTIPASS_PHASE1_MODE=v2 MULTIPASS_PIPELINE_MODE=surgery PYTHONPATH=. \
  python3 scripts/test_multipass_local.py \
  --url "infiniteage.com/pages/sea-moss-for-hair-growth" --playwright-dom --visual

# Boba (S3: 0.6366)
MULTIPASS_PHASE1_MODE=v2 MULTIPASS_PIPELINE_MODE=surgery PYTHONPATH=. \
  python3 scripts/test_multipass_local.py \
  --url "bobanutrition.co" --playwright-dom --visual
```

---

## Regression Thresholds

| Metric | Floor | Notes |
|--------|-------|-------|
| NordStick S3 SSIM | >= 0.73 | Must not regress from 0.7373 |
| InfiniteAge S3 SSIM | >= 0.74 | Must not regress from 0.7408 |
| Boba S3 SSIM | >= 0.63 | Must not regress from 0.6366 |
| Unit tests | 387 pass | No regression |
