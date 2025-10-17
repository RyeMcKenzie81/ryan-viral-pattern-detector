# Tomorrow's Data Collection Plan - October 9, 2025

**Goal:** Collect 100-200 TikTok videos to run robust correlation analysis

**Current Status:** 14 videos scored, Apify scraper broken (returns empty results)

---

## Step 1: Test if Scraper is Working

```bash
# Simple test with small count
vt tiktok search "dogs" --count 10 --project wonder-paws-tiktok --save
```

**Expected:**
- ✅ Success: Returns 10 videos → Proceed to Step 2
- ❌ Failure: Returns empty results → Wait another day or contact Apify

---

## Step 2: Collect 100-200 Videos

### Search Strategy

**Broad terms (50 each):**
```bash
vt tiktok search "dogs" --count 50 --project wonder-paws-tiktok --min-views 50000 --max-days 30
vt tiktok search "dog health" --count 50 --project wonder-paws-tiktok --min-views 50000 --max-days 30
```

**Specific terms (25 each):**
```bash
vt tiktok search "dog supplements" --count 25 --project wonder-paws-tiktok --min-views 50000 --max-days 30
vt tiktok search "pet wellness" --count 25 --project wonder-paws-tiktok --min-views 50000 --max-days 30
vt tiktok search "dog nutrition" --count 25 --project wonder-paws-tiktok --min-views 50000 --max-days 30
vt tiktok search "holistic dog care" --count 25 --project wonder-paws-tiktok --min-views 50000 --max-days 30
```

**Low-view videos (for comparison):**
```bash
vt tiktok search "dogs" --count 25 --project wonder-paws-tiktok --min-views 1000 --max-days 7
```

**Total:** ~225 videos (after deduplication, expect ~150-200 unique)

### Filter Settings

**Standard searches:**
- `--min-views 50000` (lowered from 100K to get more variety)
- `--max-days 30` (expanded from 10 days to get more results)
- `--max-followers 500000` (default, includes mid-tier creators)

**Low-view comparison:**
- `--min-views 1000` (get full range for survivorship bias test)
- `--max-days 7` (keep recent)

---

## Step 3: Process Videos

### Download Videos
```bash
vt process videos --project wonder-paws-tiktok
```

**Time estimate:** ~30-60 minutes for 100-200 videos

### Analyze with Gemini
```bash
vt analyze videos --project wonder-paws-tiktok
```

**Time estimate:** ~3-5 hours for 100-200 videos (at ~2 min/video)

**Optimization:** Can run overnight if needed

---

## Step 4: Score All Videos

```bash
vt score videos --project wonder-paws-tiktok
```

**Time estimate:** ~3 minutes for 200 videos (at ~1s/video)

**Result:** 214 total scored videos (14 existing + 200 new)

---

## Step 5: Re-run Correlation Analysis

### Command:
```bash
vt score analyze --project wonder-paws-tiktok
```

This will show updated statistics with n≥100.

### For Detailed Analysis:

Create Python script: `correlation_analysis.py`

```python
from viraltracker.core.database import get_supabase_client
import pandas as pd
import numpy as np

supabase = get_supabase_client()

# Get project
project = supabase.table('projects').select('id').eq('slug', 'wonder-paws-tiktok').single().execute()
project_id = project.data['id']

# Get all scored videos
project_posts = supabase.table('project_posts').select('post_id').eq('project_id', project_id).execute()
post_ids = [row['post_id'] for row in project_posts.data]

scores = supabase.table('video_scores').select(
    '*, posts(views, likes, comments)'
).in_('post_id', post_ids).execute()

# Convert to DataFrame and run analysis
# (See PHASE_6.3_ADDENDUM.md for full analysis code)
```

---

## Step 6: Compare Results

### Key Questions to Answer:

1. **Did negative correlations persist?**
   - Algorithm score vs views
   - Shareability score vs views
   - Relatability score vs views

2. **Did hook score remain strong?**
   - r=0.737 with n=14
   - Should remain r>0.6 with n≥100 if real

3. **Did story score strengthen?**
   - r=0.523 with n=14
   - Should clarify with larger sample

4. **What new patterns emerged?**
   - Look for previously undetected weak correlations
   - Check for non-linear relationships
   - Identify view count thresholds

### Comparison Table:

| Subscore | r (n=14) | r (n≥100) | Changed? | Action |
|----------|----------|-----------|----------|--------|
| Hook → Likes | 0.737 | ??? | TBD | If still strong, increase weight |
| Story → Views | 0.523 | ??? | TBD | If still moderate, increase weight |
| Algo → Views | -0.390 | ??? | TBD | If still negative, reduce weight |
| Shareability → Views | -0.315 | ??? | TBD | If still negative, reduce weight |
| Overall → Views | 0.108 | ??? | TBD | If still weak, major redesign needed |

---

## Step 7: Adjust Scorer Weights (if warranted)

### Decision Tree:

**If negative correlations persist:**
→ Implement v1.1.0 weights (see PHASE_6.3_ADDENDUM.md)
→ Bump scorer version
→ Re-score all videos
→ Compare v1.0.0 vs v1.1.0 performance

**If negative correlations disappear:**
→ n=14 was just noise/outliers
→ Keep current weights
→ Document false alarm

**If hook/story correlations weaken:**
→ Re-examine scoring methodology
→ Look for confounding variables

**If new strong correlations emerge:**
→ Adjust weights accordingly
→ Investigate why we missed them initially

---

## Expected Timeline

### Tomorrow (October 9)

**Morning:**
- Test scraper (5 min)
- Collect videos (30 min)
- Start processing (30 min setup, then run in background)

**Afternoon:**
- Gemini analysis (3-5 hours, can run unattended)

**Evening:**
- Score all videos (3 min)
- Run correlation analysis (10 min)
- Generate report (30 min)

**Total active time:** ~2 hours
**Total wall time:** ~4-6 hours (with background processing)

---

## Troubleshooting

### If Scraper Still Broken:

**Option 1: Wait Another Day**
- TikTok API changes can take 24-48 hours for Apify to fix
- Check Apify status page: https://status.apify.com

**Option 2: Contact Apify Support**
- Email: support@scraptik.com
- Report empty search results issue
- Include run IDs from failed attempts

**Option 3: Manual URL Collection**
- Find dog wellness TikTok videos manually
- Create `urls.txt` with one URL per line
- Use: `vt import urls urls.txt --project wonder-paws-tiktok`
- (Note: Import command currently only supports Instagram, would need to add TikTok support)

### If Processing Fails:

**Check storage space:**
```bash
df -h
```

**Check Supabase storage quota:**
- Login to Supabase dashboard
- Check storage usage

**Reduce video count:**
- Process in batches of 25-50
- Monitor for failures

### If Gemini Analysis Fails:

**Check API quota:**
```bash
# View recent Gemini usage
```

**Reduce batch size:**
```bash
vt analyze videos --project wonder-paws-tiktok --limit 25
```

**Wait between batches:**
- 2-second delay between videos (already implemented)
- Increase if hitting rate limits

---

## Success Criteria

- [ ] Apify scraper working again
- [ ] 100+ videos collected
- [ ] All videos processed successfully
- [ ] All videos analyzed with Gemini
- [ ] All videos scored
- [ ] Total sample size ≥ 114 (14 existing + 100 new)
- [ ] Correlation analysis re-run
- [ ] Results documented
- [ ] Weight adjustment decision made

---

## Deliverables

1. **Updated dataset:** 114+ scored videos
2. **Correlation report:** PHASE_6.4_CORRELATION_ANALYSIS.md
3. **Weight recommendations:** Based on data, not assumptions
4. **v1.1.0 scorer:** If warranted by analysis
5. **Comparison report:** v1.0.0 vs v1.1.0 performance

---

## Context from Today

**What we learned:**
- Hook score is a strong predictor (need to confirm)
- Algorithm/shareability scoring might be backwards
- n=14 is insufficient for reliable conclusions
- Apify scraper is temporarily broken

**What we need:**
- 100-200 videos to detect moderate correlations
- Broader search terms to reduce bias
- Some low-view videos to test survivorship bias
- Working scraper (hopefully tomorrow!)

**What we'll do:**
- Validate or invalidate today's findings
- Make evidence-based weight adjustments
- Improve scorer based on what actually works

---

**Ready to execute tomorrow! 🚀**

Commands summary:
```bash
# 1. Test
vt tiktok search "dogs" --count 10 --project wonder-paws-tiktok --save

# 2. Collect (if test passes)
vt tiktok search "dogs" --count 50 --project wonder-paws-tiktok --min-views 50000 --max-days 30
vt tiktok search "dog health" --count 50 --project wonder-paws-tiktok --min-views 50000 --max-days 30
vt tiktok search "dog supplements" --count 25 --project wonder-paws-tiktok --min-views 50000 --max-days 30
vt tiktok search "pet wellness" --count 25 --project wonder-paws-tiktok --min-views 50000 --max-days 30
vt tiktok search "dog nutrition" --count 25 --project wonder-paws-tiktok --min-views 50000 --max-days 30
vt tiktok search "dogs" --count 25 --project wonder-paws-tiktok --min-views 1000 --max-days 7

# 3. Process
vt process videos --project wonder-paws-tiktok

# 4. Analyze
vt analyze videos --project wonder-paws-tiktok

# 5. Score
vt score videos --project wonder-paws-tiktok

# 6. Analyze correlations
vt score analyze --project wonder-paws-tiktok
```
