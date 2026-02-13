# Ad Creator V2 — Checkpoint 001

> **Date**: 2026-02-12
> **Status**: Planning complete, implementation not started

---

## What Was Done This Session

### 1. Bug Fixes (committed & pushed)

- **M5- filename prefix** (`8074914`) — Added "M5-" prefix to all generated ad filenames for Meta Ads Manager filtering. Updated `generate_ad_filename()` + 3 fallback patterns + regex in `find_matching_generated_ad_id()`.

- **Version bump for redeploy** (`47e908f`) — Bumped `__version__` to 2.0.1 to trigger Railway redeploy after GitHub issue.

- **Persona generation truncation** (`6f1bb0e`) — Set `max_tokens=16384` on both `generate_persona_from_product()` and `synthesize_competitor_persona()` in `persona_service.py`. Root cause: Persona4D model is massive (8 dimensions, 40+ fields), default max_tokens (~4096) caused JSON truncation → "Unterminated string" parse errors.

- **Scraped template checkbox key bug** (`cfa19de`) — Changed checkbox key from `scraped_tpl_cb_{idx}` (loop index) to `scraped_tpl_cb_{template_id}` in Ad Creator. Index-based keys caused wrong template selections when category filter changed (Streamlit caches widget state by key). This also caused the "Generate Ads flashes and does nothing" bug — phantom toggle events fired before workflow code was reached.

- **TCPTransport closed error** (staged, NOT pushed) — Replaced `asyncio.run()` with `loop.run_until_complete()` in the batch template loop. `asyncio.run()` creates/destroys event loops per iteration, killing httpx connection pools used by PydanticAI agents. `nest_asyncio` already applied globally in `app.py`. Also added `reset_client()` method to GeminiService.

### 2. Tech Debt Updates (committed & pushed)

- **#28** — Persona4D model size / structured output. Three approaches: Pydantic `output_type`, two-pass generation, flatten/slim model. Key constraint: maintain detail richness, don't remove fields that could be used in future.

### 3. Ad Creator V2 Planning (NOT committed)

Created two planning documents:

**`docs/plans/ad-creator-v2/PLAN.md`** — Technical architecture:
- Worker-first execution (scheduler job, not browser-dependent)
- Multi-size generation via checkboxes (1:1, 4:5, 9:16, 16:9)
- Multi-color mode via checkboxes (original + complementary + brand simultaneously)
- Asset-aware prompts (wire template element classification + image tags into generation)
- Pydantic prompt models (replace 280-line dict literal)
- Headline ↔ offer variant + hero section congruence
- Expanded review rubric (14 checks instead of 4)
- "Roll the dice" random unused template selection
- V2 runs alongside V1 as separate page (`21b_🎨_Ad_Creator_V2.py`)
- 5 implementation phases

**`docs/plans/ad-creator-v2/CREATIVE_INTELLIGENCE.md`** — Marketing science layer:
- Schwartz awareness stage enforcement (headline rules change by stage)
- Market sophistication levels (unique mechanism required at Level 3+)
- Todd Brown belief chain validation (prerequisite → buying belief sequencing)
- Hopkins reason-why rule (every claim needs evidence/mechanism)
- Psychology-mapped visual direction (persona → color/imagery/hook mapping)
- Hook type diversity (curiosity gap, authority drop, emotional trigger, etc.)
- 14-point review rubric with weighted scoring
- Creative Genome concept (element-level performance tracking)
- Predictive fatigue + auto-refresh
- Competitive whitespace detection
- Authenticity scoring (detect AI tells)
- A/B test matrix generator

---

## Current V1 Pipeline Understanding

```
InitializeNode → FetchContextNode → AnalyzeTemplateNode → SelectContentNode
  → SelectImagesNode → GenerateAdsNode → ReviewAdsNode → (RetryRejectedNode)
  → CompileResultsNode → End
```

### Key Gap Identified: Asset Classification Not Wired to Prompts

Template element service classifies elements (logos, text areas, people, objects). Product images have asset tags. Asset match scores show as badges in UI. **But none of this feeds into the generation prompt.** The prompt just takes 1-2 highest-scored images blindly.

### Key Gap Identified: Review Doesn't Verify Generation Rules

The generation prompt has rules for `scale` (product proportioning) and `lighting` (consistency), but the V1 review never checks if Gemini actually followed them. V2 adds explicit V7 (proportioning) and V8 (lighting) review checks.

---

## Files Changed (Not Yet Committed)

| File | Change | Status |
|------|--------|--------|
| `viraltracker/ui/pages/21_🎨_Ad_Creator.py` | `loop.run_until_complete()` instead of `asyncio.run()` in batch loop | Staged, NOT pushed |
| `viraltracker/services/gemini_service.py` | Added `reset_client()` method | Staged, NOT pushed |
| `docs/plans/ad-creator-v2/PLAN.md` | V2 technical plan | NOT committed |
| `docs/plans/ad-creator-v2/CREATIVE_INTELLIGENCE.md` | Marketing science research | NOT committed |

---

## Open Questions for Next Session

1. **Product text accuracy** — Do we check that text ON the product packaging (label text, ingredient lists, brand name) is reproduced accurately in generated ads? V1's "text_accuracy" review check is about overlay text legibility, not product label text. Need to add a specific check for this.

2. **Ad performance feedback loop** — Can we use the existing ad performance data (Meta Ads sync → `meta_ads_performance` table) to create a feedback loop into the Creative Genome? What data do we already have that maps generated ads → performance metrics → element-level attribution?

3. **When to start Phase 1 implementation** — Plan is ready, user hasn't approved start yet.

---

## Key File Locations

| File | Purpose |
|------|---------|
| `docs/plans/ad-creator-v2/PLAN.md` | V2 technical architecture |
| `docs/plans/ad-creator-v2/CREATIVE_INTELLIGENCE.md` | Marketing science / review rubric |
| `viraltracker/pipelines/ad_creation/` | V1 pipeline (8 nodes) |
| `viraltracker/pipelines/ad_creation/services/generation_service.py` | V1 prompt construction (280-line dict) |
| `viraltracker/pipelines/ad_creation/services/review_service.py` | V1 review (4 scores, 0.8 threshold) |
| `viraltracker/pipelines/ad_creation/state.py` | V1 pipeline state dataclass |
| `viraltracker/services/template_element_service.py` | Template classification + asset matching |
| `viraltracker/services/gemini_service.py` | Gemini API wrapper (image generation) |
| `viraltracker/ui/pages/21_🎨_Ad_Creator.py` | V1 UI page |
| `viraltracker/worker/scheduler_worker.py` | Worker/cron job execution |
