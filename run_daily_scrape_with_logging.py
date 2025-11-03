#!/usr/bin/env python3
"""
Railway cron wrapper with Supabase logging.

This script:
1. Starts a cron run record in Supabase
2. Executes the daily scrape script
3. Parses the results
4. Uploads CSV to Supabase Storage
5. Updates run record with metrics
"""
import subprocess
import re
import os
from datetime import datetime

from viraltracker.storage import start_cron_run, complete_cron_run, fail_cron_run


def parse_summary(log_output: str) -> dict:
    """
    Parse summary information from scrape log output.

    Returns dict with:
    - total_tweets: int
    - green_tweets: int
    - green_percentage: float
    - keywords_scraped: int
    """
    # Default values
    result = {
        "total_tweets": 0,
        "green_tweets": 0,
        "green_percentage": 0.0,
        "keywords_scraped": 0
    }

    # Parse total tweets (e.g., "Total tweets analyzed: 2,184")
    total_match = re.search(r"Total tweets analyzed:\s+([\d,]+)", log_output)
    if total_match:
        result["total_tweets"] = int(total_match.group(1).replace(",", ""))

    # Parse green tweets (e.g., "Total greens: 58 (2.66%)")
    green_match = re.search(r"Total greens:\s+(\d+)\s+\(([\d.]+)%\)", log_output)
    if green_match:
        result["green_tweets"] = int(green_match.group(1))
        result["green_percentage"] = float(green_match.group(2))

    # Parse keywords scraped (e.g., "Scraped 19/19 keywords")
    keywords_match = re.search(r"Scraped (\d+)/(\d+) keywords", log_output)
    if keywords_match:
        result["keywords_scraped"] = int(keywords_match.group(1))

    return result


def main():
    """Run daily scrape with Supabase logging."""
    run_date = datetime.utcnow().strftime("%Y-%m-%d")

    print(f"[{datetime.utcnow().isoformat()}] Starting cron run for {run_date}")

    # Start cron run in Supabase
    try:
        run_id = start_cron_run(run_date)
        print(f"[{datetime.utcnow().isoformat()}] Created run record: {run_id}")
    except Exception as e:
        print(f"[{datetime.utcnow().isoformat()}] Failed to create run record: {e}")
        return 1

    # Run the scrape script
    try:
        print(f"[{datetime.utcnow().isoformat()}] Running scrape script...")

        # Execute scrape_all_keywords_24h.sh
        process = subprocess.run(
            ["bash", "./scrape_all_keywords_24h.sh"],
            capture_output=True,
            text=True,
            timeout=7200  # 2 hour timeout
        )

        log_output = process.stdout + "\n" + process.stderr

        print(f"[{datetime.utcnow().isoformat()}] Scrape completed with exit code: {process.returncode}")

        # Check if script failed
        if process.returncode != 0:
            fail_cron_run(run_id, f"Scrape script failed with exit code {process.returncode}", log_output)
            print(f"[{datetime.utcnow().isoformat()}] Marked run as failed")
            return process.returncode

        # Parse results
        metrics = parse_summary(log_output)
        print(f"[{datetime.utcnow().isoformat()}] Parsed metrics: {metrics}")

        # Find CSV file
        csv_path = os.path.expanduser("~/Downloads/keyword_greens_24h.csv")
        if not os.path.exists(csv_path):
            print(f"[{datetime.utcnow().isoformat()}] Warning: CSV file not found at {csv_path}")
            csv_path = None

        # Complete run in Supabase
        complete_cron_run(
            run_id=run_id,
            total_tweets=metrics["total_tweets"],
            green_tweets=metrics["green_tweets"],
            green_percentage=metrics["green_percentage"],
            keywords_scraped=metrics["keywords_scraped"],
            log_output=log_output,
            csv_local_path=csv_path
        )

        print(f"[{datetime.utcnow().isoformat()}] ✓ Cron run completed successfully")
        print(f"[{datetime.utcnow().isoformat()}] Results: {metrics['green_tweets']}/{metrics['total_tweets']} greens ({metrics['green_percentage']}%)")

        return 0

    except subprocess.TimeoutExpired:
        error_msg = "Scrape script timed out after 2 hours"
        fail_cron_run(run_id, error_msg, "")
        print(f"[{datetime.utcnow().isoformat()}] {error_msg}")
        return 1

    except Exception as e:
        error_msg = f"Unexpected error: {str(e)}"
        fail_cron_run(run_id, error_msg, "")
        print(f"[{datetime.utcnow().isoformat()}] {error_msg}")
        return 1


if __name__ == "__main__":
    exit(main())
