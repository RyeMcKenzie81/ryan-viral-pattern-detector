"""
Supabase storage helpers for Railway cron logging.

Provides functions to:
- Log cron run start/completion
- Upload CSV files to Supabase Storage
- Update run status and metrics
"""
import os
from datetime import datetime
from typing import Optional

from supabase import create_client, Client


def get_supabase_client() -> Client:
    """Create and return Supabase client."""
    supabase_url = os.environ.get("SUPABASE_URL")
    supabase_key = os.environ.get("SUPABASE_KEY")

    if not supabase_url or not supabase_key:
        raise ValueError("SUPABASE_URL and SUPABASE_KEY environment variables are required")

    return create_client(supabase_url, supabase_key)


def start_cron_run(run_date: str) -> str:
    """
    Log the start of a cron run.

    Args:
        run_date: Date string in YYYY-MM-DD format

    Returns:
        run_id: UUID of the created run
    """
    supabase = get_supabase_client()

    response = supabase.table("cron_runs").insert({
        "run_date": run_date,
        "started_at": datetime.utcnow().isoformat(),
        "status": "running",
        "keywords_scraped": 0
    }).execute()

    run_id = response.data[0]["id"]
    return run_id


def complete_cron_run(
    run_id: str,
    total_tweets: int,
    green_tweets: int,
    green_percentage: float,
    keywords_scraped: int,
    log_output: str,
    csv_local_path: Optional[str] = None,
    error_message: Optional[str] = None
) -> None:
    """
    Mark a cron run as completed and update all metrics.

    Args:
        run_id: UUID of the run
        total_tweets: Total number of tweets analyzed
        green_tweets: Number of green tweets found
        green_percentage: Green percentage (e.g., 3.17)
        keywords_scraped: Number of keywords processed
        log_output: Full log output from the run
        csv_local_path: Local path to CSV file to upload (optional)
        error_message: Error message if run failed (optional)
    """
    supabase = get_supabase_client()

    # Upload CSV to storage if provided
    csv_storage_path = None
    if csv_local_path and os.path.exists(csv_local_path):
        # Generate storage path: YYYY-MM-DD/keyword_greens_YYYYMMDD.csv
        run_date = datetime.utcnow().strftime("%Y-%m-%d")
        filename = f"keyword_greens_{run_date.replace('-', '')}.csv"
        csv_storage_path = f"{run_date}/{filename}"

        # Read CSV file
        with open(csv_local_path, "rb") as f:
            csv_data = f.read()

        # Upload to Supabase Storage
        supabase.storage.from_("cron-outputs").upload(
            path=csv_storage_path,
            file=csv_data,
            file_options={"content-type": "text/csv"}
        )

    # Update run record
    status = "completed" if not error_message else "failed"

    supabase.table("cron_runs").update({
        "completed_at": datetime.utcnow().isoformat(),
        "status": status,
        "total_tweets": total_tweets,
        "green_tweets": green_tweets,
        "green_percentage": green_percentage,
        "keywords_scraped": keywords_scraped,
        "log_output": log_output,
        "csv_storage_path": csv_storage_path,
        "error_message": error_message
    }).eq("id", run_id).execute()


def update_cron_progress(run_id: str, keywords_scraped: int) -> None:
    """
    Update progress of a running cron job.

    Args:
        run_id: UUID of the run
        keywords_scraped: Current number of keywords processed
    """
    supabase = get_supabase_client()

    supabase.table("cron_runs").update({
        "keywords_scraped": keywords_scraped
    }).eq("id", run_id).execute()


def fail_cron_run(run_id: str, error_message: str, log_output: str = "") -> None:
    """
    Mark a cron run as failed.

    Args:
        run_id: UUID of the run
        error_message: Error message describing the failure
        log_output: Any log output captured before failure
    """
    supabase = get_supabase_client()

    supabase.table("cron_runs").update({
        "completed_at": datetime.utcnow().isoformat(),
        "status": "failed",
        "error_message": error_message,
        "log_output": log_output
    }).eq("id", run_id).execute()
