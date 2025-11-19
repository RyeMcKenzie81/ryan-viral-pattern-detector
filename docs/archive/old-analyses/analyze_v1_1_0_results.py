#!/usr/bin/env python3
"""Analyze v1.1.0 continuous fields and correlate with view counts"""
import json
import numpy as np
from scipy import stats
from viraltracker.core.config import Config
from supabase import create_client

# Initialize Supabase
supabase = create_client(Config.SUPABASE_URL, Config.SUPABASE_SERVICE_KEY)

# Get project
project_response = supabase.table('projects').select('id,name').eq('slug', 'wonder-paws-tiktok').execute()
project_id = project_response.data[0]['id']
print(f"Project: {project_response.data[0]['name']} ({project_id})")

# Get all posts in project with their view counts
posts_response = supabase.table('project_posts')\
    .select('post_id,posts(id,views)')\
    .eq('project_id', project_id)\
    .execute()

post_views = {p['post_id']: p['posts']['views'] for p in posts_response.data}
print(f"Total posts in project: {len(post_views)}")

# Get all v1.1.0 Gemini 2.5 Pro analyses
analyses = supabase.table('video_analysis')\
    .select('post_id,platform_specific_metrics,analysis_model,analysis_version')\
    .in_('post_id', list(post_views.keys()))\
    .eq('analysis_version', 'vid-1.1.0')\
    .execute()

print(f"\nTotal v1.1.0 analyses: {len(analyses.data)}")

# Filter for Gemini 2.5 Pro only
pro_analyses = [a for a in analyses.data if 'gemini-2.5-pro' in a.get('analysis_model', '').lower()]
print(f"Gemini 2.5 Pro v1.1.0 analyses: {len(pro_analyses)}")

# Extract continuous metrics from v1.1.0 structure
# These are the key continuous/numeric metrics in v1.1.0
continuous_metrics_extractors = {
    'time_to_value_sec': lambda psm: psm.get('hook', {}).get('time_to_value_sec'),
    'first_frame_face_pct': lambda psm: psm.get('hook', {}).get('first_frame_face_present_pct'),
    'first_2s_motion': lambda psm: psm.get('hook', {}).get('first_2s_motion_intensity'),
    'beats_count': lambda psm: psm.get('story', {}).get('beats_count'),
    'avg_beat_length_sec': lambda psm: psm.get('story', {}).get('avg_beat_length_sec'),
    'edit_rate_per_10s': lambda psm: psm.get('visuals', {}).get('edit_rate_per_10s'),
    'brightness_mean': lambda psm: psm.get('visuals', {}).get('brightness_mean'),
    'contrast_mean': lambda psm: psm.get('visuals', {}).get('contrast_mean'),
    'speech_intelligibility': lambda psm: psm.get('audio', {}).get('speech_intelligibility_score'),
    'authenticity_signals': lambda psm: psm.get('relatability', {}).get('authenticity_signals'),
    'emotion_intensity': lambda psm: psm.get('shareability', {}).get('emotion_intensity'),
    'simplicity_score': lambda psm: psm.get('shareability', {}).get('simplicity_score'),
    'video_length_sec': lambda psm: psm.get('watchtime', {}).get('length_sec'),
    'hashtag_count': lambda psm: psm.get('algo', {}).get('hashtag_count'),
}

# Boolean flags (not continuous, but useful for context)
boolean_flags = {
    'trending_sound': lambda psm: psm.get('audio', {}).get('trending_sound_used'),
    'original_sound': lambda psm: psm.get('audio', {}).get('original_sound_created'),
    'comment_prompt': lambda psm: psm.get('engagement', {}).get('comment_prompt_present'),
}

# Collect all metrics
metrics_data = {field: [] for field in continuous_metrics_extractors.keys()}
views_list = []

for analysis in pro_analyses:
    post_id = analysis['post_id']
    views = post_views.get(post_id)

    if views is None:
        continue

    psm = analysis.get('platform_specific_metrics')
    if not psm:
        continue

    # Parse JSON if string
    if isinstance(psm, str):
        psm = json.loads(psm)

    # Extract all available metrics
    row_data = {}
    for field, extractor in continuous_metrics_extractors.items():
        value = extractor(psm)
        if value is not None:
            row_data[field] = value

    # Only include if we have at least some metrics
    if len(row_data) >= 8:  # At least 8 out of 14 metrics present
        views_list.append(views)
        for field in continuous_metrics_extractors.keys():
            metrics_data[field].append(row_data.get(field))

print(f"\nAnalyses with sufficient continuous metrics: {len(views_list)}")

# Validate variance for metrics that have values
print("\n" + "="*60)
print("CONTINUOUS FIELDS VARIANCE VALIDATION")
print("="*60)

valid_metrics = []
for field in continuous_metrics_extractors.keys():
    values = [v for v in metrics_data[field] if v is not None]

    if len(values) < 10:  # Skip metrics with too few values
        continue

    values = np.array(values)
    valid_metrics.append(field)

    print(f"\n{field}:")
    print(f"  Count:  {len(values)}")
    print(f"  Min:    {values.min():.3f}")
    print(f"  Max:    {values.max():.3f}")
    print(f"  Mean:   {values.mean():.3f}")
    print(f"  Std:    {values.std():.3f}")
    print(f"  Range:  {values.max() - values.min():.3f}")

# Correlation analysis
print("\n" + "="*60)
print("CORRELATION ANALYSIS WITH VIEW COUNTS")
print("="*60)

views_array = np.array(views_list)
print(f"\nView counts (n={len(views_array)}):")
print(f"  Min:    {views_array.min():,}")
print(f"  Max:    {views_array.max():,}")
print(f"  Mean:   {views_array.mean():,.0f}")
print(f"  Median: {np.median(views_array):,.0f}")

correlations = []

print("\nCorrelations with view counts:")
print("-" * 70)
print(f"{'Metric':<30s}  {'n':>4s}  {'r':>7s}  {'p-value':>8s}  {'Sig':>3s}")
print("-" * 70)

for field in valid_metrics:
    # Get non-null values and corresponding views
    field_values = []
    field_views = []

    for i, val in enumerate(metrics_data[field]):
        if val is not None:
            field_values.append(val)
            field_views.append(views_list[i])

    if len(field_values) < 10:
        continue

    values = np.array(field_values)
    views = np.array(field_views)

    r, p = stats.pearsonr(values, views)
    correlations.append((field, r, p, len(field_values)))

    sig = "***" if p < 0.001 else "**" if p < 0.01 else "*" if p < 0.05 else ""
    print(f"{field:<30s}  {len(field_values):>4d}  {r:>7.3f}  {p:>8.4f}  {sig:>3s}")

# Sort by absolute correlation
correlations.sort(key=lambda x: abs(x[1]), reverse=True)

print("\n" + "="*60)
print("TOP PREDICTIVE METRICS (by absolute correlation)")
print("="*60)

for i, (field, r, p, n) in enumerate(correlations[:5], 1):
    sig = "***" if p < 0.001 else "**" if p < 0.01 else "*" if p < 0.05 else ""
    direction = "positive" if r > 0 else "negative"
    print(f"{i}. {field:<30s}  r={r:>7.3f}  p={p:.4f} {sig:>3s} ({direction}, n={n})")

# Composite score using standardized metrics
print("\n" + "="*60)
print("COMPOSITE SCORE (standardized average)")
print("="*60)

# Build composite from metrics with good coverage
high_coverage_metrics = [field for field, r, p, n in correlations if n >= len(views_list) * 0.8]

if len(high_coverage_metrics) >= 3:
    print(f"Using {len(high_coverage_metrics)} metrics with >=80% coverage")

    # Standardize each metric and compute mean
    composite_scores = []
    for i in range(len(views_list)):
        scores = []
        for field in high_coverage_metrics:
            if metrics_data[field][i] is not None:
                # Get all non-null values for this metric to compute mean/std
                all_vals = [v for v in metrics_data[field] if v is not None]
                if len(all_vals) > 1:
                    mean = np.mean(all_vals)
                    std = np.std(all_vals)
                    if std > 0:
                        z_score = (metrics_data[field][i] - mean) / std
                        scores.append(z_score)

        if scores:
            composite_scores.append(np.mean(scores))
        else:
            composite_scores.append(None)

    # Remove None values
    valid_composite = [(comp, views_list[i]) for i, comp in enumerate(composite_scores) if comp is not None]

    if len(valid_composite) >= 10:
        comp_array = np.array([c[0] for c in valid_composite])
        comp_views = np.array([c[1] for c in valid_composite])

        r_composite, p_composite = stats.pearsonr(comp_array, comp_views)

        print(f"Composite score correlation:  r={r_composite:.3f}  p={p_composite:.4f}  n={len(comp_array)}")

        # Compare with v1.0.0 baseline
        print("\n" + "="*60)
        print("COMPARISON WITH v1.0.0 BASELINE")
        print("="*60)
        print(f"v1.0.0 baseline:  r=0.048  p=0.73  (NO correlation)")
        print(f"v1.1.0 composite: r={r_composite:.3f}  p={p_composite:.4f}")

        if abs(r_composite) > 0.048:
            improvement = ((abs(r_composite) - 0.048) / 0.048) * 100
            print(f"\nImprovement: {improvement:.1f}% increase in absolute correlation")

            if p_composite < 0.05:
                print("✅ SIGNIFICANT correlation achieved (p < 0.05)")
            else:
                print("⚠️  Correlation not statistically significant (p >= 0.05)")
        else:
            print("\n⚠️  No improvement over v1.0.0 baseline")
else:
    print("⚠️  Not enough high-coverage metrics for composite score")

print("\n" + "="*60)
print("ANALYSIS COMPLETE")
print("="*60)
