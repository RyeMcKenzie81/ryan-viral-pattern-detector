# ViralTracker CLI Guide

Complete command-line reference for the ViralTracker unified CLI tool (`./vt`).

---

## Table of Contents

- [Installation](#installation)
- [TikTok Commands](#tiktok-commands)
- [Instagram Commands](#instagram-commands)
- [YouTube Shorts Commands](#youtube-shorts-commands)
- [Video Processing](#video-processing)
- [AI Analysis](#ai-analysis)
- [Project Management](#project-management)
- [Export & Analysis](#export--analysis)

---

## Installation

```bash
# Clone repository
git clone https://github.com/yourusername/viraltracker.git
cd viraltracker

# Setup virtual environment
python3 -m venv venv
source venv/bin/activate

# Install dependencies
pip install -r requirements.txt

# Configure environment variables
cp .env.example .env
# Edit .env with your API keys
```

**Required Environment Variables:**
```bash
SUPABASE_URL=https://your-project.supabase.co
SUPABASE_SERVICE_KEY=your-service-key
GOOGLE_GEMINI_API_KEY=your-gemini-key
APIFY_API_TOKEN=your-apify-token
CLOCKWORKS_API_KEY=your-clockworks-key
```

---

## TikTok Commands

### Search by Keyword

Scrape TikTok videos by search query using Clockworks API.

```bash
./vt tiktok search "dog training" \
  --count 200 \
  --max-days 10 \
  --max-followers 10000 \
  --min-views 500 \
  --project wonder-paws-tiktok \
  --save
```

**Options:**
- `--count` - Number of videos to scrape (default: 50)
- `--max-days` - Only videos posted in last N days
- `--max-followers` - Filter accounts with ≤ N followers
- `--min-views` - Only videos with ≥ N views
- `--project` - Project slug to link videos
- `--save` - Save to database immediately
- `--dry-run` - Preview without saving

**Example - Multiple Keywords:**
```bash
# Scrape multiple related terms
./vt tiktok search "puppy training" --count 250 --project my-project --save
./vt tiktok search "dog tips" --count 250 --project my-project --save
./vt tiktok search "dog care" --count 250 --project my-project --save
```

**Output:**
- Saves to `posts` table with platform_id for TikTok
- Links to project via `project_posts` table
- Captures: views, likes, comments, posted_at, account info

### Search by Hashtag

```bash
./vt tiktok hashtag "dogtok" \
  --count 100 \
  --project my-project \
  --save
```

### Scrape Trending

```bash
./vt tiktok trending \
  --count 50 \
  --region US \
  --save
```

**Regions:** US, GB, CA, AU, etc.

---

## Instagram Commands

### Scrape Account

Scrape Instagram Reels from a specific account.

```bash
./vt instagram account "natgeo" \
  --count 50 \
  --project my-project \
  --save
```

**Options:**
- `--count` - Number of reels to scrape (default: 30)
- `--project` - Project slug to link videos
- `--save` - Save to database immediately
- `--reels-only` - Only scrape Reels (skip regular posts)

### Scrape Multiple Accounts

```bash
./vt instagram accounts accounts.txt \
  --count 30 \
  --project my-project \
  --save
```

**Format of `accounts.txt`:**
```
natgeo
dogsofinstagram
puppylove
goldendoodle
```

---

## YouTube Shorts Commands

### Search by Keyword

```bash
./vt youtube search "dog training shorts" \
  --count 100 \
  --max-days 30 \
  --min-views 1000 \
  --project my-project \
  --save
```

**Options:**
- `--count` - Number of shorts to scrape (default: 50)
- `--max-days` - Only videos posted in last N days
- `--min-views` - Only videos with ≥ N views
- `--max-duration` - Max video length in seconds (default: 60)
- `--project` - Project slug to link videos
- `--save` - Save to database immediately

### Scrape Channel

```bash
./vt youtube channel "UCxxxxxx" \
  --count 50 \
  --project my-project \
  --save
```

---

## Video Processing

After scraping, videos need to be downloaded and processed to extract metrics.

### Process All Videos in Project

```bash
./vt process videos --project wonder-paws-tiktok
```

**What it does:**
1. Downloads videos via `yt-dlp`
2. Uploads to Supabase Storage
3. Extracts video metrics:
   - Duration, resolution, FPS
   - Scene detection and cuts
   - Audio transcription (Whisper)
   - Face detection, motion analysis
4. Updates `video_processing` table

### Process Specific Videos

```bash
# By video IDs
./vt process videos --video-ids 123,456,789

# Process unprocessed videos only
./vt process videos --project my-project --unprocessed-only
```

### Force Reprocess

```bash
./vt process videos --project my-project --force
```

### Options

- `--project` - Process all videos in project
- `--video-ids` - Comma-separated list of video IDs
- `--unprocessed-only` - Skip already processed videos
- `--force` - Reprocess already processed videos
- `--skip-download` - Skip download if video already exists
- `--parallel` - Number of parallel workers (default: 4)

### Processing Output

Results stored in `video_processing` table:
```json
{
  "duration_sec": 15.3,
  "resolution": "1080x1920",
  "fps": 30,
  "file_size_mb": 12.5,
  "scene_cuts": [2.1, 5.3, 8.7, 12.1],
  "transcription": [
    {"start": 0.0, "end": 2.1, "text": "Hey everyone!"},
    ...
  ],
  "visual_metrics": {
    "face_pct_avg": 45.2,
    "motion_intensity_avg": 0.65
  }
}
```

---

## AI Analysis

### Hook Intelligence Analysis

Analyze videos with Google Gemini to extract hook intelligence features.

```bash
./vt analyze videos \
  --project wonder-paws-tiktok \
  --gemini-model models/gemini-2.5-pro
```

**Models:**
- `models/gemini-2.5-pro` - Best quality (recommended)
- `models/gemini-2.5-flash` - Faster, cheaper

### Options

```bash
# Analyze only unanalyzed videos
./vt analyze videos --project my-project --unanalyzed-only

# Analyze specific videos
./vt analyze videos --video-ids 123,456,789

# Dry run (no database save)
./vt analyze videos --project my-project --dry-run

# Custom temperature
./vt analyze videos --project my-project --temperature 0.2
```

### What Gets Analyzed

**Hook Intelligence v1.2.0 extracts:**

1. **14 Hook Type Probabilities (0-1 scale):**
   - `result_first` - Shows outcome immediately
   - `shock_violation` - Unexpected/shocking content
   - `reveal_transform` - Before/after transformation
   - `relatable_slice` - Everyday relatable moment
   - `humor_gag` - Comedy/funny setup
   - `tension_wait` - Build suspense
   - `direct_callout` - Addresses viewer directly
   - `challenge_stakes` - Competition/dare
   - `authority_flex` - Credibility display
   - `social_proof` - Popularity indicator
   - `open_question` - Poses a question
   - `demo_novelty` - Shows something new
   - `confession_secret` - Personal revelation
   - `contradiction_mythbust` - Challenges belief

2. **Temporal Features:**
   - `hook_span` - Start/end time of hook
   - `payoff_time_sec` - Time until payoff

3. **Modality Attribution:**
   - Audio contribution (0-1)
   - Visual contribution (0-1)
   - Overlay text contribution (0-1)

4. **Windowed Metrics (1s, 2s, 3s, 5s windows):**
   - `face_pct` - Face presence percentage
   - `cuts` - Number of cuts
   - `motion_intensity` - Movement score
   - `overlay_chars_per_sec` - Text density
   - `words_per_sec` - Speech rate

5. **Risk Flags:**
   - `violence_risk`
   - `brand_logo_risk`
   - `minors_present_risk`
   - `medical_sensitive_risk`
   - `suggestive_visual_risk`

### Output Format

Results stored in `video_analysis` table with `hook_features` JSONB column:

```json
{
  "hook_type_probs": {
    "relatable_slice": 0.8,
    "humor_gag": 0.6,
    "shock_violation": 0.2
  },
  "payoff_time_sec": 2.3,
  "hook_span": {"t_start": 0.0, "t_end": 4.5},
  "hook_windows": {
    "w1_0_1s": {
      "face_pct": 45.2,
      "cuts": 0,
      "overlay_chars_per_sec": 0.0
    }
  },
  "hook_modality_attribution": {
    "audio": 0.7,
    "visual": 0.3,
    "overlay": 0.0
  },
  "hook_risk_flags": {
    "violence_risk": false,
    "brand_logo_risk": false
  }
}
```

---

## Project Management

### Create Project

```bash
./vt project create \
  --name "Wonder Paws TikTok Research" \
  --slug "wonder-paws-tiktok" \
  --brand-id <uuid> \
  --description "Dog training content analysis"
```

### List Projects

```bash
./vt project list

# With details
./vt project list --verbose
```

### View Project Stats

```bash
./vt project stats --project wonder-paws-tiktok
```

**Output:**
- Total videos scraped
- Videos processed (%)
- Videos analyzed (%)
- Date range
- Platform breakdown
- Top performing videos

### Link Videos to Project

```bash
# Link specific videos
./vt project link-videos \
  --project wonder-paws-tiktok \
  --video-ids 123,456,789

# Link all from search
./vt project link-videos \
  --project my-project \
  --from-search "dog training" \
  --platform tiktok
```

---

## Export & Analysis

### Export Data to CSV

Export hook intelligence data for statistical analysis:

```bash
python export_hook_analysis_csv.py
```

**Output:** `data/hook_intelligence_export.csv`

**Columns exported:**
- Post metadata: `post_id`, `account_id`, `posted_at`
- Performance: `views`, `likes`, `comments`, `engagement_rate`
- Account: `followers`
- Timing: `hours_since_post`
- Hook probabilities: All 14 hook types
- Continuous features: `payoff_time_sec`, `face_pct_1s`, `cuts_in_2s`, `overlay_chars_per_sec_2s`

### Run Statistical Analysis

```bash
python -m analysis.run_hook_analysis \
  --csv data/hook_intelligence_export.csv \
  --outdir results \
  --beta 0.20
```

**Options:**
- `--csv` - Path to exported CSV
- `--outdir` - Output directory
- `--beta` - Time decay parameter (default: 0.20)

**Outputs:**
- `results/playbook.md` - Human-readable summary
- `results/univariate.csv` - Feature correlations
- `results/interactions.csv` - Synergy effects
- `results/buckets.csv` - Editor-friendly rules
- `results/pairwise_weights.csv` - Ranking model (if sufficient data)

### Simple Correlation Analysis

```bash
# Full hook intelligence correlations
python analyze_hook_intelligence_correlations.py

# Views-focused analysis
python analyze_views_correlations.py
```

---

## Advanced Usage

### Batch Processing Pipeline

Complete pipeline for new dataset:

```bash
# 1. Scrape multiple keywords
for keyword in "dog training" "puppy tips" "dog care"; do
  ./vt tiktok search "$keyword" --count 200 --project my-project --save
done

# 2. Process all videos
./vt process videos --project my-project

# 3. Analyze with AI
./vt analyze videos --project my-project --gemini-model models/gemini-2.5-pro

# 4. Export and analyze
python export_hook_analysis_csv.py
python -m analysis.run_hook_analysis --csv data/hook_intelligence_export.csv --outdir results

# 5. Review results
cat results/playbook.md
```

### Monitoring Background Jobs

Check status of long-running processes:

```bash
# In Claude Code, use:
/bashes

# Or check logs
tail -f /tmp/video_processing.log
tail -f /tmp/video_analysis.log
```

### Database Queries

Direct database access for custom queries:

```bash
# Python
python -c "
from viraltracker.core.database import get_supabase_client
supabase = get_supabase_client()

# Get top performing videos
result = supabase.table('posts')\
    .select('*')\
    .order('views', desc=True)\
    .limit(10)\
    .execute()

for post in result.data:
    print(f\"{post['post_id']}: {post['views']} views\")
"
```

---

## Troubleshooting

### Common Issues

**Video Download Failures:**
```bash
# Update yt-dlp
pip install -U yt-dlp

# Test manually
yt-dlp "https://www.tiktok.com/@user/video/123"
```

**Analysis Hanging:**
```bash
# Check Gemini API key
echo $GOOGLE_GEMINI_API_KEY

# Test connection
python test_gemini_basic.py

# Use flash model (faster)
./vt analyze videos --project my-project --gemini-model models/gemini-2.5-flash
```

**Missing Hook Features:**
```bash
# Verify videos are processed first
./vt project stats --project my-project

# Check processing status
python verify_analysis_completion.py

# Reprocess if needed
./vt process videos --project my-project --force
```

**Storage Full:**
```bash
# Check Supabase storage usage
# Delete old videos if needed (keep metadata)

# Or use local storage only
./vt process videos --project my-project --skip-upload
```

---

## Performance Tips

1. **Parallel Processing:**
```bash
./vt process videos --project my-project --parallel 8
```

2. **Use Flash Model for Speed:**
```bash
./vt analyze videos --project my-project --gemini-model models/gemini-2.5-flash
```

3. **Process in Batches:**
```bash
# Get video IDs
./vt project list-videos --project my-project > video_ids.txt

# Process in chunks
split -l 100 video_ids.txt batch_
for batch in batch_*; do
  ./vt process videos --video-ids $(cat $batch | tr '\n' ',')
done
```

4. **Filter Before Processing:**
```bash
# Only process videos with high views
./vt process videos --project my-project --min-views 10000
```

---

## Best Practices

1. **Always link to projects** - Use `--project` flag for organization
2. **Process before analyzing** - Videos must be processed before AI analysis
3. **Use consistent parameters** - Keep thresholds consistent across scraping sessions
4. **Monitor costs** - Gemini API usage adds up, use flash model when possible
5. **Backup regularly** - Export CSVs periodically for analysis
6. **Check analysis completion** - Run `verify_analysis_completion.py` before exporting

---

## Next Steps

- See [HOOK_ANALYSIS_GUIDE.md](HOOK_ANALYSIS_GUIDE.md) for detailed analysis methods
- See [API_REFERENCE.md](API_REFERENCE.md) for Python API usage
- See main [README.md](../README.md) for architecture overview
