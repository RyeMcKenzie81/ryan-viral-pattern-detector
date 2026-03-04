# Ad Creator V2 — Phase 4 Implementation Plan
# Congruence + Review Overhaul

**Date:** 2026-02-14
**Branch:** `feat/ad-creator-v2-phase0`
**Parent plan:** `docs/plans/ad-creator-v2/PLAN.md` (Phase 4 at line 1284)
**Predecessor:** `CHECKPOINT_008.md` (Phase 3 complete, 98 tests)

---

## Decisions Log

| # | Question | Decision |
|---|----------|----------|
| 1 | BeliefClarityScorer range | D1-D5 (0-15 → [0,1]). D6 handled **in-scorer**: D6=false → 0.0 (compliance penalty), no eval → 0.5 (neutral). NOT gated upstream — `fetch_template_candidates` unchanged. |
| 2 | Stage 2 primary reviewer | Claude Vision primary, Gemini for conditional Stage 3 |
| 3 | Human override effect | Update `generated_ads.final_status` + record in `ad_review_overrides`. Add `override_status` column. |
| 4 | Review column strategy | Keep `claude_review`/`gemini_review` for V1 compat. Add `review_check_scores` + `defect_scan_result` JSONB. |
| 5 | Congruence data source | Extend FetchContextNode to fetch LP hero from `brand_landing_pages`. HeadlineCongruenceNode reads from state. |
| 6 | quality_scoring_config schema | Versioned: `version INT`, `is_active BOOL`, per-check thresholds JSONB, `created_at`. Enforced with partial unique indexes. |

---

## New Pipeline Graph (Phase 4)

```
InitializeNode
  → FetchContextNode          (MODIFIED: +LP hero fetch)
  → AnalyzeTemplateNode
  → SelectContentNode
  → HeadlineCongruenceNode    (NEW — Phase 4)
  → SelectImagesNode
  → GenerateAdsNode
  → DefectScanNode            (NEW — Phase 4, Stage 1)
  → ReviewAdsNode             (MODIFIED: Stages 2-3, structured rubric)
  → RetryRejectedNode
  → CompileResultsNode
```

### Defect-rejected ad flow (P0 fix: no ads lost downstream)

DefectScanNode processes ALL `generated_ads`. For each:
- **Defect found**: save to DB with `final_status='rejected'` + `defect_scan_result` JSONB.
  Append to `ctx.state.reviewed_ads` immediately (with `defect_rejected: True` flag).
- **No defect**: pass to ReviewAdsNode via `ctx.state.defect_passed_ads`.

ReviewAdsNode runs Stages 2-3 only on `defect_passed_ads`, then appends results to
`ctx.state.reviewed_ads`. RetryRejectedNode and CompileResultsNode operate on the
complete `reviewed_ads` list (defect-rejected + review-processed), so all ads are
counted in summaries and eligible for retry.

---

## Database Changes

### Migration 1: Fix `final_status` CHECK constraint + add columns

The existing CHECK constraint on `generated_ads.final_status` allows only
`pending|approved|rejected|flagged`. The current pipeline already emits
`review_failed` (review_service.py:134) and `generation_failed`
(CompileResultsNode:59), both violating the constraint. Fix this first.

```sql
-- Fix: expand final_status CHECK to include all pipeline-emitted statuses
ALTER TABLE generated_ads
  DROP CONSTRAINT IF EXISTS generated_ads_final_status_check;

ALTER TABLE generated_ads
  ADD CONSTRAINT generated_ads_final_status_check
  CHECK (final_status IN (
    'pending', 'approved', 'rejected', 'flagged',
    'review_failed', 'generation_failed'
  ));

-- Phase 4 new columns
ALTER TABLE generated_ads
  ADD COLUMN IF NOT EXISTS review_check_scores JSONB,
  ADD COLUMN IF NOT EXISTS defect_scan_result JSONB,
  ADD COLUMN IF NOT EXISTS congruence_score NUMERIC(4,3),
  ADD COLUMN IF NOT EXISTS override_status TEXT;

-- override_status CHECK: idempotent (drop-then-add) because ADD COLUMN IF NOT EXISTS
-- won't retroactively add a CHECK if the column already existed without one.
ALTER TABLE generated_ads
  DROP CONSTRAINT IF EXISTS generated_ads_override_status_check;
ALTER TABLE generated_ads
  ADD CONSTRAINT generated_ads_override_status_check
  CHECK (override_status IN ('override_approved', 'override_rejected', 'confirmed'));

COMMENT ON COLUMN generated_ads.review_check_scores IS
  'Structured 15-check review scores: V1-V9 visual, C1-C4 content, G1-G2 congruence (0-10 each). NULL for Stage-1-rejected and generation-failed ads.';
COMMENT ON COLUMN generated_ads.defect_scan_result IS
  'Stage 1 defect scan result: {passed: bool, defects: [{type, description}], model, latency_ms}. Present for all successfully generated V2 ads. NULL for generation_failed.';
COMMENT ON COLUMN generated_ads.congruence_score IS
  'Headline ↔ offer variant ↔ hero section congruence score (0.000-1.000). NULL if no offer_variant_id.';
COMMENT ON COLUMN generated_ads.override_status IS
  'Human override status. NULL = no override.';
```

### Migration 2: `ad_review_overrides` table

```sql
CREATE TABLE IF NOT EXISTS ad_review_overrides (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    generated_ad_id UUID NOT NULL REFERENCES generated_ads(id) ON DELETE CASCADE,
    organization_id UUID NOT NULL,
    user_id UUID NOT NULL,
    override_action TEXT NOT NULL CHECK (override_action IN ('override_approve', 'override_reject', 'confirm')),
    previous_status TEXT,              -- AI status before override
    check_overrides JSONB,             -- per-check granularity: {"V1": {"ai_score": 6.0, "human_override": "pass"}}
    reason TEXT,                       -- optional human notes
    superseded_by UUID REFERENCES ad_review_overrides(id),  -- latest override chain
    created_at TIMESTAMPTZ DEFAULT NOW()
);

-- No UNIQUE on generated_ad_id — multiple overrides per ad allowed (see PLAN.md P2-2)
CREATE INDEX IF NOT EXISTS idx_aro_ad ON ad_review_overrides(generated_ad_id, created_at DESC);
CREATE INDEX IF NOT EXISTS idx_aro_org ON ad_review_overrides(organization_id);
```

### Migration 3: `quality_scoring_config` table

```sql
CREATE TABLE IF NOT EXISTS quality_scoring_config (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    organization_id UUID,             -- NULL = global default
    version INT NOT NULL DEFAULT 1,
    is_active BOOLEAN NOT NULL DEFAULT FALSE,
    pass_threshold NUMERIC(4,2) NOT NULL DEFAULT 7.00,  -- weighted score out of 10
    check_weights JSONB NOT NULL DEFAULT '{
        "V1": 1.5, "V2": 1.5, "V3": 1.0, "V4": 0.8, "V5": 0.8,
        "V6": 1.0, "V7": 1.0, "V8": 0.8, "V9": 1.2,
        "C1": 1.0, "C2": 0.8, "C3": 0.8, "C4": 0.8,
        "G1": 1.0, "G2": 0.8
    }',
    borderline_range JSONB NOT NULL DEFAULT '{"low": 5.0, "high": 7.0}',
    auto_reject_checks JSONB NOT NULL DEFAULT '["V9"]',  -- checks that auto-reject if below 3.0
    created_at TIMESTAMPTZ DEFAULT NOW(),
    created_by UUID,
    notes TEXT
);

-- Enforce unique version per org (COALESCE handles NULL org_id for global rows)
CREATE UNIQUE INDEX IF NOT EXISTS idx_qsc_unique_version
  ON quality_scoring_config (COALESCE(organization_id, '00000000-0000-0000-0000-000000000000'), version);

-- Enforce at most one active config per org (including global)
CREATE UNIQUE INDEX IF NOT EXISTS idx_qsc_single_active
  ON quality_scoring_config (COALESCE(organization_id, '00000000-0000-0000-0000-000000000000'))
  WHERE is_active = TRUE;

COMMENT ON TABLE quality_scoring_config IS
  'Versioned quality thresholds for ad review. Partial unique index enforces single is_active per org. Phase 6 adds adaptive calibration.';

-- Seed global default (version 1, active)
INSERT INTO quality_scoring_config (organization_id, version, is_active, notes)
VALUES (NULL, 1, TRUE, 'Phase 4 initial static thresholds')
ON CONFLICT DO NOTHING;
```

---

## Implementation Chunks

### P4-C1: Migrations + BeliefClarityScorer (~15-20K tokens)

**Scope:**
- [ ] Write SQL migration file for all 3 migrations above
- [ ] Add `BeliefClarityScorer` class to `template_scoring_service.py`
  - **Logic (D6 in-scorer, not upstream gate)**:
    1. Look up `template_evaluations` row for template_id (join on candidate query or prefetch)
    2. If no evaluation exists → return 0.5 (neutral, no data)
    3. If `d6_compliance_pass = false` → return 0.0 (non-compliant penalty)
    4. Else → `sum(d1..d5) / 15.0` (normalized to [0,1])
  - Prefetch strategy: extend `fetch_template_candidates()` to LEFT JOIN `template_evaluations`
    and merge `total_score`, `d6_compliance_pass`, `eligible` into each candidate row dict.
    Scorer reads from row dict — zero per-template DB calls during scoring.
- [ ] Create `PHASE_4_SCORERS` list (6 scorers: Phase 3 + BeliefClarity)
- [ ] Update weight presets (add `belief_clarity` key to ROLL_THE_DICE and SMART_SELECT)
- [ ] Update default scorers from `PHASE_3_SCORERS` to `PHASE_4_SCORERS`
- [ ] Unit tests for BeliefClarityScorer:
  - No evaluation → 0.5
  - D6 = false → 0.0
  - D6 = true, D1-D5 all 3 → 1.0
  - D6 = true, D1-D5 mixed → correct normalization
  - Partial scores (some D columns NULL) → use COALESCE(0) per DB behavior
- [ ] `py_compile` all changed files

**Files changed:**
| File | Change |
|------|--------|
| `migrations/2026-02-14_ad_creator_v2_phase4.sql` | NEW: all 3 migrations |
| `viraltracker/services/template_scoring_service.py` | +BeliefClarityScorer, +PHASE_4_SCORERS, +weight presets, +eval prefetch in fetch_template_candidates |
| `tests/services/test_template_scoring_service.py` | +BeliefClarityScorer tests |

**Success criteria:**
- Migration SQL is syntactically valid
- All existing scoring tests still pass
- New scorer tests pass (including D6=false → 0.0 case)
- `py_compile` passes

---

### P4-C2: CongruenceService + HeadlineCongruenceNode (~20-25K tokens)

**Scope:**
- [ ] Build `congruence_service.py` in `pipelines/ad_creation_v2/services/`
  - `check_congruence(headline, offer_variant_data, lp_hero_data, belief_data) → CongruenceResult`
  - LLM call (Claude) scores 0-1.0 on 3 dimensions:
    - offer_alignment: headline ↔ offer variant pain points/benefits
    - hero_alignment: headline ↔ LP hero headline/subheadline (if available)
    - belief_alignment: headline ↔ belief statement (if belief_first mode)
  - If below threshold (0.6): returns adapted headline suggestion
  - Returns `CongruenceResult` dataclass with scores + optional adapted headline
- [ ] Extend FetchContextNode to fetch LP hero data from `brand_landing_pages`
  - Query by `brand_id` AND normalized URL (strip trailing slash, lowercase, strip query params)
  - Fallback: if no match by normalized URL, try exact URL, then skip gracefully (hero_alignment = None)
  - Store in new state field: `lp_hero_data: Optional[Dict]`
- [ ] Build `headline_congruence.py` node
  - For each selected hook: call congruence_service.check_congruence()
  - If score < threshold AND adapted headline returned: replace hook text
  - If no offer_variant_id: skip (pass through, neutral score 1.0)
  - Store congruence scores in state
- [ ] Update state with new fields: `lp_hero_data`, `congruence_results`
- [ ] Update orchestrator graph: insert HeadlineCongruenceNode after SelectContentNode
- [ ] Unit tests
- [ ] `py_compile` all

**Files changed:**
| File | Change |
|------|--------|
| `viraltracker/pipelines/ad_creation_v2/services/congruence_service.py` | NEW |
| `viraltracker/pipelines/ad_creation_v2/nodes/headline_congruence.py` | NEW |
| `viraltracker/pipelines/ad_creation_v2/nodes/fetch_context.py` | +LP hero fetch (brand_id + normalized URL) |
| `viraltracker/pipelines/ad_creation_v2/state.py` | +lp_hero_data, +congruence_results |
| `viraltracker/pipelines/ad_creation_v2/orchestrator.py` | +HeadlineCongruenceNode in graph |
| `tests/pipelines/ad_creation_v2/test_congruence.py` | NEW |

**Dependencies:** P4-C1 (migration for `congruence_score` column)

**Success criteria:**
- CongruenceService unit tests pass (with/without offer variant, with/without LP data, belief mode)
- LP hero lookup uses brand_id + normalized URL, graceful fallback on no match
- Node inserts correctly between SelectContent → SelectImages
- Pipeline still runs end-to-end with no offer_variant_id (congruence node is a pass-through)
- `py_compile` passes

---

### P4-C3: DefectScanService + DefectScanNode (Stage 1) (~20-25K tokens)

**Scope:**
- [ ] Build `defect_scan_service.py` in `pipelines/ad_creation_v2/services/`
  - `scan_for_defects(image_data, product_name, media_type) → DefectScanResult`
  - Uses Gemini 3 Flash (cheapest vision model) for speed
  - 5 binary defect checks: TEXT_GARBLED, ANATOMY_ERROR, PHYSICS_VIOLATION, PACKAGING_TEXT_ERROR, PRODUCT_DISTORTION
  - Returns `DefectScanResult` dataclass: `{passed: bool, defects: List[Defect], model: str, latency_ms: int}`
  - Each `Defect`: `{type: str, description: str, severity: "critical"}`
- [ ] Build `defect_scan.py` node — **carries defect-rejected ads through full pipeline**:
  - Runs after GenerateAdsNode, reads `ctx.state.generated_ads`
  - For each generated ad: download image, call defect_scan_service
  - **Defect found**: save to DB via `save_generated_ad()` with `final_status='rejected'`,
    `defect_scan_result` JSONB. Append to `ctx.state.reviewed_ads` with `defect_rejected: True`.
  - **No defect**: append to `ctx.state.defect_passed_ads` (new state field)
  - ReviewAdsNode reads `defect_passed_ads` (not `generated_ads`)
  - RetryRejectedNode and CompileResultsNode read `reviewed_ads` (contains both defect-rejected + reviewed)
- [ ] Extend `save_generated_ad()` in `ad_creation_service.py`:
  - Add optional params: `defect_scan_result: Optional[Dict]`, `review_check_scores: Optional[Dict]`, `congruence_score: Optional[float]`
  - Write to corresponding columns when provided
- [ ] Update state: `defect_passed_ads: List[Dict]` (new), `defect_scan_results: List[Dict]` (tracking)
- [ ] Update orchestrator graph: insert DefectScanNode between GenerateAds → ReviewAds
- [ ] Unit tests
- [ ] `py_compile` all

**Files changed:**
| File | Change |
|------|--------|
| `viraltracker/pipelines/ad_creation_v2/services/defect_scan_service.py` | NEW |
| `viraltracker/pipelines/ad_creation_v2/nodes/defect_scan.py` | NEW |
| `viraltracker/pipelines/ad_creation_v2/state.py` | +defect_passed_ads, +defect_scan_results |
| `viraltracker/pipelines/ad_creation_v2/orchestrator.py` | +DefectScanNode in graph |
| `viraltracker/services/ad_creation_service.py` | +defect_scan_result, +review_check_scores, +congruence_score params to save_generated_ad() |
| `tests/pipelines/ad_creation_v2/test_defect_scan.py` | NEW |

**Dependencies:** P4-C1 (migration for columns + CHECK constraint fix)

**Success criteria:**
- DefectScanService returns well-formed DefectScanResult for all 5 defect types
- Defect-rejected ads saved to DB with correct `defect_scan_result` JSONB and `final_status='rejected'`
- Defect-rejected ads appear in `reviewed_ads` (visible to RetryRejected + CompileResults)
- ReviewAdsNode only processes `defect_passed_ads` (not defect-rejected)
- CompileResultsNode counts all ads correctly (defect + review)
- Pipeline handles: all pass, all fail, mixed
- `py_compile` passes

---

### P4-C4: Review Overhaul — 3-Stage Pipeline (Stages 2-3) (~25-30K tokens)

**Scope:**
- [ ] Refactor `review_service.py`:
  - New `review_ad_staged(image_data, context, config) → StagedReviewResult` method
  - **Stage 2**: Claude Vision reviews with 15-check rubric (V1-V9, C1-C4, G1-G2)
    - Each check scored 0-10
    - Returns structured `review_check_scores` dict
    - Compute weighted score using `quality_scoring_config` weights
  - **Stage 3**: Conditional Gemini Vision review
    - Triggers only if any Stage 2 check is in borderline range (5.0-7.0)
    - Same 15-check rubric
    - OR logic: if either reviewer's weighted score >= threshold → approved
  - New `apply_staged_review_logic(stage2_result, stage3_result, config) → final_status`
  - Load `quality_scoring_config` from DB (active version for org, fallback to global)
  - Keep old methods (`review_ad_claude`, `review_ad_gemini`, `apply_dual_review_logic`) for V1 compat
- [ ] Refactor `review_ads.py` node:
  - Read from `ctx.state.defect_passed_ads` (not `generated_ads`) — only Stage-1-clean ads
  - Call `review_ad_staged()` for each ad
  - Save via `save_generated_ad()` with `review_check_scores`, `defect_scan_result` (passed scan), `congruence_score`
  - Still populate `claude_review` / `gemini_review` for backward compat (V1 UI reads these)
  - Append to `ctx.state.reviewed_ads` (joining defect-rejected ads already there)
- [ ] Unit tests for:
  - 15-check rubric prompt parsing
  - Weighted score computation
  - Stage 3 trigger logic (borderline detection)
  - OR logic across stages
  - Config loading + fallback to defaults
- [ ] `py_compile` all

**Files changed:**
| File | Change |
|------|--------|
| `viraltracker/pipelines/ad_creation_v2/services/review_service.py` | +staged review, +15-check rubric, +config loading |
| `viraltracker/pipelines/ad_creation_v2/nodes/review_ads.py` | Refactored: reads defect_passed_ads, runs Stages 2-3, saves new columns |
| `tests/pipelines/ad_creation_v2/test_review_service.py` | NEW |
| `tests/pipelines/ad_creation_v2/test_review_node.py` | NEW |

**Dependencies:** P4-C1 (migration), P4-C3 (defect scan provides defect_passed_ads + save_generated_ad params)

**Success criteria:**
- Stage 2 runs Claude Vision with 15-check rubric and returns structured scores
- Stage 3 only triggers when borderline scores detected (cost optimization)
- Weighted score computation matches expected values from quality_scoring_config
- `defect_scan_result` (passed result) + `review_check_scores` + `congruence_score` all persisted
- V1 backward compat: `claude_review`/`gemini_review` still populated
- `py_compile` passes

---

### P4-C5: Human Override UI + Override Service (~15-20K tokens)

**Scope:**
- [ ] Create Postgres RPC function `apply_ad_override(p_generated_ad_id, p_org_id, p_user_id, p_action, p_reason, p_check_overrides)`
  - Single atomic transaction:
    1. INSERT into `ad_review_overrides`
    2. UPDATE `generated_ads` SET `final_status` + `override_status`
    3. UPDATE previous overrides SET `superseded_by` = new override id
  - Returns the new override row
  - Added to Phase 4 migration file
- [ ] Build override service (`ad_review_override_service.py` in `services/`)
  - `create_override(generated_ad_id, org_id, user_id, action, reason, check_overrides) → override`
  - Calls `supabase.rpc('apply_ad_override', {...})` — atomic, no partial writes
  - `get_latest_override(generated_ad_id) → override or None`
  - `get_override_stats(org_id, date_range) → {total, override_approve, override_reject, confirm}`
- [ ] Enhance results dashboard in V2 UI page:
  - Per-ad detail expandable: show structured review scores (V1-V9, C1-C4, G1-G2 as colored bars)
  - Show defect scan result (if rejected at Stage 1)
  - Show congruence score
  - Override buttons: "Override Approve" / "Override Reject" / "Confirm" (with optional reason field)
  - Override status badge on ad cards
  - Override rate summary at top of results
- [ ] Unit tests for override service
- [ ] `py_compile` all

**Files changed:**
| File | Change |
|------|--------|
| `migrations/2026-02-14_ad_creator_v2_phase4_rpc.sql` | NEW: `apply_ad_override()` RPC function |
| `viraltracker/services/ad_review_override_service.py` | NEW |
| `viraltracker/ui/pages/21b_🎨_Ad_Creator_V2.py` | +override buttons, +structured score display, +defect/congruence display |
| `tests/services/test_ad_review_override_service.py` | NEW |

**Dependencies:** P4-C1 (migration for tables), P4-C4 (review data to display)

**Success criteria:**
- Override buttons render and create records in `ad_review_overrides`
- `generated_ads.final_status` + `override_status` both update on override
- Override stats show correct counts
- Structured scores display correctly in UI
- `py_compile` passes

---

### P4-C6: Deferred UI Testing + Success Gate Validation (~10K tokens)

**Scope:**
- [ ] Browser-test Phase 2 UI controls (multiselect renders, batch estimate)
- [ ] Browser-test Phase 3 UI changes (6-column score display, persona-aware scoring)
- [ ] Browser-test Phase 4 UI changes (override buttons, structured scores, congruence/defect display)
- [ ] End-to-end deployed environment testing
- [ ] Validate Phase 4 success gate (see split definition below)
- [ ] Post-plan review (`/post-plan-review`)
- [ ] Write final CHECKPOINT_009.md

**Dependencies:** P4-C1 through P4-C5 all complete

**Success criteria:**
- All deferred browser tests pass
- Phase 4 success gate criteria met
- Post-plan review verdict: PASS

---

## Chunk Dependency Graph

```
P4-C1 (migrations + scorer)
  ├── P4-C2 (congruence) ──────┐
  ├── P4-C3 (defect scan) ─────┤
  │                             ├── P4-C4 (review overhaul)
  │                             │       │
  │                             │       ├── P4-C5 (override UI)
  │                             │       │       │
  │                             └───────┴───────┴── P4-C6 (testing + gate)
```

P4-C2 and P4-C3 can run in parallel after P4-C1.
P4-C4 depends on P4-C3 (defect scan feeds into review).
P4-C5 depends on P4-C4 (needs review data to display).
P4-C6 depends on all others.

---

## Risk Register

| Risk | Impact | Mitigation |
|------|--------|------------|
| 15-check rubric prompt too long → truncated/poor JSON | Stage 2 fails | Test prompt length, use structured output mode if available. Fallback to V1 review. |
| Gemini Flash defect scan too aggressive (high false positive) | Good ads auto-rejected | Log all defect results. Tunable: start with high threshold → loosen. |
| CongruenceService LLM call adds latency per hook | Pipeline slower | Batch hooks into single LLM call. Configurable: skip if no offer_variant_id. |
| `brand_landing_pages` has no data for most brands | Congruence hero_alignment always N/A | Graceful: hero_alignment = null, only score offer_alignment + belief_alignment. |
| Override superseding logic complex | Bugs in override chain | Unit test superseding thoroughly. Keep it simple: latest override wins. |
| Regenerate flow still lacks asset context (Phase 3 risk #1) | Regenerated ads miss Phase 4 checks | Out of Phase 4 scope. Log warning if regenerate used. Fix in regenerate overhaul. |
| RetryRejectedNode uses V1 dual review, not Stage 2-3 | Retried ads get old review | Acceptable for Phase 4. Phase 5 unifies retry to use staged review. |

---

## Phase 4 Success Gate (from PLAN.md, with split denominator fix)

> Defect scan catches >= 30% of rejects (saves review cost). Override rate tracked. Structured scores stored for all V2 ads.

**Split measurement** (Stage-1 rejects skip Stage-2 rubric by design):

| Metric | Denominator | Target |
|--------|-------------|--------|
| Defect catch rate | `count(defect_rejected) / count(all_rejected)` | >= 0.30 over N >= 50 ads |
| `defect_scan_result` coverage | All **successfully generated** V2 ads (excludes `generation_failed`) | 1.0 (every generated ad gets scanned) |
| `review_check_scores` coverage | Stage-2-reviewed ads only (defect-passed subset of generated) | 1.0 (every reviewed ad has structured scores) |
| Override tracking | `ad_review_override_service.get_override_stats()` | Returns non-null, rate logged |

---

## Fixes Applied (from pre-approval review)

| Issue | Severity | Fix |
|-------|----------|-----|
| [P0] BeliefClarity D1-D6 contradicts main plan | P0 | Updated PLAN.md line 755+1292 to D1-D5 + D6 in-scorer. Updated decision #1. |
| [P0] `final_status` CHECK constraint missing `review_failed`/`generation_failed` | P0 | Migration 1 now drops+recreates CHECK with all 6 statuses. |
| [P0] Stage-1 rejects lost downstream | P0 | DefectScanNode appends rejects to `reviewed_ads` immediately. ReviewAdsNode reads `defect_passed_ads`. Full pipeline sees all ads. |
| [P1] `save_generated_ad()` missing new field params | P1 | P4-C3 scope explicitly extends `save_generated_ad()` with 3 new params. `ad_creation_service.py` in file list. |
| [P1] `quality_scoring_config` no single-active enforcement | P1 | Replaced UNIQUE(org,version) with COALESCE unique index + partial unique index on `is_active=TRUE`. |
| [P1] LP hero lookup URL-only is brittle | P1 | FetchContextNode queries by `brand_id` + normalized URL (strip trailing slash, lowercase, strip query params) with fallback. |
| [P1] D6 "gated upstream" is false | P1 | BeliefClarityScorer handles D6 in-scorer: `D6=false → 0.0`. No upstream gate needed. `fetch_template_candidates` unchanged. |
| [P2] Success gate denominator inconsistent | P2 | Split: `defect_scan_result` coverage on ALL ads, `review_check_scores` coverage on Stage-2 ads only. |
| [P0] Main-plan 2 stale lines (line 617, 1293) | P0 | Updated PLAN.md line 617 (scorer list) and line 1293 (success gate) to match Phase 4 contract. |
| [P1] `override_status` CHECK not idempotent | P1 | Split into ADD COLUMN (no CHECK) + DROP CONSTRAINT IF EXISTS + ADD CONSTRAINT. |
| [P1] `defect_scan_result` coverage overclaims with `generation_failed` | P1 | Denominator changed to "all successfully generated V2 ads" (excludes `generation_failed`). |
| [P1] Override "same transaction" has no mechanism | P1 | Added Postgres RPC `apply_ad_override()` for atomic 3-step write. Service calls `supabase.rpc()`. |
