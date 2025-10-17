# New Context Window Prompt - YouTube Shorts Testing

Copy and paste this into a new Claude Code window to continue testing:

---

I'm working on the ViralTracker project. I just completed implementing YouTube Shorts integration in the `feature/youtube-shorts` branch.

**Current State:**
- Branch: `feature/youtube-shorts` (already pushed to GitHub)
- All code complete and committed
- Database configured
- Test project "Italian Brainrot" created with @animemes-collection channel linked

**What I Need:**
Test the YouTube Shorts scraper with this command:

```bash
cd /Users/ryemckenzie/projects/viraltracker
git checkout feature/youtube-shorts
vt scrape --project italian-brainrot --platform youtube_shorts --days-back 90 --max-results 100
```

**Expected Behavior:**
- Should scrape up to 100 Shorts from @animemes-collection channel
- Only Shorts from last 90 days
- Saves to database with full metadata (views, likes, comments, duration)
- Links all Shorts to "Italian Brainrot" project

**After Scraping Completes:**
1. Verify data in database:
   ```sql
   -- Check how many Shorts were scraped
   SELECT COUNT(*) FROM posts
   WHERE account_id = (SELECT id FROM accounts WHERE platform_username = 'animemes-collection');

   -- See top Shorts by views
   SELECT post_url, views, likes, comments, length_sec
   FROM posts
   WHERE account_id = (SELECT id FROM accounts WHERE platform_username = 'animemes-collection')
   ORDER BY views DESC
   LIMIT 10;
   ```

2. Run outlier detection:
   ```bash
   vt analyze outliers --project italian-brainrot --sd-threshold 3.0
   ```

3. Check for outliers:
   ```sql
   SELECT
     p.post_url,
     p.views,
     p.likes,
     pr.is_outlier,
     pr.sd_above_mean
   FROM posts p
   JOIN post_review pr ON pr.post_id = p.id
   WHERE p.account_id = (SELECT id FROM accounts WHERE platform_username = 'animemes-collection')
   AND pr.is_outlier = true
   ORDER BY pr.sd_above_mean DESC;
   ```

**Context Files to Read:**
- `CHECKPOINT_2025-10-15_youtube-shorts-complete.md` - Full implementation details
- `YOUTUBE_SHORTS_IMPLEMENTATION.md` - Architecture documentation
- `viraltracker/scrapers/youtube.py` - Scraper code

**If Errors Occur:**
Check the logs and refer to the "Troubleshooting" section in `CHECKPOINT_2025-10-15_youtube-shorts-complete.md`.

**Success Criteria:**
- [ ] Scraping completes without errors
- [ ] Shorts appear in database with metadata
- [ ] Channel metadata updated (subscriber count)
- [ ] Outlier detection identifies viral Shorts correctly
- [ ] All data properly linked to project

Let me know what happens when you run the scraper!
