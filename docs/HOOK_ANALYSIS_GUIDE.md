# Hook Analysis Guide

Complete guide to the Hook Analysis Module - advanced statistical analysis for identifying viral patterns in short-form video content.

---

## Table of Contents

- [Overview](#overview)
- [Quick Start](#quick-start)
- [Export Data](#export-data)
- [Run Analysis](#run-analysis)
- [Understanding Results](#understanding-results)
- [Configuration](#configuration)
- [Advanced Usage](#advanced-usage)
- [Case Study](#case-study)

---

## Overview

The Hook Analysis Module performs advanced statistical analysis on video hook intelligence data to identify actionable patterns for content creators.

### What It Does

1. **Normalizes Performance** - Controls for account size and post recency
2. **Univariate Analysis** - Spearman correlations for individual features
3. **Pairwise Ranking** - Within-account matchup analysis
4. **Interaction Testing** - Synergy between feature combinations
5. **Bucket Generation** - Editor-friendly rules with sample sizes and lift

### Key Features

- **Rank-based statistics** (Spearman) - Handles non-linear relationships
- **Within-account comparisons** - Controls for creator effects
- **Cross-validation** - 5-fold CV for model validation
- **Editor-friendly output** - Actionable rules with lift metrics

---

## Quick Start

### Complete Workflow

```bash
# 1. Export data from Supabase
python export_hook_analysis_csv.py

# 2. Run analysis
python -m analysis.run_hook_analysis \
  --csv data/hook_intelligence_export.csv \
  --outdir results

# 3. Review playbook
cat results/playbook.md
```

**That's it!** The analysis generates 5 output files in `results/`.

---

## Export Data

### Run Export Script

```bash
python export_hook_intelligence_export.csv.py
```

### What Gets Exported

The script queries Supabase and exports a CSV with:

**Required Columns:**
- `post_id` - Unique video identifier
- `account_id` - Creator account ID
- `posted_at` - Publication timestamp
- `followers` - Account follower count
- `views` - Video view count
- `hours_since_post` - Age of post in hours

**Hook Probabilities (0-1 scale):**
- `hook_prob_result_first`
- `hook_prob_shock_violation`
- `hook_prob_reveal_transform`
- `hook_prob_relatable_slice`
- `hook_prob_humor_gag`
- `hook_prob_tension_wait`
- `hook_prob_direct_callout`
- `hook_prob_challenge_stakes`
- `hook_prob_authority_flex`

**Continuous Features:**
- `payoff_time_sec` - Time to deliver on hook promise
- `face_pct_1s` - Face presence in first second (%)
- `cuts_in_2s` - Number of cuts in first 2 seconds
- `overlay_chars_per_sec_2s` - Text overlay density (chars/sec)

**Bonus Columns:**
- `likes`, `comments` - Engagement metrics
- `engagement_rate` - (likes + comments) / views * 100

### Data Quality Report

The export script shows data quality:

```
Required columns:
  post_id                  :  297 non-null,    0 null
  followers                :  297 non-null,    0 null
  views                    :  297 non-null,    0 null

Hook probability columns:
  hook_prob_shock_violation:  292 non-null,    5 null, mean=0.383
  hook_prob_humor_gag      :  282 non-null,   15 null, mean=0.341

Continuous features:
  payoff_time_sec          :  266 non-null,   31 null, mean=11.592
  face_pct_1s              :  297 non-null,    0 null, mean=23.440
```

---

## Run Analysis

### Basic Usage

```bash
python -m analysis.run_hook_analysis \
  --csv data/hook_intelligence_export.csv \
  --outdir results
```

### Options

```bash
# Custom time decay parameter
python -m analysis.run_hook_analysis \
  --csv data/hook_intelligence_export.csv \
  --outdir results \
  --beta 0.15

# Different goal metric (default is views)
python -m analysis.run_hook_analysis \
  --csv data/hook_intelligence_export.csv \
  --outdir results \
  --goal engagement_rate
```

### Parameters

- `--csv` - Path to exported CSV file
- `--outdir` - Output directory for results
- `--beta` - Time decay parameter (default: 0.20)
- `--goal` - Target metric: `views` or `engagement_rate` (default: `views`)

---

## Understanding Results

### Output Files

The analysis generates 5 files:

#### 1. `playbook.md` - Human-Readable Summary

```markdown
# Dog Niche Hook Playbook (Data-Driven)

## TL;DR
- **Relatable ≥ 0.6 & Humor ≥ 0.4** → Δmedian = 0.711 (n_true=71, n_false=226)
- **Payoff ≤ 1.0s** → Δmedian = 0.247 (n_true=57, n_false=240)

## Univariate Signals
hook_prob_shock_violation: ρ=0.286, p<0.001 ***
hook_prob_humor_gag: ρ=0.255, p<0.001 ***
...
```

**Interpretation:**
- **TL;DR** - Top 2 actionable rules
- **Univariate** - Individual feature effects
- **Δmedian** - Performance lift (log-scale normalized views)
- **Significance** - *** p<0.01, ** p<0.05, * p<0.1

#### 2. `univariate.csv` - Feature Correlations

```csv
feature,n,rho,p
hook_prob_shock_violation,292,0.286,0.000001
hook_prob_humor_gag,282,0.255,0.000014
overlay_chars_per_sec_2s,294,-0.200,0.000575
```

**Columns:**
- `feature` - Hook feature name
- `n` - Sample size
- `rho` - Spearman correlation coefficient
- `p` - P-value

**Interpretation:**
- **Positive rho** - Higher feature value → more views
- **Negative rho** - Higher feature value → fewer views
- **|rho| > 0.30** - Medium effect
- **|rho| > 0.50** - Large effect

#### 3. `interactions.csv` - Synergy Effects

```csv
interaction,n,rho,p
shock_x_earlyproof,261,0.169,0.006
relatable_x_humor,281,0.150,0.012
```

**Interactions Tested:**
- `shock_x_earlyproof` - shock_violation × (payoff ≤ 1.0s)
- `relatable_x_humor` - relatable_slice × humor_gag

**Interpretation:**
- Positive correlation = synergy (combination works better than sum of parts)
- Tests specific hypotheses about feature combinations

#### 4. `buckets.csv` - Editor-Friendly Rules

```csv
rule,n_true,n_false,delta_median,median_true,median_false
Relatable ≥ 0.6 & Humor ≥ 0.4,71,226,0.711,3.28,2.57
Payoff ≤ 1.0s,57,240,0.247,3.00,2.75
```

**Columns:**
- `rule` - Actionable rule
- `n_true` - Videos matching rule
- `n_false` - Videos not matching
- `delta_median` - Lift in normalized views
- `median_true/false` - Median performance for each group

**Interpretation:**
- `delta_median` - How much better the rule performs
- Larger sample (`n_true`) = more reliable
- Delta > 0.3 = meaningful lift

#### 5. `pairwise_weights.csv` - Ranking Model

*Generated only if ≥50 within-account pairs available*

```csv
feature,weight,auc_mean,auc_std
hook_prob_humor_gag,0.523,0.587,0.042
payoff_time_sec,-0.312,0.587,0.042
```

**Interpretation:**
- **weight** - Feature importance in matchups
- **auc_mean** - Cross-validation AUC
- **auc_std** - Model stability
- AUC > 0.55 = decent, > 0.60 = good

---

## Configuration

### Edit `analysis/config.py`

#### Time Decay Parameter

```python
time_decay_beta = 0.20  # Default
```

Controls how much recent posts are penalized. Higher = more penalty.

**Formula:** `y_norm = log(views+1) - log(followers+1) - β*log(hours+1)`

#### Hook Features

```python
hook_prob_cols = [
    "hook_prob_result_first",
    "hook_prob_shock_violation",
    # Add/remove features
]

cont_hook_cols = [
    "payoff_time_sec",
    "face_pct_1s",
    # Add/remove features
]
```

#### Custom Interactions

```python
interactions = {
    "shock_x_earlyproof": lambda df: (
        df["hook_prob_shock_violation"] *
        (df["payoff_time_sec"] <= 1.0).astype(float)
    ),
    # Add your own
    "custom_interaction": lambda df: (
        df["hook_prob_relatable_slice"] *
        (df["face_pct_1s"] >= 30.0).astype(float)
    ),
}
```

#### Custom Bucket Rules

```python
bucket_rules = {
    "Relatable ≥ 0.6 & Humor ≥ 0.4": lambda df: (
        (df["hook_prob_relatable_slice"] >= 0.6) &
        (df["hook_prob_humor_gag"] >= 0.4)
    ),
    # Add your own
    "High Face Early Payoff": lambda df: (
        (df["face_pct_1s"] >= 40.0) &
        (df["payoff_time_sec"] <= 2.0)
    ),
}
```

### Edit `analysis/column_map.py`

If your CSV has different column names:

```python
COLUMN_MAP = {
    "post_id": "video_id",  # Your column → Analysis column
    "followers": "follower_count",
    # Map your columns here
}
```

---

## Advanced Usage

### Analyze Engagement Instead of Views

```bash
python -m analysis.run_hook_analysis \
  --csv data/hook_intelligence_export.csv \
  --outdir results_engagement \
  --goal engagement_rate
```

This changes the target variable from normalized views to engagement rate.

### Different Normalization

```bash
# Stronger time decay (penalize recent posts more)
python -m analysis.run_hook_analysis \
  --csv data/hook_intelligence_export.csv \
  --outdir results \
  --beta 0.30

# Weaker time decay
python -m analysis.run_hook_analysis \
  --csv data/hook_intelligence_export.csv \
  --outdir results \
  --beta 0.10
```

### Batch Analysis

```bash
# Run multiple analyses
for beta in 0.15 0.20 0.25; do
  python -m analysis.run_hook_analysis \
    --csv data/hook_intelligence_export.csv \
    --outdir results_beta_$beta \
    --beta $beta
done

# Compare results
diff results_beta_0.15/playbook.md results_beta_0.25/playbook.md
```

---

## Case Study

### Wonder Paws TikTok Research (n=297)

**Dataset:**
- 297 dog-related TikTok videos
- 267 unique accounts
- Views: 503 - 186M (median: 78K)
- Followers: 0 - 318K (median: 1.6K)

**Key Findings:**

1. **Best Combination: Relatable + Humor**
   - Rule: relatable_slice ≥ 0.6 AND humor_gag ≥ 0.4
   - Sample: 71 videos
   - **Lift: +71% normalized views**

2. **Quick Payoff Matters**
   - Rule: payoff_time ≤ 1.0 seconds
   - Sample: 57 videos
   - **Lift: +25% normalized views**

3. **Individual Effects:**
   - shock_violation: +28.6% (p < 0.001)
   - humor_gag: +25.5% (p < 0.001)
   - overlay_chars_per_sec: -20.0% (p < 0.001)

4. **Paradox: Relatable Negative Individually, Positive Combined**
   - relatable_slice alone: ρ = -0.120
   - relatable × humor: ρ = +0.150
   - **Insight:** Relatable needs humor to work

5. **Shock Works Better with Early Proof**
   - shock × early_proof: ρ = +0.169 (p = 0.006)
   - **Insight:** Shocking hooks need quick validation

### Actionable Recommendations

For dog content creators:

✅ **DO:**
- Combine relatable moments with humor
- Deliver payoff in < 1 second
- Use shock tactically with quick proof
- Keep overlay text minimal

❌ **AVOID:**
- Pure relatable without humor
- Slow payoffs (> 5 seconds)
- Heavy text overlays
- Reveal/transform hooks (negative effect)

---

## Statistical Details

### Normalization Formula

```python
y_norm = log(views + 1) - log(followers + 1) - beta * log(hours_since_post + 1)
```

- **log transforms** - Handle wide range of values
- **followers adjustment** - Controls for account size
- **time decay (beta)** - Accounts for post recency
- **winsorization** - Clips outliers at 1%/99% percentiles

### Correlation Method

**Spearman Rank Correlation:**
- Non-parametric (no distribution assumptions)
- Robust to outliers
- Handles monotonic relationships (not just linear)

**Why not Pearson?**
- Pearson assumes linear relationships
- Sensitive to outliers
- Requires normal distribution

### Pairwise Ranking Model

**Within-Account, Within-Week Matchups:**

1. For each account and week, create all pairs of videos
2. Calculate feature differences: Δx = x_i - x_j
3. Binary label: y = 1 if video_i outperformed video_j
4. Train logistic regression on Δx
5. 5-fold cross-validation for AUC

**Why pairwise?**
- Controls for creator effect
- Isolates feature impact
- More robust than absolute performance

### Sample Size Requirements

- **Univariate:** Minimum 20 samples per feature
- **Pairwise:** Minimum 50 pairs for training
- **Interactions:** Minimum 50 samples
- **Buckets:** Minimum 10 samples in `n_true`

---

## Troubleshooting

### "Not enough data for pairwise ranking"

**Solution:** Need ≥50 within-account, within-week pairs

```bash
# Check pair count
python -c "
import pandas as pd
df = pd.read_csv('data/hook_intelligence_export.csv')
df['week'] = pd.to_datetime(df['posted_at']).dt.to_period('W')
pairs = 0
for (acc, week), group in df.groupby(['account_id', 'week']):
    n = len(group)
    pairs += n * (n - 1) // 2
print(f'Total pairs: {pairs}')
"
```

### "Missing required columns"

**Solution:** Check column mapping in `analysis/column_map.py`

```bash
# Verify CSV columns
head -1 data/hook_intelligence_export.csv
```

### Results seem off

**Checklist:**
1. Videos processed before analysis? → `./vt process videos`
2. Hook intelligence analysis complete? → `./vt analyze videos`
3. Sufficient sample size? → n ≥ 100 recommended
4. Time decay parameter reasonable? → Try different beta values

---

## Next Steps

- See [CLI_GUIDE.md](CLI_GUIDE.md) for scraping and processing
- See [../README.md](../README.md) for system architecture
- Check [analysis/config.py](../analysis/config.py) for customization
