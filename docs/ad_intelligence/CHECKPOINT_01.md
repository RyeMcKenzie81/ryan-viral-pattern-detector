# Ad Intelligence Agent - Checkpoint 01

**Date:** 2026-02-02
**Branch:** `feat/veo-avatar-tool`
**Status:** Core implementation complete, pre-testing

## What's Done

All 16 implementation steps (A.1–H.2) are complete:

### Files Created (16 new)
| File | Purpose |
|------|---------|
| `migrations/2026-02-02_ad_intelligence.sql` | 7 tables, 28 indexes |
| `viraltracker/services/ad_intelligence/__init__.py` | Package init |
| `viraltracker/services/ad_intelligence/models.py` | Enums, configs, 4-layer Pydantic models |
| `viraltracker/services/ad_intelligence/helpers.py` | Active ad query, org validation, conversion extractors |
| `viraltracker/services/ad_intelligence/classifier_service.py` | Layer 1: Awareness classification |
| `viraltracker/services/ad_intelligence/baseline_service.py` | Layer 2: Cohort percentile baselines |
| `viraltracker/services/ad_intelligence/diagnostic_engine.py` | Layer 3: 12 diagnostic rules |
| `viraltracker/services/ad_intelligence/recommendation_service.py` | Layer 4: Recommendations + feedback |
| `viraltracker/services/ad_intelligence/fatigue_detector.py` | Fatigue detection (frequency + CTR trend) |
| `viraltracker/services/ad_intelligence/coverage_analyzer.py` | Awareness x format coverage matrix |
| `viraltracker/services/ad_intelligence/congruence_checker.py` | Creative-copy-LP alignment scoring |
| `viraltracker/services/ad_intelligence/chat_renderer.py` | Pydantic model -> markdown adapter |
| `viraltracker/services/ad_intelligence/ad_intelligence_service.py` | Orchestration facade |
| `viraltracker/agent/agents/ad_intelligence_agent.py` | 9 thin tools (8 analysis + 1 brand lookup) |
| `tests/services/ad_intelligence/__init__.py` | Test package init |
| `docs/ad_intelligence/metric_coverage_audit.md` | Metric source documentation |

### Files Modified (4)
| File | Change |
|------|--------|
| `viraltracker/agent/agents/__init__.py` | Added `ad_intelligence_agent` export |
| `viraltracker/agent/orchestrator.py` | Added routing tool + system prompt section 7 |
| `viraltracker/agent/dependencies.py` | Added `ad_intelligence: AdIntelligenceService` |
| `viraltracker/services/feature_service.py` | Added `FeatureKey.AD_INTELLIGENCE` |

### DB Migration
Applied: `migrations/2026-02-02_ad_intelligence.sql` (7 tables, 28 indexes)

### QA Passed
- All 17 files compile
- Full import chain works (models → helpers → services → agent → orchestrator → dependencies)
- Model validation: RunConfig defaults, BaselineSnapshot.is_sufficient, AdDiagnostic properties
- Helper tests: _safe_numeric, extract_conversions, compute_roas
- All 12 diagnostic rules registered with correct aggregation types
- Congruence scoring: 1.0 (perfect), 0.0 (max misalignment)
- ChatRenderer markdown output verified
- Agent: 9 tools with metadata
- Orchestrator: routing tool present, system prompt updated
- FeatureKey.AD_INTELLIGENCE in enable_all_features()

## Known Issues

### 1. Classifier Rate Limiting (HIGH PRIORITY)
`_classify_with_gemini()` creates a **new** `GeminiService()` instance on each call (line 655 of classifier_service.py). This means:
- The rate limiter configured in AgentDependencies is NOT inherited
- Usage tracking context is NOT inherited
- The `classify_batch` loop has NO delay between Gemini calls
- Risk: hitting Gemini API rate limits when classifying many ads

**Fix needed:** Pass the existing GeminiService instance through to the classifier (e.g., via constructor or from AgentDependencies), so it inherits the configured rate limiter and tracking context.

### 2. No Unit Tests Yet
Test directory created (`tests/services/ad_intelligence/`) but no test files written yet. Golden test cases (1-16 from plan) need implementation.

## What's Next
1. Fix classifier rate limiting (pass GeminiService through deps)
2. Manual testing with Wonder Paws brand
3. Write unit tests for golden test cases
4. Monitor Logfire during first real analysis run
