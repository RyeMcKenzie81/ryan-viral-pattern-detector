# Continuation Prompt for Next Claude Code Session

## Quick Start Context

You are continuing work on the **ViralTracker** project (Wonder Paws TikTok Research). The working directory is:
```
/Users/ryemckenzie/projects/viraltracker
```

## What Just Happened

I just completed **Phase 6: Hook Analysis Module Implementation**. Here's what was done:

1. **✅ Dataset Expansion Complete**: Grew dataset from n=128 to n=289 videos (2.26x)
2. **✅ Hook Intelligence v1.2.0 Analysis**: All 289 videos analyzed with Gemini 2.5 Pro (100% success rate)
3. **✅ Correlation Analysis**: Full statistical analysis complete
4. **✅ NEW Hook Analysis Module**: Created standalone CSV-based analysis system

## Current State

### Dataset Stats (n=289)
- **Analysis success**: 100% (289/289 processed videos analyzed)
- **Statistical power**: 80% power for r≥0.25, 90% power for r≥0.30
- **Key findings**:
  - Best for engagement: relatable_slice (+0.357 ***), humor_gag (+0.217 ***)
  - Worst for engagement: shock_violation (-0.345 ***), direct_callout (-0.250 ***)
  - Paradox: shock_violation gets +0.341 views BUT -0.345 engagement

### New Module Created: `analysis/`
A standalone hook analysis module that:
- Normalizes views for followers & post age
- Runs univariate correlations (Spearman)
- Trains pairwise ranking models (within-account, within-week)
- Tests interactions (shock × early proof, relatable × humor)
- Generates editor-friendly bucket rules
- Outputs playbook.md + 4 CSV reports

Files created:
- `analysis/__init__.py`
- `analysis/config.py`
- `analysis/column_map.py`
- `analysis/run_hook_analysis.py`

### Correlation Results Available
- `hook_intelligence_correlation_results.txt` - Full analysis
- `views_correlation_results.txt` - Views-focused analysis

### Background Processes
11 TikTok scraping jobs still running (will expand dataset further):
- dog mom, goldendoodle, puppy training, dog care, dog tips, dog dad/parent/lover, poodle/puppies/puppy

## What to Work On Next

### Immediate Tasks (Priority Order):

#### 1. **Export CSV from Supabase for Hook Analysis Module**
The new `analysis/` module needs a CSV with these columns:
- Required: `post_id`, `account_id`, `posted_at`, `followers`, `views`, `hours_since_post`
- Hook probs: `hook_prob_result_first`, `hook_prob_shock_violation`, `hook_prob_reveal_transform`, `hook_prob_relatable_slice`, `hook_prob_humor_gag`, `hook_prob_tension_wait`
- Continuous: `payoff_time_sec`, `face_pct_1s`, `cuts_in_2s`, `overlay_chars_per_sec_2s`

**Task**: Create a script to export from Supabase with proper column mapping.

#### 2. **Run Hook Analysis Module**
Once CSV is ready:
```bash
python -m analysis.run_hook_analysis --csv data/dog_videos.csv --outdir results
```

This will generate:
- `results/univariate.csv`
- `results/pairwise_weights.csv`
- `results/interactions.csv`
- `results/buckets.csv`
- `results/playbook.md`

#### 3. **Review and Validate Playbook**
- Check if pairwise ranking AUC is acceptable (>0.55 good, >0.60 excellent)
- Review bucket rules for actionable insights
- Compare with existing correlation findings

#### 4. **Optional Enhancements**
- Add `--goal engagement` flag to analyze engagement_rate instead of views
- Add visualization generation (heatmaps, bucket lift charts)
- Add temporal analysis (does hook effectiveness change over time?)

### Future Considerations
- Check on background scraping jobs (may have finished)
- Consider running analysis again when n>350 for better small-effect detection
- Document final findings for team handoff

## How to Continue

### Quick Command Reference
```bash
# Activate venv
source venv/bin/activate

# Check background scraping jobs
# Use /bashes in Claude Code to list running jobs

# Run hook analysis (once CSV is ready)
python -m analysis.run_hook_analysis --csv data/dog_videos.csv --outdir results

# Check dataset status
python verify_analysis_completion.py

# Re-run correlation analysis
python analyze_hook_intelligence_correlations.py
python analyze_views_correlations.py
```

### Important Files to Reference
- **Checkpoint**: `CHECKPOINT_2025-10-16_hook-analysis-module.md` (full documentation)
- **Correlation results**: `hook_intelligence_correlation_results.txt`, `views_correlation_results.txt`
- **Module config**: `analysis/config.py` (adjust hook features, bucket rules, interactions)
- **Column mapping**: `analysis/column_map.py` (adjust if CSV has different column names)

### Git Status
- Branch: `master`
- Uncommitted changes: New `analysis/` module, checkpoint docs, correlation result files
- Consider committing the new module before major changes

## Key Insights to Remember

### Statistical Findings (n=289)
1. **relatable_slice** is the strongest positive engagement driver (+0.357 ***)
2. **shock_violation** paradox: gets views (+0.341) but kills engagement (-0.345)
3. **humor_gag** is the best balanced hook (+0.182 views, +0.217 engagement)
4. Current sample size is SUFFICIENT for medium+ effects (r≥0.30)

### Next Analysis Goals
- Generate editor-friendly playbook from hook analysis module
- Validate pairwise ranking model (within-account matchups)
- Test interaction hypotheses (shock works better with early proof?)
- Create actionable rules with sample sizes and lift metrics

## Questions to Clarify
1. Do we have the required CSV columns already, or need to create export script?
2. Should we add engagement_rate as alternative target?
3. Should we commit the new analysis module before running it?
4. Do we want visualizations added to the playbook?

---

**Read this prompt to get context, then ask: "What would you like me to work on next?"**
