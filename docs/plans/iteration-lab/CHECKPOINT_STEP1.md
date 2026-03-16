# Checkpoint: Step 1 - Fix `_format_metric` with `from_decimal` param

## Status: COMPLETE

## What Was Done
- Added `from_decimal` parameter to `_format_metric()` in `38_Iteration_Lab.py`
- When `from_decimal=True`, rate metrics (ctr, hook_rate, hold_rate, conversion_rate) are multiplied by 100 before display
- Added `None` safety check (returns "n/a")
- Added `spend` metric formatting ($X,XXX)
- Fixed `ctr_decline_pct` formatting to handle both decimal and percentage values
- Updated opportunity card call sites to pass `from_decimal=True` (detector stores CTR as decimal 0.015)
- Deep Dive / winner analysis call sites use default `from_decimal=False` (winner_dna_analyzer stores as percentage 1.5)

## Files Changed
- `viraltracker/ui/pages/38_🔬_Iteration_Lab.py` — `_format_metric()` signature + 1 call site

## QA
- `python3 -m py_compile` passes
