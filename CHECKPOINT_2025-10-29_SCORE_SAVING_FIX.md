# Checkpoint: Score Saving Fix + Railway Ready

**Date**: October 29, 2025
**Status**: ✅ Ready for production deployment

---

## ✅ Completed This Session

### 1. Fixed Critical Bug: Score Saving with --skip-comments

**Problem**: Scores weren't being saved to database when using `--skip-comments` flag
- 298 greens in report files, only 2 greens in database
- Risk of expensive re-processing ($300+ for 1,784 tweets)
- Two-pass workflow was broken

**Solution Implemented**:

1. **New function**: `save_scores_only_to_db()` in `comment_generator.py:593-646`
   - Saves scores without generating comments
   - Uses empty string for `comment_text` (database constraint)
   - Uses existing `'add_value'` suggestion type (CHECK constraint)
   - Zero API cost

2. **New method**: `_save_scores_only()` in `search_term_analyzer.py:438-470`
   - Loops through scored tweets and saves each one
   - Called when `skip_comments=True`
   - Handles errors gracefully

3. **Updated workflow** in `search_term_analyzer.py:213-216`
   - Calls `_save_scores_only()` when skipping comments
   - Displays "Saving_Scores" progress indicator

4. **Updated scrape script**: `scrape_all_keywords_24h.sh`
   - Added `--skip-comments` flag back (line 67)
   - Updated echo messages
   - Now runs 3-step workflow

**Testing**:
- ✅ Tested with 50 tweets: 100% success rate
- ✅ All scores saved to database (50/50)
- ✅ Time: ~25 seconds
- ✅ Cost: $0.00
- ✅ No errors

**Documentation**: `WORKFLOW_FIX_SCORE_SAVING.md`

### 2. Supabase Migration Completed

**Cron Runs Table**:
```sql
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

CREATE INDEX idx_cron_runs_run_date ON cron_runs(run_date DESC);
CREATE INDEX idx_cron_runs_status ON cron_runs(status);
```

**Storage Bucket**:
- Name: `cron-outputs`
- Type: Public
- Purpose: Store daily CSV files

**Status**: ✅ Created and configured in Supabase dashboard

### 3. Railway Environment Variables Configured

**Variables set in Railway dashboard**:
```
SUPABASE_URL=https://your-project.supabase.co
SUPABASE_KEY=your_service_role_key_here
APIFY_API_TOKEN=your_apify_token_here
GOOGLE_API_KEY=your_google_api_key_here
GEMINI_API_KEY=your_gemini_api_key_here
```

**Notes**:
- Using service role key for `SUPABASE_KEY` (full access for cron jobs)
- Both `GOOGLE_API_KEY` and `GEMINI_API_KEY` use same key
- Variables configured for both services (cron + web)

### 4. Web Server Running

**Status**: ✅ Railway web dashboard is running
- URL: www.viralos.ai (DNS propagating)
- Framework: FastAPI + Uvicorn
- Features:
  - Dashboard showing last 30 cron runs
  - CSV downloads
  - Log viewing
  - Health check endpoint
  - Auto-refresh for running jobs

**Railway Configuration**:
```toml
# railway.toml
[[services]]
name = "web"
startCommand = "uvicorn viraltracker.web.app:app --host 0.0.0.0 --port $PORT"

[[services]]
name = "cron"
[[services.cron.crons]]
schedule = "0 11 * * 1-5"  # Mon-Fri 6 AM EST (11:00 UTC)
command = "python run_daily_scrape_with_logging.py"
```

---

## 📋 New 3-Step Workflow

### Step 1: Scrape & Score (45-60 minutes, $0)

```bash
bash ./scrape_all_keywords_24h.sh
```

**What happens**:
1. Scrapes 500 tweets per keyword × 19 keywords
2. Scores ALL tweets with 5-topic taxonomy (V1.6)
3. **Saves scores to database** (NEW!)
4. Skips comment generation
5. Exports report JSON files

**Output**:
- `~/Downloads/keyword_analysis_24h/*.json` (19 files)
- Scores in `generated_comments` table (empty `comment_text`)

**Cost**: $0

### Step 2: Generate Comments (15 minutes, ~$15)

Script automatically runs this after Step 1:
```bash
python -m viraltracker.cli.main twitter generate-comments \
  --project yakety-pack-instagram \
  --hours-back 24 \
  --max-candidates 10000 \
  --min-followers 10 \
  --min-likes 0 \
  --greens-only
```

**What happens**:
1. Queries database for `label = 'green'`
2. Generates 5 comment suggestions per green
3. Updates database with comments
4. Rate limited to 15 requests/min

**Expected**: ~300 greens/day × $0.003 = ~$0.90/day = ~$15/month

### Step 3: Export CSV

Script automatically runs this after Step 2:
```bash
python -m viraltracker.cli.main twitter export-comments \
  --project yakety-pack-instagram \
  --out ~/Downloads/keyword_greens_24h.csv \
  --status pending \
  --greens-only \
  --sort-by balanced
```

**Output**: `~/Downloads/keyword_greens_24h.csv`

---

## 📁 Files Modified This Session

### Core Code Changes
1. `viraltracker/generation/comment_generator.py`
   - Added `save_scores_only_to_db()` function (lines 593-646)

2. `viraltracker/analysis/search_term_analyzer.py`
   - Added import (line 31)
   - Added `_save_scores_only()` method (lines 438-470)
   - Updated workflow (lines 213-216)

3. `scrape_all_keywords_24h.sh`
   - Updated message (line 43)
   - Added `--skip-comments` flag (line 67)

### Documentation Created
4. `WORKFLOW_FIX_SCORE_SAVING.md` - Full technical documentation
5. `CHECKPOINT_2025-10-29_SCORE_SAVING_FIX.md` - This file

---

## 🏗️ Railway Architecture Status

```
Railway Project (viralos.ai)
├── Service 1: Cron Job
│   ├── Schedule: Mon-Fri 6 AM EST (11:00 UTC)
│   ├── Command: python run_daily_scrape_with_logging.py
│   ├── Workflow:
│   │   1. Scrape & Score (45-60 min, $0)
│   │   2. Generate Comments (15 min, ~$1)
│   │   3. Upload CSV to Supabase Storage
│   │   4. Log results to cron_runs table
│   ├── Env vars: ✅ Configured
│   └── Status: ⏳ Ready to deploy
│
└── Service 2: Web Dashboard
    ├── URL: www.viralos.ai (DNS propagating)
    ├── Framework: FastAPI + Uvicorn
    ├── Routes:
    │   - GET /              → Dashboard
    │   - GET /runs/{id}/download → Download CSV
    │   - GET /runs/{id}/logs     → View logs
    │   - GET /health            → Health check
    ├── Env vars: ✅ Configured
    └── Status: ✅ Running

Supabase
├── Database: ✅ Configured
│   ├── Table: cron_runs ✅
│   ├── Table: generated_comments ✅
│   └── Indexes: ✅ Created
│
└── Storage: ✅ Configured
    └── Bucket: cron-outputs (public) ✅

Custom Domain
├── Root: viralos.ai
│   ├── DNS: A records + Cloudflare redirect
│   └── Status: ⏳ Propagating (2-4 hours)
│
└── WWW: www.viralos.ai
    ├── DNS: CNAME → w7x59oen.up.railway.app
    └── Status: ⏳ Propagating
```

---

## ⏳ In Progress / Next Steps

### Immediate (This Session)
1. ✅ Document workflow fix
2. ✅ Create checkpoint
3. ⏳ Run full 24h scrape with new workflow
4. ⏳ Verify scores saved to database
5. ⏳ Generate comments for greens
6. ⏳ Export CSV

### DNS & Deployment (2-4 hours)
1. ⏳ Wait for DNS propagation
2. ⏳ Test www.viralos.ai access
3. ⏳ Create Cloudflare redirect rule (viralos.ai → www.viralos.ai)
4. ⏳ Verify health check works

### Final Deployment Steps
1. ⏳ Git commit all changes
2. ⏳ Push to GitHub
3. ⏳ Deploy to Railway
4. ⏳ Test cron job manually
5. ⏳ Verify first scheduled run Mon-Fri 6 AM EST

---

## 💰 Cost Tracking

### Today's Development
- Avoided: ~$300 (didn't process 1,784 tweets)
- Actual: $0.00 (testing with 50 tweets)

### Expected Production Costs
**Daily**:
- Scraping: $0 (Apify free tier)
- Scoring: $0 (local embeddings)
- Comments: ~$0.90 (300 greens × $0.003)

**Monthly**:
- Railway: ~$5/month (cron ~$2 + web ~$3)
- Gemini API: ~$15/month (300 greens × 5 days × 4 weeks × $0.003)
- Total: **~$20/month**

---

## 🐛 Issues Resolved This Session

### Issue 1: Scores Not Saved with --skip-comments
**Root cause**: `_score_tweets()` only calculated scores in memory, didn't save to DB

**Solution**:
- Created `save_scores_only_to_db()` function
- Integrated into workflow when `skip_comments=True`
- Now all scores save to database immediately

**Status**: ✅ FIXED

### Issue 2: Database Constraints
**Error 1**: `null value in column "comment_text" violates not-null constraint`
**Fix**: Use empty string `''` instead of NULL

**Error 2**: `violates check constraint "generated_comments_suggestion_type_check"`
**Fix**: Use existing `'add_value'` type instead of custom `'score_only'`

**Status**: ✅ FIXED

### Issue 3: DNS Not Resolving
**Root cause**: Nameserver propagation delay (GoDaddy → Cloudflare)

**Solution**:
- Confirmed nameserver change is correct
- Waiting 2-4 hours for propagation
- NS records in Cloudflare are informational (don't delete)

**Status**: ⏳ Propagating (expected)

---

## 📊 Success Criteria

### Phase 1: Workflow Fix ✅ COMPLETE
- [x] Implement score saving function
- [x] Integrate into analyzer workflow
- [x] Update scrape script
- [x] Test with real data
- [x] Document changes

### Phase 2: Railway Infrastructure ✅ COMPLETE
- [x] Web dashboard built
- [x] Supabase integration code written
- [x] Railway config files created
- [x] Environment variables configured
- [x] Custom domain configured

### Phase 3: Supabase Setup ✅ COMPLETE
- [x] Supabase table created
- [x] Supabase storage bucket created
- [x] DNS configured (waiting for propagation)
- [ ] Cloudflare redirect rule created (TODO after DNS)
- [ ] Local testing completed (optional)

### Phase 4: Deployment ⏳ TODO
- [ ] Git commit and push to GitHub
- [ ] Railway project connected to GitHub
- [ ] First deployment successful
- [ ] Web dashboard accessible at www.viralos.ai
- [ ] Manual cron test run successful
- [ ] Scheduled cron runs working Mon-Fri 6 AM EST

---

## 🎯 Current Session Goals

1. ✅ Fix score saving bug
2. ✅ Document changes
3. ✅ Create checkpoint
4. ⏳ **Run full 24h scrape** (NEXT)
5. ⏳ Verify results
6. ⏳ Prepare for deployment

---

## 📝 Notes

### Why Service Role Key
- Cron jobs need **service role** key (full access) for database writes
- Web dashboard uses same key for simplicity
- Could use **anon** key for public read operations (future optimization)

### Database Design Choice
- Score-only records use empty `comment_text` to mark them
- Easy to query: `WHERE comment_text = ''` = scores only
- Easy to query: `WHERE comment_text != ''` = has comments
- Using existing suggestion_type avoids schema changes

### Testing Strategy
- Tested with 50 tweets first (minimum allowed)
- Verified 100% success rate before full scrape
- No database errors, no API errors
- Ready for production scale (9,500 tweets)

### DNS Timing
- Nameserver changes: 2-4 hours typical, up to 24 hours max
- CNAME changes: 5-30 minutes (after nameservers propagate)
- Current status: In progress (expected)

---

**Previous checkpoint**: `CHECKPOINT_2025-10-29_RAILWAY_DNS.md`
**Next checkpoint**: After successful 24h scrape and deployment
**Created by**: Claude Code
**Session status**: In progress - about to run full scrape
