# Phase 7: Hook Performance Queries - Implementation Plan

**Date:** 2026-02-04
**Status:** Planning
**Goal:** Surface which hooks work best across an account, enabling data-driven creative decisions

---

## Metrics Philosophy

### Primary Metrics

| Metric | Source | What it measures |
|--------|--------|------------------|
| **Hook Rate** | `meta_ads_performance.hook_rate` | % viewers past first 3 sec (video engagement) |
| **ROAS** | `purchase_value / spend` | Profitability |
| **Spend** | `meta_ads_performance.spend` | Scale / advertiser confidence |
| **CTR** | `meta_ads_performance.ctr` | Click engagement |
| **CPA** | `spend / purchases` | Acquisition efficiency |

### Quadrant Analysis (Key Insight)

Plotting **Hook Rate vs ROAS** reveals actionable patterns:

```
                    HIGH ROAS
                        │
     🎯 WINNERS         │         🔍 HIDDEN GEMS
     High hook rate     │         Low hook rate
     High ROAS          │         High ROAS
     → SCALE THESE      │         → Why low engagement?
                        │
────────────────────────┼────────────────────────
                        │
     ⚠️ ENGAGING BUT    │         💀 LOSERS
        NOT CONVERTING  │         Low hook rate
     High hook rate     │         Low ROAS
     Low ROAS           │         → KILL THESE
     → Fix downstream   │
       (LP? offer?)     │
                        │
                    LOW ROAS
```

**High hook rate + bad ROAS** = Hook is working, something else is broken:
- Landing page mismatch
- Weak offer
- Bad video body after hook
- Wrong audience

### Minimum Thresholds

All "top" queries require minimum spend to be meaningful:
- Default: `min_spend = $100`
- Configurable per query

### Slice & Dice

All queries support sorting/filtering by:
- Hook rate (high/low)
- ROAS (high/low)
- Spend (high/low)
- CTR (high/low)
- Ad count (volume)

---

## Overview

Phase 7 is the final phase of the Deep Video Analysis feature. It adds:
1. **Hook aggregation queries** - By fingerprint, type, visual type, and landing page
2. **Agent tools** - `/hook_analysis` for conversational hook insights
3. **UI dashboard** - Visual hook performance analysis

---

## Parallel Workstreams

| Workstream | Focus | Est. Tokens | Dependencies |
|------------|-------|-------------|--------------|
| **A** | HookAnalysisService (queries) | ~25K | None |
| **B** | Agent Tools | ~20K | Workstream A |
| **C** | UI Dashboard | ~30K | Workstream A |

**Execution order:**
1. Run Workstream A first (creates service layer)
2. Run Workstreams B and C in parallel (both depend on A)

---

## Workstream A: HookAnalysisService (~25K tokens)

### New File: `viraltracker/services/ad_intelligence/hook_analysis_service.py`

### Methods to Implement

```python
class HookAnalysisService:
    """Service for analyzing hook performance across video ads."""

    def __init__(self, supabase_client: Client):
        self.client = supabase_client

    # -------------------------------------------------------------------------
    # Core Aggregation Methods
    # -------------------------------------------------------------------------

    def get_top_hooks_by_fingerprint(
        self,
        brand_id: UUID,
        limit: int = 20,
        min_spend: float = 100,
        date_range_days: int = 30,
        sort_by: str = "roas",  # roas, hook_rate, spend, ctr, cpa
        sort_order: str = "desc"
    ) -> List[Dict]:
        """
        Get top performing hooks by unique fingerprint.

        Returns hooks grouped by fingerprint with:
        - hook_fingerprint, hook_type, hook_visual_type
        - hook_transcript_spoken, hook_transcript_overlay
        - hook_visual_description, hook_visual_elements
        - ad_count, total_spend, avg_roas, avg_ctr, avg_hook_rate
        - example_ad_ids (top 3 by spend)

        Supports sorting by any metric for flexible analysis.
        """

    def get_hooks_by_quadrant(
        self,
        brand_id: UUID,
        date_range_days: int = 30,
        min_spend: float = 100,
        hook_rate_threshold: float = 0.25,  # 25% = good hook rate
        roas_threshold: float = 1.0  # 1.0 = breakeven
    ) -> Dict[str, List[Dict]]:
        """
        Categorize hooks into quadrants based on hook_rate vs ROAS.

        Returns:
        {
            "winners": [...],           # High hook rate + High ROAS → Scale
            "hidden_gems": [...],       # Low hook rate + High ROAS → Investigate
            "engaging_not_converting": [...],  # High hook rate + Low ROAS → Fix downstream
            "losers": [...]             # Low hook rate + Low ROAS → Kill
        }

        Each hook includes full metrics + suggested action.
        """

    def get_high_hook_rate_low_roas(
        self,
        brand_id: UUID,
        date_range_days: int = 30,
        min_spend: float = 100,
        hook_rate_threshold: float = 0.25,
        roas_threshold: float = 1.0,
        limit: int = 10
    ) -> List[Dict]:
        """
        Get hooks with high engagement but poor conversion.

        These hooks are WORKING to grab attention but something
        downstream is broken. Returns hooks with:
        - Hook details
        - Metrics (hook_rate, roas, spend)
        - Landing page info (to check for mismatch)
        - Diagnostic suggestions
        """

    def get_high_hook_rate_high_roas(
        self,
        brand_id: UUID,
        date_range_days: int = 30,
        min_spend: float = 100,
        hook_rate_threshold: float = 0.25,
        roas_threshold: float = 2.0,
        limit: int = 10
    ) -> List[Dict]:
        """
        Get winning hooks - high engagement AND high conversion.

        These are your best performers. Scale these.
        """

    def get_hooks_by_type(
        self,
        brand_id: UUID,
        date_range_days: int = 30
    ) -> List[Dict]:
        """
        Aggregate hook performance by hook_type.

        Returns for each hook_type (question, claim, story, etc.):
        - hook_type
        - ad_count, total_spend, avg_spend_per_ad
        - avg_roas, avg_ctr, avg_cpc
        - top_performing_fingerprint (best ROAS in this type)
        """

    def get_hooks_by_visual_type(
        self,
        brand_id: UUID,
        date_range_days: int = 30
    ) -> List[Dict]:
        """
        Aggregate hook performance by hook_visual_type.

        Returns for each visual type (unboxing, transformation, etc.):
        - hook_visual_type
        - ad_count, total_spend
        - avg_roas, avg_ctr
        - common_visual_elements (most frequent)
        - example_ad_ids
        """

    def get_hooks_by_landing_page(
        self,
        brand_id: UUID,
        date_range_days: int = 30,
        limit: int = 20
    ) -> List[Dict]:
        """
        Aggregate hooks grouped by landing page.

        Returns for each landing page:
        - landing_page_id, landing_page_url, landing_page_title
        - hook_count (distinct hooks used)
        - hooks: [{fingerprint, type, visual_type, spend, roas}]
        - total_spend, avg_roas
        - best_hook_fingerprint (highest ROAS for this LP)
        - worst_hook_fingerprint (lowest ROAS for this LP)
        """

    # -------------------------------------------------------------------------
    # Detailed Analysis Methods
    # -------------------------------------------------------------------------

    def get_hook_details(
        self,
        brand_id: UUID,
        hook_fingerprint: str
    ) -> Optional[Dict]:
        """
        Get detailed info for a specific hook fingerprint.

        Returns:
        - Full hook data (spoken, overlay, visual, type, elements)
        - All ads using this hook
        - Performance metrics per ad
        - Landing pages this hook is used with
        - Performance variance (is it consistent or variable?)
        """

    def get_hook_comparison(
        self,
        brand_id: UUID,
        fingerprint_a: str,
        fingerprint_b: str
    ) -> Dict:
        """
        Compare two hooks head-to-head.

        Returns:
        - Hook A details + metrics
        - Hook B details + metrics
        - Winner by: spend, ROAS, CTR, CPC
        - Statistical confidence (sample size comparison)
        """

    def get_untested_hook_types(
        self,
        brand_id: UUID
    ) -> List[Dict]:
        """
        Find hook types/visual types not yet tested.

        Returns gap analysis:
        - hook_types with < 2 ads
        - hook_visual_types with < 2 ads
        - Suggestions for what to test next
        """

    # -------------------------------------------------------------------------
    # Insights & Recommendations
    # -------------------------------------------------------------------------

    def get_hook_insights(
        self,
        brand_id: UUID,
        date_range_days: int = 30
    ) -> Dict:
        """
        Generate actionable hook insights.

        Returns:
        - top_performer: Best hook by ROAS with details
        - worst_performer: Worst hook by ROAS (with min spend threshold)
        - rising_star: Hook with improving performance trend
        - coverage_gaps: Untested hook types
        - recommendations: List of actionable suggestions
        """

    def get_winning_hooks_for_lp(
        self,
        brand_id: UUID,
        landing_page_id: UUID
    ) -> List[Dict]:
        """
        Get best performing hooks for a specific landing page.

        Useful for: "What hooks work best with this LP?"
        """
```

### SQL Queries

**Top hooks by fingerprint:**
```sql
WITH hook_performance AS (
    SELECT
        v.hook_fingerprint,
        v.hook_type,
        v.hook_visual_type,
        v.hook_transcript_spoken,
        v.hook_transcript_overlay,
        v.hook_visual_description,
        v.hook_visual_elements,
        v.meta_ad_id,
        SUM(p.spend) as ad_spend,
        AVG(NULLIF(p.purchase_value, 0) / NULLIF(p.spend, 0)) as ad_roas,
        AVG(p.ctr) as ad_ctr
    FROM ad_video_analysis v
    JOIN meta_ads_performance p
        ON p.meta_ad_id = v.meta_ad_id
        AND p.brand_id = v.brand_id
        AND p.date >= CURRENT_DATE - INTERVAL '$date_range_days days'
    WHERE v.brand_id = $brand_id
        AND v.hook_fingerprint IS NOT NULL
    GROUP BY v.hook_fingerprint, v.hook_type, v.hook_visual_type,
             v.hook_transcript_spoken, v.hook_transcript_overlay,
             v.hook_visual_description, v.hook_visual_elements, v.meta_ad_id
)
SELECT
    hook_fingerprint,
    hook_type,
    hook_visual_type,
    hook_transcript_spoken,
    hook_transcript_overlay,
    hook_visual_description,
    hook_visual_elements,
    COUNT(DISTINCT meta_ad_id) as ad_count,
    SUM(ad_spend) as total_spend,
    AVG(ad_roas) as avg_roas,
    AVG(ad_ctr) as avg_ctr,
    ARRAY_AGG(DISTINCT meta_ad_id ORDER BY ad_spend DESC) FILTER (WHERE ad_spend > 0) as example_ad_ids
FROM hook_performance
GROUP BY hook_fingerprint, hook_type, hook_visual_type,
         hook_transcript_spoken, hook_transcript_overlay,
         hook_visual_description, hook_visual_elements
HAVING SUM(ad_spend) >= $min_spend
ORDER BY total_spend DESC
LIMIT $limit;
```

**Hooks by landing page:**
```sql
WITH hook_lp_performance AS (
    SELECT
        c.landing_page_id,
        lp.url as landing_page_url,
        lp.title as landing_page_title,
        v.hook_fingerprint,
        v.hook_type,
        v.hook_visual_type,
        SUM(p.spend) as hook_spend,
        AVG(NULLIF(p.purchase_value, 0) / NULLIF(p.spend, 0)) as hook_roas
    FROM ad_creative_classifications c
    JOIN ad_video_analysis v ON v.id = c.video_analysis_id
    JOIN brand_landing_pages lp ON lp.id = c.landing_page_id
    JOIN meta_ads_performance p
        ON p.meta_ad_id = c.meta_ad_id
        AND p.brand_id = c.brand_id
        AND p.date >= CURRENT_DATE - INTERVAL '$date_range_days days'
    WHERE c.brand_id = $brand_id
        AND c.landing_page_id IS NOT NULL
        AND v.hook_fingerprint IS NOT NULL
    GROUP BY c.landing_page_id, lp.url, lp.title,
             v.hook_fingerprint, v.hook_type, v.hook_visual_type
)
SELECT
    landing_page_id,
    landing_page_url,
    landing_page_title,
    COUNT(DISTINCT hook_fingerprint) as hook_count,
    SUM(hook_spend) as total_spend,
    AVG(hook_roas) as avg_roas,
    JSON_AGG(JSON_BUILD_OBJECT(
        'fingerprint', hook_fingerprint,
        'type', hook_type,
        'visual_type', hook_visual_type,
        'spend', hook_spend,
        'roas', hook_roas
    ) ORDER BY hook_roas DESC) as hooks,
    (SELECT hook_fingerprint FROM hook_lp_performance h2
     WHERE h2.landing_page_id = hook_lp_performance.landing_page_id
     ORDER BY hook_roas DESC LIMIT 1) as best_hook_fingerprint
FROM hook_lp_performance
GROUP BY landing_page_id, landing_page_url, landing_page_title
ORDER BY total_spend DESC
LIMIT $limit;
```

### Verification
- `python3 -m py_compile viraltracker/services/ad_intelligence/hook_analysis_service.py`
- Create test script: `scripts/test_hook_analysis.py`
- Test with Wonder Paws data

### Checkpoint
After Workstream A: `CHECKPOINT_06_PHASE7_SERVICE.md`

---

## Workstream B: Agent Tools (~20K tokens)

### Modify: `viraltracker/agent/agents/ad_intelligence_agent.py`

### New Tools to Add

#### Tool 1: `/hook_analysis`
```python
@ad_intelligence_agent.tool(
    metadata={
        'category': 'Analysis',
        'use_cases': [
            'Find best performing hooks',
            'Analyze hook patterns',
            'Find hooks with high engagement but low conversion',
            'Compare hook types'
        ],
        'examples': [
            'What hooks work best for Wonder Paws?',
            'Show me hooks with high hook rate but bad ROAS',
            'Which hooks are winners vs losers?',
            'Show me top hooks by hook rate',
            'Which visual hook types should I test?'
        ]
    }
)
async def hook_analysis(
    ctx: RunContext[AgentDependencies],
    brand_name: str,
    analysis_type: str = "overview",  # overview, quadrant, by_type, by_visual, by_lp, compare, gaps
    sort_by: str = "roas",  # roas, hook_rate, spend, ctr
    hook_fingerprint: Optional[str] = None,  # for detailed view
    compare_fingerprint: Optional[str] = None,  # for comparison
    limit: int = 10
) -> Dict:
    """
    Analyze hook performance for a brand's video ads.

    Analysis types:
    - overview: Top performing hooks + key insights
    - quadrant: Categorize hooks by hook_rate vs ROAS (winners, losers, engaging but not converting, hidden gems)
    - by_type: Performance breakdown by hook type (question, claim, etc.)
    - by_visual: Performance breakdown by visual type (unboxing, demo, etc.)
    - by_lp: Hooks grouped by landing page
    - compare: Compare two specific hooks (requires hook_fingerprint + compare_fingerprint)
    - gaps: Find untested hook types

    Sort options (applies to most analysis types):
    - roas: Return on ad spend (default)
    - hook_rate: Video hook rate (% past 3 sec)
    - spend: Total spend
    - ctr: Click-through rate

    Key insight: "quadrant" analysis reveals hooks with HIGH hook rate but LOW ROAS -
    these are engaging but not converting, suggesting downstream issues (LP, offer, etc.)
    """
```

#### Tool 2: `/top_hooks`
```python
@ad_intelligence_agent.tool(
    metadata={
        'category': 'Analysis',
        'use_cases': [
            'Quick view of winning hooks',
            'Find hooks to scale'
        ],
        'examples': [
            'Show me the top 5 hooks for Wonder Paws',
            'What are the best performing hooks?'
        ]
    }
)
async def top_hooks(
    ctx: RunContext[AgentDependencies],
    brand_name: str,
    metric: str = "roas",  # roas, spend, ctr
    limit: int = 5
) -> Dict:
    """
    Quick view of top performing hooks ranked by a metric.

    Simpler than /hook_analysis - just returns the top N hooks
    with their key metrics and example ad IDs.
    """
```

#### Tool 3: `/hooks_for_lp`
```python
@ad_intelligence_agent.tool(
    metadata={
        'category': 'Analysis',
        'use_cases': [
            'Find best hooks for a landing page',
            'Optimize hook/LP pairing'
        ],
        'examples': [
            'What hooks work best with the collagen landing page?',
            'Show me hooks used with wonderpaws.com/products/chews'
        ]
    }
)
async def hooks_for_lp(
    ctx: RunContext[AgentDependencies],
    brand_name: str,
    landing_page_url: Optional[str] = None,
    landing_page_id: Optional[str] = None
) -> Dict:
    """
    Get hook performance for a specific landing page.

    Shows which hooks drive best results when paired with this LP.
    Useful for optimizing creative/LP combinations.
    """
```

### Response Formatting

Format responses for readability in chat:
```python
def format_hook_analysis_response(data: Dict) -> str:
    """Format hook analysis for chat display."""
    lines = []

    if data.get("top_hooks"):
        lines.append("## Top Performing Hooks\n")
        for i, hook in enumerate(data["top_hooks"][:5], 1):
            lines.append(f"**{i}. {hook['hook_type']} hook** ({hook['hook_visual_type']})")
            lines.append(f"   Spoken: \"{hook['hook_transcript_spoken'][:50]}...\"")
            if hook.get('hook_transcript_overlay'):
                lines.append(f"   Overlay: \"{hook['hook_transcript_overlay'][:50]}...\"")
            lines.append(f"   📊 {hook['ad_count']} ads | ${hook['total_spend']:,.0f} spend | {hook['avg_roas']:.2f}x ROAS")
            lines.append("")

    if data.get("insights"):
        lines.append("## Insights\n")
        for insight in data["insights"]:
            lines.append(f"- {insight}")

    return "\n".join(lines)
```

### Verification
- `python3 -m py_compile viraltracker/agent/agents/ad_intelligence_agent.py`
- Test in Agent Chat:
  - "What hooks work best for Wonder Paws?"
  - "Show me top 5 hooks by ROAS"
  - "What hook types should I test?"

### Checkpoint
After Workstream B: Update `CHECKPOINT_07_PHASE7_COMPLETE.md`

---

## Workstream C: UI Dashboard (~30K tokens)

### New File: `viraltracker/ui/pages/35_🎣_Hook_Analysis.py`

### Page Structure

```
1. Page Config + Auth
2. Brand Selector (render_brand_selector)
3. Date Range Selector (last 7/14/30/90 days)
4. Global filters: Min spend, Sort by (ROAS/Hook Rate/Spend/CTR)
5. Tabs:
   - Overview: Top hooks + key metrics + insights
   - Quadrant: Hook Rate vs ROAS analysis (winners, losers, etc.)
   - By Type: Hook type breakdown with charts
   - By Visual: Visual type breakdown with charts
   - By Landing Page: Hooks grouped by LP
   - Compare: Side-by-side hook comparison
```

### Tab Details

#### Tab 1: Overview
- **Top metrics row:** Total hooks analyzed, Total spend on video ads, Best ROAS hook, Best hook rate hook
- **Top 10 hooks table:** Sortable by spend, ROAS, CTR, hook rate, ad count
- **Insights cards:** Auto-generated recommendations
- **Quick actions:** "View details" links to other tabs

#### Tab 2: Quadrant Analysis (Hook Rate vs ROAS)
- **Scatter plot:** X = Hook Rate, Y = ROAS, size = spend
- **Quadrant sections:** Color-coded (green=winners, red=losers, yellow=investigate)
- **Four tables:**
  - 🎯 **Winners** (High hook rate + High ROAS) - "Scale these"
  - 🔍 **Hidden Gems** (Low hook rate + High ROAS) - "Why low engagement?"
  - ⚠️ **Engaging but Not Converting** (High hook rate + Low ROAS) - "Fix downstream"
  - 💀 **Losers** (Low hook rate + Low ROAS) - "Kill these"
- **Threshold sliders:** Adjust hook_rate and ROAS thresholds
- **Diagnostic suggestions:** For "engaging but not converting" hooks, show LP info and potential issues

#### Tab 3: By Type
- **Bar chart:** Performance by hook_type (question, claim, story, etc.)
- **Metrics:** Ad count, spend, avg ROAS, avg hook rate per type
- **Drill-down:** Click type to see hooks within that type
- **Recommendation:** Highlight underused high-performing types

#### Tab 4: By Visual
- **Bar chart:** Performance by hook_visual_type (unboxing, demo, etc.)
- **Visual elements breakdown:** Most common elements in top hooks
- **Gap analysis:** Visual types not yet tested
- **Metrics:** Include hook rate alongside ROAS

#### Tab 5: By Landing Page
- **LP selector:** Dropdown to filter by specific LP
- **Table:** LPs with hook count, total spend, avg ROAS, avg hook rate
- **Expandable rows:** Show hooks used with each LP
- **Best/worst hook per LP highlighted**
- **Insight:** Flag LPs where hooks have high hook rate but low ROAS (suggests LP issue)

#### Tab 6: Compare
- **Two hook selectors:** Dropdown to pick hooks by fingerprint
- **Side-by-side comparison:** Metrics (ROAS, hook rate, CTR, spend), transcript, visual
- **Winner badges:** By ROAS, hook rate, CTR, spend
- **Confidence indicator:** Based on sample size

### Components

| Component | Implementation |
|-----------|----------------|
| Top metrics | `st.metric()` x 4 in columns |
| Hook table | `st.dataframe()` with sorting |
| Bar charts | Native `st.bar_chart()` |
| Insights | `st.info()` / `st.success()` cards |
| Hook detail modal | `st.expander()` with full hook data |
| LP selector | `st.selectbox()` with search |

### Navigation Registration
- Add `HOOK_ANALYSIS` to `FeatureKey` enum in `feature_service.py`
- Register page in `nav.py` under Ads section

### Verification
- `python3 -m py_compile viraltracker/ui/pages/35_🎣_Hook_Analysis.py`
- Start Streamlit, navigate to page
- Test all 5 tabs with Wonder Paws data
- Verify charts render correctly

### Checkpoint
After Workstream C: Update `CHECKPOINT_07_PHASE7_COMPLETE.md`

---

## Testing Plan

### Unit Tests (per workstream)

#### Workstream A Tests
```python
# scripts/test_hook_analysis.py

async def test_top_hooks_by_fingerprint():
    """Test hook aggregation by fingerprint."""
    service = HookAnalysisService(get_supabase_client())
    result = await service.get_top_hooks_by_fingerprint(
        brand_id=WONDER_PAWS_BRAND_ID,
        limit=10
    )
    assert len(result) > 0
    assert "hook_fingerprint" in result[0]
    assert "total_spend" in result[0]
    assert "avg_roas" in result[0]

async def test_hooks_by_type():
    """Test hook aggregation by type."""
    service = HookAnalysisService(get_supabase_client())
    result = await service.get_hooks_by_type(brand_id=WONDER_PAWS_BRAND_ID)
    assert len(result) > 0
    # Should have common types like question, claim, etc.
    types = [r["hook_type"] for r in result]
    assert any(t in types for t in ["question", "claim", "story", "callout"])

async def test_hooks_by_landing_page():
    """Test hook aggregation by LP."""
    service = HookAnalysisService(get_supabase_client())
    result = await service.get_hooks_by_landing_page(brand_id=WONDER_PAWS_BRAND_ID)
    assert len(result) > 0
    assert "landing_page_url" in result[0]
    assert "hooks" in result[0]

async def test_hook_insights():
    """Test insights generation."""
    service = HookAnalysisService(get_supabase_client())
    result = await service.get_hook_insights(brand_id=WONDER_PAWS_BRAND_ID)
    assert "top_performer" in result
    assert "recommendations" in result
```

#### Workstream B Tests (Agent Chat)
```
Test queries in Agent Chat:

1. "What hooks work best for Wonder Paws?"
   Expected: Overview with top hooks, metrics, insights

2. "Show me top 5 hooks by ROAS"
   Expected: Ranked list with ROAS metrics

3. "What hook types should I test for Wonder Paws?"
   Expected: Gap analysis showing untested types

4. "Compare the top two hooks for Wonder Paws"
   Expected: Side-by-side comparison

5. "What hooks work best with the collagen landing page?"
   Expected: Hooks filtered by LP with performance data
```

#### Workstream C Tests (UI)
```
Manual UI testing:

1. Overview Tab:
   - [ ] Top metrics display correctly
   - [ ] Hook table loads and is sortable
   - [ ] Insights cards show relevant recommendations

2. By Type Tab:
   - [ ] Bar chart renders with all hook types
   - [ ] Clicking a type shows drill-down
   - [ ] Metrics match expected values

3. By Visual Tab:
   - [ ] Visual types chart renders
   - [ ] Visual elements breakdown shows
   - [ ] Gap analysis identifies untested types

4. By Landing Page Tab:
   - [ ] LP dropdown populates
   - [ ] Table shows LPs with hook data
   - [ ] Expandable rows work
   - [ ] Best/worst hooks highlighted

5. Compare Tab:
   - [ ] Two hook selectors work
   - [ ] Side-by-side comparison displays
   - [ ] Winner badges appear
```

### Integration Tests

```python
# scripts/test_phase7_integration.py

async def test_end_to_end_hook_flow():
    """Test full flow from video analysis to hook insights."""

    # 1. Verify video analysis has hooks
    video_analysis = get_latest_video_analysis(WONDER_PAWS_BRAND_ID)
    assert video_analysis["hook_fingerprint"] is not None
    assert video_analysis["hook_type"] is not None

    # 2. Verify hooks join with performance data
    service = HookAnalysisService(get_supabase_client())
    hooks = await service.get_top_hooks_by_fingerprint(WONDER_PAWS_BRAND_ID)
    assert hooks[0]["total_spend"] > 0

    # 3. Verify LP linkage works
    lp_hooks = await service.get_hooks_by_landing_page(WONDER_PAWS_BRAND_ID)
    assert any(lp["hooks"] for lp in lp_hooks)

    # 4. Verify insights generate
    insights = await service.get_hook_insights(WONDER_PAWS_BRAND_ID)
    assert len(insights["recommendations"]) > 0
```

### Performance Tests

```python
async def test_query_performance():
    """Ensure queries complete in reasonable time."""
    import time

    service = HookAnalysisService(get_supabase_client())

    start = time.time()
    await service.get_top_hooks_by_fingerprint(WONDER_PAWS_BRAND_ID, limit=50)
    elapsed = time.time() - start
    assert elapsed < 5.0, f"Query took {elapsed}s, should be < 5s"

    start = time.time()
    await service.get_hooks_by_landing_page(WONDER_PAWS_BRAND_ID)
    elapsed = time.time() - start
    assert elapsed < 5.0, f"Query took {elapsed}s, should be < 5s"
```

---

## Execution Plan

### Step 1: Run Workstream A (~25K tokens)
```
Create HookAnalysisService with all query methods.
Test with scripts/test_hook_analysis.py.
Checkpoint: CHECKPOINT_06_PHASE7_SERVICE.md
```

### Step 2: Run Workstreams B & C in Parallel (~20K + ~30K tokens)
```
Workstream B: Add agent tools to ad_intelligence_agent.py
Workstream C: Create Hook Analysis UI page

Both depend on Workstream A service being complete.
Can run simultaneously.
```

### Step 3: Integration Testing
```
Run full test suite.
Test in Agent Chat with real queries.
Test UI with Wonder Paws data.
```

### Step 4: Final Checkpoint
```
Create CHECKPOINT_07_PHASE7_COMPLETE.md
Update main plan status to COMPLETE
```

---

## Files Summary

| Action | File | Workstream |
|--------|------|------------|
| CREATE | `viraltracker/services/ad_intelligence/hook_analysis_service.py` | A |
| CREATE | `scripts/test_hook_analysis.py` | A |
| MODIFY | `viraltracker/agent/agents/ad_intelligence_agent.py` | B |
| CREATE | `viraltracker/ui/pages/35_🎣_Hook_Analysis.py` | C |
| MODIFY | `viraltracker/services/feature_service.py` | C |
| MODIFY | `viraltracker/ui/nav.py` | C |
| CREATE | `scripts/test_phase7_integration.py` | Testing |

---

## Success Criteria

1. **Service layer:** All HookAnalysisService methods work with Wonder Paws data
2. **Agent tools:** Can ask "what hooks work best?" and get meaningful response
3. **UI:** All 5 tabs render with real data
4. **Performance:** Queries complete in < 5 seconds
5. **Insights:** Recommendations are actionable and accurate

---

## Before Starting: Test Analyze Feature

**IMPORTANT:** Before implementing Phase 7, verify the analyze feature works with `gemini-3-flash-preview`:

1. Run `Analyze Wonder Paws ad account` in Agent Chat
2. Check Logfire for:
   - Video analysis using `gemini-3-flash-preview`
   - No "copy only" fallbacks for video ads
   - Proper skip messages for video ads without `meta_video_id`
3. Verify Congruence Insights page shows updated data
4. Confirm video analysis data exists for hook queries to use

---

## Checkpoints

| Checkpoint | After | Contents |
|------------|-------|----------|
| `CHECKPOINT_06_PHASE7_SERVICE.md` | Workstream A | Service created, queries working |
| `CHECKPOINT_07_PHASE7_COMPLETE.md` | All workstreams | Full Phase 7 complete, all tests passing |
