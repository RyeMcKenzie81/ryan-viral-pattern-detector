"""
Export Hook Intelligence data from Supabase to CSV for analysis module.

This script fetches video data with hook intelligence features from Supabase
and exports it to CSV format compatible with the analysis/ module.

Required columns:
- post_id, account_id, posted_at, followers, views, hours_since_post
- hook_prob_result_first, hook_prob_shock_violation, hook_prob_reveal_transform,
  hook_prob_relatable_slice, hook_prob_humor_gag, hook_prob_tension_wait
- payoff_time_sec, face_pct_1s, cuts_in_2s, overlay_chars_per_sec_2s
"""
import os
import json
import pandas as pd
import numpy as np
from datetime import datetime, timezone
from dotenv import load_dotenv
from viraltracker.core.database import get_supabase_client

# Load environment variables
load_dotenv()

# Initialize Supabase client
supabase = get_supabase_client()

print("=" * 80)
print("Hook Intelligence Data Export to CSV")
print("=" * 80)

# Fetch video analyses with hook features and post metadata
print("\nFetching video analyses with hook intelligence data...")
response = supabase.table("video_analysis").select(
    """
    post_id,
    hook_features,
    posts!inner(
        post_id,
        account_id,
        posted_at,
        views,
        likes,
        comments
    )
    """
).not_.is_("hook_features", "null").execute()

# Now fetch account data separately
print("Fetching account follower counts...")
account_response = supabase.table("accounts").select("id, follower_count").execute()
account_followers = {acc["id"]: acc.get("follower_count", 0) for acc in account_response.data}

data = response.data
print(f"Found {len(data)} videos with hook intelligence data")

if len(data) == 0:
    print("No data found with hook_features. Exiting.")
    exit(1)

# Parse hook features and create flat dataframe
records = []
now = datetime.now(timezone.utc)

for record in data:
    hook_features = record.get("hook_features", {})
    posts = record.get("posts", {})

    if not hook_features or not posts:
        continue

    # Extract post metadata
    post_id = posts.get("post_id")
    account_id = posts.get("account_id")
    posted_at = posts.get("posted_at")
    views = posts.get("views", 0)
    likes = posts.get("likes", 0)
    comments = posts.get("comments", 0)

    # Get follower count from the accounts lookup
    followers = account_followers.get(account_id, 0)

    # Calculate hours since post
    hours_since_post = None
    if posted_at:
        try:
            posted_dt = datetime.fromisoformat(posted_at.replace('Z', '+00:00'))
            hours_since_post = (now - posted_dt).total_seconds() / 3600
        except Exception as e:
            print(f"Warning: Could not parse posted_at for {post_id}: {e}")

    # Calculate engagement rate (without shares since not in database)
    engagement_rate = ((likes + comments) / views * 100) if views > 0 else 0

    # Extract hook type probabilities
    hook_type_probs = hook_features.get("hook_type_probs", {})

    # Extract timing features
    payoff_time_sec = hook_features.get("payoff_time_sec")

    # Extract windowed metrics for 1s and 2s windows
    windows = hook_features.get("hook_windows", {})
    face_pct_1s = None
    cuts_in_2s = None
    overlay_chars_per_sec_2s = None

    if windows:
        # Extract face_pct from w1_0_1s window
        window_1s = windows.get("w1_0_1s", {})
        if isinstance(window_1s, dict):
            face_pct_1s = window_1s.get("face_pct")

        # Extract cuts and overlay_chars_per_sec from w2_0_2s window
        window_2s = windows.get("w2_0_2s", {})
        if isinstance(window_2s, dict):
            cuts_count = window_2s.get("cuts")
            if cuts_count is not None:
                cuts_in_2s = cuts_count  # Already in "cuts within 2s" format

            overlay_cps = window_2s.get("overlay_chars_per_sec")
            if overlay_cps is not None:
                overlay_chars_per_sec_2s = overlay_cps

    # Build record
    row = {
        # Identifiers & meta
        "post_id": post_id,
        "account_id": account_id,
        "posted_at": posted_at,
        "followers": followers,
        "views": views,
        "hours_since_post": hours_since_post,

        # Performance metrics (bonus)
        "likes": likes,
        "comments": comments,
        "engagement_rate": engagement_rate,

        # Hook type probabilities
        "hook_prob_result_first": hook_type_probs.get("result_first"),
        "hook_prob_shock_violation": hook_type_probs.get("shock_violation"),
        "hook_prob_reveal_transform": hook_type_probs.get("reveal_transform"),
        "hook_prob_relatable_slice": hook_type_probs.get("relatable_slice"),
        "hook_prob_humor_gag": hook_type_probs.get("humor_gag"),
        "hook_prob_tension_wait": hook_type_probs.get("tension_wait"),
        "hook_prob_direct_callout": hook_type_probs.get("direct_callout"),
        "hook_prob_challenge_stakes": hook_type_probs.get("challenge_stakes"),
        "hook_prob_authority_flex": hook_type_probs.get("authority_flex"),

        # Continuous features
        "payoff_time_sec": payoff_time_sec,
        "face_pct_1s": face_pct_1s,
        "cuts_in_2s": cuts_in_2s,
        "overlay_chars_per_sec_2s": overlay_chars_per_sec_2s,
    }

    records.append(row)

# Create DataFrame
df = pd.DataFrame(records)
print(f"\nDataFrame created with {len(df)} records and {len(df.columns)} columns")

# Data quality checks
print("\n" + "=" * 80)
print("DATA QUALITY CHECKS")
print("=" * 80)

required_cols = [
    "post_id", "account_id", "posted_at", "followers", "views", "hours_since_post"
]

print("\nRequired columns:")
for col in required_cols:
    non_null_count = df[col].notna().sum()
    null_count = df[col].isna().sum()
    print(f"  {col:25s}: {non_null_count:4d} non-null, {null_count:4d} null")

print("\nHook probability columns:")
hook_prob_cols = [col for col in df.columns if col.startswith("hook_prob_")]
for col in hook_prob_cols:
    non_null_count = df[col].notna().sum()
    null_count = df[col].isna().sum()
    mean_val = df[col].mean() if non_null_count > 0 else 0
    print(f"  {col:35s}: {non_null_count:4d} non-null, {null_count:4d} null, mean={mean_val:.3f}")

print("\nContinuous feature columns:")
cont_cols = ["payoff_time_sec", "face_pct_1s", "cuts_in_2s", "overlay_chars_per_sec_2s"]
for col in cont_cols:
    if col in df.columns:
        non_null_count = df[col].notna().sum()
        null_count = df[col].isna().sum()
        mean_val = df[col].mean() if non_null_count > 0 else 0
        print(f"  {col:35s}: {non_null_count:4d} non-null, {null_count:4d} null, mean={mean_val:.3f}")

# Summary statistics
print("\n" + "=" * 80)
print("SUMMARY STATISTICS")
print("=" * 80)

print(f"\nTotal videos: {len(df)}")
print(f"\nUnique accounts: {df['account_id'].nunique()}")
print(f"\nViews range: {df['views'].min():.0f} - {df['views'].max():.0f} (median: {df['views'].median():.0f})")
print(f"Followers range: {df['followers'].min():.0f} - {df['followers'].max():.0f} (median: {df['followers'].median():.0f})")
print(f"Engagement rate range: {df['engagement_rate'].min():.2f}% - {df['engagement_rate'].max():.2f}% (median: {df['engagement_rate'].median():.2f}%)")

# Export to CSV
output_path = "data/hook_intelligence_export.csv"
os.makedirs("data", exist_ok=True)

df.to_csv(output_path, index=False)
print("\n" + "=" * 80)
print(f"✓ CSV exported successfully to: {output_path}")
print("=" * 80)

print("\nNext steps:")
print("1. Run hook analysis module:")
print(f"   python -m analysis.run_hook_analysis --csv {output_path} --outdir results")
print("\n2. Review generated playbook:")
print("   cat results/playbook.md")
