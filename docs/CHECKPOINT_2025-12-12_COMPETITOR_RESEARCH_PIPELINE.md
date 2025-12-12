# Checkpoint: Competitor Research Pipeline Improvements

**Date:** 2025-12-12
**Context:** Enhancing competitor research with automated pipeline and analysis features

## Completed This Session

### 1. Logfire Deployment Fix
- Removed `logfire>=0.50.0` from requirements.txt due to OpenTelemetry dependency conflicts with pydantic-ai-slim
- Deployment was taking 22+ minutes (normally 2 min) due to pip backtracking through 100+ versions
- The `observability.py` module handles missing logfire gracefully with no-op stub
- **Commit:** `bdb7035`

### 2. Re-analyze Checkboxes
- Added `force_reanalyze` parameter to `analyze_videos_for_competitor`, `analyze_images_for_competitor`, `analyze_copy_for_competitor`
- When re-analyzing, deletes existing analyses before running new ones
- Added "Re-analyze existing" checkbox next to each analysis button in UI
- Allows updating old analyses with new prompts (advertising_structure)
- **Commit:** `9af565e`

### 3. Foreign Key Constraint Fix
- Fixed error: `brand_ad_analysis violates foreign key constraint brand_ad_analysis_asset_id_fkey`
- Added `skip_save=True` parameter to `analyze_video()` and `analyze_image()` methods
- Competitor analysis methods now skip saving to brand tables (they save to competitor tables separately)
- **Commit:** `023c836`

### 4. Landing Pages by Product Section
- Added "Landing Pages by Product" section in Competitor Research Ads tab
- Shows all landing page URLs discovered from ads, grouped by product
- Each product is an expandable section with clickable URLs
- **Commit:** `9af565e`

### 5. Full Research Pipeline Button
- Added "Run Full Research Pipeline" button at top of Ads tab
- Automatically runs: Download assets → Analyze videos → Analyze images → Analyze copy
- Configurable limits in expandable settings panel
- Progress bar with step indicators
- **Commit:** `b0aa780`

### 6. Persistent Pipeline Results
- Pipeline results now persist in session state
- Shows timestamp, status banner (success/partial/failed)
- Metrics for each step with error counts
- Detailed log of what happened
- "Clear Results" button to dismiss
- **Commit:** `2368c87`

### 7. Comparison Utils List Fix
- Fixed "unhashable type: 'list'" error in product comparison
- AI sometimes returns `advertising_angle` as a list instead of string
- Updated `aggregate_awareness_levels` and `aggregate_advertising_angles` to handle both cases
- **Commit:** `e1492b4`

## Current State

### Assets in Storage
- **318 videos** in database (verified files exist in Supabase storage)
- **130 images** in database (verified files exist)
- 74 ads still needing download (Facebook CDN URLs failing from server - likely expired or blocked)

### Analyses
- Brand (Collagen 3X): 97 analyses, **0 with advertising_structure** (old prompts)
- Competitor (Wuffes Joint): 274 analyses, **270 with advertising_structure** (new prompts)

### Facebook CDN Download Issues
Deploy logs show "All connection attempts failed" for Facebook CDN URLs. This is:
- Network connectivity issue from deployment server to Facebook servers
- Possibly IP-based blocking or expired URLs
- Options: Re-scrape ads for fresh URLs, or use proxy

## Files Changed This Session

- `requirements.txt` - Removed logfire
- `viraltracker/services/brand_research_service.py` - Added skip_save, force_reanalyze parameters
- `viraltracker/services/comparison_utils.py` - Handle list types for angles/levels
- `viraltracker/ui/pages/23_🔍_Competitor_Research.py` - Pipeline UI, landing pages section, re-analyze checkboxes
- `viraltracker/core/observability.py` - Logfire setup (remains, handles missing gracefully)

## Next Steps (TODO)

1. **Setup Amazon scraper for competitors** - Use same service/tool pattern as brand side
2. **Setup landing page scraping for competitors** - Extract and analyze landing pages from ad URLs

## Related Documentation

- Previous checkpoint: `docs/CHECKPOINT_2025-12-12_AD_ANALYSIS_COMPARISON.md`
- Logfire issue: `docs/CHECKPOINT_2025-12-12_LOGFIRE.md`
- Ad comparison plan: `docs/plans/AD_ANALYSIS_COMPARISON_PLAN.md`
