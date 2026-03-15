# Checkpoint: Cluster-Aware Interlinking, Re-run UI, GSC Link Opportunities

**Date:** 2026-03-14
**Branch:** `feat/ad-creator-v2-phase0`
**Plan:** `docs/plans/seo-content-workflow/PLAN_INTERLINKING_ENHANCEMENTS.md`

## Status: COMPLETE

All 6 phases implemented and QA'd. 73 tests passing (47 existing + 26 new).

---

## Phase 0: Critical Bug Fixes

| Bug | File | Fix | Status |
|-----|------|-----|--------|
| 0.1: `_build_article_payload` unpublishing | `cms_publisher_service.py` | Added `body_only=True` param to `ShopifyPublisher.update()`; `_push_html_to_cms` uses it | DONE |
| 0.2: Missing `published_url` filter | `interlinking_service.py:555` | Added `.not_.is_("published_url", "null")` to `_get_project_articles()` | DONE |
| 0.3: `anchor_text` NOT NULL constraint | `interlinking_service.py:599` | Always include `anchor_text` in insert dict, default `"(auto)"` | DONE |
| 0.4: One-off interlinking not pushing to CMS | `seo_workflow_service.py:436` | Pass `push_to_cms=True, brand_id, organization_id` | DONE |

## Phase A: Models & Helpers

| Item | File | Status |
|------|------|--------|
| `CLUSTER` LinkType enum | `models.py:74` | DONE |
| `find_clusters_for_article()` | `cluster_management_service.py:1476` | DONE |
| `_remove_related_section()` | `interlinking_service.py:611` | DONE |
| `_batch_count_inbound_links()` | `interlinking_service.py:653` | DONE |

## Phase B: Core Service Methods

| Method | File | Status |
|--------|------|--------|
| `interlink_cluster()` | `interlinking_service.py:358` | DONE |
| `_varied_anchor()` | `interlinking_service.py:475` | DONE |
| `find_linking_opportunities()` | `interlinking_service.py:505` | DONE |
| `rerun_interlinking()` | `seo_workflow_service.py:1489` | DONE |

## Phase C: Pipeline + Batch

| Item | File | Status |
|------|------|--------|
| InterlinkingNode cluster awareness + related sections | `nodes/interlinking.py` | DONE |
| `_execute_cluster_batch()` uses `interlink_cluster()` | `seo_workflow_service.py:1268` | DONE |

## Phase D: UI

| Item | File | Status |
|------|------|--------|
| "Re-run Links" button (4th action column) | `53_SEO_Workflow.py` | DONE |
| "Interlink Cluster" button + Push to CMS checkbox | `52_SEO_Clusters.py` | DONE |
| "GSC Opportunities" tab (4th tab) | `48_SEO_Dashboard.py` | DONE |

## Phase E: Prompt Cleanup

| Item | File | Status |
|------|------|--------|
| Remove "Related Articles" section instruction | `phase_c_optimize.txt:51` | DONE |
| Fix external link nofollow → dofollow guidance | `phase_c_optimize.txt:97` | DONE |

## Phase F: QA

- All 9 Python files pass `py_compile`
- 73 tests passing (26 new tests added for new methods)
- Test for `LinkType` enum updated to include `cluster`
- Pre-existing CMS test failures confirmed (not caused by this change)

---

## Files Changed

| File | Changes |
|------|---------|
| `viraltracker/services/seo_pipeline/models.py` | +1 enum value |
| `viraltracker/services/seo_pipeline/nodes/interlinking.py` | Cluster awareness + related sections |
| `viraltracker/services/seo_pipeline/services/cms_publisher_service.py` | `body_only` param on update() |
| `viraltracker/services/seo_pipeline/services/cluster_management_service.py` | `find_clusters_for_article()` |
| `viraltracker/services/seo_pipeline/services/interlinking_service.py` | 6 new methods + 3 bug fixes |
| `viraltracker/services/seo_pipeline/services/seo_workflow_service.py` | `rerun_interlinking()` + batch fix + one-off fix |
| `viraltracker/ui/pages/48_SEO_Dashboard.py` | GSC Opportunities tab |
| `viraltracker/ui/pages/52_SEO_Clusters.py` | Interlink Cluster button |
| `viraltracker/ui/pages/53_SEO_Workflow.py` | Re-run Links button |
| `viraltracker/services/seo_pipeline/prompts/phase_c_optimize.txt` | Remove Related Articles, fix nofollow |
| `tests/test_seo_pipeline_models.py` | Updated LinkType test |
| `tests/test_interlinking_service.py` | 26 new tests |
