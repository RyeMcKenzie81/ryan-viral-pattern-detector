# Checkpoint: Belief-First Landing Page Analysis

**Date:** 2025-12-18
**Feature:** 13-Layer Belief-First Evaluation Canvas for Landing Pages

## Overview

Added a comprehensive 13-layer "Belief-First Evaluation Canvas" for analyzing landing pages on both brand and competitor sides. Uses Claude Opus 4.5 for deep strategic analysis, evaluating each layer as clear/weak/missing/conflicting with verbatim examples and specific copy recommendations.

## The 13 Layers

The analysis evaluates landing pages through these 13 strategic layers:

### Market & Brand Foundation
1. **Market Context & Awareness** - Sophistication level, awareness stage
2. **Brand** - Trust signals, positioning, values
3. **Product/Offer** - What's being sold, pricing structure

### Audience Understanding
4. **Persona** - Who the page is written for
5. **Jobs to Be Done** - Functional, emotional, social jobs addressed
6. **Persona Sub-layers** - Current state, desired state, anxieties, aspirations

### Messaging Strategy
7. **Angle** - Core explanation/unique perspective
8. **Unique Mechanism** - Proprietary method/system/formula
9. **Problem → Pain → Symptoms** - Problem articulation cascade

### Value Communication
10. **Benefits** - Outcome-focused value propositions
11. **Features** - Specific capabilities and specs
12. **Proof & Risk Reversal** - Social proof, testimonials, guarantees
13. **Expression** - Tone, language patterns, structure

## Database Schema

### Migration: `migrations/2025-12-18_belief_first_analysis.sql`

```sql
-- New columns on brand_landing_pages
belief_first_analysis JSONB
belief_first_analyzed_at TIMESTAMPTZ

-- New columns on competitor_landing_pages
belief_first_analysis JSONB
belief_first_analyzed_at TIMESTAMPTZ

-- New table for aggregated summaries
landing_page_belief_analysis_summary (
  id UUID PRIMARY KEY,
  brand_id UUID,
  competitor_id UUID,
  product_id UUID,
  competitor_product_id UUID,
  scope TEXT CHECK (scope IN ('brand', 'competitor')),
  layer_summary JSONB,
  problem_pages JSONB,
  total_pages_analyzed INT,
  average_score DECIMAL(3,1),
  most_common_issues JSONB,
  strongest_layers JSONB,
  model_used TEXT,
  generated_at TIMESTAMPTZ
)
```

## Service Methods

### Brand Side (`brand_research_service.py`)

```python
# Analyze a single page
async def analyze_landing_page_belief_first(
    page_id: UUID,
    force_reanalyze: bool = False
) -> Optional[Dict]

# Batch analyze pages for a brand
async def analyze_landing_pages_belief_first_for_brand(
    brand_id: UUID,
    limit: int = 20,
    delay_between: float = 3.0,
    product_id: Optional[UUID] = None,
    force_reanalyze: bool = False
) -> List[Dict]

# Generate aggregated summary
def aggregate_belief_first_analysis_for_brand(
    brand_id: UUID,
    product_id: Optional[UUID] = None
) -> Dict

# Get analysis stats (total, analyzed, pending)
def get_belief_first_analysis_stats(
    brand_id: UUID,
    product_id: Optional[UUID] = None
) -> Dict[str, int]
```

### Competitor Side (`competitor_service.py`)

Same 4 methods adapted for competitors:
- `analyze_landing_page_belief_first(landing_page_id, force_reanalyze)`
- `analyze_landing_pages_belief_first_for_competitor(competitor_id, limit, delay_between, competitor_product_id, force_reanalyze)`
- `aggregate_belief_first_analysis_for_competitor(competitor_id, competitor_product_id)`
- `get_belief_first_analysis_stats_for_competitor(competitor_id, competitor_product_id)`

## UI Components

### Shared Utilities (`viraltracker/ui/utils.py`)

```python
def render_belief_first_analysis(
    analysis: dict,
    show_recommendations: bool = True,
    nested: bool = False  # Use flat layout when inside an expander
)

def render_belief_first_aggregation(
    aggregation: dict,
    entity_name: str = "Brand"
)
```

### Brand Research Page (`05_Brand_Research.py`)

- Location: Section 3 (Landing Pages) → Belief-First Analysis sub-section
- Features:
  - Stats display (scraped, analyzed, pending)
  - Cost estimate (~$0.15/page for Opus 4.5)
  - "Run Belief-First Analysis" button (batch)
  - "Generate Summary" button
  - Two tabs: Individual Pages / Summary View

### Competitor Research Page (`12_Competitor_Research.py`)

- Location: Landing Pages tab → Belief-First Analysis sub-section
- Same features as brand side

## Analysis Output Format

Each page analysis returns:

```json
{
  "layers": {
    "market_context": {
      "status": "clear|weak|missing|conflicting",
      "explanation": "Analysis text...",
      "examples": [{"quote": "...", "location": "hero section"}],
      "context": "Impact on conversion...",
      "awareness_level": "problem_aware|solution_aware|...",
      "recommendations": ["Specific copy suggestion..."]
    },
    // ... 12 more layers
  },
  "summary": {
    "overall_score": 7.5,
    "clear": 8,
    "weak": 3,
    "missing": 1,
    "conflicting": 1,
    "key_insight": "Main finding..."
  }
}
```

## Key Implementation Details

1. **Model**: Claude Opus 4.5 (`claude-opus-4-5-20251101`) - most advanced for deep strategic analysis
2. **Cost**: ~$0.15 per page analysis
3. **Rate Limiting**: 3-second delay between API calls
4. **Nested Expander Fix**: Use `nested=True` parameter when rendering inside an expander to avoid Streamlit's nested expander limitation

## Files Modified/Created

| File | Changes |
|------|---------|
| `migrations/2025-12-18_belief_first_analysis.sql` | New migration |
| `viraltracker/services/brand_research_service.py` | Added BELIEF_FIRST_ANALYSIS_PROMPT, 4 service methods |
| `viraltracker/services/competitor_service.py` | Added json import, 4 service methods |
| `viraltracker/ui/utils.py` | Added render_belief_first_analysis(), render_belief_first_aggregation() |
| `viraltracker/ui/pages/05_Brand_Research.py` | Added _render_belief_first_section() |
| `viraltracker/ui/pages/12_Competitor_Research.py` | Added _render_competitor_belief_first_section() |

## Bugs Fixed During Implementation

1. **NameError**: `competitor_name` → `selected_competitor_name` in Competitor Research page
2. **Model ID**: `claude-opus-4-5-20250514` → `claude-opus-4-5-20251101`
3. **Missing Import**: Added `import json` to competitor_service.py
4. **Nested Expander**: Added `nested` parameter to render function

## Usage

1. Navigate to Brand Research or Competitor Research page
2. Go to Landing Pages section
3. Find the "Belief-First Analysis" sub-section
4. Click "Run Belief-First Analysis" to analyze pending pages
5. View individual page results in the "Individual Pages" tab
6. Click "Generate Summary" to see aggregated insights

## Future Enhancements

- Add filtering by layer status (show only weak/missing layers)
- Export analysis to CSV/PDF
- Compare brand vs competitor belief-first scores
- Track improvements over time
