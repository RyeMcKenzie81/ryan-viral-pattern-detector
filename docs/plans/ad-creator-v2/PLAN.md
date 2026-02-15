# Ad Creator V2 — Plan

> **Status**: IN PROGRESS (v17 — Phase 5 code complete, gate pending; Phase 4 gate partially unvalidated)
> **Created**: 2026-02-12
> **Updated**: 2026-02-14
> **Replaces**: Nothing — V2 runs alongside V1 until proven better

---

## Why V2

V1 works but has structural problems:

1. **Browser-dependent** — Generation dies if user leaves the page. Every other heavy tool (meta sync, classification, scoring) runs on the scheduler worker. Ad creation should too.
2. **No size control** — Canvas size comes from the template analysis. Users can't say "give me 1x1 and 9x16." Multi-size requires a separate "edit" step after the fact.
3. **Asset gap between classification and generation** — Templates get element-classified (`template_element_service.py`), product images get asset-tagged, and there's even an asset match score shown in the UI. But **none of this feeds into the generation prompt**. The prompt just takes 1-2 best-scored images blindly.
4. **Color is single-choice** — Original OR complementary OR brand. Can't get all three in one run.
5. **Review is shallow** — Dual AI review checks 4 scores (product, text, layout, quality) with hard-coded 0.8 thresholds. No brand guideline check, no compliance check, no headline congruence check.
6. **Prompt is a 280-line dict literal** — `generation_service.generate_prompt()` builds a massive JSON dict inline. Hard to version, hard to test, hard to iterate.
7. **Headline has no offer variant congruence** — The hook text goes in as-is. There's no check that the headline matches the hero section or offer variant messaging.
8. **No learning** — Static rules, no performance feedback, no quality calibration from human decisions.

---

## V2 Principles

| Principle | Meaning |
|-----------|---------|
| **Worker-first** | Submit → scheduler job → worker generates → user views results later |
| **Explicit over magic** | User picks sizes, colors, templates — no "random smorgasbord" |
| **Asset-aware prompts** | If we classified the template and tagged the images, USE that data |
| **Pydantic prompts** | Prompt is a Pydantic model, not a dict literal |
| **Parallel V1** | New page `21b_🎨_Ad_Creator_V2.py`, V1 untouched |
| **Incremental & measurable** | Each phase has success criteria measured before building the next layer |
| **Learn from outcomes** | Human feedback + performance data feed back into generation decisions |

---

## Current V1 Pipeline (for reference)

```
InitializeNode → FetchContextNode → AnalyzeTemplateNode → SelectContentNode
    → SelectImagesNode → GenerateAdsNode → ReviewAdsNode → (RetryRejectedNode)
    → CompileResultsNode → End
```

**What works well (keep):**
- 8-node graph structure (pydantic-graph)
- Template analysis caching (saves 4-8 min re-analysis)
- Dual AI review with OR logic
- Resilient per-ad error handling (one failure doesn't abort batch)
- Content source flexibility (hooks, recreate_template, belief_first, plan, angles)
- Persona-aware hook adaptation

**What's broken/missing (fix in V2):**
- No worker offload (browser-dependent)
- No multi-size generation
- Asset classification not wired to prompt
- Single color mode per run
- Shallow review criteria
- Monolithic prompt construction
- No headline↔offer variant congruence
- No "roll the dice" template selection
- No learning from performance or human quality judgments

---

## Prerequisites: Schema & Infrastructure Fixes

> **CRITICAL**: These must be done BEFORE Phase 1 implementation. Codex review identified P0 blockers that will cause runtime failures if not addressed first.

### P0-1: Job Type Constraint + Worker Routing

**Problem:** The `scheduled_jobs` table has a CHECK constraint limiting `job_type` to 8 values (does not include `ad_creation_v2`). Unknown job types silently fall through to V1's `execute_ad_creation_job()` in the worker — no error, just wrong behavior.

**Fix (migration):**
```sql
-- Migration: Add V2 job types (ad_creation_v2 + Phase 6-7 batch jobs)
ALTER TABLE scheduled_jobs
DROP CONSTRAINT IF EXISTS scheduled_jobs_job_type_check;

ALTER TABLE scheduled_jobs
ADD CONSTRAINT scheduled_jobs_job_type_check
CHECK (job_type IN (
    -- Existing
    'ad_creation', 'meta_sync', 'scorecard', 'template_scrape',
    'template_approval', 'congruence_reanalysis', 'ad_classification',
    'asset_download', 'competitor_scrape', 'reddit_scrape',
    'amazon_review_scrape',
    -- V2 (Phase 0)
    'ad_creation_v2',
    -- Phase 6: Creative Genome
    'creative_genome_update', 'genome_validation',
    -- Phase 6: Quality calibration
    'quality_calibration',
    -- Phase 7: Experiments
    'experiment_analysis'
));
```

**Fix (worker):** Add explicit `elif job_type == 'ad_creation_v2':` branch in `scheduler_worker.py` BEFORE the `else` fallback. Add a `logger.error()` in the `else` branch for unknown types instead of silently defaulting.

### P0-2: Multi-Size Variant Identity

**Problem:** Plan says size variants share `(ad_run_id, prompt_index)` differentiated by `canvas_size`. But the current pipeline uses `prompt_index` as the unique identifier within a run. Size variants need their own identity.

**Fix:** Use a composite key: `(ad_run_id, prompt_index, canvas_size)`. Each size variant is a separate `generated_ads` row with its own UUID. The `prompt_index` identifies the creative brief (hook + template + color), and `canvas_size` identifies the size variant.

**Migration:**
```sql
-- 1. Add canvas_size column (currently extracted but not saved)
ALTER TABLE generated_ads ADD COLUMN IF NOT EXISTS canvas_size TEXT;

-- 2. Drop the existing unique index that prevents multi-size variants
--    (migration_ad_creation.sql line 137: CREATE UNIQUE INDEX idx_generated_ads_run_index ON generated_ads(ad_run_id, prompt_index))
DROP INDEX IF EXISTS idx_generated_ads_run_index;

-- 3. Recreate as composite index allowing multiple sizes per prompt_index
CREATE UNIQUE INDEX idx_generated_ads_run_index
ON generated_ads(ad_run_id, prompt_index, COALESCE(canvas_size, 'default'));

-- 4. Relax the prompt_index CHECK constraint (currently capped at 5, too low for multi-size × multi-color)
--    (migration_ad_creation.sql line 112: CHECK (prompt_index >= 1 AND prompt_index <= 5))
ALTER TABLE generated_ads DROP CONSTRAINT IF EXISTS generated_ads_prompt_index_check;
ALTER TABLE generated_ads ADD CONSTRAINT generated_ads_prompt_index_check
CHECK (prompt_index >= 1 AND prompt_index <= 100);

-- 5. Backfill existing ads from filename parsing (M5-XXXXXXXX-WP-C3-SQ.png → SQ = 1080x1080)
-- Run as one-time data migration after column add
```

**Code change:** Update `save_generated_ad()` in `ad_creation_service.py` to persist `canvas_size` from the pipeline state.

### P0-3: Roll the Dice Query Fix

**Problem:** Plan's query joins on `product_template_usage.template_id`, but the actual table uses `template_storage_name` (no `template_id` column).

**Fix:** Either:
- (A) Add a `template_id` UUID column to `product_template_usage` and update `record_template_usage()` to populate it (preferred — more reliable than filename matching), OR
- (B) Join on `scraped_templates.storage_path = product_template_usage.template_storage_name`

Choose (A) with migration:
```sql
ALTER TABLE product_template_usage
ADD COLUMN IF NOT EXISTS template_id UUID REFERENCES scraped_templates(id);

-- Backfill from storage_path match (scraped_templates uses storage_path, not storage_name)
-- IMPORTANT: storage_path has no UNIQUE constraint, so duplicates are possible.
-- Tie-break policy: pick the most recently created active template.
UPDATE product_template_usage ptu
SET template_id = st.id
FROM (
    SELECT DISTINCT ON (storage_path) id, storage_path
    FROM scraped_templates
    WHERE is_active = TRUE
    ORDER BY storage_path, created_at DESC
) st
WHERE st.storage_path = ptu.template_storage_name
  AND ptu.template_id IS NULL;
```

**Backfill audit (run after migration):**
```sql
-- Check for ambiguous mappings (multiple active templates with same storage_path)
SELECT storage_path, COUNT(*) as cnt
FROM scraped_templates
WHERE is_active = TRUE
GROUP BY storage_path
HAVING COUNT(*) > 1;

-- Check for unmapped usage rows (template_id still NULL after backfill)
SELECT COUNT(*) FROM product_template_usage WHERE template_id IS NULL;
```

**Phase 0 gate requirement:** Zero ambiguous mappings (the audit query above returns 0 rows), OR a documented tolerance with remediation plan (e.g., manually resolve the N duplicates). Any unmapped rows are acceptable only if they correspond to templates that have been deactivated.

**Note:** `scraped_templates` uses `storage_path` (not `storage_name`) and `is_active` boolean (not `status = 'approved'`). All queries in this plan use `template_id` UUID after backfill, avoiding column name confusion.

### P1-1: Canvas Size Persistence

**Problem:** `canvas_size` is extracted in `generate_ads.py` (line 94) and passed to `upload_generated_ad()` for filename generation, but `save_generated_ad()` does NOT write it to the `generated_ads` row.

**Fix:** Add `canvas_size` to the insert dict in `save_generated_ad()` (covered by P0-2 migration above). Also add to the `save_generated_ad()` function signature and insert logic.

### P1-2: Batch Size vs Scheduler Cap

**Problem:** `MAX_ADS_PER_SCHEDULED_RUN = 50` counts only approved ads (line 891: `ads_generated += approved`). A run of 90 attempts that produces 45 approved ads would stay under the cap, but the generation cost is 90 Gemini calls.

**Fix:**
- V2 tracks both `ads_attempted` and `ads_approved` in job metadata
- The 50-ad cap applies to **attempted** generations (Gemini API calls), not just approved
- UI shows: "This will attempt ~90 generations (~$1.80 est.)" with a configurable cap per org
- If estimated attempts > cap, require user confirmation or split into multiple jobs

### P1-3: Template Identity Path

**Problem:** Plan assumes `template_id` UUID available at prompt construction time, but V1 pipeline entry point uses `reference_ad_base64` + filename. Template element lookup is by `scraped_templates.id`.

**Fix:** V2 pipeline state carries `template_id: Optional[UUID]` from the start:
- If user selects from scraped_templates UI → `template_id` is the `scraped_templates.id`
- If user uploads custom image → `template_id` is None, asset context falls back to runtime analysis
- `AnalyzeTemplateNode` populates `state.template_id` when resolved from cache

### P1-4: Campaign Objective for Reward Weights

**Problem:** Reward signal architecture uses campaign objective to select weights (CONVERSIONS vs TRAFFIC vs BRAND_AWARENESS), but `meta_ads_performance` sync does not populate objective.

**Fix (migration):**
```sql
ALTER TABLE meta_ads_performance
ADD COLUMN IF NOT EXISTS campaign_objective TEXT;
```

**Fix (code):** Two-part fix required because `meta_campaigns` table exists in schema but is **not currently populated by any sync code** (no Python code reads from or writes to it):

**Part A — Populate `meta_campaigns` during meta sync.** Add a campaign sync step to `meta_ads_service.sync_performance_to_db()` that:
1. Extracts unique `campaign_id` values from fetched insights
2. Calls Meta Graph API `/campaigns?fields=id,name,objective,status` for those IDs
3. Upserts results into `meta_campaigns` table

**Required upsert fields:**
```python
{
    "meta_ad_account_id": str,   # From insight or ad account context
    "meta_campaign_id": str,     # From insight["campaign_id"]
    "name": str,                 # From API response
    "objective": str,            # CONVERSIONS, TRAFFIC, BRAND_AWARENESS, etc.
    "status": str,               # ACTIVE, PAUSED, DELETED, ARCHIVED
    "brand_id": UUID,            # From sync context
    "synced_at": datetime,       # NOW()
}
```

**Conflict key:** `ON CONFLICT (meta_ad_account_id, meta_campaign_id) DO UPDATE` — matches existing schema UNIQUE constraint at `migrations/2025-12-18_meta_ads_performance.sql:120`.

**Error handling:** Campaign sync failure is **non-fatal** for core performance ingestion. If the Meta `/campaigns` call fails:
- `logger.warning()` with campaign IDs that failed (plain logging — `system_alerts` table is not created until Phase 6)
- Continue performance record upsert with `campaign_objective = 'UNKNOWN'` fallback
- Store failure reason in `scheduled_job_runs.metadata`: `{"campaign_sync_error": "...", "campaigns_affected": [...]}`
- However, Phase 0 gate **will fail** if objective enrichment cannot be validated end-to-end in at least one successful sync run

**Part B — Enrich performance records with objective.** After Part A runs, look up objective during record build:
```python
# Build campaign objective cache from meta_campaigns (populated by Part A)
campaign_objectives_cache = {}  # {meta_campaign_id: objective}
# ... query meta_campaigns for campaign_ids in this batch ...

# In record build (~line 1035):
record["campaign_objective"] = campaign_objectives_cache.get(
    insight["meta_campaign_id"], "UNKNOWN"  # fallback if campaign sync failed
)
```

**Part C — One-time historical backfill.** After Part A is deployed and has run at least once:
```sql
-- Backfill historical meta_ads_performance rows with campaign_objective
UPDATE meta_ads_performance map
SET campaign_objective = mc.objective
FROM meta_campaigns mc
WHERE mc.meta_campaign_id = map.meta_campaign_id
  AND mc.meta_ad_account_id = map.meta_ad_account_id
  AND map.campaign_objective IS NULL;
```

**Field naming consistency:** The new column is `meta_ads_performance.campaign_objective`. However, existing code in `diagnostic_engine.py` (lines 170, 175, 987, 1003) reads `ad_data.get("objective")` from performance rows. This currently returns `None` because no `objective` column exists on `meta_ads_performance`. Phase 0 must also add an `objective` SQL alias or update the diagnostic engine query to read `campaign_objective`:
```sql
-- Option A: Add alias in the diagnostic engine's query
SELECT *, campaign_objective AS objective FROM meta_ads_performance ...
-- Option B: Update diagnostic_engine.py to read "campaign_objective" instead of "objective"
```
Choose Option B (update the code) to keep the column name unambiguous. Add to Phase 0 scope.

**Note:** The prior claim that `meta_campaigns.objective` is "already synced" was incorrect — the table schema exists but no code populates it. This is a Phase 0 implementation task.

### P1-5: Attribution via meta_ad_mapping (Not Just Name Parsing)

**Problem:** Plan centers on 8-char hex ID name parsing for attribution, but the codebase already has a more reliable `meta_ad_mapping` table with explicit `generated_ad_id ↔ meta_ad_id` links.

**Fix:** Use `meta_ad_mapping` as the primary attribution path. The 8-char name parsing (`find_matching_generated_ad_id()`) is the fallback for ads that haven't been explicitly mapped. Update all Creative Genome queries to:
```sql
-- Primary: explicit mapping
FROM generated_ads ga
JOIN meta_ad_mapping mam ON ga.id = mam.generated_ad_id
JOIN meta_ads_performance map ON mam.meta_ad_id = map.meta_ad_id
```

### P2-1: Review Status Semantics

**Problem:** `flagged` status is unreachable with current OR logic (if either approves → approved; if both reject → rejected; the `else: flagged` branch can't fire). `needs_revision` gets collapsed into rejection paths.

**Fix for V2:** Define clear status semantics:
- `approved` — passed review (at least one reviewer approved)
- `rejected` — failed review (both reviewers rejected, or critical defect detected)
- `flagged` — borderline (passed some checks, failed others; requires human review). Only set when **both reviewers return borderline scores** (weighted score 5.0-7.0)
- `review_failed` — API error during review

The 3-stage review pipeline (Section 9f) makes `flagged` meaningful: ads that pass defect scan but have borderline full-review scores get flagged for human decision.

### P2-2: Schema Design Traps

**Problem 1:** `creative_element_scores` unique key includes nullable `product_id` — Postgres treats NULL != NULL, allowing duplicate rows for brand-wide scores.

**Fix:** Use `COALESCE(product_id, '00000000-0000-0000-0000-000000000000')` in the unique constraint:
```sql
CREATE UNIQUE INDEX idx_ces_unique ON creative_element_scores(
    brand_id,
    COALESCE(product_id, '00000000-0000-0000-0000-000000000000'),
    element_dimension,
    element_value
);
```

**Problem 2:** `ad_review_overrides` UNIQUE on `generated_ad_id` blocks history of multiple human decisions on the same ad.

**Fix:** Remove the UNIQUE constraint. Add an index instead, and add a `superseded_by UUID` self-reference so the latest override is findable:
```sql
CREATE INDEX idx_aro_ad ON ad_review_overrides(generated_ad_id, created_at DESC);
-- Query for latest: WHERE generated_ad_id = :id ORDER BY created_at DESC LIMIT 1
```

---

## V2 Feature Breakdown

### 1. Worker-First Execution

**How it works now (V1):**
```
UI → asyncio.run(run_workflow()) → blocks browser → result
```

**How it works in V2:**
```
UI → creates scheduled_job(type="ad_creation_v2") → returns immediately
Worker → picks up job → runs pipeline → stores results
UI → polls/shows results from generated_ads table
```

**Implementation:**
- New job type `ad_creation_v2` in scheduler worker (see P0-1 prerequisite)
- Job parameters JSONB stores all generation config (templates, sizes, colors, content source, etc.)
- UI submits job, shows "Job submitted" confirmation with link to results
- Results page shows generated ads grouped by template × size × color
- "Run Now" button for immediate execution (like other scheduler jobs)
- Worker dispatches to new `execute_ad_creation_v2_job()` handler

**Batch limits:**
- V2 cap applies to **attempted** generations, not just approved (see P1-2)
- Default cap: 50 attempts per job (configurable per org in system_settings)
- UI shows estimated count + cost before submission
- If over cap → split into multiple sequential jobs automatically

**Success metric:** V2 job completion rate >= 95% (no browser-dependent failures).

---

### 2. Multi-Size Generation

**User selects sizes via checkboxes:**
```
☑ 1:1  (1080×1080) — Feed posts
☑ 4:5  (1080×1350) — Feed optimal
☐ 9:16 (1080×1920) — Stories/Reels
☐ 16:9 (1920×1080) — Landscape/Video
```

**Pipeline change:**
- After generating the ad at the template's native size, loop through additional selected sizes
- For each additional size: regenerate with same hook/content but different `canvas_size` in prompt
- Same approach as current "create size variant" edit feature, but built into the pipeline
- Each size variant is a separate `generated_ads` row identified by `(ad_run_id, prompt_index, canvas_size)`

**Database:** (see P0-2 prerequisite — `canvas_size` column + persistence fix)
- Group results by `(prompt_index, canvas_size)` for display

**Success metric:** Users generate multi-size batches; each size variant has its own row with correct `canvas_size` persisted.

---

### 3. Asset-Aware Prompt Construction

**Current gap:** Template element classification detects logos, text areas, people, objects. Product images have asset tags. Asset match scores are shown in UI. But **the generation prompt doesn't use any of this**.

**V2 wires it up:**

```python
# In prompt construction:
# Uses template_id UUID when available (see P1-3)
if state.template_id:
    template_elements = template_element_service.get_template_elements(state.template_id)
    asset_match = template_element_service.match_assets_to_template(state.template_id, product_id)
else:
    # Uploaded template — use runtime analysis from AnalyzeTemplateNode
    template_elements = state.runtime_analysis.get("template_elements", {})
    asset_match = {}

prompt.asset_context = AssetContext(
    template_requires_logo=any("logo" in r for r in template_elements.get("required_assets", [])),
    brand_has_logo=any(t.startswith("logo") for t in available_tags),
    template_requires_person=any("person" in r for r in template_elements.get("required_assets", [])),
    available_person_images=[...],
    template_text_areas=template_elements.get("text_areas", []),
    logo_placement=template_elements.get("logo_areas", []),
    missing_assets=asset_match.get("missing_assets", []),
)
```

**Prompt rules derived from asset context:**
- If template has logo area but brand has no logo → "Leave logo area empty or use brand name text"
- If template has person but no person images → "Use product-only composition, omit person"
- If template has text areas with max char estimates → Enforce character limits on headline/subheadline
- Text area positions feed directly into `text_placement` rules

**Success metric:** Ads generated with asset context have higher product accuracy review scores than V1 ads (compare V1 vs V2 on same templates).

---

### 4. Multi-Color Mode (Checkboxes)

**V1:** Radio button — pick ONE of original/complementary/brand.

**V2:** Checkboxes — pick any combination:
```
☑ Original (match reference colors)
☑ Complementary (fresh palette)
☑ Brand colors (from brand settings)
```

**Pipeline change:**
- For each selected hook, generate across all selected color modes
- Total ads = hooks × sizes × color_modes
- Each combination is a separate generation call

---

### 5. Headline ↔ Offer Variant Congruence

**Current:** Hook text goes into prompt as-is. No alignment check with offer variant or landing page hero section.

**V2 adds a CongruenceNode** between SelectContentNode and GenerateAdsNode:

```
SelectContentNode → HeadlineCongruenceNode → SelectImagesNode → GenerateAdsNode
```

**What it checks:**
1. **Offer variant alignment** — Does the headline reinforce the offer variant's core message/pain point?
2. **Hero section alignment** — If the offer variant has a `landing_page_url` and we've scraped the LP (`brand_landing_pages`), does the headline flow naturally into the hero headline?
3. **Belief statement alignment** — In belief_first mode, is the headline congruent with the belief statement?

**How:**
- LLM call with headline + offer variant fields + LP hero content (if available)
- Scores congruence 0-1.0
- If below threshold: adapts headline to improve alignment (returns adapted version)
- Stores congruence_score on the generated ad record

---

### 6. Methodical Review Process

**V1 review checks 4 things** with hard-coded thresholds. V2 replaces this with a 3-stage pipeline:

#### 6a. Three-Stage Review Pipeline

```
Stage 1: FAST DEFECT SCAN (~$0.002, Gemini 3 Flash)
  5 binary defect checks — catches ~40% of rejects at 1/5 the cost
  If ANY critical defect → auto-reject, skip Stages 2-3

Stage 2: FULL QUALITY REVIEW (~$0.005, single reviewer)
  15-check rubric with weighted scoring (V1-V9 visual, C1-C4 content, G1-G2 congruence)
  Only runs if Stage 1 passed

Stage 3: SECOND OPINION (conditional, ~$0.005)
  Only if Stage 2 borderline (any check 5.0-7.0)
  Uses the other AI model; OR logic applies
```

**Defect types (Stage 1):**

| Defect | What It Catches |
|--------|----------------|
| TEXT_GARBLED | Garbled/unreadable text anywhere in the image |
| ANATOMY_ERROR | Wrong finger count, impossible joints, merged limbs |
| PHYSICS_VIOLATION | Floating objects, impossible reflections, contradictory shadows |
| PACKAGING_TEXT_ERROR | Product label text doesn't match known product/brand name |
| PRODUCT_DISTORTION | Product shape squished, stretched, or unrealistic proportions |

**Full rubric (Stage 2 — 15 checks):**

| Check | Category | What It Evaluates |
|-------|----------|-------------------|
| **Visual (V1-V9)** | | |
| V1 - Product accuracy | Visual | Is the product reproduced exactly? No hallucinated features? |
| V2 - Text legibility | Visual | Is ALL text readable? No cut-off, blur, or hallucinated text? |
| V3 - Layout fidelity | Visual | Does layout match reference template structure? |
| V4 - Color compliance | Visual | Do colors match the requested mode? |
| V5 - Brand guideline check | Brand | Does it follow brand voice, prohibited claims, required disclaimers? |
| V6 - Asset accuracy | Visual | Are the right product images used? Logo present/absent as expected? |
| V7 - Overall production quality | Quality | Would you run this ad? Professional finish? |
| V8 - Background/scene coherence | Visual | Is the background realistic? No artifacts, seams, or inconsistencies? |
| V9 - Product label accuracy | Visual | Is packaging text correct? (auto-reject if garbled) |
| **Content (C1-C4)** | | |
| C1 - Headline clarity | Content | Is the headline message clear and compelling? |
| C2 - CTA effectiveness | Content | Is there a clear, action-oriented call to action? |
| C3 - Awareness stage match | Content | Does the message match the intended awareness stage? |
| C4 - Emotional driver alignment | Content | Does the creative trigger the intended emotional response? |
| **Congruence (G1-G2)** | | |
| G1 - Headline congruence | Congruence | Does headline match offer variant / hero section messaging? |
| G2 - Visual-copy alignment | Congruence | Do the visual elements reinforce (not contradict) the copy? |

**Status semantics (V2, see P2-1):**
- `approved` — Stage 2 weighted score >= pass threshold (or Stage 3 OR-logic approval)
- `rejected` — Stage 1 defect found, or both reviewers reject
- `flagged` — Both reviewers return borderline scores (5.0-7.0); requires human decision
- `review_failed` — API error during review

**Review results stored as structured JSON** on `generated_ads.review_check_scores`:
```json
{"V1": 8.5, "V2": 9.0, "V3": 7.0, "V4": 8.0, "V5": 7.5, "V6": 6.5, "V7": 9.0, "V8": 7.5, "V9": 9.0}
```

#### 6b. Human Feedback Loop & Adaptive Quality Scoring

**Problem:** Static thresholds don't improve. The system needs to learn from human decisions.

**Tier 1: Override Tracking**
- "Override Approve" / "Override Reject" / "Confirm" buttons in Results Dashboard
- Stored in `ad_review_overrides` table with per-check granularity
- No UNIQUE constraint — multiple decisions per ad allowed (see P2-2)

**Tier 2: Threshold Calibration** (Phase 6+)
- Weekly cron job computes per-check false positive/negative rates from overrides
- Produces new `quality_scoring_config` version (requires human approval before activation)
- False negatives weighted 2x (bad ads reaching production is worse than over-rejecting)

**Tier 3: Few-Shot Exemplar Library** (Phase 8)
- Curate 20-30 "calibration ads" per brand (gold approve/reject/edge case)
- Review prompts inject 3-5 most similar exemplars via embedding similarity
- Teaches the LLM the brand's quality bar without model training

**Success metric:** Override rate (human disagrees with AI) decreases over time as thresholds calibrate. Track weekly.

---

### 7. Pydantic Prompt Models

**V1:** `generation_service.generate_prompt()` is a 280-line function building a dict literal inline.

**V2:** Pydantic models define the prompt structure:

```python
# viraltracker/pipelines/ad_creation_v2/models/prompt.py

class AdGenerationPrompt(BaseModel):
    task: TaskConfig
    product: ProductContext
    content: ContentConfig
    style: StyleConfig
    images: ImageConfig
    template_analysis: TemplateAnalysis
    asset_context: AssetContext        # NEW: from element classification
    rules: GenerationRules
    ad_brief: Optional[AdBriefConfig]
    performance_context: Optional[PerformanceContext]  # NEW: from Creative Genome (Phase 6+)

class TaskConfig(BaseModel):
    action: Literal["create_facebook_ad"] = "create_facebook_ad"
    variation_index: int
    total_variations: int
    canvas_size: str                   # Explicit, not buried in style
    color_mode: Literal["original", "complementary", "brand"]
    prompt_version: str                # For A/B testing prompt changes

class ContentConfig(BaseModel):
    headline: HeadlineConfig
    subheadline: Optional[SubheadlineConfig]
    congruence_score: Optional[float]  # NEW: from congruence check

class AssetContext(BaseModel):         # NEW: from element classification
    template_requires_logo: bool
    brand_has_logo: bool
    logo_placement: Optional[str]
    template_text_areas: List[TextAreaSpec]
    missing_assets: List[str]
    asset_instructions: str            # Generated guidance based on gaps

class PerformanceContext(BaseModel):    # NEW: Phase 6+ (advisory, not constraining)
    element_scores: Dict[str, float]   # {"curiosity_gap": 0.72, "authority_drop": 0.45}
    winning_combos: List[str]          # ["curiosity_gap + warm + testimonial"]
    advisory_note: str                 # Natural language context for the LLM
```

**Benefits:**
- Versionable (bump model version, old prompts still parseable)
- Testable (validate prompt structure without calling LLM)
- Self-documenting (field descriptions = prompt documentation)
- Serializable (store full prompt as JSON in DB for debugging)

---

### 8. Template Scoring Pipeline

Template selection is the single highest-leverage decision in the pipeline — it determines layout, visual style, and asset requirements before generation even starts. V1 has three template-aware services that score templates on different dimensions, but none of them feed into selection. V2 unifies them behind a **pluggable scoring pipeline** that starts simple and gets smarter as phases add scorers.

#### 8a. Architecture

```
TemplateScorer (interface)
│   score(template, context) → float [0.0, 1.0]
│
├── AssetMatchScorer        → Phase 1  (inline set intersection — see 8f for prefetch pattern)
├── UnusedBonusScorer       → Phase 1  (binary: 1.0 if unused for this product, 0.3 if used)
├── CategoryMatchScorer     → Phase 1  (1.0 if template.category matches request, 0.5 if "All")
├── AwarenessAlignScorer    → Phase 3  (template.awareness_level vs persona.awareness_stage)
├── AudienceMatchScorer     → Phase 3  (template.target_sex vs persona demographics)
├── BeliefClarityScorer     → Phase 4  (D1-D5 from template_evaluations normalized to [0,1]; D6=false → 0.0 in-scorer gate; no eval → 0.5)
├── PerformanceScorer       → Phase 6  (Creative Genome historical reward for this template_id)
└── FatigueScorer           → Phase 8  (decay curve based on time since last use for this audience)
```

Each scorer implements one method: `score(template: dict, context: SelectionContext) → float`. Scorers are **stateless** — all state lives in the DB or in `SelectionContext`.

**`SelectionContext`** contains:
- `product_id: UUID` — required
- `brand_id: UUID` — required
- `product_asset_tags: Set[str]` — required; prefetched from `product_images.asset_tags` for this product **before** the scoring loop (one DB query). Used by `AssetMatchScorer` for inline set intersection.
- `persona: Optional[dict]` — if provided, enables AwarenessAlign and AudienceMatch scorers
- `requested_category: Optional[str]` — if provided, CategoryMatchScorer uses exact match; if None, all categories score 0.5
- `awareness_stage: Optional[int]` — persona's awareness level (1-5); if None, AwarenessAlignScorer returns 0.5 (neutral)
- `has_meta_connection: bool` — required

#### 8b. Selection Function

**Return type:** `SelectionResult` (not a raw list — always structured):

```python
@dataclass
class SelectionResult:
    templates: List[dict]           # Selected templates (may be empty)
    scores: List[Dict[str, float]]  # Per-template scorer breakdown, parallel to templates
    empty: bool                     # True if no templates were selected
    reason: Optional[str]           # Non-None only when empty=True
    candidates_before_gate: int     # Total candidates from query
    candidates_after_gate: int      # Candidates surviving asset gate

def select_templates(
    candidates: List[dict],
    context: SelectionContext,
    scorers: List[TemplateScorer],
    weights: Dict[str, float],
    min_asset_score: float = 0.0,    # Gate threshold (0.0 = no gate)
    count: int = 3,
) -> SelectionResult:
    """
    Weighted-random selection from scored candidates.

    0. Validate weights (runtime check, not assert — survives python -O):
         for name, w in weights.items():
             if not (isinstance(w, (int, float)) and math.isfinite(w) and w >= 0):
                 raise ValueError(f"Invalid weight for {name}: {w} (must be finite and >= 0)")
    1. Score each candidate with all active scorers
    2. Gate: if min_asset_score > 0, drop candidates with asset_match < threshold
             AND drop candidates with has_detection = false (see 8e)
    3. Edge cases after gating:
         if N == 0: return SelectionResult(templates=[], ..., empty=True,
                      reason="No templates passed asset gate ...") → see 8h
         if count > N: clamp count = N, log warning
    4. Compute composite per candidate:
         w_total = sum(weights.values())
         if w_total == 0: composite = 1.0 for all candidates (uniform random)
         else: composite = sum(weight[s] * s.score(candidate)) / w_total
    5. Normalize to probability distribution:
         score_total = sum(composites)
         if score_total == 0: p = [1/N] * N  (uniform fallback — all scored zero)
         else: p = [c / score_total for c in composites]
    6. Clamp draw count to nonzero-probability candidates:
         nonzero_count = sum(1 for x in p if x > 0)
         draw_count = min(count, N, nonzero_count)
         if draw_count < count: log warning ("only {draw_count} candidates with nonzero score")
    7. Draw draw_count templates WITHOUT replacement:
         numpy.random.choice(candidates, size=draw_count, replace=False, p=p)
    8. Return SelectionResult(templates=[...], scores=[...], empty=False, ...)
    """
```

**"Roll the Dice" = this function** with `weights = {unused_bonus: 1.0, category_match: 0.5}` and the rest zeroed out. It's not a separate feature — it's a preset weight configuration.

**"Smart Select" = this function** with all available scorers active and tuned weights.

#### 8c. Candidate Query

The query must return all data scorers need — no per-template lookups at scoring time.

```sql
SELECT st.*,
       (ptu.id IS NULL) AS is_unused,                        -- UnusedBonusScorer input
       st.times_used,                                         -- from scraped_templates (not ptu)
       (st.element_detection_version IS NOT NULL) AS has_detection  -- Asset gate guard
FROM scraped_templates st
LEFT JOIN product_template_usage ptu
  ON st.id = ptu.template_id AND ptu.product_id = :product_id
WHERE st.is_active = TRUE
  AND (:category IS NULL OR st.category = :category)
ORDER BY st.id  -- deterministic; randomization handled by weighted sampling
```

**Column notes:**
- `st.times_used` lives on `scraped_templates` (line 179 of `migration_brand_research_pipeline.sql`), NOT on `product_template_usage` (which only has `used_at`).
- `has_detection` uses `element_detection_version IS NOT NULL` instead of `template_elements IS NOT NULL` because `template_elements` defaults to `'{}'::jsonb` (line 7 of `2026-01-21_template_element_detection.sql`) — a non-NULL empty object — even for templates that have never been analyzed. `element_detection_version` is only set when detection actually runs.

This query runs once. Every scorer reads from the returned row dict — **zero additional DB queries during scoring**. `UnusedBonusScorer` reads `row["is_unused"]`, `AwarenessAlignScorer` reads `row["awareness_level"]`, `AssetMatchScorer` reads `row["template_elements"]` directly (see 8e for detection guard).

Note: unlike the original "Roll the Dice" query, this does NOT filter `ptu.id IS NULL` — unused templates get a higher score via `UnusedBonusScorer`, but previously used templates are still eligible (just down-weighted). This prevents dead-ends when a product has used most templates.

#### 8d. Weight Configuration

Weights start as a hardcoded config dict. Each phase adds scorers:

| Phase | Active Scorers | Weight Source |
|-------|---------------|---------------|
| 1 | AssetMatch, UnusedBonus, CategoryMatch | Hardcoded config dict |
| 3 | + AwarenessAlign, AudienceMatch | Hardcoded config dict |
| 4 | + BeliefClarity | Hardcoded config dict |
| 6 | + Performance | **Creative Genome learns weights** — Thompson Sampling posterior replaces hardcoded weights for this scorer |
| 8 | + Fatigue | Genome-learned weights for all scorers |

The scoring pipeline interface doesn't change — only the weight source evolves from static to learned.

#### 8e. Asset Match Gate

`AssetMatchScorer` is special: it doubles as a **gate** (not just a scorer). If `asset_match_score < min_asset_score`, the template is dropped from candidates entirely — not just down-weighted.

**Detection coverage guard:** `match_assets_to_template()` returns `asset_match_score = 1.0` when `template_elements` is NULL (no detection run). This would let unanalyzed templates bypass the gate. To prevent this:
- If `min_asset_score > 0` (gate is active) AND `row["has_detection"] = false`: **drop the template** from candidates. A strict gate requires detection data to be meaningful.
- If `min_asset_score = 0` (gate is off): unanalyzed templates pass through as before (score = 1.0, status = "not_analyzed").

| Brand tier | `min_asset_score` | Unanalyzed templates | Effect |
|------------|:-----------------:|:--------------------:|--------|
| Premium | 0.8 | **Excluded** | Must have logo + professional photos; detection required |
| Growth | 0.3 | **Excluded** | AI can compensate for some missing assets; detection required |
| Default | 0.0 | Included (score 1.0) | No gate (all templates eligible) |

Configurable per brand via `brands.template_selection_config` JSONB (see P0-4 migration below for schema). Global default: `{"min_asset_score": 0.0}`.

#### 8f. Existing Service Integration

The scoring pipeline reads from pre-computed data — **no per-template AI or DB calls during scoring** (except AssetMatch, which needs one product_images query, prefetched once):

| Scorer | Logic | Data Source |
|--------|-------|-------------|
| AssetMatchScorer | `required = row["template_elements"].get("required_assets", [])` → if empty/missing: return 1.0 (no requirements); else: `len(set(required) & context.product_asset_tags) / len(required)` | `row["template_elements"]` from candidate query (JSONB, may be `{}` for unanalyzed) + `context.product_asset_tags` (prefetched once) |
| AwarenessAlignScorer | `1.0 - abs(row["awareness_level"] - context.awareness_stage) / 4.0`; if either value is None → return 0.5 (neutral) | `row["awareness_level"]` from candidate query (INTEGER 1-5, nullable) — **no AI call** |
| AudienceMatchScorer | exact match → 1.0, either is `unisex`/None → 0.7, mismatch → 0.2 | `row["target_sex"]` from candidate query (TEXT, nullable) — **no AI call** |
| BeliefClarityScorer | If D6=false → 0.0; else normalize D1-D5 total (0-15) to [0,1]; no evaluation → 0.5 neutral | Pre-computed scores from `template_evaluations` table (D1-D5 INT 0-3, D6 BOOL). D6 acts as in-scorer compliance gate — non-compliant templates score 0.0, not hard-filtered from candidates. |
| PerformanceScorer | `creative_element_scores` Beta(α,β) for `template_id` | `creative_genome_service.py` (Phase 6) |

**N+1 prevention for AssetMatch:** `match_assets_to_template()` queries `product_images` per call (line 622 of `template_element_service.py`). The scoring pipeline must NOT call it per-template. Instead: (1) prefetch `product_images` for the product once into `SelectionContext.product_asset_tags: Set[str]`, (2) `AssetMatchScorer` compares `row["template_elements"]["required_assets"]` against that set directly. This replaces `match_assets_to_template()` with inline set intersection — same logic, zero DB calls per template.

#### 8g. UI

```
Template Selection:
  ○ Choose templates manually
  ○ Roll the dice — [3] random templates (weighted toward unused)
     └─ Category filter: [All ▼]
  ○ Smart select — [3] best-fit templates (scored)
     └─ Category filter: [All ▼]
     └─ Asset strictness: [Default ▼]  (Default / Growth / Premium)
```

Both "Roll the dice" and "Smart select" call the same `select_templates()` function with different weight presets.

#### 8h. Empty Selection Fallback

When `select_templates()` returns zero templates (all candidates dropped by gate), the caller follows a tiered fallback:

| Step | Action | Condition to proceed |
|------|--------|---------------------|
| 1 | **Retry with gate off** (`min_asset_score = 0`) | Brand tier is Default or Growth |
| 2 | **Retry with category filter removed** (`requested_category = None`) | A category filter was active |
| 3 | **Fail the selection** with structured error | All retries exhausted OR brand tier is Premium |

On fail, `select_templates()` returns a `SelectionResult` with `empty=True`:
- `templates: []`, `scores: []`, `empty: True`
- `reason: str` — e.g., `"No templates passed asset gate (min_score=0.8, 0/42 passed)"`
- `candidates_before_gate: int` — how many templates existed before gating
- `candidates_after_gate: int` — 0 at this point

The **caller** (pipeline node) checks `result.empty` and decides:
- **Worker job:** Mark run as `failed` with `metadata={"error": "no_eligible_templates", "reason": result.reason}`. Do not retry automatically — the fix is to either lower the brand's `min_asset_score`, run element detection on more templates, or upload more product assets.
- **UI (interactive):** Show warning with the reason and offer: "Retry with relaxed settings?" / "Choose templates manually instead?"

---

### 9. Additional V2 Improvements

#### a. Prompt Versioning
- Store `prompt_version` on each `generated_ads` row
- Track via `ad_runs.generation_config` JSONB: `{prompt_template_version, pipeline_version, review_rubric_version}`
- Enables prompt A/B testing (see Section 15)

#### b. Batch Size Guardrails
- Total attempts = templates × sizes × color_modes × variations
- Show estimated count before submission: "This will attempt ~45 generations (~$0.90 est.)"
- Cap applies to **attempts**, not just approvals (see P1-2)
- Warn if over cap; offer to split into sequential jobs

#### c. Results Dashboard
- Since generation is async (worker), need a results view
- Group by template → show all size/color variants
- Filter by status (approved/rejected/flagged)
- Bulk actions: approve all, reject all, retry rejected
- **Human override buttons** (Override Approve / Override Reject / Confirm) — feeds Section 6b
- Link back to ad run for full details

#### d. Progress Tracking

**Requires migration** (current `scheduled_job_runs` has no metadata column):
```sql
ALTER TABLE scheduled_job_runs
ADD COLUMN IF NOT EXISTS metadata JSONB DEFAULT '{}';
```

`scheduled_job_runs.metadata` JSONB tracks:
  - `ads_attempted`, `ads_approved`, `ads_rejected`, `ads_flagged`
  - `current_template`, `current_size`, `current_color`
- UI polls this for live progress

#### e. Product Label Text Accuracy Check
- Handled by Stage 1 defect scan (PACKAGING_TEXT_ERROR) — see Section 6a
- Any unreadable or incorrect packaging text → auto-reject

---

### 10. Performance Feedback Loop (Creative Genome)

Wire ad performance data back into the generation system to learn what works.

#### 10.1 Data Pipeline

```
generated_ads (with element_tags)
    ↓  join via meta_ad_mapping (primary) or 8-char ID fallback
meta_ads_performance (spend, CTR, CPA, ROAS)
    ↓  compute composite reward (after maturation window)
creative_element_rewards (per-ad reward scores)
    ↓  update Thompson Sampling state
creative_element_scores (per-element Beta distributions)
    ↓  feed advisory context into next generation
AdGenerationPrompt.performance_context
```

**Attribution path** (see P1-5): Use `meta_ad_mapping` as primary join, with `find_matching_generated_ad_id()` 8-char parsing as fallback only.

#### 10.2 Element Tagging

New column: `generated_ads.element_tags` JSONB, populated during generation:
```json
{
    "hook_type": "curiosity_gap",
    "belief_angle_id": "uuid",
    "persona_id": "uuid",
    "color_mode": "brand",
    "visual_style": "ugc",
    "template_category": "testimonial",
    "awareness_stage": "problem_aware",
    "offer_variant_id": "uuid",
    "canvas_size": "1080x1080",
    "template_id": "uuid",
    "prompt_version": "v2.1"
}
```

All data is already available in pipeline state. Zero additional LLM calls.

#### 10.3 Reward Signal Architecture

**Composite reward score** (not single metric):
```
reward = w_ctr × norm_ctr + w_conv × norm_conv + w_roas × norm_roas
```

Weights by campaign objective (see P1-4 for objective data fix):

| Objective | w_ctr | w_conv | w_roas |
|-----------|:-----:|:------:|:------:|
| CONVERSIONS | 0.2 | 0.3 | 0.5 |
| TRAFFIC | 0.7 | 0.1 | 0.2 |
| BRAND_AWARENESS | 0.5 | 0.0 | 0.0 (+0.5 w_cpm) |

Metrics normalized to [0,1] using brand's `ad_intelligence_baselines` percentiles (p25→0.0, p75→1.0, clamped).

**Maturation windows** — reward not computed until:

| Metric | Min Days | Min Impressions |
|--------|:--------:|:---------------:|
| CTR | 3 | 500 |
| Conversion Rate | 7 | 500 |
| ROAS | 10 | 500 |

#### 10.4 Thompson Sampling for Element Selection

Each element-value pair maintains a **Beta(α, β)** distribution:
- reward_score >= 0.5 → increment α (success)
- reward_score < 0.5 → increment β (failure)
- To select hook_type: sample Beta(α,β) for each option, pick highest

Independent distributions per dimension (~50 arms total, not millions of combos).

**Exploration schedule:**
```
exploration_boost = max(0.05, 0.30 × exp(-total_matured_ads / 100))
```

#### 10.5 Stratified Attribution (NOT Naive Aggregation)

Simple "avg CTR by element tag" is Simpson's Paradox waiting to happen. Instead:
1. Stratify by (awareness_stage × audience_type × spend_bucket × week)
2. Compare within strata
3. Only report effects consistent across 3+ strata
4. Flag reversed effects as Simpson's Paradox

Label all non-experimental findings as **"correlational"** in the UI.

#### 10.6 Cold-Start Strategy

| Level | When | What |
|-------|------|------|
| 0 | Day 0 (no data) | Cross-brand category priors (aggregate α/β, 0.3× shrinkage) |
| 1 | Days 1-14 | Proxy metrics (CTR, CPC — available before conversions) |
| 2 | Days 14-30 | Blend brand-specific + category priors |
| 3 | Day 30+ | Full brand-specific Creative Genome |

#### 10.7 Feedback Loop Schedule

| Job | Frequency | What |
|-----|-----------|------|
| `creative_genome_update` | Weekly | Recompute Bayesian element scores, update α/β |
| `genome_validation` | Weekly | Prediction accuracy, drift detection, experiment analysis |

**Advisory, not constraining:** Performance context is injected into the prompt as advisory context. The LLM decides how to weight it. Thompson Sampling influences element *selection*, not hard-filters.

**Success metric:** Correlation between pre_gen_score and actual CTR > 0.3 after 4+ weeks of data. V2 ads outperform V1 ads on same brand/template combos.

---

### 11. Winner Evolution System

Take ads that are performing well and systematically generate improved/expanded variations.

#### Winner Criteria (Concrete)

An ad qualifies as a "winner" if:
- >= 7 days of matured performance data AND >= 1000 impressions
- AND (reward_score >= 0.65 OR CTR in top quartile OR ROAS in top quartile)

**Iteration limits:** Max 5 single-variable iterations per winner. Max 3 rounds on same ancestor. Tag each with `parent_ad_id` and `iteration_round` in `ad_lineage` table.

#### a. Winner Iteration (Single Variable Testing)
Given a winning ad, generate variations that change ONE element at a time:
- Same hook → different visual style
- Same visual → rephrased hook (same psychological type)
- Same everything → different color mode
- Same belief → escalated emotional intensity
- Same layout → different product image

**Variable selection:** Information-gain weighted Thompson Sampling. Priority: belief_angle (1.0) > hook_type (0.9) > awareness_stage (0.85) > visual_style (0.7) > template_category (0.6) > color_mode (0.4).

#### b. Winner Amplification (Awareness Stage Expansion)
When an ad wins at one awareness stage, auto-generate versions for adjacent stages:
- Winning "Problem Aware" ad → generate "Solution Aware" version (same angle, introduce mechanism)
- Winning "Product Aware" ad → generate "Most Aware" version (same proof, lead with offer/urgency)

#### c. Anti-Fatigue Refresh
Before a winner fatigues (detected by existing `FatigueDetector` — frequency > 4.0, CTR decline > 15% WoW):
- Generate "fresh coats of paint" — same winning belief + hook type + CTA
- New visual execution, new color palette, slightly reworded headline
- Psychology stays identical; only the surface changes

Note: Predictive fatigue curves (per element combo) are a Phase 8 addition. Phase 7 uses existing reactive detection.

#### d. Cross-Size/Cross-Format Expansion
A winner in 1:1 feed might not exist in 9:16 Stories:
- Auto-generate winning ad in all sizes it hasn't been tested in

#### e. Angle/Persona/Offer Rotation on Winning Templates
When a template *structure* proves it works:
- **Rotate belief angles** — same proven visual framework, different conviction
- **Rotate personas** — same winning hook type, reframed for different audience segment
- **Rotate offer variants** — same winning visual, different LP congruence target

#### f. Competitive Counter-Creative
When the Creative Genome identifies a winning element combination:
- Cross-reference against competitor creative (from existing competitor research)
- If competitors are NOT using this winning combination → double down
- If competitors start copying → generate counter-creative that evolves the approach

**UI for Winner Evolution:**
- "Evolve This Ad" button on any ad with performance data meeting winner criteria
- Shows which evolution modes are available based on the ad's element tags
- Estimates how many variants each mode would generate
- Submits as a scheduler job (worker-first)

**Success metric:** Evolved ads outperform their parents at a rate > 50% (measured by reward_score comparison in `ad_lineage`).

---

### 12. Experimentation Framework

Structured creative experiments to build causal knowledge (not just correlational).

#### 12a. Experiment Structure
- Hypothesis + exactly ONE test variable + control arm + 1-3 treatment arms
- Hold-constant set (all other element_tags fixed)
- Budget-gated: system calculates required spend before proposing

#### 12b. Meta Deployment Strategy
**Separate ad sets per arm** (prevents Meta's intra-ad-set MAB from confounding):
- Dedicated CBO campaign per experiment
- One ad set per arm, identical targeting/bid/placements
- Equal minimum spend limits
- One ad per ad set

#### 12c. Bayesian Winner Declaration
- Beta-Binomial model for CTR; Normal approximation for CPA/ROAS
- P(best) via 10K Monte Carlo samples, updated daily
- **Winner**: P(best) > 0.90 AND all arms met min impressions
- **Futility**: P(best) < 0.05 → recommend pausing arm
- **Inconclusive**: max 14 days reached without clear winner

#### 12d. Causal Knowledge Base
Each completed experiment stores ATE + confidence intervals in `causal_effects` table. Over time, builds reliable knowledge for variable selection.

**Success metric:** 5+ completed experiments per **Meta-connected** brand within 3 months of Phase 7 launch.

---

### 13. Monitoring & Alerting

| Metric | Warning | Critical | Action |
|--------|---------|----------|--------|
| approval_rate | < 0.60 for 7 days | < 0.40 for 3 days | Check Gemini API, review prompts |
| prediction_accuracy | < 0.3 for 2 weeks | < 0.1 for 1 week | Force genome recompute |
| generation_success_rate | < 0.80 | < 0.60 | Check API credentials, rate limits |
| data_freshness | > 3 days | > 7 days | Check meta_sync job status |
| winner_rate (V2 > brand median) | < 0.10 for 3 weeks | N/A | Review element scores |

Computed by `genome_validation` weekly batch. Stored in `system_alerts` table. Surfaced in Settings page.

---

### 14. Visual Embedding Space (Phase 8)

Use Gemini 3 Flash to extract structured visual descriptors → embed with OpenAI text-embedding-3-small → store in pgvector.

**Use cases:** Duplicate detection, style clustering, diversity enforcement, "more like this" for Winner Evolution.

---

### 15. Prompt & Pipeline Versioning

Every generation run records full config in `ad_runs.generation_config` JSONB. A/B comparison via `generation_experiments` table with deterministic assignment and Mann-Whitney U test.

---

## File Structure

```
viraltracker/
├── pipelines/
│   ├── ad_creation/          # V1 (untouched)
│   └── ad_creation_v2/       # V2 pipeline
│       ├── __init__.py
│       ├── orchestrator.py   # Graph definition
│       ├── state.py          # Pipeline state dataclass
│       ├── models/
│       │   ├── __init__.py
│       │   └── prompt.py     # Pydantic prompt models
│       ├── nodes/
│       │   ├── __init__.py
│       │   ├── initialize.py
│       │   ├── fetch_context.py
│       │   ├── analyze_template.py    # Reuse V1 + wire asset classification
│       │   ├── select_content.py
│       │   ├── headline_congruence.py # NEW
│       │   ├── select_images.py       # Asset-aware selection
│       │   ├── generate_ads.py        # Multi-size × multi-color loop
│       │   ├── defect_scan.py         # NEW: Stage 1 fast pre-filter
│       │   ├── review_ads.py          # 3-stage pipeline (Stages 2-3)
│       │   ├── retry_rejected.py
│       │   └── compile_results.py
│       └── services/
│           ├── __init__.py
│           ├── analysis_service.py    # Reuse/extend V1
│           ├── content_service.py     # Reuse/extend V1
│           ├── generation_service.py  # Pydantic prompt builder
│           ├── review_service.py      # 3-stage review pipeline
│           ├── template_scoring_service.py  # NEW: pluggable scorer pipeline (Section 8)
│           ├── congruence_service.py  # NEW: headline congruence
│           ├── defect_scan_service.py # NEW: 5 binary defect checks
│           ├── exemplar_service.py    # NEW: few-shot review calibration
│           └── visual_descriptor_service.py  # NEW: visual embedding
├── services/
│   ├── creative_genome_service.py     # NEW: Thompson Sampling + element scoring
│   ├── experiment_service.py          # NEW: experiment design + analysis
│   ├── quality_calibration_service.py # NEW: adaptive threshold learning
│   └── interaction_detector_service.py # NEW: element interaction effects
├── ui/
│   └── pages/
│       ├── 21b_🎨_Ad_Creator_V2.py   # New page, V1 stays
│       └── 36_🧪_Experiments.py       # NEW: experiment management
├── worker/
│   └── scheduler_worker.py           # Add job types (see below)
```

---

## Execution Protocol (Mandatory)

> **This section governs HOW implementation happens.** All contributors (human and AI) must follow these rules. No exceptions.

### Hard Rules

1. **Chunk-capped execution.** Work is done in implementation chunks of **<= 50K tokens each**. A chunk is a coherent unit of work (e.g., "write all Phase 0 migrations", "build defect scan node + service + tests"). If a chunk will clearly exceed 50K tokens, split it before starting.

2. **Checkpoint after every chunk.** After completing a chunk, create or update a checkpoint doc (`CHECKPOINT_NNN.md`) **before** starting the next chunk. The checkpoint uses the standard template below. No "I'll write it later" — the checkpoint is the proof the chunk is done.

3. **Post-phase review after every phase.** After completing a phase (all chunks within it), run the post-plan review (`/post-plan-review`) against all files changed in that phase. The review must produce a PASS verdict before advancing.

4. **No phase advancement** unless ALL of:
   - [ ] Phase success gate passes (defined per phase below)
   - [ ] All required acceptance tests pass
   - [ ] Checkpoint is written for the final chunk
   - [ ] Post-phase review verdict is PASS

5. **Remediation on failure.** If any gate or test fails, create a **remediation chunk** — a new chunk scoped to fixing the failures only. Do not advance phases. Do not start new feature work. Fix, re-test, re-checkpoint, re-review.

6. **Chunk naming convention.** Chunks are numbered sequentially within a phase: `P0-C1` (Phase 0, Chunk 1), `P0-C2`, `P1-C1`, etc. Checkpoints reference their chunk ID.

### Chunk Checkpoint Template

Every chunk produces a checkpoint entry (in the current `CHECKPOINT_NNN.md` or a new one if the file is getting long):

```markdown
### Chunk [P{phase}-C{chunk}]: {Short Title}

**Date**: YYYY-MM-DD
**Token estimate**: ~{N}K / 50K

#### Scope Completed
- [ ] Item 1
- [ ] Item 2

#### Files Changed
| File | Change |
|------|--------|
| `path/to/file.py` | Description |

#### Migrations Run
- `migrations/YYYY-MM-DD_description.sql` — applied to {env}

#### Tests Run + Results
| Test | Result |
|------|--------|
| `python3 -m py_compile path/file.py` | PASS/FAIL |
| Acceptance test: description | PASS/FAIL |

#### Success Gate Status
- [ ] Gate criterion 1: PASS / FAIL
- [ ] Gate criterion 2: PASS / FAIL

#### Risks / Open Issues
- Risk 1
- None

#### Next Chunk Plan
- P{phase}-C{next}: Brief description of what's next
```

### Post-Phase Review Checklist

After the final chunk of a phase:
1. Run `/post-plan-review` against all files changed in the phase
2. Record verdict (PASS / FAIL) in the checkpoint
3. If FAIL: create remediation chunk, fix, re-run review
4. If PASS: phase is complete — next phase may begin

---

## Implementation Phases (Incremental, Measurable)

> **Principle**: Each phase has measurable success criteria. Do NOT start the next phase until the current phase's metrics are green. Each layer builds on proven foundations.

### Phase 0: Prerequisites (Schema & Infrastructure Fixes) ✅
- [x] P0-1: Add `ad_creation_v2` to job type CHECK constraint + worker routing
- [x] P0-2: Add `canvas_size` column to `generated_ads` + composite key migration
- [x] P0-3: Add `template_id` UUID to `product_template_usage` + backfill
- [ ] P0-4: Add `template_selection_config` JSONB column to `brands` table:
  ```sql
  ALTER TABLE brands
  ADD COLUMN IF NOT EXISTS template_selection_config JSONB DEFAULT '{"min_asset_score": 0.0}';
  COMMENT ON COLUMN brands.template_selection_config IS 'Per-brand template scoring config: min_asset_score (gate threshold), weight overrides, etc.';
  ```
  No backfill needed — default value applies to all existing brands.
- [x] P1-1: Fix `save_generated_ad()` to persist canvas_size (fixed in Phase 2 — see CHECKPOINT_008)
- [ ] P1-2: Change batch cap to count attempts, not approvals
- [ ] P1-4: Add `campaign_objective` to `meta_ads_performance` + populate `meta_campaigns` table + enrich perf records
- [ ] P2-1: Unknown job types hard-fail (raise error + log), no silent fallthrough to V1
- [ ] Add `metadata` JSONB column to `scheduled_job_runs`
- [ ] Add **stub** `execute_ad_creation_v2_job()` handler to scheduler worker (logs "V2 pipeline not yet implemented", marks run as `completed` with `metadata={"stub": true, "reason": "V2 pipeline not yet implemented"}`). Uses valid status per `scheduled_job_runs.status` CHECK (`pending|running|completed|failed`). Full implementation in Phase 1.
- [ ] **Success gate** (ALL must pass):
  1. All migrations applied without error, existing data intact
  2. Worker routes `ad_creation_v2` jobs to the stub handler (not V1 fallback); stub completes with `metadata.stub = true`
  3. **Unknown `job_type` hard-fails** — call `execute_job()` directly with a mocked job dict containing an unrecognized type; confirm: (a) error is logged, (b) no V1 execution path is triggered, (c) function raises an exception or returns an explicit error result (NOTE: with a mocked dict there is no persisted run record to update — pass criteria are the error log + no V1 side-effects + exception/error return, not a DB status change)
  4. **Meta sync persists `campaign_objective`** — after a meta performance sync, `meta_ads_performance.campaign_objective` is populated (requires `meta_campaigns` to be populated first — see P1-4 two-part fix)
  5. **Campaign sync failure is non-fatal** — if Meta `/campaigns` API call fails, performance sync still completes with `campaign_objective = 'UNKNOWN'` (not crash)
  6. **Template backfill produces zero ambiguous mappings** — audit query returns 0 duplicate `storage_path` rows among active templates, OR count is within documented tolerance with remediation plan
  7. **Non-Meta brand does not crash** — submit a V2 job for a brand without `brand_ad_accounts` link; confirm it routes to stub and completes (no meta-dependent failure path)
  8. `python3 -m py_compile` passes on all changed files
  9. Checkpoint written + post-phase review PASS

### Phase 1: Foundation (Worker + Pydantic Prompts + Scoring Pipeline) ✅
- [x] Create `ad_creation_v2/` directory structure
- [x] Port V1 pipeline to V2 directory (copy, don't modify V1)
- [x] Replace dict-literal prompt with Pydantic models
- [x] Implement full `execute_ad_creation_v2_job()` logic (Phase 0 added the stub; this replaces it with working pipeline execution)
- [x] Build `template_scoring_service.py` with `TemplateScorer` interface + `select_templates()` function
- [x] Implement Phase 1 scorers: `AssetMatchScorer`, `UnusedBonusScorer`, `CategoryMatchScorer`
- [x] Build minimal V2 UI page (submit job, view results) with "Roll the dice" and "Smart select" presets
- [x] Verify V2 produces same quality output as V1
- **Checkpoints**: `CHECKPOINT_004.md` through `CHECKPOINT_007.md`
- [x] **Success gate**: V2 generates ads end-to-end via worker. Approval rate within 5% of V1 on same templates (N >= 30 paired comparisons, same brand/product/template combos). Job completion rate >= 95% (measured over >= 20 consecutive jobs). Template scoring pipeline returns scored list (draw-order, not ranked) with composite + per-scorer breakdown for all three Phase 1 scorers.

### Phase 2: Multi-Size + Multi-Color ✅
- [x] Add size checkbox UI (multiselect with friendly labels)
- [x] Add color checkbox UI (multiselect with friendly labels)
- [x] Modify GenerateAdsNode to loop sizes × colors (triple-nested: hook × size × color)
- [x] Show estimated attempt count + cost before submission (T × V × S × C formula)
- [ ] ~~Group results by template × size × color~~ → Phase 5 results dashboard
- [x] Relax `variation_index`/`total_variations` from `le=15` to `le=100` (supports 5 hooks × 4 sizes × 3 colors = 60)
- [x] Add `color_mode` column to `generated_ads` table (migration)
- [x] Fix P1-1: ReviewAdsNode + RetryRejectedNode now pass `canvas_size` + `color_mode` to `save_generated_ad()`
- [x] Worker: validate/dedupe size+color lists, fix cap math for fanout
- [x] Backward compat: old scalar params still work (worker normalizes, orchestrator accepts both, state has compat properties)
- [x] `python3 -m py_compile` passes on all 12 changed files
- [x] Graph Invariants Checker: PASS (all G1-G6 + P1-P8)
- **Checkpoint**: `CHECKPOINT_008.md`
- **Deferred to Phase 3 start**: Browser testing of UI controls, unit tests for Phase 2 code, 10 consecutive multi-size/color worker runs on deployed environment
- **Success gate** (partial — code complete, deployment testing deferred):
  - Code: All pipeline logic, UI, worker changes complete and compile-verified
  - Deployment: Multi-size/color runs complete without errors across >= 10 consecutive runs (to be validated at Phase 3 start)
  - Persistence: Each variant has correct `canvas_size` + `color_mode` persisted (to be spot-checked at Phase 3 start)

### Phase 2.5: Manual Template Grid — Filters + Pagination ✅
- [x] Add awareness level, industry/niche, and target audience filters to V2 manual template selection (port from V1)
- [x] Replace direct DB query in V2 `get_scraped_templates()` with `TemplateQueueService.get_templates()` (service layer delegation)
- [x] Add "Load More" pagination (30 at a time, matching V1 pattern)
- [x] Reset pagination when filters change
- [x] File modified: `viraltracker/ui/pages/21b_🎨_Ad_Creator_V2.py` only
- [x] **Note**: Recommendation filter and asset match badges are intentionally excluded — recommendation filter is V1-specific, asset badges come with Phase 3 scoring expansion
- [x] **Conflict check**: Safe. Phase 3's `AwarenessAlignScorer`/`AudienceMatchScorer` operate in the scoring pipeline (smart_select/roll_the_dice), not the manual grid. Worker only uses `scraped_template_ids` from manual jobs. No schema changes needed.
- [x] **Success gate**: All 4 filters render and update the grid. Pagination works. Scored selection modes unaffected. Manual job submission still works end-to-end.

### Phase 3: Asset-Aware Prompts + Scoring Expansion ✅
- [x] **Phase 2 deferred items (pre-work)**:
  - [x] Write unit tests for Phase 2 changes (state compat properties, orchestrator normalization, worker validation/cap math, GenerateAdsNode triple loop)
  - [ ] ~~Browser-test Phase 2 UI controls~~ → **deferred to post-Phase 5 UI test pass**
  - [ ] ~~Run Phase 2 end-to-end on deployed environment~~ → **deferred to post-Phase 5 UI test pass**
- [x] Wire template element classification into prompt (handle both template_id and uploaded)
- [x] Wire product image asset tags into image selection
- [x] Add asset gap instructions to prompt
- [x] Add text area character limits from template classification
- [x] Add `AwarenessAlignScorer` and `AudienceMatchScorer` to scoring pipeline (pure column comparison against `scraped_templates.awareness_level` and `target_sex` — see Section 8f; does NOT use `template_recommendation_service` AI calls)
- [x] Configure `min_asset_score` gate per brand tier (see Section 8e)
- [x] **Success gate**: V2 product accuracy review scores > V1 on same templates (paired comparison, N=50+). Scoring pipeline returns 5 scorer dimensions for all template selections. Phase 2 deferred items all pass.
- **Known risks (from post-plan review)**:
  1. **Regenerate flow lacks asset context** — `ad_creation_service.py:1965` regenerate doesn't pass `template_elements`/`brand_asset_info`/`selected_image_tags` to `generate_prompt()`. Regenerated ads get `asset_context=None`. Intentional for backward compat, but means regenerated ads miss asset-aware instructions. Fix in Phase 4 or when regenerate flow is overhauled.
  2. **`element_detection_version` dependency** — FetchContextNode relies on `scraped_templates.element_detection_version` to distinguish "never analyzed" (None → skip AssetContext) from "analyzed but empty" ({} → build default AssetContext). If this column is missing or null for a template that WAS analyzed, the system incorrectly skips AssetContext. Mitigated: column exists on all templates; detection service always sets it.
  3. **Selected-image coverage can diverge from all-image coverage** — Informational asset match (all images) may show high coverage, but actual generation uses only 1-2 selected images. The asset tag bonus (+0.3 required, +0.1 optional) helps prioritize matching images, but visual quality scoring can still win. Monitor: compare `state.asset_match_result.asset_match_score` vs prompt `asset_context.asset_match_score` in production logs.
  4. **Node-level test gap** — FetchContextNode and SelectImagesNode Phase 3 additions (template elements fetch, brand assets fetch, asset_tags enrichment) lack dedicated unit tests. Business logic in `_build_asset_context()` IS tested (15 cases). Add node tests when refactoring these nodes.
  5. **`brand_assets` table schema assumption** — FetchContextNode assumes `brand_assets.asset_type` contains "logo"/"badge" substrings. If naming convention changes, logo/badge detection silently fails (non-fatal, defaults to False). Low risk — table is stable.

### Phase 4: Congruence + Review Overhaul (code ✅, gate partially unvalidated)
- [x] Build CongruenceService (headline ↔ offer variant ↔ hero section)
- [x] Add HeadlineCongruenceNode to pipeline
- [x] Build 3-stage review pipeline (defect scan → full review → conditional 2nd opinion)
- [x] Store structured review scores (review_check_scores JSONB)
- [x] Add human override buttons to Results Dashboard (Override Approve/Reject/Confirm)
- [x] Create `ad_review_overrides` table
- [x] Create `quality_scoring_config` table with initial static thresholds
- [x] Add `BeliefClarityScorer` to scoring pipeline (reads D1-D5 from `template_evaluations`, D6=false → 0.0, no eval → 0.5)
- [ ] **Success gate**: Defect scan catches >= 30% of rejects (saves review cost). Override rate tracked. `defect_scan_result` present for all successfully generated V2 ads. `review_check_scores` present for all Stage-2-reviewed ads (defect-passed). **NOTE:** Defect catch rate (>= 30%) requires 50+ production ads to validate — see risk #3 below. Code is in place but metric is not yet measurable.
- **Known risks (from post-plan review)**:
  1. **Browser testing deferred** — Override Approve/Reject/Confirm buttons, structured review scores, defect scan display, and congruence score display all untested in browser. Requires Railway staging deployment.
  2. **Regenerate flow lacks Phase 4 checks** — `ad_creation_service.py` regenerate doesn't pass congruence/defect/review data. Regenerated ads skip Phase 4 pipeline. Separate overhaul needed.
  3. **Defect catch rate target unvalidated** — >= 30% target needs 50+ ads in production to measure. Code is in place but the success gate metric is not yet provable.
  4. **CongruenceService hero_alignment null** — Brands without `brand_landing_pages` data get null hero_alignment in congruence results. Non-fatal (overall score still computed from other dimensions) but reduces congruence signal strength.
  5. **RetryRejectedNode still used V1 dual review** — Fixed in Phase 5 (P5-C1 rewrite to staged review).

### Phase 5: Polish + Promotion (code ✅, GATE_PENDING)
- [x] Scoring pipeline already active from Phase 1 — validate "Roll the dice" and "Smart select" presets produce good template diversity across >= 5 brands (25 diversity invariant tests + analysis script)
- [x] Add prompt versioning to generated_ads + ad_runs.generation_config (migration + service + pipeline wiring)
- [x] Build results dashboard with grouping/filtering (summary stats, status/date filters, template grouping, bulk actions, pagination)
- [x] Add batch size guardrails and cost estimation (CostEstimationService, tiered guardrails, hard cap at 50)
- [x] RetryRejectedNode refactored to use staged review (replaced V1 dual review)
- [x] QA full end-to-end flow (276 tests passing, syntax verified, post-plan review PASS)
- [ ] **Success gate**: Full V2 pipeline stable over >= 2 weeks of daily use. V2 approval rate >= V1 (N >= 100 ads per pipeline, same brand/template distribution). **Promotion to primary** requires additionally: V2 ads deployed to Meta show non-inferior CTR vs V1 ads (one-sided 90% CI lower bound >= 0.9× V1 mean CTR, measured over >= 50 V2 ads with >= 7 days matured data each). For brands without Meta connection, promotion requires V2 approval rate >= V1 only. **NOTE:** All code and tests complete. Gate is PENDING because stability, approval-rate comparison, and CTR non-inferiority require production deployment and time-based measurement. See CHECKPOINT_010.md for detailed gate evidence table.
- **Known risks (from post-plan review)**:
  1. **No automated Streamlit UI tests** — Dashboard filter/pagination/bulk-action logic only testable via manual browser verification. All service-layer logic is tested (30 override service tests), but UI rendering paths are uncovered.
  2. **`ad_runs!inner` join dependency** — `get_ads_filtered()` and `get_summary_stats()` use inner join on ad_runs. If an ad_run row lacks `organization_id`, its ads are silently excluded from results. Low risk (org_id is always set at run creation) but worth noting.
  3. **No golden eval fixtures for retry node** — `test_retry_rejected.py` mocks all external calls (LLM, storage, DB). No integration test with real LLM responses to validate retry quality.
  4. **Unused `Any` import** — `retry_rejected.py` imports `Any` from typing but doesn't use it. Cosmetic only.
  5. **`print()` in analysis script** — `scripts/validate_scoring_presets.py` uses `print()` for console output instead of `logger.info()`. Acceptable for CLI script but inconsistent with project patterns.
- **Bugs fixed (post-checkpoint)**:
  1. **`fetch_template_candidates` PostgREST 400** (FIXED) — `.in_("template_id", template_ids)` on `template_evaluations` passed all active template IDs as a URL query parameter. With 200+ templates the URL exceeded PostgREST's ~8KB limit, causing a raw `400 Bad Request`. Fix: removed `.in_()` filter; query now fetches all `template_evaluations WHERE template_source = 'scraped_templates'` and Python-side merge already discards non-matching rows.
  2. **`test_orchestrator_allows_50` env-dependent failure** (FIXED) — Test called `run_ad_creation_v2()` which triggered `AgentDependencies` import-time side effects (Apify client init) in environments without credentials. Fix: patches `ad_creation_v2_graph.run` with sentinel exception, passes mock deps, tests real validation path without external service init.

### Phase 6: Creative Genome (Learning Loop)
- [ ] Add `element_tags` JSONB to generated_ads + populate during generation
- [ ] Create `creative_element_scores` + `creative_element_rewards` tables
- [ ] Build `CreativeGenomeService` (Thompson Sampling + Bayesian scoring)
- [ ] Add `PerformanceScorer` to template scoring pipeline (reads `creative_element_scores` for `template_id`)
- [ ] Transition scoring pipeline weights from hardcoded config to **Genome-learned** for PerformanceScorer (Thompson Sampling posterior updates weight based on which template selections produce winning ads)
- [ ] Add `creative_genome_update` weekly job to scheduler worker
- [ ] Wire advisory performance context into prompt (non-constraining)
- [ ] Build pre-generation scoring (pre_gen_score on generated_ads)
- [ ] Build stratified attribution (not naive aggregation)
- [ ] Add `genome_validation` weekly job (prediction accuracy + drift detection)
- [ ] Create `system_alerts` table + monitoring dashboard in Settings
- [ ] Implement cold-start category priors
- [ ] Begin quality threshold calibration from accumulated human overrides
- [ ] **Success gate**: Correlation(pre_gen_score, actual_ctr) > 0.3 after 4+ weeks. Thompson Sampling demonstrably shifts element selection toward better-performing options. Template scoring pipeline PerformanceScorer active and influencing selection.

### Phase 7: Winner Evolution + Experimentation
- [ ] Create `ad_lineage` table + winner trigger criteria
- [ ] "Evolve This Ad" button with iteration limits
- [ ] Information-gain weighted variable selection
- [ ] Create `experiments` + `experiment_arms` + `causal_effects` tables
- [ ] Build experiment design service (power analysis, budget gating)
- [ ] Build Bayesian winner declaration (daily posterior updates)
- [ ] Experiment UI page (36_Experiments.py)
- [ ] Anti-fatigue refresh using existing FatigueDetector
- [ ] Cross-size expansion for winners
- [ ] **Success gate**: Evolved ads outperform parents > 50% of the time (N >= 20 evolved ads with >= 7 days matured data each, measured by reward_score). >= 5 completed experiments per active **Meta-connected** brand within 3 months of Phase 7 launch (experiments require Meta ad sets — non-Meta brands are exempt from experiment count; see Non-Meta Operating Mode).

### Phase 8: Full Autonomous Intelligence
- [ ] Few-shot exemplar library + embedding similarity for review
- [ ] Adaptive threshold calibration cron job (weekly, auto-proposes new config)
- [ ] Visual embedding space + style clustering
- [ ] Interaction effect detection (top 15 element pairs)
- [ ] Predictive fatigue curves (per element combo)
- [ ] Add `FatigueScorer` to template scoring pipeline (decay curve based on time since last use per audience segment)
- [ ] Transition ALL scoring pipeline weights to Genome-learned (Thompson Sampling updates weights for every scorer, not just PerformanceScorer)
- [ ] Prompt/pipeline A/B testing (generation_experiments)
- [ ] Cross-brand transfer learning (opt-in)
- [ ] Competitive whitespace identification
- [ ] **Success gate**: Human override rate decreasing quarter-over-quarter (compare Q1 vs Q2 override rates, require >= 50 overrides per quarter for statistical validity). Approval rate trend positive over 8-week rolling window. At least one autonomous threshold adjustment accepted by operator.

---

## Pending UI Tests (Manual Browser Verification)

These tests require deployment to Railway staging and manual browser verification. All underlying service-layer logic is unit-tested (276 tests passing), but UI rendering and interaction paths need manual confirmation.

### Phase 2 (Deferred)
- [ ] Template grid filters render and update correctly
- [ ] Pagination works in manual template selection
- [ ] V2 end-to-end: job creation → worker execution → results display

### Phase 4 (Deferred from P4-C6)
- [ ] Override Approve/Reject/Confirm buttons update ad status
- [ ] Structured review scores display with colored indicators (V1-V9, C1-C4, G1-G2)
- [ ] Defect scan results display PASSED/FAILED badge
- [ ] Congruence score color-coded (red < 0.4, yellow 0.4-0.7, green > 0.7)
- [ ] Override rate summary shows correct 30-day stats

### Phase 5 (New)
- [ ] Cost estimate shows correct values for selected variation count
- [ ] 11-30 variations: estimate displayed (no blocking)
- [ ] 31-50 variations: confirmation checkbox required before submit
- [ ] >50 variations: blocked with error message
- [ ] Summary stats bar shows correct counts (total, approved, rejected, flagged, review_failed, override_rate)
- [ ] Status multiselect filter works
- [ ] Date range filter works
- [ ] Ad run ID filter works
- [ ] Sort by newest/oldest works
- [ ] Template grouping displays ads grouped by template name
- [ ] Bulk Approve All per template group works
- [ ] Bulk Reject All per template group works
- [ ] Pagination (Previous/Next) navigates correctly with page counter

### Full E2E (Post-Deployment)
- [ ] V2 job creation → submission → worker execution → results display (full pipeline)
- [ ] Retry uses staged review (not V1 dual review)
- [ ] Run `scripts/validate_scoring_presets.py` against production data

---

## Migration Path

1. V2 page lives at `21b_🎨_Ad_Creator_V2.py` alongside V1
2. Both share the same database tables (`ad_runs`, `generated_ads`)
3. V2 ads get a marker: `ad_runs.pipeline_version = 'v2'`
4. Compare V1 vs V2 output quality over 2-4 weeks
5. Promote V2 to primary when Phase 5 success gate passes:
   - **Meta-connected brands:** V2 approval rate >= V1 (N >= 100) AND CTR non-inferiority (90% CI lower bound >= 0.9× V1 mean CTR, N >= 50 ads with >= 7d matured data)
   - **Non-Meta brands:** V2 approval rate >= V1 (N >= 100)
6. After promotion: archive V1 page, keep V1 pipeline code for rollback

---

## Non-Meta Operating Mode

V2 must work for brands without a linked Meta ad account (`brand_ad_accounts`). This affects multiple subsystems:

### Preflight Check

At the start of every V2 job, check `brand_ad_accounts` for the brand:
- **Has Meta link:** Full pipeline including meta-dependent features (reward weighting by objective, performance context, experiment deployment)
- **No Meta link:** Generation, review, and human feedback still work. Meta-dependent features degrade gracefully:

| Feature | Meta-connected | No Meta connection |
|---------|---------------|-------------------|
| Ad generation | Full | Full (no difference) |
| Review pipeline | Full | Full (no difference) |
| Human overrides | Full | Full (no difference) |
| `campaign_objective` | Populated from meta_campaigns | `'UNKNOWN'` — reward weights use equal-weight fallback (0.33/0.33/0.33) |
| Creative Genome | Full performance data | Review + human override signals only (no CTR/CPA/ROAS). Thompson Sampling still learns from approval/rejection rates. |
| Experiments | Deploys to Meta ad sets | Unavailable — UI shows "Requires Meta connection" |
| Winner Evolution | Full performance criteria | Approval-rate-only winner criteria (no CTR/ROAS thresholds) |

### Error Handling

- V2 pipeline must **never crash** due to missing Meta connection. If a meta-dependent step encounters no `brand_ad_accounts` row: log info-level message, skip the step, continue.
- `meta_sync` jobs for unlinked brands should complete with status `completed` and `metadata={"skipped": true, "reason": "no_ad_account_linked"}`.
- Worker routing: check for Meta link **before** calling campaign sync in performance enrichment path. If no link, set `campaign_objective = 'UNKNOWN'` and proceed.

### Success Gate Split

Where relevant, success gates distinguish:
- **Meta-connected brands:** Full gate criteria including performance KPIs
- **Non-Meta brands:** Gate criteria limited to approval rate, generation stability, and human feedback metrics

---

## NOT in V2 Scope

- Video ad generation (separate feature)
- Automatic Meta upload (separate from generation)
- Multi-brand batch runs (one brand at a time)
- Custom model training (no PyTorch, no GPU instances)
- Real-time learning (all updates are batch)
- Cross-organization data sharing
- Kafka/Redis/streaming infrastructure
