# Workflow Plan: PDP Rendering Fix — Surgery Pipeline

**Branch**: `fix/pdp-rendering-surgery-pipeline`
**Created**: 2026-03-10
**Status**: Phase 1 - Intake

---

## Phase 1: INTAKE

### 1.1 Original Request

PDP (Product Detail Page) and content pages come back looking broken after the surgery pipeline processes them. Two example pages demonstrate the issues:
- `mengotomars.com/products/30-day-supply-starter-kit` — Shopify PDP with Alpine.js
- `moonbrew.co/pages/gummies` — Shopify page with Shoplift A/B testing framework

Key problems identified through multi-agent analysis:
1. 98-100% of images have empty `src=""` (image URLs not captured from JS-hydrated DOM)
2. CSS `@import url()` truncated, leaving corrupt CSS fragments
3. `scroll-behavior:` falsely matches the IE `behavior:` security filter
4. `url()` values double-stripped (surgery S3 preserves them, mockup service re-strips)
5. JS-dependent visibility classes leave product galleries hidden
6. No `<form>`/`<input>`/`<select>` awareness in element classifier
7. Empty `aspect-ratio: ;` values on images
8. `<link rel="preload" as="style">` not discovered by CSS extractor
9. External CSS fetch limit too low / silent failures
10. Images break when brand doesn't allow external loading (hotlinking)

### 1.2 Clarifying Questions

| # | Question | Answer |
|---|----------|--------|
| 1 | Image strategy? | Proxy through S3 — download images and rewrite URLs to our storage |
| 2 | Visibility fix approach? | Strongest cross-page solution — Playwright-based computed visibility detection |
| 3 | Scope? | All 10 fixes |
| 4 | Push to GitHub? | Do NOT push without asking first — production is running |

### 1.3 Desired Outcome

**User Story**: As a user analyzing competitor landing pages, I want PDP pages to render with high fidelity (images visible, layout intact, interactive elements represented) so that I can accurately study their design patterns and generate useful blueprints.

**Success Criteria**:
- [ ] All existing tests pass (`pytest tests/test_multipass_*.py tests/test_mockup_service.py tests/test_surgery_invariants.py -v`)
- [ ] mengotomars PDP renders with product images, gallery visible, correct prices
- [ ] moonbrew gummies page renders with product images, variant selectors, correct layout
- [ ] Eval harness scores do not regress (SSIM, slot retention, text fidelity)
- [ ] Images proxied to S3 survive even if original site blocks hotlinking
- [ ] No broken CSS fragments (truncated @import, corrupted scroll-behavior)

---

## Phase 2: ARCHITECTURE DECISION

### 2.1 Workflow Type Decision

**Chosen**: [x] Python workflow (surgical fixes to existing pipeline)

This is NOT a new feature — it's a series of targeted fixes to 4 existing files in the surgery pipeline. No new agents, tools, or pipelines needed.

### 2.2 High-Level Fix Order

All fixes are to existing deterministic pipeline code. Ordered by dependency (each fix builds on the previous):

```
Fix 1: CSS @import cleanup in mockup_service.py
    ↓  (lowest risk, no dependencies)
Fix 2: scroll-behavior regex in mockup_service.py
    ↓  (same file, simple regex fix)
Fix 3: Preserve url() through mockup service for surgery mode
    ↓  (same file, conditional logic)
Fix 4: Playwright visibility — force-show JS-hidden content
    ↓  (page_capture.py — captures better DOM)
Fix 5: Image src population — ensure all lazy/JS images resolved
    ↓  (sanitizer.py — works on better DOM from Fix 4)
Fix 6: Image S3 proxy — download and rewrite image URLs
    ↓  (new helper in sanitizer or separate utility)
Fix 7: Preserve aspect-ratio values during sanitization
    ↓  (sanitizer.py — stop stripping valid inline styles)
Fix 8: Add <link rel="preload" as="style"> discovery
    ↓  (html_extractor.py — CSS extraction)
Fix 9: Increase external CSS fetch limit + better logging
    ↓  (html_extractor.py — same file as Fix 8)
Fix 10: Add form/input/select awareness to element classifier
    ↓  (element_classifier.py — new slot types)
Result: High-fidelity PDP rendering with proxied images
```

### 2.3 Files Modified

| File | Fixes | Risk |
|------|-------|------|
| `mockup_service.py` | 1, 2, 3 | Low — CSS sanitizer changes only |
| `page_capture.py` | 4 | Medium — changes DOM capture behavior |
| `sanitizer.py` | 5, 6, 7 | Medium — changes HTML sanitization |
| `html_extractor.py` | 8, 9 | Low — CSS extraction improvements |
| `element_classifier.py` | 10 | Low — additive slot types |

---

## Phase 3: INVENTORY & GAP ANALYSIS

### 3.1 Existing Components (Modify, Not Replace)

| Component | Type | Location | Fix # |
|-----------|------|----------|-------|
| `_sanitize_css_block()` | Function | `mockup_service.py` | 1, 2, 3 |
| `_CSS_BEHAVIOR_RE` | Regex | `mockup_service.py` | 2 |
| `_strip_unsafe_css_urls()` | Function | `mockup_service.py` | 3 |
| `capture_rendered_page()` | Function | `page_capture.py` | 4 |
| `_REMOVE_HIDDEN_AND_SPRITES_JS` | JS snippet | `page_capture.py` | 4 |
| `HTMLSanitizer.sanitize()` | Method | `sanitizer.py` | 5, 7 |
| `HTMLSanitizer._resolve_lazy_images()` | Method | `sanitizer.py` | 5 |
| `CSSExtractor.fetch_raw_external_css()` | Method | `html_extractor.py` | 8, 9 |
| `CSSExtractor._extract_stylesheet_urls()` | Method | `html_extractor.py` | 8 |
| `ElementClassifier.classify()` | Method | `element_classifier.py` | 10 |

### 3.2 New Components to Build

| Component | Type | Purpose |
|-----------|------|---------|
| `_proxy_images_to_s3()` | Function in sanitizer.py | Download images, upload to S3, rewrite URLs |
| `_FORCE_SHOW_JS_HIDDEN_JS` | JS snippet in page_capture.py | Playwright JS to force-show JS-hidden content |
| `_resolve_js_bound_images()` | Method in sanitizer.py | Handle Alpine.js `:src`, `x-bind:src` patterns |

### 3.3 Database Evaluation

No database changes needed. Images will be stored in existing Supabase Storage bucket.

### 3.4 Test Plan

Run after EACH fix:
```bash
# Unit tests (must all pass)
pytest tests/test_multipass_pipeline.py tests/test_multipass_v4.py tests/test_mockup_service.py tests/test_surgery_invariants.py -v

# Syntax check on modified file
python3 -m py_compile <modified_file>
```

Run after ALL fixes:
```bash
# Full test suite
pytest tests/test_multipass_pipeline.py tests/test_multipass_v4.py tests/test_mockup_service.py tests/test_surgery_invariants.py tests/test_blueprint_image_service.py tests/test_analysis_service_qa.py -v

# E2E test against real pages (manual)
python scripts/test_e2e_blueprint.py --url "https://mengotomars.com/products/30-day-supply-starter-kit" --visual
python scripts/test_e2e_blueprint.py --url "https://moonbrew.co/pages/gummies" --visual
```

---

## Phase 4: BUILD

### 4.1 Build Order

1. [ ] Fix 1: CSS @import cleanup — `mockup_service.py`
2. [ ] Fix 2: scroll-behavior regex — `mockup_service.py`
3. [ ] Fix 3: url() preservation in surgery mode — `mockup_service.py`
4. [ ] Fix 4: Playwright JS-hidden content visibility — `page_capture.py`
5. [ ] Fix 5: Image src population — `sanitizer.py`
6. [ ] Fix 6: Image S3 proxy — `sanitizer.py`
7. [ ] Fix 7: aspect-ratio preservation — `sanitizer.py`
8. [ ] Fix 8: preload stylesheet discovery — `html_extractor.py`
9. [ ] Fix 9: CSS fetch limit + logging — `html_extractor.py`
10. [ ] Fix 10: form/input/select slot tagging — `element_classifier.py`

---

## Change Log

| Date | Phase | Change |
|------|-------|--------|
| 2026-03-10 | 1 | Initial plan created |
