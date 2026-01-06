# Phases 3-6 Checkpoint: All Input Sources Connected

**Date:** 2026-01-05
**Status:** Complete
**Phases Covered:** 3 (Reddit Research), 4 (Ad Performance), 5 (Competitor Research), 6 (Brand Research)

## Overview

Phases 3-6 connect all remaining input sources to the Angle Pipeline, enabling users to extract angle candidates from various research data sources. These phases were combined into a single session since they follow the same implementation pattern.

## Completed Work

### 1. AngleCandidateService Extraction Methods

Added new extraction methods to `viraltracker/services/angle_candidate_service.py`:

| Method | Source | Description |
|--------|--------|-------------|
| `extract_from_reddit_quotes()` | `reddit_research` | Extracts from `reddit_sentiment_quotes` |
| `extract_from_ad_analysis()` | `ad_performance` | Extracts from ad creative analysis |
| `extract_from_competitor_amazon_reviews()` | `competitor_research` | Extracts from competitor Amazon analysis |
| `extract_from_competitor_landing_pages()` | `competitor_research` | Extracts from competitor landing pages |
| `extract_from_brand_amazon_reviews()` | `brand_research` | Extracts from brand's Amazon analysis |
| `extract_from_brand_landing_pages()` | `brand_research` | Extracts from brand's landing pages |

### 2. UI Integrations

#### Reddit Research (15_Reddit_Research.py)
- Added `render_candidate_extraction()` function
- Shows after pipeline results with quote counts
- Allows selecting brand/product for extraction
- Extracts PAIN_POINT, DESIRED_OUTCOME, BUYING_OBJECTION, FAILED_SOLUTION quotes

#### Ad Performance (30_Ad_Performance.py)
- Added `_render_save_candidate_ui()` function
- Shows in `render_analysis_result()` when analysis completes
- Allows saving angle/belief as candidate with product selection
- Creates `ad_hypothesis` candidate type

#### Competitor Research (12_Competitor_Research.py)
- Added `_render_competitor_extraction_section()` function
- Shows in Amazon tab when analysis exists
- Allows extracting from Amazon reviews and landing pages
- Links to brand's products (not competitor's)

#### Brand Research (05_Brand_Research.py)
- Added `render_angle_extraction_section()` function (Section 5)
- Shows between Amazon Review Analysis and Persona Synthesis
- Extracts from Amazon reviews and belief-first landing page analysis
- Updated Persona Synthesis to Section 6

## Extraction Mapping

| Source Category | Data Source | Candidate Types Created |
|-----------------|-------------|------------------------|
| reddit_research | `reddit_sentiment_quotes` | pain_signal, jtbd, pattern, ump |
| ad_performance | Ad analysis results | ad_hypothesis |
| competitor_research | `competitor_amazon_review_analysis` | pain_signal, jtbd, ump |
| competitor_research | `competitor_landing_pages.belief_first_analysis` | pain_signal, jtbd, ad_hypothesis, pattern |
| brand_research | `amazon_review_analysis` | pain_signal, jtbd |
| brand_research | `brand_landing_pages.belief_first_analysis` | pain_signal, jtbd, ad_hypothesis, pattern |

## Key Implementation Patterns

### Deduplication via get_or_create_candidate()
All extraction methods use `get_or_create_candidate()` which:
1. Checks for similar candidates via embedding similarity (>0.92)
2. Creates new candidate if no match found
3. Updates existing candidate if match found
4. Returns tuple of (candidate, was_created)

### Evidence Tracking
Each extraction adds evidence records to `angle_candidate_evidence`:
- Links back to source (run_id, post_id, url)
- Stores original quote/text
- Tracks confidence scores

### Product Linkage
All candidates are linked to a **brand's product** (not competitor's):
- Reddit: User selects product before extraction
- Ad Performance: User selects product when saving
- Competitor Research: User selects brand product (competitive intel)
- Brand Research: Uses selected product or prompts selection

## Files Modified

### Service Layer
- `viraltracker/services/angle_candidate_service.py` - Added 6 extraction methods + helper

### UI Layer
- `viraltracker/ui/pages/15_🔍_Reddit_Research.py` - Added extraction section
- `viraltracker/ui/pages/30_📈_Ad_Performance.py` - Added save candidate UI
- `viraltracker/ui/pages/12_🔍_Competitor_Research.py` - Added extraction section
- `viraltracker/ui/pages/05_🔬_Brand_Research.py` - Added extraction section

## Testing Checklist

- [ ] Reddit Research: Run pipeline, extract quotes as candidates
- [ ] Ad Performance: Analyze ad, save as candidate
- [ ] Competitor Research: Extract from Amazon/landing pages
- [ ] Brand Research: Extract from Amazon/landing pages
- [ ] Verify candidates appear in Angle Pipeline UI
- [ ] Verify deduplication works (re-extract same data)
- [ ] Verify evidence records are created

## Next Steps (Phase 7+)

### Phase 7: Research Insights UI
- Create dedicated UI page for viewing/managing candidates
- Add filtering, sorting, status updates
- Add evidence viewer
- "Promote to Angle" workflow

### Phase 8: Scheduler Belief-First Support
- Add belief-first support to Ad Scheduler
- Connect angle_candidates to scheduling workflow

### Phase 9: Pattern Discovery Engine
- Automatic clustering of similar candidates
- Novelty scoring
- Growth mechanism for angle library

## Architecture Notes

```
Input Sources → AngleCandidateService.extract_from_*() → angle_candidates table
                                                      ↘ angle_candidate_evidence table
```

Each extraction method:
1. Queries source data from appropriate table
2. Filters to relevant items
3. Calls `get_or_create_candidate()` for deduplication
4. Calls `add_evidence()` to track source
5. Returns stats: {created, updated, errors}
