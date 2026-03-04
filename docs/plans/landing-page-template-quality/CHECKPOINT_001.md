# Landing Page Template Quality -- Checkpoint 001

**Date:** 2026-02-19
**Branch:** `feat/ad-creator-v2-phase0`
**Commit:** `4b68fec` (feat: Improve landing page HTML template quality (4-phase overhaul))

---

## Summary

Implemented a 4-phase overhaul of `MockupService` to improve the quality, safety, and fidelity of HTML templates generated from landing page screenshots. The system uses Gemini Vision to analyze a screenshot (plus page markdown) and produce a faithful HTML/CSS recreation with `data-slot` markers for downstream brand copy rewriting.

---

## What Was Implemented

### Phase 0 -- Safety Foundation

- Added `_sanitize_css_block()` for `<style>` block content, stripping:
  - `</style>` breakout patterns (entire block rejected)
  - `<!` and `<tag>` HTML injection patterns (entire block rejected)
  - `@import` and `@charset` at-rules
  - `url()` values (iterative stripping until stable)
  - `expression()`, `-moz-binding`, `behavior` legacy JS vectors
- Added parser-based `_strip_url_from_inline_styles()` using `_InlineStyleUrlStripper` (HTMLParser subclass) scoped strictly to `style=` attribute values -- never touches visible text content
- Chained both post-sanitizers into `_sanitize_html()` after bleach

### Phase 1 -- Quick Wins (Prompt & Allowlist)

- Rewrote `_build_vision_prompt()` with explicit guidance for:
  - Semantic HTML structure (`<section>`, `<header>`, etc.)
  - Typography scale (h1-h3 sizes, body text, line-height)
  - Exact hex color extraction from the screenshot
  - CSS approach (prefer `<style>` blocks with class-based CSS, inline for overrides)
  - Spacing/visual (section padding, element margins, button styles)
- Expanded `_ALLOWED_CSS_PROPERTIES` to include: `text-transform`, `background-image`, `background-size`, `background-position`, `background-repeat`, `flex-grow`, `flex-shrink`, `flex-basis`, `align-self`, `order`, `grid-column`, `grid-row`, `z-index`, `float`, `clear`, `vertical-align`, `transform`, `object-fit`, `object-position`, `list-style`, `list-style-type`
- Multi-modal input: Gemini now receives both the screenshot AND scraped page markdown (truncated at heading boundaries via `_truncate_markdown_for_prompt()`)
- Added `_validate_analysis_slots()` with severity tiers (`ok`, `degraded`, `unusable`) and exactly-once retry on `unusable`
- Added `_validate_html_completeness()` (min-length, mid-tag truncation, tag imbalance) with automatic fallback to markdown rendering

### Phase 2 -- Style Block Preservation + Blueprint Carry-Through

- Added `_extract_and_sanitize_css()` for atomic extract + strip + sanitize of `<style>` blocks from Gemini output
- Updated `_wrap_mockup()` with `page_css` parameter, injected as `<style class="page-css">` in `<head>`
- Added `_extract_page_css_and_strip()` for blueprint CSS extraction from persisted analysis HTML, with defense-in-depth re-sanitization on read
- Updated `generate_blueprint_mockup()` to carry CSS through ALL code paths (rewritten, fallback-to-analysis, and error branches)
- `_strip_mockup_wrapper()` signature unchanged -- backward compatible

### Phase 3 -- Image URL Embedding

- Plumbed `page_url` parameter through `generate_analysis_mockup()` and the UI call site
- Added `_extract_image_urls()` to parse `![alt](url)` patterns from page markdown and resolve relative URLs via `urljoin()`
- Added `_validate_image_url()` with:
  - HTTPS-only enforcement
  - Private IP blocking (localhost, 192.168.x, 10.x, 172.16-31.x, 169.254.x)
  - Tracking pixel domain blocking (doubleclick, facebook, google-analytics, etc.)
  - Tracking prefix blocking (pixel., beacon., track.)
- Added `_validate_data_uri()` for safe data: URI validation (png/jpeg/gif/webp only, no SVG, 500KB cap)
- Added parser-based `_SrcSanitizer` for `<img src>` validation after bleach
- Included validated image URLs in Gemini prompt (up to 20 images)

---

## Files Modified

| File | Changes |
|------|---------|
| `viraltracker/services/landing_page_analysis/mockup_service.py` | +829 lines -- all 4 phases |
| `tests/test_mockup_service.py` | +689 lines -- 60+ new tests across 12 test classes |
| `viraltracker/ui/pages/33_<Landing_Page_Analyzer>.py` | +2 lines -- `page_url` plumbing to `generate_analysis_mockup()` |

---

## Test Coverage

**191 tests passing** (60+ new in this commit).

New test classes added:
- `TestSanitizeCssBlock` -- CSS block sanitization (breakout, injection, dangerous at-rules)
- `TestStripUrlFromInlineStyles` -- Parser-based inline style url() stripping
- `TestExtractAndSanitizeCss` -- Atomic CSS extraction and sanitization
- `TestWrapMockupPageCss` -- Page CSS injection into mockup wrapper
- `TestExtractPageCssAndStrip` -- Blueprint CSS extraction with re-sanitization
- `TestBlueprintCssCarryThrough` -- End-to-end CSS preservation through blueprint pipeline
- `TestValidateAnalysisSlots` -- Slot severity tiers and retry logic
- `TestValidateHtmlCompleteness` -- Truncation detection and structural checks
- `TestBuildVisionPrompt` -- Prompt construction with markdown and image URLs
- `TestExtractImageUrls` -- Image URL extraction and resolution
- `TestValidateImageUrl` -- URL safety validation (HTTPS, private IPs, tracking)
- `TestSanitizeImgSrc` -- Parser-based img src sanitization

---

## Current Quality Assessment

### What Works

1. **Safety pipeline is solid** -- CSS blocks are sanitized, url() values stripped from both blocks and inline styles, img src validated, no XSS vectors survive
2. **CSS is preserved through the full pipeline** -- Gemini-generated `<style>` blocks persist from analysis mockup through DB storage, blueprint extraction, and re-wrapping
3. **Slot marking** -- The prompt produces `data-slot` attributes and validation catches failures with retry
4. **Image URLs** -- Real image URLs from the original page are included in the prompt and validated for safety
5. **Structural validation** -- Truncation detection and tag imbalance checks prevent broken HTML from reaching the user
6. **Multi-modal input** -- Gemini receives both the screenshot and page text, reducing guesswork

### What Does NOT Work Well

1. **Image sizing is wrong** -- On pages like `bobanutrition.co/pages/7reabreakfast`, the author bio has a small circular image (~60-80px), but the mockup renders it as an enormous full-width image. Gemini is not extracting or respecting the actual image dimensions from the screenshot.

2. **Hallucinated content** -- The mockup includes a summary paragraph that does not exist on the original page. The page markdown reference is not sufficient to prevent Gemini from inventing text. The "reproduce ALL visible text content VERBATIM" instruction is not being followed faithfully.

3. **Layout fidelity gaps** -- While the overall structure is recognizable, the proportions, spacing, and visual hierarchy do not closely match the original. Sections that are compact on the original expand too much; elements that are side-by-side sometimes stack vertically.

4. **Color accuracy** -- The prompt asks for "exact hex colors" but Gemini frequently approximates. Background gradients, subtle tints, and accent colors diverge from the original.

5. **Overall template reusability** -- The purpose of these templates is to be rewritten with brand copy via the blueprint pipeline. If the template does not faithfully represent the original page's layout, the rewritten version will also look wrong, undermining the entire feature.

---

## Root Cause Hypotheses

1. **Prompt is too broad** -- The prompt asks Gemini to do too many things at once (layout, typography, colors, content, slots, images). A multi-pass approach might yield better results for each dimension.

2. **No dimensional constraints** -- Gemini has no information about actual element sizes, positions, or aspect ratios. It guesses from the screenshot, which is lossy for precise measurements.

3. **No content verification** -- There is no post-generation check to compare generated text against the page markdown and flag hallucinations.

4. **Single-shot generation** -- The entire page is generated in one call. Errors in early sections compound. A section-by-section approach could allow correction.

5. **Screenshot resolution** -- The screenshot may not be high enough resolution for Gemini to accurately read all text and measure all proportions.

---

## What Still Needs Improvement

### High Priority
- Image sizing accuracy (especially circular/constrained images)
- Content hallucination prevention
- Layout proportion fidelity

### Medium Priority
- Exact color reproduction
- Section spacing consistency
- Responsive behavior matching

### Lower Priority
- Animation/transition recreation
- Custom font matching
- Interactive element fidelity (hover states, form validation styles)

---

## Next Steps

See `PHASE_2_FIDELITY_PROMPT.md` in this directory for the next-phase expert analysis prompt designed to address these remaining quality issues.
