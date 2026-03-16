# Plan: Iteration Lab UX Improvements

## Phase 1: Requirements

### Goal
Make it easy to visually scan ads, understand what's working/broken, and spot iteration opportunities. The user's core use case: find ads with strong performance in one metric but held back by another (e.g., 4% conversion rate + 1% CTR = ROAS below 1.0x), and analyze winners to understand replicable patterns.

### 6 Improvements

| # | Improvement | Scope |
|---|-------------|-------|
| 1 | **Metric formatting** | Fix `_format_metric` with explicit `from_decimal` param. CTR (%), ROAS (Xs), CPC ($) |
| 2 | **Lookback window on Analyze Winners** | Add "Days back" selector to Analyze Winners tab (matching Find Opportunities) |
| 3 | **Better opportunity explanations** | Data-driven plain-language explanations + proportional ROAS projection with caveat |
| 4 | **Visual ad identification everywhere** | Add thumbnails to Deep Dive winner selector + Winner Blueprint gallery |
| 5 | **Richer Winner Blueprint** | Winner thumbnail gallery, sub-threshold trends ("Also Notable"), cohort performance summary |
| 6 | **"Replicate Winner DNA" button** | Generate ads from Blueprint's element_combo + visual_directives via scheduled job |

### User Decisions
- **Projections**: Simple proportional, no cap, add caveat "assumes constant CVR"
- **Blueprint gallery**: Horizontal thumbnail row at top (80px) with ROAS labels
- **CTR format**: Display-layer fix only — add `from_decimal` param to `_format_metric`. Full service normalization deferred to tech debt (23 locations across 7 files).
- **Blueprint action**: Add "Replicate Winner DNA" button — auto-import winning ad + run V2 pipeline with `recreate_template` mode
- **Conversion rate in explanations**: Frame as messaging alignment signal ("your messaging resonates with buyers")

### QA-Identified Fixes (from review)
- **CTR normalization**: `value < 1` auto-detect heuristic fails for percentages 0-1% (e.g., 0.8% stored as 0.8 → incorrectly displays as 80%). Fix: normalize at service layer.
- **Session state serialization**: New `CrossWinnerAnalysis` fields must be added to `_run_cross_winner_analysis()` serialization block.
- **Explanation vs strategy_description**: Add new `explanation_headline` and `explanation_projection` fields to `IterationOpportunity` — don't overwrite `strategy_description` (still used by iterate confirmation).
- **Missing thumbnail fallback**: Show format badge in Deep Dive selector and Blueprint gallery when thumbnail is NULL.
- **Order by date**: Add `.order("date", desc=True)` to detector's performance query so first thumbnail is most recent.

### QA Round 2 — Blockers Fixed
- **`organization_id` not on `scheduled_jobs`**: Column does not exist on `scheduled_jobs` table. No existing job insertion in the codebase includes it. **Fixed**: Removed from `job_row` in Step 6.
- **`manual_template_ids` wrong name AND location**: Worker reads `scraped_template_ids` as a **top-level column** on `scheduled_jobs` (`job.get('scraped_template_ids')`), NOT from `parameters` JSONB. **Fixed**: Changed to top-level `"scraped_template_ids": [generated_ad_id]` in Step 6.
- **Private instance methods**: `_get_account_id()` and `_find_generated_ad()` are instance methods on `IterationOpportunityDetector` requiring `self.supabase`. **Fixed**: Step 6 creates detector instance and calls through it.
- **`MetaWinnerImportService` constructor**: Takes 0 args (creates its own Supabase client internally). **Fixed**: Changed to `MetaWinnerImportService()` (no args).
- **`generated_ads.reference_ad_filename` does not exist**: Plan queried this column but it's on `ad_runs.reference_ad_storage_path`. **Fixed**: Removed unnecessary query — V2 pipeline looks up template data from `generated_ad_id` itself.

---

## Phase 2: Architecture Decision

**Pattern**: Direct service modifications + UI changes. No new services, no pipelines, no agent changes.

**Reasoning**: All improvements are UI presentation + minor service enrichments. User controls the flow. The "Replicate Winner DNA" button reuses existing scheduled job infrastructure.

### Change Map

| File | Changes | Risk |
|------|---------|------|
| `viraltracker/ui/pages/38_🔬_Iteration_Lab.py` | All 6 improvements (UI) | Medium — largest change |
| `viraltracker/services/iteration_opportunity_detector.py` | Data-driven explanations, new fields on dataclass, order-by fix | Low |
| `viraltracker/services/winner_dna_analyzer.py` | `days_back` param, notable trends, cohort summary, winner thumbnails | Low-Medium |
| `viraltracker/services/ad_performance_query_service.py` | `thumbnail_url` in `_aggregate_by_ad()` | Low |

No new tables, no new files, no migration needed.

---

## Phase 3: Inventory & Gap Analysis

### What We Reuse
- `AdPerformanceQueryService.get_top_ads()` — already has `days_back` param
- `IterationOpportunityDetector` — already stores baselines; add explanation computation
- `WinnerDNAAnalyzer.analyze_cross_winners()` — already returns `winner_dnas`; pass `days_back`, extract thumbnails
- `_format_metric()` — exists in UI, needs fixing
- Scheduled job "Run Now" pattern — create one-time `ad_creation` job with `next_run_at` = now + 1 min

### What We Build (all modifications to existing files)

---

#### Step 1: Metric formatting fix (display-layer only)

**File**: `38_🔬_Iteration_Lab.py`

Add `from_decimal` parameter to `_format_metric`. The detector stores CTR as decimal (0.015); winner_dna_analyzer and ad_performance_query_service store as percentage (1.5). Each call site passes the appropriate flag.

```python
def _format_metric(metric: str, value: float, from_decimal: bool = False) -> str:
    """Format a metric value for display.

    Args:
        metric: Metric name (roas, ctr, cpc, etc.)
        value: Metric value.
        from_decimal: True if rate metrics (ctr, conversion_rate) are stored as
            decimals (0.015) rather than percentages (1.5). The detector uses
            decimals; winner_dna_analyzer and ad_performance_query_service use
            percentages.
    """
    if value is None:
        return "n/a"
    if metric in ("roas",):
        return f"{value:.1f}x"
    elif metric in ("ctr", "hook_rate", "hold_rate", "conversion_rate"):
        display = value * 100 if from_decimal else value
        return f"{display:.1f}%"
    elif metric in ("cpc", "cpa"):
        return f"${value:.2f}"
    elif metric in ("impressions",):
        return f"{value:,.0f}"
    elif metric in ("spend",):
        return f"${value:,.0f}"
    elif metric in ("ctr_decline_pct",):
        return f"-{abs(value) * 100:.0f}%" if value < 1 else f"-{value:.0f}%"
    else:
        return f"{value:.3f}"
```

**Call sites in Iteration Lab:**
- Opportunity cards (detector data): `_format_metric(metric, value, from_decimal=True)`
- Deep Dive / winner analysis (winner_dna data): `_format_metric(metric, value)` (default `from_decimal=False`)
- Cohort comparison: use `_format_metric` instead of raw `.4f`

**Tech debt**: Full service-layer CTR normalization deferred. See `docs/TECH_DEBT.md`.
Impact: 23 format locations across 7 files (30_Ad_Performance, 36_Experiments, ad_intelligence_agent, etc.).

---

#### Step 2: Lookback window on Analyze Winners

**Files**: `38_🔬_Iteration_Lab.py`, `winner_dna_analyzer.py`

**Service**: `_find_top_winners()` and `analyze_cross_winners()` accept `days_back`:
```python
async def analyze_cross_winners(self, brand_id, org_id, top_n=10, min_reward=0.65, days_back=30):
    winner_ads = self._find_top_winners(brand_id, top_n, min_reward, days_back)

def _find_top_winners(self, brand_id, top_n, min_reward, days_back=30):
    result = perf_service.get_top_ads(brand_id=brand_id, sort_by="roas", days_back=days_back, ...)
```

**UI**: Add `days_back` at top of Tab 2, shared across Blueprint and Deep Dive views:
```python
# In render_winners_tab():
col_mode, col_n, col_days = st.columns([3, 1, 1])
with col_mode:
    view_mode = st.radio("View", ["Winner Blueprint", "Deep Dive"], horizontal=True, ...)
with col_n:
    top_n = st.selectbox("Top N", [5, 10, 15, 20], index=1, ...)
with col_days:
    winner_days_back = st.selectbox("Days back", [14, 30, 60, 90], index=1, ...)
```

Pass `days_back` to both `_run_cross_winner_analysis()` and `_render_per_winner()`.

---

#### Step 3: Data-driven opportunity explanations

**Files**: `iteration_opportunity_detector.py`, `38_🔬_Iteration_Lab.py`

**New fields on `IterationOpportunity`** (don't overwrite `strategy_description`):
```python
explanation_headline: str = ""
explanation_projection: str = ""
projected_roas: float = 0.0
```

**New method `_build_explanation()`** — called during `_evaluate_pattern()`:

For **high_converter_low_stopper** (Strong ROAS, Weak CTR):
```python
cvr = ad.get("conversion_rate", 0)
headline = (
    f"This ad converts at {cvr*100:.1f}% — your messaging clearly resonates with buyers. "
    f"But CTR is only {ctr*100:.1f}%, meaning most people scroll past."
)
projected_roas = current_roas * (median_ctr / current_ctr)
projection = (
    f"If visual stopping power improved CTR to the median ({median_ctr*100:.1f}%), "
    f"ROAS could go from {current_roas:.1f}x to ~{projected_roas:.1f}x "
    f"(assumes constant conversion rate)."
)
```

For **good_hook_bad_close** (Strong CTR, Weak ROAS):
```python
headline = (
    f"This ad gets clicked at {ctr*100:.1f}% (above median) but ROAS is only {roas:.1f}x. "
    f"People are interested but not converting."
)
projection = (
    f"Your brand's median ROAS is {median_roas:.1f}x. "
    f"Improving offer alignment or landing page congruence could close the gap."
)
```

For **thumb_stopper_quick_dropper**, **efficient_but_starved**, **fatiguing_winner**:
Similar pattern-specific explanations using actual metric values.

**UI**: Show `explanation_headline` in the card summary (line 326). Show `explanation_projection` in the details expander alongside strategy actions.

Also add `.order("date", desc=True)` to detector's `_load_ads_with_performance()` query.

---

#### Step 4: Thumbnails everywhere

**Files**: `ad_performance_query_service.py`, `winner_dna_analyzer.py`, `38_🔬_Iteration_Lab.py`

**4a. `_aggregate_by_ad()` passthrough:**
```python
# In aggregation loop:
if d.get("thumbnail_url") and not a.get("thumbnail_url"):
    a["thumbnail_url"] = d["thumbnail_url"]

# In result:
"thumbnail_url": a.get("thumbnail_url", ""),
```

**4b. Deep Dive: Replace selectbox with visual card selector:**
```python
for i, ad in enumerate(top_ads[:10]):
    with st.container(border=True):
        col_thumb, col_info, col_btn = st.columns([1, 4, 1])
        with col_thumb:
            if ad.get("thumbnail_url"):
                st.image(ad["thumbnail_url"], width=60)
            else:
                st.markdown("🖼️")
        with col_info:
            st.markdown(f"**{ad.get('ad_name', '')[:40]}**")
            roas = ad.get('roas', 0)
            ctr = ad.get('ctr', 0)
            st.caption(f"ROAS {roas:.1f}x | CTR {ctr*100:.1f}% | ${ad.get('spend', 0):,.0f}")
        with col_btn:
            if st.button("Analyze", key=f"iter_analyze_{i}"):
                _run_per_winner_analysis(ad["meta_ad_id"], brand_id, org_id)
```

**4c. Winner Blueprint gallery** (at top of blueprint card):
```python
if winner_thumbnails:
    cols = st.columns(min(len(winner_thumbnails), 6))
    for i, thumb in enumerate(winner_thumbnails[:6]):
        with cols[i]:
            if thumb.get("thumbnail_url"):
                st.image(thumb["thumbnail_url"], width=80)
            else:
                st.markdown("🖼️")
            st.caption(f"{thumb.get('roas', 0):.1f}x")
```

**4d. Per-winner Deep Dive thumbnail** at top of results:
Fetch `thumbnail_url` from `meta_ads_performance` alongside metrics. Show at top of DNA card.

**4e. winner_dna_analyzer**: Collect thumbnails from `winner_ads` during `analyze_cross_winners()`.

---

#### Step 5: Richer Winner Blueprint

**Files**: `winner_dna_analyzer.py`, `38_🔬_Iteration_Lab.py`

**New fields on `CrossWinnerAnalysis`:**
```python
notable_elements: Dict[str, Any] = field(default_factory=dict)
notable_visual_traits: Dict[str, Any] = field(default_factory=dict)
cohort_summary: Dict[str, Any] = field(default_factory=dict)
winner_thumbnails: List[Dict] = field(default_factory=list)
```

**5a. Sub-threshold "Also Notable" trends (25-49% frequency):**
Add second pass in `_find_common_elements()` and `_find_common_visual_traits()` with 25% threshold. Cap at 5 items.

**5b. Cohort performance summary:**
```python
cohort_summary = {
    "avg_roas": statistics.mean([d.metrics.get("roas", 0) for d in winner_dnas]),
    "roas_range": [min_roas, max_roas],
    "avg_ctr": statistics.mean([d.metrics.get("ctr", 0) for d in winner_dnas]),
    "ctr_range": [min_ctr, max_ctr],
    "total_spend": sum(d.metrics.get("spend", 0) for d in winner_dnas),
    "avg_cpa": statistics.mean([d.metrics.get("cpa", 0) for d in winner_dnas if d.metrics.get("cpa")]),
}
```

**UI**: Metrics row above thumbnail gallery:
```python
m1, m2, m3, m4 = st.columns(4)
with m1:
    st.metric("Avg ROAS", f"{summary['avg_roas']:.1f}x")
with m2:
    st.metric("CTR Range", f"{summary['ctr_range'][0]*100:.1f}%–{summary['ctr_range'][1]*100:.1f}%")
with m3:
    st.metric("Total Spend", f"${summary['total_spend']:,.0f}")
with m4:
    st.metric("Avg CPA", f"${summary.get('avg_cpa', 0):,.2f}")
```

**5c. Session state serialization** — update `_run_cross_winner_analysis()`:
```python
st.session_state.iter_cross_winner_result = {
    # existing fields...
    "notable_elements": result.notable_elements,
    "notable_visual_traits": result.notable_visual_traits,
    "cohort_summary": result.cohort_summary,
    "winner_thumbnails": result.winner_thumbnails,
}
```

---

#### Step 6: "Replicate Winner DNA" button

**File**: `38_🔬_Iteration_Lab.py`

Adds a button to the Winner Blueprint that creates a one-time `ad_creation` scheduled job using the blueprint's parameters.

**UI flow:**
1. "Replicate Winner DNA" button below the Blueprint card
2. Expands confirmation section with:
   - Product selector (required)
   - Pre-filled instructions from blueprint (editable text area)
   - Number of variations (default 5)
   - "Generate" button
3. On click: creates `scheduled_jobs` row with `job_type='ad_creation'`, `next_run_at` = now + 1 minute
4. Shows success message with link to Scheduled Tasks page

**Blueprint → instructions conversion:**
```python
def _blueprint_to_instructions(blueprint: dict) -> str:
    lines = ["WINNER DNA REPLICATION BRIEF:"]
    element_combo = blueprint.get("element_combo", {})
    visual = blueprint.get("visual_directives", {})
    messaging = blueprint.get("messaging_directives", {})

    if element_combo:
        lines.append("Creative elements to use:")
        for k, v in element_combo.items():
            label = ELEMENT_DISPLAY_NAMES.get(k, k.replace('_', ' ').title())
            lines.append(f"  - {label}: {v}")

    if visual:
        lines.append("Visual directives:")
        for k, v in visual.items():
            lines.append(f"  - {k.replace('_', ' ').title()}: {v}")

    if messaging:
        lines.append("Messaging directives:")
        for k, v in messaging.items():
            label = ELEMENT_DISPLAY_NAMES.get(k, k.replace('_', ' ').title())
            lines.append(f"  - {label}: {v}")

    return "\n".join(lines)
```

**Flow:**
1. User selects a winner from the thumbnail gallery
2. System checks `meta_ad_mapping` for existing template
3. If no template: auto-import via `MetaWinnerImportService` (same as Iterate button)
4. Create one-time V2 job with the winning ad as reference template

```python
import json
from datetime import datetime, timedelta
from viraltracker.services.iteration_opportunity_detector import IterationOpportunityDetector
from viraltracker.core.database import get_supabase_client

# Step 1: Find or import the winning ad as a template
detector = IterationOpportunityDetector(get_supabase_client())
meta_ad_id = selected_winner["meta_ad_id"]
generated_ad_id = detector._find_generated_ad(meta_ad_id, brand_id)

if not generated_ad_id:
    # Auto-import winning ad (constructor takes 0 args — creates its own client)
    from viraltracker.services.meta_winner_import_service import MetaWinnerImportService
    import_service = MetaWinnerImportService()
    meta_ad_account_id = detector._get_account_id(meta_ad_id)
    import_result = await import_service.import_meta_winner(
        brand_id=UUID(brand_id),
        meta_ad_id=meta_ad_id,
        product_id=UUID(product_id),
        meta_ad_account_id=meta_ad_account_id,
        extract_element_tags=True,
    )
    generated_ad_id = import_result.get("generated_ad_id")

# Step 2: Create V2 job with recreate_template mode
# (V2 pipeline looks up template data from generated_ad_id itself)
# NOTE: scraped_template_ids is a TOP-LEVEL column (UUID[]), NOT in parameters JSONB
# NOTE: scheduled_jobs has NO organization_id column — do not include it
job_row = {
    "name": f"Blueprint Replication — {brand_name}",
    "job_type": "ad_creation_v2",
    "brand_id": brand_id,
    "product_id": product_id,
    "schedule_type": "one_time",
    "next_run_at": (datetime.utcnow() + timedelta(minutes=1)).isoformat(),
    "is_active": True,
    "scraped_template_ids": [generated_ad_id],
    "parameters": json.dumps({
        "content_source": "recreate_template",
        "template_selection_mode": "manual",
        "num_variations": num_variations,
        "canvas_sizes": ["1080x1080px"],
        "color_modes": ["original"],
        "additional_instructions": instructions,
    }),
}
get_supabase_client().table("scheduled_jobs").insert(job_row).execute()
```

Uses `ad_creation_v2` with `recreate_template` mode — the winning ad IS the template, and the blueprint directives guide how to iterate on it.

---

## Phase 4: Build Order

| Step | What | File(s) | Depends On |
|------|------|---------|------------|
| 1 | Fix `_format_metric` with `from_decimal` param | UI | None |
| 2 | Add `days_back` param to winner analysis | `winner_dna_analyzer.py`, UI | None |
| 3 | Add `thumbnail_url` to `_aggregate_by_ad()` | `ad_performance_query_service.py` | None |
| 4 | Data-driven opportunity explanations | `iteration_opportunity_detector.py`, UI | Step 1 |
| 5 | Thumbnails in Deep Dive (card selector) | UI | Step 3 |
| 6 | Winner Blueprint: gallery + notable + cohort + replicate button | `winner_dna_analyzer.py`, UI | Steps 2, 3 |
| 7 | QA: py_compile all files, add CTR normalization to tech debt | All | All |

Steps 1-3 are independent (parallel). Steps 4-6 build on them. Step 7 is final QA.

---

## Risks & Mitigations

| Risk | Mitigation |
|------|-----------|
| CTR decimal/percentage mismatch | Display-layer fix with `from_decimal` param. Full normalization deferred to tech debt. |
| `thumbnail_url` is NULL for some ads | Show 🖼️ format badge as fallback everywhere |
| ROAS projection misleading for large gaps | Add caveat text: "assumes constant conversion rate" |
| Sub-threshold trends create noise | Cap at 5 notable items, only ≥ 25% frequency |
| Blueprint replication needs a template | Auto-imports winning ad via MetaWinnerImportService if not already a template |
| Session state missing new fields | Explicitly add all 4 new CrossWinnerAnalysis fields to serialization |

---

## Files Modified (Complete List)

1. `viraltracker/ui/pages/38_🔬_Iteration_Lab.py` — All 6 improvements (UI)
2. `viraltracker/services/iteration_opportunity_detector.py` — Data-driven explanations, new fields, order-by fix
3. `viraltracker/services/winner_dna_analyzer.py` — `days_back`, CTR normalization, notable trends, cohort summary, thumbnails
4. `viraltracker/services/ad_performance_query_service.py` — `thumbnail_url`, CTR/conversion_rate normalization

No new files. No migrations. No dependency changes.
