# Client Onboarding Pipeline - Checkpoint 12

**Date**: 2026-01-07
**Status**: Plan Approved, Ready to Implement
**Feature**: Auto-Analyze Brand Ads & Amazon for Onboarding

---

## Summary

Plan approved for enhancing Client Onboarding to automatically analyze:
1. **Facebook Ads** - Scrape → Group by URL → Analyze creatives → Pre-fill offer variants
2. **Amazon Listings** - Scrape listing + reviews → Extract messaging → Pre-fill product data

---

## Completed in Previous Sessions

1. ✅ Product Offer Variants feature (Checkpoint 03)
2. ✅ Landing Page Analyzer - `analyze_landing_page()` method
3. ✅ Disallowed Claims - Brand + Offer Variant level compliance
4. ✅ Migration `2026-01-08_disallowed_claims.sql` - Run successfully

---

## Plan File Location

Full implementation plan: `/Users/ryemckenzie/.claude/plans/zippy-dreaming-duckling.md`

---

## Implementation Tasks (Not Started)

| # | Task | File | Status |
|---|------|------|--------|
| 1 | Create `AdAnalysisService` with `group_ads_by_url()` | `ad_analysis_service.py` (NEW) | Pending |
| 2 | Add `analyze_ad_group()` - image/video/copy analysis | `ad_analysis_service.py` | Pending |
| 3 | Add `synthesize_messaging()` - merge analyses | `ad_analysis_service.py` | Pending |
| 4 | Add `analyze_listing_for_onboarding()` | `amazon_review_service.py` | Pending |
| 5 | Update Facebook tab UI - scrape & show groups | `06_🚀_Client_Onboarding.py` | Pending |
| 6 | Add variant creation flow from analysis | `06_🚀_Client_Onboarding.py` | Pending |
| 7 | Update Products tab - Amazon analysis button | `06_🚀_Client_Onboarding.py` | Pending |
| 8 | Update session schema + import logic | `client_onboarding_service.py` | Pending |

---

## Key Existing Infrastructure

| Component | Location | Purpose |
|-----------|----------|---------|
| `FacebookAdsScraper` | `scrapers/facebook_ads.py` | Scrapes Ad Library via Apify |
| `extract_url_from_ad()` | `product_url_service.py:341` | Gets landing URL from snapshot |
| `extract_asset_urls()` | `ad_scraping_service.py:42` | Gets image/video URLs from snapshot |
| `analyze_image_sync()` | `brand_research_service.py` | Gemini image analysis |
| `analyze_video()` | `brand_research_service.py` | Gemini video analysis |
| `analyze_copy_sync()` | `brand_research_service.py` | Claude copy analysis |
| `AmazonReviewService` | `amazon_review_service.py` | Amazon scraping |

---

## User Requirements

- **Trigger**: User-controlled (scrape → review URL groups → decide per group)
- **Analysis Depth**: All ads per URL group (thorough)
- **Amazon**: Full analysis including reviews
- **URL Groups**: User chooses per group - Create Variant / Merge with Existing / Skip

---

## Next Steps

1. Read the plan file at `/Users/ryemckenzie/.claude/plans/zippy-dreaming-duckling.md`
2. Create `viraltracker/services/ad_analysis_service.py`
3. Follow CLAUDE.md guidelines (thin services, syntax verification)
4. Create checkpoints every ~40K tokens
