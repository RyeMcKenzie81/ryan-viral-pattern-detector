#!/usr/bin/env python3
"""
Ryan's Viral Pattern Detector - Complete Implementation

A CLI tool for scraping Instagram posts, analyzing viral patterns, and exporting data for review.
"""

import os
import json
import time
import logging
from datetime import datetime, timedelta
from typing import List, Dict, Optional, Tuple, Any
from pathlib import Path

import click
import pandas as pd
import requests
from dotenv import load_dotenv
from tqdm import tqdm
from tenacity import retry, stop_after_attempt, wait_exponential
from supabase import create_client, Client

# Load environment variables
load_dotenv()

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format="[%(asctime)s] %(levelname)s: %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S"
)
logger = logging.getLogger(__name__)

# Configuration from environment
APIFY_TOKEN = os.getenv("APIFY_TOKEN")
APIFY_ACTOR_ID = os.getenv("APIFY_ACTOR_ID", "apify/instagram-scraper")
SUPABASE_URL = os.getenv("SUPABASE_URL")
SUPABASE_SERVICE_KEY = os.getenv("SUPABASE_SERVICE_KEY")
DAYS_BACK = int(os.getenv("DAYS_BACK", 120))
CONCURRENCY = int(os.getenv("CONCURRENCY", 5))
POST_TYPE = os.getenv("POST_TYPE", "reels")
OUTLIER_SD_THRESHOLD = float(os.getenv("OUTLIER_SD_THRESHOLD", 3.0))
EXPORT_DIR = os.getenv("EXPORT_DIR", "./exports")
MAX_USERNAMES_PER_RUN = int(os.getenv("MAX_USERNAMES_PER_RUN", 100))
MAX_POSTS_PER_ACCOUNT = int(os.getenv("MAX_POSTS_PER_ACCOUNT", 10000))
CHUNK_SIZE_FOR_DB_OPS = int(os.getenv("CHUNK_SIZE_FOR_DB_OPS", 1000))
APIFY_TIMEOUT_SECONDS = int(os.getenv("APIFY_TIMEOUT_SECONDS", 300))

# Validation rules
VALIDATION_RULES = {
    "reject_reason": ["IRR", "NSFW", "LEN", "AUD", "CELEB", "OTH"]
}


def get_supabase_client() -> Client:
    """Initialize and return Supabase client."""
    if not SUPABASE_URL or not SUPABASE_SERVICE_KEY:
        raise ValueError("Missing Supabase configuration. Check SUPABASE_URL and SUPABASE_SERVICE_KEY.")
    return create_client(SUPABASE_URL, SUPABASE_SERVICE_KEY)


def load_usernames(path: str) -> List[str]:
    """
    Load usernames from CSV file.

    Args:
        path: Path to usernames file

    Returns:
        List of username strings

    Raises:
        FileNotFoundError: If file doesn't exist
        ValueError: If file format is invalid
    """
    if not os.path.exists(path):
        raise FileNotFoundError(f"Usernames file not found: {path}")

    try:
        if path.endswith('.csv'):
            df = pd.read_csv(path)
            if 'username' in df.columns:
                usernames = df['username'].dropna().astype(str).tolist()
            else:
                # Assume first column is usernames
                usernames = df.iloc[:, 0].dropna().astype(str).tolist()
        else:
            # Try reading as plain text
            with open(path, 'r') as f:
                usernames = [line.strip() for line in f if line.strip()]
    except Exception as e:
        raise ValueError(f"Error reading usernames file: {e}")

    # Clean usernames (remove @ if present)
    usernames = [u.lstrip('@') for u in usernames if u.strip()]

    if not usernames:
        raise ValueError("No valid usernames found in file")

    logger.info(f"Loaded {len(usernames)} usernames from {path}")
    return usernames


@retry(stop=stop_after_attempt(3), wait=wait_exponential(multiplier=2, min=2, max=8))
def start_apify_run(usernames: List[str], days_back: int = 120, post_type: str = "reels") -> str:
    """
    Start Apify actor run for Instagram scraping.

    Args:
        usernames: List of Instagram usernames
        days_back: Number of days to scrape back
        post_type: Type of posts to scrape (posts, reels, tagged)

    Returns:
        Apify run ID

    Raises:
        requests.RequestException: If API call fails
    """
    if not APIFY_TOKEN:
        raise ValueError("Missing APIFY_TOKEN environment variable")

    # Configure actor input for this specific Instagram scraper
    # Convert usernames to Instagram profile URLs
    direct_urls = [f"https://www.instagram.com/{username}/" for username in usernames]

    actor_input = {
        "directUrls": direct_urls,
        "resultsType": "posts",
        "resultsLimit": 200,
        "onlyPostsNewerThan": f"{days_back} days",
        "addParentData": False
    }

    # Add reels-specific parameter if post_type is reels
    if post_type == "reels":
        actor_input["isUserReelFeedURL"] = True

    url = f"https://api.apify.com/v2/acts/{APIFY_ACTOR_ID}/runs"
    headers = {
        "Authorization": f"Bearer {APIFY_TOKEN}",
        "Content-Type": "application/json"
    }

    logger.info(f"Starting Apify run for {len(usernames)} usernames ({days_back} days back, {post_type})")

    response = requests.post(url, json=actor_input, headers=headers)
    response.raise_for_status()

    run_data = response.json()
    run_id = run_data["data"]["id"]

    logger.info(f"Apify run started: {run_id}")
    return run_id


@retry(stop=stop_after_attempt(3), wait=wait_exponential(multiplier=2, min=2, max=8))
def poll_apify_run(run_id: str, timeout: int = 300) -> Dict[str, Any]:
    """
    Poll Apify run until completion using exponential backoff.

    Args:
        run_id: Apify run identifier
        timeout: Maximum seconds to wait

    Returns:
        Dict with datasetId and status

    Raises:
        TimeoutError: If run doesn't complete within timeout
    """
    if not APIFY_TOKEN:
        raise ValueError("Missing APIFY_TOKEN environment variable")

    url = f"https://api.apify.com/v2/actor-runs/{run_id}"
    headers = {"Authorization": f"Bearer {APIFY_TOKEN}"}

    start_time = time.time()
    wait_time = 2

    logger.info(f"Polling Apify run {run_id}...")

    while time.time() - start_time < timeout:
        response = requests.get(url, headers=headers)
        response.raise_for_status()

        run_data = response.json()
        status = run_data["data"]["status"]

        if status in ["SUCCEEDED", "FAILED", "ABORTED", "TIMED-OUT"]:
            if status == "SUCCEEDED":
                dataset_id = run_data["data"]["defaultDatasetId"]
                logger.info(f"Apify run completed successfully. Dataset ID: {dataset_id}")
                return {"datasetId": dataset_id, "status": status}
            else:
                raise RuntimeError(f"Apify run failed with status: {status}")

        logger.info(f"Run status: {status}. Waiting {wait_time}s...")
        time.sleep(wait_time)
        wait_time = min(wait_time * 1.5, 30)  # Exponential backoff with max 30s

    raise TimeoutError(f"Apify run timeout after {timeout}s")


@retry(stop=stop_after_attempt(3), wait=wait_exponential(multiplier=2, min=2, max=8))
def fetch_dataset(dataset_id: str) -> List[Dict]:
    """
    Fetch complete dataset from Apify with retry logic.

    Args:
        dataset_id: Apify dataset identifier

    Returns:
        List of post dictionaries
    """
    if not APIFY_TOKEN:
        raise ValueError("Missing APIFY_TOKEN environment variable")

    url = f"https://api.apify.com/v2/datasets/{dataset_id}/items"
    headers = {"Authorization": f"Bearer {APIFY_TOKEN}"}

    logger.info(f"Fetching dataset {dataset_id}...")

    response = requests.get(url, headers=headers)
    response.raise_for_status()

    items = response.json()
    logger.info(f"Fetched {len(items)} items from dataset")

    return items


def normalize_items(items: List[Dict], username: str = None) -> pd.DataFrame:
    """
    Normalize Apify items to standard DataFrame format.

    Args:
        items: Raw Apify post data
        username: Account handle (optional, will use ownerUsername from items)

    Returns:
        DataFrame with columns: account, post_url, post_id, posted_at,
        views, likes, comments, caption, length_sec
    """
    normalized_data = []

    for item in items:
        try:
            # Extract basic fields (this actor has different field names)
            post_data = {
                "account": item.get("ownerUsername", username or "unknown"),
                "post_url": item.get("url", ""),
                "post_id": item.get("shortCode", ""),
                "posted_at": item.get("timestamp"),
                "likes": item.get("likesCount", 0),
                "comments": item.get("commentsCount", 0),
                "caption": item.get("caption", "")[:2200] if item.get("caption") else "",
                "length_sec": item.get("videoDuration")
            }

            # Handle views (priority: videoViewCount > videoPlayCount > likesCount)
            views = (item.get("videoViewCount") or
                    item.get("videoPlayCount") or
                    item.get("likesCount", 0))
            post_data["views"] = max(0, int(views)) if views is not None else 0

            # Validate and convert data types
            post_data["likes"] = max(0, int(post_data["likes"]) if post_data["likes"] else 0)
            post_data["comments"] = max(0, int(post_data["comments"]) if post_data["comments"] else 0)

            if post_data["length_sec"]:
                try:
                    post_data["length_sec"] = max(1, min(3600, int(float(post_data["length_sec"]))))
                except:
                    post_data["length_sec"] = None

            # Parse timestamp
            if post_data["posted_at"]:
                try:
                    post_data["posted_at"] = pd.to_datetime(post_data["posted_at"]).isoformat()
                except:
                    post_data["posted_at"] = None

            # Skip if essential fields are missing
            if not post_data["post_url"] or not post_data["account"]:
                logger.warning(f"Skipping item with missing essential fields")
                continue

            normalized_data.append(post_data)

        except Exception as e:
            logger.warning(f"Error normalizing item: {e}")
            continue

    df = pd.DataFrame(normalized_data)
    if len(df) > 0:
        logger.info(f"Normalized {len(df)} posts from {df['account'].nunique()} accounts")
    else:
        logger.warning("No posts were successfully normalized")

    return df


def upsert_accounts(df: pd.DataFrame, supabase_client: Client) -> Dict[str, str]:
    """
    Upsert accounts to database and return handle->account_id mapping.

    Args:
        df: DataFrame with 'account' column
        supabase_client: Initialized Supabase client

    Returns:
        Dict mapping handle to account_id (UUID)
    """
    unique_handles = df['account'].unique().tolist()
    account_map = {}

    for handle in tqdm(unique_handles, desc="Upserting accounts"):
        try:
            # Try to get existing account
            result = supabase_client.table("accounts").select("id").eq("handle", handle).execute()

            if result.data:
                account_id = result.data[0]["id"]
            else:
                # Insert new account
                result = supabase_client.table("accounts").insert({"handle": handle}).execute()
                account_id = result.data[0]["id"]

            account_map[handle] = account_id

        except Exception as e:
            logger.error(f"Error upserting account {handle}: {e}")
            continue

    logger.info(f"Upserted {len(account_map)} accounts")
    return account_map


def upsert_posts(df: pd.DataFrame, account_map: Dict[str, str], supabase_client: Client):
    """
    Upsert posts to database with account relationships.

    Args:
        df: Normalized posts DataFrame
        account_map: Handle to account_id mapping
        supabase_client: Initialized Supabase client
    """
    # Add account_id to DataFrame
    df['account_id'] = df['account'].map(account_map)

    # Remove rows where account_id is missing
    df = df.dropna(subset=['account_id'])

    # Prepare data for upsert
    posts_data = df[[
        'account_id', 'post_url', 'post_id', 'posted_at',
        'views', 'likes', 'comments', 'caption', 'length_sec'
    ]].to_dict('records')

    # Process in chunks
    total_posts = len(posts_data)
    chunks = [posts_data[i:i + CHUNK_SIZE_FOR_DB_OPS]
              for i in range(0, total_posts, CHUNK_SIZE_FOR_DB_OPS)]

    upserted_count = 0

    for chunk in tqdm(chunks, desc="Upserting posts"):
        try:
            # Use upsert to handle duplicates
            result = supabase_client.table("posts").upsert(
                chunk,
                on_conflict="post_url"
            ).execute()
            upserted_count += len(result.data)

        except Exception as e:
            logger.error(f"Error upserting posts chunk: {e}")
            continue

    logger.info(f"Upserted {upserted_count} posts")


def compute_summaries(supabase_client: Client):
    """
    Compute per-account statistics with trimmed mean/SD.

    Args:
        supabase_client: Initialized Supabase client
    """
    logger.info("Computing account summaries...")

    # Get all posts with views > 0
    result = supabase_client.table("posts").select("account_id, views").gt("views", 0).execute()

    if not result.data:
        logger.warning("No posts with views found")
        return

    df_posts = pd.DataFrame(result.data)
    summaries = []

    for account_id in tqdm(df_posts['account_id'].unique(), desc="Computing summaries"):
        account_posts = df_posts[df_posts['account_id'] == account_id]['views']

        if len(account_posts) < 3:  # Need at least 3 posts for meaningful stats
            continue

        try:
            # Calculate percentiles
            p10 = float(account_posts.quantile(0.1))
            p90 = float(account_posts.quantile(0.9))

            # Trim data to [p10, p90] range
            trimmed_views = account_posts[(account_posts >= p10) & (account_posts <= p90)]

            if len(trimmed_views) < 2:
                continue

            # Calculate trimmed statistics
            trimmed_mean = float(trimmed_views.mean())
            trimmed_sd = float(trimmed_views.std(ddof=0))  # Population standard deviation

            summaries.append({
                "account_id": account_id,
                "n_posts": len(account_posts),
                "p10_views": p10,
                "p90_views": p90,
                "trimmed_mean_views": trimmed_mean,
                "trimmed_sd_views": trimmed_sd
            })

        except Exception as e:
            logger.warning(f"Error computing summary for account {account_id}: {e}")
            continue

    if summaries:
        # Upsert summaries
        result = supabase_client.table("account_summaries").upsert(
            summaries,
            on_conflict="account_id"
        ).execute()

        logger.info(f"Computed summaries for {len(summaries)} accounts")
    else:
        logger.warning("No account summaries computed")


def flag_outliers(threshold: float, supabase_client: Client):
    """
    Set outlier flag in post_review based on statistical threshold.

    Args:
        threshold: Number of standard deviations for outlier detection
        supabase_client: Initialized Supabase client
    """
    logger.info(f"Flagging outliers with threshold {threshold} SD...")

    # Get posts and their account summaries using separate queries
    posts_result = supabase_client.table("posts").select("id, account_id, views").gt("views", 0).execute()
    summaries_result = supabase_client.table("account_summaries").select("*").execute()

    if not posts_result.data or not summaries_result.data:
        logger.warning("No posts or summaries found for outlier analysis")
        return

    # Create lookup for summaries
    summaries_map = {s["account_id"]: s for s in summaries_result.data}

    outlier_posts = []

    for post in posts_result.data:
        post_id = post["id"]
        account_id = post["account_id"]
        views = post["views"]

        if account_id not in summaries_map:
            continue

        summary = summaries_map[account_id]
        mean_views = float(summary["trimmed_mean_views"])
        sd_views = float(summary["trimmed_sd_views"])

        if sd_views <= 0:
            continue

        # Calculate outlier threshold
        outlier_threshold = mean_views + (threshold * sd_views)
        is_outlier = views > outlier_threshold

        if is_outlier:
            outlier_posts.append(post_id)

    if outlier_posts:
        # Update post_review table (create rows if they don't exist)
        for post_id in tqdm(outlier_posts, desc="Flagging outliers"):
            try:
                # Upsert post_review record
                supabase_client.table("post_review").upsert({
                    "post_id": post_id,
                    "outlier": True
                }, on_conflict="post_id").execute()

            except Exception as e:
                logger.warning(f"Error flagging outlier {post_id}: {e}")
                continue

        logger.info(f"Flagged {len(outlier_posts)} outliers")
    else:
        logger.info("No outliers found")


def export_outliers_csv(path: str, threshold: float, supabase_client: Client):
    """
    Export outliers for video download.

    Args:
        path: Output CSV path
        threshold: SD threshold used for filtering
        supabase_client: Initialized Supabase client
    """
    logger.info(f"Exporting outliers to {path}...")

    # Get outliers using table joins
    outliers_result = supabase_client.table("post_review").select("post_id").eq("outlier", True).is_("keep", "null").execute()

    if not outliers_result.data:
        logger.warning("No outliers found for export")
        return

    outlier_post_ids = [row["post_id"] for row in outliers_result.data]

    # Get post details for outliers with views
    posts_result = supabase_client.table("posts").select("id, post_url, post_id, account_id, views").in_("id", outlier_post_ids).execute()

    # Get account handles and summaries
    account_ids = list(set([p["account_id"] for p in posts_result.data]))
    accounts_result = supabase_client.table("accounts").select("id, handle").in_("id", account_ids).execute()
    summaries_result = supabase_client.table("account_summaries").select("account_id, trimmed_mean_views, trimmed_sd_views").in_("account_id", account_ids).execute()

    # Create mappings
    account_map = {a["id"]: a["handle"] for a in accounts_result.data}
    summaries_map = {s["account_id"]: s for s in summaries_result.data}

    # Combine data with statistics
    export_data = []
    for post in posts_result.data:
        account_id = post["account_id"]
        views = post["views"] or 0
        summary = summaries_map.get(account_id, {})

        trimmed_mean = float(summary.get("trimmed_mean_views", 0))
        trimmed_sd = float(summary.get("trimmed_sd_views", 1))

        # Calculate how many standard deviations away from mean
        if trimmed_sd > 0:
            sd_away = (views - trimmed_mean) / trimmed_sd
        else:
            sd_away = 0

        export_data.append({
            "post_url": post["post_url"],
            "account": account_map.get(account_id, "unknown"),
            "post_id": post["post_id"],
            "views": views,
            "trimmed_mean_views": round(trimmed_mean, 0),
            "standard_deviations_away": round(sd_away, 2)
        })

    if export_data:
        # Sort by standard deviations away (highest first)
        export_data.sort(key=lambda x: x["standard_deviations_away"], reverse=True)

        df = pd.DataFrame(export_data)
        os.makedirs(os.path.dirname(path), exist_ok=True)
        df.to_csv(path, index=False)
        logger.info(f"Exported {len(df)} outliers to {path}")
    else:
        logger.warning("No outliers found for export")


def export_review_csv(path: str, supabase_client: Client):
    """
    Export full dataset for VA review.

    Args:
        path: Output CSV path
        supabase_client: Initialized Supabase client
    """
    logger.info(f"Exporting review data to {path}...")

    # Get all posts
    posts_result = supabase_client.table("posts").select("*").execute()
    if not posts_result.data:
        logger.warning("No posts found for review export")
        return

    # Get all accounts and summaries
    account_ids = list(set([p["account_id"] for p in posts_result.data]))
    accounts_result = supabase_client.table("accounts").select("id, handle").in_("id", account_ids).execute()
    summaries_result = supabase_client.table("account_summaries").select("account_id, trimmed_mean_views, trimmed_sd_views").in_("account_id", account_ids).execute()

    # Create mappings
    account_map = {a["id"]: a["handle"] for a in accounts_result.data}
    summaries_map = {s["account_id"]: s for s in summaries_result.data}

    # Get all reviews
    post_ids = [p["id"] for p in posts_result.data]
    reviews_result = supabase_client.table("post_review").select("*").in_("post_id", post_ids).execute()
    reviews_map = {r["post_id"]: r for r in reviews_result.data}

    # Combine data with statistics
    export_data = []
    for post in posts_result.data:
        review = reviews_map.get(post["id"], {})
        account_id = post["account_id"]
        views = post["views"] or 0
        summary = summaries_map.get(account_id, {})

        trimmed_mean = float(summary.get("trimmed_mean_views", 0))
        trimmed_sd = float(summary.get("trimmed_sd_views", 1))

        # Calculate how many standard deviations away from mean
        if trimmed_sd > 0:
            sd_away = (views - trimmed_mean) / trimmed_sd
        else:
            sd_away = 0

        export_data.append({
            "account": account_map.get(account_id, "unknown"),
            "post_url": post["post_url"],
            "posted_at": post["posted_at"],
            "views": views,
            "likes": post["likes"],
            "comments": post["comments"],
            "caption": post["caption"],
            "length_sec": post["length_sec"],
            "outlier": review.get("outlier", False),
            "trimmed_mean_views": round(trimmed_mean, 0),
            "standard_deviations_away": round(sd_away, 2),
            "keep": review.get("keep"),
            "reject_reason": review.get("reject_reason"),
            "reject_notes": review.get("reject_notes"),
            "video_file_url": review.get("video_file_url")
        })

    df = pd.DataFrame(export_data)
    # Sort by standard deviations away (highest first), then account
    df = df.sort_values(["standard_deviations_away", "account"], ascending=[False, True])

    os.makedirs(os.path.dirname(path), exist_ok=True)
    df.to_csv(path, index=False)
    logger.info(f"Exported {len(df)} posts for review to {path}")


def export_ai_jsonl(path: str, threshold: float, supabase_client: Client):
    """
    Export JSONL for AI batch analysis.

    Args:
        path: Output JSONL path
        threshold: SD threshold used for filtering
        supabase_client: Initialized Supabase client
    """
    logger.info(f"Exporting AI batch data to {path}...")

    # Get outliers not yet reviewed
    outliers_result = supabase_client.table("post_review").select("post_id, video_file_url").eq("outlier", True).is_("keep", "null").execute()

    if not outliers_result.data:
        logger.warning("No posts found for AI export")
        return

    # Get post details for outliers
    outlier_post_ids = [row["post_id"] for row in outliers_result.data]
    posts_result = supabase_client.table("posts").select("id, post_url, caption, views, length_sec").in_("id", outlier_post_ids).execute()

    # Create review mapping
    reviews_map = {r["post_id"]: r for r in outliers_result.data}

    # Combine data and sort by views
    export_data = []
    for post in posts_result.data:
        review = reviews_map.get(post["id"], {})
        export_data.append({
            "post_url": post["post_url"],
            "caption": post["caption"],
            "views": post["views"],
            "length_sec": post["length_sec"],
            "video_file_url": review.get("video_file_url")
        })

    # Sort by views descending
    export_data.sort(key=lambda x: x["views"] or 0, reverse=True)

    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, 'w') as f:
        for row in export_data:
            json.dump(row, f)
            f.write('\n')

    logger.info(f"Exported {len(export_data)} posts for AI analysis to {path}")


def import_review_csv(path: str, supabase_client: Client):
    """
    Import VA-edited review CSV back to database.

    Args:
        path: Path to edited CSV file
        supabase_client: Initialized Supabase client
    """
    logger.info(f"Importing review data from {path}...")

    if not os.path.exists(path):
        raise FileNotFoundError(f"Review file not found: {path}")

    df = pd.read_csv(path)

    # Validate required columns
    required_cols = ['post_url', 'keep', 'reject_reason', 'reject_notes']
    missing_cols = [col for col in required_cols if col not in df.columns]
    if missing_cols:
        raise ValueError(f"Missing required columns: {missing_cols}")

    # Validate reject_reason values
    valid_reasons = VALIDATION_RULES["reject_reason"]
    invalid_reasons = df[df['reject_reason'].notna()]['reject_reason'].unique()
    invalid_reasons = [r for r in invalid_reasons if r not in valid_reasons]
    if invalid_reasons:
        raise ValueError(f"Invalid reject_reason values: {invalid_reasons}")

    updates = []
    for _, row in df.iterrows():
        if pd.notna(row['keep']) or pd.notna(row['reject_reason']) or pd.notna(row['reject_notes']):
            update_data = {
                "post_url": row['post_url'],
                "keep": bool(row['keep']) if pd.notna(row['keep']) else None,
                "reject_reason": row['reject_reason'] if pd.notna(row['reject_reason']) else None,
                "reject_notes": row['reject_notes'] if pd.notna(row['reject_notes']) else None
            }
            updates.append(update_data)

    # Update records
    updated_count = 0
    for update in tqdm(updates, desc="Importing reviews"):
        try:
            # Get post_id from post_url
            result = supabase_client.table("posts").select("id").eq("post_url", update["post_url"]).execute()

            if not result.data:
                logger.warning(f"Post not found: {update['post_url']}")
                continue

            post_id = result.data[0]["id"]

            # Update post_review
            review_data = {k: v for k, v in update.items() if k != "post_url"}
            review_data["post_id"] = post_id

            supabase_client.table("post_review").upsert(
                review_data,
                on_conflict="post_id"
            ).execute()

            updated_count += 1

        except Exception as e:
            logger.warning(f"Error updating review for {update['post_url']}: {e}")
            continue

    logger.info(f"Updated {updated_count} review records")


def upload_videos(dir_path: str, supabase_client: Client) -> int:
    """
    Optional: Upload video files to Supabase Storage.

    Args:
        dir_path: Directory containing video files
        supabase_client: Initialized Supabase client

    Returns:
        Number of videos uploaded
    """
    logger.info(f"Uploading videos from {dir_path}...")

    if not os.path.exists(dir_path):
        raise FileNotFoundError(f"Directory not found: {dir_path}")

    video_extensions = ['.mp4', '.mov', '.webm', '.avi']
    video_files = []

    for ext in video_extensions:
        video_files.extend(Path(dir_path).glob(f"*{ext}"))

    if not video_files:
        logger.warning(f"No video files found in {dir_path}")
        return 0

    uploaded_count = 0

    for video_file in tqdm(video_files, desc="Uploading videos"):
        try:
            # Extract post info from filename (format: username_postid.ext)
            filename = video_file.stem
            if '_' not in filename:
                logger.warning(f"Invalid filename format: {video_file.name}")
                continue

            username, post_id = filename.split('_', 1)

            # Upload to Supabase Storage
            with open(video_file, 'rb') as f:
                result = supabase_client.storage.from_("videos").upload(
                    f"downloads/{video_file.name}",
                    f.read()
                )

            if result.error:
                logger.warning(f"Upload failed for {video_file.name}: {result.error}")
                continue

            # Get public URL
            public_url = supabase_client.storage.from_("videos").get_public_url(f"downloads/{video_file.name}")

            # Update post_review with video URL
            post_result = supabase_client.table("posts").select("id").eq("post_id", post_id).execute()

            if post_result.data:
                post_db_id = post_result.data[0]["id"]
                supabase_client.table("post_review").upsert({
                    "post_id": post_db_id,
                    "video_file_url": public_url
                }, on_conflict="post_id").execute()

                uploaded_count += 1

        except Exception as e:
            logger.warning(f"Error uploading {video_file.name}: {e}")
            continue

    logger.info(f"Uploaded {uploaded_count} videos")
    return uploaded_count


# CLI Commands
@click.group()
@click.version_option(version="1.0.0")
def cli():
    """Ryan's Viral Pattern Detector - Analyze Instagram viral patterns"""
    pass


@cli.command()
@click.option('--usernames', default='./usernames.csv', help='Path to usernames CSV file')
@click.option('--days', default=DAYS_BACK, help='Number of days to scrape back')
@click.option('--concurrency', default=CONCURRENCY, help='Number of concurrent requests')
@click.option('--post-type', default=POST_TYPE,
              type=click.Choice(['all', 'posts', 'reels', 'tagged']),
              help='Type of posts to scrape')
def scrape(usernames, days, concurrency, post_type):
    """Scrape Instagram posts for specified usernames"""
    try:
        supabase = get_supabase_client()

        # Load usernames
        username_list = load_usernames(usernames)

        if len(username_list) > MAX_USERNAMES_PER_RUN:
            logger.warning(f"Too many usernames ({len(username_list)}). Processing first {MAX_USERNAMES_PER_RUN}")
            username_list = username_list[:MAX_USERNAMES_PER_RUN]

        # Start Apify run
        run_id = start_apify_run(username_list, days, post_type)

        # Poll for completion
        result = poll_apify_run(run_id, APIFY_TIMEOUT_SECONDS)

        # Fetch and process data
        items = fetch_dataset(result["datasetId"])

        if not items:
            logger.warning("No data returned from Apify")
            return

        # Save raw data
        os.makedirs("data/raw_apify", exist_ok=True)
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        raw_path = f"data/raw_apify/raw_{timestamp}.json"
        with open(raw_path, 'w') as f:
            json.dump(items, f, indent=2)
        logger.info(f"Saved raw data to {raw_path}")

        # Normalize and save processed data
        # This actor returns all items together, not separated by username
        combined_df = normalize_items(items)

        if len(combined_df) > 0:

            # Save normalized data
            os.makedirs("data/normalized", exist_ok=True)
            normalized_path = f"data/normalized/normalized_{timestamp}.csv"
            combined_df.to_csv(normalized_path, index=False)
            logger.info(f"Saved normalized data to {normalized_path}")

            # Upsert to database
            account_map = upsert_accounts(combined_df, supabase)
            upsert_posts(combined_df, account_map, supabase)

            logger.info(f"Scraping completed successfully. Total posts: {len(combined_df)}")
        else:
            logger.warning("No posts to process")

    except Exception as e:
        logger.error(f"Scraping failed: {e}")
        raise click.ClickException(str(e))


@cli.command()
@click.option('--sd-threshold', default=OUTLIER_SD_THRESHOLD, help='Standard deviation threshold for outliers')
def analyze(sd_threshold):
    """Analyze posts and flag outliers"""
    try:
        supabase = get_supabase_client()

        # Compute account summaries
        compute_summaries(supabase)

        # Flag outliers
        flag_outliers(sd_threshold, supabase)

        logger.info("Analysis completed successfully")

    except Exception as e:
        logger.error(f"Analysis failed: {e}")
        raise click.ClickException(str(e))


@cli.command()
@click.option('--format', default='outliers,review,ai', help='Export formats (comma-separated)')
@click.option('--sd-threshold', default=OUTLIER_SD_THRESHOLD, help='Standard deviation threshold')
def export(format, sd_threshold):
    """Export data for processing"""
    try:
        supabase = get_supabase_client()

        formats = [f.strip() for f in format.split(',')]
        timestamp = datetime.now().strftime("%Y-%m-%d")

        os.makedirs(EXPORT_DIR, exist_ok=True)

        if 'outliers' in formats:
            path = f"{EXPORT_DIR}/outliers_to_download_{timestamp}.csv"
            export_outliers_csv(path, sd_threshold, supabase)

        if 'review' in formats:
            path = f"{EXPORT_DIR}/review_export_{timestamp}.csv"
            export_review_csv(path, supabase)

        if 'ai' in formats:
            path = f"{EXPORT_DIR}/ai_batch_{timestamp}.jsonl"
            export_ai_jsonl(path, sd_threshold, supabase)

        logger.info("Export completed successfully")

    except Exception as e:
        logger.error(f"Export failed: {e}")
        raise click.ClickException(str(e))


@cli.command()
@click.option('--path', required=True, help='Path to edited review CSV')
def import_review(path):
    """Import VA-edited review CSV"""
    try:
        supabase = get_supabase_client()
        import_review_csv(path, supabase)
        logger.info("Review import completed successfully")

    except Exception as e:
        logger.error(f"Review import failed: {e}")
        raise click.ClickException(str(e))


@cli.command()
@click.option('--from', 'from_dir', default='./downloads', help='Directory containing video files')
def upload_videos(from_dir):
    """Upload video files to Supabase Storage"""
    try:
        supabase = get_supabase_client()
        count = upload_videos(from_dir, supabase)
        logger.info(f"Upload completed successfully. {count} videos uploaded.")

    except Exception as e:
        logger.error(f"Video upload failed: {e}")
        raise click.ClickException(str(e))


if __name__ == '__main__':
    cli()