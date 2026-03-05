# SEO Pipeline Enhancements — Implementation Checkpoint

**Date:** 2026-03-04
**Branch:** `feat/ad-creator-v2-phase0` (merged from `worktree-seo-pipeline-enhancements`)
**Status:** All 3 phases implemented, post-plan review PASSED, live testing in progress

## Commits (in order)

1. `300192c` — Phase 1: brand-level SEO dashboard + pre-req CMS publisher fix
2. `783f4fd` — Phase 2: article image generation pipeline
3. `7770104` — Phase 3: external analytics integrations (GSC, GA4, Shopify)
4. `0704b54` — Post-plan review fixes (URL encoding, avg_position, XSS, test gaps)
5. `4786f7f` — Merge into feat/ad-creator-v2-phase0
6. `2735102` — Fix: show analytics section on dashboard even with zero projects
7. `b7e0eaa` — Fix: use APP_BASE_URL env var for OAuth redirect URI
8. `0a72557` — Fix: remove nonexistent `status` column from GSC integration upsert

## Test Results

- **231 tests passing** across 5 test files
- Post-plan review: PASS (Graph Invariants + Test/Evals Gatekeeper)

## Files Created/Modified

### New Files (10 service + 2 migrations + 3 test + 1 UI)
- `viraltracker/services/seo_pipeline/utils.py` — `normalize_url_path()` utility
- `viraltracker/services/seo_pipeline/services/base_analytics_service.py` — shared base class
- `viraltracker/services/seo_pipeline/services/gsc_service.py` — Google Search Console OAuth + sync
- `viraltracker/services/seo_pipeline/services/ga4_service.py` — Google Analytics 4 service account + sync
- `viraltracker/services/seo_pipeline/services/shopify_analytics_service.py` — Shopify conversion attribution
- `viraltracker/services/seo_pipeline/services/seo_image_service.py` — Image generation + upload
- `viraltracker/services/seo_pipeline/nodes/image_generation.py` — Pipeline node
- `viraltracker/ui/pages/47_━━━_SEO_━━━.py` — Sidebar divider
- `migrations/2026-03-04_seo_article_images.sql` — hero_image_url + image_metadata columns
- `migrations/2026-03-04_seo_analytics_integrations.sql` — seo_article_analytics table
- `tests/test_seo_analytics_integrations.py` — 35 Phase 3 tests
- `tests/test_seo_image_service.py` — 23 Phase 2 tests

### Modified Files
- `viraltracker/ui/pages/48_🔍_SEO_Dashboard.py` — Optional project selector, zero-state UX, OAuth callback, analytics display
- `viraltracker/ui/pages/51_📤_Article_Publisher.py` — Image preview + regeneration UI
- `viraltracker/services/seo_pipeline/services/seo_analytics_service.py` — `get_brand_dashboard()`, N+1 fix
- `viraltracker/services/seo_pipeline/services/cms_publisher_service.py` — `.eq("platform", "shopify")` fix
- `viraltracker/services/seo_pipeline/state.py` — Image fields, `from_dict()` rollback safety
- `viraltracker/services/seo_pipeline/nodes/qa_publish.py` — Route to ImageGenerationNode
- `viraltracker/services/seo_pipeline/nodes/__init__.py` — Export ImageGenerationNode
- `viraltracker/services/seo_pipeline/orchestrator.py` — Register ImageGenerationNode (13 nodes)
- `viraltracker/worker/scheduler_worker.py` — `analytics_sync` job handler
- `requirements.txt` — google-auth-oauthlib, google-analytics-data
- `docs/TECH_DEBT.md` — Credentials-in-JSONB security concern

## Environment Variables Required

| Variable | Where | Purpose |
|----------|-------|---------|
| `GOOGLE_OAUTH_CLIENT_ID` | Railway | Google OAuth app client ID (one for all brands) |
| `GOOGLE_OAUTH_CLIENT_SECRET` | Railway | Google OAuth app client secret |
| `APP_BASE_URL` | Railway | Base URL for OAuth redirect (e.g. `https://viraltracker-ui-production.up.railway.app`) |

## Google Cloud Setup (Completed)

- Project: `ViralVideoAnalyzer`
- APIs enabled: Google Search Console API, Google Analytics Data API
- OAuth consent screen: External, testing mode
- Test user: `ryan.mckenzie@gmail.com`
- OAuth client: `M5-viraltracker` (Web application)
- Redirect URI: `https://viraltracker-ui-production.up.railway.app/SEO_Dashboard`

## Supabase Setup (Completed)

- Storage bucket: `seo-article-images` (public)
- Migrations run: `2026-03-04_seo_article_images.sql`, `2026-03-04_seo_analytics_integrations.sql`

## Live Testing Status

### Phase 1: Dashboard Without Project Requirement ✅
- Zero-state shows KPIs at 0, "Create Your First SEO Project" button
- "All Projects" default view works
- Analytics section renders even with zero projects

### Phase 2: Article Image Generation — NOT YET TESTED LIVE
- Requires running an article through the full pipeline
- Need published articles with `[IMAGE: desc]` markers

### Phase 3: External Analytics — IN PROGRESS
- Google Cloud OAuth app configured ✅
- Env vars set on Railway ✅
- GSC Connect flow: OAuth redirect works ✅
- GSC token exchange: Fixed `status` column error, awaiting redeploy to verify save
- GA4: Not yet configured (needs service account + brand_integrations row)
- Shopify: Should work automatically if CMS publishing is configured

## Known Issues Fixed During Testing

1. `st.stop()` in zero-project state blocked analytics section from rendering
2. Hardcoded `localhost:8501` redirect URI — replaced with `APP_BASE_URL` env var
3. `site_url` not passed through OAuth state — added `**extra` to `encode_oauth_state()`
4. `brand_integrations` table has no `status` column — removed from GSC upsert

## Remaining Items

- Verify GSC save_integration works after redeploy
- Test "Sync Now" button for GSC data pull
- Set up GA4 service account (Step 7 from setup guide)
- Test image generation on a real article pipeline run
- Test Shopify analytics sync (if Shopify CMS is configured for a brand)
