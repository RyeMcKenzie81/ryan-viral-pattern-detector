# Checkpoint: Phase 1 v2 Redesign Complete

> Date: 2026-02-23
> Branch: feat/ad-creator-v2-phase0
> Status: Phase 1 v2 implemented and tested. Downstream Phase 2-4 adaptation needed.

## What Was Done

Implemented the "Phase 1 Redesign: Gemini Sees, Claude Builds" plan — a 7-milestone redesign that splits Phase 1 of the multipass landing page pipeline into 4 focused sub-steps:

| Step | What | API Calls | Latency |
|------|------|-----------|---------|
| 1A | Gemini Visual Audit — describes each section's visual layout | 1 (Gemini) | ~28s |
| 1B | Deterministic Layout Fusion — weighted merge of HTML + Gemini + content signals | 0 | <1ms |
| 1C | Claude Skeleton Codegen — generates HTML/CSS skeleton from structured descriptions | 1 (Claude) | ~22s |
| 1D | Deterministic Validation — validates placeholders, structure, CSS against contract | 0 | <1ms |

### Files Changed (1,380 lines added)

| File | Changes |
|------|---------|
| `viraltracker/core/config.py` | Added `claude-opus-4-6`, `claude-sonnet-4-6` to TOKEN_COSTS |
| `viraltracker/services/landing_page_analysis/multipass/pipeline.py` | Added `_run_phase_1_v2()`, `_call_claude_text()`, `_validate_skeleton()`, `LAYOUT_PLACEHOLDER_MAP`, `SkeletonValidationResult`, extended `PipelineRateLimiter` with provider param, routing in `generate()` |
| `viraltracker/services/landing_page_analysis/multipass/prompts.py` | Added `build_phase_1a_visual_audit_prompt()`, `build_phase_1c_skeleton_codegen_prompt()` |
| `viraltracker/services/landing_page_analysis/multipass/layout_analyzer.py` | Added `fuse_layout_signals()`, `build_section_contexts()` |
| `viraltracker/services/landing_page_analysis/multipass/phase_diagnostics.py` | Extended Phase 1 display with v2 sub-step timings |
| `scripts/test_multipass_local.py` | Added `--phase1-mode` CLI flag |
| `scripts/compare_phase1.py` | New A/B comparison script |
| `tests/test_multipass_v4.py` | 25 new tests (304 total, all pass) |

### Feature Flag

```
MULTIPASS_PHASE1_MODE=v2    # activates new path
MULTIPASS_PHASE1_MODE=template  # default, existing path unchanged
```

### 5-Level Fallback Cascade

0. Claude skeleton passes validation (both test pages hit this)
1. Claude retry with error feedback
2. Template skeleton with fused layout_map
3. Template skeleton with layout_hints only
4. Bare fallback skeleton

## Current Scores

See `BENCHMARK_BASELINE.md` for full details.

### InfiniteAge (the primary benchmark page)

| Metric | Template (before) | v2 (after) |
|--------|-------------------|------------|
| **Phase 1 Skeleton SSIM** | 0.5851 | **0.7152** (+22%) |
| **Final Output SSIM** | **0.7596** | 0.5903 (-17%) |
| Text fidelity | 0.46 | 0.60 |
| Slots | 1,267 | 841 |
| SSIM trajectory | improving | regressing |

**Phase 1 is better. Final output is worse because Phases 2-4 are tuned for template skeletons.**

The template path SSIM improves through phases: 0.58 → 0.76 (trajectory: improving).
The v2 path SSIM degrades through phases: 0.72 → 0.59 (trajectory: regressing).

## What Needs to Happen Next

The v2 skeleton starts at a much higher SSIM (0.7152) but the downstream phases degrade it to 0.5903. The template skeleton starts lower (0.5851) but downstream phases improve it to 0.7596.

The gap is in **Phase 2 content assembly** — it was designed around template skeleton conventions:

### Root Causes of Phase 2-4 Regression

1. **Fewer slots generated** (841 vs 1267) — Claude's skeleton has fewer `data-slot` insertion points because it uses different HTML structure than the templates
2. **CSS class mismatch** — Phase 3/4 CSS patches target `mp-*` template classes that don't exist in Claude's bespoke skeleton
3. **Content patterns not mapping** — `content_patterns.py` generates structured HTML (`mp-feature-card`, `mp-testimonial-card`, etc.) designed for template containers
4. **Placeholder semantics differ** — Claude's skeleton placeholders sit in different DOM contexts than template placeholders, affecting how `content_assembler.py` fills them

### Key Files for Phase 2-4 Adaptation

| File | Lines | Role |
|------|-------|------|
| `multipass/content_assembler.py` | 607 | Fills placeholders with markdown content — needs to understand v2 skeleton structure |
| `multipass/content_patterns.py` | 500 | Detects FAQ, feature grid, testimonial patterns and generates structured HTML — hardcoded to `mp-*` classes |
| `multipass/section_templates.py` | 464 | 13 fixed templates + `_build_shared_css()` — shared CSS already injected into v2, but patterns need updating |
| `multipass/pipeline.py` | 2,735 | Phase 3 (CSS refinement) and Phase 4 (patches) reference template conventions |
| `multipass/prompts.py` | 637+ | Phase 2/3/4 prompts may need adjustment for v2 skeleton context |

### Target Scores After Phase 2-4 Adaptation

The goal is for v2 to maintain its Phase 1 advantage AND improve through downstream phases (like template does), achieving:

| Metric | Current v2 | Target |
|--------|------------|--------|
| Phase 1 Skeleton SSIM | 0.7152 | >= 0.70 (maintain) |
| Phase 2 Content SSIM | 0.5933 | >= 0.75 (match template's Phase 2 lift) |
| Final Output SSIM | 0.5903 | **>= 0.80** (beat template's 0.76) |
| Text fidelity | 0.60 | >= 0.85 |
| SSIM trajectory | regressing | **improving** |
| Slots | 841 | >= 1000 |

## How to Test

```bash
# Run v2 on InfiniteAge
MULTIPASS_PHASE1_MODE=v2 PYTHONPATH=. python3 scripts/test_multipass_local.py \
  --url "infiniteage.com/pages/sea-moss-for-hair-growth" --visual

# Run v2 on Boba
MULTIPASS_PHASE1_MODE=v2 PYTHONPATH=. python3 scripts/test_multipass_local.py \
  --url "bobanutrition.co" --visual

# Run template baseline for comparison
MULTIPASS_PHASE1_MODE=template PYTHONPATH=. python3 scripts/test_multipass_local.py \
  --url "infiniteage.com/pages/sea-moss-for-hair-growth" --visual

# Unit tests
python3 -m pytest tests/test_multipass_v4.py -x -q
```
