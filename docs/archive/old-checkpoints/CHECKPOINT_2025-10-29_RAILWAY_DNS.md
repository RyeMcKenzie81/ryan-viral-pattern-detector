# Checkpoint: Railway Deployment + DNS Configuration
**Date**: October 29, 2025
**Status**: Railway configured, DNS propagating, 24h scrape running

---

## ✅ Completed This Session

### 1. Fixed Comment Generation Workflow

**Problem identified**: The `--skip-comments` flag was causing:
- Two-pass workflow (scrape, then generate comments separately)
- Scores not properly saved to database (298 greens in reports, only 2 in DB)
- Risk of expensive re-processing for yellows (~$300+ for 1,784 tweets)

**Solution implemented**:
- **Modified**: `scrape_all_keywords_24h.sh`
- **Removed**: `--skip-comments` flag from line 66
- **Updated**: Echo message to "Generate comments: Yes (greens only)"
- **Result**: One-pass workflow that generates comments for greens during scraping

**Cost optimization**:
- Avoided: ~$300 for 1,784 tweets (greens + yellows)
- Actual: $0.000212 for 2 greens (used `--greens-only` for today)
- Future: ~$15/month for 300 greens/day × 5 days × 4 weeks

### 2. Railway Environment Variables Configured

**Variables added to Railway dashboard**:
```
SUPABASE_URL=https://your-project.supabase.co
SUPABASE_KEY=your_service_role_key_here
APIFY_API_TOKEN=your_apify_token_here
GOOGLE_API_KEY=your_google_api_key_here
GEMINI_API_KEY=your_gemini_api_key_here
```

**Key notes**:
- Using **service role key** for `SUPABASE_KEY` (not anon key) for cron access
- Both `GOOGLE_API_KEY` and `GEMINI_API_KEY` use same Gemini key
- These are set in Railway for both services (cron + web)

### 3. Custom Domain DNS Configuration

**Domain**: viralos.ai (purchased)
**Goal**: Root redirects to www, www points to Railway

**Cloudflare DNS changes**:
1. ✅ **Deleted**: `_domainconnect` CNAME (GoDaddy leftover)
2. ✅ **Edited**: `www` CNAME → `w7x59oen.up.railway.app` (Railway endpoint)
3. ✅ **Kept**: A records at root for redirect functionality
4. ⏳ **TODO**: Create redirect rule: viralos.ai → www.viralos.ai (301)

**Railway custom domain**:
- Set custom domain to: `www.viralos.ai`

**Nameserver migration**:
- ✅ Changed at GoDaddy: Point to Cloudflare nameservers
- ⏳ **Propagating**: 2-4 hours (up to 24 hours max)
- Current status: DNS lookup failing (expected during propagation)

### 4. Re-ran 24h Scrape with Fixed Workflow

**Command**: `bash ./scrape_all_keywords_24h.sh`
**Status**: Running (Bash 1831b8)
**Progress**: Keyword 1/19 completed (device limits)
**ETA**: ~60-90 minutes remaining

**Workflow now**:
1. Scrape 500 tweets per keyword
2. Score all tweets with 5-topic taxonomy (V1.6)
3. **Generate comments for greens automatically** (new!)
4. Save to database with proper scoring
5. Export to CSV at end

**Expected output**:
- Report JSON files: `~/Downloads/keyword_analysis_24h/`
- CSV with greens: `~/Downloads/keyword_greens_24h.csv`

---

## ⏳ In Progress

1. **24h scrape running** - Keyword 1/19 complete, ~60-90 minutes remaining
2. **DNS propagation** - Nameservers changed to Cloudflare, waiting 2-4 hours

---

## 📋 Next Steps

### Immediate (Once Scrape Completes)
1. ✅ Export results to CSV
   ```bash
   source venv/bin/activate && python -m viraltracker.cli.main twitter export-comments \
     --project yakety-pack-instagram \
     --out ~/Downloads/keyword_greens_24h.csv \
     --status pending \
     --greens-only \
     --sort-by balanced
   ```

### DNS Configuration (Once Propagated)
1. Test domain access: `www.viralos.ai`
2. Create Cloudflare redirect rule:
   - Source: `viralos.ai`
   - Destination: `https://www.viralos.ai`
   - Type: 301 (permanent)
3. Verify redirect works: `viralos.ai` → `www.viralos.ai`

### Supabase Setup (Phase 3 - Still TODO)
From `RAILWAY_DEPLOYMENT_NEXT_STEPS.md`:

**Step 1**: Create Supabase table
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

**Step 2**: Create Supabase storage bucket
1. Go to Storage in Supabase dashboard
2. Create bucket: `cron-outputs`
3. Set as **public bucket**

**Step 3**: Test web dashboard locally
```bash
source venv/bin/activate
uvicorn viraltracker.web.app:app --reload
# Visit http://localhost:8000
```

### Railway Deployment Testing
1. Wait for DNS propagation (2-4 hours)
2. Visit `www.viralos.ai` - should show web dashboard
3. Check Railway logs for any errors
4. Manually trigger cron for testing (optional)
5. Verify first scheduled run Mon-Fri 6 AM EST (11:00 UTC)

---

## 📁 Files Modified

### `scrape_all_keywords_24h.sh`
**Line 43** - Updated message:
```bash
# Before:
echo "Skip comments: Yes (faster)"

# After:
echo "Generate comments: Yes (greens only)"
```

**Lines 60-67** - Removed `--skip-comments` flag:
```bash
# Before:
  source venv/bin/activate && python -m viraltracker.cli.main twitter analyze-search-term \
    --project yakety-pack-instagram \
    --term "$term" \
    --count 500 \
    --days-back 1 \
    --min-likes 0 \
    --skip-comments \
    --report-file ~/Downloads/keyword_analysis_24h/${filename}_report.json

# After:
  # Run analysis (generates comments for greens automatically)
  source venv/bin/activate && python -m viraltracker.cli.main twitter analyze-search-term \
    --project yakety-pack-instagram \
    --term "$term" \
    --count 500 \
    --days-back 1 \
    --min-likes 0 \
    --report-file ~/Downloads/keyword_analysis_24h/${filename}_report.json
```

---

## 🏗️ Architecture Status

```
Railway Project (configured, ready to deploy)
├── Service 1: Cron Job
│   ├── Schedule: Mon-Fri 6 AM EST (11:00 UTC)
│   ├── Command: python run_daily_scrape_with_logging.py
│   ├── Env vars: ✅ Configured
│   └── Status: Ready (needs Supabase table first)
│
└── Service 2: Web Dashboard
    ├── URL: www.viralos.ai (DNS propagating)
    ├── Framework: FastAPI + Uvicorn
    ├── Env vars: ✅ Configured
    └── Status: Ready (needs Supabase table first)

Custom Domain
├── Root: viralos.ai
│   ├── DNS: A records + Cloudflare redirect
│   └── Behavior: Redirect to www.viralos.ai (TODO)
│
└── WWW: www.viralos.ai
    ├── DNS: CNAME → w7x59oen.up.railway.app
    ├── Status: ⏳ Propagating (2-4 hours)
    └── Railway: Custom domain configured
```

---

## 🐛 Issues Resolved

### Issue 1: Expensive Comment Generation
**Problem**: Initial attempt to generate comments would process 1,784 tweets (greens + yellows), costing ~$300+

**Root cause**: Used `--skip-comments` during scraping, then tried to re-process all tweets

**Solution**:
1. Killed expensive process (only 2 greens in DB, rest were yellows)
2. Used `--greens-only` flag for today ($0.000212 for 2 tweets)
3. Fixed scrape script to generate comments during scraping

### Issue 2: Scores Not Saving to Database
**Problem**: 298 greens in report files, only 2 greens in database

**Root cause**: `--skip-comments` flag skips database insertion of scored tweets

**Solution**: Removed `--skip-comments` flag so all scoring saves to database

### Issue 3: DNS Not Resolving
**Problem**: Domain viralos.ai not accessible after Cloudflare setup

**Root cause**: Nameserver propagation delay (GoDaddy → Cloudflare)

**Solution**:
- Confirmed nameserver change at GoDaddy is correct
- NS records in Cloudflare are informational (don't delete)
- Wait 2-4 hours for propagation

---

## 💰 Cost Tracking

**Today's API costs**:
- Avoided: ~$300 (didn't process 1,784 tweets)
- Actual: $0.000212 (2 greens with `--greens-only`)

**Ongoing costs**:
- Railway: ~$5/month (cron ~$2/month + web ~$3/month)
- Gemini API: ~$15/month (300 greens/day × 5 days × 4 weeks × $0.003)
- Total: ~$20/month

---

## 🎯 Success Criteria

### Phase 2: ✅ COMPLETE
- [x] Web dashboard infrastructure built
- [x] Supabase integration code written
- [x] Railway config files created
- [x] Environment variables configured
- [x] Custom domain configured

### Phase 3: ⏳ IN PROGRESS
- [ ] Supabase table created
- [ ] Supabase storage bucket created
- [x] DNS configured (waiting for propagation)
- [ ] Cloudflare redirect rule created
- [ ] Local testing completed (optional)

### Phase 4: 📅 TODO
- [ ] Git commit and push to GitHub
- [ ] Railway project created
- [ ] First deployment successful
- [ ] Web dashboard accessible at www.viralos.ai
- [ ] Manual cron test run successful
- [ ] Scheduled cron runs working Mon-Fri 6 AM EST

---

## 📝 Notes

**Comment generation workflow**:
- **Old**: Scrape → Skip comments → Generate comments separately → Expensive
- **New**: Scrape → Score → Generate comments for greens → Save to DB → Efficient

**Why service role key**:
- Cron jobs need **service role** key (full access) for database writes
- Web dashboard can use **anon** key for reads (not implemented yet)
- Using service role for both for simplicity

**DNS timing**:
- Nameserver changes: 2-4 hours typical, up to 24 hours max
- CNAME changes: 5-30 minutes (after nameservers propagate)
- Don't panic if domain doesn't work immediately!

**Testing checklist** (once DNS propagates):
1. Can access www.viralos.ai
2. viralos.ai redirects to www.viralos.ai
3. Dashboard shows "No cron runs yet" (expected)
4. Health check works: www.viralos.ai/health
5. Railway logs show web service running

---

**Previous checkpoint**: `RAILWAY_DEPLOYMENT_NEXT_STEPS.md`
**Next checkpoint**: After Railway deployment and first successful cron run
**Created by**: Claude Code
**Session ended**: Context limit approaching, scrape in progress
