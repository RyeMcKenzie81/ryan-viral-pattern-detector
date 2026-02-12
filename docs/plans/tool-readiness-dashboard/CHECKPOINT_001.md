# Tool Readiness Dashboard — Checkpoint 001

**Date:** 2026-02-11
**Phase:** Full Implementation Complete (Phases A-D)
**Status:** Implementation complete, pending manual QA in browser

## What Was Built

### Feature Registration

1. **`FeatureKey.TOOL_READINESS`** (`viraltracker/services/feature_service.py:55`)
   - Added to Brands page keys section
   - Added to `enable_all_features()` list
   - Opt-in: hidden by default, enable per-org in Admin

2. **Navigation entry** (`viraltracker/ui/nav.py:234`)
   - Added to Brands section after Brand Research
   - Page file: `pages/07_📥_Tool_Readiness.py`
   - Superuser dict includes `FeatureKey.TOOL_READINESS: True`

3. **Admin toggle** (`viraltracker/ui/pages/69_🔧_Admin.py:383`)
   - Added `(FeatureKey.TOOL_READINESS, "Tool Readiness")` to Brands opt-in list

### Data Models (`viraltracker/services/models.py`)

4. **6 Pydantic models** added at end of file:
   - `ReadinessStatus` — Enum: ready, partial, blocked, n/a
   - `RequirementType` — Enum: hard, soft, freshness
   - `RequirementResult` — Single requirement evaluation result
   - `ToolReadiness` — Full readiness assessment for one tool
   - `ToolReadinessReport` — Complete report for a brand (grouped by status)

### Requirements Registry (`viraltracker/ui/tool_readiness_requirements.py`)

5. **Declarative config for 13 tools** — single source of truth for tool prerequisites:

   | Tool | Hard | Soft | Freshness |
   |------|------|------|-----------|
   | Brand Research | has_products | has_ad_library_url, has_ad_account | — |
   | Ad Performance | has_ad_account | has_ads | meta_ads_performance |
   | URL Mapping | has_products, has_ads | has_product_urls | — |
   | Competitor Research | — (applicable_when: has competitors) | competitor_ad_library_urls | — |
   | Ad Creator | has_products | has_offer_variants, has_personas, has_templates, has_angles | — |
   | Hook Analysis | has_ads | — | ad_classifications |
   | Congruence Insights | has_ads | — | ad_classifications, landing_pages |
   | Landing Page Analyzer | — | has_landing_pages | — |
   | Personas | has_products | has_brand_ads, has_amazon_reviews | — |
   | Research Insights | has_products | has_candidates | — |
   | Ad Planning | has_products | has_angles, has_templates | — |
   | Template Queue | — | — | templates_scraped |
   | Template Evaluation | — | — | templates_evaluated |
   | Competitive Analysis | — (applicable_when: has competitors) | has_brand_personas | — |

6. **Check types implemented:**
   - `count_gt_zero` — `SELECT id FROM {table} WHERE {filters} LIMIT 1` (memoized)
   - `count_via_products` — Join through products table for tables without `brand_id`
   - `count_any_of` — Check multiple tables, True if any has rows
   - `field_not_null` — Check specific field is not null/empty
   - `competitors_have_field` — Count competitors with non-null field vs total
   - `dataset_fresh` — Derived from prefetched `DatasetFreshnessService` data

### Service (`viraltracker/services/tool_readiness_service.py`)

7. **`ToolReadinessService`** — Evaluates all requirements for a brand:
   - Constructor initializes Supabase client + `DatasetFreshnessService`
   - `get_readiness_report(brand_id)` — main entry point, returns `ToolReadinessReport`
   - Per-request `_memo` dict prevents duplicate Supabase queries
   - Prefetches all freshness data with single `get_all_freshness()` call
   - Feature gating: skips tools whose feature is disabled for the brand's org
   - `applicable_when` rules: competitor-dependent tools → NOT_APPLICABLE when no competitors
   - Graceful NULL `organization_id` handling: skips feature gating for orphaned brands
   - ISO `Z` suffix handling: `.replace("Z", "+00:00")` before `fromisoformat()`

### UI Page (`viraltracker/ui/pages/07_📥_Tool_Readiness.py`)

8. **Tool Readiness page:**
   - Brand selector (shared `render_brand_selector()`)
   - Progress bar: `{ready}/{total} tools ready`
   - Three sections: Ready (green), Partially Ready (orange), Blocked (red)
   - Each tool card shows: icon + label, unmet requirements with badges, fix action links
   - Not Applicable section in collapsed expander
   - Session state caching with refresh button
   - Zero-data "Getting Started" card when no tools are ready
   - `_time_ago()` helper for relative timestamps
   - `st.page_link()` wrapped in try/except for disabled feature pages

### Bugfix (separate)

9. **`PIPELINE_MANAGER` missing from `enable_all_features()`** (`feature_service.py:267`)
   - Added `FeatureKey.PIPELINE_MANAGER` after `PIPELINE_VISUALIZER`
   - Pre-existing bug: Pipeline Manager wasn't enabled by "Enable All" in Admin

## Architecture Decisions

- **Tool-centric, not data-level**: Dashboard answers "which tools can I use?" rather than tracking data ingestion levels. More actionable for users.
- **Registry is single source of truth**: `tool_readiness_requirements.py` owns all tool prerequisites. No ad-hoc checks scattered across pages.
- **Reuses existing infrastructure**: `DatasetFreshnessService` + `dataset_status` table for freshness checks. No parallel freshness logic.
- **Read-only**: No mutations, no AI calls, no side effects. Pure data reads + in-memory evaluation.
- **Memoization**: Per-request `_memo` dict caches repeated checks (e.g. `has_products` used by 5 tools).
- **Safe job types**: Only `meta_sync`, `ad_classification`, `template_approval` are safe for auto-queue (only need brand_id). Others show page links only.

## Files Changed

| File | Action | Lines Changed |
|------|--------|---------------|
| `viraltracker/services/feature_service.py` | EDIT | +3 lines (FeatureKey + enable_all_features + PIPELINE_MANAGER fix) |
| `viraltracker/services/models.py` | EDIT | +52 lines (6 Pydantic models) |
| `viraltracker/ui/nav.py` | EDIT | +2 lines (page entry + superuser dict) |
| `viraltracker/ui/pages/69_🔧_Admin.py` | EDIT | +1 line (opt-in entry) |
| `viraltracker/ui/tool_readiness_requirements.py` | NEW | ~370 lines |
| `viraltracker/services/tool_readiness_service.py` | NEW | ~335 lines |
| `viraltracker/ui/pages/07_📥_Tool_Readiness.py` | NEW | ~125 lines |

## Post-Plan Review

**Verdict: PASS**

| Check | Status |
|-------|--------|
| G1: Validation consistency | PASS — New types only used in new files |
| G2: Error handling | PASS — All exceptions logged, no bare except:pass in service |
| G3: Service boundary | PASS — UI calls service only |
| G4: Schema drift | PASS — No DB changes |
| G5: Security | PASS — No secrets, parameterized queries |
| G6: Import hygiene | PASS — All 7 files compile, no debug code |
| T2: Syntax verification | PASS — `py_compile` passes all files |

## What's Next

- Manual QA in browser (3 scenarios: full data, no data, mixed data)
- Commit and push
