# Phase 2 Content Assembly Adaptation for v2 Skeleton — Continuation Prompt

Copy this into a new Claude Code context window:

---

## Context

I just completed Phase 1 v2 of the multipass landing page pipeline ("Gemini Sees, Claude Builds"). Phase 1 now produces a much better skeleton (SSIM 0.7152 vs 0.5851 with templates), but the final output is WORSE because Phase 2 content assembly was designed for template skeletons. We're tackling one phase at a time — this session is **Phase 2 only**.

Read these files first to understand the current state:
- `docs/plans/phase1-v2-redesign/CHECKPOINT_PHASE1_V2_COMPLETE.md` — what was done, current scores, root causes
- `docs/plans/phase1-v2-redesign/BENCHMARK_BASELINE.md` — full benchmark scores with regression thresholds

## The Problem (Phase 2 only)

When running with `MULTIPASS_PHASE1_MODE=v2`, Phase 2 content assembly degrades the skeleton:
- **SSIM drops**: 0.7152 (skeleton) → 0.5933 (after Phase 2) — a -0.12 loss
- **Fewer slots**: 841 vs 1267 with template skeletons
- **Text fidelity**: 0.60 (below 0.70 threshold)

With the template path, Phase 2 IMPROVES the skeleton: 0.5851 → 0.7562 (+0.17 gain).

The content assembler and content pattern generators were built around template skeleton conventions. Claude's v2 skeleton uses different HTML structure and CSS classes.

## Task

Adapt Phase 2 content assembly so v2 skeletons gain quality through Phase 2 instead of losing it. Do NOT touch Phase 3 or Phase 4 — we'll handle those separately.

**Target scores after Phase 2 (InfiniteAge):**
- Phase 1 Skeleton SSIM: >= 0.70 (maintain, don't regress)
- Phase 2 Content SSIM: **>= 0.72** (currently 0.5933, template achieves 0.7562)
- Text fidelity: >= 0.70 (currently 0.60)
- Slots: >= 1000 (currently 841)

## Approach

Spin up multiple research sub-agents in parallel to investigate:

1. **Content Assembly Agent** — Read `multipass/content_assembler.py` (607 lines) and `multipass/content_patterns.py` (500 lines). Analyze why v2 skeletons produce fewer slots (841 vs 1267). The assembler fills `{{sec_N}}` / `{{sec_N_header}}` / `{{sec_N_items}}` placeholders — investigate whether Claude's skeleton HTML structure around these placeholders differs enough from templates that the assembler inserts less content. Check if content_patterns.py's structured HTML generators (using `mp-feature-card`, `mp-testimonial-card`, etc.) are compatible with v2 skeleton containers.

2. **Skeleton Structure Agent** — Read the v2 skeleton output at `test_multipass_snapshots/latest/phase_1_skeleton.html` and compare it to `multipass/section_templates.py` (464 lines). Map the differences: what CSS classes does Claude use vs templates? Where does Claude put placeholders in the DOM tree vs where templates put them? This tells us exactly what the assembler needs to adapt to.

3. **Pipeline Flow Agent** — Read `multipass/pipeline.py` and find the Phase 2 orchestration code (search for `phase_2` and `assemble_content`). Understand how the pipeline passes the v2 skeleton to the assembler and whether any context is lost in the handoff. Also check whether `use_templates_this_run = True` (set for v2) affects Phase 2 behavior correctly.

4. **Test Coverage Agent** — Read `tests/test_multipass_v4.py` to understand existing Phase 2 test coverage. We need to ensure any changes maintain 304+ tests passing and can be validated with `--visual` runs.

After the research agents report back, synthesize their findings into a plan. Use `/plan-workflow` to enter plan mode and design the Phase 2 adaptation.

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

Compare scores against `BENCHMARK_BASELINE.md`. The template path must NOT regress (final SSIM >= 0.72). Focus on Phase 2 Content SSIM reaching >= 0.72 with improving trajectory.
