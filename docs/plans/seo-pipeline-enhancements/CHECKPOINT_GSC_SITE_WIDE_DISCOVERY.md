# Checkpoint: GSC Site-Wide Page Discovery & Analytics

**Date:** 2026-03-04
**Branch:** `feat/ad-creator-v2-phase0`
**Status:** Implementation complete, pending review

## Problem

SEO dashboard showed 44 impressions while Google Search Console reported 664 for the same 28-day period. Root cause: `GSCService.sync_to_db()` silently discarded all GSC data for URLs that didn't match an existing `seo_articles` record. Homepage, product pages, collection pages, etc. were all dropped.

## Solution

Store analytics for ALL GSC-reported URLs by auto-creating `seo_articles` records with `status="discovered"` for unmatched URLs, then add a "Site-wide" vs "Tracked articles" toggle to the dashboard.

## Changes Made (7 files)

### 1. `viraltracker/services/seo_pipeline/models.py`
- Added `DISCOVERED = "discovered"` to `ArticleStatus` enum
- No DB migration needed — `status` is TEXT with no CHECK constraint

### 2. `viraltracker/services/seo_pipeline/services/gsc_service.py`
- **Removed** `fetch_site_wide_performance()` — no longer needed since all data is now stored in DB
- **Added** `_get_or_create_discovered_project(brand_id, organization_id)` — finds or creates a "Discovered Pages (GSC)" project per brand
- **Added** `_create_discovered_articles(brand_id, organization_id, all_urls)` — creates `seo_articles` with `status="discovered"` for URLs not yet tracked. Derives keyword from last URL segment (hyphens to spaces). Sets `phase="c"` (already published).
- **Modified** `sync_to_db()` — calls `_create_discovered_articles()` before `_match_urls_to_articles()` so analytics get stored for ALL URLs

### 3. `viraltracker/services/seo_pipeline/services/article_tracking_service.py`
- Added `DISCOVERED` transition rules: can promote to `DRAFT` or `ARCHIVED`
- Added `exclude_discovered: bool = True` parameter to `list_articles()` — when True and no explicit status filter, adds `.neq("status", "discovered")`. This automatically protects the dashboard articles table since it calls `list_articles()`.

### 4. `viraltracker/services/seo_pipeline/services/seo_analytics_service.py`
- Added `.neq("status", "discovered")` to `get_project_dashboard()` article query
- Added `.neq("status", "discovered")` to `get_brand_dashboard()` article query
- KPI counts (Total Articles, Published) now exclude discovered pages

### 5. `viraltracker/services/seo_pipeline/services/content_generation_service.py`
- Added `.neq("status", "discovered")` to `list_articles()` query
- Article Writer never shows discovered pages

### 6. `viraltracker/services/seo_pipeline/services/interlinking_service.py`
- Added `.neq("status", "discovered")` to `_get_project_articles()` query
- Link suggestions exclude discovered pages (no content_html to modify)

### 7. `viraltracker/ui/pages/48_SEO_Dashboard.py`
- Added `_load_discovered_articles()` cached function
- Computed `all_article_ids = brand_article_ids + discovered_article_ids`
- **Site-wide scope** uses `all_article_ids`; **Tracked articles** uses `brand_article_ids` (or filtered subset)
- Per-article breakdown shows URL paths as labels for discovered pages in site-wide view

## Dedup Safety

On repeated syncs, discovered articles already exist with `published_url` set, so `_match_urls_to_articles()` finds them via normalized path matching. The `_create_discovered_articles()` method checks existing paths before creating, preventing duplicates.

## Verification Checklist

- [x] `python3 -m py_compile` all 7 modified files — all pass
- [ ] Sync test: Click "Sync Now" — verify discovered project created, analytics stored for all pages
- [ ] No duplicates: Run sync again — no new discovered articles for same URLs
- [ ] KPI test: Dashboard "Total Articles" and "Published" counts unchanged
- [ ] Site-wide toggle: Impressions jump from ~44 to ~664
- [ ] Per-page breakdown: Site-wide view shows page URLs; tracked view shows keywords
- [ ] Article Writer: Discovered pages NOT in article selector
- [ ] Interlinking: Discovered pages NOT suggested as link targets
