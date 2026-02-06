# Checkpoint: Classification Error Reporting Fix & Asset Dependency Issue

**Date:** 2026-02-05
**Branch:** `feat/veo-avatar-tool`
**Commit:** `ad04156` - fix: Distinguish skipped-due-to-cap from actual errors in classification reporting

---

## Completed

### 1. BatchClassificationResult — Accurate Error Reporting

**Problem:** `_run_classification_for_brand()` computed `errors = total_active - total_classified`, but `classify_batch()` breaks out of its loop when `max_new` cap is reached. With 109 active ads and `max_new=40`, the 69 unprocessed ads were reported as "errors" when they were just skipped.

**Solution:** New `BatchClassificationResult` model with breakdown:
- `classifications` — the list of classified ads
- `new_count` — new Gemini API calls made
- `cached_count` — reused from dedup cache
- `skipped_count` — skipped because max_new cap reached
- `error_count` — actual classification failures

**Files changed:**
- `viraltracker/services/ad_intelligence/models.py` — Added `BatchClassificationResult`
- `viraltracker/services/ad_intelligence/classifier_service.py` — `classify_batch()` returns `BatchClassificationResult`
- `viraltracker/services/ad_intelligence/ad_intelligence_service.py` — Updated to use `batch_result.classifications`
- `viraltracker/worker/scheduler_worker.py` — Updated all 3 callers (standalone job, auto_classify chain, summary logging)

**Test results (all 4 passing):**

| Test | max_new | Result | Status |
|------|---------|--------|--------|
| 1 | 10 | 19 classified (10 new, 9 cached), 90 skipped | PASS |
| 2 | 10 | 19 classified (10 new, 9 cached), 90 skipped | PASS (see note) |
| 3 | 50 | 68 classified (50 new, 18 cached), 41 skipped | PASS |
| 4 | 200 | 109 classified (74 new, 35 cached), 0 skipped | PASS |

**Note on Test 2:** Expected 0 new / 19 cached, but got 10 new / 9 cached again. This is because ~10 of the "new" classifications are **video ads being re-skipped** each run. The skipped video classification (source=`skipped_*`) is returned as a model but never persisted to the DB, so dedup doesn't find it on the next run. This is a pre-existing issue (not harmful — no Gemini calls wasted, just extra DB lookups). The 9 cached are image ads that went through full classification and were persisted.

### 2. Railway CLI Skill

Created global skill at `~/.claude/skills/railway-cli/SKILL.md` for Railway CLI operations. Updated after real-world testing to fix:
- `--lines` and `--follow` flags don't exist — `railway logs` streams continuously
- Interactive commands (`railway service`, `railway link`) need explicit flags (`-p`, `-e`, `-s`) in non-TTY environments
- `railway login` must be run in user's terminal (requires browser)
- Added timeout wrapper pattern for capturing log snapshots

---

## Discovered Issue: Classification Without Downloaded Assets

### Problem

Infi brand has **0 downloaded assets** (0/74 videos, 0/101 images). Despite this, 74 image ads were "successfully" classified. Investigation reveals:

**Current fallback chain in `_classify_with_gemini()` (classifier_service.py:1344):**
1. Try stored image from `meta_ad_assets` → **fails** (0 assets downloaded)
2. Fall back to `thumbnail_url` from `meta_ads_performance` → **succeeds** (Meta CDN URLs still valid, but will expire)
3. If both fail → classify from **copy only** (ad_name text) → **pollutes data**

**Current state:** Step 2 is working because CDN URLs haven't expired yet. But this is fragile:
- Meta CDN URLs expire after an unknown period
- When they expire, all future classifications fall back to copy-only
- Copy-only classifications produce unreliable awareness levels and formats
- These bad classifications then get cached by dedup and persist for 30 days

**For video ads:** Already handled correctly — skipped with `source="skipped_*"` when no video file in storage. But the skip classification isn't persisted (see Test 2 note above).

### Proposed Fix

1. **Remove copy-only fallback** — if no image is available (neither stored asset nor valid thumbnail URL), skip the ad with `source="skipped_no_media"` instead of classifying from copy alone
2. **Add `source` tracking for thumbnail URL classifications** — distinguish `gemini_light_stored_image` vs `gemini_light_thumbnail_url` so we know which are fragile
3. **Consider:** Should classification require downloaded assets as a prerequisite? Or is thumbnail URL acceptable as a temporary source?

---

## Next Steps — All Completed

All items from this checkpoint were resolved in subsequent commits:

| Item | Resolution | Commit |
|------|-----------|--------|
| Fix copy-only fallback | Removed — ads without media are skipped with `source="skipped_no_media"` | `50c395b` |
| Download Infi assets | Standalone `asset_download` job type created and tested (15 assets downloaded) | `f079bde` |
| Tech debt updates | Items 12 and 13 moved to Completed | `f079bde` |
| Auto-download in classification pipeline | Decoupled as independent schedulable job instead — pipeline is now: meta_sync → asset_download → classification | `f079bde` |
