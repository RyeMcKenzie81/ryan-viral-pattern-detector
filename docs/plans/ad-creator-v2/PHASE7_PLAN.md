# Phase 7: Winner Evolution + Experimentation — Implementation Plan

**Branch**: `feat/ad-creator-v2-phase0`
**Created**: 2026-02-15
**Status**: 7A COMPLETE — 7B planning
**Parent Plan**: `docs/plans/ad-creator-v2/PLAN.md` Sections 11 & 12

> **Sub-phasing**: Phase 7 splits into 7A (Winner Evolution) and 7B (Experimentation Framework), each with separate checkpoints and gates. 7A ships first; 7B follows.

---

## Phase 1: INTAKE

### 1.1 Original Request

Build the Winner Evolution System (Section 11) and Experimentation Framework (Section 12) from the Ad Creator V2 plan. Phase 6 (Creative Genome) provides the learning loop foundation — Phase 7 acts on that knowledge.

### 1.2 Scope Decision

**7A — Winner Evolution Core** (this plan):
- `ad_lineage` table for parent→child tracking
- Winner detection criteria (reward_score, CTR, ROAS thresholds)
- 3 evolution modes: Winner Iteration (a), Anti-Fatigue Refresh (c), Cross-Size Expansion (d)
- `WinnerEvolutionService` with variable selection via information-gain weighted Thompson Sampling
- "Evolve This Ad" UI (button on ad cards with performance data)
- `winner_evolution` scheduler job type + worker handler
- Iteration limits: max 5 single-variable iterations per winner, max 3 rounds on same ancestor

**7B — Experimentation Framework** (separate plan, after 7A ships):
- Experiment tables (experiments, experiment_arms, causal_effects)
- Experiment design + Bayesian winner declaration
- 7B proceeds with manual Meta deployment. System generates setup instructions; user deploys and links IDs back.

### 1.3 Clarifying Questions

| # | Question | Answer |
|---|----------|--------|
| 1 | End result? | Given a winning ad, systematically generate evolved variants that change one variable at a time, refresh fatiguing winners, and expand winners to untested sizes. |
| 2 | Triggers? | "Evolve This Ad" button (UI), or scheduled `winner_evolution` job (worker-first) |
| 3 | Inputs? | Parent ad ID + evolution mode (+ optional variable override for winner_iteration) |
| 4 | Outputs? | New generated_ads linked to parent via `ad_lineage`, submitted through normal V2 pipeline |
| 5 | Error cases? | Parent doesn't meet winner criteria, iteration limit exceeded, parent ad image not in storage, pipeline generation failure |
| 6 | Chat-routable? | No — UI and scheduler only |
| 7 | Scope split? | 7A = Winner Evolution (a, c, d). 7B = Experimentation. Separate gates. |
| 8 | Meta API ready? | No — only read access (performance sync). Experiment deployment is 7B scope. |
| 9 | Lineage approach? | New `ad_lineage` table (not extending generated_ads columns). |

### 1.4 Success Criteria

- [ ] Evolved ads can be generated from winners via UI button or scheduled job
- [ ] `ad_lineage` tracks parent→child with evolution mode, variable changed, iteration round
- [ ] Iteration limits enforced (max 5 per winner, max 3 rounds on ancestor)
- [ ] Anti-fatigue refresh triggers for ads approaching fatigue thresholds
- [ ] Cross-size expansion generates winner in all untested sizes
- [ ] Winner Iteration uses information-gain weighted variable selection
- [ ] All evolution runs go through V2 pipeline (worker-first)
- [ ] **Success metric**: evolved ads outperform parents >50% of the time (measured post-launch)

### 1.5 Phase 1 Approval

- [ ] User confirmed requirements
- [ ] Scope (7A only, modes a/c/d) confirmed

---

## Phase 2: ARCHITECTURE DECISION

### 2.1 Workflow Type

**Chosen**: Python service + scheduler job (NOT pydantic-graph)

**Reasoning**:

| Question | Answer |
|----------|--------|
| Who decides what happens next? | **Deterministic rules** — winner criteria, variable selection, iteration limits are all algorithmic |
| Autonomous or interactive? | **Both** — UI triggers evolution, worker executes it |
| Needs pause/resume? | **No** — evolution submits V2 pipeline jobs which handle their own lifecycle |
| Complex branching? | **No** — mode selection is a simple switch, then delegates to V2 pipeline |

The evolution service is a **job builder** that wraps `run_ad_creation_v2()`. It:
1. Validates winner criteria and iteration limits
2. Determines what to change (variable selection)
3. Builds V2 pipeline parameters with the change applied
4. Calls `run_ad_creation_v2()` (or submits as scheduler job)
5. Records lineage entries after pipeline completion

No pydantic-graph needed — this is orchestration logic, not an AI-driven workflow.

### 2.2 High-Level Flow

```
"Evolve This Ad" button (UI)
    ↓
WinnerEvolutionService.get_evolution_options(ad_id)
    → Returns available modes based on element_tags + performance + iteration limits
    ↓
User selects mode → creates scheduled_job(job_type='winner_evolution')
    ↓
Worker picks up job → execute_winner_evolution_job()
    ↓
WinnerEvolutionService.evolve_winner(parent_ad_id, mode, variable_override=None)
    ├── 1. Load parent ad + element_tags
    ├── 2. Validate winner criteria (reward_score >= 0.65 OR top-quartile CTR/ROAS)
    ├── 3. Check iteration limits (max 5 per winner, max 3 on ancestor)
    ├── 4. Select variable to change (information-gain weighted Thompson Sampling)
    ├── 5. Build V2 pipeline params with change applied
    ├── 6. Call run_ad_creation_v2() → generates new ads
    └── 7. Record ad_lineage entries (parent → each child)
    ↓
Result: New ads in generated_ads, linked via ad_lineage table
```

### 2.3 Evolution Mode Details

#### Mode a: Winner Iteration (Single Variable Testing)

**Input**: Parent ad ID
**Logic**:
1. Load parent's `element_tags` from `generated_ads`
2. Select variable to change via `select_evolution_variable()`:
   - For each tracked element, compute information gain = uncertainty(Beta(α,β)) × priority_weight
   - Priority weights: hook_type (0.9), awareness_stage (0.85), template_category (0.6), color_mode (0.4)
   - Pick element with highest information gain
3. For the selected element, use Thompson Sampling to pick a NEW value (different from parent's)
4. Build V2 pipeline params:
   - `reference_ad_base64` = parent's generated image (from storage)
   - `template_id` = parent's template (unless template_category is the variable)
   - `content_source` = "hooks" (with single selected hook, unless hook_type is the variable)
   - `canvas_sizes` = parent's size (unless canvas_size is the variable)
   - `color_modes` = parent's mode (unless color_mode is the variable)
   - `num_variations` = 1 (one variation per evolution)
5. Submit V2 pipeline with overridden param

#### Mode c: Anti-Fatigue Refresh

**Input**: Parent ad ID (must be approaching fatigue)
**Logic**:
1. Verify fatigue signals via `FatigueDetector` (frequency > 2.5 or CTR decline trend)
2. Keep identical: hook_text, belief angle, CTA, persona
3. Change: template_id (different template), color_mode (different palette)
4. Build V2 pipeline params:
   - `reference_ad_base64` = parent's image
   - `template_id` = different template (same template_category if possible)
   - `content_source` = "recreate_template" (injects parent's hook text)
   - `color_modes` = different from parent's
   - `canvas_sizes` = same as parent
   - `num_variations` = 3 (multiple fresh coats)
   - `additional_instructions` = "Maintain the same psychological approach and messaging. Only refresh the visual execution."

#### Mode d: Cross-Size Expansion

**Input**: Parent ad ID
**Logic**:
1. Look up which canvas_sizes already exist for this winner (via `ad_lineage` ancestor chain + `generated_ads`)
2. Determine untested sizes from: `["1080x1080px", "1080x1350px", "1080x1920px"]`
3. For each untested size, build V2 pipeline params:
   - `reference_ad_base64` = parent's image
   - `template_id` = parent's template
   - `content_source` = parent's content_source (preserve hook)
   - `canvas_sizes` = [untested_size]
   - `color_modes` = parent's color_mode
   - `num_variations` = 1
4. Run V2 pipeline for each untested size

### 2.4 Phase 2 Approval

- [ ] User confirmed architecture approach

---

## Phase 3: INVENTORY & GAP ANALYSIS

### 3.1 Existing Components to Reuse

| Component | Type | Location | How We'll Use It |
|-----------|------|----------|------------------|
| `CreativeGenomeService` | Service | `services/creative_genome_service.py` | Thompson Sampling for variable selection, reward lookups for winner criteria |
| `FatigueDetector` | Service | `services/ad_intelligence/fatigue_detector.py` | Detect fatigue signals for anti-fatigue refresh mode |
| `AdCreationService` | Service | `services/ad_creation_service.py` | Load parent ad data, get generated ad images |
| `run_ad_creation_v2()` | Pipeline | `pipelines/ad_creation_v2/orchestrator.py` | Execute generation for evolved variants |
| `TemplateScoringService` | Service | `services/template_scoring_service.py` | Select alternative templates for refresh mode |
| Scheduler Worker | Worker | `worker/scheduler_worker.py` | Route `winner_evolution` job type |
| `scheduled_jobs` table | DB | Existing | Store evolution jobs |
| `generated_ads` table | DB | Existing | Parent ad lookup, child ad storage |
| `creative_element_scores` | DB | Existing | Beta distributions for variable selection |
| `creative_element_rewards` | DB | Existing | Reward scores for winner criteria |

### 3.2 Database Evaluation

**Existing tables to use**:

| Table | Purpose in Phase 7A |
|-------|---------------------|
| `generated_ads` | Parent ad lookup (element_tags, storage_path, pre_gen_score); child ad storage |
| `creative_element_rewards` | Winner criteria check (reward_score >= 0.65) |
| `creative_element_scores` | Thompson Sampling for variable selection |
| `scheduled_jobs` | Evolution job scheduling |
| `scheduled_job_runs` | Job execution tracking |
| `meta_ads_performance` | Top-quartile CTR/ROAS checks |
| `ad_runs` | V2 pipeline run tracking |

**Existing lineage columns** (partial, not sufficient):
- `generated_ads.regenerate_parent_id` — only tracks retry regeneration
- `generated_ads.edit_parent_id` — only tracks smart edits

These don't capture evolution mode, variable changed, iteration round, or ancestor chains. Need dedicated table.

**New tables needed**:

| Table | Purpose | Collision Check |
|-------|---------|-----------------|
| `ad_lineage` | Parent→child evolution tracking with mode, variable, iteration | No collision (searched codebase) |

**New columns needed**:

| Column | Table | Purpose |
|--------|-------|---------|
| None | — | ad_lineage table captures all evolution metadata externally |

**Job type constraint update**:
- Add `'winner_evolution'` to `scheduled_jobs.job_type` CHECK constraint

### 3.3 New Components to Build

| # | Component | Type | Location | Purpose |
|---|-----------|------|----------|---------|
| 1 | `ad_lineage` table | Migration | `migrations/2026-02-15_winner_evolution.sql` | Parent→child lineage with evolution metadata |
| 2 | `WinnerEvolutionService` | Service | `services/winner_evolution_service.py` | Core logic: winner detection, variable selection, evolution execution, lineage recording |
| 3 | Worker handler | Worker | `worker/scheduler_worker.py` | `execute_winner_evolution_job()` + routing |
| 4 | UI: "Evolve This Ad" | UI | `ui/pages/` (TBD which page) | Button on ad cards, mode selection, job submission |
| 5 | Unit tests | Test | `tests/services/test_winner_evolution_service.py` | Test winner criteria, variable selection, iteration limits, lineage |

### 3.4 ad_lineage Table Design

```sql
CREATE TABLE IF NOT EXISTS ad_lineage (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),

    -- Lineage links
    parent_ad_id UUID NOT NULL REFERENCES generated_ads(id) ON DELETE CASCADE,
    child_ad_id UUID NOT NULL REFERENCES generated_ads(id) ON DELETE CASCADE,
    ancestor_ad_id UUID NOT NULL REFERENCES generated_ads(id) ON DELETE CASCADE,

    -- Evolution metadata
    evolution_mode TEXT NOT NULL,     -- winner_iteration, anti_fatigue_refresh, cross_size_expansion
    variable_changed TEXT,           -- hook_type, color_mode, canvas_size, template_category, awareness_stage (null for cross_size/refresh)
    variable_old_value TEXT,         -- parent's value for the changed variable
    variable_new_value TEXT,         -- child's value for the changed variable
    iteration_round INTEGER NOT NULL DEFAULT 1,  -- which round of evolution from ancestor

    -- Performance tracking
    parent_reward_score FLOAT,       -- parent's reward at time of evolution
    child_reward_score FLOAT,        -- populated after child matures (nullable)
    outperformed_parent BOOLEAN,     -- child reward > parent reward (nullable until matured)

    -- Tracking
    evolution_job_id UUID,           -- scheduled_job that triggered this
    created_at TIMESTAMPTZ DEFAULT NOW(),

    UNIQUE(parent_ad_id, child_ad_id)
);

-- Indexes for common queries
CREATE INDEX IF NOT EXISTS idx_ad_lineage_parent ON ad_lineage(parent_ad_id);
CREATE INDEX IF NOT EXISTS idx_ad_lineage_child ON ad_lineage(child_ad_id);
CREATE INDEX IF NOT EXISTS idx_ad_lineage_ancestor ON ad_lineage(ancestor_ad_id);
CREATE INDEX IF NOT EXISTS idx_ad_lineage_mode ON ad_lineage(evolution_mode);
```

### 3.5 WinnerEvolutionService API Design

```python
class WinnerEvolutionService:
    """Service for evolving winning ads into improved variants."""

    # --- Winner Detection ---
    async def identify_winners(self, brand_id: UUID) -> List[Dict]:
        """Find ads meeting winner criteria for a brand."""

    async def check_winner_criteria(self, ad_id: UUID) -> Dict:
        """Check if a specific ad meets winner criteria.
        Returns: {is_winner, reward_score, ctr_quartile, roas_quartile, days_matured, impressions}
        """

    # --- Evolution Options ---
    async def get_evolution_options(self, ad_id: UUID) -> Dict:
        """Get available evolution modes for an ad.
        Returns: {
            is_winner: bool,
            winner_details: {...},
            available_modes: [
                {mode: "winner_iteration", available: bool, reason: str, estimated_variants: int},
                {mode: "anti_fatigue_refresh", available: bool, reason: str, estimated_variants: int},
                {mode: "cross_size_expansion", available: bool, reason: str, estimated_variants: int, untested_sizes: [...]},
            ],
            iteration_count: int,
            iteration_limit: 5,
            ancestor_round_count: int,
            ancestor_round_limit: 3,
        }
        """

    # --- Variable Selection ---
    async def select_evolution_variable(
        self, brand_id: UUID, parent_element_tags: Dict
    ) -> Dict:
        """Select which variable to change using information-gain weighted Thompson Sampling.
        Returns: {variable: str, new_value: str, information_gain: float, all_candidates: [...]}
        """

    # --- Evolution Execution ---
    async def evolve_winner(
        self,
        parent_ad_id: UUID,
        mode: str,
        variable_override: Optional[str] = None,
    ) -> Dict:
        """Execute winner evolution: validate, select variable, run V2 pipeline, record lineage.
        Returns: {ad_run_id, child_ad_ids: [...], lineage_entries: int, mode, variable_changed}
        """

    # --- Iteration Limits ---
    async def check_iteration_limits(self, ad_id: UUID) -> Dict:
        """Check if evolution limits are reached.
        Returns: {can_evolve: bool, iteration_count: int, ancestor_round: int, reason: str}
        """

    # --- Lineage Recording ---
    async def record_lineage(
        self,
        parent_ad_id: UUID,
        child_ad_ids: List[UUID],
        ancestor_ad_id: UUID,
        mode: str,
        variable_changed: Optional[str],
        old_value: Optional[str],
        new_value: Optional[str],
        iteration_round: int,
        parent_reward: Optional[float],
        job_id: Optional[UUID] = None,
    ) -> int:
        """Record lineage entries for evolved ads. Returns count inserted."""

    # --- Lineage Queries ---
    async def get_lineage_tree(self, ad_id: UUID) -> Dict:
        """Get full lineage tree for an ad (ancestors and descendants)."""

    async def get_ancestor(self, ad_id: UUID) -> Optional[UUID]:
        """Find the root ancestor of an ad in the lineage chain."""

    # --- Performance Comparison ---
    async def update_evolution_outcomes(self, brand_id: UUID) -> Dict:
        """After child ads mature, compare to parent and update outperformed_parent.
        Returns: {updated: int, outperformed: int, underperformed: int}
        """
```

### 3.6 Phase 3 Approval

- [ ] User confirmed component list
- [ ] Database design approved
- [ ] Service API approved

---

## Phase 4: BUILD ORDER

### 4.1 Build Sequence

1. [ ] Migration: `ad_lineage` table + job type constraint update
2. [ ] Service: `WinnerEvolutionService` — winner detection + iteration limits
3. [ ] Service: `WinnerEvolutionService` — variable selection (information-gain weighted Thompson Sampling)
4. [ ] Service: `WinnerEvolutionService` — evolution execution (3 modes) + lineage recording
5. [ ] Worker: `execute_winner_evolution_job()` + routing
6. [ ] Tests: Unit tests for all service methods
7. [ ] UI: "Evolve This Ad" button + mode selection dialog
8. [ ] Post-plan review

### 4.2 Component Details

_(Filled in during Phase 4 implementation)_

---

## Phase 5: INTEGRATION & TEST

### 5.1 UI Validation Tests

| # | Test | Where | Priority |
|---|------|-------|----------|
| 1 | Run migration on Supabase | SQL editor | MUST |
| 2 | "Evolve This Ad" button appears for ads with performance data | Ad results UI | HIGH |
| 3 | Evolution options correctly show available/unavailable modes | Ad results UI | HIGH |
| 4 | Winner iteration creates evolved ad with one variable changed | Ad results UI → worker | HIGH |
| 5 | Cross-size expansion generates untested sizes | Ad results UI → worker | MEDIUM |
| 6 | Anti-fatigue refresh generates fresh variants | Ad results UI → worker | MEDIUM |
| 7 | Iteration limits block evolution after max iterations | Ad results UI | MEDIUM |
| 8 | Lineage tree viewable for evolved ads | Ad results UI | LOW |

---

## Phase 7A Post-Plan Review

**Verdict: PASS** (2026-02-15)

### Known Risks

| # | Severity | Location | Description |
|---|----------|----------|-------------|
| 1 | MEDIUM | `winner_evolution_service.py:116-117` | `except (ValueError, TypeError): pass` swallows datetime parse error. `days_matured` stays None — acceptable fallback but could mask data issues. |
| 2 | LOW | `migrations/2026-02-15_winner_evolution.sql:79` | `experiment_analysis` in CHECK constraint has no worker handler yet (Phase 7B scope). Unknown jobs hard-fail in worker — correct behavior. |
| 3 | LOW | UI pages | `asyncio.run()` for async service calls — consistent with existing codebase pattern (20+ other pages). |
| 4 | LOW | `winner_evolution_service.py:256` | `_check_top_quartile()` calls `genome._load_baselines()` (private method). Mild coupling — could break if CreativeGenomeService internals change. |
| 5 | LOW | `winner_evolution_service.py:515` | Anti-fatigue threshold `>= 2.5` matches `FatigueDetector.FREQUENCY_WARNING` but is a separate hardcoded constant. No shared constant. |

### Nice-to-Have Improvements (deferred)

- Add unit tests for `identify_winners()`, `get_evolution_options()`, and the three `_evolve_*` execution methods
- Extract fatigue threshold (2.5) to a shared constant with FatigueDetector
- Replace `genome._load_baselines()` call with a public method on CreativeGenomeService

---

## Questions Log

| Date | Question | Answer |
|------|----------|--------|
| 2026-02-15 | Sub-phase or single? | Sub-phases: 7A (evolution), 7B (experiments) |
| 2026-02-15 | Which evolution modes? | a (iteration), c (anti-fatigue), d (cross-size) |
| 2026-02-15 | Meta API ready? | No, read-only. 7B deferred. |
| 2026-02-15 | Lineage approach? | New `ad_lineage` table |

---

## Phase 7B Post-Plan Review

**Verdict: PASS** (2026-02-16)

All 3 blocking issues fixed during review. 32 unit tests passing.

### 7B Files Changed

**New (4):**
- `migrations/2026-02-16_experimentation_framework.sql` — 4 tables with CHECK constraints, partial unique indexes
- `viraltracker/services/experiment_service.py` — Full service: CRUD, arms, guards, power analysis, Meta linking, Bayesian analysis, causal effects
- `viraltracker/ui/pages/36_🧪_Experiments.py` — 3-tab UI: Active, Completed, Create New (6-step wizard)
- `tests/services/test_experiment_service.py` — 32 unit tests covering all pure functions

**Modified (5):**
- `viraltracker/worker/scheduler_worker.py` — +`execute_experiment_analysis_job()` handler
- `viraltracker/ui/nav.py` — +experiments page entry + superuser feature flag
- `viraltracker/services/feature_service.py` — +`EXPERIMENTS` FeatureKey + enable_all_features()
- `viraltracker/services/winner_evolution_service.py` — +`get_causal_priors()` + causal boost in variable selection
- `docs/plans/ad-creator-v2/PHASE7_PLAN.md` — Updated 7B description

### 7B Known Risks

| # | Severity | Location | Description |
|---|----------|----------|-------------|
| 1 | MEDIUM | `experiment_service.py:_fetch_arm_performance` | Performance lookup relies on `meta_ads` table mapping adset→ad. If a brand's Meta sync hasn't run recently, performance data may be stale or missing. |
| 2 | MEDIUM | `experiment_service.py:run_analysis` | Auto-transition from running→analyzing could race with manual UI actions if two analysis runs fire concurrently. Mitigated by idempotent upsert + debug logging on transition skip. |
| 3 | LOW | `experiment_service.py:_z_score` | Uses Abramowitz & Stegun rational approximation (~4.5e-4 accuracy). Sufficient for power analysis but not for extreme tail probabilities. |
| 4 | LOW | UI page `36_Experiments.py` | `asyncio.run()` for async service calls — consistent with existing codebase pattern (20+ other pages). |
| 5 | LOW | `experiment_service.py:compute_required_sample_size` | Bonferroni correction is conservative for multi-arm experiments. Could over-estimate sample size for 3-4 arm experiments. Acceptable for budget safety. |
| 6 | LOW | DB schema | No `organization_id` on `experiments` or `causal_effects` tables. Relies on `brand_id → brands.organization_id` join for multi-tenant filtering. Consistent with existing tables (e.g., `ad_lineage`). |

### 7B Nice-to-Have Improvements (deferred)

- Add mocked integration tests for `transition_status` gate logic (complex conditional branches)
- Add mocked tests for `declare_winner`, `run_analysis`, `link_arm_to_meta`
- Add tests for `get_causal_priors` and worker handler
- Consider Holm-Bonferroni step-down correction (less conservative than Bonferroni) for multi-arm power analysis
- Extract `asyncio.run()` into a shared helper across UI pages

### 7B Deferred UI Tests (perform after Phase 8)

| # | Test | Page / Tab | What to Verify |
|---|------|-----------|----------------|
| 1 | Non-Meta brand guard | `36_Experiments.py` (all tabs) | Warning shows and page stops when brand has no Meta ad account |
| 2 | Create wizard step 1 | Create New → Hypothesis | Name, hypothesis, test_variable selectbox, optional product picker all render; "Next" disabled until name+hypothesis filled |
| 3 | Create wizard step 2 | Create New → Arms | Add/remove arms, max 4 enforced, only 1 control allowed, "Next" disabled until >= 2 arms with 1 control |
| 4 | Create wizard step 3 | Create New → Protocol | method_type, budget_strategy, randomization_unit, audience_rules, min/max days, hold_constant all persist across navigation |
| 5 | Power analysis gating | Create New → Power Analysis | Power analysis must run before "Next" is enabled; results show impressions/arm, budget/arm, estimated days |
| 6 | Deployment checklist | Create New → Deploy Checklist | Budget from power analysis appears in step 3 instructions; all arms listed with variable values |
| 7 | Meta ID linking validation | Create New → Link Meta IDs | Same-account, same-campaign, no-duplicate adset checks surface errors; "Validate & Activate" only enabled when all arms + campaign linked |
| 8 | Active tab — P(best) bars | Active Experiments | Running experiment shows P(best) progress bars per arm, decision badge, days running |
| 9 | Active tab — Declare Winner | Active Experiments | "Declare Winner" button appears only when decision='winner'; clicking concludes experiment and moves to Completed |
| 10 | Active tab — Mark Inconclusive | Active Experiments | "Mark Inconclusive" appears for futility/inconclusive decisions; clicking concludes experiment |
| 11 | Completed tab — outcomes | Completed | Concluded experiments show winner name or inconclusive badge, quality grade |
| 12 | Causal Knowledge Base | Completed | Effects table shows ATE, CI, grade; filters by product and variable work |
| 13 | Worker skip behavior | Manual trigger | `experiment_analysis` job for non-Meta brand completes with `skipped=True, reason="no_ad_account_linked"` |

### 7B Blocking Issues Fixed During Review

| # | Check | Issue | Fix |
|---|-------|-------|-----|
| 1 | G1 | `FeatureKey.EXPERIMENTS` missing from superuser dict in `nav.py` | Added to superuser "all" features dict |
| 2 | G1 | `FeatureKey.EXPERIMENTS` missing from `enable_all_features()` in `feature_service.py` | Added to all_features list |
| 3 | G2 | `except ValueError: pass` swallowed auto-transition error in `run_analysis()` | Replaced with `logger.debug()` |

---

## Change Log

| Date | Phase | Change |
|------|-------|--------|
| 2026-02-15 | 1 | Initial plan created (Phase 7A scope) |
| 2026-02-15 | 4-5 | 7A code complete: migration, service, worker, UI, 39 tests |
| 2026-02-15 | Review | Post-plan review PASS — fixed unused imports, added risk log |
| 2026-02-16 | 7B | 7B code complete: migration, service, worker, UI, 32 tests. Post-plan review PASS after 3 fixes. |
