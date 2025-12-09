# Sprint 3.5: Amazon Review Scraping

**Branch**: `feature/brand-research-pipeline`
**Status**: Planning
**Created**: 2025-12-08

---

## 1. Overview

### Problem
- Ads show what marketers *think* resonates
- Reviews show what customers *actually* feel and say
- We need authentic customer language for 4D personas

### Solution
Use the **Axesso Amazon Review Scraper** on Apify with a multi-layer scraping strategy to capture 80%+ of reviews (~1,300+ from 1,600 total) for ~$1 per ASIN.

### Key Constraint
- Each Apify config returns max ~100 reviews
- No traditional pagination
- Solution: Run multiple configs (star filters, keywords, sort modes) and deduplicate by `reviewId`

---

## 2. Scraping Strategy (From User Research)

### Layer 1: Star-Level Sweep (Core Coverage)
```
sortBy: recent, no filter (all stars)
sortBy: recent, filterByStar: five_star
sortBy: recent, filterByStar: four_star
sortBy: recent, filterByStar: three_star
sortBy: recent, filterByStar: two_star
sortBy: recent, filterByStar: one_star
```

### Layer 2: Universal Keyword Sweep (Surface-Area Booster)

**Positive keywords:**
```
great, good, love, amazing, excellent, perfect, works, helpful, happy, recommend
```

**Negative keywords:**
```
bad, terrible, awful, broke, waste, refund, disappointed
```

**Experience/Quality keywords:**
```
quality, price, value, smell, taste
```

### Layer 3: Helpful Sort Sweep (High-Signal Reviews)
```
sortBy: helpful, no filter
sortBy: helpful, filterByStar: five_star
sortBy: helpful, filterByStar: one_star
```

### Deduplication
- All reviews merged by `reviewId`
- Result: ~1,300 unique reviews per ASIN

---

## 3. Technical Implementation

### 3.1 New Service: `AmazonReviewService`

**File**: `viraltracker/services/amazon_review_service.py`

```python
class AmazonReviewService:
    """Service for scraping and analyzing Amazon reviews via Apify."""

    APIFY_ACTOR = "axesso_data/amazon-reviews-scraper"

    # Scraping configuration
    STAR_FILTERS = ["five_star", "four_star", "three_star", "two_star", "one_star"]
    POSITIVE_KEYWORDS = ["great", "good", "love", "amazing", "excellent", "perfect", "works", "helpful", "happy", "recommend"]
    NEGATIVE_KEYWORDS = ["bad", "terrible", "awful", "broke", "waste", "refund", "disappointed"]
    EXPERIENCE_KEYWORDS = ["quality", "price", "value", "smell", "taste"]

    def __init__(self, apify_token: str = None):
        self.apify_token = apify_token or os.getenv("APIFY_API_TOKEN")
        self.supabase = get_supabase_client()

    # --- URL Parsing ---
    def extract_asin_from_url(self, url: str) -> Optional[str]:
        """Extract ASIN from Amazon URL."""
        # Handles: /dp/ASIN, /gp/product/ASIN, /product/ASIN

    def extract_domain_from_url(self, url: str) -> str:
        """Extract domain code from Amazon URL (com, ca, co.uk, etc.)."""

    # --- Scraping ---
    def build_scrape_configs(self, asin: str, domain: str = "com") -> List[Dict]:
        """Build the full set of Apify actor configs for max coverage."""
        # Returns 31 configs: 6 star + 15 positive + 7 negative + 3 helpful

    async def scrape_reviews_for_product(
        self,
        product_id: UUID,
        amazon_url: str,
        max_configs: int = 31  # All configs by default
    ) -> Dict[str, Any]:
        """
        Scrape Amazon reviews for a product.

        Returns: {"reviews_scraped": int, "unique_reviews": int, "cost_estimate": float}
        """

    async def _run_apify_actor(self, configs: List[Dict]) -> List[Dict]:
        """Run Axesso actor with given configs and return raw results."""

    def _deduplicate_reviews(self, raw_reviews: List[Dict]) -> List[Dict]:
        """Deduplicate reviews by reviewId."""

    # --- Storage ---
    def save_reviews(
        self,
        reviews: List[Dict],
        product_id: UUID,
        brand_id: UUID,
        asin: str
    ) -> int:
        """Save deduped reviews to database. Returns count saved."""

    # --- Analysis ---
    async def analyze_reviews_for_product(
        self,
        product_id: UUID,
        limit: int = 500
    ) -> Dict[str, Any]:
        """
        Analyze stored reviews with Claude to extract persona signals.

        Returns analysis with:
        - pain_points (categorized)
        - desires (categorized)
        - language_patterns (exact phrases)
        - objections
        - purchase_triggers
        - sentiment_distribution
        """

    # --- Stats ---
    def get_review_stats(self, product_id: UUID) -> Dict[str, int]:
        """Get review counts and analysis status for a product."""
```

### 3.2 Database Schema

**File**: `migrations/2025-12-08_amazon_reviews.sql`

```sql
-- Amazon product URLs (links products to Amazon listings)
CREATE TABLE amazon_product_urls (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    product_id UUID NOT NULL REFERENCES products(id) ON DELETE CASCADE,
    brand_id UUID NOT NULL REFERENCES brands(id) ON DELETE CASCADE,
    amazon_url TEXT NOT NULL,
    asin TEXT NOT NULL,
    domain_code TEXT NOT NULL DEFAULT 'com',

    -- Scrape tracking
    last_scraped_at TIMESTAMPTZ,
    total_reviews_scraped INTEGER DEFAULT 0,
    scrape_cost_estimate DECIMAL(10,4),

    created_at TIMESTAMPTZ DEFAULT NOW(),
    updated_at TIMESTAMPTZ DEFAULT NOW(),

    UNIQUE(product_id, asin)
);

-- Individual reviews
CREATE TABLE amazon_reviews (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    amazon_product_url_id UUID NOT NULL REFERENCES amazon_product_urls(id) ON DELETE CASCADE,
    product_id UUID NOT NULL REFERENCES products(id) ON DELETE CASCADE,
    brand_id UUID NOT NULL REFERENCES brands(id) ON DELETE CASCADE,

    -- Amazon data
    review_id TEXT NOT NULL,  -- Amazon's review ID for deduplication
    asin TEXT NOT NULL,
    rating INTEGER CHECK (rating >= 1 AND rating <= 5),
    title TEXT,
    body TEXT,
    author TEXT,
    review_date DATE,
    verified_purchase BOOLEAN DEFAULT FALSE,
    helpful_votes INTEGER DEFAULT 0,

    -- Scrape metadata
    scrape_source TEXT,  -- 'star_filter', 'keyword_filter', 'helpful_sort'
    scrape_filter TEXT,  -- The specific filter used (e.g., 'five_star', 'great')

    scraped_at TIMESTAMPTZ DEFAULT NOW(),

    UNIQUE(review_id, asin)  -- Dedupe constraint
);

-- Aggregated review analysis per product
CREATE TABLE amazon_review_analysis (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    product_id UUID NOT NULL REFERENCES products(id) ON DELETE CASCADE,
    brand_id UUID NOT NULL REFERENCES brands(id) ON DELETE CASCADE,

    -- Analysis results
    total_reviews_analyzed INTEGER,
    sentiment_distribution JSONB,  -- {"5_star": 450, "4_star": 300, ...}

    -- Extracted persona signals
    pain_points JSONB,        -- {"emotional": [...], "functional": [...], "social": [...]}
    desires JSONB,            -- {"emotional": [...], "functional": [...], "social": [...]}
    language_patterns JSONB,  -- {"positive_phrases": [...], "negative_phrases": [...]}
    objections JSONB,         -- Common objections/complaints
    purchase_triggers JSONB,  -- What made people buy

    -- Verbatim quotes (gold for ad copy)
    top_positive_quotes TEXT[],
    top_negative_quotes TEXT[],
    transformation_quotes TEXT[],  -- Before/after language

    -- Meta
    model_used TEXT,
    analyzed_at TIMESTAMPTZ DEFAULT NOW(),

    UNIQUE(product_id)
);

-- Indexes
CREATE INDEX idx_amazon_reviews_product ON amazon_reviews(product_id);
CREATE INDEX idx_amazon_reviews_rating ON amazon_reviews(rating);
CREATE INDEX idx_amazon_reviews_asin ON amazon_reviews(asin);
CREATE INDEX idx_amazon_product_urls_product ON amazon_product_urls(product_id);
```

### 3.3 UI Integration

**Location**: Add section to `19_🔬_Brand_Research.py` OR create new tab in URL Mapping

**UI Flow**:
1. User adds Amazon URL for a product (in URL Mapping or Brand Research)
2. System extracts ASIN and domain
3. "Scrape Reviews" button triggers scraping
4. Progress shows: configs run, reviews collected, duplicates removed
5. "Analyze Reviews" button runs Claude analysis
6. Results displayed and included in persona synthesis

**New UI Section: "4. Amazon Reviews"**
```
┌─────────────────────────────────────────────────────────────┐
│ 4. Amazon Reviews                                           │
│                                                             │
│ Add Amazon product URLs to scrape authentic customer        │
│ language for persona building.                              │
│                                                             │
│ ┌─────────────────────────────────────────────────────────┐│
│ │ Product: [Dropdown - select product]                    ││
│ │ Amazon URL: [________________________] [Add URL]        ││
│ └─────────────────────────────────────────────────────────┘│
│                                                             │
│ Products with Amazon URLs:                                  │
│ ┌─────────────────────────────────────────────────────────┐│
│ │ Yakety Yak Treats - Himalayan Yak Chews                 ││
│ │ ASIN: B0DJWSV1J3 | Reviews: 1,314 scraped | ✅ Analyzed ││
│ │ [Scrape Reviews] [Analyze Reviews] [View Insights]      ││
│ └─────────────────────────────────────────────────────────┘│
│                                                             │
│ Estimated cost: ~$1.00 per product (1,000+ reviews)        │
└─────────────────────────────────────────────────────────────┘
```

### 3.4 Review Analysis Prompt

```python
REVIEW_ANALYSIS_PROMPT = """Analyze these Amazon reviews to extract customer insights for persona building.

REVIEWS (Rating | Title | Body):
{reviews_text}

Extract the following and return as JSON:

{
    "pain_points": {
        "emotional": ["Exact phrases about feelings/frustrations"],
        "functional": ["Exact phrases about product not working"],
        "social": ["Exact phrases about embarrassment/judgment"]
    },
    "desires": {
        "emotional": ["What they hoped to feel"],
        "functional": ["What they wanted the product to do"],
        "social": ["How they wanted to be perceived"]
    },
    "language_patterns": {
        "positive_phrases": ["Exact phrases they use when happy"],
        "negative_phrases": ["Exact phrases they use when upset"],
        "descriptive_words": ["Common adjectives/adverbs used"]
    },
    "objections": [
        {"objection": "The concern", "frequency": "common/occasional/rare"}
    ],
    "purchase_triggers": [
        "What made them finally buy"
    ],
    "transformation_language": {
        "before": ["How they describe life before"],
        "after": ["How they describe life after"]
    },
    "top_quotes": {
        "positive": ["Best 5 positive verbatim quotes for ads"],
        "negative": ["Top 5 complaints to address in copy"],
        "transformation": ["Best before/after quotes"]
    },
    "sentiment_summary": {
        "overall": "positive/mixed/negative",
        "common_praise": ["What people love most"],
        "common_complaints": ["What people dislike most"]
    }
}

CRITICAL: Use EXACT customer language. Do not paraphrase. These phrases will be used in ad copy.

Return ONLY valid JSON."""
```

### 3.5 Integration with Persona Synthesis

Update `synthesize_to_personas()` to include review data:

```python
# In BrandResearchService.synthesize_to_personas():

# Fetch review analysis if available
review_analysis = self._get_review_analysis_for_brand(brand_id)

# Add to aggregated data
aggregated_data = {
    "video_analyses": [...],
    "image_analyses": [...],
    "copy_analyses": [...],
    "landing_page_analyses": [...],
    "amazon_review_analysis": review_analysis  # NEW
}

# Update synthesis prompt to weight review language heavily
```

---

## 4. Implementation Order

### Phase 1: Database & Service Foundation
1. [ ] Create migration for amazon tables
2. [ ] Create `AmazonReviewService` with URL parsing
3. [ ] Implement `build_scrape_configs()`
4. [ ] Test config generation

### Phase 2: Apify Integration
1. [ ] Implement `_run_apify_actor()` with polling
2. [ ] Implement `_deduplicate_reviews()`
3. [ ] Implement `save_reviews()`
4. [ ] Test full scrape flow with real ASIN

### Phase 3: Analysis
1. [ ] Implement `analyze_reviews_for_product()`
2. [ ] Create analysis prompt
3. [ ] Store analysis results
4. [ ] Test analysis quality

### Phase 4: UI Integration
1. [ ] Add Amazon URL input to UI
2. [ ] Add scrape/analyze buttons
3. [ ] Display review stats and insights
4. [ ] Add to persona synthesis flow

### Phase 5: Testing & Polish
1. [ ] Test with multiple products
2. [ ] Verify deduplication works
3. [ ] Verify analysis integrates into personas
4. [ ] Add cost tracking

---

## 5. Dependencies

### New Environment Variable
```
APIFY_API_TOKEN=your_apify_token
```

### Python Dependencies
```
apify-client>=1.0.0  # Already have this for Facebook scraping?
```

### Cost Estimate
- ~$0.75 per 1,000 results from Apify
- ~31 configs × ~100 results = ~3,100 raw results
- After dedup: ~1,300 unique reviews
- **Cost per ASIN: ~$2.30** (3,100 × $0.75/1000)
- Could optimize with early-stopping to reduce to ~$1

---

## 6. Apify Actor Reference

**Actor**: `axesso_data/amazon-reviews-scraper`

**Input Schema**:
```json
{
    "asin": "B0DJWSV1J3",
    "domainCode": "com",
    "sortBy": "recent",           // or "helpful"
    "maxPages": 10,
    "filterByStar": "five_star",  // optional
    "filterByKeyword": "great",   // optional
    "reviewerType": "all_reviews",
    "mediaType": "all_contents",
    "formatType": "current_format"
}
```

**Output Fields**:
- `reviewId` - Unique identifier (for deduplication)
- `asin` - Product ASIN
- `rating` - 1-5 stars
- `title` - Review title
- `text` - Review body
- `date` - Review date
- `verified` - Verified purchase boolean
- `numberOfHelpful` - Helpful votes count
- `author` - Reviewer name

---

## 7. Questions to Resolve

1. **Where to add Amazon URLs?**
   - Option A: New section in Brand Research page
   - Option B: New column in URL Mapping page
   - Option C: Dedicated Amazon Reviews page

2. **Scrape trigger?**
   - Manual button only
   - Auto-scrape when URL added
   - Scheduled refresh?

3. **Cost controls?**
   - Show estimated cost before scraping?
   - Implement early-stopping?
   - Daily/monthly budget limits?

---

## 8. Success Criteria

- [ ] Can add Amazon URL for a product
- [ ] Scrapes 1,000+ unique reviews per product
- [ ] Deduplication works correctly
- [ ] Analysis extracts authentic customer language
- [ ] Review insights appear in persona synthesis
- [ ] Cost is ~$1-2 per product
