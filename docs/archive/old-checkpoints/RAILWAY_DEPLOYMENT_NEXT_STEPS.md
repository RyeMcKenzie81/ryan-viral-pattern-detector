# Railway Deployment - Next Steps

## Phase 2: ✅ COMPLETE (Just Completed)

We've built the web dashboard infrastructure:

### Files Created:
1. ✅ `viraltracker/web/__init__.py` - Package initialization
2. ✅ `viraltracker/web/app.py` - FastAPI application with routes
3. ✅ `viraltracker/web/templates/dashboard.html` - Bootstrap dashboard UI
4. ✅ `viraltracker/storage.py` - Supabase storage helper functions
5. ✅ `run_daily_scrape_with_logging.py` - Python wrapper with Supabase logging

### Files Modified:
1. ✅ `railway.toml` - Updated to use Python wrapper (`python run_daily_scrape_with_logging.py`)

### Features Implemented:
- Dashboard showing last 30 cron runs
- CSV download for each run
- Log viewing with syntax highlighting
- Next scheduled run display
- Auto-refresh when jobs are running
- Health check endpoint
- Supabase integration for logging and storage

---

## Phase 3: Supabase Setup (⏳ TODO - 15 minutes)

Before deploying to Railway, you need to set up Supabase:

### Step 1: Create Supabase Table

Go to your Supabase dashboard (https://supabase.com/dashboard) and run this SQL:

```sql
-- Create cron_runs table
CREATE TABLE cron_runs (
  id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
  run_date DATE NOT NULL,
  started_at TIMESTAMP NOT NULL,
  completed_at TIMESTAMP,
  status TEXT NOT NULL,
  total_tweets INT,
  green_tweets INT,
  green_percentage DECIMAL(5,2),
  keywords_scraped INT,
  log_output TEXT,
  csv_storage_path TEXT,
  error_message TEXT,
  created_at TIMESTAMP DEFAULT NOW()
);

-- Create index for faster queries
CREATE INDEX idx_cron_runs_run_date ON cron_runs(run_date DESC);
CREATE INDEX idx_cron_runs_status ON cron_runs(status);
```

### Step 2: Create Supabase Storage Bucket

1. Go to **Storage** in Supabase dashboard
2. Click **New Bucket**
3. Name: `cron-outputs`
4. **Public bucket**: ✅ Yes (enable)
5. Click **Create bucket**

### Step 3: Test Locally (Optional)

Test the setup locally before deploying:

```bash
# Make sure environment variables are set in .env
source venv/bin/activate

# Test the web dashboard
uvicorn viraltracker.web.app:app --reload

# Visit http://localhost:8000
```

---

## Phase 4: Railway Deployment (⏳ TODO - 15 minutes)

### Step 1: Push to GitHub

```bash
git add .
git commit -m "Add Railway deployment with web dashboard

- FastAPI dashboard for monitoring cron runs
- Supabase integration for logging and CSV storage
- Python wrapper for cron execution
- Bootstrap UI with auto-refresh
- CSV download and log viewing"

git push origin feature/comment-finder-v1
```

### Step 2: Create Railway Project

1. Go to https://railway.app
2. Click **New Project**
3. Select **Deploy from GitHub repo**
4. Choose your `viraltracker` repository
5. Railway will detect `railway.toml` automatically

### Step 3: Configure Environment Variables

In Railway dashboard, add these environment variables:

```
SUPABASE_URL=https://your-project.supabase.co
SUPABASE_KEY=your_anon_key_here
APIFY_API_TOKEN=apify_api_your_token_here
GOOGLE_API_KEY=your_google_api_key_here
GEMINI_API_KEY=your_gemini_api_key_here
```

**Where to find these:**
- **SUPABASE_URL** & **SUPABASE_KEY**: Supabase dashboard → Settings → API
- **APIFY_API_TOKEN**: Apify dashboard → Settings → Integrations
- **GOOGLE_API_KEY**: Google Cloud Console → APIs & Services → Credentials
- **GEMINI_API_KEY**: Google AI Studio → Get API Key

### Step 4: Deploy

Railway will automatically deploy both services:

1. **Cron service**: Runs Mon-Fri at 6 AM EST (11:00 UTC)
2. **Web service**: Accessible at `https://your-project.up.railway.app`

### Step 5: Verify Deployment

1. Visit the web dashboard URL
2. Check that environment variables are set correctly
3. View Railway logs for any errors
4. Wait for first scheduled run or manually trigger for testing

---

## Architecture Overview

```
Railway Project
├── Service 1: Cron Job
│   ├── Schedule: Mon-Fri 6 AM EST (11:00 UTC)
│   ├── Command: python run_daily_scrape_with_logging.py
│   ├── Process:
│   │   1. Log run start to Supabase
│   │   2. Execute scrape_all_keywords_24h.sh
│   │   3. Parse results
│   │   4. Upload CSV to Supabase Storage
│   │   5. Update run record with metrics
│   └── Duration: ~45-60 minutes
│
└── Service 2: Web Dashboard
    ├── URL: https://your-project.up.railway.app
    ├── Framework: FastAPI + Uvicorn
    ├── Routes:
    │   - GET /              → Dashboard (last 30 runs)
    │   - GET /runs/{id}/download → Download CSV
    │   - GET /runs/{id}/logs     → View logs
    │   - GET /health            → Health check
    └── Features:
        - Real-time status
        - Next run countdown
        - Success rate tracking
        - CSV downloads
        - Log viewer
        - Auto-refresh for running jobs
```

---

## Cost Estimate

**Railway**: ~$5/month
- Cron service: ~$2/month (runs 1 hour/day, Mon-Fri)
- Web service: ~$3/month (always on, minimal resources)

**Total**: ~$5/month

---

## File Structure After Phase 2

```
viraltracker/
├── viraltracker/
│   ├── web/
│   │   ├── __init__.py          ← Web package
│   │   ├── app.py              ← FastAPI application
│   │   └── templates/
│   │       └── dashboard.html  ← Bootstrap UI
│   ├── storage.py              ← Supabase helpers
│   └── ... (existing files)
├── run_daily_scrape_with_logging.py  ← Cron wrapper
├── scrape_all_keywords_24h.sh        ← Scrape script
├── railway.toml                      ← Railway config
├── requirements.txt                  ← Updated with FastAPI
└── .env.example                      ← Environment variables doc
```

---

## Testing Checklist

Before deploying to production:

- [ ] Supabase table created
- [ ] Supabase storage bucket created (public)
- [ ] Environment variables documented in `.env.example`
- [ ] All files committed to git
- [ ] Pushed to GitHub
- [ ] Railway project created
- [ ] Environment variables set in Railway
- [ ] Web dashboard loads successfully
- [ ] Cron schedule is correct (Mon-Fri 6 AM EST)
- [ ] First manual test run completes successfully

---

## Troubleshooting

### Web dashboard shows "Error loading dashboard"
- Check SUPABASE_URL and SUPABASE_KEY environment variables
- Verify Supabase table exists
- Check Railway logs for Python errors

### Cron job fails to start
- Check all environment variables are set
- Verify `scrape_all_keywords_24h.sh` is executable
- Check Railway logs for error messages

### CSV download fails
- Verify Supabase storage bucket is public
- Check csv_storage_path in database
- Verify file was uploaded successfully

### Logs not appearing
- Check log_output field in database
- Verify Python wrapper is capturing stdout/stderr
- Check Railway cron execution logs

---

## Next Session Goals

1. ✅ Create Supabase table (SQL above)
2. ✅ Create Supabase storage bucket
3. ✅ Test locally (optional)
4. ✅ Push to GitHub
5. ✅ Deploy to Railway
6. ✅ Configure environment variables
7. ✅ Verify first run

**Estimated time**: 30 minutes total

---

**Created**: October 29, 2025
**Phase 2 Completion**: Railway implementation ready for deployment
**Status**: Ready for Supabase setup and deployment
