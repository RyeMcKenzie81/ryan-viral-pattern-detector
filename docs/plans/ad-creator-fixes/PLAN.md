# Ad Creator Fixes & Improvements Plan

## Status: Fixes 1-8 COMPLETE | Fixes 9-13 NOT STARTED

See `CHECKPOINT_BATCH_FIXES.md` for implementation details.
See `TESTING_CHECKLIST.md` for manual and unit test checklists.

## Quick Fixes (1-4) -- ALL DONE

### 1. Scheduler time display mismatch -- DONE
- **Fix**: Added `.astimezone(PST)` + `%Z` format to 4 time display locations

### 2. Smart edit ratio bug — defaults to 1:1 -- DONE
- **Fix**: Multi-step dimension detection chain (canvas.dimensions -> aspect_ratio -> string parse -> variant_size -> fallback)

### 3. Listicle landing page number matching -- DONE
- **Fix**: Extract `listicle_item_count` from `landing_page_analyses.content_patterns` JSONB, pass to headline generation prompt

### 4. Money back guarantee hallucination -- DONE
- **Fix**: Added `guarantee` field to Product model, wired through prompt, explicit instruction to use verified guarantee or prohibit mention

## Medium Fixes (5-8) -- ALL DONE

### 5. Ad Creator 2 "View Results" shows nothing -- DONE
- **Fix**: Changed `!inner` to left join, added `source_scraped_template_id` FK column + migration + backfill

### 6. Ad Creator 2 template sorting — brand dropdown + filters -- DONE
- **Fix**: Added `source_brand` filter + `sort_by` param to service, added 2nd filter row in UI

### 7. ~~Add recurring template pulling~~ — ALREADY IMPLEMENTED
- **No work needed**

### 8. Manual ad template addition with auto-ingestion -- DONE
- **Fix**: New `add_manual_template()` service method + "Manual Upload" tab in Template Queue UI

## Brand Manager Enhancement

### 9. Brand Manager — LP Analysis, Gap Filling & Feature Parity with Onboarding
- **Problem**: Client Onboarding has many features missing from Brand Manager. If gaps aren't filled during onboarding, there's no way to do it later.
- **Missing features**:
  - Website scraping + brand voice auto-fill (`ContentGapFillerService`)
  - Amazon listing analysis + review auto-fill (`AmazonReviewService`)
  - Landing page analysis for new variants (`ProductOfferVariantService.analyze_landing_page()`)
  - Product image extraction from LP (`WebScrapingService.extract_product_images()`)
  - Auto-fill UI with Accept/Skip/Undo pattern
  - All brand input fields visible (some only in onboarding)
- **Services exist** — just need UI wiring in Brand Manager
- **Scope**: Large (M-L)

## Hard Fixes

### 10. Template ingestion/scoring — impression-based prioritization
- **Problem**: Meta now sorts Ad Library by impressions; we should leverage this to prioritize testing high-performing ads
- **Fix**: Capture position/impression data during scrapes, track changes over time, surface top performers

### 11. Fix SEO tool — GSC integration
- **Problem**: SEO pipeline GSC integration not functional
- **Scope**: API integration debugging across multiple services

## Export Tools (Last)

### 12. V1 — Zip download export list
- Add "Add to export list" button in ad history/results
- Export tool page to view list and download as named zip

### 13. V2 — Google Drive export
- Push unzipped files with original names to Google Drive folder
- Save brand folder mapping
- Google Drive API OAuth integration

## Removed from Scope
- Video builder for Wonder Paws (not included)
- Lip sync / voice tool integration (not included)

## Operational Tasks (Non-Development)
- Create 3 avatar/offer variants for Martin Clinic pages
- Create 50 ads for each page
- Create ads for Savage
- Bill Martin Clinic Statics
- Bill Wonder Paws
- Figure out WonderPaws pricing
- Create static ads for Wonder Paws
- Create TikTok app for WonderPaws
- Breakthrough Studio links on YouTube
