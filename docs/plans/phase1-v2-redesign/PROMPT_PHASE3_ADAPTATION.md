# Phase 3/4 Adaptation Plan — Continuation Prompt

> Copy everything below the line into a new Claude Code session on branch `feat/ad-creator-v2-phase0`.

---

## Context & Mission

We're building a multipass landing page generation pipeline that converts scraped web pages into high-fidelity landing page recreations. The pipeline has 4 phases:

- **Phase 1**: Generate HTML/CSS skeleton from visual analysis (DONE — "Gemini Sees, Claude Builds")
- **Phase 2**: Fill skeleton with real content from the scraped page (DONE — adapted for v2)
- **Phase 3**: Per-section visual refinement via Gemini Vision (NEEDS ADAPTATION)
- **Phase 4**: Global patch pass for final polish (NEEDS ADAPTATION)

We have two Phase 1 modes: `template` (deterministic templates, the original path) and `v2` (Claude-generated bespoke skeletons, the new path). The v2 path produces better Phase 1 skeletons but Phase 3/4 are still optimized for template output.

**Your mission**: Determine whether we should continue squeezing Phase 2 or move to Phase 3/4 adaptation, then build and execute the plan. Use the data below to make a rigorous, evidence-based decision.

## Required Reading

Before doing ANYTHING else, read these files in this exact order:

1. `docs/plans/phase1-v2-redesign/CHECKPOINT_PHASE2_ADAPTATION_COMPLETE.md` — What was just completed, current scores, gap analysis
2. `docs/plans/phase1-v2-redesign/BENCHMARK_BASELINE.md` — Original baseline scores for regression detection
3. `docs/plans/phase1-v2-redesign/CHECKPOINT_PHASE1_V2_COMPLETE.md` — Phase 1 v2 context and architecture
4. `docs/plans/phase1-v2-redesign/PHASE2_ADAPTATION_PLAN.md` — What was done in Phase 2 adaptation and why

Then read the implementation files:

5. `viraltracker/services/landing_page_analysis/multipass/pipeline.py` — Core pipeline (2800+ lines). Focus on:
   - `_run_phase_3_refinement()` (~line 2406) — per-section Gemini Vision refinement
   - `_run_phase_4_patches()` (~line 2614) — global patch pass
   - `_fix_v2_skeleton_css()` (~line 1015) — the Phase 2 CSS fix (for context)
6. `viraltracker/services/landing_page_analysis/multipass/prompts.py` — All prompt builders. Focus on:
   - `build_phase_3_refinement_prompt()` (~line 233) — Phase 3 prompt
   - `build_phase_4_patch_prompt()` — Phase 4 prompt
7. `viraltracker/services/landing_page_analysis/multipass/patch_applier.py` — Phase 4 patch validation/application
8. `viraltracker/services/landing_page_analysis/multipass/content_assembler.py` — Phase 2 content assembly
9. `viraltracker/services/landing_page_analysis/multipass/content_patterns.py` — Pattern detection
10. `viraltracker/services/landing_page_analysis/multipass/section_templates.py` — Template system + shared CSS

## Current v2 Scores (What You're Improving)

### InfiniteAge v2 — SSIM by Phase

```
Phase 1 (skeleton):  0.7094  ← starts strong
Phase 2 (content):   0.6408  ← -0.069 drop (content assembly still degrades)
Phase 3 (refined):   0.6700  ← +0.029 lift (Phase 3 helps slightly)
Phase 4 (final):     0.6736  ← +0.004 lift (Phase 4 negligible)
Trajectory: improving (was regressing before Phase 2 fix)
```

### Boba v2 — SSIM by Phase

```
Phase 1 (skeleton):  0.5888  ← lower starting point
Phase 2 (content):   0.5618  ← -0.027 drop (less degradation than before)
Phase 3 (refined):   0.4281  ← -0.134 DROP (Phase 3 ACTIVELY HARMS this page)
Phase 4 (final):     0.5366  ← +0.109 recovery (Phase 4 partially compensates)
Trajectory: improving overall, but Phase 3 is destructive
```

### Template Path (Must Not Regress)

```
Phase 1: 0.5851 → Phase 2: 0.7562 → Phase 3: 0.7591 → Phase 4: 0.7596
Trajectory: improving (this is the healthy pattern we want v2 to match)
```

### Target Scores

| Metric | Current v2 (InfiniteAge) | Target |
|--------|-------------------------|--------|
| Phase 1 SSIM | 0.7094 | >= 0.70 (maintain) |
| Phase 2 SSIM | 0.6408 | >= 0.70 (neutral or positive) |
| Phase 3 SSIM | 0.6700 | >= 0.72 (consistent lift) |
| Final SSIM | 0.6736 | >= 0.78 (approach template quality) |
| Boba Phase 3 SSIM | 0.4281 | >= 0.55 (STOP the regression) |
| Text fidelity | 0.64 | >= 0.75 |
| Slots | 882 | >= 950 |
| SSIM trajectory | improving | improving (all phases) |

## Key Technical Facts

### Phase 3 Architecture
- Launches parallel Gemini Vision calls, one per section
- Each call gets: cropped screenshot of that section + section HTML + design system + image metadata
- Gemini returns refined HTML for that section
- Invariant checks after each: if check fails, original HTML is restored
- Phase 3 prompts are markup-agnostic (don't reference `mp-*` classes directly)
- BUT: the prompts assume certain skeleton conventions about placeholder naming and structure

### Phase 4 Architecture
- Single Gemini Vision call with complete HTML + full-page screenshot
- Returns max 15 JSON patches in restricted format: `css_fix`, `add_element`, `remove_element`
- Selector grammar is restricted: `[data-section='sec_N']`, `[data-slot='name']`, `.class`, `tag`
- Protected attributes: `data-slot`, `data-section` (never modified)
- Global invariant check: if any check fails, ALL patches reverted

### What's Different About v2 Skeletons
- Claude generates **custom CSS classes** (e.g., `mp-container-wide`, `mp-hero-text`) that only exist in its own `<style>` block
- CSS is now fixed (range values corrected, shared CSS appended) but Claude's custom class defs are preserved
- Section structure uses standard `<section data-section="sec_N">` containers (same as template)
- Placeholder naming follows the same contract: `{{sec_N}}`, `{{sec_N_header}}`, `{{sec_N_items}}`, etc.
- v2 skeletons tend to have more complex nested structure than templates

### Why Boba Phase 3 Regresses So Badly (-0.134 SSIM)
This is the most critical problem. Hypotheses:
1. Phase 3 Gemini prompts may be restructuring Claude's custom CSS/HTML in ways that break layout
2. Invariant checks may be passing but layout still degrading (checks verify slot/section attrs, not visual quality)
3. Per-section refinement may be removing or simplifying Claude's bespoke styling
4. Image handling differences between template and v2 skeletons

## Agent Team & Process

Spin up the following deep research agents in parallel BEFORE writing any plan. Each agent should be MIT-caliber — thorough, rigorous, citation-heavy, with specific file:line references.

### Agent 1: LLM Prompt Engineering Expert
**Task**: Analyze Phase 3 and Phase 4 prompts (`prompts.py`) for v2 compatibility issues.
- Read the full Phase 3 and Phase 4 prompt builder functions
- Identify any assumptions about HTML structure that break with v2 skeletons
- Analyze whether the prompts guide Gemini to preserve vs restructure custom CSS
- Propose specific prompt modifications that would make Phase 3/4 v2-aware
- Check if Phase 3 per-section screenshots are captured correctly for v2 layout
- Evaluate whether the design_system context given to Gemini is sufficient for v2

### Agent 2: Software Architecture Expert
**Task**: Analyze the Phase 3/4 pipeline code (`pipeline.py`) for v2 adaptation points.
- Map the full Phase 3 flow: screenshot capture → prompt construction → Gemini call → invariant check → merge
- Map the full Phase 4 flow: full screenshot → prompt → patch generation → validation → application
- Identify where v2-specific branching would be needed vs universal fixes
- Analyze the invariant checking system — is it catching layout regressions or just structural integrity?
- Look at error handling and fallback paths in Phase 3/4
- Assess whether Phase 3's section-cropping correctly handles v2's different padding/spacing
- Check the `_strip_unresolved_placeholders()` interaction with Phase 3/4

### Agent 3: QA & Metrics Expert
**Task**: Analyze the scoring/diagnostic infrastructure and design a measurement framework.
- Read `phase_diagnostics.py` — understand all metrics tracked per phase
- Analyze how SSIM is calculated — is it per-section or full-page? How are screenshots compared?
- Determine why Phase 3 HELPS InfiniteAge (+0.029) but DESTROYS Boba (-0.134)
- Look at the visual test runner (`scripts/test_multipass_local.py`) — how are screenshots captured?
- Propose per-section SSIM tracking to identify WHICH sections Phase 3 helps vs harms
- Design acceptance criteria: what scores constitute "done" for Phase 3/4 adaptation?
- Look at existing test coverage (`tests/test_multipass_v4.py`) — what Phase 3/4 tests exist?

### Agent 4: Web Development & CSS Expert
**Task**: Analyze the CSS/HTML differences between template and v2 output.
- Read actual v2 skeleton output: `test_multipass_snapshots/latest/phase_1_skeleton.html`
- Read actual Phase 2 output: `test_multipass_snapshots/latest/phase_2_content.html`
- Read actual Phase 3 output: `test_multipass_snapshots/latest/phase_3_refined.html`
- Compare Phase 2 → Phase 3 HTML diff to see what Gemini changes
- Look at `_build_shared_css()` in section_templates.py — does the appended CSS conflict with Claude's CSS?
- Analyze CSS specificity issues: does shared CSS accidentally override Claude's custom styles?
- Check if responsive breakpoints in shared CSS conflict with v2 skeleton's breakpoints
- Identify CSS fixes that would improve rendering without touching the LLM prompts

## Decision Framework

After all agents report back, synthesize their findings into a decision:

### Option A: Continue Phase 2 Optimization
Choose this if agents find that Phase 2 content assembly has significant untapped improvement (>= 0.05 SSIM gain available) AND Phase 3/4 issues are mostly prompt-level (easy to fix later).

### Option B: Move to Phase 3/4 Adaptation
Choose this if agents find that Phase 3 is actively destroying quality (confirmed by Boba's -0.134 drop) and the fixes are structural (not just prompt tweaks). This is the expected recommendation.

### Option C: Hybrid — Quick Phase 2 Wins + Phase 3/4 Focus
Choose this if agents identify 1-2 quick Phase 2 wins (< 20 lines each) that can be done alongside Phase 3/4 work.

## Constraints

- **Branch**: Continue on `feat/ad-creator-v2-phase0`
- **Template path must not regress**: All changes must be v2-specific or additive
- **Unit tests**: 313 currently pass. Add tests for new functionality. Never drop below 313.
- **Feature flag**: `MULTIPASS_PHASE1_MODE=v2` gates all v2 behavior
- **No Phase 1 changes**: Phase 1 v2 is done
- **Verification after each milestone**:
  ```bash
  # v2 on InfiniteAge
  MULTIPASS_PHASE1_MODE=v2 PYTHONPATH=. python3 scripts/test_multipass_local.py \
    --url "infiniteage.com/pages/sea-moss-for-hair-growth" --visual

  # v2 on Boba (critical — Phase 3 regression must be fixed)
  MULTIPASS_PHASE1_MODE=v2 PYTHONPATH=. python3 scripts/test_multipass_local.py \
    --url "bobanutrition.co" --visual

  # Template baseline (must not regress)
  MULTIPASS_PHASE1_MODE=template PYTHONPATH=. python3 scripts/test_multipass_local.py \
    --url "infiniteage.com/pages/sea-moss-for-hair-growth" --visual

  # Unit tests
  python3 -m pytest tests/test_multipass_v4.py -x -q
  ```

## Deliverables

1. **Decision document**: Which option (A/B/C) and why, with agent findings as evidence
2. **Milestone plan**: Ordered list of changes with expected impact per milestone
3. **Implementation**: Code changes following the plan
4. **Checkpoint**: `CHECKPOINT_PHASE3_ADAPTATION_COMPLETE.md` with before/after scores
5. **Updated regression thresholds** in the checkpoint

## Use `/plan-workflow` After Research

After the 4 agents complete their research, synthesize findings and use `/plan-workflow` to create the formal plan. Then implement milestone by milestone, testing after each.
