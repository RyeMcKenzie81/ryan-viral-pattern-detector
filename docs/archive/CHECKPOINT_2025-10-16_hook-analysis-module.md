# CHECKPOINT: Hook Analysis Module Implementation
**Date**: 2025-10-16
**Project**: ViralTracker - Wonder Paws TikTok Research
**Phase**: Advanced Hook Intelligence Analysis System

---

## Summary

Created a standalone **hook analysis module** (`analysis/`) that performs advanced statistical analysis on scraped TikTok video data. This module operates independently on CSV exports and produces actionable insights for content editors through:

1. **Univariate correlations** (Spearman rank)
2. **Pairwise ranking models** (within-account, within-week matchups)
3. **Interaction effects** (e.g., shock × early proof, relatable × humor)
4. **Bucket tests** (editor-friendly rules with sample sizes and median lift)
5. **Data-driven playbook** (markdown summary for team sharing)

---

## Current Dataset Status

### Completed Phase 6 Milestones
- ✅ **Dataset expanded**: n=128 → **n=289 videos** (2.26x growth)
- ✅ **Hook Intelligence v1.2.0**: All 289 videos analyzed with Gemini 2.5 Pro
- ✅ **100% analysis success rate**: All processed videos analyzed
- ✅ **Statistical power**: 80% power for r ≥ 0.25 effects, 90% power for r ≥ 0.30
- ✅ **Processing rate**: 94.4% (289/306 videos successfully processed)

### Key Correlation Findings (n=289)

**Engagement Rate Correlations:**
- **Best performers**:
  - relatable_slice: +0.357 *** (medium effect)
  - humor_gag: +0.217 *** (small effect)
- **Worst performers**:
  - shock_violation: -0.345 *** (medium effect)
  - direct_callout: -0.250 *** (small effect)
  - challenge_stakes: -0.202 *** (small effect)
  - authority_flex: -0.201 *** (small effect)

**Views Correlations (Attention vs Engagement Paradox):**
- shock_violation: +0.341 views *** BUT -0.345 engagement ***
- relatable_slice: -0.174 views *** BUT +0.357 engagement ***

**Files Generated:**
- `hook_intelligence_correlation_results.txt`
- `views_correlation_results.txt`

---

## New Module: `analysis/`

### File Structure
```
analysis/
├── __init__.py                  # Module marker
├── config.py                    # Analysis configuration & hyperparameters
├── column_map.py                # CSV column mapping
└── run_hook_analysis.py         # Main analysis script
```

### Module Purpose

This module provides a **CSV-based analysis pipeline** that:
1. Normalizes view performance (controls for followers & post age)
2. Computes rank-based correlations (Spearman) for individual features
3. Trains pairwise ranking models to identify what hook choices win matchups
4. Tests specific interactions (e.g., does shock work better with early proof?)
5. Generates bucket tests for editor-friendly rules
6. Outputs machine-readable CSVs + human-readable playbook

### Key Features

#### 1. **Target Normalization**
```python
y_norm = log(views+1) - log(followers+1) - β*log(hours+1)
```
- Controls for account size and post recency
- Winsorizes at 1st/99th percentile to handle outliers
- Default β = 0.20 (configurable)

#### 2. **Univariate Analysis**
- Spearman correlation for each hook feature vs normalized target
- Outputs: `results/univariate.csv`
- Features tested:
  - Hook probabilities: result_first, shock_violation, reveal_transform, relatable_slice, humor_gag, tension_wait
  - Continuous features: payoff_time_sec, face_pct_1s, cuts_in_2s, overlay_chars_per_sec_2s

#### 3. **Pairwise Ranking Model**
- Learns from within-account, within-week video pairs
- Logistic regression on feature differences
- 5-fold cross-validation with AUC reporting
- Outputs: `results/pairwise_weights.csv`
- Answers: "When the same creator posts 2 videos in the same week, which hook choice wins?"

#### 4. **Interaction Tests**
- **shock_x_earlyproof**: shock_violation × (payoff_time ≤ 1.0s)
- **relatable_x_humor**: relatable_slice × humor_gag
- Outputs: `results/interactions.csv`

#### 5. **Bucket Tests**
Editor-friendly rules with sample sizes and lift:
- "Result-first ≥ 0.6"
- "Payoff ≤ 1.0s"
- "Relatable ≥ 0.6 & Humor ≥ 0.4"
- "Shock ≥ 0.6 WITH early proof"
- "Overlay ≤ 80 chars/s"
- Outputs: `results/buckets.csv`

#### 6. **Playbook Generation**
- Human-readable markdown summary: `results/playbook.md`
- Includes TL;DR with top 5 rules
- Full univariate, pairwise, interaction, and bucket results

---

## Configuration Files

### `analysis/config.py`
Defines:
- `time_decay_beta`: Normalization hyperparameter (default 0.20)
- `hook_prob_cols`: List of hook probability features
- `cont_hook_cols`: List of continuous features
- `interactions`: Dictionary of interaction tests to compute
- `bucket_rules`: Dictionary of editor-friendly rules
- `pairwise_features`: Combined feature list for ranking

### `analysis/column_map.py`
Maps CSV columns to analysis column names:
- **Required**: `post_id`, `account_id`, `posted_at`, `followers`, `views`, `hours_since_post`
- **Hook probabilities**: `hook_prob_*` columns (0..1 range)
- **Continuous features**: `payoff_time_sec`, `face_pct_1s`, `cuts_in_2s`, `overlay_chars_per_sec_2s`

**Note**: Script auto-scales `face_pct_1s` from 0..100 to 0..1 if needed.

---

## Usage

### Installation
```bash
pip install pandas numpy scipy scikit-learn
```

### Basic Usage
```bash
python -m analysis.run_hook_analysis \
  --csv data/dog_videos.csv \
  --outdir results
```

### Advanced Usage
```bash
python -m analysis.run_hook_analysis \
  --csv data/dog_videos.csv \
  --outdir results \
  --beta 0.15  # custom time decay parameter
```

### Expected Outputs
```
results/
├── univariate.csv           # Spearman correlations per feature
├── pairwise_weights.csv     # Pairwise ranking model weights + AUC
├── interactions.csv         # Interaction effect tests
├── buckets.csv             # Editor-friendly rules with lift
└── playbook.md             # Human-readable summary
```

---

## Technical Details

### Pairwise Ranking Logic
1. **Pair generation**: For each (account, week), create all combinations of video pairs
2. **Feature difference**: Δx = x_i - x_j
3. **Binary label**: y = 1 if video_i outperformed video_j, else 0
4. **Model**: Logistic regression on Δx to predict which video wins
5. **Validation**: 5-fold stratified CV, report mean AUC ± SD
6. **Interpretation**: Positive coefficient = "more of this feature tilts matchups in your favor"

### Robustness Features
- Gracefully handles missing columns (skips unavailable features)
- Requires minimum 20 samples for each correlation test
- Requires minimum 50 pairs for pairwise ranking
- Auto-detects and scales face_pct_1s if in percentage format
- Winsorizes target at 1%/99% to handle outliers
- Uses Spearman (rank-based) to handle non-linear relationships

---

## Background Process Status

Multiple TikTok scraping jobs still running in parallel:
- Bash 215430: "dog mom" search (200 videos)
- Bash 705408: "goldendoodle" search (200 videos)
- Bash 4a5d64: "puppy training" search (250 videos)
- Bash 78946c: "dog care" search (250 videos)
- Bash ddc390: "dog tips" search (250 videos)
- Bash b94631: "dog dad/parent/lover" searches (600 videos total)
- Bash 381d6b: "poodle/puppies/puppy" searches (600 videos total)

These will continue to expand the dataset for future analysis.

---

## Next Steps (Future Work)

1. **Export CSV from Supabase** for hook analysis module
2. **Run initial analysis** with current n=289 dataset
3. **Review playbook** and validate findings
4. **Optional enhancements**:
   - Add `--goal engagement` flag to swap target to engagement_rate
   - Add statistical significance markers to playbook
   - Add visualization generation (correlation heatmaps, bucket lift charts)
   - Add temporal analysis (does hook effectiveness change over time?)
   - Add account-level stratification (small vs large accounts)

---

## Files Modified/Created

### New Files
- `analysis/__init__.py` - Module marker
- `analysis/config.py` - Configuration & hyperparameters
- `analysis/column_map.py` - CSV column mapping
- `analysis/run_hook_analysis.py` - Main analysis script (276 lines)
- `CHECKPOINT_2025-10-16_hook-analysis-module.md` - This documentation

### Existing Correlation Results
- `hook_intelligence_correlation_results.txt` - Full Hook Intelligence analysis (n=289)
- `views_correlation_results.txt` - Views-specific correlation analysis (n=289)
- `verify_analysis_completion.py` - Dataset verification script

---

## Statistical Power Summary

With **n=289**:
- ✅ **90% power** to detect r ≥ 0.30 (medium effects)
- ✅ **80% power** to detect r ≥ 0.25 (small-medium effects)
- ⚠️ **Would need n=194** for 80% power at r=0.20 (currently n=289, so OVER-powered)
- ⚠️ **Would need n=783** for 80% power at r=0.10 (small effects)

**Current findings are statistically robust for medium+ effects.**

---

## Context for Next Session

This checkpoint documents the creation of a **standalone CSV-based hook analysis module**. The module is ready to use but requires:

1. **CSV export** from Supabase with the required columns
2. **Column mapping** adjustment if CSV uses different names
3. **Execution** of the analysis script
4. **Review** of generated playbook and outputs

The module operates independently of the main codebase and can be run on any CSV export of TikTok video data with hook intelligence features.

---

## Repository State

- **Working directory**: `/Users/ryemckenzie/projects/viraltracker`
- **Git branch**: `master`
- **Unstaged changes**: Multiple new analysis files
- **Background processes**: 11 TikTok scraping jobs still running
- **Dataset size**: n=289 analyzed videos (Hook Intelligence v1.2.0)
- **Analysis complete**: Correlation analysis complete and documented
