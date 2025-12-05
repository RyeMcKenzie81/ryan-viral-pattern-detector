# Checkpoint: Sprint 1 - URL Mapping System Complete

**Date**: 2025-12-04
**Branch**: `feature/brand-research-pipeline`
**Status**: Complete and tested

---

## Overview

The URL Mapping system enables product-level isolation for Facebook ad analysis. Instead of analyzing all ads at the brand level, ads can now be categorized by:
- **Product**: Specific product landing pages
- **Collection**: Category/collection pages featuring multiple products
- **Brand-level**: Homepage, about pages (brand-wide but not product-specific)
- **Ignored**: Social media links, external sites (excluded from analysis)

---

## Database Schema

### Tables Created

#### `product_urls`
Maps landing page URL patterns to products.

| Column | Type | Description |
|--------|------|-------------|
| id | UUID | Primary key |
| product_id | UUID | FK to products |
| url_pattern | TEXT | URL or pattern to match |
| match_type | TEXT | 'exact', 'prefix', 'contains', 'regex' |
| is_primary | BOOLEAN | Primary landing page flag |
| notes | TEXT | Optional notes |
| created_at | TIMESTAMPTZ | Creation timestamp |
| updated_at | TIMESTAMPTZ | Last update timestamp |

#### `url_review_queue`
Queue for discovered URLs awaiting categorization.

| Column | Type | Description |
|--------|------|-------------|
| id | UUID | Primary key |
| brand_id | UUID | FK to brands |
| url | TEXT | Original URL |
| normalized_url | TEXT | Cleaned URL for deduplication |
| occurrence_count | INT | Number of ads using this URL |
| sample_ad_ids | UUID[] | Sample ad IDs for preview |
| suggested_product_id | UUID | AI-suggested product |
| suggestion_confidence | FLOAT | Confidence score |
| status | TEXT | 'pending', 'assigned', 'new_product', 'ignored', 'brand_level', 'collection' |
| notes | TEXT | Categorization notes |
| reviewed_by | TEXT | Reviewer identifier |
| reviewed_at | TIMESTAMPTZ | Review timestamp |
| created_at | TIMESTAMPTZ | Creation timestamp |
| updated_at | TIMESTAMPTZ | Last update timestamp |

### Columns Added to Existing Tables

#### `facebook_ads`
| Column | Type | Description |
|--------|------|-------------|
| product_id | UUID | FK to products |
| product_match_confidence | FLOAT | Match confidence (0.0-1.0) |
| product_match_method | TEXT | 'url', 'ai', 'manual' |
| product_matched_at | TIMESTAMPTZ | When matched |

#### `personas_4d`
| Column | Type | Description |
|--------|------|-------------|
| persona_level | TEXT | 'brand' or 'product' |

---

## Service Layer

### ProductURLService

Location: `viraltracker/services/product_url_service.py`

#### Product Management
```python
create_product(brand_id, name, description=None) -> Dict
```
Create a new product for a brand.

#### URL Pattern Management
```python
add_product_url(product_id, url_pattern, match_type='contains', is_primary=False, notes=None) -> Dict
get_product_urls(product_id) -> List[Dict]
get_all_product_urls_for_brand(brand_id) -> List[Dict]
delete_product_url(url_id) -> bool
```

#### URL Matching
```python
match_url_to_product(url, brand_id) -> Optional[Tuple[UUID, float, str]]
extract_url_from_ad(ad) -> Optional[str]
```

#### Bulk Operations
```python
discover_urls_from_ads(brand_id, limit=1000) -> Dict[str, Any]
bulk_match_ads(brand_id, limit=500, only_unmatched=True) -> Dict[str, int]
```

#### Review Queue Management
```python
get_review_queue(brand_id, status='pending', limit=50) -> List[Dict]
assign_url_to_product(queue_id, product_id, add_as_pattern=True, match_type='contains') -> Dict
ignore_url(queue_id, ignore_reason=None) -> Dict
mark_as_brand_level(queue_id) -> Dict
mark_as_collection(queue_id) -> Dict
```

#### Statistics
```python
get_matching_stats(brand_id) -> Dict[str, Any]
```

---

## UI Page

### URL Mapping Page

Location: `viraltracker/ui/pages/18_🔗_URL_Mapping.py`

#### Features

1. **Brand Selector**: Choose which brand to manage URLs for

2. **Matching Statistics**: Shows total ads, matched, unmatched, URLs pending review

3. **Action Buttons**:
   - **Discover URLs from Ads**: Scans ads to find unique landing page URLs
   - **Run Bulk URL Matching**: Matches ads to products using configured patterns

4. **Product URL Patterns**: Per-product URL pattern management with tabs

5. **URL Review Queue**: Categorize discovered URLs with:
   - **✓ Assign to Product**: Link to existing product
   - **➕ New Product**: Create product inline and assign
   - **🏠 Brand-level**: Homepage, about pages
   - **📁 Collection**: Collection/category pages
   - **✗ Ignore**: Social media, external links

---

## URL Categorization Guide

| URL Type | Action | Status | Included In |
|----------|--------|--------|-------------|
| Product page | ✓ Assign | `assigned` | Product + Brand analysis |
| New product landing | ➕ New Product | `assigned` | Product + Brand analysis |
| Collection page | 📁 Collection | `collection` | Brand analysis only |
| Homepage | 🏠 Brand-level | `brand_level` | Brand analysis only |
| About/Info page | 🏠 Brand-level | `brand_level` | Brand analysis only |
| Social media | ✗ Ignore | `ignored` | Excluded |
| External link | ✗ Ignore | `ignored` | Excluded |

---

## Key Implementation Details

### Junction Table Pattern

Facebook ads are linked to brands via the `brand_facebook_ads` junction table, NOT via `facebook_ads.brand_id`. All queries for "ads belonging to a brand" must:

```python
# 1. Get ad IDs from junction table
link_result = supabase.table("brand_facebook_ads")\
    .select("ad_id")\
    .eq("brand_id", str(brand_id))\
    .execute()

ad_ids = [r['ad_id'] for r in link_result.data]

# 2. Query facebook_ads using IN clause
ads_result = supabase.table("facebook_ads")\
    .select("id, snapshot")\
    .in_("id", ad_ids)\
    .execute()
```

### Snapshot Parsing

The `snapshot` field in `facebook_ads` is stored as a JSON string:

```python
snapshot = ad.get('snapshot', {})

if isinstance(snapshot, str):
    snapshot = json.loads(snapshot)

# Now access fields
url = snapshot.get('link_url')
```

### URL Normalization

URLs are normalized before matching to ensure consistency:
- Protocol removed (http/https)
- `www.` prefix removed
- Trailing slashes removed
- Tracking parameters removed (utm_*, fbclid, gclid, etc.)

Example:
```
Input:  https://www.mywonderpaws.com/products/plaque?utm_source=facebook&fbclid=123
Output: mywonderpaws.com/products/plaque
```

---

## Workflow

### Initial Setup (Per Brand)

1. **Scrape Ads**: Use Brand Manager to scrape Facebook Ad Library
2. **Discover URLs**: Click "Discover URLs from Ads" in URL Mapping
3. **Categorize URLs**: Review each URL and assign to product/brand-level/collection/ignore
4. **Create Products**: Use "➕ New Product" to create products inline

### Ongoing

1. After new ad scrapes, run "Discover URLs" to find new URLs
2. New URLs appear in review queue
3. Categorize new URLs
4. Run "Bulk URL Matching" to tag new ads with products

---

## Files

```
migrations/
├── 2025-12-04_product_url_mapping.sql      # Initial schema
└── 2025-12-04_url_review_queue_updates.sql # Added statuses

viraltracker/
├── services/
│   └── product_url_service.py              # Core service
├── ui/pages/
│   └── 18_🔗_URL_Mapping.py                # Streamlit UI
└── agent/
    └── dependencies.py                      # Added ProductURLService
```

---

## Commits

```
b8cef54 feat: Add collection page category for URL mapping
c2b5553 feat: Add inline product creation and brand-level URL support
3bff800 fix: Use junction table for brand-ad relationships in ProductURLService
a0c1923 feat: Add URL discovery flow for better UX
4486f93 fix: Remove non-existent code column from products query
6a01065 feat: Add product URL mapping system (Sprint 1)
```

---

## Next Steps

### Sprint 2: Video Analysis
- Analyze video content from scraped ads using Gemini
- Extract hooks, themes, messaging patterns
- Store analysis results per product

### Sprint 3: Competitive Analysis
- Parallel URL mapping structure for competitor brands
- Compare competitor ad strategies
- Track competitor product launches

---

## Related Documents

- `/docs/CHECKPOINT_2025-12-04_PRODUCT_ISOLATION_PLAN.md` - Full product isolation plan
- `/CLAUDE.md` - Development guidelines
