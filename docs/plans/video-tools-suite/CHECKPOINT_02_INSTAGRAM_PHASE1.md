# Video Tools Suite - Checkpoint 02: Instagram Content Library (Phase 1)

**Date:** 2026-02-25
**Branch:** `feat/chainlit-agent-chat` (worktree: `worktree-feat/chainlit-agent-chat`)
**Status:** Phase 1 implementation complete, post-plan review PASS

---

## What Was Done

### Summary

Implemented Phase 1 (Instagram Content Library) of the Video Tools Suite plan. This provides per-brand Instagram account monitoring, content scraping via existing Apify integration, statistical outlier detection, and selective media download for high-performing posts.

### Key Design Decisions

| Decision | Rationale |
|----------|-----------|
| Reuse existing `InstagramScraper` | Avoids duplicating Apify integration; scraper already handles normalization, upserts, metadata |
| Z-score outlier detection with edge case handling | Handles N<3 (skip detection), std=0 (all z-score=0), and trimmed statistics for robustness |
| Outlier-first media download | Only downloads media for outlier posts, saving ~90% storage costs |
| Lazy scraper initialization | `@property` pattern avoids Apify client creation until actually needed |
| Existing `posts`/`accounts` tables | Extended with outlier columns rather than creating duplicate Instagram-specific tables |
| `instagram_media` separate table | Media files are 1:many to posts (carousel support), need download status tracking |

### Files Created (4 new)

| File | Lines | Purpose |
|------|-------|---------|
| `migrations/2026-02-25_instagram_content.sql` | ~60 | `instagram_watched_accounts` table, `instagram_media` table, outlier columns on `posts` |
| `viraltracker/services/instagram_content_service.py` | ~510 | Full service: watched account CRUD, scraping, outlier detection, media download, content queries |
| `viraltracker/ui/pages/50_📸_Instagram_Content.py` | ~310 | Streamlit UI with 3 tabs: Watched Accounts, Content Library, Top Content |
| `tests/test_instagram_content_service.py` | ~480 | 37 tests covering all service methods, edge cases, error handling |

### Files Modified (3)

| File | Change |
|------|--------|
| `viraltracker/services/feature_service.py` | Added `SECTION_VIDEO_TOOLS`, `INSTAGRAM_CONTENT`, `VIDEO_STUDIO` to `FeatureKey`. Added to `enable_all_features()`. |
| `viraltracker/ui/nav.py` | Added Video Tools section with Instagram Content + Video Studio pages. Added feature keys to superuser features dict. |
| `viraltracker/core/models.py` | Added `is_outlier`, `outlier_score`, `outlier_method`, `outlier_calculated_at` fields to `Post` model (G4 schema consistency). |

---

## Service Methods

### InstagramContentService

| Method | Purpose |
|--------|---------|
| `add_watched_account(brand_id, username, org_id)` | Add IG account to watch list (creates in `accounts` + `instagram_watched_accounts`) |
| `remove_watched_account(watched_id)` | Soft delete (is_active=false) |
| `reactivate_watched_account(watched_id)` | Re-enable a deactivated account |
| `list_watched_accounts(brand_id, org_id)` | Get active watched accounts with account details |
| `scrape_account(watched_account_id, days_back, force)` | Scrape single account via Apify, enforces min_scrape_interval |
| `scrape_all_active(brand_id, org_id)` | Batch scrape all active accounts for a brand |
| `calculate_outliers(brand_id, org_id, days, method, threshold)` | Z-score/percentile outlier detection, updates posts table |
| `download_outlier_media(brand_id, org_id, limit)` | Download media only for outlier posts to Supabase storage |
| `get_top_content(brand_id, org_id, days, limit, outliers_only, media_type)` | Filtered query with engagement sorting |
| `get_content_stats(brand_id, org_id, days)` | Aggregate statistics for dashboard |
| `get_post_media(post_id)` | Get downloaded media files for a post |

### Edge Cases Handled

| Edge Case | Handling |
|-----------|----------|
| N < 3 posts | Skip outlier detection, return message |
| std = 0 (identical engagement) | All z-scores = 0, none flagged |
| CDN URL expiration | Track `cdn_url_captured_at`, re-scrape for fresh URLs |
| File too large (>500MB) | Reject download, return None |
| Min scrape interval | Enforce unless `force=True` |
| Superuser "all" mode | Skip org_id filter in queries |
| Empty username / @ prefix | Strip and validate |

---

## Post-Plan Review Results

### Graph Invariants Checker: PASS

| Check | Status | Notes |
|-------|--------|-------|
| G1: Validation consistency | PASS | Feature keys in feature_service.py, nav.py, enable_all_features(). No API-level feature key validation needed. |
| G2: Error handling | PASS | Improved: scrape_account logs with exc_info before re-raising. No bare except:pass. |
| G3: Service boundary | PASS | All business logic in service. UI delegates to service. No raw DB calls in UI. |
| G4: Schema drift | PASS | Added outlier fields to Post model in core/models.py to match migration. |
| G5: Security | PASS | No hardcoded secrets, no SQL injection risk (Supabase fluent API), input validation on usernames. |
| G6: Import hygiene | PASS | No debug code, no unused imports, late import for optional apify_client is intentional. |
| P1-P8 | SKIP | No graph/pipeline files created. |

### Test/Evals Gatekeeper: PASS

| Check | Status | Notes |
|-------|--------|-------|
| T1: Unit tests | PASS | 37 tests across 6 test classes covering all public methods |
| T2: Syntax verification | PASS | All 6 files compile (py_compile) |
| T3: Integration tests | PASS | Service-layer only (no cross-service dependencies in Phase 1) |
| T4: No regressions | PASS | All 172 tests pass (135 Phase 3 + 37 Phase 1) |
| A1-A5 | SKIP | No agent/pipeline files created. |

---

## Test Coverage Summary

| Source File | Test File | Tests | Coverage |
|-------------|-----------|-------|----------|
| `instagram_content_service.py` | `test_instagram_content_service.py` | 37 | CRUD, scraping, outliers, download, queries, edge cases |
| **Total** | | **37** | |

### Combined (Phase 1 + Phase 3)

| Phase | Tests |
|-------|-------|
| Phase 3 (Kling) | 135 |
| Phase 1 (Instagram) | 37 |
| **Total** | **172** |

---

## What's NOT Done Yet

### Phase 1 Remaining Work
- [ ] Run migration `2026-02-25_instagram_content.sql` against Supabase
- [ ] Create `instagram-media` Supabase storage bucket
- [ ] Verify existing Apify Instagram actor still works
- [ ] Smoke test: add watched account, scrape, detect outliers, download media

### Other Phases (Not Started)
- [ ] **Phase 2**: Content Analysis (Gemini two-pass analysis, structural extraction, shot sheets)
- [ ] **Phase 4**: Video Recreation Pipeline (scoring, storyboard adaptation, audio-first workflow, clip stitching)
- [ ] **Phase 5**: Video Studio UI (51_Video_Studio page)

### Phase 3 Remaining
- [ ] Run migration `2026-02-25_kling_generations.sql` against Supabase
- [ ] Create `kling-videos` Supabase storage bucket
- [ ] Kling developer account + API keys in `.env`
- [ ] Smoke tests against live Kling API

---

## Environment Setup Required

```bash
# Migrations to run (both Phase 1 and Phase 3):
# 1. migrations/2026-02-25_kling_generations.sql
# 2. migrations/2026-02-25_instagram_content.sql

# Supabase storage buckets to create:
# 1. kling-videos (Phase 3)
# 2. instagram-media (Phase 1)

# Verify Apify actor:
# - apify/instagram-scraper
# - apify/instagram-post-scraper (for individual post media URLs)
```

---

## Commit History for This Checkpoint

Single commit containing all Phase 1 files (see git log after push).
