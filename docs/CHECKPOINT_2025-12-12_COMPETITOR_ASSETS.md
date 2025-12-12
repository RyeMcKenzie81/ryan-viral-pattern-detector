# Checkpoint: Competitor Asset Download Fix

**Date:** 2025-12-12
**Context:** Fixing competitor ad asset download issues

## Current State

### Problem Being Fixed
Competitor asset downloads were failing with:
1. "All connection attempts failed" - FB CDN connection issues
2. "409 Duplicate" - Files exist in Supabase Storage but DB records deleted
3. "0 videos/images downloaded" - Success not being counted properly

### Changes Made (Uncommitted)
File: `viraltracker/services/ad_scraping_service.py`
- Added `scrape_and_store_competitor_assets()` method (mirrors brand version)
- Added storage upsert: `{"upsert": "true"}` to overwrite existing files
- Added graceful duplicate handling for DB records
- Better logging for upload success

File: `viraltracker/services/brand_research_service.py`
- Added `force_redownload` parameter to `download_assets_for_competitor()`
- Improved asset existence check (only counts records with valid storage_path)
- Refactored to use `scrape_and_store_competitor_assets()`

File: `viraltracker/ui/pages/23_🔍_Competitor_Research.py`
- Added "Force re-download" checkbox

### Need to Commit
```bash
git add -A && git commit -m "fix: Handle duplicate storage files and improve competitor asset download

- Use upsert mode for Supabase storage uploads
- Gracefully handle duplicate DB records
- Add force_redownload option
- Better logging for debugging

🤖 Generated with [Claude Code](https://claude.com/claude-code)

Co-Authored-By: Claude Opus 4.5 <noreply@anthropic.com>" && git push
```

## Other Work Done This Session

### 1. Copy Analysis Fix
- Fixed `analyze_copy_for_competitor()` - was calling Claude with wrong params
- Now calls Claude directly instead of reusing brand method

### 2. Persona Synthesis Fix
- Fixed `competitor_amazon_review_analysis` query - table has specific columns, not `analysis_data`
- Added `competitor_ad_analysis` data to synthesis input
- Added `confidence_score` to synthesis prompt

### 3. Persona Preview Flow
- Synthesized personas now go to preview state (not auto-saved)
- Added Save/Discard buttons
- Shows confidence score

### 4. Persona Display
- Updated competitor persona display to match Brand Research format
- Tabbed layout: Pain & Desires, Identity, Social, Worldview, Barriers, Purchase

### 5. Migrations Created
- `2025-12-12_competitor_analysis_types.sql` - Add analysis types
- `2025-12-12_competitor_landing_pages_analysis.sql` - Add analysis_data column

## Pending: Ad Analysis Comparison Plan

Plan created at: `docs/plans/AD_ANALYSIS_COMPARISON_PLAN.md`

New fields to extract from ads:
- Advertising angle (testimonial, demo, problem-agitation, etc.)
- Messaging angles (benefit dimensionalization)
- Awareness level (Schwartz spectrum)
- Benefits with framing
- Features
- Objections addressed
- Hooks (from videos)

User wants:
1. Product-to-product comparison (not just brand level)
2. Historical tracking
3. Plotly/Altair for visualizations (can embed in Streamlit)

## To Resume

1. Commit the asset download fix
2. Test competitor asset download with force_redownload
3. If still failing, check if brand download works for same type of FB CDN URLs
4. Continue with Ad Analysis Comparison Plan implementation
