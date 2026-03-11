# Checkpoint: PDP Render Fixes (Playwright Capture + Sanitizer)

**Date**: 2026-03-10
**Branch**: `feat/ad-creator-v2-phase0`
**Status**: In Progress — capture fixes complete, sanitizer bottleneck remains for some sites

## Problem

PDP (Product Detail Page) renders were broken on two test sites:
- `mengotomars.com/products/30-day-supply-starter-kit` — single-column layout (missing desktop gallery), missing header/nav/announcement bar, duplicate product image
- `moonbrew.co/pages/gummies` — huge vertical gap below press mentions, UGC video sizing issues

## Root Causes Found & Fixed

### 1. Swiper.js `height:100%` resolving to viewport height
- **Symptom**: ~800px gap below press logos on moonbrew
- **Cause**: External Swiper CSS sets `height:100%` on wrapper/slides. Without JS runtime, resolves to viewport height instead of content height
- **Fix**: Added `height:auto!important` to Swiper fallback CSS in `sanitizer.py`

### 2. Viewport 1280px missing Tailwind `xl:` breakpoints
- **Symptom**: Desktop gallery hidden on mengotomars (uses `hidden xl:block`)
- **Cause**: Custom Tailwind breakpoints; `xl` starts at 1280+ but needs >1280
- **Fix**: Changed viewport from 1280x800 → 1440x900 in `page_capture.py`, `html_renderer.py`, `analysis_service.py`

### 3. CSS not loaded before DOM manipulation
- **Symptom**: `getComputedStyle()` returned wrong values during force-show checks
- **Cause**: `domcontentloaded` fires before CSS loads
- **Fix**: Added `page.wait_for_load_state("load", timeout=8000)` before DOM manipulation

### 4. Animation freeze preventing opacity transitions
- **Symptom**: Announcement bar invisible (opacity:0)
- **Cause**: `transition:none!important` injected before hydration prevented fade-in
- **Fix**: Moved `add_style_tag` after 3-second hydration wait

### 5. Scroll-triggered header collapse
- **Symptom**: Header/announcement bar vanish after scroll-to-load
- **Cause**: Scroll event handlers set opacity:0 and height:0 on header elements
- **Fix**: Added header restoration step after scroll with `opacity:1!important` and `height:auto!important`

### 6. Chrome selectors removing header/nav
- **Symptom**: Missing header and navigation on mengotomars
- **Cause**: `_CHROME_SELECTORS` included `header, nav,` and various header-related selectors
- **Fix**: Removed header/nav from chrome selectors (keep only footer, cart drawers, mega menus, mobile menus, etc.)

### 7. Force-show creating responsive duplicates
- **Symptom**: Duplicate product image, broken grid layout on mengotomars
- **Cause**: `.hidden` class removal on mobile gallery variant added 3rd child to 2-column grid
- **Fix**: Added ancestor-level (3 levels) responsive duplicate detection — skips `.hidden` elements when any ancestor has a visible sibling with media content

### 8. x-collapse zombie elements
- **Symptom**: Invisible elements taking up layout space
- **Cause**: Force-show gave `display:block!important` to elements with `height:0px;overflow:hidden` (Alpine.js x-collapse)
- **Fix**: Skip elements with x-collapse attributes or height:0+overflow:hidden

### 9. Sanitizer stripping header/nav
- **Symptom**: Header removed in S0 sanitization
- **Cause**: `_SHOPIFY_CHROME_ID_PATTERN` matched header sections; bare `<header>` and `<nav>` tags stripped
- **Fix**: Pattern now only matches footer/mega-menu; bare tag removal limited to `<footer>` only

## Files Changed (5 files, +378/-46)

| File | Changes |
|------|---------|
| `page_capture.py` | Viewport 1440x900, CSS load wait, animation freeze timing, chrome selectors update, force-show rewrite with duplicate detection, Swiper slide cycling, header restoration after scroll |
| `sanitizer.py` | Swiper fallback CSS `height:auto!important`, chrome ID pattern fix, bare tag removal fix |
| `html_renderer.py` | Viewport constants 1440x900 |
| `analysis_service.py` | Image scaling 1440 max width |
| `tests/test_multipass_v4.py` | Updated viewport assertions, chrome selector assertions |

## Test Results (SSIM Scores)

| Page | S0 SSIM | Status |
|------|---------|--------|
| bobanutrition.co | 1.000 | No regression |
| moonbrew.co/pages/gummies | 0.800 | User approved |
| mengotomars.com (starter kit) | 0.439 | Original capture much improved; sanitizer is now the bottleneck |

## Remaining Work

1. **Sanitizer improvements for mengotomars** — The original Playwright capture is now much better (correct 2-column layout, header/nav visible), but the sanitizer (S0) produces very different output (SSIM 0.439). The sanitizer is the next bottleneck.
2. **Image proxying through S3/Supabase** — Not yet started. Would improve render reliability for external images.
3. **Verify duplicate product image fix** — User hasn't confirmed the latest ancestor-level duplicate check fix yet.
4. **Consider Swiper slide content extraction** — Currently cycling slides to trigger lazy load; could also extract all slide content for static rendering.
