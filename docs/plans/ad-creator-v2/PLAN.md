# Ad Creator V2 — Plan

> **Status**: DRAFT
> **Created**: 2026-02-12
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

---

## V2 Principles

| Principle | Meaning |
|-----------|---------|
| **Worker-first** | Submit → scheduler job → worker generates → user views results later |
| **Explicit over magic** | User picks sizes, colors, templates — no "random smorgasbord" |
| **Asset-aware prompts** | If we classified the template and tagged the images, USE that data |
| **Pydantic prompts** | Prompt is a Pydantic model, not a dict literal |
| **Parallel V1** | New page `21b_🎨_Ad_Creator_V2.py`, V1 untouched |

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
- New job type `ad_creation_v2` in scheduler worker
- Job parameters JSONB stores all generation config (templates, sizes, colors, content source, etc.)
- UI submits job, shows "Job submitted" confirmation with link to results
- Results page shows generated ads grouped by template × size × color
- "Run Now" button for immediate execution (like other scheduler jobs)
- Worker uses existing `run_ad_creation()` pipeline internally

**Benefit:** User can submit 10 templates × 3 sizes × 3 color modes = 90 ads and go do something else.

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
- Each size variant shares the same `ad_run_id` and `prompt_index`, differentiated by `canvas_size`

**Database:**
- `generated_ads.canvas_size` already exists
- Group results by `(prompt_index, canvas_size)` for display

---

### 3. Asset-Aware Prompt Construction

**Current gap:** Template element classification detects logos, text areas, people, objects. Product images have asset tags. Asset match scores are shown in UI. But **the generation prompt doesn't use any of this**.

**V2 wires it up:**

```python
# In prompt construction:
template_elements = template_element_service.get_template_elements(template_id)
asset_match = template_element_service.match_assets_to_template(template_id, product_id)

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

**V1 review checks 4 things** with hard-coded thresholds. V2 expands to a structured review rubric:

| Check | Category | What It Evaluates |
|-------|----------|-------------------|
| Product accuracy | Visual | Is the product reproduced exactly? No hallucinated features? |
| Text legibility | Visual | Is ALL text readable? No cut-off, blur, or hallucinated text? |
| Layout fidelity | Visual | Does layout match reference template structure? |
| Color compliance | Visual | Do colors match the requested mode (original/complementary/brand)? |
| Brand guideline check | Brand | Does it follow brand voice, prohibited claims, required disclaimers? |
| Headline congruence | Content | Does headline match offer variant / hero section? |
| Asset accuracy | Visual | Are the right product images used? Logo present/absent as expected? |
| Overall production quality | Quality | Would you run this ad? Professional finish? |

**Implementation:**
- Review prompt requests structured scores per check
- Each check has its own threshold (configurable per brand or globally)
- "Flagged" status includes which specific checks failed
- Review results stored as structured JSON, not just 4 floats

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

class TaskConfig(BaseModel):
    action: Literal["create_facebook_ad"] = "create_facebook_ad"
    variation_index: int
    total_variations: int
    canvas_size: str                   # Explicit, not buried in style
    color_mode: Literal["original", "complementary", "brand"]

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
```

**Benefits:**
- Versionable (bump model version, old prompts still parseable)
- Testable (validate prompt structure without calling LLM)
- Self-documenting (field descriptions = prompt documentation)
- Serializable (store full prompt as JSON in DB for debugging)

---

### 8. "Roll the Dice" Template Selection

**New option in V2 UI:**

```
Template Selection:
  ○ Choose templates manually
  ○ 🎲 Roll the dice (random unused templates)
     └─ How many? [3] templates
     └─ Category filter: [All ▼]  (optional: quote_card, testimonial, etc.)
```

**How it works:**
1. Query `scraped_templates` for all approved templates matching optional category filter
2. LEFT JOIN `product_template_usage` to find which templates this brand/product has already used
3. Filter to unused only
4. Random sample N templates
5. Show preview of selected templates before submission
6. If fewer unused templates than requested → show warning, offer to include previously used

**Query:**
```sql
SELECT st.* FROM scraped_templates st
LEFT JOIN product_template_usage ptu
  ON st.id = ptu.template_id AND ptu.product_id = :product_id
WHERE st.status = 'approved'
  AND ptu.id IS NULL
  AND (:category IS NULL OR st.category = :category)
ORDER BY random()
LIMIT :count
```

---

### 9. Additional V2 Improvements

#### a. Prompt Versioning
- Store prompt version string on each `generated_ads` row
- Track which prompt version produced which results
- Enables A/B testing of prompt changes

#### b. Batch Size Guardrails
- Total ads = templates × sizes × color_modes × variations
- Show estimated count before submission: "This will generate ~45 ads"
- Warn if over 50 (scheduler limit)
- Show estimated cost based on Gemini token pricing

#### c. Results Dashboard
- Since generation is async (worker), need a results view
- Group by template → show all size/color variants
- Filter by status (approved/rejected/flagged)
- Bulk actions: approve all, reject all, retry rejected
- Link back to ad run for full details

#### d. Progress Tracking
- `scheduled_job_runs.metadata` JSONB tracks:
  - `ads_generated`, `ads_reviewed`, `ads_approved`
  - `current_template`, `current_size`, `current_color`
- UI polls this for live progress (or use existing job status UI)

#### e. Product Label Text Accuracy Check
- V1's "text_accuracy" review only checks overlay text (headlines, CTAs) legibility
- Gemini's most common failure: garbled or hallucinated text on product packaging
- V2 adds a separate **Product Label Accuracy** review check (V9):
  - Compare generated product label text against known product name, brand name
  - Check for hallucinated ingredients, garbled characters, misspelled brand names
  - If product has `product_images` with readable labels, use as ground truth comparison
  - Any unreadable or incorrect packaging text → auto-reject (this is a non-negotiable quality bar)

---

### 10. Performance Feedback Loop (Creative Genome)

Wire ad performance data back into the generation system to learn what works.

**Data pipeline:**
```
generated_ads (with element tags)
    ↓  join on ad_id via find_matching_generated_ad_id()
meta_ads_performance (spend, CTR, CPA, ROAS, hook_rate)
    ↓  aggregate by element combination
creative_genome (element → performance mapping)
    ↓  feed back into generation
generation priority + review scoring
```

**Element tagging (new column: `generated_ads.element_tags` JSONB):**
```json
{
    "hook_type": "curiosity_gap",
    "belief_angle_id": "uuid",
    "belief_name": "cortisol_sleep_cycle",
    "persona_id": "uuid",
    "color_mode": "brand",
    "visual_style": "ugc",
    "template_category": "testimonial",
    "awareness_stage": "problem_aware",
    "offer_variant_id": "uuid",
    "canvas_size": "1080x1080"
}
```

**Performance attribution:**
- Join `generated_ads` → `meta_ads_performance` via the 8-char hex ID match
- Aggregate performance metrics (CTR, CPA, ROAS) by each element tag
- Build a scoring model: which element combinations outperform?
- Surface winning combos in the UI: "curiosity_gap + warm_colors = 3.2% avg CTR for this brand"

**Feeding back into generation:**
- Pre-generation scoring: predict performance of a creative brief before spending Gemini tokens
- Element priority: when selecting hooks, prefer hook types that historically perform for this brand/persona
- Review bonus: ads matching proven element combos get a review score boost
- Whitespace detection: surface untested element combos with high predicted potential

---

### 11. Winner Evolution System

Take ads that are performing well and systematically generate improved/expanded variations.

#### a. Winner Iteration (Single Variable Testing)
Given a winning ad, generate variations that change ONE element at a time:
- Same hook → different visual style
- Same visual → rephrased hook (same psychological type)
- Same everything → different color mode
- Same belief → escalated emotional intensity
- Same layout → different product image

Each variation is tagged with what changed, enabling clean attribution when performance data comes back.

#### b. Winner Amplification (Awareness Stage Expansion)
When an ad wins at one awareness stage, auto-generate versions for adjacent stages:
- Winning "Problem Aware" ad → generate "Solution Aware" version (same angle, introduce mechanism)
- Winning "Product Aware" ad → generate "Most Aware" version (same proof, lead with offer/urgency)
- Same belief thread, different entry points in the buyer's journey

#### c. Anti-Fatigue Refresh
Before a winner fatigues (predicted from Creative Genome fatigue curves):
- Generate "fresh coats of paint" — same winning belief + hook type + CTA
- New visual execution, new color palette, slightly reworded headline
- Psychology stays identical; only the surface changes
- Schedule replacement to go live 2 days before predicted fatigue onset

#### d. Cross-Size/Cross-Format Expansion
A winner in 1:1 feed might not exist in 9:16 Stories:
- Auto-generate winning ad in all sizes it hasn't been tested in
- Maximizes reach without creative risk
- Same creative, more placements

#### e. Angle/Persona/Offer Rotation on Winning Templates
When a template *structure* (layout, composition, CTA placement) proves it works:
- **Rotate belief angles** — same proven visual framework, different conviction
- **Rotate personas** — same winning hook type, reframed for different audience segment
- **Rotate offer variants** — same winning visual, different LP congruence target
- **Rotate awareness stages** — same winning belief, different headline construction

The template/visual/layout is de-risked. Only the strategic message variable is being tested. This is the highest-ROI creative testing approach: proven execution + untested message = high-probability new winner.

#### f. Competitive Counter-Creative
When the Creative Genome identifies a winning element combination:
- Cross-reference against competitor creative (from existing competitor research)
- If competitors are NOT using this winning combination → double down (own the space)
- If competitors start copying → generate counter-creative that evolves the approach
- Take your winning structure and apply it to belief angles in competitive whitespace

**UI for Winner Evolution:**
- "Evolve This Ad" button on any ad with performance data
- Shows which evolution modes are available based on the ad's element tags
- Estimates how many variants each mode would generate
- Submits as a scheduler job (worker-first, like all V2 generation)

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
│       │   ├── review_ads.py          # Expanded rubric
│       │   ├── retry_rejected.py
│       │   └── compile_results.py
│       └── services/
│           ├── __init__.py
│           ├── analysis_service.py    # Reuse/extend V1
│           ├── content_service.py     # Reuse/extend V1
│           ├── generation_service.py  # Pydantic prompt builder
│           ├── review_service.py      # Expanded review rubric
│           └── congruence_service.py  # NEW: headline congruence
├── ui/
│   └── pages/
│       └── 21b_🎨_Ad_Creator_V2.py   # New page, V1 stays
├── worker/
│   └── scheduler_worker.py           # Add ad_creation_v2 job handler
```

---

## Implementation Phases

### Phase 1: Foundation (Worker + Pydantic Prompts)
- [ ] Create `ad_creation_v2/` directory structure
- [ ] Port V1 pipeline to V2 directory (copy, don't modify V1)
- [ ] Replace dict-literal prompt with Pydantic models
- [ ] Add `ad_creation_v2` job type to scheduler worker
- [ ] Build minimal V2 UI page (submit job, view results)
- [ ] Verify V2 produces same quality output as V1

### Phase 2: Multi-Size + Multi-Color
- [ ] Add size checkbox UI
- [ ] Add color checkbox UI
- [ ] Modify GenerateAdsNode to loop sizes × colors
- [ ] Show estimated ad count before submission
- [ ] Group results by template × size × color

### Phase 3: Asset-Aware Prompts
- [ ] Wire template element classification into prompt construction
- [ ] Wire product image asset tags into image selection
- [ ] Add asset gap instructions to prompt (logo missing, person missing, etc.)
- [ ] Add text area character limits from template classification

### Phase 4: Headline Congruence + Review Overhaul
- [ ] Build CongruenceService (headline ↔ offer variant ↔ hero section)
- [ ] Add HeadlineCongruenceNode to pipeline
- [ ] Expand review rubric (14 checks: V1-V9 visual, C1-C4 content, G1-G2 congruence)
- [ ] Add product label text accuracy check (V9)
- [ ] Make review thresholds configurable
- [ ] Store structured review results

### Phase 5: Roll the Dice + Polish
- [ ] Build "roll the dice" unused template selection
- [ ] Add prompt versioning to generated_ads
- [ ] Build results dashboard with grouping/filtering
- [ ] Add batch size guardrails and cost estimation
- [ ] QA full end-to-end flow

### Phase 6: Performance Feedback Loop (Creative Genome)
- [ ] Add `element_tags` JSONB column to `generated_ads`
- [ ] Tag all V2 generated ads with element metadata during generation
- [ ] Build join query: `generated_ads` → `meta_ads_performance` via ad ID match
- [ ] Build element-level performance aggregation service
- [ ] Surface winning element combos in UI
- [ ] Pre-generation scoring: predict performance before spending Gemini tokens

### Phase 7: Winner Evolution
- [ ] "Evolve This Ad" button on ads with performance data
- [ ] Winner Iteration mode (single variable testing)
- [ ] Winner Amplification (awareness stage expansion)
- [ ] Anti-Fatigue Refresh (same psychology, fresh surface)
- [ ] Cross-Size/Cross-Format Expansion
- [ ] Angle/Persona/Offer Rotation on winning templates
- [ ] Competitive counter-creative suggestions

---

## Migration Path

1. V2 page lives at `21b_🎨_Ad_Creator_V2.py` alongside V1
2. Both share the same database tables (`ad_runs`, `generated_ads`)
3. V2 ads get a marker: `ad_runs.pipeline_version = 'v2'`
4. Compare V1 vs V2 output quality over 2-4 weeks
5. When V2 approval rates match or exceed V1 → promote V2 to primary, archive V1

---

## NOT in V2 Scope

- Video ad generation (separate feature)
- Automatic Meta upload (separate from generation)
- Multi-brand batch runs (one brand at a time)
