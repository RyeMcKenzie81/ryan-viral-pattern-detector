# Ryan's Viral Pattern Detector

A comprehensive CLI tool for scraping Instagram posts, analyzing viral patterns, and exporting data for review and content creation.

## Features

- **Instagram Scraping**: Uses Apify's Instagram scraper to collect posts from specified accounts
- **Statistical Analysis**: Computes per-account statistics with trimmed mean and standard deviation
- **Outlier Detection**: Flags posts that exceed configurable standard deviation thresholds
- **Multiple Export Formats**: CSV for video downloads, VA review, and JSONL for AI batch analysis
- **Review Workflow**: Import/export system for human review and content decisions
- **Video Management**: Optional video upload to Supabase Storage
- **Railway Deployment**: Ready for cloud deployment with manual execution

## Prerequisites

- Python 3.11 or higher
- [Supabase](https://supabase.com) project
- [Apify](https://apify.com) account with API token
- Access to `apify/instagram-scraper` actor

## Installation

1. **Clone the repository:**
   ```bash
   git clone <repository-url>
   cd ryan-viral-pattern-detector
   ```

2. **Install dependencies:**
   ```bash
   pip install -r requirements.txt
   ```

3. **Set up environment:**
   ```bash
   cp .env.example .env
   # Edit .env with your configuration
   ```

## Supabase Setup

1. **Create a new Supabase project** at [supabase.com](https://supabase.com)

2. **Run the schema setup:**
   ```sql
   -- Copy and execute the contents of sql/schema.sql in your Supabase SQL editor
   ```

3. **Get your credentials:**
   - Project URL: `https://YOUR-PROJECT.supabase.co`
   - Service role key: Found in Settings > API

4. **Configure Supabase Storage (optional for video uploads):**
   - Create a bucket named `videos`
   - Set it to public if you want direct video access

## Apify Setup

1. **Create an Apify account** at [apify.com](https://apify.com)

2. **Get your API token:**
   - Go to Settings > Integrations
   - Copy your API token

3. **Ensure access to `apify/instagram-scraper`:**
   - This is the official Apify Instagram scraper
   - Should be available to all accounts

## Configuration

Edit your `.env` file with the following:

```bash
# Apify Configuration
APIFY_TOKEN=your_apify_token_here
APIFY_ACTOR_ID=apify/instagram-scraper

# Supabase Configuration
SUPABASE_URL=https://your-project.supabase.co
SUPABASE_SERVICE_KEY=your_service_key_here

# Scraping Parameters
DAYS_BACK=120                    # How many days back to scrape
CONCURRENCY=5                    # Concurrent requests (be careful with rate limits)
POST_TYPE=reels                  # Options: all, posts, reels, tagged

# Analysis Parameters
OUTLIER_SD_THRESHOLD=3.0         # Standard deviations for outlier detection

# Export Configuration
EXPORT_DIR=./exports             # Where to save export files

# Performance Settings
MAX_USERNAMES_PER_RUN=100        # Maximum usernames per scrape
MAX_POSTS_PER_ACCOUNT=10000      # Maximum posts per account
CHUNK_SIZE_FOR_DB_OPS=1000       # Database batch size
APIFY_TIMEOUT_SECONDS=300        # Apify run timeout
```

## Usage

### 1. Prepare Username List

Create a `usernames.csv` file with Instagram usernames:

```csv
username
natgeo
nasa
bbcnews
```

### 2. Scrape Instagram Data

```bash
# Basic scraping (uses .env defaults)
python ryan_vpd.py scrape

# Custom parameters
python ryan_vpd.py scrape --usernames ./usernames.csv --days 90 --post-type reels

# All available options
python ryan_vpd.py scrape --usernames ./custom_users.csv --days 120 --concurrency 3 --post-type all
```

### 3. Analyze and Flag Outliers

```bash
# Use default threshold (3.0 SD)
python ryan_vpd.py analyze

# Custom threshold
python ryan_vpd.py analyze --sd-threshold 2.5
```

### 4. Export Data

```bash
# Export all formats
python ryan_vpd.py export

# Export specific formats
python ryan_vpd.py export --format outliers,review

# Custom threshold for exports
python ryan_vpd.py export --format outliers --sd-threshold 2.0
```

This creates three files in the exports directory:
- `outliers_to_download_YYYY-MM-DD.csv` - URLs for video downloading
- `review_export_YYYY-MM-DD.csv` - Complete dataset for VA review
- `ai_batch_YYYY-MM-DD.jsonl` - JSON Lines format for AI analysis

### 5. Download Videos (Optional)

Use the outliers CSV with a tool like yt-dlp:

```bash
# Extract URLs from CSV
cut -d',' -f1 exports/outliers_to_download_2024-01-15.csv | tail -n +2 > urls.txt

# Download with yt-dlp
yt-dlp -o "downloads/%(uploader)s_%(id)s.%(ext)s" -a urls.txt
```

### 6. Upload Videos to Supabase (Optional)

```bash
python ryan_vpd.py upload-videos --from ./downloads
```

### 7. Import Review Decisions

After VA team edits the review CSV:

```bash
python ryan_vpd.py import-review --path ./exports/review_export_EDITED.csv
```

## Complete Workflow Example

```bash
# 1. Scrape reels from last 120 days
python ryan_vpd.py scrape --usernames ./usernames.csv --days 120 --post-type reels

# 2. Analyze with strict threshold
python ryan_vpd.py analyze --sd-threshold 3.5

# 3. Export for processing
python ryan_vpd.py export --format outliers,review,ai --sd-threshold 3.5

# 4. Download videos (external tool)
cut -d',' -f1 exports/outliers_to_download_2024-01-15.csv | tail -n +2 > urls.txt
yt-dlp -o "downloads/%(uploader)s_%(id)s.%(ext)s" -a urls.txt

# 5. Upload to Supabase
python ryan_vpd.py upload-videos --from ./downloads

# 6. After VA review, import decisions
python ryan_vpd.py import-review --path ./exports/review_export_EDITED.csv
```

## Makefile Commands

Use the included Makefile for convenience:

```bash
# Install dependencies
make install

# Run complete pipeline
make full-pipeline

# Individual steps
make scrape
make analyze
make export
make import-review REVIEW_PATH=path/to/edited.csv
make upload-videos

# Utility commands
make test           # Test CLI is working
make clean          # Clean data directories
make setup-env      # Copy .env.example to .env
```

## Railway Deployment

1. **Connect Repository:**
   - Connect your GitHub repository to Railway
   - Railway will automatically detect the Dockerfile

2. **Set Environment Variables:**
   - Add all environment variables from your `.env` file
   - Use the Railway dashboard Variables section

3. **Manual Execution:**
   - Use Railway's Run tab for manual command execution
   - No automatic scheduling - all runs are manual

4. **Example Railway Commands:**
   ```bash
   # Scrape new data
   python ryan_vpd.py scrape --usernames usernames.csv --days $DAYS_BACK --post-type reels

   # Analyze with custom threshold
   python ryan_vpd.py analyze --sd-threshold 2.5

   # Export all formats
   python ryan_vpd.py export --format outliers,review,ai --sd-threshold 2.5
   ```

## Data Validation

The tool includes comprehensive validation:

- **Views**: Integer ≥ 0, falls back to likes if missing
- **Likes/Comments**: Integer ≥ 0, defaults to 0
- **Posted Date**: Valid ISO timestamp or NULL
- **Length**: 1-3600 seconds, NULL allowed
- **Caption**: Max 2200 characters, HTML escaped
- **Reject Reason**: Must be one of: IRR, NSFW, LEN, AUD, CELEB, OTH
- **Post URL**: Valid Instagram URL format
- **Username**: Alphanumeric, underscore, period only

## Error Handling

- **Apify Timeouts**: 3 retries with exponential backoff
- **Invalid Usernames**: Warning logged, processing continues
- **Database Conflicts**: Upsert strategy, updates metrics if newer
- **Missing Views**: Uses likes as fallback
- **Malformed Data**: Row skipped with warning
- **Rate Limits**: Automatic delays and respect for API limits
- **Network Errors**: Retry logic with tenacity library

## Performance Tuning

Default settings are conservative. Adjust for your needs:

```bash
# Increase concurrency (watch rate limits)
CONCURRENCY=10

# Larger database batches
CHUNK_SIZE_FOR_DB_OPS=2000

# More usernames per run
MAX_USERNAMES_PER_RUN=200

# Longer timeout for large accounts
APIFY_TIMEOUT_SECONDS=600
```

## Database Schema

### accounts
- `id` (UUID, PK)
- `handle` (TEXT, unique)
- `created_at` (TIMESTAMPTZ)

### posts
- `id` (UUID, PK)
- `account_id` (UUID, FK to accounts)
- `post_url` (TEXT, unique)
- `post_id` (TEXT) - Instagram shortcode
- `posted_at` (TIMESTAMPTZ)
- `views`, `likes`, `comments` (BIGINT)
- `caption` (TEXT)
- `length_sec` (INT)
- `created_at`, `updated_at` (TIMESTAMPTZ)

### post_review
- `post_id` (UUID, PK, FK to posts)
- `outlier` (BOOLEAN) - Set by analyze command
- `keep` (BOOLEAN) - Set by import-review
- `reject_reason` (TEXT) - Set by import-review
- `reject_notes` (TEXT) - Set by import-review
- `video_file_url` (TEXT) - Set by upload-videos
- Human/AI review fields (hook_style, tone, etc.)
- `updated_at` (TIMESTAMPTZ)

### account_summaries
- `account_id` (UUID, PK, FK to accounts)
- `n_posts` (INT)
- `p10_views`, `p90_views` (NUMERIC)
- `trimmed_mean_views`, `trimmed_sd_views` (NUMERIC)
- `last_updated` (TIMESTAMPTZ)

## Troubleshooting

### Common Issues

1. **"Missing APIFY_TOKEN"**
   - Check your `.env` file
   - Ensure the token is valid and has proper permissions

2. **"Supabase connection failed"**
   - Verify SUPABASE_URL and SUPABASE_SERVICE_KEY
   - Check if the database schema is properly set up

3. **"No data returned from Apify"**
   - Instagram usernames might be private or invalid
   - Check if the time range has any posts
   - Verify the actor has proper permissions

4. **"Apify run timeout"**
   - Increase APIFY_TIMEOUT_SECONDS
   - Reduce the number of usernames per run
   - Check Apify actor status

5. **"Database constraint violations"**
   - Usually related to duplicate post URLs
   - The tool handles this automatically with upserts

### Logging

All operations are logged with timestamps:
- `INFO`: Normal operations and progress
- `WARNING`: Recoverable issues (invalid data, missing fields)
- `ERROR`: Failures requiring attention

### Testing

Use the test data for validation:

```bash
# Test with sample data
python ryan_vpd.py scrape --usernames test_data/sample_usernames.csv --days 30

# Verify against expected outputs
diff exports/outliers_to_download_2024-01-15.csv test_data/expected_outputs/expected_outliers.csv
```

## Data Privacy

- **Local Processing**: All data processing happens locally or in your cloud environment
- **No Data Sharing**: Raw Instagram data is not shared with third parties
- **Compliance**: Follow Instagram's Terms of Service and applicable data protection laws
- **Retention**: Implement appropriate data retention policies for your use case

## Support

For issues and feature requests, please check:
1. This README for common solutions
2. Environment variable configuration
3. Database schema setup
4. Apify actor permissions

## License

This project is for internal use. Ensure compliance with Instagram's Terms of Service and applicable data protection regulations.