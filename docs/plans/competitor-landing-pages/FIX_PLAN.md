# Competitor Landing Pages Fix Plan

**Date:** 2025-12-17
**Issue:** Landing pages from competitor ads don't appear in the Landing Pages tab for scraping/analysis

## Problem Summary

The competitor landing page feature is partially implemented but incomplete:
- URLs are extracted from competitor ads (`competitor_ads.link_url`)
- They're displayed in the Ads tab under "Landing Pages by Product"
- **BUT** they're never auto-saved to `competitor_landing_pages` table
- The Landing Pages tab only shows manually-added URLs

## Root Cause

Missing methods in `competitor_service.py`:
1. No `scrape_landing_pages_for_competitor()` - batch discovery + scrape
2. No `analyze_landing_pages_for_competitor()` - batch analysis
3. No `get_landing_page_stats()` - progress tracking

The brand side has all these methods in `brand_research_service.py`.

## Comparison: Brand vs Competitor

| Feature | Brand | Competitor | Gap |
|---------|-------|------------|-----|
| Auto-discover URLs from ads | ✅ | ❌ | **Missing** |
| Batch scrape pages | ✅ | ❌ | **Missing** |
| Batch analyze pages | ✅ | ❌ | **Missing** |
| Progress stats | ✅ | ❌ | **Missing** |
| Manual URL entry | ✅ | ✅ | Works |
| Single page scrape/analyze | ✅ | ✅ | Works |

## Fix Plan

### 1. Add `get_landing_page_stats()` to competitor_service.py

Returns counts for:
- `available`: Total unique URLs from competitor ads
- `to_scrape`: URLs not yet in `competitor_landing_pages`
- `successfully_scraped`: URLs with `scraped_at` set
- `analyzed`: URLs with `analyzed_at` set
- `to_analyze`: Scraped but not analyzed

### 2. Add `scrape_landing_pages_for_competitor()` to competitor_service.py

Logic:
1. Get all unique `link_url` values from `competitor_ads` for this competitor
2. Filter out URLs already in `competitor_landing_pages`
3. For each new URL, create record and scrape using `WebScrapingService`
4. Link to `competitor_product_id` if URL matches product patterns
5. Return stats: `{urls_found, pages_scraped, pages_failed}`

### 3. Add `analyze_landing_pages_for_competitor()` to competitor_service.py

Logic:
1. Get pages where `scraped_at IS NOT NULL` and `analyzed_at IS NULL`
2. For each page, call existing `analyze_landing_page()` method
3. Return list of results

### 4. Update UI (12_🔍_Competitor_Research.py)

In the Landing Pages tab:
- Show stats (X URLs available, Y scraped, Z analyzed)
- Add "Scrape Landing Pages" button (batch)
- Add "Analyze Landing Pages" button (batch)
- Show list of all landing pages with status

## Files to Modify

1. `viraltracker/services/competitor_service.py`
   - Add `get_landing_page_stats()`
   - Add `scrape_landing_pages_for_competitor()`
   - Add `analyze_landing_pages_for_competitor()`

2. `viraltracker/ui/pages/12_🔍_Competitor_Research.py`
   - Update landing pages tab with stats and batch buttons

## Reference Implementation

Brand side implementation in `brand_research_service.py`:
- `get_landing_page_stats()` - lines 2875-2942
- `scrape_landing_pages_for_brand()` - lines 2444-2630
- `analyze_landing_pages_for_brand()` - lines 2722-2862
