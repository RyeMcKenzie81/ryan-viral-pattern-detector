# Checkpoint: Planning Complete

**Date:** 2026-05-25
**Branch:** `RyeMcKenzie81/angle-driven-ad-creator`
**Status:** All planning artifacts produced and approved. Ready for implementation.

---

## What we did this session

Three skill runs back-to-back: `/office-hours` → `/plan-eng-review` → prompt draft.

### `/office-hours` (Approach D approved)

Reframed AC2 from template-first to angle-first. Codex outside voice reframed the work as "experimentation architecture, not copywriting" — the angle is the top-level testable hypothesis, hooks/templates/fatigue become implementation detail.

Settled on **Approach D** (B + in-batch hook diversity guardrail with cross-angle similarity logging). Falsifiability built in: at 30 days, compare intra-angle vs cross-angle hook similarity to decide whether V2 needs angle→template fit logic (P4).

Two-round adversarial spec review converged to ~9/10 quality. Doc approved.

**Artifact:** `~/.gstack/projects/RyeMcKenzie81-ryan-viral-pattern-detector/ryemckenzie-RyeMcKenzie81-angle-driven-ad-creator-design-20260525-132236.md`

### `/plan-eng-review` (12 implementation decisions locked)

| ID | Decision |
|----|----------|
| 1A (revised) | `belief_angles.jtbd_framed_id` becomes nullable; generated angles store jtbd as text |
| 1B | Sequential hook gen, batched embedding calls in groups of 10 (10x latency cut) |
| 1C | Two distinct run IDs: `belief_angles.angle_generation_run_id` + `generated_ads.ad_creation_run_id` (FK to scheduled_jobs.id) |
| 1D | HNSW index on `generated_ads.hook_embedding` (not ivfflat) |
| 1E | Separate Streamlit page `22_🎯_Generate_Angles.py` + deep-link to AC2 |
| 2A | Retry loop lives in `HookDiversityChecker.generate_with_diversity()` |
| 2A.1 | `INTRA_ANGLE_THRESHOLD` hardcoded default 0.85 + system_settings override |
| 2B | `AngleGeneratorService` writes directly to `belief_angles` (skips angle_candidates) |
| 3A | No LLM eval suite for V1; manual review via baseline assignment |
| 3B | One E2E test for the happy path; diversity-rejection + re-generation E2Es are fast-follows |
| M1 | Use **Claude Opus 4.7** via `viraltracker/core/config.py` constant (don't hardcode) |
| OV-4 | Migration preamble: `CREATE EXTENSION IF NOT EXISTS vector;` |
| UX-1 | Consolidate AC2 content_source dropdown from 4 modes to 3 (deprecate `belief_first`, fold into `angles`) |

**Critical gap flagged for impl:** OpenAI rate-limit handling in `HookDiversityChecker.batched_embed` must wrap in try/except in the scheduler loop, mark batch as `status='incomplete'` rather than crash the scheduled job.

**Artifacts:**
- `docs/plans/angle-driven-ad-creator/PLAN.md` (implementation plan with GSTACK REVIEW REPORT)
- `~/.gstack/projects/.../eng-review-test-plan-20260525-134500.md` (consumed by `/qa` later)

### Prompt draft

`AngleGeneratorService` system prompt + user prompt template drafted, reviewed, two changes incorporated:
- **Rule #3** loosened from hard "no shared desire AND villain" to soft "spread or differentiation across N, never two sharing desire AND villain AND identity arc" (accounts for narrow product categories)
- **Rule #7** (safest→exploratory ordering) kept but added to TODOS.md for review after 5–10 production batches

**Artifact:** `docs/plans/angle-driven-ad-creator/PROMPT_DRAFT.md`

### TODOS added (2)

1. **Review Rule #7** in angle generator prompt after 5–10 batches
2. **LLM Eval Suite** for AngleGeneratorService prompt (fast-follow after V1 produces golden examples)
3. **Angle Performance Dashboard** in Research Insights (was added in eng review; was already there)

### Preflights confirmed

- pgvector 0.8.0 installed on production Supabase ✓
- AC2 content_source dropdown audited (4 modes: `recreate_template`, `belief_first`, `plan`, `angles` — UX-1 consolidates to 3)
- `generated_ads.angle_id` already exists; just needs population
- `belief_angles.jtbd_framed_id` is NOT NULL FK to `belief_jtbd_framed` — Migration must drop NOT NULL

---

## What's still pending before code work

1. **Step 1b inputs:** Ryan picks the one (persona, offer_variant) to use for baseline extraction. Recommendation in chat: pick the combo where "wired but tired at 3am" repetition was worst in the last 2 weeks.
2. **3 handwritten stretch angles** for the chosen (persona, offer) — the strategic ceiling reference set. Pair with the 5–10 winning angles from Step 1b to form the 8–13 angle baseline that V1 must match.

These are user-side tasks; don't block code work on Step 1 baseline script implementation.

---

## Implementation order (from PLAN.md)

```
Day 1 (parallel, zero deps):
  Lane A: Step 1a (measure_hook_similarity_baseline.py)
  Lane A: Step 1b (extract_winning_angle_baselines.py)

Day 2-4:
  Step 2 (migration) → merge → deploy

Week 2 (parallel worktrees):
  Lane B: Step 3a (HookDiversityChecker) → Step 4 (scheduler ext) → Step 5b (AC2 mod)
  Lane C: Step 3b (AngleGeneratorService) → Step 5a (Generate Angles page)

Week 3 (converge):
  Step 6 (E2E happy-path test)
```

---

## Files to commit at this checkpoint

```
docs/plans/angle-driven-ad-creator/PLAN.md           (new)
docs/plans/angle-driven-ad-creator/PROMPT_DRAFT.md   (new)
docs/plans/angle-driven-ad-creator/CHECKPOINT_planning_complete.md   (new — this file)
TODOS.md                                              (modified — 2 new TODOs at top)
```

The design doc and test plan live under `~/.gstack/projects/` (not in repo, by design — they're personal workspace artifacts that travel with the user, not the codebase).

---

## Recommended next move

Commit these planning artifacts as one "planning complete" commit (clean separation from upcoming code commits), then start Step 1 baseline scripts as separate PR(s).

Reasoning: keeps the planning paper-trail reviewable on its own, makes the first code PR small and focused, lets you read Step 1 output before committing to schema migration in Step 2.
