# Iteration Lab - Implementation Checkpoint

## Status: All 7 Phases Complete

**Date**: 2026-03-12
**Branch**: feat/ad-creator-v2-phase0

## Files Created/Modified

### New Files
| File | Purpose |
|------|---------|
| `migrations/2026-03-12_iteration_lab.sql` | 3 tables + RLS + indexes + job type CHECK |
| `viraltracker/services/visual_property_extractor.py` | Gemini vision extraction + caching |
| `viraltracker/services/iteration_opportunity_detector.py` | 6 pattern types + action_opportunity |
| `viraltracker/services/winner_dna_analyzer.py` | Per-winner + cross-winner DNA analysis |
| `viraltracker/ui/pages/38_🔬_Iteration_Lab.py` | 2-tab UI (Opportunities + Winners) |

### Modified Files
| File | Change |
|------|--------|
| `viraltracker/services/feature_service.py` | Added `ITERATION_LAB` to FeatureKey |
| `viraltracker/ui/nav.py` | Registered page 38 + added to superuser defaults |
| `viraltracker/worker/scheduler_worker.py` | Added `iteration_auto_run` dispatch + handler |
| `viraltracker/ui/pages/24_📅_Ad_Scheduler.py` | Added iteration auto-run form |

## Architecture

```
IterationOpportunityDetector (6 patterns)
  ├── high_converter_low_stopper (visual)
  ├── good_hook_bad_close (messaging)
  ├── thumb_stopper_quick_dropper (pacing)
  ├── efficient_but_starved (budget)
  ├── size_limited_winner (cross_size)
  └── fatiguing_winner (anti_fatigue)

WinnerDNAAnalyzer
  ├── analyze_winner() → per-winner DNA
  ├── analyze_cross_winners() → blueprint
  └── build_action_brief() → video briefs

VisualPropertyExtractor
  └── Gemini vision → ad_visual_properties (cached)

Iteration Lab UI (page 38)
  ├── Tab 1: Find Opportunities (scan, iterate, dismiss)
  └── Tab 2: Analyze Winners (blueprint, deep dive)

Scheduler: iteration_auto_run job type
  └── Weekly detect → filter image → iterate → log
```

## Database Tables
1. `ad_visual_properties` — cached Gemini visual extraction
2. `iteration_opportunities` — detected mixed-signal opportunities
3. `winner_dna_analyses` — per-winner and cross-winner analyses

## Multi-Tenant Compliance
- All 3 services have `_resolve_org_id()` for "all" → real UUID
- All reads filter by `brand_id` (and `organization_id` where applicable)
- FeatureKey registered, page gated via `require_feature()`

## Post-Plan Review

### Graph Invariants Checker (G1-G6): PASS (after fixes)
| Check | Status | Notes |
|-------|--------|-------|
| G1: Validation consistency | PASS | `iteration_auto_run` consistent across DB, worker, UI |
| G2: Error handling | PASS | Fixed 3 bare `except` blocks — added logging |
| G3: Service boundary | PASS | All business logic in services, UI delegates |
| G4: Schema drift | PASS | Migration columns match service read/write |
| G5: Security | PASS | No hardcoded secrets, no SQL injection |
| G6: Import hygiene | PASS | Removed unused `asdict`, `field`, `datetime`, `Any` |

### Test/Evals Gatekeeper (T1-T4): PASS
| Check | Status | Notes |
|-------|--------|-------|
| T1: Unit tests | PASS | 59 tests across 3 test files |
| T2: Syntax verification | PASS | All 8 files pass py_compile |
| T3: Integration tests | PASS (exempt) | No graph/pipeline nodes; service wiring tested via mocks |
| T4: No regressions | PASS | 466 existing tests pass (1 pre-existing failure unrelated) |

**Test Files Created:**
- `tests/services/test_visual_property_extractor.py` — 12 tests (parse, validate, cache, org_id)
- `tests/services/test_iteration_opportunity_detector.py` — 20 tests (baseline, confidence, patterns)
- `tests/services/test_winner_dna_analyzer.py` — 27 tests (brief, elements, visuals, blueprint)

### Fixes Applied During QA
1. `winner_dna_analyzer.py:572` — bare `except` → `except Exception as e: logger.debug(...)`
2. `Iteration_Lab.py:57` — bare `except` → added `logger.warning()`
3. `Iteration_Lab.py:66` — bare `except` → added `logger.warning()`
4. `iteration_opportunity_detector.py:16` — removed unused `asdict`, `field` imports
5. `Iteration_Lab.py:11-12` — removed unused `datetime`, `Any` imports
6. `winner_dna_analyzer.py` + `Iteration_Lab.py` — fixed `AdPerformanceQueryService()` → needs `supabase_client` arg

## Syntax Verification
All 8 production files + 3 test files pass `python3 -m py_compile`.

## Known Limitations
- Video ads: action brief only (no generation). "Create Image Version" button placeholder.
- Gemini rate limit (9 RPM) means cross-winner analysis of 10 takes ~70 seconds.
- Visual extraction skipped when no image available (graceful degradation).
- Anti-pattern detection requires generated ads with element_tags in bottom performers.

## Next Steps
- Run migration against Supabase
- Enable `iteration_lab` feature for target organizations
- Test with real brand data (minimum: 7 days, 5+ ads, $100+ spend)
- Monitor Gemini usage tracking
