# SEO Pipeline Integration Tests + Bug Fixes

## Context

All 7 phases of the SEO pipeline are implemented with 431 unit tests passing and a PASS on the post-plan review. However, the unit tests mock entire service classes at the boundary, which masked **5 latent parameter/method mismatch bugs** between nodes and their services. The user wants integration tests that exercise real business logic, walk through each phase, then run end-to-end.

**No real API keys, database, or network access needed** — all external deps are mocked. Prompt template files on disk ARE needed (they exist already).

## Prerequisites (user must do before running pipeline for real)

### SQL Migration
Run `migrations/2026-03-02_seo_pipeline_tables.sql` in Supabase. Creates 9 tables:
- `seo_projects`, `seo_authors`, `seo_clusters`, `seo_keywords`, `seo_articles`
- `seo_competitor_analyses`, `seo_article_rankings`, `seo_internal_links`, `brand_integrations`
- Plus 15 indexes, 7 `updated_at` triggers, RLS policies on all tables

### Environment Variables (for real pipeline runs, NOT needed for tests)
| Variable | Purpose |
|----------|---------|
| `SUPABASE_URL` + `SUPABASE_SERVICE_KEY` | All DB operations |
| `ANTHROPIC_API_KEY` | Content generation (Phases A/B/C) — or use `mode="cli"` to skip |
| `FIRECRAWL_API_KEY` | Competitor analysis web scraping |
| Shopify config in `brand_integrations` table | CMS publishing (store_domain, access_token, blog_id) |

### Python Packages (verify installed)
`beautifulsoup4`, `markdown-it-py`, `httpx`, `pydantic-graph`, `anthropic` — should be in venv already.

---

## Step 0: Fix 5 Node→Service Bugs

These bugs cause `TypeError`/`AttributeError` at runtime when nodes call real services. Masked by unit tests that mock entire service classes.

### Bug 1: `nodes/keyword_discovery.py:48-53`
**Problem:** Node passes `organization_id` (not a param) and `seed_keywords` (should be `seeds`).
**Service sig:** `discover_keywords(self, project_id, seeds, min_word_count=3, max_word_count=10)`
**Fix:** Change to `seeds=ctx.state.seed_keywords`, remove `organization_id`.

### Bug 2: `nodes/content_generation.py:69-74` (ContentPhaseANode)
**Problem:** Node passes `brand_id` (not a param), missing required `keyword`. Missing `competitor_data`, `author_id`.
**Service sig:** `generate_phase_a(self, article_id, keyword, competitor_data=None, brand_context=None, author_id=None, mode="api", organization_id=None, model=...)`
**Fix:** Add `keyword=ctx.state.selected_keyword`, `competitor_data={"winning_formula": ctx.state.winning_formula, "results": ctx.state.competitor_results}`, `author_id=str(ctx.state.author_id) if ctx.state.author_id else None`. Keep `organization_id`, `mode`. Remove `brand_id`.

### Bug 3: `nodes/content_generation.py:174-178` (ContentPhaseBNode)
**Problem:** Node passes `brand_id` (not a param), missing required `keyword` and `phase_a_output`.
**Service sig:** `generate_phase_b(self, article_id, keyword, phase_a_output, brand_context=None, author_id=None, mode="api", organization_id=None, ...)`
**Fix:** Add `keyword=ctx.state.selected_keyword`, `phase_a_output=ctx.state.phase_a_output or ""`, `author_id=str(ctx.state.author_id) if ctx.state.author_id else None`. Keep `organization_id`, `mode`. Remove `brand_id`.

### Bug 4: `nodes/content_generation.py:227-231` (ContentPhaseCNode)
**Problem:** Node passes `brand_id` (not a param), missing required `keyword` and `phase_b_output`.
**Service sig:** `generate_phase_c(self, article_id, keyword, phase_b_output, competitor_data=None, existing_articles=None, brand_context=None, author_id=None, mode="api", organization_id=None, ...)`
**Fix:** Add `keyword=ctx.state.selected_keyword`, `phase_b_output=ctx.state.phase_b_output or ""`, `competitor_data={"winning_formula": ctx.state.winning_formula}`, `author_id=str(ctx.state.author_id) if ctx.state.author_id else None`. Keep `organization_id`, `mode`. Remove `brand_id`.

### Bug 5: `nodes/competitor_analysis.py:51,65` (CompetitorAnalysisNode)
**Problem:** Node calls `service.analyze_page()` and `service.calculate_winning_formula()` — neither exists as public methods. Service has `analyze_urls()` (public), `_analyze_page()` (private), `_calculate_winning_formula()` (private).
**Service sig:** `analyze_urls(self, keyword_id, urls) -> {"results": [...], "winning_formula": {...}, ...}`
**Fix:** Refactor node to call `analyze_urls()` instead:
```python
result = service.analyze_urls(
    keyword_id=str(ctx.state.selected_keyword_id) if ctx.state.selected_keyword_id else "",
    urls=ctx.state.competitor_urls,
)
ctx.state.competitor_results = result.get("results", [])
ctx.state.winning_formula = result.get("winning_formula")
```
Remove the per-URL loop and separate `calculate_winning_formula` call.

### Update existing unit tests
Update `test_seo_pipeline_graph.py` mock assertions for all 5 fixed nodes — verify corrected parameter names/method calls. The tests should still mock at the service class level but assert correct call signatures.

---

## Step 1: Create `tests/test_seo_pipeline_integration.py`

Single test file, ~29 tests across 9 classes. **Mock only true externals** (Supabase, HTTP, Anthropic API). All internal business logic runs for real.

### Fixtures (top of file)
- `FIXED_UUIDS` — 8 deterministic UUIDs for project, brand, org, keyword, author, article, persona, cms_article
- `COMPETITOR_HTML` — ~80-line realistic HTML with schema, FAQ, headings, links, images, TOC, author byline
- `PASSING_ARTICLE_MD` — ~600-word well-structured markdown article (proper headings, keyword placement, internal links, images, schema)
- `FAILING_ARTICLE_MD` — ~200-word poorly structured article (no headings, no links, em dashes)
- `BRAND_CONTEXT` — dict mimicking BrandProfileService output
- `mock_supabase` fixture — MagicMock with chainable query builder
- `make_full_state()` — factory for fully-populated SEOPipelineState

### Phase 1: `TestPhase1StateRoundtrip` (3 tests)
No mocks needed — pure in-memory logic.
- Full state round-trip through `to_dict()`→`from_dict()` with all 25+ fields
- Round-trip through `json.dumps()`→`json.loads()`→`from_dict()` (simulating DB)
- Checkpoint enum + human_input preserved across round-trip

### Phase 2: `TestPhase2KeywordDiscovery` (4 tests)
Mock: httpx, asyncio.sleep, Supabase. Real: variations, filtering, dedup.
- `_generate_variations()` produces ≥150 unique queries per seed
- `_filter_keyword()` on batch of 20 edge cases
- Full `discover_keywords()` with mock autocomplete → real filtering → real dedup
- Cross-seed frequency tracking (same keyword from 2 seeds → `found_in_seeds=2`)

### Phase 3: `TestPhase3CompetitorAnalysis` (4 tests)
Mock: WebScrapingService, Supabase. Real: HTML parsing, Flesch, winning formula.
- `_parse_html_metrics()` on realistic HTML → verify 20+ metrics
- Flesch scoring on texts at known readability levels
- `_calculate_winning_formula()` from 3 competitor dicts → verify stats/opportunities
- Full `analyze_urls()` with mock scraping → real parsing → real formula

### Phase 4: `TestPhase4ContentGeneration` (4 tests)
Mock: Supabase (author lookup). Real: template loading, prompt building.
- Phase A prompt contains keyword, competitor data, brand context, no unresolved `{VARIABLE}` placeholders
- Phase B prompt contains Phase A output, author voice, keyword
- Phase C prompt contains internal links, competitor stats, Phase B output
- Author context loading with persona cascade

### Phase 5a: `TestPhase5aQAValidation` (3 tests)
No mocks for `run_checks()` — pure logic. Real: all 10 QA checks.
- Passing article → 0 errors, `passed=True`
- Failing article → 8+ errors, `passed=False`
- Warning vs error distinction

### Phase 5b: `TestPhase5bCMSPublisher` (3 tests)
No mocks needed — pure transformation logic.
- `_markdown_to_html()` strips frontmatter/schema, converts remainder
- `_build_article_payload()` correct Shopify structure + metafields
- `_generate_handle()` on varied inputs → URL-safe slugs

### Phase 6a: `TestPhase6aInterlinking` (4 tests)
Mock: Supabase. Real: Jaccard, anchor text, link insertion.
- Jaccard similarity ranking of 5 keywords
- Anchor text generation with how-to stripping
- `_insert_links_in_paragraphs()` on realistic HTML
- Full `suggest_links()` with mock articles → verify ordering

### Phase 6b: `TestPhase6bArticleTracking` (3 tests)
Mock: Supabase. Real: status transition validation.
- Full lifecycle: draft→outline_complete→...→published→archived
- Invalid transitions rejected with ValueError
- Force override bypasses validation

### Phase 7: `TestEndToEndPipeline` (1 comprehensive test)
Mock: all services at class level (patch). Real: Graph.run(), all nodes, state mutations.
- Run graph → pauses at KEYWORD_SELECTION
- Resume → pauses at OUTLINE_REVIEW
- Resume → pauses at ARTICLE_REVIEW (skips Phase B/C pause since they're automated)
- Resume → pauses at QA_APPROVAL
- Resume → completes with published_url
- Verify all steps_completed, final state fields

**E2E mocking strategy:** Patch each service class at its import path (same pattern as existing `test_seo_pipeline_graph.py`). This is the simplest approach since nodes instantiate services with `Service()` inside `run()`.

---

## Critical Files

### Modify (bug fixes):
- `viraltracker/services/seo_pipeline/nodes/keyword_discovery.py` — Bug 1
- `viraltracker/services/seo_pipeline/nodes/competitor_analysis.py` — Bug 5
- `viraltracker/services/seo_pipeline/nodes/content_generation.py` — Bugs 2, 3, 4
- `tests/test_seo_pipeline_graph.py` — Update mock assertions

### Create:
- `tests/test_seo_pipeline_integration.py` — 29 integration tests

---

## Verification

1. Fix all 5 bugs → `py_compile` on all modified node files
2. Run existing tests: `pytest tests/test_seo_pipeline*.py` → 431 still pass (may need mock assertion updates)
3. Write integration tests phase by phase, run after each class
4. Final: `pytest tests/test_seo_pipeline_integration.py -v` → all 29 pass
5. Full suite: all SEO tests → ~460 tests pass
