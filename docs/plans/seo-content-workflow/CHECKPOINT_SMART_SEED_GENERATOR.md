# Checkpoint: Brand-Aware Smart Seed Generator

**Date**: 2026-03-13
**Branch**: `feat/ad-creator-v2-phase0`
**Status**: Implementation complete, pending live testing

## What Was Built

### New Service: `BrandSeedGeneratorService`
**File**: `viraltracker/services/seo_pipeline/services/brand_seed_generator_service.py` (~430 lines)

Two-step AI-powered flow for generating cluster research seeds from brand data:

1. **`discover_topics(brand_id, org_id)`** — Gathers brand context across 4 data tiers, calls Claude Sonnet to suggest 5-8 content topics with rationale, source attribution, and gap detection.

2. **`generate_seeds_for_topics(topics, brand_context, org_id)`** — For selected topics, generates 8-12 long-tail search phrases using customer language patterns. Deduplicates via Jaccard similarity (>0.6) on stemmed word sets.

### Brand Context Extraction (4 Tiers)
- **Tier 1**: Products (name, benefits, problems solved, ingredients, FAQ) + offer variants (pain points, desires, mechanisms, hooks)
- **Tier 2**: Angle candidates (belief statements, confidence), discovered patterns, persona insights (pain points, JTBDs, transformation maps)
- **Tier 3**: GSC opportunities (page 2-3 keywords with impressions), existing article keywords
- **Tier 4**: Brand name/description, content style guide, available tags

Each tier has independent try/except — partial data still produces useful results.

### UI Changes: Cluster Builder Sub-tabs
**File**: `viraltracker/ui/pages/53_🚀_SEO_Workflow.py` (~200 lines added)

Cluster Builder tab now has two sub-tabs:

**Smart Research** — 3-state flow:
1. "Discover Topics" button → spinner → topic checkboxes with GAP badges and source attribution
2. Topic review: check/uncheck AI topics, add custom topics
3. "Generate Seeds" → seed review grouped by topic with intent icons (💰 commercial, ⚖️ comparison, ℹ️ informational) → "Run Cluster Research" feeds into existing pipeline

**Manual Research** — Existing form moved here unchanged (seed textarea + source checkboxes + mode radio).

Batch progress, report display, and recent batches remain shared below both sub-tabs.

### Key Patterns Followed
- Lazy-loaded Supabase + Anthropic clients (matches `content_generation_service.py`)
- `claude-sonnet-4-20250514` model (matches `seo_workflow_service.py:948`)
- JSON extraction via `re.search(r"\{[\s\S]*\}", text)` + `json.loads()`
- Usage tracking via `UsageTracker` with `provider="anthropic"`, `tool_name="seo_pipeline"`
- All DB queries schema-verified against actual migrations

## Files Changed

| File | Action | Lines |
|------|--------|-------|
| `viraltracker/services/seo_pipeline/services/brand_seed_generator_service.py` | CREATE | ~430 |
| `viraltracker/ui/pages/53_🚀_SEO_Workflow.py` | MODIFY | ~200 added |

## What's Next

1. **Live test with YaketyPack** (full data stack) — verify topics use real customer language
2. **Live test with minimal brand** — verify graceful degradation with warnings
3. **Test topic editing** — add custom topic, uncheck AI topics, verify seeds only for selected
4. **End-to-end** — Smart Research → topics → seeds → cluster research → generate cluster → articles
5. **Manual fallback** — verify Manual Research tab works unchanged
