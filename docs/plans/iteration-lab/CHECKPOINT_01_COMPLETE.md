# Iteration Lab - Implementation Checkpoint

## Status: All 7 Phases Complete + QA PASS

**Date**: 2026-03-12
**Branch**: `feat/ad-creator-v2-phase0`
**Commit**: `43a5d6b` — pushed to GitHub

---

## What Was Built

### Services (3 new files)

| Service | File | Responsibility |
|---------|------|---------------|
| **VisualPropertyExtractor** | `viraltracker/services/visual_property_extractor.py` | Gemini vision extraction of ad image properties (contrast, color, faces, composition, etc.). Cached in `ad_visual_properties` table. Graceful degradation when no image available. |
| **IterationOpportunityDetector** | `viraltracker/services/iteration_opportunity_detector.py` | Detects 6 mixed-signal patterns in ad performance. Auto-imports non-generated ads via MetaWinnerImportService. Calls WinnerEvolutionService to iterate. |
| **WinnerDNAAnalyzer** | `viraltracker/services/winner_dna_analyzer.py` | Per-winner DNA decomposition (elements, visuals, messaging, cohort comparison, synergies). Cross-winner blueprint extraction. Video action brief builder. |

### 6 Opportunity Patterns

| Pattern | Label | Strong Signal | Weak Signal | Strategy |
|---------|-------|--------------|-------------|----------|
| `high_converter_low_stopper` | Strong ROAS, Weak CTR | ROAS > p50 | CTR < p25 | Visual — higher contrast, bolder text, face close-ups |
| `good_hook_bad_close` | Strong CTR, Weak ROAS | CTR > p50 | ROAS < p25 | Messaging — CTA clarity, offer alignment |
| `thumb_stopper_quick_dropper` | Strong Hook Rate, Weak Hold Rate | Hook rate > p50 | Hold rate < p50 | Pacing — mid-video retention, value reveal timing |
| `efficient_but_starved` | Profitable but Under-Scaled | ROAS > p50 | Impressions < 5,000 | Budget — no evolution, budget recommendation |
| `size_limited_winner` | Winner in Only One Format | Reward ≥ 0.5 | 1 canvas size | Cross-size expansion |
| `fatiguing_winner` | Declining Performance (Fatigue) | First-half CTR > median | CTR decline > 15% | Anti-fatigue refresh |

### UI Page

**`viraltracker/ui/pages/38_🔬_Iteration_Lab.py`** — Two-tab layout:
- **Tab 1: Find Opportunities** — Scan button, category pills, two-level cards (collapsed summary → expanded details), Iterate button for image ads, action briefs for video ads, dismiss/restore
- **Tab 2: Analyze Winners** — Radio toggle between "Winner Blueprint" (cross-winner, default) and "Deep Dive" (per-winner), element attribution with humanized labels, visual properties, cohort comparison

### Infrastructure

- **Migration**: `migrations/2026-03-12_iteration_lab.sql` — 3 tables + RLS + indexes + `iteration_auto_run` job type
- **Feature gate**: `ITERATION_LAB` added to `FeatureKey`, registered in `nav.py`, added to superuser defaults
- **Scheduler**: `execute_iteration_auto_run_job()` handler + `_render_iteration_auto_run_form()` in Scheduler UI

### Tests (59 passing)

| Test File | Tests | Coverage |
|-----------|-------|----------|
| `tests/services/test_visual_property_extractor.py` | 12 | JSON parsing, enum validation, float clamping, cache hit, org_id resolution |
| `tests/services/test_iteration_opportunity_detector.py` | 20 | Baseline lookup, percentile labels, confidence scoring, all 4 standard patterns, strategy actions |
| `tests/services/test_winner_dna_analyzer.py` | 27 | Action briefs, common elements (threshold), visual traits, replication blueprint, messaging profile |

---

## Database Tables

### `ad_visual_properties`
Cached Gemini visual extraction per ad creative. Unique on `(meta_ad_id, brand_id, prompt_version)`.

Key columns: `contrast_level`, `color_palette_type`, `dominant_colors`, `text_density`, `visual_hierarchy`, `composition_style`, `face_presence`, `face_count`, `face_emotion`, `person_framing`, `product_visible`, `product_prominence`, `headline_style`, `cta_visual_treatment`, `visual_quality_score`, `thumb_stop_prediction`, `raw_extraction`, `input_hash`.

### `iteration_opportunities`
Detected mixed-signal opportunities. Unique on `(meta_ad_id, brand_id, pattern_type, detected_at)`.

Key columns: `pattern_type`, `pattern_label`, `confidence`, `strong_metric`, `strong_value`, `strong_percentile`, `weak_metric`, `weak_value`, `weak_percentile`, `strategy_category`, `strategy_description`, `strategy_actions`, `evolution_mode`, `status` (detected/actioned/dismissed/expired), `evolved_ad_id`, `expires_at`.

### `winner_dna_analyses`
Per-winner and cross-winner DNA analyses.

Key columns: `analysis_type` (per_winner/cross_winner), `meta_ad_ids[]`, `element_scores`, `top_elements`, `weak_elements`, `visual_properties`, `messaging_properties`, `cohort_comparison`, `active_synergies`, `active_conflicts`, `common_elements`, `common_visual_traits`, `anti_patterns`, `iteration_directions`, `replication_blueprint`.

---

## Post-Plan Review: PASS

### Graph Invariants (G1-G6): PASS
| Check | Status |
|-------|--------|
| G1: Validation consistency | PASS — `iteration_auto_run` consistent across DB CHECK, worker dispatch, and UI |
| G2: Error handling | PASS — 3 bare `except` blocks fixed with logging |
| G3: Service boundary | PASS — all business logic in services, UI delegates |
| G4: Schema drift | PASS — migration columns match service read/write exactly |
| G5: Security | PASS — no hardcoded secrets, no SQL injection, no eval |
| G6: Import hygiene | PASS — removed unused `asdict`, `field`, `datetime`, `Any` |

### Test/Evals (T1-T4): PASS
| Check | Status |
|-------|--------|
| T1: Unit tests | PASS — 59 tests across 3 test files |
| T2: Syntax verification | PASS — all 11 files pass py_compile |
| T3: Integration tests | PASS (exempt) — no graph/pipeline nodes |
| T4: No regressions | PASS — 466 existing tests pass |

---

## How to Test

### Prerequisites

Before testing Iteration Lab, a brand needs:

1. **Meta performance data** — at least 7 days of daily sync data in `meta_ads_performance`
   - **How**: A `meta_sync` scheduled job must have been running for the brand
   - **Check**: `SELECT COUNT(DISTINCT meta_ad_id) FROM meta_ads_performance WHERE brand_id = '<brand_id>' AND date >= NOW() - INTERVAL '7 days';` — should be ≥ 5

2. **Ad Intelligence baselines** — `ad_intelligence_baselines` must have rows for the brand
   - **How**: Run `full_analysis()` via the Ad Intelligence page (page 30) or via an `ad_intelligence_analysis` scheduled job
   - **Check**: `SELECT COUNT(*) FROM ad_intelligence_baselines WHERE brand_id = '<brand_id>';` — should be ≥ 1

3. **Classifications** — `ad_creative_classifications` must exist for the brand's ads
   - **How**: Same `full_analysis()` run creates these, OR run an `ad_classification` scheduled job
   - **Check**: `SELECT COUNT(*) FROM ad_creative_classifications WHERE brand_id = '<brand_id>';` — should be ≥ 5

4. **Run the migration** — execute `migrations/2026-03-12_iteration_lab.sql` against Supabase
   - **How**: Copy/paste the SQL into the Supabase SQL Editor and run it

5. **Enable the feature** — add `iteration_lab` feature for the org
   - **How**: In Admin page → Feature Management → enable `iteration_lab` for the target org
   - **OR**: Superuser mode (`org_id = "all"`) sees all pages automatically

### Optional (for full functionality)

6. **Asset download** — run an `asset_download` scheduled job for stored images (better than CDN thumbnails for visual extraction)
7. **Creative genome** — run a `creative_genome_update` job for element attribution in DNA analysis
8. **Products** — the brand needs at least one product in the `products` table (required for "Iterate" action)

### Testing Steps

#### Tab 1: Find Opportunities
1. Navigate to Iteration Lab (page 38)
2. Select a brand with prerequisites met
3. Click "Scan for Opportunities"
4. Verify opportunity cards appear with pattern labels, metrics, confidence badges
5. Test category pills (filter by visual/messaging/etc.)
6. Expand an opportunity card → verify strategy and actions shown
7. For an IMAGE ad: click "Iterate" → verify confirmation card with pre-filled instructions → click "Confirm & Launch"
8. For a VIDEO ad: verify action brief shown (no Iterate button)
9. Click "Dismiss" on an opportunity → verify it moves to Dismissed section
10. Click "Restore" in Dismissed section → verify it returns

#### Tab 2: Analyze Winners
1. Switch to "Analyze Winners" tab
2. Click "Analyze Winners" with default Top N = 10
3. Verify "Your Winning Formula" card shows DO THIS / AVOID THIS
4. Switch radio to "Deep Dive"
5. Select a winner from dropdown → click "Analyze"
6. Verify DNA breakdown: performance, visual properties, element scores, cohort comparison

#### Automated Scheduling
1. Go to Scheduler page (page 24)
2. Create new → select "Iteration Auto-Run"
3. Configure: brand, top_n, days_back, min_confidence
4. Click "Run Now" to test immediately
5. Check job run logs for evolved/skipped/failed counts

#### Unit Tests
```bash
./venv/bin/python3 -m pytest tests/services/test_visual_property_extractor.py tests/services/test_iteration_opportunity_detector.py tests/services/test_winner_dna_analyzer.py -v
```
Should show 59 passed.

---

## Known Limitations
- Video ads: action brief only (no generation). "Create Image Version" is a placeholder.
- Gemini rate limit (9 RPM) means cross-winner analysis of 10 takes ~70 seconds.
- Visual extraction skipped when no image available (graceful degradation).
- Anti-pattern detection requires generated ads with `element_tags` in bottom performers.
- Hook rate/hold rate patterns only work for video ads with video metric data.
