# Phase 2-4 Adaptation for v2 Skeleton — Continuation Prompt

Copy this into a new Claude Code context window:

---

## Context

I just completed Phase 1 v2 of the multipass landing page pipeline ("Gemini Sees, Claude Builds"). Phase 1 now produces a much better skeleton (SSIM 0.7152 vs 0.5851 with templates), but the final output is WORSE (0.5903 vs 0.7596) because Phases 2-4 were designed for template skeletons.

Read these files first to understand the current state:
- `docs/plans/phase1-v2-redesign/CHECKPOINT_PHASE1_V2_COMPLETE.md` — what was done, current scores, root causes
- `docs/plans/phase1-v2-redesign/BENCHMARK_BASELINE.md` — full benchmark scores with regression thresholds

## Task

Adapt Phases 2-4 of the multipass pipeline so the v2 skeleton's quality advantage carries through to the final output instead of regressing.

**Target scores (InfiniteAge):**
- Phase 1 Skeleton SSIM: >= 0.70 (maintain, don't regress)
- Final Output SSIM: **>= 0.80** (currently 0.59, template achieves 0.76)
- Text fidelity: >= 0.85 (currently 0.60)
- SSIM trajectory: **improving** (currently regressing)
- Slots: >= 1000 (currently 841)

## Approach

Spin up multiple research sub-agents in parallel to investigate:

1. **Content Assembly Agent** — Read `multipass/content_assembler.py` (607 lines) and `multipass/content_patterns.py` (500 lines). Analyze why v2 skeletons produce fewer slots (841 vs 1267). The assembler fills `{{sec_N}}` / `{{sec_N_header}}` / `{{sec_N_items}}` placeholders — investigate whether Claude's skeleton HTML structure around these placeholders differs enough from templates that the assembler inserts less content. Check if content_patterns.py's structured HTML generators (using `mp-feature-card`, `mp-testimonial-card`, etc.) are compatible with v2 skeleton containers.

2. **CSS Patch Agent** — Read `multipass/pipeline.py` Phase 3 and Phase 4 code (search for `phase_3` and `phase_4` in the file), plus `multipass/prompts.py` (the Phase 3 and Phase 4 prompts). Investigate why SSIM degrades from 0.71 to 0.59 through these phases. The prompts tell Gemini to generate CSS patches targeting specific selectors — if Claude's skeleton uses different class names than templates, the patches may be destructive. Compare the v2 skeleton HTML (saved at `test_multipass_snapshots/latest/phase_1_skeleton.html`) against a template skeleton to identify class name mismatches.

3. **Skeleton Structure Agent** — Read the v2 skeleton output at `test_multipass_snapshots/latest/phase_1_skeleton.html` and compare it to `multipass/section_templates.py` (464 lines). Map the differences: what CSS classes does Claude use vs templates? Where does Claude put placeholders in the DOM tree vs where templates put them? This tells us exactly what the assembler and CSS patches need to adapt to.

4. **Test Infrastructure Agent** — Read `tests/test_multipass_v4.py` and `multipass/phase_diagnostics.py`. Understand the existing test coverage for Phase 2-4 and the diagnostic reporting. We need to ensure any changes maintain 304+ tests passing and can be validated with `--visual` runs.

After the research agents report back, synthesize their findings into a plan. Use `/plan-workflow` to enter plan mode and design the adaptation.

## How to Verify

After implementation, run:
```bash
# v2 pipeline
MULTIPASS_PHASE1_MODE=v2 PYTHONPATH=. python3 scripts/test_multipass_local.py \
  --url "infiniteage.com/pages/sea-moss-for-hair-growth" --visual

# Template baseline (must not regress)
MULTIPASS_PHASE1_MODE=template PYTHONPATH=. python3 scripts/test_multipass_local.py \
  --url "infiniteage.com/pages/sea-moss-for-hair-growth" --visual

# Boba
MULTIPASS_PHASE1_MODE=v2 PYTHONPATH=. python3 scripts/test_multipass_local.py \
  --url "bobanutrition.co" --visual

# Unit tests
python3 -m pytest tests/test_multipass_v4.py -x -q
```

Compare scores against `BENCHMARK_BASELINE.md`. The template path must NOT regress (final SSIM >= 0.72). The v2 path should achieve final SSIM >= 0.80 with improving trajectory.
