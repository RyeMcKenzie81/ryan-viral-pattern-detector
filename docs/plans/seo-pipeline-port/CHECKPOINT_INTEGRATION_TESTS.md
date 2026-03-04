# SEO Pipeline Port — Integration Tests Checkpoint

**Date**: 2026-03-03
**Branch**: `worktree-seo-pipeline-port`
**Status**: 5 BUG FIXES + 29 INTEGRATION TESTS COMPLETE
**Tests**: 120 SEO pipeline tests passing (44 graph + 47 models/state + 29 integration)

---

## What Was Done

### Step 0: Fixed 5 Node→Service Parameter Mismatch Bugs

These bugs were latent — masked by unit tests mocking entire service classes. They would cause `TypeError`/`AttributeError` at runtime.

| Bug | File | Problem | Fix |
|-----|------|---------|-----|
| 1 | `nodes/keyword_discovery.py:48-53` | Passed `seed_keywords=` (wrong name), included `organization_id` (not a param) | Changed to `seeds=`, removed `organization_id` |
| 2 | `nodes/content_generation.py:69-74` (Phase A) | Passed `brand_id` (not a param), missing `keyword`, `competitor_data`, `author_id` | Added correct params, removed `brand_id` |
| 3 | `nodes/content_generation.py:174-178` (Phase B) | Passed `brand_id` (not a param), missing `keyword`, `phase_a_output`, `author_id` | Added correct params, removed `brand_id` |
| 4 | `nodes/content_generation.py:227-231` (Phase C) | Passed `brand_id` (not a param), missing `keyword`, `phase_b_output`, `competitor_data`, `author_id` | Added correct params, removed `brand_id` |
| 5 | `nodes/competitor_analysis.py:48-63` | Called `service.analyze_page()` + `service.calculate_winning_formula()` — neither exists | Replaced with single `service.analyze_urls(keyword_id, urls)` call |

### Step 1: Updated Existing Unit Tests

Updated `tests/test_seo_pipeline_graph.py` mock assertions:
- `TestCompetitorAnalysisNode` — now mocks `analyze_urls` instead of `analyze_page`/`calculate_winning_formula`
- Added `selected_keyword_id` to mock state for competitor analysis tests
- All 44 graph tests pass with corrected assertions

### Step 2: Created Integration Test File

`tests/test_seo_pipeline_integration.py` — 29 tests across 9 classes:

| Class | Tests | What It Covers |
|-------|-------|----------------|
| `TestPhase1StateRoundtrip` | 3 | State serialization, JSON round-trip, checkpoint preservation |
| `TestPhase2KeywordDiscovery` | 4 | Variations generation, keyword filtering, full discover flow, cross-seed tracking |
| `TestPhase3CompetitorAnalysis` | 4 | HTML parsing (20+ metrics), Flesch scoring, winning formula, full analyze_urls |
| `TestPhase4ContentGeneration` | 4 | Phase A/B/C prompt building, author context loading |
| `TestPhase5aQAValidation` | 3 | Passing article, failing article, warning vs error distinction |
| `TestPhase5bCMSPublisher` | 3 | Markdown→HTML, Shopify payload, URL slug generation |
| `TestPhase6aInterlinking` | 4 | Jaccard similarity, anchor text, link insertion, full suggest_links |
| `TestPhase6bArticleTracking` | 3 | Status lifecycle, invalid transitions, force override |
| `TestEndToEndPipeline` | 1 | Full graph run with 4 human checkpoint pauses + resumes |

### Key Test Data Constants

- `COMPETITOR_HTML` — ~80 lines realistic HTML with schema, FAQ, headings, links, images, TOC, author byline
- `PASSING_ARTICLE_MD` — ~600-word well-structured markdown (proper headings, keyword placement, internal links, images, schema)
- `FAILING_ARTICLE_MD` — ~200-word poorly structured article (no headings, no links, em dashes)

---

## Files Modified

### Bug fixes:
- `viraltracker/services/seo_pipeline/nodes/keyword_discovery.py` — Bug 1
- `viraltracker/services/seo_pipeline/nodes/competitor_analysis.py` — Bug 5
- `viraltracker/services/seo_pipeline/nodes/content_generation.py` — Bugs 2, 3, 4

### Test updates:
- `tests/test_seo_pipeline_graph.py` — Updated mock assertions for 5 fixed nodes

### New files:
- `tests/test_seo_pipeline_integration.py` — 29 integration tests

---

## Known Issues / Gotchas

1. **`bs4` dependency**: `competitor_analysis_service.py` and `qa_validation_service.py` import `from bs4 import BeautifulSoup` at module level. Must have `beautifulsoup4` installed.
2. **Publish step name**: `PublishNode` calls `mark_step_complete("publishing")` not `"publish"` — use `"publishing"` in assertions.
3. **TOC detection**: The HTML parser decomposes `<nav>` tags before checking for TOC. Use `<div class="table-of-contents">` in test HTML, not `<nav>`.
4. **PYTHONPATH**: Must prepend worktree path when running tests: `PYTHONPATH=/Users/ryemckenzie/projects/viraltracker/.claude/worktrees/seo-pipeline-port:$PYTHONPATH`

---

## Running Tests

```bash
# From the worktree directory
cd /Users/ryemckenzie/projects/viraltracker/.claude/worktrees/seo-pipeline-port

# All SEO pipeline tests (120 tests)
PYTHONPATH=$(pwd):$PYTHONPATH python3 -m pytest tests/test_seo_pipeline*.py -v

# Just integration tests (29 tests)
PYTHONPATH=$(pwd):$PYTHONPATH python3 -m pytest tests/test_seo_pipeline_integration.py -v

# Just graph unit tests (44 tests)
PYTHONPATH=$(pwd):$PYTHONPATH python3 -m pytest tests/test_seo_pipeline_graph.py -v
```

---

## Next Steps

1. **Run migration** `migrations/2026-03-02_seo_pipeline_tables.sql` against Supabase
2. **Set up env vars**: `SUPABASE_URL`, `SUPABASE_SERVICE_KEY`, `ANTHROPIC_API_KEY`, `FIRECRAWL_API_KEY`
3. **Run mock tests** to verify they pass in the live environment
4. **Run real-data tests** against live Supabase + services
5. **Commit all changes** on the branch
6. **Create PR** to merge into main
