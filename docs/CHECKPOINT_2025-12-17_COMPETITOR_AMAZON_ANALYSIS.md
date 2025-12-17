# Checkpoint: Competitor Amazon Review Analysis

**Date:** 2025-12-17
**Branch:** main

## What Was Built

### 1. Competitor Amazon Review Scraping & Analysis

Added full Amazon review scraping and rich themed analysis for competitors.

**Files Modified:**
- `viraltracker/services/competitor_service.py` - Added ~500 lines:
  - `scrape_amazon_reviews_for_competitor()` - Scrapes via Apify/Axesso
  - `analyze_amazon_reviews_for_competitor()` - Rich Claude analysis
  - `_save_competitor_reviews()` - Saves to `competitor_amazon_reviews`
  - `_build_rich_analysis_prompt()` - 7-category themed prompt
  - `_save_competitor_amazon_analysis()` - Saves analysis results

- `viraltracker/ui/pages/23_🔍_Competitor_Research.py` - Updated Amazon tab:
  - Wired up Scrape button to actually scrape
  - Added Analyze button
  - 7-tab display with themed quotes + context

### 2. Rich Analysis Format (7 Categories)

Each category has numbered themes with:
- Theme name and score (1-10)
- 3-5 verbatim quotes per theme
- Context explaining customer psychology for each quote

**Categories:**
| Tab | Description |
|-----|-------------|
| Pain Points | Life frustrations BEFORE the product |
| Jobs to Be Done | Functional, emotional, social goals |
| Product Issues | Problems WITH this specific product |
| Desired Outcomes | What they want to achieve |
| Buying Objections | Pre-purchase hesitations |
| Desired Features | Attributes they value |
| Failed Solutions | Past products that didn't work |

### 3. Database Storage

Analysis stored in `competitor_amazon_review_analysis` table:
- `pain_points` JSONB contains: `themes`, `jobs_to_be_done`, `product_issues`
- `desires` JSONB contains: `themes` (desired outcomes)
- `objections` JSONB contains: `themes` (buying objections)
- `language_patterns` JSONB contains: `themes` (desired features)
- `transformation` JSONB contains: `themes` (failed solutions)

### 4. Migrations Created

- `migrations/2025-12-17_add_competitor_product_id_to_reviews.sql` - Adds optional product-level tracking

## What's Next

**Migrate to Brand Side:**
1. Update `viraltracker/services/amazon_review_service.py`:
   - Replace `REVIEW_ANALYSIS_PROMPT` with 7-category rich format
   - Update `analyze_reviews_for_product()` to use new prompt
   - Update `_save_analysis()` to store new structure

2. Update `viraltracker/ui/pages/19_🔬_Brand_Research.py`:
   - Add 7-tab display for Amazon analysis results
   - Use same `render_themed_section()` pattern as competitor side

## Key Code References

### Rich Analysis Prompt (competitor_service.py ~1921-2060)
```python
def _build_rich_analysis_prompt(self, reviews_text, competitor_name, product_name, review_count):
    """7-category prompt with themes, scores, quotes, and context"""
```

### Save Analysis (competitor_service.py ~2062-2110)
```python
def _save_competitor_amazon_analysis(self, competitor_id, competitor_product_id, analysis, reviews_count):
    """Stores jobs_to_be_done and product_issues inside pain_points JSONB"""
```

### UI Display (23_🔍_Competitor_Research.py ~1205-1290)
```python
def render_themed_section(themes: list, tab_name: str):
    """Renders themed quotes with context in markdown blockquote format"""
```

## Commits

- `b46ef55` - feat: Add Amazon review scraping & analysis for competitors
- `1b7b5a1` - fix: Remove competitor_product_id from reviews save (column missing)
- `121cd26` - fix: Use delete+insert instead of upsert for competitor analysis
- `fd9dacb` - feat: Add Jobs to Be Done and Product Issues tabs to Amazon analysis
