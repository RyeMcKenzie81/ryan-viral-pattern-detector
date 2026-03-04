# Ad Creator V2 — Phase 0 Cleanup Prompt

> Paste this into a new Claude Code context window to finish Phase 0 nice-to-haves, browser tests, and commit.

---

## Prompt

```
I'm finishing Phase 0 of the Ad Creator V2 plan. The core implementation is done and post-plan review passed. I need you to complete the remaining nice-to-haves, verify browser test results, and commit.

## Required Reading

1. `docs/plans/ad-creator-v2/CHECKPOINT_005.md` — current state, all context you need
2. `docs/plans/ad-creator-v2/PLAN.md` — full V2 plan (Phase 0 scope only)
3. `CLAUDE.md` — project guidelines

## Branch

We're on `feat/ad-creator-v2-phase0`. All Phase 0 code changes are uncommitted.

## Remaining Nice-to-Haves (3 items)

### Fix #2: Batch `_fetch_campaigns_sync()` in `meta_ads_service.py`

Currently fetches campaigns one-by-one. Batch in groups of 50 (same pattern as `_fetch_ad_statuses_sync()`). The method is at ~line 1074.

### Fix #3: Deactivate 12 duplicate `scraped_templates` rows

Run via Supabase client (NOT raw SQL). The audit found 12 storage_paths with 2 active rows each. For each pair, deactivate the OLDER row (the one created on 2026-01-15, keep the one from 2026-01-23). Script at `scripts/phase0_audit.py` has the query pattern. Write a cleanup script or add to the audit script.

### Fix #4: Clean up 53 orphaned `product_template_usage` rows

These are legacy rows where `template_storage_name` doesn't match any `scraped_templates.storage_path`. Their `template_id` is NULL and will never be populated. Delete them (they're inert tracking records from the old workflow).

## Browser Tests to Verify

After fixes, I'll test these in the browser. Just remind me of what to check:

1. **Scheduled Tasks page** — job badges display correctly (we added V2 + other missing types to `job_type_badge()`)
2. **Ad Scheduler** — create a test V1 ad_creation job, "Run Now", confirm it runs normally
3. **Meta Sync** — trigger sync for a Meta-connected brand, check:
   - `meta_campaigns` table gets rows
   - `meta_ads_performance.campaign_objective` gets populated
   - Railway worker logs show campaign sync messages
4. **Ad Performance / Diagnostics** — load diagnostics, verify objective-aware rules still work

## After Fixes

1. `python3 -m py_compile` on any changed Python files
2. `venv/bin/python3 -m pytest tests/ -x` to verify no regressions
3. Update CHECKPOINT_005.md nice-to-have table (mark items DONE)
4. Commit all changes with descriptive message
5. Push branch to GitHub

## Files You'll Touch

| File | Change |
|------|--------|
| `viraltracker/services/meta_ads_service.py` | Batch `_fetch_campaigns_sync()` |
| `scripts/phase0_cleanup.py` (new) | Deactivate duplicates + delete orphans |
| `docs/plans/ad-creator-v2/CHECKPOINT_005.md` | Update nice-to-have status |

Start by reading CHECKPOINT_005.md, then fix #2, #3, #4 in order.
```
