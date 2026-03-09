# Fix 10 Checkpoint: Impression-Based Template Scoring — COMPLETE

**Date**: 2026-03-08
**Branch**: `feat/ad-creator-v2-phase0`
**Status**: All 3 phases complete, committed (not pushed)
**Plan**: `docs/plans/ad-creator-fixes/PLAN_FIX10_IMPRESSION_SCORING.md`
**Parent Plan**: `docs/plans/ad-creator-fixes/PLAN.md` (Fixes 1-10 now complete; 11-13 remaining)

---

## Summary

Implemented impression-based prioritization across the full template scraping and scoring pipeline. Meta Ad Library sorts results by total impressions — we now capture this signal and use it to prioritize high-performing competitor ads for template creation.

---

## Phase 1: Capture Position + Collation Dedup (COMPLETE — earlier commits)

### What Was Built
- **DB Migration** (`migrations/2026-03-07_impression_position_tracking.sql`): Added 7 columns to `facebook_ads`: `scrape_position`, `best_scrape_position`, `latest_scrape_position`, `scrape_total`, `impression_lower`, `impression_upper`, `impression_text`
- **Impression Parser** (`ad_scraping_service.py`): `parse_impression_data()` handles dict, int, float, JSON string, and None formats
- **Position Pipeline** (`scheduler_worker.py`, `ad_scraping_service.py`): Captures Apify `position` + `total`, computes `deduped_position` counting only lead ads, tracks `best_scrape_position = min(existing, new)` and `latest_scrape_position`
- **Collation Dedup** (`scheduler_worker.py`): Deduplicates creative groups at template_queue level — lead ads (collation_count > 0) and singletons queued, variants skipped. All ads still saved to `facebook_ads` for intelligence.
- **Backfill Script** (`scripts/backfill_impression_data.py`): Parsed existing impressions (121 parseable, 879 unparseable US commercial ads) and cleaned queue duplicates.
- **FacebookAd Model** (`services/models.py`): Added `collation_id`, `collation_count`, `scrape_position`, `scrape_total` fields
- **Facebook Service** (`services/facebook_service.py`): Both `search_ads()` and `scrape_page_ads()` now parse position/total/collation with `pd.notna()` checks
- **Tests** (`tests/test_impression_parsing.py`): 25 unit tests covering all parser formats

### Live Validation
- Mars Men scrape (76 ads): position data populated, deduped positions sequential (1-39), 14 variants deduped, scrape_total=76 consistent

---

## Phase 2: Scoring Integration + UI (COMPLETE — commit `4d2e5ec`)

### What Was Built

#### 3 New Pluggable Scorers (`template_scoring_service.py`)

| Scorer | Signal | Score Range | Key Formula |
|--------|--------|-------------|-------------|
| `ImpressionRankScorer` | `best_scrape_position` | [0.2, 1.0] | Position 1 → 1.0, position 50+ → 0.2. Small pages (total ≤ 10) compressed to [0.4, 0.6] (Risk 10). |
| `ImpressionVelocityScorer` | `latest_scrape_position` + `start_date` | [0.0, 1.0] | `pos_percentile × (0.4 + 0.6 × 2^(-days/30))`. 7-day-old #2 = 0.90, 180-day-old #1 = 0.41. |
| `CreativeVariantScorer` | `collation_count` | [0.3, 1.0] | 1 variant → 0.3, 2-3 → 0.6, 4-7 → 0.8, 8+ → 1.0. Independent of Meta sort order. |

#### Weight Presets

```python
SMART_SELECT_WEIGHTS = {
    ...,  # existing 8 scorers unchanged
    "impression_rank": 0.4,       # Total impression position
    "impression_velocity": 0.6,   # Highest weight — hot-right-now signal
    "creative_variants": 0.3,     # Bonus for heavily-tested creatives
}

ROLL_THE_DICE_WEIGHTS = {
    ...,  # existing 8 scorers unchanged
    "impression_rank": 0.0,       # Random mode ignores these
    "impression_velocity": 0.0,
    "creative_variants": 0.0,
}
```

#### Data Access
- `fetch_template_candidates()` now joins `facebook_ads` via `source_facebook_ad_id` FK to get `best_scrape_position`, `latest_scrape_position`, `scrape_total`, `start_date`, `collation_count`
- Fields flattened onto template row dicts before passing to scorers

#### Sort Options (`template_queue_service.py`, Ad Creator V2)
- **Highest Rank**: `best_scrape_position` ASC (position 1 = most total impressions)
- **Hottest**: Velocity formula computed in Python, sorted descending (highest velocity first)
- `get_templates()` always joins facebook_ads and flattens position data for badge display

#### UI Updates
- **Ad Creator V2** (`21b_🎨_Ad_Creator_V2.py`): Sort dropdown now has 6 options: Most Used, Least Used, Highest Rank, Hottest, Newest, Oldest. Scored selection view shows 3 new metrics (Rank, Velocity, Variants) in a second row.
- **Template Queue** (`28_📋_Template_Queue.py`): Approved templates show position badges (🟢 #1-10, 🟡 #11-25, plain #26+) and variant counts.

#### Tests
- `tests/test_impression_scorers.py`: 16 unit tests covering all 3 scorers — missing data (neutral), edge cases, hot-beats-steady validation, small page compression, invalid dates.

---

## Phase 3: Position History & Trend Tracking (COMPLETE — commit `1ad19f5`)

### What Was Built

#### Position History Table (`migrations/2026-03-08_position_history_table.sql`)

```sql
facebook_ad_position_history
├── facebook_ad_id  UUID FK → facebook_ads(id) CASCADE
├── scrape_run_id   UUID FK → scheduled_job_runs(id)
├── raw_position    INT NOT NULL
├── deduped_position INT
├── scrape_total    INT
├── is_active       BOOLEAN
├── scraped_at      TIMESTAMPTZ
└── UNIQUE(facebook_ad_id, scrape_run_id)
```

Index: `(facebook_ad_id, scraped_at DESC)` — optimized for trend queries.

#### History Recording
- `save_facebook_ad_with_tracking()` now accepts optional `scrape_run_id` parameter
- After successful upsert, inserts a position history record (non-fatal — wrapped in try/except)
- `scheduler_worker.py` passes `run_id` through to the service

#### Trend Computation
- `TemplateQueueService._compute_position_trends()`: Batch queries last 3 position history entries per ad
- Compares newest vs oldest deduped_position: diff ≥ 2 → "rising", diff ≤ -2 → "falling", else "stable"
- Results surfaced as `position_trend` field on template rows

#### Trend Arrows in UI
- Template Queue library badges show ↑ (rising) / ↓ (falling) arrows next to position number
- Example: `🟢 #3 ↑` means position 3 and improving

#### Compaction Function
```sql
compact_position_history()  -- PL/pgSQL function
```
- Entries > 30 days old: keep only the best position per ISO week
- Cap at 100 entries per ad (keep most recent)
- Safe to run repeatedly via scheduled maintenance

---

## Files Changed

### Phase 1 (earlier commits)
| File | Change |
|------|--------|
| `migrations/2026-03-07_impression_position_tracking.sql` | NEW — 7 columns on facebook_ads |
| `viraltracker/services/ad_scraping_service.py` | `parse_impression_data()`, position tracking in `save_facebook_ad_with_tracking()` |
| `viraltracker/services/models.py` | 4 new fields on `FacebookAd` model |
| `viraltracker/services/facebook_service.py` | Impression parsing, position/collation handling |
| `viraltracker/worker/scheduler_worker.py` | Deduped position computation, collation dedup, position passthrough |
| `viraltracker/scrapers/facebook_ads.py` | Capture `position` and `total` from Apify |
| `scripts/backfill_impression_data.py` | NEW — one-time backfill + queue dedup |
| `tests/test_impression_parsing.py` | NEW — 25 tests |

### Phase 2
| File | Change |
|------|--------|
| `viraltracker/services/template_scoring_service.py` | 3 new scorers, weight presets, PHASE_10_SCORERS, facebook_ads join in fetch |
| `viraltracker/services/template_queue_service.py` | Always-join facebook_ads, flatten position data, Highest Rank + Hottest sorts |
| `viraltracker/ui/pages/21b_🎨_Ad_Creator_V2.py` | 6 sort options, 3 new score metrics |
| `viraltracker/ui/pages/28_📋_Template_Queue.py` | Position + variant badges |
| `tests/test_impression_scorers.py` | NEW — 16 tests |

### Phase 3
| File | Change |
|------|--------|
| `migrations/2026-03-08_position_history_table.sql` | NEW — history table + compaction function |
| `viraltracker/services/ad_scraping_service.py` | `scrape_run_id` param, history recording |
| `viraltracker/worker/scheduler_worker.py` | Passes `run_id` to save function |
| `viraltracker/services/template_queue_service.py` | `_compute_position_trends()`, trend field on templates |
| `viraltracker/ui/pages/28_📋_Template_Queue.py` | Trend arrows in badges |

### Bug Fix (bundled)
| File | Change |
|------|--------|
| `viraltracker/pipelines/ad_creation_v2/services/content_service.py` | Fixed nested `f"""` inside `f"""` — changed inner to `f'''` for Python 3.11 compat |

---

## QA Results

- **Syntax**: All 8 Python files compile cleanly (`py_compile`)
- **Tests**: 41/41 pass (25 parser + 16 scorer)
- **Unused imports**: Fixed (`Tuple` removed from ad_scraping_service.py)
- **Debug code**: None found
- **Error handling**: All position history operations are non-fatal
- **Edge cases**: Division by zero protected everywhere, None handling returns neutral values
- **Docstrings**: Updated for new `scrape_run_id` parameter

---

## Deployment Steps

1. Run migration: `migrations/2026-03-08_position_history_table.sql`
2. Push branch and deploy
3. Position history starts populating on next template scrape run
4. Trends appear after 2+ scrapes of the same page
5. (Optional) Schedule `SELECT compact_position_history()` as weekly maintenance

---

## Remaining Work (Parent Plan: `docs/plans/ad-creator-fixes/PLAN.md`)

| # | Task | Status |
|---|------|--------|
| 1-10 | All fixes | **COMPLETE** |
| 11 | Fix SEO tool — GSC integration | Not Started |
| 12 | V1 — Zip download export list | Not Started |
| 13 | V2 — Google Drive export (OAuth, folder mapping) | Not Started |

### Operational Tasks (Non-Development)
- Create 3 avatar/offer variants for Martin Clinic pages
- Create 50 ads for each page
- Create ads for Savage
- Bill Martin Clinic Statics
- Bill Wonder Paws
- Figure out WonderPaws pricing
- Create static ads for Wonder Paws
- Create TikTok app for WonderPaws
- Breakthrough Studio links on YouTube
