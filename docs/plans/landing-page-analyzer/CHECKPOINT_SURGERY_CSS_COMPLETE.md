# Checkpoint: Surgery CSS Pipeline — Complete

**Date**: 2026-02-26
**Branch**: `feat/ad-creator-v2-phase0`
**Last Commit**: `f27cd48` — docs: update STATUS.md with scroll fix and commit history
**Tests**: 410 passing

---

## Problem

The surgery pipeline's S3 (CSS Scoping) was destroying visual quality:
- Regex-prefixed all CSS rules with `.lp-mockup` — broke complex selectors, pseudo-elements, media queries
- Only fetched 1/5 external stylesheets (first-party only)
- Truncated CSS at 512KB (Webflow files are 684KB+)
- S4 Visual QA patches couldn't compensate (0/10 applied)
- **SSIM: ~0.60** (target: 0.75+)

## Solution

### Phase 1 — Fetch All External CSS (necessary but not sufficient)

| Change | File |
|--------|------|
| Increased external CSS fetch limit 3→10 | `html_extractor.py` |
| Added `fetch_raw_external_css()` — raw CSS without parsing/reordering | `html_extractor.py` |
| Added `_rewrite_css_urls()` — resolve relative `url()` paths | `html_extractor.py` |
| Added content-type validation | `html_extractor.py` |
| Increased max CSS response 500KB→2MB | `html_extractor.py` |
| Skip font-only domains (Google Fonts) | `html_extractor.py` |

**Result**: 3/5 stylesheets fetched (was 1/5), but SSIM unchanged at 0.603 because CSS scoping was the bottleneck.

### Phase 2 — Standalone HTML (the fix)

| Change | File |
|--------|------|
| Complete rewrite — standalone `<!DOCTYPE html>` documents, no CSS scoping | `css_scoper.py` |
| Uses `fetch_raw_external_css()` for raw CSS | `pipeline.py` |
| Removed `.lp-mockup` from S4 patch prompt | `prompts.py` |
| `data-pipeline="surgery"` detection instead of `.lp-mockup` | `phase_diagnostics.py` |
| Updated docstring | `section_templates.py` |
| Added `link` to bleach `_ALLOWED_TAGS` for Google Fonts | `mockup_service.py` |
| Fixed double-wrapping in public preview | `api/app.py` |
| Updated/added tests (408→410) | `test_multipass_v4.py` |

**Key insight**: CSS cascade order matters — external CSS (framework) must come FIRST, then inline `<style>` blocks (page-specific overrides). This single fix was the biggest SSIM jump.

**Result**: **SSIM 0.604 → 0.772**

### Scroll Fix

Klaviyo injects `class="klaviyo-prevent-body-scrolling"` on `<body>` with `body.klaviyo-prevent-body-scrolling{overflow:hidden !important}` — prevents scrolling on standalone documents.

| Change | File |
|--------|------|
| Strip known scroll-blocking classes from `<body>` | `css_scoper.py` |
| Append `html,body{overflow:auto !important}` CSS override | `css_scoper.py` |
| Blocked: `klaviyo-prevent-body-scrolling`, `no-scroll`, `modal-open`, `overflow-hidden` | `css_scoper.py` |

---

## E2E Results (Hike Footwear)

| Metric | Before | After |
|--------|--------|-------|
| **SSIM** | 0.604 | **0.771** |
| **External CSS fetched** | 1/5 | 3/5 (1 font-only, 1 returns 404) |
| **CSS rules in output** | ~800 (scoped, broken) | **6,574** (full, unscoped) |
| **S4 Visual QA** | Dead code | Running (SSIM scoring + LLM patches) |
| **Slots** | 51 | 51 |
| **Pipeline time** | ~60s | 71s |
| **Scrolling** | Blocked by Klaviyo CSS | Working |
| **Output size** | ~130K chars | 903K chars (includes all CSS) |

## Blockers & Traps Resolved

| # | Issue | Resolution |
|---|-------|------------|
| B1 | Bleach strips `<link>` tags | Added `link` to `_ALLOWED_TAGS` |
| B2 | Reconstruction pipeline uses `.lp-mockup` | Kept `.lp-mockup` for reconstruction, only changed surgery |
| B3 | `_strip_mockup_wrapper()` destroys styles | `_wrap_mockup()` is normalization boundary — safe |
| T1 | Eval harness checks `.lp-mockup` | Updated to check `data-pipeline="surgery"` |
| T2 | S4 prompt hardcodes `.lp-mockup` selectors | Updated to standard selectors |
| T3 | Public preview double-wraps HTML | Detect full documents, serve as-is |
| T5 | `is_surgery_mode` CSS limit fallback | `data-pipeline="surgery"` preserved on `<body>` |
| T6 | Third-party scroll-blocking classes | Strip classes + CSS override |

## Commits

| Hash | Description |
|------|-------------|
| `8f4b8db` | feat: standalone HTML surgery output + full external CSS fetching |
| `5b48a49` | fix: surgery pipeline integration — bleach allowlist, preview double-wrap, docstrings |
| `7696d94` | fix: strip scroll-blocking classes from body tag in surgery output |
| `f27cd48` | docs: update STATUS.md with scroll fix and commit history |

---

## What's Next

The surgery pipeline S0→S4 is working end-to-end with good visual fidelity (SSIM 0.771). Remaining work:

1. **S4 PatchApplier** — All 10 Gemini patches were skipped due to unsupported complex selectors (multi-class, pseudo-selectors, attribute selectors). PatchApplier needs selector support improvements.
2. **Multi-page QA** — Test on other page types (Shopify, custom sites) to verify generalization.
3. **MockupService integration** — Verify full flow: surgery output → MockupService → blueprint → slot rewriting → brand preview.
