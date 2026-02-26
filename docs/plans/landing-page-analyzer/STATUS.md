# Landing Page Analyzer — Status

**Last Updated:** 2026-02-26

## Phase Overview

| Phase | Description | Status | Checkpoint |
|-------|-------------|--------|------------|
| Phase 0 | Schema extensions (brand voice/colors, product blueprint fields) | Done | `CHECKPOINT_PHASE_0_1A.md` |
| Phase 1A | Foundation (service, models, prompts package) | Done | `CHECKPOINT_PHASE_0_1A.md` |
| Phase 1B | Analysis pipeline (Skills 1-4 prompts, parallel execution) | Done | `CHECKPOINT_PHASE_0_1A.md` |
| Phase 1C | Analysis UI (Tab 1 Analyze, Tab 2 Results) | Done | `CHECKPOINT_PHASE_0_1A.md` |
| Phase 2A | Brand Profile + Blueprint Service (Skill 5) | Done | `CHECKPOINT_PHASE_2.md` |
| Phase 2B | Blueprint UI (Tab 3) | Done | `CHECKPOINT_PHASE_2.md` |
| Phase 2C | Chunked streaming blueprint fix | Done | `CHECKPOINT_PHASE_2_CHUNKED_BLUEPRINT.md` |
| Phase 2D | Persona selector for blueprint generation | Done | `CHECKPOINT_PERSONA_SELECTOR.md` |
| Surgery CSS Phase 1 | Fetch all external CSS (not just first-party) | Done | `CHECKPOINT_PHASE1_CSS_FETCH.md` |
| Surgery CSS Phase 2 | Standalone HTML output (no CSS scoping) | Done | `CHECKPOINT_STANDALONE_HTML_PROPOSAL.md` |
| Surgery CSS Phase 2 Integration | mockup_service, api/app.py, docstring fixes | Done | — |
| Surgery Scroll Fix | Strip scroll-blocking classes + CSS override | Done | — |
| **Manual QA** | **Test surgery pipeline E2E on multiple pages** | **Next** | — |

## Surgery Pipeline CSS Fix — Summary

### Problem
S3 (CSS Scoping) was destroying visual quality by regex-prefixing all CSS rules with `.lp-mockup`. This broke complex selectors, pseudo-elements, and media queries. Only 1/5 external stylesheets were fetched. SSIM was ~0.60.

### Solution (2 phases)

**Phase 1 — Fetch all external CSS:**
- Increased external CSS fetch limit from 3→10 for surgery path
- Added `fetch_raw_external_css()` to bypass CSS parsing/reordering
- Added `_rewrite_css_urls()` for relative URL resolution
- Increased max CSS response from 500KB→2MB
- Result: Necessary but not sufficient (SSIM unchanged at 0.603)

**Phase 2 — Standalone HTML (no CSS scoping):**
- Rewrote `CSSScoper` to produce complete `<!DOCTYPE html>` documents
- Removed `.lp-mockup` CSS prefixing entirely
- Added `data-pipeline="surgery"` on `<body>` for downstream detection
- Fixed CSS cascade order: external CSS first, then inline overrides
- Result: **SSIM 0.604 → 0.772**

**Integration fixes:**
- Added `link` to `_ALLOWED_TAGS` in mockup_service.py (Google Fonts `<link>` preservation)
- Fixed double-wrapping in api/app.py public preview (detect full documents)
- Updated docstrings in section_templates.py, html_extractor.py, pipeline.py

**Scroll fix:**
- Klaviyo injects `class="klaviyo-prevent-body-scrolling"` on `<body>` with
  `body.klaviyo-prevent-body-scrolling{overflow:hidden !important}` — prevents scrolling
- Strip known scroll-blocking classes from `<body>` during CSS consolidation
- Append `html,body{overflow:auto !important;height:auto !important}` CSS override as fallback
- Blocked classes: `klaviyo-prevent-body-scrolling`, `no-scroll`, `modal-open`, `overflow-hidden`

### Files Changed

| File | Changes |
|------|---------|
| `multipass/surgery/css_scoper.py` | Complete rewrite — standalone HTML, no scoping |
| `multipass/html_extractor.py` | `fetch_raw_external_css()`, URL rewriting, content-type validation |
| `multipass/surgery/pipeline.py` | Uses raw CSS fetch, updated docstring |
| `multipass/surgery/prompts.py` | Removed `.lp-mockup` from S4 prompt |
| `multipass/phase_diagnostics.py` | `data-pipeline="surgery"` detection instead of `.lp-mockup` |
| `multipass/section_templates.py` | Updated docstring |
| `mockup_service.py` | Added `link` tag to bleach allowlist |
| `api/app.py` | Fixed double-wrapping in public preview |
| `tests/test_multipass_v4.py` | Updated CSS scoper tests, added fetch + scroll tests (410 total) |

### Known Blockers Resolved

| # | Blocker | Resolution |
|---|---------|------------|
| B1 | Bleach strips `<link>` tags | Added `link` to `_ALLOWED_TAGS` with href/rel/type/crossorigin attrs |
| B2 | Non-surgery pipeline also uses `.lp-mockup` | Kept `.lp-mockup` for reconstruction path, only changed surgery |
| B3 | `_strip_mockup_wrapper()` destroys `<style>` blocks | MockupService `_wrap_mockup()` is normalization boundary — safe |

### Known Traps Resolved

| # | Trap | Resolution |
|---|------|------------|
| T1 | Eval harness checks for `.lp-mockup` | Updated phase_diagnostics.py to check `data-pipeline="surgery"` |
| T2 | S4 prompt hardcodes `.lp-mockup` selectors | Updated prompts.py to use standard selectors |
| T3 | Public preview double-wraps documents | api/app.py now detects full documents and serves as-is |
| T5 | `is_surgery_mode` CSS limit fallback | `data-pipeline="surgery"` preserved on `<body>` tag |
| T6 | Third-party scroll-blocking classes on `<body>` | Strip known classes + CSS override with `!important` |

### Commits

| Hash | Description |
|------|-------------|
| `8f4b8db` | feat: standalone HTML surgery output + full external CSS fetching |
| `5b48a49` | fix: surgery pipeline integration — bleach allowlist, preview double-wrap, docstrings |
| `7696d94` | fix: strip scroll-blocking classes from body tag in surgery output |

---

## Previous Phases

### What Needs Testing (Phases 0-2D)

#### Phase 0+1: Analysis Pipeline
1. Brand Manager — verify brand voice/tone, colors, and product blueprint fields save correctly
2. Tab 1 (Analyze) — scrape a URL and run the 4-skill pipeline end-to-end
3. Tab 2 (Results) — verify analysis renders with all 4 sub-tabs (Classification, Elements, Gaps, Copy Scores)

#### Phase 2: Blueprint
4. Tab 3 (Blueprint) — select product, offer variant, and a completed analysis
5. Generate a blueprint — verify 4-step progress and section accordion renders
6. Check CONTENT NEEDED highlighting for brands with incomplete data
7. Test JSON and Markdown exports
8. Test multi-brand: same analysis, different brand → different blueprint
9. Verify past blueprints section loads correctly

## Migrations (already run)
- `migrations/2026-02-09_landing_page_blueprint_fields.sql`
- `migrations/2026-02-09_landing_page_analyses.sql`
- `migrations/2026-02-09_landing_page_blueprints.sql`
- `migrations/2026-02-09_landing_page_blueprints_add_persona_id.sql`
- `migrations/2026-02-10_landing_page_blueprints_add_partial_status.sql`

## Feature Flag
```sql
-- Required for the page to appear in navigation
INSERT INTO org_features (organization_id, feature_key, enabled)
VALUES ('your-org-id', 'landing_page_analyzer', true);
```

## Tech Debt (deferred)
- #16: Unit tests for Phase 1 (analysis_service, models)
- #17: Unit tests for Phase 2 + enhancements (docx export, comparison view, screenshot storage, retry failed)
