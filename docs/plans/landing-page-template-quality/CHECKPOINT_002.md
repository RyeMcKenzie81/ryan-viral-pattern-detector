# Landing Page Template Quality - Checkpoint 002

**Date:** 2026-02-19
**Branch:** `feat/ad-creator-v2-phase0`
**Predecessor:** `CHECKPOINT_001.md` (safety foundation + structural overhaul)

---

## Summary

Phase 2 fidelity improvements to `MockupService` addressing the four quality gaps identified in Checkpoint 001: image sizing errors, content hallucination, layout proportion issues, and CSS fidelity gaps. Changes span prompt hardening, CSS allowlist expansion, and a new post-generation content verification system.

---

## Root Cause Analysis

### 2.1 Image Sizing Problems

| Root Cause | Evidence |
|-----------|----------|
| No dimension hints in prompt | `_build_vision_prompt()` listed image URLs with alt text only - no width, height, or shape info |
| `_extract_image_urls()` captures no dimension data | Only extracts `alt` and `url` from `![alt](url)` patterns |
| Sanitization is NOT the issue | `_ALLOWED_CSS_PROPERTIES` already included width, height, max-width, border-radius; `_ALLOWED_ATTRS` included width/height on `<img>` |
| Gemini guesses wrong | Without sizing context, defaults to full-width for ambiguous images like small circular avatars |

### 2.2 Content Hallucination

| Root Cause | Evidence |
|-----------|----------|
| "VERBATIM" instruction too weak | Single line at line 1279 easily overridden by Gemini's tendency to "help" |
| "reference" wording gives license to rearrange | Line 1336: "Use this as reference" implies flexibility |
| No explicit "DO NOT invent" instruction | No negative constraint on text that doesn't exist on the page |
| No post-generation text verification | No step to compare generated text against source markdown |

### 2.3 Layout Fidelity

| Root Cause | Evidence |
|-----------|----------|
| No concrete dimensional references | Prompt gives ranges ("60-80px") not page-specific values |
| Missing `aspect-ratio` in CSS allowlist | Not in the property list, needed for modern CSS layouts |
| No viewport width assumption | Gemini doesn't know target viewport width |
| No proportional guidance | No instruction to match section proportions from screenshot |

### 2.4 Color Accuracy

| Root Cause | Evidence |
|-----------|----------|
| Color instruction is vague | "Extract EXACT hex colors" - Gemini can't read hex from pixels accurately |
| Gradients DO survive sanitization | `_CSS_URL_RE` matches `url(...)` but NOT `linear-gradient(...)` - confirmed safe |
| No pre-extracted color palette | Prompt doesn't include computed colors from the page |

---

## What Was Implemented

### Phase A - Prompt Hardening (5 changes)

1. **Anti-hallucination language** - Replaced weak "VERBATIM" instruction with explicit DO NOT rules:
   - "Reproduce ONLY text that is VISIBLE in the screenshot"
   - "NEVER add introductory paragraphs, summaries, transitions"
   - "When in doubt, OMIT the text rather than invent it"

2. **IMAGE SIZING section** - New prompt section with explicit dimensional guidance:
   - Small circular images: 48-80px with border-radius: 50%
   - Thumbnails: constrain with appropriate max-width
   - Hero images: width: 100% of container
   - "Do NOT render small images as full-width"

3. **Layout fidelity instructions** - Added to LAYOUT REQUIREMENTS:
   - Explicit 1440px viewport assumption
   - "compact sections stay compact, tall sections stay tall"
   - "Side-by-side layouts MUST remain side-by-side (do NOT stack vertically)"

4. **PAGE TEXT CONTENT strict wording** - Replaced "reference" language with source-of-truth rules:
   - "The screenshot determines LAYOUT and VISUAL DESIGN"
   - "This text section determines WHAT TEXT to include"
   - "Do NOT rephrase, summarize, or add transitions between sections"
   - "Copy text VERBATIM - preserve exact wording, capitalization, and punctuation"

5. **Image URL sizing hints** - Added "Set width/height on each `<img>` to match the image's apparent size in the screenshot" to the ACTUAL IMAGE URLs section.

### Phase B - CSS Allowlist Expansion

Added 5 CSS properties to `_ALLOWED_CSS_PROPERTIES`:
- `aspect-ratio` - Modern layout property for maintaining proportions
- `text-shadow` - Text styling
- `cursor` - Interactive element styling
- `row-gap` - Grid/flex row spacing (complement to existing `gap`)
- `column-gap` - Grid/flex column spacing

Verified that CSS gradient functions (`linear-gradient()`, `radial-gradient()`) survive sanitization - `_CSS_URL_RE` only matches `url(...)` patterns, not gradient functions.

### Phase C - Post-Generation Content Verification

New `_verify_content_fidelity()` method with supporting helpers:

- **`_TextExtractor`** (HTMLParser subclass) - Extracts visible text nodes from HTML, skipping `<style>`, `<script>`, `<meta>`, `<title>`, `<head>` content
- **`_extract_visible_text()`** - Static wrapper for text extraction
- **`_normalize_for_comparison()`** - Normalizes text for fuzzy comparison (lowercase, strip punctuation, collapse whitespace, Unicode NFKD normalization)
- **`_verify_content_fidelity()`** - Compares generated HTML text against page markdown:
  - Extracts all text nodes from HTML
  - Builds normalized reference from markdown (strips formatting)
  - Uses sliding-window substring matching (40-char probe, 25-char fallback)
  - Skips short text (<20 chars), placeholder text, and UI boilerplate
  - Returns `(matched_texts, suspect_texts)` tuple
  - Logs warnings for suspect content (potential hallucinations)
  - Wired into `generate_analysis_mockup()` - runs after slot validation, before wrapping

The verification is **non-blocking** - it logs warnings but does not prevent generation. This prevents false positives from blocking valid output while still providing observability into hallucination patterns.

---

## Files Modified

| File | Changes |
|------|---------|
| `viraltracker/services/landing_page_analysis/mockup_service.py` | Prompt hardening (5 edits), CSS allowlist (+5 properties), content verification system (+~120 lines) |
| `tests/test_mockup_service.py` | +20 new tests across 3 test classes |

---

## Test Coverage

**211 tests passing** (191 original + 20 new).

New test classes:
- `TestPromptHardening` (5 tests) - Anti-hallucination language, image sizing section, layout fidelity instructions, page text strict wording, image URL sizing hints
- `TestCssAllowlistAdditions` (6 tests) - aspect-ratio, row-gap/column-gap, text-shadow, cursor, gradient preservation (linear + radial)
- `TestContentFidelityVerification` (9 tests) - Text extraction, style/script skipping, normalization, matching content, hallucinated content detection, empty markdown handling, short text handling, pipeline integration

---

## Ranked Improvement List (Future Work)

| # | Improvement | Impact | Confidence | Effort | Score | Status |
|---|------------|--------|------------|--------|-------|--------|
| 1 | Anti-hallucination prompt language | High | High | 30min | 9.0 | Done |
| 2 | Image sizing guidance in prompt | High | High | 30min | 9.0 | Done |
| 3 | Fix "reference" wording to strict | High | High | 15min | 9.0 | Done |
| 4 | Layout fidelity instructions | Medium | High | 30min | 6.0 | Done |
| 5 | Post-generation text diff | High | Medium | 2h | 5.0 | Done |
| 6 | CSS allowlist additions | Medium | High | 15min | 5.0 | Done |
| 7 | Image dimension extraction from scraper | Medium | Medium | 2h | 3.0 | Future |
| 8 | Structural hints (bounding boxes) | Medium | Medium | 4h | 2.5 | Future |
| 9 | Color palette pre-extraction | Medium | Low | 3h | 2.0 | Future |
| 10 | Multi-pass generation | High | Low | 8h | 1.5 | Future |
| 11 | Render-and-compare (SSIM) validation | High | Low | 6h | 1.5 | Future |

---

## Constraints Verified

1. **data-slot contract** - Unchanged. All slot-related code untouched.
2. **CSS safety** - Sanitization pipeline intact. Only added safe properties to allowlist. Verified gradient preservation.
3. **Gemini context window** - Prompt additions are ~500 bytes. Well within `_PROMPT_TEXT_BUDGET` of 40KB.
4. **Blueprint round-trip** - No changes to the extraction/rewrite/wrap pipeline. Content verification is read-only.
5. **Incremental and testable** - Each phase is independently deployable. 20 new tests cover all additions.
6. **No em dashes** - All new prompt text uses standard dashes.

---

## Next Steps

### High-Impact Future Work

1. **Image dimension extraction** - Modify the web scraper to capture `getBoundingClientRect()` for images and pass dimensions to the prompt. This would give Gemini concrete size targets instead of relying on screenshot interpretation.

2. **Structural hints** - Include a simplified DOM skeleton (tag names, classes, nesting) and computed styles for key elements. This tells Gemini the structural intent beyond what the screenshot conveys.

3. **Multi-pass generation** - Break generation into Structure -> Content -> Styling passes. Each pass gets the screenshot but focuses on one aspect. High effort but could significantly improve all fidelity dimensions.

4. **Render-and-compare validation** - Render generated HTML in a headless browser, screenshot it, and compare against the original using SSIM. Automated retry on low similarity scores.
