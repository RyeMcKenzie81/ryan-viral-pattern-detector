# SEO Pipeline Port — Phase 7 Checkpoint: Pipeline Graph

**Date**: 2026-03-03
**Branch**: `worktree-seo-pipeline-port`
**Status**: COMPLETE
**Tests**: 431 passing (387 from Phases 1-6 + 44 new)

---

## What Was Built

### 1. Pipeline Graph Nodes (12 nodes in 6 files)

Each node is a thin wrapper following the pydantic-graph `BaseNode` pattern,
delegating all business logic to the Phase 1-6 services.

| Node | File | Type | Service |
|------|------|------|---------|
| `KeywordDiscoveryNode` | `keyword_discovery.py` | Automated | KeywordDiscoveryService |
| `KeywordSelectionNode` | `keyword_selection.py` | **HUMAN** | — |
| `CompetitorAnalysisNode` | `competitor_analysis.py` | Automated | CompetitorAnalysisService |
| `ContentPhaseANode` | `content_generation.py` | Automated (LLM) | ContentGenerationService |
| `OutlineReviewNode` | `content_generation.py` | **HUMAN** | — |
| `ContentPhaseBNode` | `content_generation.py` | Automated (LLM) | ContentGenerationService |
| `ContentPhaseCNode` | `content_generation.py` | Automated (LLM) | ContentGenerationService |
| `ArticleReviewNode` | `article_review.py` | **HUMAN** | — |
| `QAValidationNode` | `qa_publish.py` | Automated | QAValidationService |
| `QAApprovalNode` | `qa_publish.py` | **HUMAN** | — |
| `PublishNode` | `qa_publish.py` | Automated | CMSPublisherService |
| `InterlinkingNode` | `interlinking.py` | Automated | InterlinkingService |

### 2. Human Checkpoints (4 pause points)

| Checkpoint | After Step | Actions Available |
|-----------|-----------|-------------------|
| `keyword_selection` | Discovery | `select` (pick keyword), `rediscover` (new seeds) |
| `outline_review` | Phase A | `approve` (continue), `regenerate` (redo Phase A) |
| `article_review` | Phase C | `approve` (QA), `regenerate` (redo C), `restart` (redo A) |
| `qa_approval` | QA check | `approve` (publish), `override` (force publish), `fix` (redo C) |

### 3. Orchestrator (`orchestrator.py`)

- **`seo_pipeline_graph`** — Graph definition with all 12 nodes
- **`run_seo_pipeline()`** — Entry point: creates state, starts from KeywordDiscoveryNode
- **`resume_seo_pipeline()`** — Resume from checkpoint with human input
- **`get_pipeline_status()`** — Query current pipeline state (step, checkpoint, errors)
- **State persistence** — Saves/loads state to `seo_projects.workflow_data` via SEOProjectService

### 4. Pipeline Flow

```
KeywordDiscovery → KeywordSelection (H) → CompetitorAnalysis
→ PhaseA → OutlineReview (H) → PhaseB → PhaseC
→ ArticleReview (H) → QAValidation → QAApproval (H)
→ Publish → Interlinking → End
```

### 5. Key Design Decisions

- **Interlinking is non-fatal**: If interlinking fails after publishing, the pipeline still completes with `status: "complete_with_warnings"`
- **QA approval gate**: `approve` is blocked when QA fails (must use `override` to force-publish)
- **Node metadata**: All nodes have `ClassVar[NodeMetadata]` for visualization/debugging
- **Lazy service imports**: Services imported inside `run()` to avoid circular dependencies and heavy startup cost
- **UUID resilience**: `KeywordSelectionNode` gracefully handles non-UUID keyword IDs

---

## Test Coverage

| Test Class | Tests | What's Tested |
|-----------|-------|---------------|
| `TestGraphDefinition` | 4 | Node count, name, checkpoint mapping, node names |
| `TestNodeMetadata` | 2 | All nodes have metadata, LLM nodes annotated |
| `TestKeywordDiscoveryNode` | 2 | Successful discovery, service failure |
| `TestKeywordSelectionNode` | 5 | Pause, resume+select, competitor URLs, rediscover, invalid action |
| `TestCompetitorAnalysisNode` | 3 | Success, partial failure, no URLs |
| `TestContentPhaseANode` | 3 | Create+run, existing article, failure |
| `TestOutlineReviewNode` | 3 | Pause, approve, regenerate |
| `TestContentPhaseBNode` | 1 | Phase B execution |
| `TestContentPhaseCNode` | 1 | Phase C execution |
| `TestArticleReviewNode` | 4 | Pause, approve, regenerate, restart |
| `TestQAValidationNode` | 2 | QA pass, QA fail (still proceeds) |
| `TestQAApprovalNode` | 5 | Pause, approve, block failed QA, override, fix |
| `TestPublishNode` | 2 | Success, CMS failure |
| `TestInterlinkingNode` | 2 | Success, non-fatal failure |
| `TestGetPipelineStatus` | 4 | Not started, at checkpoint, completed, error |
| **Phase 7 total** | **44** | |

---

## Files Created

```
viraltracker/services/seo_pipeline/nodes/keyword_discovery.py
viraltracker/services/seo_pipeline/nodes/keyword_selection.py
viraltracker/services/seo_pipeline/nodes/competitor_analysis.py
viraltracker/services/seo_pipeline/nodes/content_generation.py
viraltracker/services/seo_pipeline/nodes/article_review.py
viraltracker/services/seo_pipeline/nodes/qa_publish.py
viraltracker/services/seo_pipeline/nodes/interlinking.py
viraltracker/services/seo_pipeline/orchestrator.py
tests/test_seo_pipeline_graph.py
docs/plans/seo-pipeline-port/CHECKPOINT_PHASE_7.md
```

## Files Modified

```
viraltracker/services/seo_pipeline/nodes/__init__.py  (added all node exports)
```

---

## Cumulative Progress — All Phases Complete

| Phase | Status | Services/Files | Tests |
|-------|--------|----------------|-------|
| 1: Models & State | DONE | models.py, state.py, project_service | 48 |
| 2: Keyword Discovery | DONE | keyword_discovery_service | 77 |
| 3: Competitor Analysis | DONE | competitor_analysis_service | 35 |
| 4: Content Generation | DONE | content_generation_service, prompts | 40 |
| 5: Publishing + QA | DONE | qa_validation_service, cms_publisher_service | 95 |
| 6: Tracking + Interlinking | DONE | interlinking, tracking, analytics services | 92 |
| 7: Pipeline Graph | DONE | 12 nodes, orchestrator | 44 |
| **Total** | **ALL DONE** | **9 services, 12 nodes, 1 orchestrator** | **431 tests** |

---

## Architecture Summary

```
viraltracker/services/seo_pipeline/
├── __init__.py
├── models.py               # 8 enums + 7 Pydantic models
├── state.py                # SEOPipelineState dataclass + checkpoints
├── orchestrator.py         # Graph + run/resume/status
├── nodes/                  # 12 thin graph nodes
│   ├── __init__.py
│   ├── keyword_discovery.py
│   ├── keyword_selection.py
│   ├── competitor_analysis.py
│   ├── content_generation.py  (PhaseA, OutlineReview, PhaseB, PhaseC)
│   ├── article_review.py
│   ├── qa_publish.py          (QAValidation, QAApproval, Publish)
│   └── interlinking.py
├── services/               # 9 business logic services
│   ├── __init__.py
│   ├── seo_project_service.py
│   ├── keyword_discovery_service.py
│   ├── competitor_analysis_service.py
│   ├── content_generation_service.py
│   ├── qa_validation_service.py
│   ├── cms_publisher_service.py
│   ├── article_tracking_service.py
│   ├── interlinking_service.py
│   └── seo_analytics_service.py
└── prompts/                # 3 parameterized prompt templates
    ├── phase_a_research.txt
    ├── phase_b_write.txt
    └── phase_c_optimize.txt

UI Pages:
├── 48_🔍_SEO_Dashboard.py
├── 49_🔑_Keyword_Research.py
├── 50_✍️_Article_Writer.py
└── 51_📤_Article_Publisher.py

CLI: viraltracker/cli/seo.py (20+ subcommands)
Migration: migrations/2026-03-02_seo_pipeline_tables.sql (9 tables)
Tests: 12 test files, 431 tests
```
