# Checkpoint: Playwright DOM Capture + Surgery Chrome Removal

- **Date**: 2026-02-24
- **Branch**: `feat/ad-creator-v2-phase0`
- **Commit**: `5e99115`
- **Status**: COMPLETE

---

## Problem Solved

Firecrawl's `formats=["html"]` returns pre-JS HTML containing Shopify template placeholders ("Your headline", "Image caption appears here") instead of real hydrated content. Firecrawl screenshots are also height-truncated on long landing pages. Both issues severely penalized surgery pipeline SSIM scores.

### Before (Firecrawl HTML)
| Page | S0 SSIM | Final SSIM | Reference |
|------|---------|------------|-----------|
| Boba | 0.44 | 0.44 | Truncated Firecrawl screenshot |
| InfiniteAge | 0.73 | 0.67 | Truncated Firecrawl screenshot |

### After (Playwright DOM + full-page screenshot)
| Page | S0 SSIM | Final SSIM | Reference |
|------|---------|------------|-----------|
| Boba | **0.68** | 0.63 | Playwright full-page screenshot |
| InfiniteAge | **0.85** | 0.72 | Playwright full-page screenshot |
| NordStick | **0.74** | 0.70 | Playwright full-page screenshot (new page) |

---

## What Was Done

### 1. New `page_capture.py` — Sync Playwright DOM Capture
- **File**: `viraltracker/services/landing_page_analysis/page_capture.py` (NEW, ~308 lines)
- Sync Playwright pattern matching `html_renderer.py`
- `capture_rendered_page()` → `CaptureResult` dataclass (dom_html, screenshot_bytes, final_url, capture_time_ms, visible_text_len)
- Returns `None` on any failure (caller falls back to Firecrawl)
- **Chrome removal** (2-pass: before and after scroll):
  - Header, nav, footer, cart drawers (ajax-cart, CartDrawer, cart-sidebar)
  - ShopifyChat, shop-cart-sync, Monster Upsells (monster-cart-wrapper, monster-upsell-cart)
  - Alia popup overlays, free shipping bars (fsb_*)
  - Shopify app blocks (shopify-app-block class — NOT Replo content)
  - Polaris CSS lockdown, web-pixels-manager sandbox
  - Accessibility skip-nav links (visually-hidden)
  - Modal dialogs (aria-modal=true)
  - SVG sprite sheets (symbol-based, aria-hidden small, unconstrained viewBox)
  - display:none direct body children
  - Mobile menu/nav drawers, icon references
- **lazy→eager conversion**: All `loading="lazy"` → `loading="eager"` for below-fold images
- **Script content stripping**: `<script>` tag contents emptied to reduce noise

### 2. Modified `analysis_service.py` — Playwright-First Stage 2
- **File**: `viraltracker/services/landing_page_analysis/analysis_service.py`
- Stage 2 now: Playwright capture → Firecrawl fallback → empty string
- Extracted `_firecrawl_html_fallback()` helper
- `PlaywrightNotInstalledError` graceful degradation

### 3. Modified `test_multipass_local.py` — Playwright Testing Support
- **File**: `scripts/test_multipass_local.py`
- `--playwright-dom` flag: re-captures page_html via Playwright, updates DB
- Playwright full-page screenshot used as SSIM reference (fixes Firecrawl height truncation)
- Tracks `playwright_dom` in run metadata

### 4. Modified `pipeline.py` — Body Tag Search Window
- **File**: `viraltracker/services/landing_page_analysis/multipass/pipeline.py`
- `<body` tag search window: 50,000 → 200,000 chars (Playwright DOMs have larger `<head>` sections)

### 5. Unit Tests — 387 Passing (17 new)
- **File**: `tests/test_multipass_v4.py`
- B34: TestPageCapture (9 tests) — CaptureResult, error handling, script stripping, quality check
- B35: TestS0WithPlaywrightDom (4 tests) — sanitizer with Playwright-style DOM
- B36: TestScrapeConsistencyRicherDom (4 tests) — consistency check with richer DOM

---

## Key Architecture Decisions

1. **Sync Playwright** (not async) — matches html_renderer.py pattern, avoids async/thread hazards
2. **Conservative chrome selectors** — Replo content lives inside Shopify section wrappers; broad class selectors like `[class*='primary-logo']` catch visible content and drop SSIM
3. **Two-pass cleanup** — first pass before scroll, second pass after scroll catches late-injected elements (Alia popups)
4. **Playwright screenshot as reference** — Firecrawl truncates at ~14K pixels; Playwright captures full 23K+ pixel pages
5. **`shopify-app-block` removal safe** — verified none contain Replo `data-rid` content

## Chrome Removal Lessons Learned

| Selector | Result | Lesson |
|----------|--------|--------|
| `[class*='primary-logo']` | SSIM dropped 0.59→0.50 | Too broad — catches Replo content |
| `[class*='shopify-section-group-header']` | SSIM dropped 0.65→0.48 | Replo content lives inside these wrappers |
| `body > *` position:fixed | SSIM dropped 0.59→0.48 | Sticky sections are legitimate Replo content |
| `[class~='shopify-app-block']` | Safe | None contain data-rid (Replo) content |
| `[id^='alia-root']` + second pass | Safe | Must run after scroll (late-injected) |
| `[class*='visually-hidden']` | Safe | Only 3 elements: skip-nav + "Payment methods" |

---

## Files Changed

| File | Change |
|------|--------|
| `page_capture.py` | NEW — Playwright DOM capture service |
| `analysis_service.py` | Playwright-first Stage 2 with Firecrawl fallback |
| `test_multipass_local.py` | --playwright-dom flag, PW screenshot reference |
| `pipeline.py` | Body tag search window 50K→200K |
| `test_multipass_v4.py` | 17 new tests (B34-B36) |
| `surgery/*` | Surgery pipeline modules (sanitizer, mapper, classifier, scoper) |
| `eval_harness.py` | Visual fidelity scoring updates |
| `prompts.py` | Phase prompt updates |
| `section_templates.py` | Template updates |
| `phase_diagnostics.py` | Diagnostic reporting updates |
| `html_extractor.py` | Extractor updates |
| `mockup_service.py` | Mockup service updates |
| `eval_multipass.py` | Eval script updates |

---

## Verification Commands

```bash
# Unit tests (387 pass)
python3 -m pytest tests/test_multipass_v4.py -x -q

# Boba (Shopify/Replo) — S0: 0.68
MULTIPASS_PHASE1_MODE=v2 MULTIPASS_PIPELINE_MODE=surgery PYTHONPATH=. \
  python3 scripts/test_multipass_local.py \
  --url "bobanutrition.co" --playwright-dom --visual

# InfiniteAge — S0: 0.85
MULTIPASS_PHASE1_MODE=v2 MULTIPASS_PIPELINE_MODE=surgery PYTHONPATH=. \
  python3 scripts/test_multipass_local.py \
  --url "infiniteage.com/pages/sea-moss-for-hair-growth" --playwright-dom --visual

# NordStick — S0: 0.74
MULTIPASS_PHASE1_MODE=v2 MULTIPASS_PIPELINE_MODE=surgery PYTHONPATH=. \
  python3 scripts/test_multipass_local.py \
  --url "thenordstick.com/pages/nordbench-founder-story-solve-body-pain" --playwright-dom --visual

# Template baseline (must not regress)
MULTIPASS_PHASE1_MODE=template PYTHONPATH=. \
  python3 scripts/test_multipass_local.py \
  --url "infiniteage.com/pages/sea-moss-for-hair-growth" --visual
```

---

## Regression Thresholds

| Metric | Floor | Notes |
|--------|-------|-------|
| Boba S0 SSIM | >= 0.60 | With Playwright reference |
| InfiniteAge S0 SSIM | >= 0.80 | With Playwright reference |
| NordStick S0 SSIM | >= 0.65 | With Playwright reference |
| Unit tests | 387 pass | No regression |
| Template SSIM | >= 0.72 | Must not regress |
