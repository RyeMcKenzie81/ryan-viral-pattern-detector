# Checkpoint: Fix 10 Planning Complete

**Date**: 2026-03-06
**Branch**: `feat/ad-creator-v2-phase0`
**Status**: Planning complete, implementation NOT started

## What Was Done

### Research Phase
1. Traced the full template scraping pipeline end-to-end:
   - `FacebookAdsScraper` (Apify actor) → `FacebookService` → `AdScrapingService` → `TemplateQueueService`
   - Worker: `execute_template_scrape_job()` in `scheduler_worker.py:2006-2273`
   - DB tables: `facebook_ads` → `scraped_ad_assets` → `template_queue` → `scraped_templates`

2. Read and documented existing scoring infrastructure:
   - `template_scoring_service.py`: 8 pluggable scorers with weighted presets (ROLL_THE_DICE, SMART_SELECT)
   - `template_recommendation_service.py`: 3 methodologies (AI_MATCH, DIVERSITY, LONGEVITY)
   - `template_queue_service.py`: approval workflow, sort options (most_used, least_used, newest, oldest)

3. Identified existing underutilized fields on `facebook_ads`:
   - `collation_id`, `collation_count` — already captured but never used for dedup
   - `impressions` (TEXT) — stored raw, silently dropped when dict format
   - `start_date`, `last_seen_at`, `times_seen` — used for longevity but not velocity

### Empirical Validation (2 Apify test scrapes)
- **Sort order**: CONFIRMED preserved. Meta's top 5 appeared in same relative order in Apify results.
- **Apify native fields**: `position` (explicit), `collation_id`, `collation_count`, `total` — all available.
- **Impression data**: NULL for all 20 US commercial ads — confirms position must be primary signal.
- **Collation groups**: 4 groups found in 20 results. Members had identical image URLs + body text = true duplicates.
- **Test scripts**: `scripts/test_apify_order.py`, `scripts/test_apify_collation.py`

### Plan Produced
- **File**: `docs/plans/ad-creator-fixes/PLAN_FIX10_IMPRESSION_SCORING.md`
- **3 phases**: Phase 1 (capture + dedup), Phase 2 (scoring + UI), Phase 3 (history, deferred)
- **3 new scorers**: ImpressionRankScorer, ImpressionVelocityScorer, CreativeVariantScorer
- **13 adversarial risks** identified with mitigations and task mappings
- **Velocity concept**: position × recency formula with 30-day half-life exponential decay

## Key Files Referenced

| File | Role |
|------|------|
| `viraltracker/scrapers/facebook_ads.py` | Apify actor integration, field normalization |
| `viraltracker/services/facebook_service.py` | Async wrapper, impression parsing (broken — silently drops dicts) |
| `viraltracker/services/ad_scraping_service.py` | Asset download, `save_facebook_ad_with_tracking()` |
| `viraltracker/services/template_queue_service.py` | Queue management, approval flow, `get_templates()` |
| `viraltracker/services/template_scoring_service.py` | 8 pluggable scorers, `fetch_template_candidates()` |
| `viraltracker/services/template_recommendation_service.py` | LONGEVITY methodology (joins facebook_ads for start_date) |
| `viraltracker/worker/scheduler_worker.py:2006-2273` | `execute_template_scrape_job()` |
| `viraltracker/ui/pages/21b_🎨_Ad_Creator_V2.py` | Template selection UI, sort/filter (lines 296-440, 342-389) |
| `viraltracker/ui/pages/28_📋_Template_Queue.py` | Template queue/approval UI |
| `migrations/2026-02-13_ad_creator_v2_phase0.sql` | V2 schema (scraped_template_ids, template_source) |
| `sql/2025-12-04_template_ai_analysis_fields.sql` | AI analysis columns on scraped_templates |
| `sql/2025-01-22_template_scrape_longevity.sql` | Longevity columns on facebook_ads |

## Not Yet Done
- No code changes made
- No migration written
- No implementation started
- Phase 3 (position history) intentionally deferred
