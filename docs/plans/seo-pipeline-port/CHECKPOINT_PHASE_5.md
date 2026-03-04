# SEO Pipeline Port — Checkpoint: Phase 5 Complete

**Date:** 2026-03-02
**Branch:** `worktree-seo-pipeline-port`
**Status:** Phases 1-5 complete, Phases 6-7 pending

## Phase 5: Publishing + QA

### QA Validation Service
**File:** `viraltracker/services/seo_pipeline/services/qa_validation_service.py`

10 pre-publish QA checks:
1. **word_count** — Minimum 500 words (error if below)
2. **em_dashes** — Detects em/en dashes, suggests hyphens (warning)
3. **title_length** — SEO title 50-60 chars ideal
4. **meta_description** — Meta description 150-160 chars ideal
5. **heading_structure** — H1 present (exactly 1), H2s exist, no skipped levels
6. **readability** — Flesch Reading Ease 60-70 target range
7. **keyword_placement** — Keyword in title, H1, first paragraph, meta description
8. **internal_links** — At least 2 links present
9. **images** — At least 1 image with alt text
10. **schema_markup** — Schema.org JSON-LD present

Severity model: errors fail the check, warnings are advisory. Article passes if zero errors (warnings OK).

### CMS Publisher Service
**File:** `viraltracker/services/seo_pipeline/services/cms_publisher_service.py`

Architecture:
- `CMSPublisher` ABC — abstract base with `publish()`, `update()`, `get_article()`
- `ShopifyPublisher` — Shopify REST API v2024-10 via httpx
- `CMSPublisherService` — Factory that loads publisher from `brand_integrations` table

Shopify integration features (ported from `convert-and-publish.js`):
- Markdown→HTML conversion via markdown-it-py (strips frontmatter, schema sections, metadata)
- Metafields: `global.title_tag`, `global.description_tag`, `seo.schema_json`
- Author name from `seo_authors` table
- Hero image as featured image
- URL handle generation from keyword
- Draft vs published modes
- Create new vs update existing (checks `cms_article_id`)
- Responsive image styling injected

### CLI Commands
**File:** `viraltracker/cli/seo.py`

- `seo validate <article-id>` — Runs QA checks, shows PASS/FAIL with error/warning details
- `seo publish <article-id> [--draft|--published] [--brand] [--org-id]` — Publishes to configured CMS

### UI Page
**File:** `viraltracker/ui/pages/51_📤_Article_Publisher.py`

Sections:
1. Brand/project/article selectors
2. Article info metrics (status, phase, CMS ID)
3. QA Validation panel — run checks, view pass/fail details
4. CMS Publishing panel — integration status, configure Shopify, publish draft/live

### Test Coverage

| Test File | Tests | Status |
|-----------|-------|--------|
| `tests/test_seo_pipeline_models.py` | 25 | All pass |
| `tests/test_seo_pipeline_state.py` | 14 | All pass |
| `tests/test_keyword_discovery_service.py` | 30 | All pass |
| `tests/test_seo_project_service.py` | 42 | All pass |
| `tests/test_competitor_analysis_service.py` | 43 | All pass |
| `tests/test_content_generation_service.py` | 50 | All pass |
| `tests/test_qa_validation_service.py` | 52 | All pass |
| `tests/test_cms_publisher_service.py` | 39 | All pass |
| **Total** | **295** | **All pass** |

## Files Created/Modified

### New Files (Phase 5)
```
viraltracker/services/seo_pipeline/services/qa_validation_service.py
viraltracker/services/seo_pipeline/services/cms_publisher_service.py
viraltracker/ui/pages/51_📤_Article_Publisher.py
tests/test_qa_validation_service.py
tests/test_cms_publisher_service.py
docs/plans/seo-pipeline-port/CHECKPOINT_PHASE_5.md
```

### Modified Files (Phase 5)
```
viraltracker/cli/seo.py — Implemented validate and publish commands (were stubs)
```

## Remaining Work

### Phase 6: Tracking + Interlinking + Analytics
- `article_tracking_service.py` — Article CRUD, status transitions
- `interlinking_service.py` — 3 tools: suggest links, auto-link, bidirectional
- `seo_analytics_service.py` — Rankings/analytics
- CLI: `seo status`, `seo suggest-links`, `seo auto-link`, `seo add-related`
- UI: `48_🔍_SEO_Dashboard.py`

### Phase 7: Pipeline Graph
- Graph nodes and orchestrator
- Human checkpoint pattern
