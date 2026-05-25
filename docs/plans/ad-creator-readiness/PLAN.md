# Ad Creator V2 — Readiness Panel

**Status**: in implementation
**Owner**: RyeMcKenzie81
**Added**: 2026-05-22

## Why

Today's Smart Select incident on Martin Clinic exposed a class of *silent
configuration gaps*: every product image had zero `asset_tags`, which collapsed
the effective template pool from 3,134 → 432 (~86% of templates were invisible
to `AssetMatchScorer`). The user only noticed because the same handful of
templates kept resurfacing. Nothing in the UI surfaced the underlying gap.

Several adjacent inputs have the same property — when missing, scorers fall
back to neutral values, the ad still generates, but quality silently degrades:

- Product images missing → V2 can still run but uses cached references
- Product images missing `asset_tags` → `asset_match` collapses
- Persona not attached / missing demographics → `audience_match` + `awareness_align` neutralize
- Offer variant missing UMP / UMS / sample hooks → no mechanism-aware copy
- Brand voice / current offer empty → generic ads
- Recent runs concentrated on a few templates → likely asset-tag or pool issue

## Goal

After the user picks brand → product (and optionally an offer variant) in
Ad Creator V2, surface a small readiness panel that traffic-lights these
checks and tells the user exactly where to fix each gap.

## Non-goals

- Refactoring the existing `tool_readiness_service` (brand-level, different
  shape). The new service is per-(brand, product, variant), not per-brand.
- Blocking submit. The panel is advisory — `BLOCKED` rows are warnings, not
  hard stops, because some checks (e.g., "no persona attached") are valid
  user choices.
- Auto-fixing anything. Each check returns a fix hint + page link; the user
  clicks through.
- Adding checks for other pipelines (SEO, content pipeline, etc.). This panel
  is scoped to Ad Creator V2.

## Architecture

### Service

`viraltracker/services/ad_creator_readiness_service.py`

```python
class AdCreatorReadinessService:
    def check(
        self,
        brand_id: UUID,
        product_id: UUID,
        offer_variant_id: Optional[UUID] = None,
    ) -> ReadinessReport:
        ...
```

Returns a `ReadinessReport` with one `ReadinessCheck` per dimension. Service
runs sync — every check is a small Supabase query or a Python-side
computation against already-cached data.

### Models

Co-located with other Pydantic models in `viraltracker/services/models.py`
(or a new submodule if it grows). Each check is structured:

```python
class ReadinessStatus(str, Enum):
    OK = "ok"
    WARNING = "warning"
    BLOCKED = "blocked"
    SKIPPED = "skipped"  # variant check when no variant selected

class ReadinessCheck(BaseModel):
    key: str           # stable identifier — "product_images", "asset_tags", etc.
    label: str         # user-facing label — "Product images"
    status: ReadinessStatus
    summary: str       # one-line current state — "8 images uploaded"
    fix_hint: Optional[str]  # what to do — "Upload at least one image"
    fix_page: Optional[str]  # streamlit page path — "pages/02_🏢_Brand_Manager.py"

class ReadinessReport(BaseModel):
    overall: ReadinessStatus  # worst-case across checks
    checks: List[ReadinessCheck]
```

### Checks (v1 scope)

| Key | Source | Status logic |
|---|---|---|
| `product_images` | `product_images` count for product | 0 → BLOCKED, 1-4 → WARNING, 5+ → OK |
| `asset_tags` | `prefetch_product_asset_tags(product_id)` + effective pool calc | 0 tags → WARNING (pool ≤ 432), some tags + effective pool < 25% of active → WARNING, otherwise OK |
| `persona` | `personas` row for product | None → WARNING, exists but missing demographics → WARNING, complete → OK |
| `offer_variant_mechanism` | `product_offer_variants` row | variant_id None → SKIPPED, has mech_name + mech_problem + mech_solution + 2+ sample_hooks → OK, otherwise WARNING |
| `brand_voice` | `brands.brand_voice` | empty/None → WARNING, set → OK |
| `recent_template_diversity` | `ad_runs` for product, last 14d | 0 runs → SKIPPED, distinct/total < 0.5 → WARNING, ≥ 0.5 → OK |

`overall = max(any BLOCKED → BLOCKED, any WARNING → WARNING, else OK)`. SKIPPED rows don't influence overall.

### UI integration

In `viraltracker/ui/pages/21b_🎨_Ad_Creator_V2.py`:

- Add `render_readiness_panel(brand_id, product_id)` helper at module scope.
- Call it once, after the product is confirmed (around line 2061, just before
  `render_template_selection()`).
- Display as a Streamlit expander labeled "Readiness check — N issues" /
  "Readiness check — all clear ✅".
- Auto-expand if `overall != OK`.
- Each row: status icon + label + summary, with the fix hint and a `st.page_link`
  to the relevant page when available.

### Effective pool calculation

`asset_tags` check needs the effective template pool size. Cheap version:

```python
# In service:
candidates = await fetch_template_candidates(product_id)
effective = sum(
    1 for c in candidates
    if AssetMatchScorer().score(c, context_with_product_tags) >= 1.0
)
```

This reuses code already in `template_scoring_service.py`. Total runtime: one
templates query (already paginated, ~3K rows) + one product_images query +
in-memory set intersections. Sub-second.

To keep the panel fast, cache the result for the (brand, product, variant)
tuple in `st.session_state` for the lifetime of the page render. Invalidate
when product changes (same trigger as line 2041's reset cascade).

## Risks & edge cases

- **Brand has no products yet** — page already `st.stop()`s before product
  selection. Panel never runs.
- **Variant not yet selected** — `offer_variant_mechanism` returns SKIPPED.
  Other checks still fire.
- **Recently uploaded product with zero history** — `recent_template_diversity`
  returns SKIPPED (no signal yet).
- **Multi-tenant** — service must filter by `organization_id` where relevant
  (brands query) and respect `"all"` superuser mode. Pattern: use existing
  helpers, don't introduce new org logic here.
- **Streamlit rerun cost** — panel runs on every interaction. Use session-state
  cache keyed by `(product_id, variant_id)` to avoid hitting Supabase on every
  keystroke.

## Test plan

- Unit tests for `AdCreatorReadinessService.check()` covering each check's
  OK / WARNING / BLOCKED / SKIPPED branches with mocked Supabase.
- Manual smoke on Martin Clinic / The Big Three Bundle:
  - Before any variant pick: 5 checks fire, `asset_tags` should now be `OK`
    (since we tagged earlier today), `persona`/`brand_voice` likely WARNING.
  - After variant pick: variant check turns from SKIPPED to OK/WARNING.
- Manual smoke on a brand with no products → page already stops, panel never
  shown. (Verify no crash path through the helper.)

## Out of scope (follow-ups)

- Auto-fix actions ("Tag all images as `product:bottle`" button).
- Bulk readiness across all products for a brand (use existing tool readiness
  for that).
- Persisting the report — every check is cheap, no need to store.
- Integration into Ad Creator V1 (V1 is being phased out per roadmap).
