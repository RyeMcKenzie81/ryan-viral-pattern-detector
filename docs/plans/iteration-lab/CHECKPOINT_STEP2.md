# Checkpoint: Step 2 - Add `days_back` param to winner analysis

## Status: COMPLETE

## What Was Done
- Added `days_back` parameter to `WinnerDNAAnalyzer.analyze_cross_winners()` (default 30)
- Added `days_back` parameter to `WinnerDNAAnalyzer._find_top_winners()` (default 30)
- `_find_top_winners()` now passes `days_back` through to `perf_service.get_top_ads()`
- Added "Days back" selector to top of Tab 2 (Analyze Winners), shared across Blueprint and Deep Dive
- Both `_render_cross_winner()` and `_render_per_winner()` now accept and use `days_back`
- `_run_cross_winner_analysis()` passes `days_back` through to the analyzer

## Files Changed
- `viraltracker/services/winner_dna_analyzer.py` — `analyze_cross_winners()`, `_find_top_winners()` signatures
- `viraltracker/ui/pages/38_🔬_Iteration_Lab.py` — `render_winners_tab()`, `_render_cross_winner()`, `_render_per_winner()`, `_run_cross_winner_analysis()`

## QA
- `python3 -m py_compile` passes for both files
