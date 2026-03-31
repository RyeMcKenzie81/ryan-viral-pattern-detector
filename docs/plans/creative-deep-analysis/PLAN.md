# Workflow Plan: Creative Deep Analysis (Phase 2 of Strategic Leverage Engine)

**Branch**: `feature/creative-deep-analysis`
**Created**: 2026-03-30
**Status**: Phase 1 - Intake

---

## Phase 1: INTAKE

### 1.1 Original Request

Use Gemini Pro 3 to analyze ALL video and image ads — extract messaging themes, hooks, personas, storyboards, scripts, who's in the ad, emotional tone, visual patterns. Correlate these with performance data to identify what's actually driving results, then surface insights as leverage moves in the Strategic Leverage tab.

### 1.2 Clarifying Questions & Answers

| # | Question | Answer |
|---|----------|--------|
| 1 | New table vs extend `ad_creative_classifications`? | New table — also extract script/storyboard. Store structured fields + raw JSONB for future mining |
| 2 | What should Gemini extract? | Messaging theme, persona signals, emotional tone, hook pattern, CTA style + storyboard, script, who's in the ad, video length |
| 3 | How should this be triggered? | Both — scheduled job for bulk runs + auto-chain after ad_classification |
| 4 | Video analysis depth? | Full video understanding (frames + audio) — worth the cost |
| 5 | How should results feed into Strategic Leverage? | Both — new move types AND enrich existing ones |
| 6 | Who's in the ad — what detail level? | Demographics + role (spokesperson, testimonial, lifestyle model, UGC creator) |
| 7 | Analyze competitor ads too? | No — only our ads (meta_ads_performance) since we need performance data for correlations |

### 1.3 Key Discovery: Existing Infrastructure

**Most of the analysis infrastructure already exists:**

| Component | Status | What It Does |
|-----------|--------|-------------|
| `ad_video_analysis` table | EXISTS (schema ready, partially populated) | Transcript, storyboard, hooks, messaging, benefits, pain points, angles, claims |
| `ad_visual_properties` table | EXISTS (schema ready, empty) | Visual properties (contrast, color, faces, composition) — NOT messaging/persona |
| `VideoAnalysisService` | EXISTS | Handles Gemini Files API for video analysis |
| `ClassifierService.classify_batch()` | EXISTS | Batch pipeline with cost budgets and prefetch optimization |
| `meta_ad_assets` table | EXISTS | Stored videos/images in Supabase storage |
| `UsageTracker` in GeminiService | EXISTS | Cost tracking integrated |

**What's missing:**

1. **Image deep analysis** — `ad_visual_properties` has visual properties but NOT messaging/persona/tone analysis for images. Need a new table or extend this one.
2. **Ensure video analysis runs for ALL video ads** — currently budget-gated (`max_video=15` per classification run)
3. **Correlation engine** — no service exists to correlate analysis fields with performance data
4. **Leverage move integration** — wire correlations into AccountLeverageService as new move generators

### 1.4 Desired Outcome

**User Story**: As a brand operator, I want the system to watch/look at every ad creative and identify which messaging themes, hooks, personas, and visual patterns correlate with strong performance, so I can create more ads that follow winning patterns.

**Success Criteria**:
- [ ] Every ad with stored assets gets Gemini deep analysis (image and video)
- [ ] Analysis extracts: messaging theme, emotional tone, persona signals (who's in the ad + demographics + role), hook pattern, CTA style, script/storyboard (video), visual style
- [ ] Correlations surface in Strategic Leverage tab as new move types (e.g., "Ads with empathetic tone outperform by 2.3x — create more")
- [ ] Existing leverage moves are enriched with creative analysis data
- [ ] Runs as both scheduled batch job and auto-chains after classification
- [ ] Raw Gemini response stored for future mining

### 1.5 Phase 1 Approval

- [ ] User confirmed requirements are complete

---

## Phase 2: ARCHITECTURE DECISION

### 2.1 Workflow Type Decision

**Chosen**: Python workflow (service + scheduled job)

**Reasoning**:

| Question | Answer |
|----------|--------|
| Who decides what happens next - AI or user? | Deterministic — process all unanalyzed ads |
| Autonomous or interactive? | Autonomous batch job |
| Needs pause/resume capability? | No — idempotent, can re-run safely |
| Complex branching logic? | Minimal — image vs video path, skip already-analyzed |

### 2.2 High-Level Architecture

```
┌─────────────────────────────────────────────────────────────┐
│  Scheduled Job: creative_deep_analysis                       │
│  (also auto-chains after ad_classification)                  │
│                                                              │
│  For each unanalyzed ad with stored assets:                  │
│    ├── IMAGE → Gemini: extract messaging, persona, tone      │
│    │          → Store in ad_image_analysis                    │
│    └── VIDEO → Gemini: full video understanding              │
│               → Store in ad_video_analysis (already exists)  │
│                                                              │
│  After batch completes:                                      │
│    → CreativeCorrelationService.compute_correlations()        │
│    → Store in creative_performance_correlations               │
└─────────────────────────────────────────────────────────────┘

┌─────────────────────────────────────────────────────────────┐
│  AccountLeverageService (enhanced)                           │
│                                                              │
│  New move generator: _creative_insight_moves()               │
│    → Reads creative_performance_correlations                 │
│    → "Empathetic tone ads outperform by 2.3x"               │
│    → "UGC creator ads have 40% lower CPA than studio"       │
│    → "Testimonial hooks convert 3x better at problem-aware" │
│                                                              │
│  Enriched existing moves:                                    │
│    → Awareness gap moves now suggest tone/persona            │
│    → Format moves now reference visual style patterns        │
└─────────────────────────────────────────────────────────────┘
```

### 2.3 Data Model

**New table: `ad_image_analysis`** (parallel to existing `ad_video_analysis`):
```sql
- meta_ad_id, brand_id, organization_id
- messaging_theme (TEXT)
- emotional_tone (TEXT[])  -- fear, aspiration, urgency, empathy, humor
- hook_pattern (TEXT)  -- question, statement, testimonial, statistic, story
- cta_style (TEXT)  -- direct, soft, curiosity, none
- target_persona_signals (JSONB)  -- {age_group, gender_signals, pain_points, aspirations}
- people_in_ad (JSONB[])  -- [{role, age_range, gender, description}]
- text_overlays (JSONB)  -- extracted text from image
- visual_style (JSONB)  -- {color_mood, imagery_type, setting, production_quality}
- raw_analysis (JSONB)  -- full Gemini response
- model_used, prompt_version, input_hash, analyzed_at
```

**New table: `creative_performance_correlations`** (computed, not raw):
```sql
- brand_id, organization_id
- analysis_field (TEXT)  -- e.g., "emotional_tone", "hook_pattern", "people_role"
- field_value (TEXT)  -- e.g., "empathy", "testimonial", "ugc_creator"
- ad_count (INT)
- mean_reward (FLOAT)
- mean_ctr, mean_conv_rate, mean_roas (FLOAT)
- vs_account_avg (FLOAT)  -- relative performance multiplier
- confidence (FLOAT)  -- based on sample size
- computed_at (TIMESTAMPTZ)
```

**Extend existing `ad_video_analysis`**: Add `people_in_ad` JSONB[] column if missing (for who's in the video + role).

### 2.4 Phase 2 Approval

- [ ] User confirmed architecture approach

---

## Phase 3: INVENTORY & GAP ANALYSIS

### 3.1 Existing Components to Reuse

| Component | Type | Location | How We'll Use It |
|-----------|------|----------|------------------|
| `VideoAnalysisService` | Service | `viraltracker/services/video_analysis_service.py` | Video analysis pipeline — extend for people_in_ad |
| `ClassifierService` | Service | `viraltracker/services/ad_intelligence/classifier_service.py` | Batch processing pattern, asset fetching |
| `GeminiService` | Service | `viraltracker/services/gemini_service.py` | Gemini API calls with usage tracking |
| `AdIntelligenceService` | Service | `viraltracker/services/ad_intelligence/ad_intelligence_service.py` | Run management, active ad discovery |
| `AccountLeverageService` | Service | `viraltracker/services/account_leverage_service.py` | Add new move generator |
| `meta_ad_assets` | Table | Supabase | Source of stored images/videos |
| `ad_video_analysis` | Table | Supabase | Already has most video analysis fields |
| `creative_element_rewards` | Table | Supabase | Performance data for correlations |
| `UsageTracker` | Service | `viraltracker/services/usage_tracker.py` | Cost tracking |

### 3.2 New Components to Build

| Component | Type | Purpose |
|-----------|------|---------|
| `ImageAnalysisService` | Service | Gemini image deep analysis (messaging, persona, tone) |
| `CreativeCorrelationService` | Service | Correlate analysis fields with performance |
| `_creative_insight_moves()` | Method | New move generator in AccountLeverageService |
| `_render_creative_deep_analysis_form()` | UI | Scheduler form for the job type |
| `execute_creative_deep_analysis_job()` | Worker | Scheduler worker handler |
| `ad_image_analysis` | Migration | New table for image analysis results |
| `creative_performance_correlations` | Migration | New table for computed correlations |

### 3.3 Implementation Steps

**Step 1: Migration** — Create `ad_image_analysis` and `creative_performance_correlations` tables, add `people_in_ad` to `ad_video_analysis`

**Step 2: ImageAnalysisService** (~200 lines)
- `analyze_image(meta_ad_id, brand_id, image_url_or_bytes)` → Gemini analysis → store in `ad_image_analysis`
- `analyze_batch(brand_id, meta_ad_ids, max_new)` → batch with dedup via input_hash
- Prompt extracts: messaging_theme, emotional_tone[], hook_pattern, cta_style, target_persona_signals, people_in_ad[], text_overlays, visual_style

**Step 3: Extend VideoAnalysisService** (~30 lines)
- Add `people_in_ad` extraction to existing video analysis prompt
- Store in new column on `ad_video_analysis`

**Step 4: CreativeCorrelationService** (~250 lines)
- `compute_correlations(brand_id)` → join analysis tables with performance data
- For each analysis field (emotional_tone, hook_pattern, people_role, messaging_theme, etc.):
  - Group ads by field value
  - Compute mean reward, CTR, conv rate, ROAS per group
  - Compare to account average → relative performance multiplier
  - Store in `creative_performance_correlations`
- `get_top_correlations(brand_id, min_confidence, limit)` → ranked insights

**Step 5: AccountLeverageService enhancement** (~80 lines)
- Add `_creative_insight_moves()` — reads correlations, generates moves like "Ads with empathetic tone outperform by 2.3x"
- Enrich existing moves with creative context when available

**Step 6: Scheduler integration** (~250 lines)
- Worker: `execute_creative_deep_analysis_job()` — processes unanalyzed ads
- UI: `_render_creative_deep_analysis_form()` in Ad Scheduler
- Auto-chain: after `ad_classification` completes, trigger deep analysis

### 3.4 Phase 3 Approval

- [ ] User confirmed component list
- [ ] Database impact assessed and approved

---

## Phase 4: BUILD

### 4.1 Build Order

1. [ ] Migration — `ad_image_analysis`, `creative_performance_correlations`, extend `ad_video_analysis`
2. [ ] `ImageAnalysisService` — Gemini image deep analysis
3. [ ] Extend `VideoAnalysisService` — add people_in_ad extraction
4. [ ] `CreativeCorrelationService` — performance correlation engine
5. [ ] `AccountLeverageService` enhancement — new move generator
6. [ ] Scheduler worker + UI — job type and form
7. [ ] Auto-chain after classification

---

## Questions Log

| Date | Question | Answer |
|------|----------|--------|
| 2026-03-30 | New table vs extend classifications? | New table + raw JSONB |
| 2026-03-30 | What to extract? | Messaging, persona, tone, hook, CTA + storyboard, script, who's in ad |
| 2026-03-30 | Trigger method? | Both — scheduled + auto-chain after classification |
| 2026-03-30 | Video analysis depth? | Full video understanding |
| 2026-03-30 | Feed into leverage? | Both new move types and enrich existing |
| 2026-03-30 | Who's in ad detail? | Demographics + role |
| 2026-03-30 | Analyze competitors? | No — only our ads with performance data |

---

## Change Log

| Date | Phase | Change |
|------|-------|--------|
| 2026-03-30 | 1 | Initial plan created from design doc Phase 2 + user Q&A |
