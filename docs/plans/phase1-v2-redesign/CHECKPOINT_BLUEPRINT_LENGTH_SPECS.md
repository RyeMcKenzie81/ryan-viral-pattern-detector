# Checkpoint: Blueprint-Level Length Specs with A/B Comparison

**Date**: 2026-02-25
**Branch**: `feat/ad-creator-v2-phase0`
**Commits**: `15f2872` (length specs), `b88ce2f` (Shopify chrome fix)
**Status**: Implementation complete, A/B test run, deployed

## Problem

The per-slot length enforcement shipped in the slot pipeline (regen loop + truncation) works mechanically, but copy quality suffers. In the live Martin Clinic test, 36/187 slots were over-length after the initial AI write. The regen loop and truncation produced flat, lifeless copy — particularly in body paragraphs (e.g., `body-14`: 90 -> 82 -> 79 -> truncated to 72 words).

**Root cause**: The AI writes freely, then gets told to cut. Cutting always degrades quality.

**Hypothesis**: If the AI knows the space budget as part of the creative direction — not as a mechanical post-hoc constraint — it will compose-to-fit and produce better copy on the first pass.

## What Was Done

### 1. Strategy Pattern Refactor

Replaced monolithic `_rewrite_slots_for_brand()` with a strategy pattern:

- **`_SlotRewriteConfig` dataclass** — encapsulates all strategy-specific configuration
- **`_build_runtime_rewrite_config()`** — builds config for existing `"slot_constrained"` strategy (per-slot `max_words`)
- **`_build_blueprint_rewrite_config()`** — builds config for new `"section_guided"` strategy (section-level `space_budget`)
- **`_execute_slot_rewrite_pipeline(config)`** — shared core (~250 lines) extracted from the original method
- **`_rewrite_slots_for_brand()`** — now a thin delegate that picks strategy and calls the pipeline

### 2. Section Metrics & Space Budgets

Two new methods compute section-level length guidance:

- **`_aggregate_section_metrics(slot_contents, slot_sections)`** — groups slots by section, computes total_words, slot_count, per-type breakdown
- **`_format_section_space_budget(section_metrics)`** — converts metrics to structured `space_budget` dicts with word ranges

Guards applied:
- Skip `"global"` sections (orphan slots — meaningless aggregate)
- Skip sections with only 1 slot (per-slot constraint sufficient)
- Simplify sections with >15 slots (`"Large section; follow individual slot targets"`)
- Exclude slot types with <=3 words from breakdown (nav items, prices, badges)

Space budget structure per section:
```json
{
    "total_words": 180,
    "breakdown": [
        {"role": "headline", "target_range": [6, 10], "slots": ["headline"]},
        {"role": "body", "target_range": [55, 70], "slots": ["body-14"]},
        {"role": "cta", "target_range": [3, 5], "slots": ["cta-1"]}
    ],
    "note": "Use 85-100% of each target range. Underusing space wastes layout real estate."
}
```

### 3. Prompt Refactoring

Split `_SLOT_REWRITE_SYSTEM_PROMPT` into composable parts:

| Part | Purpose |
|------|---------|
| `_SLOT_REWRITE_PROMPT_BASE` | Shared rules, slot type guidelines, anti-repetition rule |
| `_SLOT_REWRITE_ADDENDUM_RUNTIME` | Hard word limit framing ("Over budget is NOT acceptable") |
| `_SLOT_REWRITE_ADDENDUM_BLUEPRINT` | Creative constraint framing ("undershooting wastes space") |
| `_REGEN_PROMPT_RUNTIME` | Existing "condense" regen framing |
| `_REGEN_PROMPT_BLUEPRINT` | New "rewrite tighter" regen with copy_direction context |

Backward compat: `_SLOT_REWRITE_SYSTEM_PROMPT = _SLOT_REWRITE_PROMPT_BASE + _SLOT_REWRITE_ADDENDUM_RUNTIME`

### 4. A/B Test Infrastructure

Updated `scripts/test_slot_pipeline_martin.py` with `--ab` flag:
- Runs both strategies on the same input
- Outputs `test_martin_A_slot_constrained.html` and `test_martin_B_section_guided.html`
- Prints comparison metrics: word counts, first-pass compliance, regen/truncation counts, side-by-side text samples

### 5. Shopify Chrome Stripping

Added `_strip_shopify_chrome()` to remove Shopify theme elements that survive the surgery pipeline DOM capture:

- **Anti-scraping overlay** — `<div>` with z-index >10^8 and color:transparent
- **Header** — elements with IDs matching `header|footer|mega[_-]?menu`
- **Footer** — same ID pattern
- **Mega menu** — nested nav with product cards

Uses Python's `HTMLParser` to walk the DOM and skip matched elements. Only active in surgery mode (`is_surgery_mode=True`). Called in `generate_blueprint_mockup()` right after CSS extraction, before slot processing.

## Files Modified

| File | Changes |
|------|---------|
| `mockup_service.py` | `_SlotRewriteConfig` dataclass, 6 new methods, prompt refactoring, strategy routing, `_strip_shopify_chrome()` |
| `scripts/test_slot_pipeline_martin.py` | `--ab` flag, `_run_single_strategy()`, `_count_slot_words()`, `test_ab_comparison()` |

## A/B Test Results (Martin Clinic / Boba Nutrition)

| Metric | A: slot_constrained | B: section_guided |
|--------|---------------------|-------------------|
| First-pass OK | 162/187 (87%) | 137/187 (73%) |
| Regen'd | 43 | 0 (batch too large) |
| Truncated | 10 | 50 |
| Total words | 2,901 | 3,168 |

**Qualitative**: User reviewed both outputs side-by-side and said "ok this is a lot better" about the section_guided output. The copy reads more naturally, with better flow within sections.

## Known Issues

1. **Regen batching for section_guided** — When 50 slots exceed target in a single batch, the regen call fails output validation (too many slots for structured output). All 50 fall through to truncation. Fix: batch regen calls like initial writes.

2. **Blueprint addendum causes overshooting** — The "undershooting wastes space" framing causes the AI to write 9% more total words than slot_constrained. The asymmetric cost framing may need tuning — consider rebalancing to "aim for 90-95% of target range" rather than "85-100%".

## Architecture Decision: Why Strategy Pattern

The plan originally considered `if length_mode` branching throughout the 335-line rewrite method. The strategy pattern (config dataclass + separate builders + shared pipeline) was chosen because:

- The rewrite method has 6 stages (batching, AI call, validation, regen, truncation, logging) — branching in each would be shotgun surgery
- The config dataclass makes the two strategies' differences explicit and testable
- The shared pipeline ensures both strategies get the same safety nets (regen + truncation)
- Forward-compatible: when blueprints natively carry length data, only `_build_blueprint_rewrite_config()` changes

## What's Next

- **Tune blueprint addendum** — reduce overshooting by adjusting target framing
- **Batch regen calls** — split over-length slots into batches of ~30 for regen, matching initial write batching
- **Deferred: Blueprint-native length data** — bake length guidance into blueprint generation pipeline so it doesn't need to be computed at rewrite time
