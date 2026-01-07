# Checkpoint 13: Auto-Analyze Brand Ads Feature Complete

**Date:** 2026-01-08
**Status:** Complete

## Summary

Implemented the Auto-Analyze Brand Ads feature for Client Onboarding. This allows users to:
1. Scrape their existing Facebook ads and group them by landing page URL
2. Analyze ad groups to extract messaging (pain points, desires, benefits, hooks)
3. Auto-create offer variants from the analysis
4. Analyze Amazon listings to extract product info and review-based messaging

## Files Created

### New Service
- `viraltracker/services/ad_analysis_service.py` - Core ad analysis service
  - `group_ads_by_url()` - Groups ads by normalized destination URL
  - `analyze_ad_group()` - Analyzes all ads in a group (images, videos, copy)
  - `synthesize_messaging()` - Merges analyses into offer variant data
  - Includes UM/UMP/UMS (unique mechanism) field extraction

### New Migration
- `migrations/2026-01-08_pov_mechanism_fields.sql` - Adds mechanism columns to product_offer_variants:
  - `mechanism_name` - The unique mechanism name
  - `mechanism_problem` - UMP (why other solutions fail)
  - `mechanism_solution` - UMS (how mechanism solves problem)
  - `sample_hooks` - Array of extracted ad hooks
  - `source` - How variant was created (ad_analysis, amazon_analysis, etc.)
  - `source_metadata` - JSONB with ad_count, review_count, etc.

## Files Modified

### Amazon Review Service
- `viraltracker/services/amazon_review_service.py`
  - Added `analyze_listing_for_onboarding()` - Full Amazon listing analysis
  - Uses `axesso_data/amazon-product-details-scraper` for product info
  - Extracts: title, bullets, images, dimensions, weight, price, rating
  - Analyzes reviews for pain points, desires, customer language

### Client Onboarding UI
- `viraltracker/ui/pages/06_🚀_Client_Onboarding.py`
  - Enhanced Facebook tab with ad scraping and URL grouping
  - Added "Scrape & Group Ads" button
  - Shows discovered landing pages with ad counts
  - "Analyze & Create Variant" button for each URL group
  - Added "Analyze Listing" button for Amazon products
  - Auto-creates offer variants from analysis results

### Client Onboarding Service
- `viraltracker/services/client_onboarding_service.py`
  - Updated `import_to_production()` to include mechanism fields
  - Added source tracking (ad_analysis, amazon_analysis)
  - Added source_metadata for ad_count, review_count

## User Flow

### Facebook Ad Analysis
1. Enter Ad Library URL in Facebook tab
2. Click "Scrape & Group Ads" - scrapes up to 100 ads
3. View discovered landing pages grouped by URL
4. For each group:
   - Click "Analyze & Create Variant" to analyze ads and create offer variant
   - Or "Skip" to ignore
5. Variant is auto-created with extracted messaging

### Amazon Analysis
1. Add product with Amazon URL in Products tab
2. Click "Analyze Listing" button
3. Product info (title, dimensions) and messaging (from reviews) extracted
4. Amazon-based offer variant auto-created

## Data Extracted

From Facebook ads:
- Pain points
- Desires/goals
- Benefits
- Claims
- Sample hooks
- Target audience
- Mechanism name/problem/solution (if present)

From Amazon listings:
- Product title, bullets, description
- Images (up to 5)
- Dimensions and weight
- Price and rating
- Pain points (from reviews)
- Desires (from reviews)
- Customer language quotes

## Services Used

- `AdScrapingService.extract_asset_urls()` - Get image/video URLs from ad snapshots
- `BrandResearchService.analyze_image_sync()` - Gemini image analysis
- `BrandResearchService.analyze_video_from_url()` - Gemini video analysis
- `BrandResearchService.analyze_copy_sync()` - Claude copy analysis
- `ApifyService` - Amazon scraping (reviews + product details)

## Testing Notes

1. Run the new migration: `migrations/2026-01-08_pov_mechanism_fields.sql`
2. Test Facebook flow:
   - Use an Ad Library URL with active ads
   - Verify ads are grouped correctly
   - Test analyze & create variant
3. Test Amazon flow:
   - Add product with Amazon URL
   - Click Analyze Listing
   - Verify product info and variant creation

## Next Steps

Potential enhancements:
- Add progress bar for multi-ad analysis
- Allow selecting which product to add variants to (currently adds to first)
- Add bulk analysis (analyze all groups at once)
- Add cost estimation for Apify usage
