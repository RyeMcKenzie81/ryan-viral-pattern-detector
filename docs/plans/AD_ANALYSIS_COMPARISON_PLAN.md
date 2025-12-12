# Ad Analysis & Product-Level Comparison Plan

## Overview

Enhance ad analysis to extract structured, comparable fields from both brand and competitor ads, enabling product-to-product comparison and competitive intelligence.

---

## New Analysis Fields

### 1. Advertising Angle (Structural)
The tactical approach/format of the ad.

**Values:**
- `testimonial` - Customer/expert sharing experience
- `demonstration` - Showing product in action
- `problem_agitation` - Highlighting pain, then solution
- `transformation` - Before/after story
- `social_proof` - Numbers, reviews, popularity
- `authority` - Expert endorsement, credentials
- `scarcity_urgency` - Limited time/quantity
- `comparison` - Us vs them/alternatives
- `educational` - Teaching something valuable
- `lifestyle` - Aspirational imagery
- `ugc_style` - User-generated content feel
- `founder_story` - Brand origin narrative

### 2. Messaging Angles (Benefit Dimensionalization)
How benefits are framed/positioned. Same benefit can have multiple angles.

**Structure:**
```json
{
  "messaging_angles": [
    {
      "benefit": "Joint health improvement",
      "angle": "Freedom & mobility",
      "framing": "Get back to doing what you love together",
      "emotional_driver": "freedom"
    },
    {
      "benefit": "Joint health improvement",
      "angle": "Guilt relief",
      "framing": "Stop watching them struggle - do something about it",
      "emotional_driver": "guilt"
    },
    {
      "benefit": "Joint health improvement",
      "angle": "Scientific credibility",
      "framing": "Clinically proven ingredients vets recommend",
      "emotional_driver": "trust"
    }
  ]
}
```

**Common Emotional Drivers:**
- Freedom, Relief, Pride, Fear, Guilt, Love, Status, Security, Belonging, Achievement

### 3. Awareness Level
Where on Eugene Schwartz's awareness spectrum the ad targets.

**Values:**
- `unaware` - Doesn't know they have a problem
- `problem_aware` - Knows problem, not solutions
- `solution_aware` - Knows solutions exist, not your product
- `product_aware` - Knows your product, not convinced
- `most_aware` - Ready to buy, needs push

### 4. Benefits Highlighted
Outcomes/results promised.

```json
{
  "benefits": [
    {
      "benefit": "Improved mobility",
      "specificity": "high",  // high/medium/low
      "proof_provided": "clinical study mentioned",
      "timeframe": "2-3 weeks"
    }
  ]
}
```

### 5. Features Mentioned
Product attributes/ingredients/specs.

```json
{
  "features": [
    {
      "feature": "Glucosamine 500mg",
      "positioning": "premium ingredient",
      "differentiation": true  // Is this used to differentiate?
    }
  ]
}
```

### 6. Objections Addressed
Concerns preemptively handled.

```json
{
  "objections_addressed": [
    {
      "objection": "My dog won't eat supplements",
      "response": "Bacon flavor dogs love",
      "method": "feature_highlight"  // feature_highlight, social_proof, guarantee, testimonial
    }
  ]
}
```

---

## Data Model

### Option A: Store in existing raw_response (Recommended)
- No schema changes needed
- Analysis already stores full JSON in `raw_response`
- Query with JSONB operators

### Option B: Add structured columns
- More queryable but requires migration
- Could add `advertising_angle`, `awareness_level` as indexed columns
- Keep detailed fields in `raw_response`

**Recommendation:** Start with Option A, add indexed columns later if query performance needs it.

---

## Prompt Updates

### Files to Modify:
1. `viraltracker/services/brand_research_service.py`
   - `COPY_ANALYSIS_PROMPT`
   - `VIDEO_ANALYSIS_PROMPT`
   - `IMAGE_ANALYSIS_PROMPT`

### New Prompt Section (to add to each):

```
ADVERTISING STRUCTURE:
{
  "advertising_angle": "testimonial|demonstration|problem_agitation|transformation|social_proof|authority|scarcity_urgency|comparison|educational|lifestyle|ugc_style|founder_story",

  "awareness_level": "unaware|problem_aware|solution_aware|product_aware|most_aware",

  "messaging_angles": [
    {
      "benefit": "The core benefit being communicated",
      "angle": "How the benefit is framed/dimensionalized",
      "framing": "The actual words/approach used",
      "emotional_driver": "freedom|relief|pride|fear|guilt|love|status|security|belonging|achievement"
    }
  ],

  "benefits_highlighted": [
    {
      "benefit": "Specific outcome promised",
      "specificity": "high|medium|low",
      "proof_provided": "What proof/evidence if any",
      "timeframe": "When results expected (if mentioned)"
    }
  ],

  "features_mentioned": [
    {
      "feature": "Product attribute/ingredient/spec",
      "positioning": "How it's positioned",
      "differentiation": true/false
    }
  ],

  "objections_addressed": [
    {
      "objection": "The concern being addressed",
      "response": "How the ad addresses it",
      "method": "feature_highlight|social_proof|guarantee|testimonial|demonstration"
    }
  ]
}
```

---

## UI: Product-Level Competitive Analysis

### Location
`viraltracker/ui/pages/24_📊_Competitive_Analysis.py`

### Current State
- Brand-level comparison only
- Shows competitor overview, ad counts
- No product-to-product comparison

### New Features

#### 1. Product Selector
```
┌─────────────────────────────────────────────────────┐
│ Compare Products                                     │
├─────────────────────────────────────────────────────┤
│ Your Product: [Dropdown: Product A ▼]               │
│ vs                                                   │
│ Competitor:   [Dropdown: WonderPaws ▼]              │
│ Their Product: [Dropdown: Joint Supplement ▼]       │
│                                                      │
│ [Compare Products]                                   │
└─────────────────────────────────────────────────────┘
```

#### 2. Awareness Level Distribution
```
┌─────────────────────────────────────────────────────┐
│ Awareness Level Focus                                │
├─────────────────────────────────────────────────────┤
│           Your Product    │  Their Product          │
│ ─────────────────────────┼───────────────────────── │
│ Most Aware:     ████ 40% │  ██ 20%                  │
│ Product Aware:  ██ 20%   │  ████ 40%                │
│ Solution Aware: ██ 25%   │  ██ 25%                  │
│ Problem Aware:  █ 10%    │  █ 10%                   │
│ Unaware:        █ 5%     │  █ 5%                    │
└─────────────────────────────────────────────────────┘
```

#### 3. Advertising Angles Comparison
```
┌─────────────────────────────────────────────────────┐
│ Advertising Angles Used                              │
├─────────────────────────────────────────────────────┤
│ Angle              │ You  │ Them │ Gap              │
│ ───────────────────┼──────┼──────┼───────────────── │
│ Testimonial        │  15  │  25  │ They use more    │
│ Problem Agitation  │  20  │   5  │ Your strength    │
│ Transformation     │  10  │  15  │ -                │
│ UGC Style          │   5  │  30  │ Big gap!         │
│ Social Proof       │  12  │   8  │ -                │
└─────────────────────────────────────────────────────┘
```

#### 4. Messaging Angles Deep Dive
```
┌─────────────────────────────────────────────────────┐
│ How "Joint Health" is Messaged                       │
├─────────────────────────────────────────────────────┤
│ YOUR ANGLES:                                         │
│ • Freedom/Mobility (45%) - "Get back to adventures"  │
│ • Scientific (30%) - "Vet-formulated"               │
│ • Love/Care (25%) - "Because they deserve it"       │
│                                                      │
│ THEIR ANGLES:                                        │
│ • Guilt Relief (50%) - "Stop watching them suffer"  │
│ • Urgency (25%) - "Before it's too late"            │
│ • Social Proof (25%) - "500,000 happy dogs"         │
│                                                      │
│ 💡 INSIGHT: They're using guilt-based messaging     │
│    heavily. You're not using this angle at all.     │
└─────────────────────────────────────────────────────┘
```

#### 5. Objection Handling Comparison
```
┌─────────────────────────────────────────────────────┐
│ Objections Addressed                                 │
├─────────────────────────────────────────────────────┤
│ Objection                │ You │ Them │             │
│ ─────────────────────────┼─────┼──────┤             │
│ "It's too expensive"     │  ✓  │  ✓   │             │
│ "My dog won't eat it"    │  ✓  │  ✓   │             │
│ "Does it really work?"   │  ✓  │  ✓   │             │
│ "How long until results?"│  ✗  │  ✓   │ ⚠️ Gap     │
│ "Is it safe long-term?"  │  ✗  │  ✓   │ ⚠️ Gap     │
└─────────────────────────────────────────────────────┘
```

#### 6. Benefits & Features Matrix
```
┌─────────────────────────────────────────────────────┐
│ Benefits Comparison                                  │
├─────────────────────────────────────────────────────┤
│ Benefit           │ You          │ Them             │
│ ──────────────────┼──────────────┼───────────────── │
│ Pain relief       │ High focus   │ Medium           │
│ Mobility          │ High focus   │ High focus       │
│ Energy/vitality   │ Low          │ High focus       │ ← Gap
│ Longevity         │ Not used     │ Medium           │ ← Gap
│ Coat health       │ Medium       │ Not used         │ ← Unique
└─────────────────────────────────────────────────────┘
```

---

## Implementation Phases

### Phase 1: Prompt Updates
**Files:** `brand_research_service.py`
**Effort:** ~2 hours

1. Update `COPY_ANALYSIS_PROMPT` with new fields
2. Update `VIDEO_ANALYSIS_PROMPT` with new fields
3. Update `IMAGE_ANALYSIS_PROMPT` with new fields
4. Test with a few sample analyses

**Note:** This affects NEW analyses only. Existing analyses won't have these fields.

### Phase 2: Product-Level Data Access
**Files:** `competitor_service.py`, `brand_research_service.py`
**Effort:** ~2 hours

1. Add methods to get analyses filtered by product:
   - `get_brand_analyses_by_product(brand_id, product_id)`
   - `get_competitor_analyses_by_product(competitor_id, product_id)`
2. Aggregate analysis data for comparison

### Phase 3: Comparison UI
**Files:** `24_📊_Competitive_Analysis.py`
**Effort:** ~4 hours

1. Add product selector UI
2. Build comparison data aggregation
3. Create visualization components:
   - Awareness level chart
   - Advertising angles table
   - Messaging angles breakdown
   - Objection handling matrix
   - Benefits comparison

### Phase 4: Insights Generation (Optional Enhancement)
**Effort:** ~2 hours

1. Auto-generate insights from comparison data
2. "You're missing X angle that competitor uses heavily"
3. "Gap in objection handling: they address Y, you don't"

---

## Questions Before Implementation

1. **Re-analyze existing ads?**
   - New prompts only affect future analyses
   - Should we provide a "re-analyze" button to update existing?
   - Cost consideration: ~$0.01-0.05 per ad for copy analysis

2. **Product mapping required?**
   - For product-level comparison to work, ads need to be mapped to products
   - Brand side: `brand_facebook_ads` → `products` (need to verify this exists)
   - Competitor side: `competitor_ads.competitor_product_id` (already exists)

3. **Visualization library?**
   - Streamlit native charts (simple, consistent)
   - Plotly (more interactive)
   - Altair (good for comparisons)

4. **Historical tracking?**
   - Just current snapshot comparison?
   - Or track changes over time? (e.g., "Competitor started using more UGC in Q4")

---

## Success Metrics

After implementation, users should be able to:

- [ ] See which awareness levels competitors focus on vs themselves
- [ ] Identify advertising angles competitors use that they don't
- [ ] Discover messaging angles (benefit framings) they're missing
- [ ] Find objections competitors address that they don't
- [ ] Compare product-to-product across brands
- [ ] Get actionable insights for ad strategy

---

## Files to Create/Modify

| File | Action | Description |
|------|--------|-------------|
| `brand_research_service.py` | Modify | Update 3 analysis prompts |
| `competitor_service.py` | Modify | Add product-filtered analysis methods |
| `24_📊_Competitive_Analysis.py` | Modify | Add product comparison UI |
| `comparison_utils.py` (new) | Create | Helper functions for aggregating/comparing |

---

## Estimated Total Effort

| Phase | Effort |
|-------|--------|
| Phase 1: Prompts | 2 hours |
| Phase 2: Data Access | 2 hours |
| Phase 3: UI | 4 hours |
| Phase 4: Insights | 2 hours (optional) |
| **Total** | **8-10 hours** |
