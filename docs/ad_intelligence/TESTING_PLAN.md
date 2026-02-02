# Ad Intelligence Agent - Testing Plan

## Pre-Testing Checklist

- [x] Migration applied: `migrations/2026-02-02_ad_intelligence.sql`
- [ ] Fix classifier rate limiting (see Checkpoint 01 — known issue #1)
- [ ] Restart Streamlit app after latest push

## 1. Smoke Test — App Starts

Start the app and check logs for:
```
AdIntelligenceService initialized
Ad Intelligence Agent initialized with 9 tools
Orchestrator Agent initialized with 8 tools (7 routing + 1 utility)
```

If missing, check import errors in the console.

## 2. Brand Resolution

In the chat UI, type:
```
Analyze the Wonder Paws ad account
```

**Expected:** Agent calls `resolve_brand_name("Wonder Paws")` → gets brand_id → calls `analyze_account`.

**If it fails:** Try "Analyze WonderPaws ads" or check Logfire for the routing trace.

## 3. Full Account Analysis (`/analyze_account`)

This is the big test — runs the full 4-layer pipeline.

**What to verify:**
- [ ] `ad_intelligence_runs` table has a new row with `status = 'completed'`
- [ ] `ad_creative_classifications` table has new rows for Wonder Paws ads
  - Check `source` column: should be `existing_brand_ad_analysis` (for analyzed ads) or `gemini_light` (for new)
  - Check `input_hash` is populated
- [ ] `ad_intelligence_baselines` table has new rows
  - Should have at least a brand-wide (`all`/`all`) baseline
  - Check `p25_ctr`, `median_ctr`, `p75_ctr` are populated
- [ ] `ad_intelligence_diagnostics` table has rows with the run_id
  - Check `fired_rules` JSONB has rule objects
  - Check `classification_id` is NOT NULL on every row
  - Verify some ads show `warning` or `critical` health
- [ ] `ad_intelligence_recommendations` table has rows
  - Check they reference the correct run_id
  - Check `priority` spread (critical/high/medium/low)
- [ ] Chat output shows formatted markdown with:
  - Account summary (brand name, active ads, spend)
  - Awareness distribution
  - Health summary
  - Top issues
  - Recommendation count

**Common failures:**
- "0 active ads" → Check `meta_ads_performance` has recent data for this brand_id
- Classification errors → Check Logfire for Gemini API errors (rate limits)
- Baseline errors → May need ≥5 unique ads and ≥30 ad-days of data

## 4. Recommendations (`/recommend`)

After a successful analysis:
```
Show me recommendations
```

**Verify:**
- [ ] Shows recommendations grouped by priority
- [ ] Each rec has: ID, title, summary, evidence, action
- [ ] Action links shown: `/rec_done`, `/rec_ignore`, `/rec_note`

Then test feedback:
```
/rec_done <paste-a-rec-id>
```
- [ ] Status changes to `acted_on` in DB
- [ ] Confirmation message displayed

## 5. Fatigue Check

```
Check for fatigued ads for Wonder Paws
```

**Verify:**
- [ ] Shows fatigued ads (frequency ≥ 4.0 + CTR declining)
- [ ] Shows at-risk ads (frequency ≥ 2.5)
- [ ] Shows healthy count
- [ ] No errors in Logfire

## 6. Coverage Gaps

```
What awareness levels am I missing for Wonder Paws?
```

**Verify:**
- [ ] Shows awareness × format matrix
- [ ] Identifies hard gaps (0 ads), SPOFs (< 2 ads)
- [ ] Suggests actions for gaps

## 7. Congruence Check

```
Check ad congruence for Wonder Paws
```

**Verify:**
- [ ] Shows average congruence score
- [ ] Lists misaligned ads (score < 0.75) with levels
- [ ] Handles ads with no landing page data (2-way score)

## 8. Re-Run Stability

Run analysis again:
```
Analyze Wonder Paws ads again
```

**Verify:**
- [ ] Creates a new run (new run_id)
- [ ] Reuses existing fresh classifications (no new Gemini calls)
- [ ] New baselines/diagnostics/recs created under new run_id
- [ ] No duplicate classifications

## 9. Edge Cases

### Brand with No Ads
If you have a brand with no `meta_ads_performance` data:
- [ ] Should return "0 active ads" message, not an error

### Few Ads (< 5)
- [ ] Baselines should show insufficient data
- [ ] Diagnostics should show `insufficient_data` health

## 10. Logfire Monitoring

During all tests, check Logfire for:
- [ ] No unhandled exceptions
- [ ] Routing traces show orchestrator → ad_intelligence_agent
- [ ] Gemini calls (if any) are logged
- [ ] Run completion logged

### Useful Logfire queries:
```sql
-- Recent ad intelligence activity
SELECT start_timestamp, message, span_name
FROM records
WHERE message LIKE '%ad_intelligence%' OR message LIKE '%Ad Intelligence%'
ORDER BY start_timestamp DESC
LIMIT 50

-- Any errors
SELECT start_timestamp, exception_type, exception_message
FROM records
WHERE exception_type IS NOT NULL
ORDER BY start_timestamp DESC
LIMIT 20
```

## Known Issues to Fix Before Full Testing

1. **Classifier rate limiting** — `_classify_with_gemini()` creates a new GeminiService per call instead of reusing the one with configured rate limits. Risk of hitting Gemini API rate limits on large accounts. Fix: pass GeminiService through AdIntelligenceService constructor.
