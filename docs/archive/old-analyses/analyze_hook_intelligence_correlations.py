"""
Correlation Analysis: Hook Intelligence v1.2.0 Features vs Performance
Analyzes relationships between hook features and video performance metrics.
"""
import os
import json
import pandas as pd
import numpy as np
from dotenv import load_dotenv
from scipy import stats
from viraltracker.core.database import get_supabase_client

# Load environment variables
load_dotenv()

# Initialize Supabase client
supabase = get_supabase_client()

print("=" * 80)
print("Hook Intelligence v1.2.0 Correlation Analysis")
print("=" * 80)

# Fetch video analyses with hook features
print("\nFetching video analyses with hook intelligence data...")
response = supabase.table("video_analysis").select(
    "post_id, hook_features, posts(views, likes, comments)"
).not_.is_("hook_features", "null").execute()

data = response.data
print(f"Found {len(data)} videos with hook intelligence data")

if len(data) == 0:
    print("No data found with hook_features. Exiting.")
    exit()

# Parse hook features and create flat dataframe
records = []
for record in data:
    hook_features = record.get("hook_features", {})
    posts = record.get("posts", {})

    if not hook_features or not posts:
        continue

    # Extract performance metrics
    views = posts.get("views", 0)
    likes = posts.get("likes", 0)
    comments = posts.get("comments", 0)

    # Calculate engagement rate
    engagement_rate = ((likes + comments) / views * 100) if views > 0 else 0

    # Extract hook type probabilities
    hook_type_probs = hook_features.get("hook_type_probs", {})

    # Extract modality attribution
    modality = hook_features.get("hook_modality_attribution", {})

    # Extract timing features
    hook_span = hook_features.get("hook_span", {})
    payoff_time = hook_features.get("payoff_time_sec")

    # Extract windowed metrics
    windows = hook_features.get("hook_windows", {})

    # Build record
    row = {
        "post_id": record.get("post_id"),
        "views": views,
        "likes": likes,
        "comments": comments,
        "engagement_rate": engagement_rate,
    }

    # Add hook type probabilities
    for hook_type, prob in hook_type_probs.items():
        row[f"hook_{hook_type}"] = prob

    # Add modality attribution
    if modality:
        row["modality_audio"] = modality.get("audio", 0)
        row["modality_visual"] = modality.get("visual", 0)
        row["modality_overlay"] = modality.get("overlay", 0)

    # Add timing features
    if hook_span:
        row["hook_start_sec"] = hook_span.get("start_sec")
        row["hook_end_sec"] = hook_span.get("end_sec")
        hook_duration = None
        if hook_span.get("start_sec") is not None and hook_span.get("end_sec") is not None:
            hook_duration = hook_span.get("end_sec") - hook_span.get("start_sec")
        row["hook_duration_sec"] = hook_duration

    row["payoff_time_sec"] = payoff_time

    # Add windowed retention metrics
    if windows:
        for window_name, window_data in windows.items():
            if isinstance(window_data, dict):
                retention = window_data.get("retention_pct")
                if retention is not None:
                    row[f"retention_{window_name}"] = retention

    records.append(row)

df = pd.DataFrame(records)
print(f"\nDataFrame created with {len(df)} records and {len(df.columns)} features")

# Remove columns with all NaN or zeros
df = df.dropna(axis=1, how='all')
df = df.loc[:, (df != 0).any(axis=0)]

print(f"After cleaning: {len(df.columns)} features")

# Define feature groups for analysis
hook_types = [col for col in df.columns if col.startswith("hook_") and not col.startswith("hook_duration")]
modality_cols = [col for col in df.columns if col.startswith("modality_")]
timing_cols = ["hook_start_sec", "hook_end_sec", "hook_duration_sec", "payoff_time_sec"]
timing_cols = [col for col in timing_cols if col in df.columns]
retention_cols = [col for col in df.columns if col.startswith("retention_")]
performance_cols = ["views", "likes", "comments", "engagement_rate"]

print("\n" + "=" * 80)
print("1. HOOK TYPE CORRELATIONS WITH PERFORMANCE")
print("=" * 80)

if hook_types and len(df) > 2:
    print(f"\nAnalyzing {len(hook_types)} hook types...")

    correlations = {}
    for hook_type in hook_types:
        hook_name = hook_type.replace("hook_", "")
        correlations[hook_name] = {}

        for perf in performance_cols:
            if perf in df.columns and df[perf].notna().sum() > 2:
                # Filter out rows where both values are present
                mask = df[hook_type].notna() & df[perf].notna()
                if mask.sum() > 2:
                    corr, p_value = stats.spearmanr(df.loc[mask, hook_type], df.loc[mask, perf])
                    correlations[hook_name][perf] = {"corr": corr, "p_value": p_value}

    # Create correlation matrix for visualization
    corr_matrix = pd.DataFrame({
        hook: {perf: data["corr"] for perf, data in perfs.items()}
        for hook, perfs in correlations.items()
    }).T

    print("\nTop positive correlations (sorted by engagement_rate):")
    if "engagement_rate" in corr_matrix.columns:
        top_positive = corr_matrix["engagement_rate"].sort_values(ascending=False).head(10)
        for hook_type, corr_val in top_positive.items():
            sig = "***" if correlations[hook_type]["engagement_rate"]["p_value"] < 0.01 else \
                  "**" if correlations[hook_type]["engagement_rate"]["p_value"] < 0.05 else \
                  "*" if correlations[hook_type]["engagement_rate"]["p_value"] < 0.1 else ""
            print(f"  {hook_type:30s}: {corr_val:+.3f} {sig}")

    print("\nTop negative correlations (sorted by engagement_rate):")
    if "engagement_rate" in corr_matrix.columns:
        top_negative = corr_matrix["engagement_rate"].sort_values(ascending=True).head(10)
        for hook_type, corr_val in top_negative.items():
            sig = "***" if correlations[hook_type]["engagement_rate"]["p_value"] < 0.01 else \
                  "**" if correlations[hook_type]["engagement_rate"]["p_value"] < 0.05 else \
                  "*" if correlations[hook_type]["engagement_rate"]["p_value"] < 0.1 else ""
            print(f"  {hook_type:30s}: {corr_val:+.3f} {sig}")

print("\n" + "=" * 80)
print("2. MODALITY ATTRIBUTION CORRELATIONS")
print("=" * 80)

if modality_cols and len(df) > 2:
    print(f"\nAnalyzing {len(modality_cols)} modality features...")

    for modality in modality_cols:
        print(f"\n{modality}:")
        for perf in performance_cols:
            if perf in df.columns and df[perf].notna().sum() > 2:
                mask = df[modality].notna() & df[perf].notna()
                if mask.sum() > 2:
                    corr, p_value = stats.spearmanr(df.loc[mask, modality], df.loc[mask, perf])
                    sig = "***" if p_value < 0.01 else "**" if p_value < 0.05 else "*" if p_value < 0.1 else ""
                    print(f"  {perf:20s}: {corr:+.3f} {sig}")

print("\n" + "=" * 80)
print("3. TIMING FEATURES CORRELATIONS")
print("=" * 80)

if timing_cols and len(df) > 2:
    print(f"\nAnalyzing {len(timing_cols)} timing features...")

    for timing in timing_cols:
        print(f"\n{timing}:")
        for perf in performance_cols:
            if perf in df.columns and df[perf].notna().sum() > 2:
                mask = df[timing].notna() & df[perf].notna()
                if mask.sum() > 2:
                    corr, p_value = stats.spearmanr(df.loc[mask, timing], df.loc[mask, perf])
                    sig = "***" if p_value < 0.01 else "**" if p_value < 0.05 else "*" if p_value < 0.1 else ""
                    print(f"  {perf:20s}: {corr:+.3f} {sig}")

print("\n" + "=" * 80)
print("4. WINDOWED RETENTION CORRELATIONS")
print("=" * 80)

if retention_cols and len(df) > 2:
    print(f"\nAnalyzing {len(retention_cols)} retention windows...")

    for retention in retention_cols:
        print(f"\n{retention}:")
        for perf in performance_cols:
            if perf in df.columns and df[perf].notna().sum() > 2:
                mask = df[retention].notna() & df[perf].notna()
                if mask.sum() > 2:
                    corr, p_value = stats.spearmanr(df.loc[mask, retention], df.loc[mask, perf])
                    sig = "***" if p_value < 0.01 else "**" if p_value < 0.05 else "*" if p_value < 0.1 else ""
                    print(f"  {perf:20s}: {corr:+.3f} {sig}")

print("\n" + "=" * 80)
print("5. SUMMARY STATISTICS")
print("=" * 80)

print(f"\nTotal videos analyzed: {len(df)}")
print(f"\nPerformance metrics summary:")
for col in performance_cols:
    if col in df.columns:
        print(f"  {col:20s}: mean={df[col].mean():.2f}, median={df[col].median():.2f}, std={df[col].std():.2f}")

print(f"\nTop 3 most common hook types (by average probability):")
if hook_types:
    avg_probs = {col.replace("hook_", ""): df[col].mean() for col in hook_types if col in df.columns}
    for hook, prob in sorted(avg_probs.items(), key=lambda x: x[1], reverse=True)[:3]:
        print(f"  {hook:30s}: {prob:.3f}")

print("\n" + "=" * 80)
print("Analysis complete!")
print("=" * 80)
print("\nSignificance levels: *** p<0.01, ** p<0.05, * p<0.1")
