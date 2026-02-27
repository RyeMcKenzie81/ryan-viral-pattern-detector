# Checkpoint: PatchApplier Style-Block Injection — Complete

**Date**: 2026-02-27
**Branch**: `feat/ad-creator-v2-phase0`
**Status**: Style-block injection working, needs post-patch SSIM validation safety net

---

## What Was Done

### 1. PatchApplier: Style-Block Injection (COMPLETE)

**File**: `viraltracker/services/landing_page_analysis/multipass/patch_applier.py`

- Added `_css_contains_injection()` helper — blocks `</style>`, `javascript:`, `expression()`, `@import`
- Added `_add_important()` helper — appends `!important` to each CSS property (skips if already present)
- Added `_apply_css_fix_via_style_block()` method — injects a single `<style data-patch-applier>` block before `</head>`
- Modified `apply_patches()` — detects full documents (`</head>` present), routes `css_fix` patches to style-block path. Fragments and `add_element`/`remove_element` still use existing inline/restricted-grammar path.

### 2. Prompt Updates (COMPLETE)

**File**: `viraltracker/services/landing_page_analysis/multipass/surgery/prompts.py`
- `build_surgery_patch_prompt()` now accepts `html_preview` and `selector_summary` params
- Added `_extract_selector_summary()` — extracts class names, IDs, data-section, data-slot from HTML
- Prompt now includes available selectors + truncated HTML so Gemini targets valid elements

**File**: `viraltracker/services/landing_page_analysis/multipass/prompts.py`
- Phase 4: Split selector grammar into css_fix (any valid selector) vs add_element/remove_element (restricted)
- Phase 3 fullpage: Relaxed to allow any valid CSS selector
- Phase 3 section: Same relaxation

### 3. Pipeline Integration (COMPLETE)

**File**: `viraltracker/services/landing_page_analysis/multipass/surgery/pipeline.py`
- S4 now passes `html_preview` (first 20K chars) and `selector_summary` to `build_surgery_patch_prompt()`

### 4. Tests (COMPLETE)

**File**: `tests/test_multipass_pipeline.py`
- Added `TestPatchApplierStyleBlock` class with 7 tests:
  - `test_css_fix_injects_style_block_in_full_doc`
  - `test_css_fix_falls_back_to_inline_for_fragment`
  - `test_complex_selector_accepted_in_full_doc`
  - `test_injection_blocked`
  - `test_add_element_still_uses_restricted_grammar`
  - `test_important_not_duplicated`
  - `test_multiple_css_fix_batched_into_one_block`
- All 7 new tests pass, all existing tests pass (71/71 + 410/410)

---

## Test Results (3 rounds x 3 pages)

### Round 1: Baseline (BEFORE any changes)
| Page | S3 SSIM | S4 SSIM | S3→S4 Delta |
|------|---------|---------|-------------|
| Boba | 0.5469 | 0.5469 | 0.0000 |
| InfiniteAge | 0.6900 | 0.6900 | 0.0000 |
| Hike | 0.7701 | 0.7701 | 0.0000 |

All S4 patches were **skipped** (complex selectors rejected by old grammar).

### Round 2: Style-block injection, no HTML context in prompt
| Page | S3 SSIM | S4 SSIM | S3→S4 Delta |
|------|---------|---------|-------------|
| Boba | 0.5469 | 0.5469 | 0.0000 |
| InfiniteAge | 0.6900 | 0.6900 | 0.0000 |
| Hike | 0.7701 | 0.7701 | 0.0000 |

Style blocks injected but patches targeted **non-existent selectors** (original page classes stripped in S0).

### Round 3: Style-block + HTML-aware prompt (selector summary + 20K preview)
| Page | S3 SSIM | S4 SSIM | S3→S4 Delta | vs Baseline |
|------|---------|---------|-------------|-------------|
| Boba | 0.5469 | 0.5469 | 0.0000 | flat |
| InfiniteAge | 0.6900 | **0.6969** | **+0.0069** | **improved** |
| Hike | 0.7701 | **0.7134** | **-0.0568** | **regressed** |

Patches now target **real elements** — InfiniteAge improved, but Hike regressed because Gemini applied aggressive layout changes (`display: flex/grid`) to content slots.

### Snapshot Directories
```
# Baseline (before changes)
test_multipass_snapshots/run_20260227_001336_d6ad0f/  # Boba baseline
test_multipass_snapshots/run_20260227_001323_3ace14/  # InfiniteAge baseline
test_multipass_snapshots/run_20260227_001749_8f437c/  # Hike baseline

# Round 2 (style-block, no HTML context)
test_multipass_snapshots/run_20260227_002417_7aee25/  # Boba
test_multipass_snapshots/run_20260227_002413_c4c936/  # InfiniteAge
test_multipass_snapshots/run_20260227_002349_829195/  # Hike

# Round 3 (style-block + HTML-aware prompt)
test_multipass_snapshots/run_20260227_005053_5d4d7f/  # Boba
test_multipass_snapshots/run_20260227_005100_28a91b/  # InfiniteAge
test_multipass_snapshots/run_20260227_005059_7f8057/  # Hike (REGRESSED)
```

---

## What Needs to Be Done Next

### Post-Patch SSIM Validation (NOT YET IMPLEMENTED)

The Hike regression proves that S4 patches can make things worse. Need a safety net:

**Location**: `viraltracker/services/landing_page_analysis/multipass/surgery/pipeline.py`, lines ~241-255

**Current flow**:
```
1. Render S3 scoped HTML → compute S3 SSIM
2. If S3 SSIM < threshold → ask Gemini for patches
3. Apply patches via PatchApplier
4. Validate slot count didn't decrease → accept or revert
```

**Proposed flow** (add step between 3 and 4):
```
1. Render S3 scoped HTML → compute S3 SSIM (already done)
2. If S3 SSIM < threshold → ask Gemini for patches (already done)
3. Apply patches via PatchApplier (already done)
3.5 NEW: Render patched HTML → compute S4 SSIM
    - If S4 SSIM < S3 SSIM → revert to S3 output, log warning
    - If S4 SSIM >= S3 SSIM → keep patched output
4. Validate slot count didn't decrease → accept or revert (already done)
```

**Key implementation details**:
- `render_html_to_png_async()` is already imported and used for S3 rendering
- `score_visual_fidelity()` is already imported and used for S3 SSIM
- Just need one more render + compare + conditional revert
- Cost: ~3-5 seconds for Playwright render (negligible vs Gemini API call)
- The `original_png` (decoded screenshot) is already available at line 203

**After implementing**, re-run all 3 pages and verify:
- InfiniteAge: S4 >= 0.6969 (improvement preserved)
- Hike: S4 = 0.7701 (regression prevented, falls back to S3)
- Boba: S4 >= 0.5469 (no regression)

---

## Files Modified (current state on disk)

| File | Status |
|------|--------|
| `multipass/patch_applier.py` | Modified — style-block injection + helpers |
| `multipass/surgery/prompts.py` | Modified — HTML-aware prompt + selector extractor |
| `multipass/surgery/pipeline.py` | Modified — passes HTML to prompt |
| `multipass/prompts.py` | Modified — relaxed selector grammar in Phase 3/4 |
| `tests/test_multipass_pipeline.py` | Modified — 7 new tests |
