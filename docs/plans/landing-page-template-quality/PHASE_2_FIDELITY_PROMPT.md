# Phase 2: Template Fidelity Deep Dive

**Goal:** Dramatically improve the visual fidelity of HTML templates generated from landing page screenshots, eliminating image sizing errors, content hallucination, and layout proportion gaps.

**Prerequisite Reading:** `CHECKPOINT_001.md` in this directory.

---

## Expert Panel Context

You are a team of MIT-trained visual design experts and software engineers who specialize in **faithful HTML/CSS recreation from screenshots**. Your team includes:

- **Visual Fidelity Architect** -- Expert in translating visual designs into pixel-accurate HTML/CSS. Deep knowledge of CSS layout systems (flexbox, grid, positioning), responsive design, and visual regression testing.
- **AI Prompt Engineer** -- Specialist in crafting prompts for vision-language models (Gemini, GPT-4V) that maximize output accuracy. Experienced with multi-pass generation, chain-of-thought for visual tasks, and few-shot learning for structured output.
- **Frontend QA Engineer** -- Focused on automated comparison between generated HTML and source screenshots. Expert in visual diff tools, DOM structure validation, and content integrity verification.

Your mission: analyze the current landing page template generation system, identify exactly why it fails to produce faithful recreations, and deliver a concrete plan to fix it.

---

## Step 1: Deep System Analysis

Read and understand the following files thoroughly before proposing any changes.

### Core Files to Read

1. **`viraltracker/services/landing_page_analysis/mockup_service.py`**
   - The main service (1966 lines). Focus on:
     - `_build_vision_prompt()` (lines ~1238-1343) -- the prompt sent to Gemini
     - `_generate_via_ai_vision()` (lines ~1345-1402) -- how Gemini is called
     - `_extract_and_sanitize_css()` (lines ~1418-1445) -- CSS extraction pipeline
     - `_sanitize_html()` (lines ~784-801) -- the bleach sanitization pass
     - `_validate_analysis_slots()` (lines ~1006-1031) -- slot validation logic
     - `_validate_html_completeness()` (lines ~1033-1058) -- structural checks
     - `generate_analysis_mockup()` (lines ~380-465) -- the main entry point

2. **`viraltracker/services/gemini_service.py`**
   - Focus on `analyze_image()` (lines ~727-852):
     - How the image is decoded from base64 and sent to Gemini
     - The PIL Image conversion step
     - What model is being used (`gemini-2.5-flash` default)
     - Rate limiting and retry behavior

3. **`tests/test_mockup_service.py`**
   - Understand the existing test coverage, especially:
     - `TestBuildVisionPrompt` -- what the prompt looks like
     - `TestValidateAnalysisSlots` -- what slot coverage is expected
     - `TestBlueprintCssCarryThrough` -- the full pipeline test

4. **`viraltracker/ui/pages/33_*_Landing_Page_Analyzer.py`**
   - How `generate_analysis_mockup()` is called from the UI
   - What data is available at call time (screenshot, markdown, page_url, classification, element_detection)

### Test Case

Use `bobanutrition.co/pages/7reabreakfast` as the reference page for analysis. Known issues on this page:
- Author bio section has a small circular image (~60-80px) that gets rendered as an enormous full-width image in the mockup
- A summary paragraph appears in the mockup that does not exist on the original page
- Overall proportions are off (sections too tall, elements not properly sized)

---

## Step 2: Root Cause Analysis

For each of the following failure modes, identify the **specific technical root cause** in the current code and prompt. Do not speculate -- trace the issue through the code.

### 2.1 Image Sizing Problems

**Observed:** Images rendered at wrong dimensions. Small circular avatars become full-width blocks. Product thumbnails expand to hero size.

Investigate:
- Does the Gemini prompt give ANY guidance on image dimensions? (Check `_build_vision_prompt()`)
- When image URLs are included in the prompt, are dimensions provided? (Check `_extract_image_urls()`)
- Does the CSS allowlist include `width`, `height`, `max-width`, `max-height` for inline styles? (Check `_ALLOWED_CSS_PROPERTIES`)
- Does the CSS allowlist include `border-radius` (needed for circular images)? (Check `_ALLOWED_CSS_PROPERTIES`)
- Are `width` and `height` attributes allowed on `<img>` tags? (Check `_ALLOWED_ATTRS`)
- Does bleach strip dimension-related CSS properties during sanitization?
- Is the screenshot resolution high enough for Gemini to determine relative sizes?

### 2.2 Content Hallucination

**Observed:** Text appears in the mockup that does not exist on the original page. The model invents summary paragraphs, section introductions, or rephrasings.

Investigate:
- The prompt says "Reproduce ALL visible text content VERBATIM from the screenshot" -- is this instruction strong enough? Is it contradicted by other parts of the prompt?
- Is the page markdown being sent as "reference" giving Gemini license to rearrange or summarize content?
- Is there any post-generation step that compares generated text against the source? (There is not currently -- this is a gap.)
- Does the Gemini model (gemini-2.5-flash) have known tendencies toward hallucination on vision tasks? Would a different model (gemini-2.5-pro, for example) perform better?

### 2.3 Layout Fidelity

**Observed:** Overall structure is recognizable but proportions are wrong. Sections expand/compress incorrectly. Side-by-side layouts sometimes stack.

Investigate:
- Does the prompt provide any concrete dimensional references (e.g., "the hero section occupies approximately 60% of the viewport height")?
- Are CSS properties like `aspect-ratio`, `min-height`, `max-height` in the allowlist?
- Does the prompt instruct the model to use relative units (%, vw, vh) or fixed units (px, rem)?
- Is there guidance about viewport width assumptions?
- After sanitization, are any layout-critical CSS properties being stripped?

### 2.4 Color Accuracy

**Observed:** Colors approximate but do not match. Gradients are simplified. Subtle background tints are lost.

Investigate:
- Does the prompt ask for specific hex values, or just "extract colors"?
- Are CSS gradient functions (linear-gradient, radial-gradient) preserved by the sanitizer?
- Is `background-image` in the CSS allowlist? (It is -- but are gradient values inside it stripped by the url() sanitizer?)
- Does `_CSS_URL_RE` match `linear-gradient()` or `radial-gradient()` and incorrectly strip them?

---

## Step 3: Solution Exploration

For each area below, evaluate the approach and estimate impact (High/Medium/Low) and effort (hours).

### 3.1 Prompt Engineering

**Question:** Is the current prompt too vague? Too long? Does it give Gemini conflicting instructions?

Explore:
- **Instruction hierarchy** -- Currently all instructions are at the same level. Should critical instructions (verbatim text, image sizing) be separated and emphasized with stronger language?
- **Conflicting signals** -- Does telling Gemini to "use system font stack" conflict with "extract EXACT hex colors from the screenshot"? The model might interpret "use system fonts" as permission to deviate from the original.
- **Prompt length** -- The current prompt is ~40KB with markdown. Is this within Gemini's effective attention window? Does instruction-following degrade at this length?
- **Few-shot examples** -- Would including a before/after example (screenshot + expected HTML output) dramatically improve fidelity? What is the token cost of one example?
- **Negative examples** -- Would showing "DO NOT do this" examples (hallucinated text, oversized images) help?
- **Section-by-section instructions** -- Instead of one monolithic prompt, should we have Gemini process the page top-to-bottom in sections?

### 3.2 Multi-Pass Generation

**Question:** Should we break generation into multiple Gemini calls?

Explore:
- **Pass 1: Structure** -- Generate the HTML skeleton with correct layout (no text content, just structural elements with approximate sizing)
- **Pass 2: Content** -- Fill in all text content verbatim from the screenshot + markdown reference
- **Pass 3: Styling** -- Apply exact colors, spacing, fonts, and visual details
- **Pass 4: Validation** -- Have Gemini compare its own output against the screenshot and fix discrepancies

Considerations:
- Token cost multiplied by number of passes
- Each pass needs the screenshot (image tokens are not cheap)
- How to merge passes without losing information
- Whether Gemini can reliably diff its own output against a screenshot

### 3.3 Image Handling

**Question:** How to get image dimensions right?

Explore:
- **Extract actual dimensions from page** -- Can we use the web scraper to capture element bounding boxes (`getBoundingClientRect()`)? This would give us exact pixel dimensions for every image.
- **Include dimensions in the prompt** -- If we know `author-avatar.jpg` is 64x64px and circular, include that: `"author-avatar.jpg: 64x64px, border-radius: 50%"`
- **CSS constraints in prompt** -- Explicitly instruct: "Images should NOT exceed their container width. Use `max-width: 100%` and explicit width/height where visible in the screenshot."
- **Post-generation image audit** -- Parse the generated HTML, find all `<img>` and image placeholders, and validate their CSS dimensions against expectations.

### 3.4 Content Verification

**Question:** How to prevent hallucinated text?

Explore:
- **Post-generation diff** -- Extract all text nodes from the generated HTML, compare against page markdown using fuzzy matching (e.g., `difflib.SequenceMatcher`). Flag any text that has no close match in the original.
- **Strict verbatim mode** -- Restructure the prompt so Gemini receives the exact text to include (from markdown) and is told to place it in the correct structural position. It should NOT generate any text -- only position the provided text.
- **Content extraction + layout generation** -- Split the task: use the markdown for ALL text content, use the screenshot ONLY for layout/structure/colors. Gemini should not look at the screenshot for text at all.
- **Hallucination penalty** -- In the prompt, add an explicit penalty: "Any text that does not appear in the PAGE TEXT CONTENT section below is HALLUCINATED and must NOT be included. If you are unsure about text, leave the element empty rather than inventing content."

### 3.5 CSS Fidelity

**Question:** Are we losing important CSS during sanitization?

Explore:
- **Gradient preservation** -- Verify that `_CSS_URL_RE` does not accidentally match `linear-gradient()`, `radial-gradient()`, `conic-gradient()`. These are not `url()` values but could match the regex pattern.
- **CSS custom properties** -- Does the allowlist support `var(--custom-prop)`? These are commonly used in modern CSS.
- **CSS shorthand** -- Some shorthand properties may not be in the allowlist (e.g., `gap` is there, but `row-gap` / `column-gap` may not be).
- **Missing properties** -- Check if `aspect-ratio`, `clip-path`, `filter`, `backdrop-filter`, `mix-blend-mode`, `text-shadow`, `transition`, `animation` should be added.
- **Audit approach** -- Generate HTML for a known page, then diff the CSS properties used in the output against the allowlist. Log any properties that were stripped.

### 3.6 Screenshot Quality

**Question:** Is the screenshot resolution sufficient?

Explore:
- **Current capture** -- How is the screenshot captured? What resolution/viewport? (Check the web scraping service.)
- **Higher resolution** -- Would capturing at 2x DPI (device pixel ratio) improve Gemini's ability to read text and measure proportions?
- **Multiple viewports** -- Would capturing at multiple widths (desktop + mobile) and sending both screenshots improve the output?
- **Full-page vs viewport** -- Is the screenshot a full-page capture or just the viewport? A full-page capture may be too long, causing detail loss at the Gemini image processing stage.
- **Image token cost** -- What is the token cost of sending a higher-resolution screenshot? Is it worth the cost/latency tradeoff?

### 3.7 Structural Hints

**Question:** Should we provide the DOM structure or element bounding boxes to Gemini alongside the screenshot?

Explore:
- **Bounding box extraction** -- Modify the scraper to capture `getBoundingClientRect()` for major elements (sections, headings, images, buttons). Include as structured data: `{"element": "h1.hero-title", "x": 40, "y": 120, "width": 680, "height": 64}`
- **DOM skeleton** -- Extract a simplified DOM tree (just tag names, classes, and nesting depth) and include it in the prompt. This tells Gemini the structural intent.
- **CSS computed styles** -- Extract computed styles for key elements (font-size, color, background-color, padding) from the live page. Include as a "style reference" in the prompt.
- **Trade-offs** -- More structured data = more accurate output, but also more tokens and complexity. Find the minimum viable set of hints.

### 3.8 Post-Generation Validation

**Question:** Can we automatically compare the generated HTML against the original and flag major differences?

Explore:
- **Render-and-compare** -- Render the generated HTML in a headless browser, take a screenshot, and compare against the original using structural similarity (SSIM) or perceptual hash.
- **Text diff** -- Extract all visible text from both the original page and generated HTML, compute a diff, and flag additions/deletions.
- **Structure diff** -- Compare the DOM structure (tag hierarchy, section count, heading levels) between original and generated HTML.
- **Automated retry** -- If validation fails (e.g., SSIM below threshold, significant text additions), automatically retry with feedback: "Your previous output had these issues: [list]. Please fix them."
- **Human-in-the-loop** -- Show the user a side-by-side comparison and let them flag issues before proceeding to blueprint.

---

## Step 4: Deliverables

After completing the analysis above, produce the following:

### 4.1 Root Cause Report

A concise report mapping each quality issue to its specific technical cause:

```
| Issue | Root Cause | Evidence |
|-------|-----------|----------|
| Oversized images | No dimension hints in prompt; Gemini defaults to full-width | _build_vision_prompt() has no image size guidance |
| Hallucinated text | "VERBATIM" instruction insufficient; markdown ref gives permission to rearrange | Prompt says "use this as reference" which implies flexibility |
| ... | ... | ... |
```

### 4.2 Ranked Improvement List

Rank all proposed improvements by `(impact * confidence) / effort`:

```
| # | Improvement | Impact | Confidence | Effort | Score |
|---|------------|--------|------------|--------|-------|
| 1 | Add hallucination guard prompt language | High | High | 1h | 9.0 |
| 2 | Include image dimensions in prompt | High | Medium | 3h | 5.0 |
| ... | ... | ... | ... | ... | ... |
```

### 4.3 Implementation Plan

A phased plan (each phase independently deployable and testable):

**Phase A -- Prompt Hardening** (estimated X hours)
- Specific prompt rewrites (show exact before/after text)
- Test with 3+ reference pages and compare before/after quality

**Phase B -- Content Verification** (estimated X hours)
- Post-generation text diff implementation
- Hallucination detection and flagging

**Phase C -- Dimensional Accuracy** (estimated X hours)
- Image dimension extraction from scraper
- Structural hints in prompt
- Post-generation dimension validation

**Phase D -- Multi-Pass Generation** (estimated X hours, if deemed worthwhile)
- Architecture changes for multi-pass pipeline
- Pass definitions and merge logic

### 4.4 Prompt Rewrites

For each prompt change, provide the exact `old_string` and `new_string` for the Edit tool. Example format:

```
### Change 1: Stronger anti-hallucination language

**File:** viraltracker/services/landing_page_analysis/mockup_service.py

**Before (lines ~1278-1281):**
"## TEXT CONTENT\n"
"- Reproduce ALL visible text content VERBATIM from the screenshot\n"
"- If text is hard to read, use the PAGE TEXT CONTENT section below as reference\n\n"

**After:**
"## TEXT CONTENT (CRITICAL -- DO NOT HALLUCINATE)\n"
"- Reproduce ONLY text that is visible in the screenshot. Do NOT add, summarize, or rephrase.\n"
"- If text is hard to read in the screenshot, check the PAGE TEXT CONTENT section.\n"
"- If text does not appear in EITHER the screenshot or PAGE TEXT CONTENT, DO NOT include it.\n"
"- NEVER add introductory paragraphs, summaries, or transitions that are not on the original page.\n\n"
```

### 4.5 Architectural Changes

Document any changes to the service interface, database schema, or pipeline flow. Include migration SQL if needed. Ensure all changes maintain:

- The `data-slot` contract (slots must survive through blueprint rewriting)
- CSS safety (sanitization pipeline must not be weakened)
- Gemini context window limits (total prompt size must stay under limits)
- Blueprint round-trip integrity (analysis HTML is stored in DB, later extracted for blueprint, rewritten with brand copy, and re-wrapped -- CSS and structure must survive all stages)

---

## Constraints (DO NOT VIOLATE)

1. **data-slot contract** -- Every replaceable text element must have a `data-slot` attribute with the naming convention defined in `_build_vision_prompt()`. The blueprint rewrite step (`_rewrite_html_for_brand()`) depends on these slots.

2. **CSS safety** -- The sanitization pipeline (`_sanitize_css_block()`, bleach CSSSanitizer, `_strip_url_from_inline_styles()`, `_sanitize_img_src()`) must remain intact. Any changes to allowlists must be justified and safe.

3. **Gemini context window** -- Total prompt size (text + image tokens) must stay within Gemini's effective processing window. The current `_PROMPT_TEXT_BUDGET` is 40KB. Do not exceed this without evidence that it helps.

4. **Blueprint round-trip** -- The full pipeline is:
   ```
   Screenshot --> Gemini --> raw HTML
   --> _extract_and_sanitize_css() --> (body, css)
   --> _sanitize_html(body)
   --> _validate_analysis_slots()
   --> _wrap_mockup(body, css)     [persisted to DB as analysis_mockup_html]
   --> _extract_page_css_and_strip()  [on blueprint gen]
   --> _rewrite_html_for_brand()
   --> _sanitize_html()
   --> _wrap_mockup(rewritten, css)   [persisted as blueprint_mockup_html]
   ```
   Changes must not break any stage of this pipeline.

5. **Incremental and testable** -- Each improvement should be deployable independently. Add tests for new behavior. Verify with `python3 -m py_compile` and the existing test suite (191 tests must continue to pass).

6. **No em dashes** -- All AI-generated customer-facing text must avoid em dashes. The `_sanitize_dashes()` function handles this in the blueprint rewrite path, but the analysis path should also avoid them in the prompt instructions.

---

## How to Use This Prompt

1. Start a fresh Claude Code session on the `feat/ad-creator-v2-phase0` branch
2. Read this file and `CHECKPOINT_001.md`
3. Read the files listed in Step 1 (mockup_service.py, gemini_service.py, tests, UI page)
4. Work through Steps 2-4 systematically
5. Implement the highest-impact changes first (Phase A from your plan)
6. Test after each change: `python3 -m pytest tests/test_mockup_service.py -v`
7. Create `CHECKPOINT_002.md` with results

---

## Reference: Current Prompt (for context)

The current vision prompt (`_build_vision_prompt()`) includes these sections:
- `## LAYOUT REQUIREMENTS` -- Semantic HTML, max-width, flexbox, CSS grid
- `## TYPOGRAPHY` -- System font stack, heading sizes, color extraction
- `## SPACING & VISUAL` -- Section padding, margins, button styles
- `## CSS APPROACH` -- Style blocks vs inline, class-based preference
- `## TEXT CONTENT` -- Verbatim reproduction instruction
- `## SLOT MARKING CONTRACT` -- data-slot naming convention
- `## ACTUAL IMAGE URLs` (if available) -- Validated image URLs from markdown
- `## PAGE TEXT CONTENT` (if available) -- Truncated page markdown
- `## IMAGES` (if no URLs) -- Placeholder div instruction

The prompt is approximately 2-4KB of instructions plus up to 30KB of page markdown, plus a base64-encoded screenshot image.
