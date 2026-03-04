# Checkpoint: Milestone 1 — Per-Phase Evaluation Infrastructure

**Date**: 2026-02-23
**Branch**: `feat/ad-creator-v2-phase0`
**Previous commit**: `7e7e439` — Template fidelity improvements
**Status**: Complete, not yet committed

---

## What Was Done

### Step 1: Fixed Phase 1 Fallback Bug
**File**: `pipeline.py:1603-1618`

`_phase_1_fallback_classify()` was returning `layout_map={}` even when `layout_hints` from `layout_analyzer.py` were available. Now accepts and filters `layout_hints` through to callers. Both fallback call sites (rate-limit at line 1707, exception at line 1712) updated.

### Step 2: Created html_renderer.py (NEW)
**File**: `viraltracker/services/landing_page_analysis/multipass/html_renderer.py`

Thin Playwright sync wrapper: `render_html_to_png()`. Canonical settings:
- Viewport: 1280x800 (matching `visual_fidelity_check.py`)
- Freezes animations via CSS injection
- Restores background images before rendering
- Function-local Playwright imports (dev-only dependency)
- Never crashes — returns `None` on failure

### Step 3: Extended PhaseVerdict + PhaseDiagnosticReport
**File**: `phase_diagnostics.py`

- `PhaseVerdict.warnings: List[str]` — WARN-level issues (never cause FAIL)
- `PhaseDiagnosticReport.visual_scores: Optional[Dict[str, float]]` — phase → SSIM
- `PhaseDiagnosticReport.visual_trajectory: Optional[str]` — "improving"/"regressing"/"flat"
- `format()` renders WARN lines distinctly + visual SSIM section
- `to_dict()` serializes warnings + visual data
- Added `_check_unclosed_tags()` helper

### Step 4: WARN-First Quality Gates
**File**: `phase_diagnostics.py`

| Phase | Gate | Level |
|-------|------|-------|
| Phase 1 | Malformed `{{` vs `}}` count | WARN |
| Phase 3 | Text preservation < 0.80 vs Phase 2 | WARN |
| Final | Unclosed block-level tags | WARN |
| Final | Slot retention < 80% vs Phase 2 | WARN |

All WARN-only until distributions collected from 5+ pages.

### Step 5: Patched eval_multipass.py
**File**: `scripts/eval_multipass.py`

- `evaluate_page()` now receives screenshot bytes for SSIM scoring
- Per-phase SSIM trajectory via `render_html_to_png` + `score_visual_fidelity`
- Run-scoped output: `bench_{ts}_{hash}/page_{id}/` with metadata.json, PNGs, diagnostics
- `--skip-visual` fully functional
- `benchmark_summary.json` with aggregate scores

### Step 6: Patched test_multipass_local.py
**File**: `scripts/test_multipass_local.py`

- Added `--visual` flag
- Run-scoped output: `run_{ts}_{hash}/` with metadata.json, phase HTMLs, rendered PNGs
- SSIM trajectory with deltas printed to terminal
- `latest` symlink updated each run
- Visual scores attached to diagnostic report

### Step 7: PIL Decompression Bomb Fix
**File**: `eval_harness.py:137`

Added `Image.MAX_IMAGE_PIXELS = 300_000_000` to handle long landing page screenshots (InfiniteAge was 185M pixels, default limit is 178M).

### Step 8: Tests
**File**: `tests/test_multipass_v4.py`

20 new tests across 5 test classes:
- B25: PhaseVerdict warnings (5 tests)
- B26: Quality gates (5 tests)
- B27: Fallback layout_hints preservation (3 tests)
- B28: html_renderer (3 tests)
- B29: PhaseDiagnosticReport visual fields (4 tests — including `_check_unclosed_tags`)

**All 237 tests pass.**

---

## Baseline Results (2 pages)

### Boba Nutrition (simpler page)
- URL: `https://bobanutrition.co/pages/7reabreakfast`
- 8 sections, 26K markdown, 178K page_html
- 99 slots, 11 images, 1 overflow section
- Run dir: `test_multipass_snapshots/run_20260223_204328_19fc8c/`

| Phase | SSIM | Delta |
|-------|------|-------|
| Phase 1 — Skeleton | 0.5774 | — |
| Phase 2 — Content | 0.5869 | +0.010 |
| Phase 3 — Refined | 0.6253 | +0.038 |
| Phase 4 — Final | 0.6035 | -0.022 |
| **Trajectory** | **improving** | |

Diagnostic: Phase 2 FAIL (12 unfilled placeholders, text fidelity 0.24), Final FAIL (fidelity 0.25)

### InfiniteAge (complex page)
- URL: `http://infiniteage.com/pages/sea-moss-for-hair-growth`
- 8 sections, 54K markdown, 428K page_html
- 671 slots, 252 images, 5 overflow sections
- Run dir: `test_multipass_snapshots/run_20260223_204744_e3d233/`

| Phase | SSIM | Delta |
|-------|------|-------|
| Phase 1 — Skeleton | 0.5765 | — |
| Phase 2 — Content | 0.5973 | +0.021 |
| Phase 3 — Refined | 0.6068 | +0.010 |
| Phase 4 — Final | 0.6078 | +0.001 |
| **Trajectory** | **improving** | |

Diagnostic: Phase 2 FAIL (7 unfilled placeholders, text fidelity 0.56), Final FAIL (fidelity 0.56)

### Key Observations
1. Phase 1 SSIM nearly identical (~0.577) despite 10x complexity difference
2. Both trajectories improving — pipeline adds value at each phase
3. Phase 4 slightly regressed on Boba (-0.022) — patch pass CSS needs investigation
4. **Text fidelity is the bottleneck** — nav/footer chrome inflates source markdown, making scores artificially low → Milestone 2 fix
5. Unfilled placeholders (12 Boba, 7 InfiniteAge) — template pattern gaps → Milestone 3 fix

---

## Files Changed (uncommitted)

| File | Change |
|------|--------|
| `viraltracker/services/landing_page_analysis/multipass/pipeline.py` | Fallback fix (~10 lines) |
| `viraltracker/services/landing_page_analysis/multipass/html_renderer.py` | **NEW** (~85 lines) |
| `viraltracker/services/landing_page_analysis/multipass/phase_diagnostics.py` | Warnings + visual + gates (~70 lines) |
| `viraltracker/services/landing_page_analysis/multipass/eval_harness.py` | PIL pixel limit fix (~1 line) |
| `scripts/eval_multipass.py` | Visual scoring + run dirs (~100 lines rewritten) |
| `scripts/test_multipass_local.py` | --visual + run dirs (~80 lines rewritten) |
| `tests/test_multipass_v4.py` | 20 new tests (~350 lines) |

---

## What's Next: Milestone 2 — Markdown Classifier

See continuation prompt below.
