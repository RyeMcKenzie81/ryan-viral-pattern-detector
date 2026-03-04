# Post-Plan Review Prompt — Phase 6: Creative Genome

Copy-paste this into a new Claude Code window:

---

Run the post-plan review for Phase 6 (Creative Genome) of Ad Creator V2. The implementation is complete on branch `feat/ad-creator-v2-phase0`.

## Instructions

1. **Read the review specs** from `agents/review/`:
   - `post_plan_review_orchestrator.md`
   - `graph_invariants_checker.md`
   - `test_evals_gatekeeper.md`

2. **Read the checkpoint** at `docs/plans/ad-creator-v2/CHECKPOINT_PHASE6.md` for a full list of changed files.

3. **Read the plan** at `docs/plans/ad-creator-v2/PLAN.md` Section 10 for the original requirements.

4. **Run Graph Invariants Checker** against all changed files:

   **New files:**
   - `migrations/2026-02-15_creative_genome.sql`
   - `viraltracker/services/creative_genome_service.py`
   - `tests/services/test_creative_genome_service.py`
   - `tests/pipelines/ad_creation_v2/test_element_tagging.py`

   **Modified files:**
   - `viraltracker/services/ad_creation_service.py` (save_generated_ad +element_tags, +pre_gen_score)
   - `viraltracker/services/template_scoring_service.py` (+PerformanceScorer, +PHASE_6_SCORERS, weight presets)
   - `viraltracker/pipelines/ad_creation_v2/state.py` (+performance_context field)
   - `viraltracker/pipelines/ad_creation_v2/models/prompt.py` (expanded PerformanceContext)
   - `viraltracker/pipelines/ad_creation_v2/nodes/generate_ads.py` (element_tags, pre_gen_score, performance_context)
   - `viraltracker/pipelines/ad_creation_v2/nodes/fetch_context.py` (genome context fetch)
   - `viraltracker/pipelines/ad_creation_v2/nodes/defect_scan.py` (element_tags passthrough)
   - `viraltracker/pipelines/ad_creation_v2/nodes/review_ads.py` (element_tags passthrough)
   - `viraltracker/pipelines/ad_creation_v2/nodes/retry_rejected.py` (element_tags, performance_context)
   - `viraltracker/pipelines/ad_creation_v2/services/generation_service.py` (performance_context wiring)
   - `viraltracker/worker/scheduler_worker.py` (+genome_update, +validation job handlers)
   - `tests/services/test_template_scoring_service.py` (updated weight preset assertions)

5. **Run Test/Evals Gatekeeper** against all changed files.

6. **Produce the consolidated report** — PASS/FAIL verdict, plan-to-code-to-coverage map, minimum fix set.

7. **Fix and rerun** until verdict is PASS.

8. After PASS, **commit all changes** with message: `feat: Ad Creator V2 Phase 6 — Creative Genome learning loop`

Test command: `/Users/ryemckenzie/projects/viraltracker/venv/bin/pytest tests/ --tb=short -q`

Note: 8 pre-existing test failures exist in `test_ad_creation_integration.py`, `test_belief_reverse_engineer.py`, `test_phase1_integration.py` — these are NOT caused by Phase 6.
