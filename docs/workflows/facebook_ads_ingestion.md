# Facebook Ads Ingestion Workflow

## Overview

Complete Facebook Ads ingestion tool for scraping ads from Facebook Ad Library using the Apify actor `curious_coder/facebook-ads-library-scraper`. This tool ingests all available metadata from Facebook Ad Library for competitive analysis, brand tracking, and ad research.

## Features

- Search Facebook Ad Library by URL (keyword search, filters)
- Scrape all ads run by specific Facebook pages
- Full metadata capture: spend, impressions, reach, creative snapshots, political transparency
- Link ads to projects and brands for organized analysis
- Date range filtering (last 24h, 7d, 14d, 30d)
- Active status filtering (all, active, inactive)
- EU transparency details scraping

## Database Schema

### Tables

#### `facebook_ads`
Main table storing all Facebook ad data with 30+ metadata fields:

**Core Identifiers:**
- `ad_id` - Facebook ad ID
- `ad_archive_id` - Unique archive identifier (primary key)
- `account_id` - References `accounts` table (Facebook page)
- `platform_id` - References `platforms` table (Facebook)

**Ad Metadata:**
- `categories` - Ad category tags (JSONB)
- `archive_types` - Archive classification (JSONB)
- `entity_type` - Entity type classification
- `is_active` - Current active status
- `is_profile_page` - Profile page flag

**Creative & Content:**
- `snapshot` - Full creative snapshot data (JSONB)
- `contains_digital_media` - Digital media flag

**Dates:**
- `start_date` - Ad start date
- `end_date` - Ad end date (if inactive)

**Financial & Reach:**
- `currency` - Spend currency
- `spend` - Estimated spend range
- `impressions` - Impression counts with index
- `reach_estimate` - Estimated reach

**Political & Transparency:**
- `political_countries` - Countries for political ads (JSONB)
- `state_media_label` - State media labeling
- `is_aaa_eligible` - AAA eligibility flag
- `aaa_info` - AAA transparency data (JSONB)

**Platform & Delivery:**
- `publisher_platform` - Publishing platforms (JSONB)
- `gated_type` - Gating type

**Collation & Grouping:**
- `collation_id` - Ad group identifier
- `collation_count` - Number in collation

**Safety & Moderation:**
- `has_user_reported` - User reporting flag
- `report_count` - Number of reports
- `hide_data_status` - Data hiding status
- `hidden_safety_data` - Safety-related data (JSONB)

**Additional Data:**
- `advertiser` - Advertiser information (JSONB)
- `insights` - Ad insights data (JSONB)
- `menu_items` - Menu options (JSONB)

**Import Tracking:**
- `import_source` - Source of import
- `scraped_at` - Scrape timestamp

#### `project_facebook_ads`
Links Facebook ads to projects for analysis:
- `project_id` - References `projects` table
- `ad_id` - References `facebook_ads` table
- `import_method` - Import method used
- `notes` - Optional notes

#### `brand_facebook_ads`
Links Facebook ads to brands for competitor analysis:
- `brand_id` - References `brands` table
- `ad_id` - References `facebook_ads` table
- `import_method` - Import method used
- `notes` - Optional notes

## CLI Commands

### `facebook search`

Search Facebook Ad Library by URL with keyword/filter parameters.

```bash
facebook search <URL> [OPTIONS]
```

**Arguments:**
- `url` - Facebook Ad Library search URL

**Options:**
- `--count <int>` - Max number of ads to scrape
- `--details` - Scrape EU transparency details (flag)
- `--period <choice>` - Date range filter: last24h, last7d, last14d, last30d, or empty
- `--project <slug>` - Project slug to link ads to
- `--brand <slug>` - Brand slug to link ads to
- `--save` - Save ads to database (flag)

**Example:**
```bash
facebook search "https://www.facebook.com/ads/library/?active_status=all&ad_type=all&country=US&q=marketing" \
  --count 100 \
  --period last30d \
  --save \
  --project my-project
```

### `facebook page`

Scrape all ads run by a specific Facebook page.

```bash
facebook page <PAGE_URL> [OPTIONS]
```

**Arguments:**
- `page_url` - Facebook page URL

**Options:**
- `--count <int>` - Max number of ads to scrape
- `--status <choice>` - Filter by active status: all, active, inactive (default: all)
- `--country <code>` - 2-letter country code or ALL (default: ALL)
- `--details` - Scrape EU transparency details (flag)
- `--project <slug>` - Project slug to link ads to
- `--brand <slug>` - Brand slug to link ads to
- `--save` - Save ads to database (flag)

**Example:**
```bash
facebook page "https://www.facebook.com/Nike" \
  --count 50 \
  --status active \
  --country US \
  --save \
  --project nike-ads
```

## Usage Workflows

### Workflow 1: Competitor Ad Research

Track competitor advertising on Facebook:

```bash
# 1. Create brand for competitor
viraltracker brand create nike-competitor --name "Nike"

# 2. Create project for analysis
viraltracker project create nike-ad-analysis --brand nike-competitor

# 3. Scrape all active Nike ads
facebook page "https://www.facebook.com/Nike" \
  --status active \
  --save \
  --project nike-ad-analysis \
  --brand nike-competitor
```

### Workflow 2: Keyword-Based Ad Discovery

Discover ads by keyword/topic:

```bash
# Search for "fitness marketing" ads from last 30 days
facebook search "https://www.facebook.com/ads/library/?active_status=all&ad_type=all&country=US&q=fitness+marketing" \
  --count 200 \
  --period last30d \
  --save \
  --project fitness-ad-research
```

### Workflow 3: Political Ad Transparency

Research political advertising with full transparency data:

```bash
# Scrape political ads with EU details
facebook search "https://www.facebook.com/ads/library/?active_status=all&ad_type=political_and_issue_ads&country=US&q=election" \
  --count 100 \
  --details \
  --save \
  --project political-ads-2024
```

## Technical Implementation

### Scraper: `viraltracker/scrapers/facebook_ads.py`

**Class:** `FacebookAdsScraper`

**Key Methods:**

1. `search_ad_library()` - Search Ad Library by URL
   - Takes search URL with embedded filters
   - Optional count, period, details flags
   - Returns pandas DataFrame with normalized ad data

2. `scrape_page_ads()` - Scrape ads from specific page
   - Takes page URL, count, status, country, details
   - Returns pandas DataFrame with normalized ad data

3. `save_ads_to_db()` - Save ads to database
   - Takes DataFrame, optional project_id, brand_id
   - Upserts ads using ad_archive_id as unique key
   - Creates project/brand linkages
   - Returns list of saved ad IDs

### Data Normalization

The scraper normalizes all Apify actor fields into database schema:

```python
ad_data = {
    "ad_id": str(ad.get("adid", "")),
    "ad_archive_id": str(ad.get("adArchiveID", "")),
    "page_id": str(page_id),
    "page_name": page_name,
    "categories": json.dumps(ad.get("categories", [])),
    "snapshot": json.dumps(ad.get("snapshot", {})),
    "currency": ad.get("currency"),
    "spend": ad.get("spend"),
    "impressions": ad.get("impressionsWithIndex"),
    "reach_estimate": ad.get("reachEstimate"),
    # ... 30+ fields total
}
```

### Account (Page) Mapping

Facebook pages are stored in the `accounts` table:
- `platform_username` = Facebook page ID
- `display_name` = Facebook page name
- `platform_id` = Facebook platform ID

This allows linking ads to their source pages for page-level analysis.

## Setup Instructions

### 1. Run Database Migration

```bash
# Apply the Facebook ads schema migration
psql <your-database-url> < migrations/05_facebook_ads.sql
```

This creates:
- `facebook_ads` table
- `project_facebook_ads` linking table
- `brand_facebook_ads` linking table
- Facebook platform entry
- All indexes

### 2. Configure Apify API Key

Ensure your `.env` file contains:

```bash
APIFY_API_TOKEN=your_apify_token_here
```

The scraper uses the `curious_coder/facebook-ads-library-scraper` actor.

### 3. Test the CLI

```bash
# Test search command
facebook search "https://www.facebook.com/ads/library/?active_status=all&ad_type=all&country=US&q=marketing" \
  --count 5

# Test page command
facebook page "https://www.facebook.com/Nike" --count 5
```

## Apify Actor Details

**Actor:** `curious_coder/facebook-ads-library-scraper`

**Input Parameters:**
- `searchPageUrl` - Ad Library search URL
- `facebookPages` - Array of Facebook page URLs to scrape
- `count` - Maximum number of ads (default: 20)
- `scrapeDetails` - Enable EU transparency details (default: false)
- `period` - Date range filter (optional)

**Output Fields:**
- Ad identification (adid, adArchiveID)
- Page info (pageID, pageName)
- Creative data (snapshot, images, videos)
- Financial data (currency, spend, impressions)
- Political transparency (politicalCountries, stateMediaRunLabel)
- Dates (startDate, endDate)
- Platform (publisherPlatform)
- And 20+ more fields...

All fields are captured and stored in the database for maximum flexibility.

## Data Analysis Examples

### Query Active Ads by Spend

```sql
SELECT
    page_name,
    COUNT(*) as ad_count,
    spend,
    impressions,
    start_date
FROM facebook_ads
WHERE is_active = true
    AND spend IS NOT NULL
ORDER BY start_date DESC
LIMIT 100;
```

### Find Political Ads

```sql
SELECT
    ad_archive_id,
    page_name,
    political_countries,
    state_media_label,
    spend,
    impressions
FROM facebook_ads
WHERE political_countries IS NOT NULL
    AND political_countries != '[]'
ORDER BY scraped_at DESC;
```

### Project Ad Analysis

```sql
SELECT
    p.name as project_name,
    COUNT(pfa.ad_id) as total_ads,
    COUNT(CASE WHEN fa.is_active THEN 1 END) as active_ads,
    MIN(fa.start_date) as earliest_ad,
    MAX(fa.start_date) as latest_ad
FROM projects p
JOIN project_facebook_ads pfa ON p.id = pfa.project_id
JOIN facebook_ads fa ON pfa.ad_id = fa.id
GROUP BY p.name;
```

## Limitations & Notes

1. **Facebook Ad Library Access** - Data availability depends on Facebook's Ad Library policies and API access
2. **Rate Limiting** - Apify actor may have rate limits depending on subscription
3. **Spend Ranges** - Facebook provides spend/impressions as ranges, not exact numbers
4. **EU Transparency** - Detailed transparency data only available for EU/political ads
5. **Active Status** - Ad active status may change; data reflects status at scrape time
6. **Creative Assets** - Images/videos referenced by URL in snapshot JSONB field

## Next Steps

1. **Bulk Import Scripts** - Create scripts for bulk page/keyword scraping
2. **Scheduled Scraping** - Set up cron jobs for regular ad monitoring
3. **Creative Analysis** - Build tools to analyze ad creative patterns
4. **Spend Tracking** - Track spend changes over time
5. **Competitive Dashboards** - Build dashboards comparing competitor ad strategies
6. **Export Utilities** - Create CSV/JSON export tools for ad data

## File Locations

- **Scraper:** `viraltracker/scrapers/facebook_ads.py`
- **CLI:** `viraltracker/cli/facebook.py`
- **Migration:** `migrations/05_facebook_ads.sql`
- **Documentation:** `docs/workflows/facebook_ads_ingestion.md`

## Support

For issues with:
- **Database schema** - Check migration file and table definitions
- **Apify actor** - Refer to `curious_coder/facebook-ads-library-scraper` documentation
- **CLI errors** - Check `.env` configuration and database connection
- **Data quality** - Review Facebook Ad Library access and data availability
