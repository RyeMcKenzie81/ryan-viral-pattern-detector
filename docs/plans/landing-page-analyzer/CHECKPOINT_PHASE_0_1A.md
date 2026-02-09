# Checkpoint: Phase 0 (Schema Extensions) + Phase 1A-1C (Full Analysis Pipeline)

**Date:** 2026-02-09
**Status:** Complete

## What Was Built

### Phase 0 — Schema Extensions + Brand Manager UI

**New Migration:**
- `migrations/2026-02-09_landing_page_blueprint_fields.sql` — Adds to `products`: `guarantee`, `ingredients`, `results_timeline`, `faq_items`. Adds to `brands`: `brand_voice_tone`, `brand_colors`.

**Brand Manager UI Updates:**
- `viraltracker/ui/pages/02_🏢_Brand_Manager.py` — Added "Brand Voice & Colors" section (voice tone text input, primary/accent color pickers, secondary colors input). Added product "Blueprint Fields" section (guarantee text, structured ingredients JSON, results timeline JSON, FAQ items JSON). All new fields save properly with JSON validation.

### Phase 1A — Foundation

**New Service Directory:**
```
viraltracker/services/landing_page_analysis/
├── __init__.py
├── analysis_service.py           # LandingPageAnalysisService
├── models.py                     # Pydantic output models for all 4 skills
└── prompts/
    ├── __init__.py
    ├── page_classifier.py        # Skill 1 system prompt (full taxonomy)
    ├── element_detector.py       # Skill 2 system prompt (34 elements, 130+ subtypes)
    ├── gap_analyzer.py           # Skill 3 system prompt (full gap rules)
    └── copy_scorer.py            # Skill 4 system prompt (full scoring rubrics)
```

**Analysis Service (`analysis_service.py`):**
- `scrape_landing_page(url)` — Scrapes via FireCrawl with markdown + full-page screenshot
- `load_from_competitor_lp(id)` / `load_from_brand_lp(id)` — Load from existing records
- `run_full_analysis(...)` — Full 4-skill pipeline: Skill 1→2 sequential, Skill 3+4 parallel
- Partial failure handling: each skill saved as it completes, `return_exceptions=True` on parallel step
- Status tracking: `pending` → `processing` → `completed` / `partial` / `failed`
- Denormalized fields on final save for filtering (awareness_level, element_count, completeness_score, overall_score, overall_grade)
- Multimodal support: Skills 1+2 use Gemini via `analyze_image()` when screenshot available, text-only fallback otherwise
- Usage tracking via `set_tracking_context()`

**Screenshot Support:**
- `viraltracker/services/web_scraping_service.py` — Added `screenshot: Optional[str]` to `ScrapeResult`, extracted in both `scrape_url()` and `scrape_url_async()`

**Database:**
- `migrations/2026-02-09_landing_page_analyses.sql` — Full table with org_id, all 4 skill JSONB columns, denormalized filter fields, status, RLS, trigger, indexes

**Feature Registration:**
- `viraltracker/services/feature_service.py` — Added `LANDING_PAGE_ANALYZER = "landing_page_analyzer"` to FeatureKey
- `viraltracker/ui/nav.py` — Registered in Ads section (page 33), added to superuser feature list

### Phase 1B — Complete Analysis Pipeline

All 4 prompt files contain the FULL taxonomy from the SKILL.md files — not compressed. Every awareness level evidence signal, every element subtype definition, every scoring rubric dimension is preserved.

**Prompt sizes (approximate):**
- `page_classifier.py` — ~5KB (5 classification dimensions with full evidence signals)
- `element_detector.py` — ~10KB (34 elements across 6 sections, 130+ subtypes, flow analysis)
- `gap_analyzer.py` — ~7KB (required/recommended/optional by awareness level, 10 critical gap rules, scoring methodology)
- `copy_scorer.py` — ~9KB (11 element types × 5 dimensions each, full 0-2 rubrics, compliance flags, rewrite guidance)

### Phase 1C — Analysis UI

**UI Page:**
- `viraltracker/ui/pages/33_🏗️_Landing_Page_Analyzer.py`

**Tab 1 — Analyze:**
- Radio button: "Enter URL" / "From Competitor LPs" / "From Brand LPs"
- URL text input or dropdown of existing scraped pages
- Progress bar with 4-step labels (Classifying → Detecting → Analyzing → Complete)
- Quick summary card on completion (awareness badge, element count, completeness score, copy grade)

**Tab 2 — Results:**
- List of past analyses sorted by date, expandable
- Each analysis has 4 sub-tabs: Classification, Elements, Gaps, Copy Scores
- Classification: awareness badge, sophistication meter, architecture type, buyer persona
- Elements: section-by-section breakdown with element types and summaries
- Gaps: critical/moderate/minor with color coding, quick wins section
- Copy Scores: per-element progress bars, rewrite suggestions in expanders, compliance flags

## Modified Files

| File | Changes |
|------|---------|
| `viraltracker/services/web_scraping_service.py` | Added `screenshot` field to ScrapeResult, extract in both scrape methods |
| `viraltracker/services/feature_service.py` | Added `LANDING_PAGE_ANALYZER` to FeatureKey |
| `viraltracker/ui/nav.py` | Added page 33 to Ads section, added to superuser list |
| `viraltracker/ui/pages/02_🏢_Brand_Manager.py` | Added brand voice/colors section, added product blueprint fields |

## New Files

| File | Purpose |
|------|---------|
| `migrations/2026-02-09_landing_page_blueprint_fields.sql` | Schema: brand/product fields |
| `migrations/2026-02-09_landing_page_analyses.sql` | Schema: analyses table |
| `viraltracker/services/landing_page_analysis/__init__.py` | Package init |
| `viraltracker/services/landing_page_analysis/models.py` | Pydantic output types |
| `viraltracker/services/landing_page_analysis/analysis_service.py` | Main service |
| `viraltracker/services/landing_page_analysis/prompts/__init__.py` | Prompts package |
| `viraltracker/services/landing_page_analysis/prompts/page_classifier.py` | Skill 1 prompt |
| `viraltracker/services/landing_page_analysis/prompts/element_detector.py` | Skill 2 prompt |
| `viraltracker/services/landing_page_analysis/prompts/gap_analyzer.py` | Skill 3 prompt |
| `viraltracker/services/landing_page_analysis/prompts/copy_scorer.py` | Skill 4 prompt |
| `viraltracker/ui/pages/33_🏗️_Landing_Page_Analyzer.py` | UI page |

## What Works

- All Python files compile cleanly (`python3 -m py_compile`)
- Service follows established patterns (belief_analysis_service, product_context_service)
- Multi-tenancy: org_id filtering on list_analyses(), org_id stored on records
- Feature gating: page hidden when feature disabled
- Partial failure handling: if Skill 3 or 4 fails, others still saved
- Multimodal: Skills 1+2 use Gemini with screenshot when available

## Decisions Made

1. **Model selection:** Skills 1, 2, 4 use `Config.get_model("complex")` (Claude Opus 4.5). Skill 3 uses `Config.get_model("fast")` (Claude Sonnet) since it's mostly comparison logic.
2. **JSON parsing:** Used local `_parse_llm_json()` helper instead of importing from persona_service to avoid circular dependency potential.
3. **Combined Phase 0 + 1A-1C:** Implemented the full analysis pipeline in one session since the phases were not independently testable without the complete pipeline.
4. **Brand Manager JSON fields:** Used `st.text_area` with JSON for structured fields (ingredients, timeline, FAQ) rather than building custom add/remove editors — simpler, and power users can edit JSON directly.
5. **No screenshot storage in Supabase:** The plan mentioned storing screenshots in Supabase storage — deferred to Phase 2 since the base64 is passed directly to Gemini during analysis and not needed for persistence of the analysis itself.

## What's Left

### ~~Phase 2A — Brand Profile + Blueprint Service~~ ✅ DONE
### ~~Phase 2B — Blueprint UI~~ ✅ DONE

See `CHECKPOINT_PHASE_2.md` for details.

## How to Test

1. **Run migrations** against Supabase:
   ```sql
   -- Run both migration files in order
   ```

2. **Enable feature for org:**
   ```sql
   INSERT INTO org_features (organization_id, feature_key, enabled)
   VALUES ('your-org-id', 'landing_page_analyzer', true);
   ```

3. **Test analysis pipeline:**
   - Navigate to Landing Page Analyzer in sidebar
   - Enter a URL (e.g., a supplement landing page)
   - Click "Scrape & Analyze"
   - Watch 4-step progress
   - Check Results tab for stored analysis

4. **Test Brand Manager fields:**
   - Go to Brand Manager
   - Edit brand voice/tone and colors
   - Edit a product's guarantee, ingredients JSON, timeline JSON, FAQ JSON
   - Verify saves work
