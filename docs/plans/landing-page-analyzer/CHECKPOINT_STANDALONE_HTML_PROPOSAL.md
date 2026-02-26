# Checkpoint: Standalone HTML Serving Proposal

**Date**: 2026-02-26
**Branch**: `feat/ad-creator-v2-phase0`
**Last Commit**: `e6df6b1` — fix: unblock S4 visual QA in surgery pipeline

---

## Context: What Just Happened

The S4 Visual QA step in the surgery pipeline was completely dead code due to three bugs:
1. Playwright sync/async conflict (sync Playwright called from async context)
2. Missing `GeminiService.generate_content_async()` method
3. Expired Gemini model + wrong `PatchApplier` method signature

All three were fixed in commit `e6df6b1`. S4 now runs end-to-end: renders HTML, scores SSIM, calls Gemini for CSS patches, applies them with slot-preservation validation.

**However**, the underlying visual quality is poor (SSIM ~0.60) because S3 (CSS Scoping) only fetches first-party external CSS (1/5 stylesheets). The CSS scoping approach is fundamentally fragile:
- Regex-scopes 500KB+ CSS under `.lp-mockup`
- Truncates external CSS at 512KB
- Only fetches first-party stylesheets (misses CommerceSpace, Swiper, Klaviyo, Google Fonts)
- S4 patches can't compensate for missing entire stylesheets

## Proposed Change: Serve Standalone HTML

Instead of embedding scoped HTML fragments in the Streamlit UI, serve landing page mockups as **standalone HTML documents at their own URLs**.

### Current Architecture

```
Surgery Pipeline → S3: Scope CSS under .lp-mockup, strip <html>/<head>/<body>
                     → Output: HTML fragment wrapped in <div class="lp-mockup">
                     → Display: st.components.html() inline embed
                     → Problem: CSS scoping loses 4/5 external stylesheets
```

### Proposed Architecture

```
Surgery Pipeline → S3: Download ALL external CSS, inline as <style> blocks
                     → Keep full <html>/<head>/<body> document structure
                     → Output: Complete standalone HTML document
                     → Storage: Supabase storage or DB column (already exists)
                     → Display: Served at /preview/{id} or iframe srcdoc
```

### What Changes

| Component | Current | Proposed |
|-----------|---------|----------|
| **S3 (CSSScoper)** | Regex-scope all CSS under `.lp-mockup`, strip document wrapper | Download ALL external CSS (not just first-party), inline as `<style>` blocks. Keep full document. No scoping. |
| **S4 (Visual QA)** | SSIM ~0.60 due to missing CSS | SSIM should be much higher — all CSS present |
| **Storage** | `blueprint_mockup_html` TEXT column in `landing_page_blueprints` | Same column, but stores complete HTML doc instead of fragment |
| **Streamlit Display** | `st.components.html()` with CSS scale transform | iframe with srcdoc, or link to preview URL |
| **Public Preview** | `GET /api/public/blueprint/{share_token}` already exists | Same endpoint, already returns `HTMLResponse` |
| **Blueprint Slot System** | Operates on `data-slot`/`data-section` attributes | **Unchanged** — attributes are in HTML body, not affected by CSS approach |
| **MockupService** | Extracts CSS from `<style>` blocks, sanitizes, wraps in mockup shell | Needs update: work with full document instead of fragment |

### What Stays The Same

- S0 (Sanitize), S1 (Segment), S2 (Classify/slot-tag) — untouched
- `data-slot`, `data-section`, `data-pipeline="surgery"` attributes — untouched
- Blueprint AI rewriting (`_rewrite_slots_for_brand()`) — untouched
- Template swap (`_template_swap()`) — untouched
- Listicle detection and numbering safety — untouched
- Quality gates (nav junk, incomplete sentences) — untouched
- Image replacement service — untouched
- XSS sanitization via bleach — untouched

### Key Interface Points (Blueprint Compatibility)

The blueprint system interacts with surgery output via:
1. **`data-pipeline="surgery"`** attribute — triggers surgery-mode CSS preservation in MockupService
2. **`data-slot="..."` attributes** — used by `_extract_slots_with_content()` and `_template_swap()`
3. **`data-section="..."` attributes** — used by `_map_slots_to_sections()` for section context
4. **CSS in `<style>` blocks** — extracted by MockupService for sanitization and re-injection
5. **`.lp-mockup` wrapper** — currently expected by scoped CSS selectors

Items 1-4 are unaffected by the proposal. Item 5 (`.lp-mockup` wrapper) would be removed since CSS no longer needs scoping. The MockupService `_wrap_mockup()` method would need updating.

### External CSS Fetching Strategy

Current `CSSExtractor` behavior:
- Only fetches first-party CSS (`_is_first_party()` check)
- Skips known CDNs (`cdn.jsdelivr.net`, `fonts.googleapis.com`, etc.)
- Max 3 external fetches, 512KB truncation per file

Proposed:
- Fetch ALL `<link rel="stylesheet">` URLs (not just first-party)
- Keep CDN `<link>` tags as-is for fonts (Google Fonts, etc.) — browser loads them
- Download and inline site-specific CSS for stability (snapshot in time)
- OR: keep all `<link>` tags and let browser load everything (simpler, but depends on CDN availability)

### Risk Assessment

| Risk | Severity | Mitigation |
|------|----------|------------|
| Blueprint slot system breaks | HIGH | Verify: slots are in HTML body, not CSS. `data-slot`/`data-section` unaffected. |
| MockupService `_wrap_mockup()` breaks | MEDIUM | Update to work with full document structure instead of fragment |
| `is_surgery_mode` detection breaks | LOW | Still check for `data-pipeline="surgery"` — that attribute stays |
| CSS sanitization in MockupService | MEDIUM | Currently extracts from `<style>` blocks — needs to handle `<link>` tags if we keep them |
| Streamlit inline preview breaks | MEDIUM | Switch to iframe-based preview or link-out |
| Public preview endpoint | LOW | Already serves `HTMLResponse` — just serves a bigger document |
| CDN availability for external resources | LOW | Images already load from CDNs today. CSS can be inlined for stability. |
| Large HTML documents in DB column | LOW | Already storing large HTML. Could move to Supabase Storage if needed. |
| `st.components.html()` security sandbox | MEDIUM | iframe srcdoc may have different security constraints than inline HTML |

---

## Files That Would Change

1. `viraltracker/services/landing_page_analysis/multipass/surgery/css_scoper.py` — Replace scoping with CSS consolidation
2. `viraltracker/services/landing_page_analysis/multipass/surgery/pipeline.py` — S3 produces full doc, S4 compares against it
3. `viraltracker/services/landing_page_analysis/multipass/html_extractor.py` — `CSSExtractor` fetches all external CSS
4. `viraltracker/services/landing_page_analysis/mockup_service.py` — Handle full document instead of fragment
5. `viraltracker/ui/pages/33_🏗️_Landing_Page_Analyzer.py` — Preview rendering (iframe or link)
6. `viraltracker/api/app.py` — Public preview (may need no changes)

## Open Questions

1. **Inline all CSS vs keep `<link>` tags?** — Inlining creates a stable snapshot but bloats HTML. Keeping `<link>` tags is simpler but breaks if CDN changes.
2. **How to handle `<link>` to Google Fonts?** — These need the browser to load them. Can keep as `<link>` in `<head>` even if other CSS is inlined.
3. **Streamlit preview: iframe srcdoc vs link-out?** — iframe keeps user on page but has size/interaction limits. Link-out is simpler.
4. **Storage: DB column vs Supabase Storage?** — Full HTML docs could be 500KB-1MB. Current TEXT column works but Supabase Storage might be cleaner for large docs.
5. **Should we serve from the app server or static storage?** — App server gives us auth/tracking. Static storage is simpler but no access control.

---

## Deep Analysis Results (2026-02-26)

Three independent review agents analyzed this proposal. Key findings below.

### Verdict: CONDITIONAL PASS — Phase the work

The full standalone-document architecture is the right long-term direction, but it's bigger than it looks. A simpler Phase 1 fix addresses the immediate SSIM problem with minimal risk.

### BLOCKERS Found (3)

| # | Finding | File | Impact |
|---|---------|------|--------|
| B1 | **Bleach strips `<style>` and `<link>` tags** — `_ALLOWED_TAGS` in mockup_service.py doesn't include `link`. If proposal keeps `<link>` tags for Google Fonts, bleach silently deletes them. | `mockup_service.py:271-296` | Silent font loss |
| B2 | **Non-surgery pipeline also uses `.lp-mockup`** — reconstruction pipeline at `multipass/pipeline.py:1540,1560,1630` also wraps and scopes CSS under `.lp-mockup`. Removing it from surgery alone creates two incompatible output formats. | `multipass/pipeline.py` | Format bifurcation |
| B3 | **`_strip_mockup_wrapper()` destroys all `<style>` blocks** — this method (mockup_service.py:1027-1056) regex-strips `<head>`, `<style>`, `<body>`, `<html>` tags. If standalone HTML with ALL CSS inline goes through this, result has zero styling. | `mockup_service.py:1027-1056` | Blueprint renders unstyled |

### TRAPS Found (5)

| # | Finding | File | Impact |
|---|---------|------|--------|
| T1 | **Eval harness hard-fails without `.lp-mockup`** — `_has_lp_mockup_wrapper()` in phase_diagnostics.py reports "ISSUE: .lp-mockup wrapper missing" for every eval run. Corrupts quality metrics. | `phase_diagnostics.py:293,612` | All evals report false failures |
| T2 | **S4 LLM prompt hardcodes `.lp-mockup` selectors** — prompt tells LLM to "Target .lp-mockup scoped selectors". Without `.lp-mockup`, patches silently match nothing. | `surgery/prompts.py:69-82` | S4 patches silently stop working |
| T3 | **Public preview double-wraps documents** — `app.py:222-231` wraps stored HTML in `<!DOCTYPE>` shell. Already a latent bug since `_wrap_mockup()` already produces a complete document. | `api/app.py:222-231` | Pre-existing bug, worsens |
| T4 | **Containment CSS clips standalone pages** — `contain: layout style paint` on `.lp-mockup` clips content at container boundary. If carried over accidentally to standalone page, content below fold invisible. | `css_scoper.py:16-19` | Below-fold content hidden |
| T5 | **`is_surgery_mode` CSS limit fallback** — if `data-pipeline="surgery"` detection fails, CSS size limit drops from 2.5MB to 100KB, silently truncating all styling for large pages. | `mockup_service.py:36-37,667` | Silent CSS truncation |

### DEBT Items (4)

| # | Finding | File | Impact |
|---|---------|------|--------|
| D1 | **12+ tests assert `.lp-mockup` format** — test_multipass_v4.py has 40+ assertions. All CSS scoping tests + snapshot files need rewriting. | `tests/test_multipass_v4.py` | Test maintenance |
| D2 | **`st.components.html()` embeds raw HTML** — full `<!DOCTYPE>` nested inside Streamlit iframe body creates invalid nested HTML. | `33_Landing_Page_Analyzer.py:139-163` | Preview rendering quirks |
| D3 | **Section templates assume `.lp-mockup` context** — documented dependency on `.lp-mockup` for box-sizing reset and containment. | `section_templates.py:10` | Cascade changes |
| D4 | **`_scope_css_under_class` shared utility** — used by both surgery and reconstruction pipelines. Removing from one without the other creates divergence. | `html_extractor.py:321` | Code divergence |

### Critical Insight: MockupService Is Well-Insulated

The blueprint compatibility agent found that **the blueprint system is actually well-insulated** from surgery output format. The key is `_wrap_mockup()` acting as a normalization boundary:

```
Surgery output (any format)
  → _extract_and_sanitize_css()   ← extracts <style> blocks (regex, format-agnostic)
  → _sanitize_html()              ← bleach clean
  → _wrap_mockup()                ← produces standardized <!DOCTYPE> document
  → Stored in DB                  ← always same format regardless of upstream
  → Blueprint pipeline reads      ← always reads from _wrap_mockup format
```

This means **slot operations are completely safe**: `_extract_slots_with_content()`, `_map_slots_to_sections()`, `_template_swap()`, `_rewrite_slots_for_brand()` — all attribute-based HTMLParser operations that don't care about document structure.

### Recommended Approach: Two Phases

**Phase 1 — Immediate fix (LOW RISK, 1-2 files)**

Remove the first-party CSS filter in `CSSExtractor.extract()` for the surgery path. Increase `_MAX_EXTERNAL_CSS_FETCHES` from 3 to 8-10. Keep existing scoping/fragment architecture.

- Fixes: 4/5 external stylesheets now fetched
- Risk: Near zero (scoping stays, fragment model stays)
- Expected SSIM improvement: 0.60 → 0.75-0.85
- Files changed: `html_extractor.py` (remove `_is_first_party` guard)

Additional Phase 1 improvements:
- Add content-type validation to `_safe_fetch_css()` (reject non-CSS responses)
- Rewrite relative `url()` paths to absolute in fetched CSS (critical for CDN CSS)
- Parallelize CSS fetches with `asyncio.gather()`

**Phase 2 — Standalone document architecture (MEDIUM RISK, 8-10 files)**

Only if Phase 1 SSIM is still insufficient:

1. `css_scoper.py` — Replace scoping with CSS consolidation
2. `multipass/pipeline.py` — Update reconstruction pipeline too
3. `surgery/prompts.py` — Remove `.lp-mockup` from S4 prompt
4. `mockup_service.py` — Increase `_CSS_MAX_SIZE_SURGERY` to 5MB, add `link` to `_ALLOWED_TAGS`
5. `api/app.py` — Fix double-wrapping bug (serve HTML as-is)
6. `phase_diagnostics.py` — Update `.lp-mockup` checks
7. `section_templates.py` — Update containment assumptions
8. `tests/test_multipass_v4.py` — Rewrite 40+ assertions
9. Add format detection for old vs new blueprints in DB
10. Preserve `data-pipeline="surgery"` on `<body>` tag
