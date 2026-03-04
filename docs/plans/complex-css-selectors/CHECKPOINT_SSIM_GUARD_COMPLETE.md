# Checkpoint: Post-Patch SSIM Guard — Complete

**Date**: 2026-02-27
**Branch**: `feat/ad-creator-v2-phase0`
**Status**: COMPLETE — Complex CSS selectors plan fully implemented

---

## What Was Done

### Post-Patch SSIM Validation (COMPLETE)

**File**: `viraltracker/services/landing_page_analysis/multipass/surgery/pipeline.py`

Added a post-patch SSIM guard to the S4 Visual QA stage. After patches are applied, the patched HTML is rendered and its SSIM is compared to the pre-patch S3 SSIM. If the patches made things worse (SSIM regressed), they are reverted.

**Implementation** (~10 lines, inserted at line 248):

```python
if patch_count > 0:
    # Validate 1: SSIM must not regress
    s4_png = await render_html_to_png_async(patched)
    if s4_png:
        s4_ssim = score_visual_fidelity(original_png, s4_png)
        if s4_ssim < ssim_score:
            # Revert — patches made things worse
            patch_count = 0

    if patch_count > 0:
        # Validate 2: patches must not lose slots (existing check)
        ...
```

**Key details**:
- Uses existing `render_html_to_png_async()` and `score_visual_fidelity()` — no new dependencies
- Cost: ~3-5 seconds for one Playwright render (negligible vs Gemini API call)
- Two-gate validation: SSIM check first, then slot-count check (both must pass)
- Logging shows S3 vs S4 SSIM with delta for easy debugging

---

## Test Results (Post-Guard)

| Page | S3 SSIM | S4 SSIM (patches) | Guard Action | Final SSIM | vs Baseline |
|------|---------|-------------------|--------------|------------|-------------|
| **Hike** | 0.770 | 0.643 (-0.127) | **Reverted** | **0.7701** | flat (regression prevented) |
| **Boba** | 0.547 | 0.558 (+0.011) | Accepted | **0.5582** | **+0.011 improved** |
| **InfiniteAge** | 0.690 | 0.693 (+0.003) | Accepted | **0.6925** | **+0.003 improved** |

All three pages meet expectations:
- Hike: Regression prevented (reverts to S3)
- Boba: Improvement preserved
- InfiniteAge: Improvement preserved

### Snapshot Directories
```
# Post-guard results
test_multipass_snapshots/run_20260227_010246_e25387/  # Hike (REVERTED, 0.7701)
test_multipass_snapshots/run_20260227_010302_a61499/  # Boba (ACCEPTED, 0.5582)
test_multipass_snapshots/run_20260227_010526_151740/  # InfiniteAge (ACCEPTED, 0.6925)
```

---

## Complete Plan Summary

The complex-css-selectors plan is now **fully implemented**. Here's everything that was delivered:

### 1. PatchApplier Style-Block Injection
- `_css_contains_injection()` — blocks XSS patterns
- `_add_important()` — ensures specificity
- `_apply_css_fix_via_style_block()` — injects `<style data-patch-applier>` block
- Routes full-doc `css_fix` patches to style-block; fragments use inline

### 2. HTML-Aware Prompts
- `_extract_selector_summary()` — extracts available classes, IDs, data-attributes
- Prompt includes selector summary + 20K HTML preview for Gemini context

### 3. Relaxed Selector Grammar
- Phase 3/4: `css_fix` accepts any valid CSS selector
- `add_element`/`remove_element` still use restricted grammar

### 4. Post-Patch SSIM Guard
- Renders patched HTML, compares SSIM to S3
- Reverts if SSIM regressed
- Two-gate validation: SSIM + slot-count

### 5. Tests
- 7 new unit tests in `TestPatchApplierStyleBlock` (all passing)
- 3 integration tests across Hike, Boba, InfiniteAge (all passing)

---

## Files Modified

| File | Changes |
|------|---------|
| `multipass/patch_applier.py` | Style-block injection + security helpers |
| `multipass/surgery/prompts.py` | HTML-aware prompt + selector extractor |
| `multipass/surgery/pipeline.py` | HTML context pass-through + SSIM guard |
| `multipass/prompts.py` | Relaxed selector grammar in Phase 3/4 |
| `tests/test_multipass_pipeline.py` | 7 new tests |

---

## What's Next (Out of Scope)

No remaining items for this plan. Potential future improvements:
- **Prompt tuning**: Restrict Gemini from applying layout-changing properties (`display`, `position`, `grid`, `flex`) in S4 patches
- **Per-property allowlist**: Only allow safe CSS properties (color, font, margin, padding, background) in S4
- **Multi-round S4**: If SSIM improved but is still below threshold, try another round of patches
