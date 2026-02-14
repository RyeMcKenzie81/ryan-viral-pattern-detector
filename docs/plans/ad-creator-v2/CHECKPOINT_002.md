# Ad Creator V2 — Checkpoint 002: Expert Review & Self-Improving Architecture

> **Date**: 2026-02-12
> **Status**: Expert review complete, Codex review integrated, PLAN.md updated
> **Follows**: CHECKPOINT_001 (planning complete, implementation not started)
> **PLAN.md**: Updated to v2 — includes all Codex P0/P1 fixes, incremental success gates, expert enhancements

---

## What Was Done This Session

Four parallel expert agents reviewed PLAN.md, CREATIVE_INTELLIGENCE.md, and CHECKPOINT_001.md against the full codebase. Each agent identified holes, proposed concrete additions, designed data architecture, and produced algorithm pseudocode.

### Expert Agents Deployed

| Agent | Specialization | Key Contribution |
|-------|---------------|------------------|
| 1 | **RL & Bandit Optimization** | Thompson Sampling bandit for element selection, reward signal architecture, cold-start strategy |
| 2 | **Computer Vision & Generative AI Quality** | 3-stage review pipeline, human feedback loop, visual embedding space, adaptive quality calibration |
| 3 | **Causal Inference & Experimentation** | A/B testing framework, stratified causal attribution, interaction effect detection, Bayesian stopping rules |
| 4 | **Production ML Systems** | Autonomous learning loop (Collect→Score→Apply→Validate), monitoring/alerting, prompt versioning, drift detection |

---

## Critical Holes Identified (Consensus Across Agents)

### 1. Section 10 (Creative Genome) Has No Learning Algorithm
All four agents flagged that Section 10 says "build a scoring model" with zero algorithmic detail. The phrase "aggregate by element tag" is purely correlational and will produce misleading results due to confounding (Simpson's Paradox — e.g., `curiosity_gap` hooks always paired with `problem_aware` audiences makes it impossible to isolate which caused good CTR).

### 2. No Human Feedback Loop
The plan expands AI review from 4 to 14 checks but all thresholds are static. No mechanism exists to record whether humans agree with AI decisions, and no path for thresholds to adapt over time. Without this, the 14-check system is just a more elaborate version of the same problem.

### 3. No Delayed Reward Handling
Conversions arrive 1-7 days after clicks. The plan doesn't specify when to "lock in" performance data. A newly deployed ad looks terrible on Day 1 but may be a winner by Day 7. No maturation window is defined.

### 4. No Experiment Design for Winner Evolution
Section 11 describes "single variable testing" but provides no framework for sample sizes, statistical stopping rules, or handling Meta's own ad rotation (which concentrates spend on predicted winners and starves other variants of data).

### 5. No Cold-Start Strategy
Every Phase 6-7 feature requires historical performance data. New brands get nothing for weeks. No cross-brand transfer learning, no proxy metrics, no progressive capability unlocking.

### 6. No Monitoring/Drift Detection
No mechanism to detect when the system is getting worse. No tracking of approval rate trends, prediction accuracy, or generation quality over time.

---

## Unified Enhancement Plan

Based on all four expert reports, here are the additions organized by phase. Each addition specifies the source agent(s) and integrates cleanly with the existing plan structure.

---

### NEW Section 6b: Human Feedback Loop & Adaptive Quality Scoring
**Source**: Agent 2 (CV & Quality)
**Phase**: 4 (alongside Review Overhaul)

Every AI review decision can be overridden by a human:
- "Override Approve" on a rejected ad
- "Override Reject" on an approved ad
- "Confirm" — AI was correct

**Three-tier learning system:**

1. **Tier 1: Override Tracking** — `ad_review_overrides` table records every human decision with per-check granularity.

2. **Tier 2: Threshold Calibration** — Weekly cron job computes per-check false positive/negative rates from override data. Adjusts thresholds to minimize weighted error (false negatives weighted 2x — bad ads reaching production is worse than over-rejecting). Produces new config version requiring human approval before activation.

3. **Tier 3: Few-Shot Exemplar Library** — Maintain 20-30 curated "calibration ads" per brand (10 gold-approve, 10 gold-reject, 5-10 edge cases). Review prompts inject 3-5 most similar exemplars via embedding similarity. Teaches the LLM the brand's quality bar without model training.

---

### NEW Section 9f: Gemini Failure Detection Pipeline (Fast Pre-Filter)
**Source**: Agent 2 (CV & Quality)
**Phase**: 4 (alongside Review Overhaul)

**3-Stage Review Pipeline replacing current dual-review:**

```
Stage 1: FAST DEFECT SCAN (~$0.002, Gemini 3 Flash)
  5 binary checks: TEXT_GARBLED, ANATOMY_ERROR, PHYSICS_VIOLATION,
  PACKAGING_TEXT_ERROR, PRODUCT_DISTORTION
  If ANY critical defect → auto-reject, skip Stages 2-3
  Expected to catch ~40% of rejections at 1/5 the cost

Stage 2: FULL QUALITY REVIEW (~$0.005, Gemini 3 Pro or Claude)
  14-check rubric (single reviewer)
  Only runs if Stage 1 passed

Stage 3: SECOND OPINION (conditional, ~$0.005)
  Only runs if Stage 2 borderline (any check 5.0-7.0)
  Uses the other AI model
  OR logic still applies

Net effect: ~30% cost reduction in review spend.
V1: ~$0.010/ad review → V2: ~$0.007/ad average
```

---

### ENHANCED Section 10: Performance Feedback Loop (Creative Genome)
**Source**: Agents 1, 3, 4 (all three)

Replace the current vague description with a concrete architecture:

#### 10.1 Reward Signal Architecture (Agent 1)

**Composite reward score** (not single metric):
```
reward_score = w_ctr * normalized_ctr + w_conv * normalized_conv + w_roas * normalized_roas

Weights by campaign objective:
  CONVERSIONS:      w_ctr=0.2, w_conv=0.3, w_roas=0.5
  TRAFFIC:          w_ctr=0.7, w_conv=0.1, w_roas=0.2
  BRAND_AWARENESS:  w_ctr=0.5, w_cpm=0.5
```

Metrics normalized to [0,1] using brand's existing `ad_intelligence_baselines` percentiles.

**Maturation windows** before ingesting rewards:
| Metric | Maturation Days | Min Impressions |
|--------|:-:|:-:|
| CTR | 3 | 500 |
| Conversion Rate | 7 | 500 |
| ROAS | 10 | 500 |

#### 10.2 Thompson Sampling for Element Selection (Agent 1)

Each element-value pair (e.g., `hook_type=curiosity_gap`) maintains a **Beta(alpha, beta)** distribution.

- "Good" threshold: reward_score >= 0.5 → increment alpha; else increment beta
- To select next hook_type: sample Beta(α,β) for each option, pick highest sample
- Independent Beta distributions per element dimension (not full combinatorial space)
- Reduces action space from millions of combos to ~50 independent arms

**Why Thompson Sampling over alternatives:**
| Algorithm | Verdict |
|-----------|---------|
| UCB1 | Over-explores in high-dimensional spaces |
| Contextual Bandits (LinUCB) | Requires matrix ops outside Postgres |
| **Thompson Sampling** | Natural exploration/exploitation, handles sparse data, easy Beta updates in Postgres |

#### 10.3 Cold-Start Strategy (Agents 1, 4)

Four-level progression:

| Level | Timeframe | Strategy |
|-------|-----------|----------|
| 0 | Day 0 | Cross-brand category priors (aggregate α/β across same-category brands, 0.3x shrinkage) |
| 1 | Days 1-14 | Proxy metrics (CTR, CPC — available faster than conversions) |
| 2 | Days 14-30 | Blended scores: `brand_weight = min(brand_sample/100, 0.8)` |
| 3 | Day 30+ | Full brand-specific scores, prior_n drops to 10 |

Accelerated exploration: first 30 ads force 30% random element selection.

#### 10.4 Exploration vs Exploitation Schedule (Agent 1)

```
exploration_boost = max(0.05, 0.30 * exp(-total_matured_ads / 100))
```
- 0 matured ads: 30% forced exploration
- 100 ads: ~11%
- 500+ ads: 5% floor

#### 10.5 Stratified Attribution (Agent 3, replacing naive aggregation)

**Do NOT use simple "avg CTR by element tag"** — this is Simpson's Paradox waiting to happen.

Instead, use stratified comparison (Cochran-Mantel-Haenszel approach):
1. Group ads into strata: (awareness_stage × audience_type × spend_bucket × week)
2. Within each stratum, compare element performance
3. Only report effects consistent across 3+ strata
4. Flag effects that reverse across strata (Simpson's Paradox detection)

Label all non-experimental findings as "correlational" in the UI.

#### 10.6 Feedback Loop Cycle (Agent 4)

```
COLLECT (daily, post meta_sync)
  → Auto-compute element-tag aggregates for ads with new perf data
  → Backfill element_tags for V1 ads from ad_runs.parameters

SCORE (weekly, new job: creative_genome_update)
  → Bayesian-averaged element scores per dimension
  → Update Thompson Sampling α/β values
  → Compute element combos for 2-3 element combinations

APPLY (generation time, inline)
  → Query element scores → inject advisory context into prompt
  → Compute pre_gen_score → store on generated_ads
  → Thompson Sampling selects preferred elements

VALIDATE (weekly, new job: genome_validation)
  → Correlation(pre_gen_score, actual_ctr) over 14-day lag
  → If accuracy < 0.3 for 3 consecutive weeks → alert + stale flag
```

---

### NEW Section 12: Experimentation Framework
**Source**: Agent 3 (Causal Inference)
**Phase**: 6 (alongside Creative Genome)

#### 12a. Experiment Structure

Every creative test is an `experiment` record with:
- Hypothesis, test variable (exactly ONE element), control arm, 1-3 treatment arms
- Hold-constant set (all other element_tags fixed)

#### 12b. Meta Deployment Strategy

**Deploy as separate ad sets with identical targeting to prevent Meta's intra-ad-set MAB from confounding results:**
- Dedicated CBO campaign per experiment
- One ad set per arm, identical targeting/bid/placements
- Equal minimum spend limits (forces balanced allocation)
- One ad per ad set

#### 12c. Bayesian Winner Declaration

Daily posterior updates using Beta-Binomial model for CTR:
- P(best) computed via 10K Monte Carlo samples
- **Winner**: P(best) > 0.90 AND all arms met min impressions
- **Futility**: P(best) < 0.05 → recommend pausing arm
- **Inconclusive**: max_days reached without clear winner

Budget-gate every experiment: compute required spend before proposing.

#### 12d. Causal Knowledge Base

Each completed experiment stores its ATE (average treatment effect) with confidence intervals in `causal_effects` table. Over time, this builds reliable knowledge for the variable selection algorithm.

---

### ENHANCED Section 11: Winner Evolution (Concrete Triggers)
**Source**: Agents 1, 3

Replace vague "winning ad" with concrete criteria:
```python
WINNER_CRITERIA = {
    "min_matured_days": 7,
    "min_impressions": 1000,
    "min_reward_score": 0.65,  # Above 65th percentile
    "or_conditions": [
        {"metric": "link_ctr", "threshold": "p75"},
        {"metric": "roas", "threshold": "p75"},
    ]
}
```

**Iteration limits:** Max 5 single-variable iterations per winner. Max 3 rounds on same ancestor.

**Variable selection algorithm** (Information-Gain Weighted Thompson Sampling):
1. For each untested variable, compute "expected information gain" from causal knowledge + genome data
2. Multiply by strategic weight (belief_angle=1.0, hook_type=0.9, color_mode=0.4)
3. Add noise proportional to uncertainty, pick highest

---

### NEW Section 13: Visual Embedding Space
**Source**: Agent 2 (CV & Quality)
**Phase**: 6-7

Use Gemini 3 Flash to extract structured visual descriptors → embed with OpenAI text-embedding-3-small → store in pgvector (reuses existing infrastructure).

**Visual descriptor**: dominant_colors, color_temperature, composition_type, text_density, visual_style, subject_position, negative_space_ratio, mood

**Use cases:**
1. Duplicate detection (cosine > 0.95)
2. Style clustering (DBSCAN → correlate with performance)
3. Diversity enforcement (reject if cosine > 0.90 with batch siblings)
4. "More like this" for Winner Evolution

---

### NEW Section 14: Monitoring & Alerting
**Source**: Agent 4 (Production ML)
**Phase**: 6

| Metric | Warning | Critical |
|--------|---------|----------|
| approval_rate | < 0.60 for 7 days | < 0.40 for 3 days |
| prediction_accuracy | < 0.3 for 2 weeks | < 0.1 for 1 week |
| generation_success_rate | < 0.80 | < 0.60 |
| data_freshness | > 3 days | > 7 days |
| winner_rate (V2 ads > brand median) | < 0.10 for 3 weeks | N/A |

Computed by `genome_validation` weekly batch. Stored in `system_alerts` table. Surfaced in Settings page.

---

### NEW Section 15: Prompt & Pipeline Versioning
**Source**: Agent 4 (Production ML)
**Phase**: 5 (alongside prompt versioning)

Every generation run records:
- `prompt_template_version`, `pipeline_version`, `review_rubric_version`, `genome_scores_version`
- Stored on `ad_runs.generation_config` JSONB

A/B comparison via `generation_experiments` table:
- Deterministic assignment (odd/even ad_run sequence)
- Mann-Whitney U test (pure Python, no scipy)
- Weekly analysis in `genome_validation` batch job

---

## New Database Tables (Consolidated)

### From Agent 1 (Bandit State)

```sql
-- Thompson Sampling state: one row per (brand, dimension, value)
CREATE TABLE creative_element_scores (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    organization_id UUID NOT NULL,
    brand_id UUID NOT NULL REFERENCES brands(id),
    product_id UUID REFERENCES products(id),
    element_dimension TEXT NOT NULL,
    element_value TEXT NOT NULL,
    alpha FLOAT NOT NULL DEFAULT 1.0,
    beta FLOAT NOT NULL DEFAULT 1.0,
    win_rate FLOAT GENERATED ALWAYS AS (alpha / (alpha + beta)) STORED,
    total_observations INT GENERATED ALWAYS AS (CAST(alpha + beta - 2 AS INT)) STORED,
    confidence_width FLOAT,
    created_at TIMESTAMPTZ DEFAULT NOW(),
    updated_at TIMESTAMPTZ DEFAULT NOW(),
    UNIQUE(brand_id, product_id, element_dimension, element_value)
);

-- Matured reward scores linking element_tags to performance
CREATE TABLE creative_element_rewards (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    organization_id UUID NOT NULL,
    brand_id UUID NOT NULL REFERENCES brands(id),
    product_id UUID REFERENCES products(id),
    generated_ad_id UUID NOT NULL REFERENCES generated_ads(id),
    element_tags JSONB NOT NULL,
    reward_score FLOAT NOT NULL,
    reward_components JSONB,
    campaign_objective TEXT,
    matured_at TIMESTAMPTZ DEFAULT NOW(),
    total_impressions INT,
    total_spend FLOAT,
    raw_ctr FLOAT,
    raw_roas FLOAT,
    bandit_selected BOOLEAN DEFAULT FALSE,
    UNIQUE(generated_ad_id)
);
```

### From Agent 2 (Quality Learning)

```sql
-- Human overrides of AI review decisions
CREATE TABLE ad_review_overrides (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    organization_id UUID NOT NULL,
    generated_ad_id UUID NOT NULL REFERENCES generated_ads(id),
    ai_status TEXT NOT NULL,
    ai_weighted_score NUMERIC(5,3),
    human_status TEXT NOT NULL CHECK (human_status IN ('approved', 'rejected')),
    human_reason TEXT,
    override_type TEXT NOT NULL CHECK (override_type IN (
        'override_approve', 'override_reject', 'confirm_approve', 'confirm_reject')),
    check_overrides JSONB DEFAULT '{}',
    overridden_by UUID,
    created_at TIMESTAMPTZ DEFAULT NOW(),
    UNIQUE(generated_ad_id)
);

-- Versioned quality scoring configuration
CREATE TABLE quality_scoring_config (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    organization_id UUID NOT NULL,
    brand_id UUID REFERENCES brands(id),
    version TEXT NOT NULL,
    is_active BOOLEAN DEFAULT FALSE,
    check_weights JSONB NOT NULL,
    check_thresholds JSONB NOT NULL,
    weighted_pass_threshold NUMERIC(4,2) DEFAULT 7.0,
    calibrated_from_overrides INT DEFAULT 0,
    calibration_metrics JSONB DEFAULT '{}',
    created_at TIMESTAMPTZ DEFAULT NOW()
);

-- Curated exemplar library for few-shot review
CREATE TABLE ad_quality_exemplars (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    organization_id UUID NOT NULL,
    brand_id UUID NOT NULL REFERENCES brands(id),
    generated_ad_id UUID NOT NULL REFERENCES generated_ads(id),
    exemplar_type TEXT NOT NULL CHECK (exemplar_type IN (
        'gold_approve', 'gold_reject', 'edge_case')),
    visual_description TEXT NOT NULL,
    quality_notes TEXT NOT NULL,
    check_scores JSONB DEFAULT '{}',
    exemplar_embedding VECTOR(1536),
    is_active BOOLEAN DEFAULT TRUE,
    created_at TIMESTAMPTZ DEFAULT NOW()
);

-- Fast defect scan results (Stage 1)
CREATE TABLE ad_defect_scans (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    generated_ad_id UUID NOT NULL REFERENCES generated_ads(id),
    passed BOOLEAN NOT NULL,
    defects_found TEXT[] DEFAULT '{}',
    text_garbled BOOLEAN DEFAULT FALSE,
    anatomy_error BOOLEAN DEFAULT FALSE,
    physics_violation BOOLEAN DEFAULT FALSE,
    packaging_text_error BOOLEAN DEFAULT FALSE,
    product_distortion BOOLEAN DEFAULT FALSE,
    model_used TEXT,
    scan_time_ms INT,
    created_at TIMESTAMPTZ DEFAULT NOW()
);
```

### From Agent 3 (Experimentation)

```sql
-- Experiment management
CREATE TABLE experiments (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    organization_id UUID NOT NULL,
    brand_id UUID NOT NULL REFERENCES brands(id),
    product_id UUID REFERENCES products(id),
    name TEXT NOT NULL,
    hypothesis TEXT NOT NULL,
    test_variable TEXT NOT NULL,
    status TEXT NOT NULL DEFAULT 'draft'
        CHECK (status IN ('draft','deploying','running','analyzing','completed','cancelled')),
    hold_constant JSONB NOT NULL DEFAULT '{}',
    audience_config JSONB DEFAULT '{}',
    budget_per_arm_daily NUMERIC(10,2),
    primary_metric TEXT NOT NULL DEFAULT 'link_ctr',
    significance_level NUMERIC(4,3) DEFAULT 0.90,
    meta_campaign_id TEXT,
    winning_arm_id UUID,
    result_summary JSONB,
    created_at TIMESTAMPTZ DEFAULT NOW(),
    started_at TIMESTAMPTZ,
    completed_at TIMESTAMPTZ
);

-- Experiment arms (1 ad set = 1 ad = 1 arm)
CREATE TABLE experiment_arms (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    experiment_id UUID NOT NULL REFERENCES experiments(id) ON DELETE CASCADE,
    arm_name TEXT NOT NULL,
    arm_index INT NOT NULL,
    test_variable_value TEXT NOT NULL,
    element_tags JSONB NOT NULL DEFAULT '{}',
    generated_ad_id UUID REFERENCES generated_ads(id),
    meta_adset_id TEXT,
    total_impressions BIGINT DEFAULT 0,
    total_clicks BIGINT DEFAULT 0,
    total_spend NUMERIC(12,2) DEFAULT 0,
    total_conversions INT DEFAULT 0,
    ctr NUMERIC(8,6),
    roas NUMERIC(8,4),
    posterior_mean NUMERIC(10,6),
    prob_best NUMERIC(6,4),
    created_at TIMESTAMPTZ DEFAULT NOW(),
    UNIQUE(experiment_id, arm_index)
);

-- Causal knowledge base (from completed experiments)
CREATE TABLE causal_effects (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    brand_id UUID NOT NULL REFERENCES brands(id),
    experiment_id UUID NOT NULL REFERENCES experiments(id),
    test_variable TEXT NOT NULL,
    control_value TEXT NOT NULL,
    treatment_value TEXT NOT NULL,
    primary_metric TEXT NOT NULL,
    effect_size NUMERIC(10,6) NOT NULL,
    relative_effect NUMERIC(6,4),
    ci_lower NUMERIC(10,6),
    ci_upper NUMERIC(10,6),
    posterior_prob_positive NUMERIC(6,4),
    control_n INT NOT NULL,
    treatment_n INT NOT NULL,
    created_at TIMESTAMPTZ DEFAULT NOW()
);
```

### From Agent 4 (ML Systems)

```sql
-- Winner evolution lineage tracking
CREATE TABLE ad_lineage (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    parent_ad_id UUID NOT NULL REFERENCES generated_ads(id),
    child_ad_id UUID NOT NULL REFERENCES generated_ads(id),
    evolution_type TEXT NOT NULL CHECK (evolution_type IN (
        'iteration','amplification','refresh','cross_size','rotation','counter_creative')),
    variable_changed TEXT,
    variable_from TEXT,
    variable_to TEXT,
    created_at TIMESTAMPTZ DEFAULT NOW(),
    UNIQUE(parent_ad_id, child_ad_id)
);

-- Prompt/pipeline A/B experiments
CREATE TABLE generation_experiments (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    organization_id UUID NOT NULL,
    brand_id UUID NOT NULL REFERENCES brands(id),
    name TEXT NOT NULL,
    status TEXT NOT NULL DEFAULT 'active'
        CHECK (status IN ('draft','active','completed','cancelled')),
    experiment_type TEXT NOT NULL
        CHECK (experiment_type IN ('prompt_version','pipeline_config','review_rubric','element_strategy')),
    control_config JSONB NOT NULL,
    variant_config JSONB NOT NULL,
    split_ratio NUMERIC(3,2) DEFAULT 0.50,
    control_metrics JSONB,
    variant_metrics JSONB,
    winner TEXT,
    confidence NUMERIC(4,3),
    created_at TIMESTAMPTZ DEFAULT NOW(),
    completed_at TIMESTAMPTZ,
    min_sample_size INTEGER DEFAULT 20
);

-- System health alerts
CREATE TABLE system_alerts (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    organization_id UUID NOT NULL,
    brand_id UUID REFERENCES brands(id),
    alert_type TEXT NOT NULL,
    severity TEXT NOT NULL CHECK (severity IN ('info','warning','critical')),
    title TEXT NOT NULL,
    details JSONB NOT NULL DEFAULT '{}',
    status TEXT NOT NULL DEFAULT 'active'
        CHECK (status IN ('active','acknowledged','resolved','auto_resolved')),
    created_at TIMESTAMPTZ DEFAULT NOW(),
    expires_at TIMESTAMPTZ
);
```

### Column Additions to Existing Tables

```sql
-- generated_ads
ALTER TABLE generated_ads ADD COLUMN IF NOT EXISTS element_tags JSONB DEFAULT '{}';
ALTER TABLE generated_ads ADD COLUMN IF NOT EXISTS bandit_selected BOOLEAN DEFAULT FALSE;
ALTER TABLE generated_ads ADD COLUMN IF NOT EXISTS prompt_version TEXT;
ALTER TABLE generated_ads ADD COLUMN IF NOT EXISTS parent_ad_id UUID REFERENCES generated_ads(id);
ALTER TABLE generated_ads ADD COLUMN IF NOT EXISTS iteration_round INT DEFAULT 0;
ALTER TABLE generated_ads ADD COLUMN IF NOT EXISTS pre_gen_score NUMERIC(6,4);
ALTER TABLE generated_ads ADD COLUMN IF NOT EXISTS genome_version INTEGER;
ALTER TABLE generated_ads ADD COLUMN IF NOT EXISTS visual_embedding VECTOR(1536);
ALTER TABLE generated_ads ADD COLUMN IF NOT EXISTS visual_descriptor JSONB;
ALTER TABLE generated_ads ADD COLUMN IF NOT EXISTS review_model_version TEXT;
ALTER TABLE generated_ads ADD COLUMN IF NOT EXISTS review_weighted_score NUMERIC(5,3);
ALTER TABLE generated_ads ADD COLUMN IF NOT EXISTS review_check_scores JSONB;
ALTER TABLE generated_ads ADD COLUMN IF NOT EXISTS human_override_status TEXT;
ALTER TABLE generated_ads ADD COLUMN IF NOT EXISTS defect_scan_passed BOOLEAN;

-- ad_runs
ALTER TABLE ad_runs ADD COLUMN IF NOT EXISTS generation_config JSONB DEFAULT '{}';
ALTER TABLE ad_runs ADD COLUMN IF NOT EXISTS pipeline_version TEXT DEFAULT 'v1';
ALTER TABLE ad_runs ADD COLUMN IF NOT EXISTS experiment_id UUID;
ALTER TABLE ad_runs ADD COLUMN IF NOT EXISTS experiment_group TEXT;
```

---

## New Services (Consolidated File Map)

```
viraltracker/
├── services/
│   ├── creative_genome_service.py        # Thompson Sampling + element scoring
│   ├── experiment_service.py             # Experiment design + power analysis
│   ├── experiment_analysis_service.py    # Bayesian posteriors + stopping rules
│   ├── quality_calibration_service.py    # Adaptive threshold learning
│   ├── interaction_detector_service.py   # Element interaction effects
│   └── template_element_prompt_translator.py  # Element → prompt rules
├── pipelines/
│   └── ad_creation_v2/
│       ├── nodes/
│       │   └── defect_scan.py            # Stage 1 fast pre-filter
│       └── services/
│           ├── defect_scan_service.py    # 5 binary defect checks
│           ├── exemplar_service.py       # Few-shot exemplar selection
│           └── visual_descriptor_service.py  # Visual embedding extraction
└── worker/
    └── scheduler_worker.py              # +4 job types (see below)
```

### New Scheduler Worker Job Types

| Job Type | Frequency | What It Does |
|----------|-----------|-------------|
| `creative_genome_update` | Weekly | Recompute Bayesian element scores, update Thompson Sampling α/β |
| `genome_validation` | Weekly | Compute prediction accuracy, check drift, analyze experiments |
| `quality_calibration` | Weekly | Calibrate review thresholds from human overrides |
| `experiment_analysis` | Daily | Update Bayesian posteriors for running experiments |

---

## Revised Phase Structure

### Phases 1-5: Unchanged
Original plan phases remain as-is.

### Phase 6: Creative Genome + Quality Learning (ENHANCED)
- [ ] `element_tags` JSONB column + element tagging during generation
- [ ] `creative_element_scores` table + Bayesian averaging service
- [ ] Thompson Sampling integration into SelectContentNode
- [ ] Reward signal computation with maturation windows
- [ ] `creative_genome_update` weekly batch job
- [ ] Pre-generation scoring (advisory context, not hard constraints)
- [ ] Stratified attribution (NOT naive aggregation)
- [ ] `ad_review_overrides` table + UI override buttons
- [ ] `quality_scoring_config` table + configurable thresholds
- [ ] Defect scan pipeline (Stage 1 fast pre-filter)
- [ ] Basic monitoring: `system_alerts` table + `genome_validation` job
- [ ] V1 vs V2 comparison dashboard

### Phase 7: Winner Evolution + Experimentation (ENHANCED)
- [ ] Winner trigger criteria (reward_score >= 0.65, min 7 days, min 1000 impressions)
- [ ] `ad_lineage` table for parent-child tracking
- [ ] Information-gain weighted variable selection
- [ ] Iteration limits (max 5 per winner, max 3 rounds)
- [ ] `experiments` + `experiment_arms` tables
- [ ] Bayesian winner declaration with stopping rules
- [ ] Budget-gated experiment proposals
- [ ] Experiment UI page (`36_🧪_Experiments.py`)
- [ ] `causal_effects` table for causal knowledge base
- [ ] Cold-start category priors

### Phase 8: Full Autonomous Intelligence (NEW)
- [ ] Few-shot exemplar library + embedding similarity selection
- [ ] Adaptive threshold calibration cron job
- [ ] Visual embedding space + style clustering
- [ ] Interaction effect detection (top 15 pairs)
- [ ] Fatigue prediction from element combo histories
- [ ] Anti-fatigue auto-refresh scheduling
- [ ] Prompt/pipeline A/B testing (`generation_experiments`)
- [ ] Cross-brand transfer learning (opt-in)
- [ ] Competitive whitespace identification
- [ ] Full Creative Genome dashboard with causal graph visualization

---

## MVP Definition (Ship in Phase 6, ~3-4 weeks)

The minimum viable self-improving loop that actually works:

1. **Element tagging** (0 cost) — Populate `element_tags` from data already in pipeline state
2. **Bayesian element scoring** (0 LLM cost) — Weekly SQL aggregation + Beta distribution updates
3. **Advisory context injection** (1 query/generation) — Add "performance_context" to prompt
4. **Pre-generation scoring** (0 cost) — Dot product against element scores
5. **Human override tracking** (0 cost) — UI buttons + `ad_review_overrides` table
6. **Defect pre-filter** ($0.002/ad) — Gemini Flash scan before full review
7. **Basic monitoring** (0 cost) — Threshold alerts in `system_alerts`

**Total incremental cost**: ~$0.002/ad for defect scan. Everything else is SQL + Python math.

**What this validates**: "Does the system actually learn to select better-performing elements over time?" If yes, expand to Phase 7-8. If no, debug the reward signal before adding complexity.

---

## Key Design Decisions Made

| Decision | Choice | Rationale |
|----------|--------|-----------|
| Learning algorithm | Thompson Sampling (Beta distributions) | Natural exploration/exploitation, works in Postgres, handles sparse data |
| Reward metric | Composite score (weighted CTR + Conv + ROAS) | Single metric is too narrow; weights adapt to campaign objective |
| Attribution method | Stratified comparison, NOT naive aggregation | Prevents Simpson's Paradox from confounders |
| Experiment deployment | Separate ad sets per arm | Prevents Meta's intra-ad-set MAB from confounding |
| Statistical framework | Bayesian (P(best) > 0.90) | Allows daily checking without false positive inflation |
| Quality learning | Human overrides → threshold calibration | No custom model training needed |
| Visual similarity | Text descriptor → OpenAI embedding → pgvector | Reuses existing infrastructure, interpretable |
| Review pipeline | 3-stage (fast defect → full review → conditional 2nd opinion) | 30% cost reduction, catches worst failures cheaply |
| Cold start | Category-level priors with shrinkage | Cross-brand learning without data leakage |
| All computation | Postgres + Python + LLM calls only | No Redis, no Kafka, no separate ML infra |

---

## Cost Impact Summary

| Component | Per-Ad Cost | Frequency |
|-----------|:-:|:-:|
| Element tagging | $0.000 | Every generation |
| Defect scan (Gemini Flash) | $0.002 | Every generation |
| Full review (reduced from dual to conditional) | $0.005-0.008 avg | Every generation |
| Visual descriptor extraction | $0.001 | Approved ads only |
| Genome update batch | $0.000 | Weekly |
| Genome validation batch | $0.000 | Weekly |
| Calibration batch | $0.000 | Weekly |
| Experiment analysis | $0.000 | Daily |

**Net effect**: Review costs decrease ~30% ($0.010 → $0.007). Visual descriptors add $0.001 for approved ads only. Learning loop itself is zero marginal cost.

---

## Codex Review (Post-Expert-Review)

After the expert review, the plan was submitted to OpenAI Codex for code-level verification against the actual codebase. Codex identified 10 findings (3 P0, 5 P1, 2 P2) — all verified against source code.

### P0 Findings (Would Cause Runtime Failures)

| ID | Finding | Root Cause | Fix |
|----|---------|-----------|-----|
| P0-1 | `ad_creation_v2` job type will misroute to V1 | CHECK constraint on `scheduled_jobs.job_type` doesn't include it; unknown types silently fall through to `execute_ad_creation_job()` | Migration to add to CHECK + explicit elif branch + error logging on else |
| P0-2 | Multi-size variants conflict with prompt_index identity | Plan assumed `(ad_run_id, prompt_index)` differentiated by canvas_size, but pipeline uses prompt_index as unique ID | Composite key `(ad_run_id, prompt_index, canvas_size)`, each variant gets own row |
| P0-3 | Roll-the-dice query references nonexistent column | Plan joins on `product_template_usage.template_id` but table only has `template_storage_name` | Add `template_id` UUID column + backfill from storage_name match |

### P1 Findings (Would Cause Incorrect Behavior)

| ID | Finding | Fix |
|----|---------|-----|
| P1-1 | canvas_size extracted but never persisted to DB | Add to `save_generated_ad()` insert dict |
| P1-2 | 50-ad cap counts approvals, not attempts (cost != cap) | V2 caps **attempts** (Gemini calls), tracks both attempted + approved |
| P1-3 | Template identity assumes UUID but V1 enters via base64 | V2 state carries `template_id: Optional[UUID]`, fallback to runtime analysis |
| P1-4 | Reward weights need campaign objective but it's not synced | Add `campaign_objective` to meta_ads_performance, populate from meta_campaigns |
| P1-5 | Attribution via name parsing is fragile | Use `meta_ad_mapping` table as primary, name parsing as fallback |

### P2 Findings (Design Issues)

| ID | Finding | Fix |
|----|---------|-----|
| P2-1 | `flagged` review status unreachable with OR logic | V2 3-stage pipeline makes flagged meaningful (both borderline) |
| P2-2 | Schema traps: NULL in unique key, no override history | COALESCE for NULLs, remove UNIQUE on overrides (allow history) |

### Changes Made to PLAN.md

All findings integrated into PLAN.md v2:
- **New "Prerequisites" section** (Phase 0) — all P0/P1/P2 fixes with exact SQL migrations
- **Every phase has a "Success gate"** — measurable criteria before proceeding to next phase
- **Incremental principle** added to V2 Principles table
- **Sections 1-15** updated with fixes where relevant (batch caps, template identity, attribution path, etc.)

---

## What's NOT Included (Explicit Exclusions)

- Custom model training (no PyTorch, no GPU instances)
- Real-time learning (all updates are batch)
- Auto-deployment to Meta (manual ad set creation for experiments)
- Video ad quality scoring
- Cross-organization data sharing (privacy boundary)
- Kafka/Redis/streaming infrastructure
