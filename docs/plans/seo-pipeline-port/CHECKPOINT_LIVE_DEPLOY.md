# SEO Pipeline Port — Live Deploy & Testing Checkpoint

**Date**: 2026-03-03
**Branch**: `worktree-seo-pipeline-port`
**PR**: https://github.com/RyeMcKenzie81/ryan-viral-pattern-detector/pull/6
**Status**: ALL 9 SERVICES LIVE-TESTED, 3 ADDITIONAL BUGS FIXED

---

## What Was Done

### 1. Database Migration
- Executed `migrations/2026-03-02_seo_pipeline_tables.sql` against Supabase
- 9 tables created: `seo_projects`, `seo_authors`, `seo_clusters`, `seo_keywords`, `seo_articles`, `seo_competitor_analyses`, `seo_article_rankings`, `seo_internal_links`, `brand_integrations`
- All with RLS policies, updated_at triggers, indexes, and circular FK handling

### 2. Environment Verification
- Confirmed all 4 required env vars in `.env`: `SUPABASE_URL`, `SUPABASE_SERVICE_KEY`, `ANTHROPIC_API_KEY`, `FIRECRAWL_API_KEY`
- Symlinked `.env` from main project to worktree for local testing

### 3. Mock Tests
- All 120 tests passing (44 graph + 47 models/state + 29 integration)

### 4. Live Smoke Tests (All 9 Services)

| Service | Test | Result |
|---------|------|--------|
| **SEOProjectService** | CRUD: create/read/list projects + create/list authors | PASSED |
| **KeywordDiscoveryService** | Discovered 50 keywords via Google Autocomplete for "raccoon repellent" | PASSED |
| **ContentGenerationService** | All 3 phases via Anthropic API (Haiku): Phase A (4K tokens), B (5K), C (8K) | PASSED |
| **CompetitorAnalysisService** | Scraped 2 real pages via Firecrawl, extracted metrics, computed winning formula | PASSED |
| **QAValidationService** | Ran 10 checks on test article, saved qa_report to DB | PASSED |
| **ArticleTrackingService** | Full lifecycle walk (6 transitions), invalid blocked, force override | PASSED |
| **InterlinkingService** | Generated link suggestions via Jaccard similarity, saved to DB | PASSED |
| **SEOAnalyticsService** | Recorded rankings, retrieved history + dashboard | PASSED |
| **CMSPublisherService** | Published draft to Shopify, verified in admin, deleted | PASSED |

### 5. Bugs Found and Fixed

| Bug | File | Problem | Fix | Commit |
|-----|------|---------|-----|--------|
| UsageTracker lazy-load | `content_generation_service.py` | `UsageTracker()` called with no args, but `__init__` requires `supabase_client` | Changed to `UsageTracker(self.supabase)` | `862d71b` |
| Interlinking column name | `interlinking_service.py` | Wrote `placement_position` but migration column is `placement` | Renamed to `placement` | `e2c3cde` |
| Shopify token expiry | `cms_publisher_service.py` | No auto-refresh when token expires (401) | Added auto-refresh via client credentials grant + DB persistence | `a20ae9b` |

### 6. Shopify Auto-Refresh Feature
- On 401 response, `ShopifyPublisher._refresh_token()` calls Shopify OAuth endpoint with `client_id`/`client_secret`
- New token persisted to `brand_integrations.config` via callback
- Retry logic: one automatic retry after successful refresh
- Tested with deliberately expired token — 401 → refresh → 201 Created

---

## Commits on Branch

1. `5b40cd6` — Main SEO pipeline: 55 files, 16,022 lines (9 services, 12 nodes, orchestrator, 4 UI pages, CLI, migration, 120 tests)
2. `862d71b` — Fix: UsageTracker lazy-load missing `supabase_client`
3. `e2c3cde` — Fix: interlinking `placement_position` → `placement`
4. `a20ae9b` — Feat: Shopify auto-refresh token on 401

---

## Shopify Integration Config

The `brand_integrations` table stores per-brand Shopify credentials:

```json
{
    "store_domain": "mystore.myshopify.com",
    "access_token": "shpat_...",
    "client_id": "...",
    "client_secret": "shpss_...",
    "api_version": "2024-10",
    "blog_id": "99206135908",
    "blog_handle": "articles"
}
```

With `client_id`/`client_secret` present, token auto-refreshes on 401.
Without them, the original 401 error is raised.

---

## Test Data Cleanup

All test data was cleaned up after each smoke test:
- Projects, articles, keywords, rankings, internal links deleted from Supabase
- Shopify draft articles deleted via API
- `brand_integrations` record retained (has valid Shopify config for future use)
