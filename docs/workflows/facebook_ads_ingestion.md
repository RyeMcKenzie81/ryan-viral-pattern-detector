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

## Video Analysis Workflow (Gemini 2.5)

After scraping Facebook ads to the database, you can analyze the video creative using Google's Gemini 2.5 to extract hooks, transcripts, text overlays, and visual storyboards.

### Complete Analysis Workflow

This is the end-to-end process for downloading and analyzing Facebook ad videos:

#### Step 1: Extract Video URLs from Database

Create a script to query the database and extract video URLs from the `snapshot` JSONB field:

```python
# extract_video_urls.py
import os
import json
from dotenv import load_dotenv
from supabase import create_client

# Load environment
load_dotenv('/path/to/your/project/.env')

# Initialize Supabase
supabase = create_client(
    os.getenv("SUPABASE_URL"),
    os.getenv("SUPABASE_SERVICE_KEY")
)

# Query for specific ads by ad_archive_id
ad_ids = ["2310031212786978", "1050791440000803"]  # Your target ads

videos = []
for ad_id in ad_ids:
    result = supabase.table('facebook_ads').select(
        'ad_archive_id, snapshot, start_date'
    ).eq('ad_archive_id', ad_id).execute()

    if result.data and len(result.data) > 0:
        ad = result.data[0]
        snapshot = ad['snapshot']

        # Parse snapshot if string
        if isinstance(snapshot, str):
            snapshot = json.loads(snapshot)

        # Extract video URL (check multiple fields)
        video_url = None
        videos_array = snapshot.get('videos', [])
        if videos_array and len(videos_array) > 0:
            video_url = videos_array[0].get('video_hd_url') or videos_array[0].get('video_sd_url')

        if not video_url:
            video_url = snapshot.get('video_hd_url') or snapshot.get('video_sd_url')

        if video_url:
            videos.append({
                'ad_archive_id': ad_id,
                'start_date': ad['start_date'],
                'video_url': video_url,
                'ad_library_url': f"https://www.facebook.com/ads/library/?id={ad_id}"
            })

# Save to JSON
with open('video_metadata.json', 'w') as f:
    json.dump(videos, f, indent=2)
```

#### Step 2: Download Videos

Download videos from Facebook CDN using the extracted URLs:

```python
# download_videos.py
import json
import requests
from pathlib import Path

# Load video metadata
with open('video_metadata.json', 'r') as f:
    videos = json.load(f)

# Create output directory
output_dir = Path('./facebook_ad_videos')
output_dir.mkdir(exist_ok=True)

# Download each video
for video in videos:
    ad_id = video['ad_archive_id']
    video_url = video['video_url']

    print(f"Downloading ad {ad_id}...")

    response = requests.get(video_url, stream=True, timeout=60)
    response.raise_for_status()

    output_file = output_dir / f"{ad_id}.mp4"

    with open(output_file, 'wb') as f:
        for chunk in response.iter_content(chunk_size=8192):
            f.write(chunk)

    print(f"  ✓ Saved: {output_file.name}")
```

#### Step 3: Analyze Videos with Gemini 2.5

Use Gemini 2.5 to extract comprehensive video analysis:

```python
# analyze_videos.py
import os
import json
import time
from pathlib import Path
from dotenv import load_dotenv
from google import genai

# Load environment
load_dotenv('/path/to/your/project/.env')

# Initialize Gemini
client = genai.Client(api_key=os.getenv("GEMINI_API_KEY"))
model_name = "models/gemini-2.0-flash-exp"

# Analysis prompt
ANALYSIS_PROMPT = """Analyze this Facebook ad video.

Return ONLY valid JSON (no markdown) with this structure:

{
  "hook_analysis": {
    "transcript": "Exact spoken words in the first 3 seconds",
    "visual_description": "What's shown in the first 3 seconds",
    "hook_type": "Type of hook (problem-solution, question, etc.)",
    "timestamp_end": 3.0,
    "effectiveness_score": 8.5
  },
  "full_transcript": "Complete word-for-word transcript",
  "text_overlays": [
    {
      "text": "Exact overlay text",
      "timestamp_start": 0.0,
      "timestamp_end": 2.0,
      "position": "center/top/bottom",
      "style": "description of font/animation"
    }
  ],
  "visual_storyboard": [
    {
      "timestamp_start": 0.0,
      "timestamp_end": 3.0,
      "description": "Detailed scene description",
      "scene_type": "hook/demo/testimonial/cta"
    }
  ],
  "key_insights": {
    "primary_message": "Main value proposition",
    "call_to_action": "What viewers are asked to do",
    "emotional_trigger": "Primary emotion targeted",
    "product_showcase_method": "How product is demonstrated"
  }
}

Return ONLY the JSON, nothing else."""

# Load video metadata
with open('video_metadata.json', 'r') as f:
    videos = json.load(f)

videos_dir = Path('./facebook_ad_videos')
results = []

# Analyze each video
for video in videos:
    ad_id = video['ad_archive_id']
    video_path = videos_dir / f"{ad_id}.mp4"

    print(f"Analyzing ad {ad_id}...")

    try:
        # Upload to Gemini
        video_file = client.files.upload(file=str(video_path))

        # Wait for processing
        while video_file.state.name == "PROCESSING":
            time.sleep(2)
            video_file = client.files.get(name=video_file.name)

        if video_file.state.name == "FAILED":
            print(f"  ✗ Video processing failed")
            continue

        # Analyze
        response = client.models.generate_content(
            model=model_name,
            contents=[video_file, ANALYSIS_PROMPT]
        )

        # Parse response
        response_text = response.text.strip()

        # Remove markdown if present
        if response_text.startswith("```json"):
            response_text = response_text[7:]
        if response_text.startswith("```"):
            response_text = response_text[3:]
        if response_text.endswith("```"):
            response_text = response_text[:-3]

        analysis = json.loads(response_text.strip())

        # Add metadata
        analysis['metadata'] = {
            'ad_archive_id': ad_id,
            'start_date': video['start_date'],
            'ad_library_url': video['ad_library_url']
        }

        results.append(analysis)

        # Clean up
        client.files.delete(name=video_file.name)

        print(f"  ✓ Analysis complete")

        # Rate limit
        time.sleep(3)

    except Exception as e:
        print(f"  ✗ Error: {e}")

# Save results
with open('video_analysis.json', 'w') as f:
    json.dump(results, f, indent=2)

print(f"\n✓ Analyzed {len(results)} videos")
```

#### Step 4: Generate Summary Reports

Extract hooks and text overlays for analysis:

```python
# generate_hooks_report.py
import json
from collections import Counter

# Load analysis
with open('video_analysis.json', 'r') as f:
    analyses = json.load(f)

print("="*100)
print("HOOKS AND TEXT OVERLAYS ANALYSIS")
print("="*100)
print()

# Analyze each video
for analysis in analyses:
    meta = analysis['metadata']
    hook = analysis['hook_analysis']
    overlays = analysis.get('text_overlays', [])

    print(f"Ad ID: {meta['ad_archive_id']}")
    print(f"Started: {meta['start_date']}")
    print(f"-" * 100)

    # Hook Analysis
    print("HOOK ANALYSIS (First 3 seconds)")
    print(f"  Type: {hook['hook_type']}")
    print(f"  Visual: {hook['visual_description']}")
    print(f"  Spoken: \"{hook['transcript']}\"")
    print()

    # Text Overlays
    print(f"TEXT OVERLAYS ({len(overlays)} total)")
    for i, overlay in enumerate(overlays, 1):
        print(f"  {i}. \"{overlay['text']}\"")
        print(f"     Time: {overlay['timestamp_start']:.1f}s - {overlay['timestamp_end']:.1f}s")
        print(f"     Position: {overlay['position']}")

    print()
    print()

# Summary Statistics
print("="*100)
print("SUMMARY STATISTICS")
print("="*100)
print()

# Hook type distribution
hook_types = [a['hook_analysis']['hook_type'] for a in analyses]
hook_counter = Counter(hook_types)
print("HOOK TYPE DISTRIBUTION:")
for hook_type, count in hook_counter.most_common():
    print(f"  {hook_type}: {count} videos ({count/len(analyses)*100:.0f}%)")
print()

# Text overlay usage
overlay_counts = [len(a.get('text_overlays', [])) for a in analyses]
print("TEXT OVERLAY USAGE:")
print(f"  Average overlays per video: {sum(overlay_counts)/len(overlay_counts):.1f}")
print(f"  Total overlays: {sum(overlay_counts)}")
print(f"  Range: {min(overlay_counts)} - {max(overlay_counts)} overlays")
```

### Analysis Output

The video analysis provides:

**Hook Analysis:**
- Hook type classification (problem-solution, question, POV, etc.)
- Visual description of first 3 seconds
- Spoken transcript of opening
- Effectiveness score (1-10)

**Text Overlays:**
- Exact overlay text
- Precise timestamps (start/end)
- Position on screen (top/center/bottom)
- Style description (font, animation)

**Visual Storyboard:**
- Scene-by-scene breakdown with timestamps
- Description of what's shown
- Scene type classification

**Key Insights:**
- Primary message/value proposition
- Call-to-action
- Emotional trigger
- Product showcase method

### Example Findings (Tales Family Edition Case Study)

From analyzing the top 10 longest-running Tales ads:

**Hook Evolution:**
- Early ads (June, 138 days running): Product shots, 1 overlay each
- Later ads (August, 76 days running): Direct testimonials, 6-21 overlays

**Hook Patterns:**
- 90% use problem-solution variants
- Common pain points: "sick of gossip", "dreading reunions", "getting interrogated"
- POV format used in 20% of ads

**Text Overlay Strategy:**
- June ads: Single overlay matching voiceover exactly
- August ads: Dynamic word-by-word text emphasis
- Average: 5.9 overlays per video (range 1-21)

**Messaging Consistency:**
- Core problem: Family gatherings dominated by gossip/interrogation
- Solution: 150 conversation questions
- Benefit: Turn toxic/boring time into meaningful connections

### File Locations for Video Analysis

- **Analysis Scripts:** `/tmp/analyze_facebook_ads.py`
- **Hook Extraction:** `/tmp/extract_hooks_and_overlays.py`
- **Report Generation:** `/tmp/generate_summary_report.py`
- **URL Extraction:** `/tmp/extract_video_urls.py`
- **Video Download:** `/tmp/download_facebook_videos.py`

## Next Steps

1. **Bulk Import Scripts** - Create scripts for bulk page/keyword scraping
2. **Scheduled Scraping** - Set up cron jobs for regular ad monitoring
3. **Creative Analysis** - Build tools to analyze ad creative patterns
4. **Spend Tracking** - Track spend changes over time
5. **Competitive Dashboards** - Build dashboards comparing competitor ad strategies
6. **Export Utilities** - Create CSV/JSON export tools for ad data
7. **Automated Video Analysis** - Integrate Gemini 2.5 analysis into scraping pipeline
8. **Hook Pattern Database** - Build database of successful hook patterns by industry

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
