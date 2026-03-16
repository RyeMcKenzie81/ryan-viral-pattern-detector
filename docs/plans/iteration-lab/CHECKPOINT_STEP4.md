# Checkpoint: Step 4 - Data-driven opportunity explanations

## Status: COMPLETE

## What Was Done

### Service (`iteration_opportunity_detector.py`)
- Added 3 new fields to `IterationOpportunity` dataclass:
  - `explanation_headline: str = ""` — plain-language summary of the opportunity
  - `explanation_projection: str = ""` — projected improvement with caveat
  - `projected_roas: float = 0.0` — numeric projection
- Added `_build_explanation()` method with pattern-specific explanations for all 5 pattern types:
  - `high_converter_low_stopper` — CVR + CTR framing, proportional ROAS projection
  - `good_hook_bad_close` — CTR + ROAS framing, median ROAS target
  - `thumb_stopper_quick_dropper` — hook vs hold rate framing
  - `efficient_but_starved` — budget scaling framing
  - `fatiguing_winner` — decline percentage framing
- Wired `_build_explanation()` into `_evaluate_pattern()` to set fields on each opportunity
- Added `.order("date", desc=True)` to `_load_ads_with_performance()` query so most recent thumbnail comes first

### UI (`38_Iteration_Lab.py`)
- Opportunity card now shows `explanation_headline` as the summary text (falls back to metric string if empty)
- Details expander now shows `explanation_projection` in italics above the strategy section
- New fields flow through `_run_scan()` via `__dict__` serialization (no changes needed there)

## Design Decisions
- New fields are NOT stored in DB (no migration needed) — computed at detection time, carried via session state
- Don't overwrite `strategy_description` — used separately by iterate confirmation
- Projection uses simple proportional ROAS math with "assumes constant conversion rate" caveat

## Files Changed
- `viraltracker/services/iteration_opportunity_detector.py` — dataclass, `_build_explanation()`, `_evaluate_pattern()`, `_load_ads_with_performance()`
- `viraltracker/ui/pages/38_🔬_Iteration_Lab.py` — `_render_opportunity_card()`

## QA
- `python3 -m py_compile` passes for both files
