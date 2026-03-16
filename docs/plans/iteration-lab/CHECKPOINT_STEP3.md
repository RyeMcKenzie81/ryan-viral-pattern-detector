# Checkpoint: Step 3 - Add `thumbnail_url` to `_aggregate_by_ad()`

## Status: COMPLETE

## What Was Done
- Added `thumbnail_url` passthrough in `_aggregate_by_ad()` aggregation loop
  - Picks the first non-empty thumbnail URL (rows are ordered by date desc, so most recent)
- Added `thumbnail_url` to the result dict output

## Files Changed
- `viraltracker/services/ad_performance_query_service.py` — `_aggregate_by_ad()` method

## Notes
- `_fetch_performance_rows()` already uses `select("*")`, so `thumbnail_url` was already being fetched from the database
- This was purely a passthrough addition in the aggregation layer

## QA
- `python3 -m py_compile` passes
