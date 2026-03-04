# Checkpoint: Phase 2 v2 Adaptation Complete

> Date: 2026-02-23
> Branch: feat/ad-creator-v2-phase0
> Commit: 84113d4
> Status: Phase 2 adaptation implemented. Trajectory flipped from regressing to improving.

## What Was Done

Adapted Phase 2 content assembly so v2 skeletons gain quality through Phase 2 instead of losing it. Three root causes fixed across 5 files, 9 new tests added.

### Root Causes Fixed

| # | Root Cause | Fix | Impact |
|---|-----------|-----|--------|
| 1 | Claude generates invalid CSS range values (`gap: 16-24px`) | Fix ranges in Claude's CSS + append shared CSS as override layer | Primary SSIM improvement |
| 2 | Pre-Phase-3 gate rebuild loses `layout_map` | Pass `layout_map` and `extracted_css` to fallback `assemble_content()` | Preserves structured assembly on rebuild |
| 3 | Stats/testimonials generate non-slottable `<span>`/`<blockquote>` elements | Wrap in `<p>` tags for slot counting | +2 slots per stat item, +2 per testimonial |

### Bonus Fixes Discovered During Testing

| Fix | What | Why |
|-----|------|-----|
| Placeholder stripping | Strip unresolved `{{sec_N_*}}` after Phase 2 | Claude sometimes generates duplicate/unexpected placeholders |
| Sub-placeholder fallback | When skeleton has `{{sec_N_header}}`+`{{sec_N_items}}` but layout_map expects `{{sec_N}}`, combine and inject | Prevents silent content loss from skeleton/layout_map mismatch |

### Files Changed

| File | Changes |
|------|---------|
| `multipass/pipeline.py` | Added `_fix_v2_skeleton_css()` (~40 lines), call site in `_run_phase_1_v2()`, placeholder stripping after Phase 2, fixed gate bug (2 lines) |
| `multipass/content_assembler.py` | Sub-placeholder fallback in structured and linear assembly paths (~25 lines) |
| `multipass/content_patterns.py` | Stats use `<p>` instead of `<span>`, testimonials wrap in `<p>` tags (4 lines) |
| `multipass/section_templates.py` | Updated CSS selectors for `p.mp-stat-number`, `p.mp-stat-label`, blockquote p (4 lines) |
| `tests/test_multipass_v4.py` | 9 new tests: 5 for CSS fix, 4 for slot generation (313 total, all pass) |

### Key Design Decision: Fix+Append, Not Replace

Initially tried replacing Claude's entire `<style>` block with `_build_shared_css()` output. This **made things worse** because Claude generates custom classes (e.g., `mp-container-wide`, `mp-hero-text`, `mp-feature-header`) that only exist in Claude's CSS. Replacing removed those definitions, collapsing layout.

Final approach: Fix invalid range values in Claude's CSS (regex `\d+-\d+px` → midpoint), then append shared CSS after it. This preserves Claude's custom class definitions while fixing invalid values and adding shared CSS as an override layer.

## Current Scores

### InfiniteAge v2 (sea-moss-for-hair-growth)

| Metric | Before (baseline) | After (post-fix) | Delta |
|--------|-------------------|------------------|-------|
| Phase 1 SSIM | 0.7152 | 0.7094 | -0.006 (Claude variability) |
| Phase 2 SSIM | 0.5933 | **0.6408** | **+0.048** |
| Phase 3 SSIM | 0.5929 | 0.6700 | +0.077 |
| Final SSIM | 0.5903 | **0.6736** | **+0.083** |
| Ph1→Ph2 delta | -0.1219 | **-0.0686** | **44% less degradation** |
| Slots | 841 | **882** | +41 |
| Text fidelity | 0.60 | **0.64** | +0.04 |
| Trajectory | regressing | **improving** | **FLIPPED** |

### Boba v2 (bobanutrition.co)

| Metric | Before (baseline) | After (post-fix) | Delta |
|--------|-------------------|------------------|-------|
| Phase 1 SSIM | 0.6133 | 0.5888 | -0.025 (Claude variability) |
| Phase 2 SSIM | 0.5239 | **0.5618** | **+0.038** |
| Phase 3 SSIM | 0.4787 | 0.4281 | -0.051 (Phase 3 not adapted yet) |
| Final SSIM | 0.4787 | **0.5366** | **+0.058** |
| Slots | 259 | 259 | 0 |
| Text fidelity | 0.83 | 0.83 | 0 |
| Trajectory | regressing | **improving** | **FLIPPED** |

### SSIM by Phase (InfiniteAge v2 — Before vs After)

```
Before: 0.7152 → 0.5933 → 0.5929 → 0.5903  (↘ regressing)
After:  0.7094 → 0.6408 → 0.6700 → 0.6736  (↗ improving)
Target:   0.70 →   0.75 →   0.78 →   0.80   (goal)
```

### SSIM by Phase (Boba v2 — Before vs After)

```
Before: 0.6133 → 0.5239 → 0.4787 → 0.4787  (↘ regressing)
After:  0.5888 → 0.5618 → 0.4281 → 0.5366  (↗ improving overall, Ph3 dip)
```

### Template Path (no regression)

Template SSIM trajectory remains improving. No regression from our changes.

## Gap Analysis

| Metric | Current v2 | Original Target | Gap | Notes |
|--------|-----------|----------------|-----|-------|
| Phase 2 SSIM | 0.6408 | 0.75 | -0.11 | Phase 2 still degrades from Phase 1, just less |
| Final SSIM | 0.6736 | 0.80 | -0.13 | Phase 3/4 not adapted yet |
| Text fidelity | 0.64 | 0.85 | -0.21 | Content matching needs improvement |
| Slots | 882 | 1000 | -118 | v2 skeleton structure inherently fewer insertion points |
| Phase 3 SSIM | 0.6700 | 0.78 | -0.08 | Phase 3 CSS refinement not tuned for v2 |
| Phase 4 SSIM | 0.6736 | 0.80 | -0.06 | Phase 4 patches not tuned for v2 |

### Where the Remaining SSIM Gap Comes From

1. **Phase 2 still degrades from Phase 1** (-0.069 on InfiniteAge) — content assembly replaces Claude's carefully-crafted placeholder layout with real content, but the content doesn't perfectly match the visual weight/positioning of the original page
2. **Claude skeleton variability** — Phase 1 SSIM varies 0.67-0.72 across runs due to non-deterministic LLM output
3. **Design system color/font approximation** — extracted design tokens don't perfectly match original page styling
4. **Content pattern simplification** — structured patterns (feature_grid, testimonial_cards, etc.) produce simpler HTML than the original page's bespoke markup
5. **Phase 3/4 not adapted** — CSS refinement and patch prompts still reference template conventions

### Boba-Specific Issues

- Phase 3 SSIM **drops to 0.4281** before recovering to 0.5366 in Phase 4. This suggests Phase 3 CSS patches are actively harming the v2 skeleton (likely targeting wrong selectors).
- Only 259 slots — the Boba page scrape has less structured content, so fewer insertion points regardless of fixes.

## What Needs to Happen Next

### Decision: Continue Phase 2 Work or Move to Phase 3?

**Phase 2 remaining opportunity**: ~0.07 SSIM improvement possible
- Phase 2 currently degrades SSIM by -0.069 (InfiniteAge) / -0.027 (Boba)
- Ideal Phase 2 would be neutral or slightly positive (+0.02 to +0.05)
- Gap: content patterns don't replicate original page structure closely enough

**Phase 3 opportunity**: ~0.08 SSIM improvement possible
- Phase 3 currently adds +0.029 on InfiniteAge (good) but -0.134 on Boba (actively harmful)
- Boba's Phase 3 dip (0.5618 → 0.4281) is a clear regression that Phase 3 adaptation could fix
- Phase 3 CSS refinement prompts likely reference template-specific selectors

**Phase 4 opportunity**: ~0.02-0.05 SSIM improvement possible
- Phase 4 adds small polish (+0.004 InfiniteAge, +0.109 Boba)
- Boba's Phase 4 recovery suggests patch prompts partially compensate for Phase 3 damage

**Recommendation**: Phase 3 adaptation likely has higher ROI than squeezing more from Phase 2, especially given Boba's Phase 3 regression.

## How to Test

```bash
# v2 on InfiniteAge
MULTIPASS_PHASE1_MODE=v2 PYTHONPATH=. python3 scripts/test_multipass_local.py \
  --url "infiniteage.com/pages/sea-moss-for-hair-growth" --visual

# v2 on Boba
MULTIPASS_PHASE1_MODE=v2 PYTHONPATH=. python3 scripts/test_multipass_local.py \
  --url "bobanutrition.co" --visual

# Template baseline (must not regress)
MULTIPASS_PHASE1_MODE=template PYTHONPATH=. python3 scripts/test_multipass_local.py \
  --url "infiniteage.com/pages/sea-moss-for-hair-growth" --visual

# Unit tests (must stay at 313+ pass)
python3 -m pytest tests/test_multipass_v4.py -x -q
```

## Regression Thresholds (Updated)

| Metric | Minimum Acceptable |
|--------|-------------------|
| v2 Phase 1 Skeleton SSIM (InfiniteAge) | >= 0.68 |
| v2 Phase 2 Content SSIM (InfiniteAge) | >= 0.62 (was 0.59, raised after fix) |
| v2 Final SSIM (InfiniteAge) | >= 0.65 (was 0.59, raised after fix) |
| v2 Phase 1 Skeleton SSIM (Boba) | >= 0.56 |
| v2 Phase 2 Content SSIM (Boba) | >= 0.54 (was 0.52, raised after fix) |
| Template Final SSIM (InfiniteAge) | >= 0.72 (no regression on existing path) |
| Unit tests | 313 pass, 0 fail |
| v2 trajectory | improving (MUST NOT regress to regressing) |
