"""
Pipeline Helpers - Consistent job creation for the scheduler pipeline.

Two helpers that keep job creation consistent everywhere:
- ensure_recurring_job(): Create or update a recurring schedule
- queue_one_time_job(): Queue a one-time job for immediate execution

Usage:
    from viraltracker.services.pipeline_helpers import queue_one_time_job, ensure_recurring_job

    # Queue immediate execution
    queue_one_time_job(brand_id, "meta_sync", parameters={"days_back": 30})

    # Create/update recurring schedule
    ensure_recurring_job(brand_id, "meta_sync", "0 6 * * *", parameters={"days_back": 7})
"""

import logging
from datetime import datetime
from typing import Any, Dict, Optional

import pytz

logger = logging.getLogger(__name__)

PST = pytz.timezone("America/Los_Angeles")


def ensure_recurring_job(
    brand_id: Optional[str],
    job_type: str,
    cron_expression: str,
    parameters: Optional[Dict[str, Any]] = None,
    enabled: bool = True,
    name: Optional[str] = None,
) -> Optional[str]:
    """Create or update a recurring scheduled job for (brand_id, job_type).

    - If a recurring job exists for (brand_id, job_type): update schedule + params in-place
    - If none exists: insert a new recurring row
    - Never touches one-time jobs
    - Sets status='active' if enabled, 'paused' if not

    Args:
        brand_id: Brand UUID string, or None for platform-level jobs
        job_type: Job type identifier (e.g. 'meta_sync')
        cron_expression: Cron schedule string
        parameters: Optional job-specific parameters
        enabled: Whether the job should be active
        name: Optional display name (auto-generated if not provided)

    Returns:
        Job ID string, or None on failure.
    """
    from viraltracker.core.database import get_supabase_client
    from viraltracker.worker.scheduler_worker import calculate_next_run

    db = get_supabase_client()
    status = "active" if enabled else "paused"

    try:
        # Look for existing recurring job for this (brand_id, job_type)
        query = db.table("scheduled_jobs").select("id")
        if brand_id is None:
            query = query.is_("brand_id", "null")
        else:
            query = query.eq("brand_id", brand_id)
        result = query.eq("job_type", job_type).eq(
            "schedule_type", "recurring"
        ).limit(1).execute()

        next_run = calculate_next_run(cron_expression) if enabled else None

        if result.data:
            # Update existing recurring job
            job_id = result.data[0]["id"]
            updates = {
                "cron_expression": cron_expression,
                "status": status,
            }
            if next_run:
                updates["next_run_at"] = next_run.isoformat()
            if parameters is not None:
                updates["parameters"] = parameters
            if name:
                updates["name"] = name

            db.table("scheduled_jobs").update(updates).eq("id", job_id).execute()
            logger.info(f"Updated recurring {job_type} job {job_id} for {'platform' if brand_id is None else f'brand {brand_id}'}")
            return job_id
        else:
            # Create new recurring job
            job_name = name or f"{job_type.replace('_', ' ').title()} - Recurring"
            insert_data = {
                "brand_id": brand_id,
                "job_type": job_type,
                "name": job_name,
                "schedule_type": "recurring",
                "cron_expression": cron_expression,
                "next_run_at": next_run.isoformat() if next_run else None,
                "status": status,
                "parameters": parameters or {},
                "trigger_source": "scheduled",
            }

            result = db.table("scheduled_jobs").insert(insert_data).execute()
            job_id = result.data[0]["id"] if result.data else None
            logger.info(f"Created recurring {job_type} job {job_id} for {'platform' if brand_id is None else f'brand {brand_id}'}")
            return job_id

    except Exception as e:
        logger.error(f"Failed to ensure_recurring_job {job_type} for {'platform' if brand_id is None else f'brand {brand_id}'}: {e}")
        return None


def queue_one_time_job(
    brand_id: Optional[str],
    job_type: str,
    parameters: Optional[Dict[str, Any]] = None,
    trigger_source: str = "manual",
    name: Optional[str] = None,
    max_retries: int = 3,
) -> Optional[str]:
    """Queue a one-time job for immediate execution.

    - Creates a new scheduled_jobs row with schedule_type='one_time'
    - next_run_at = NOW() (picked up within 60s by worker)
    - Worker auto-archives after completion (status='archived')

    Args:
        brand_id: Brand UUID string, or None for platform-level jobs
        job_type: Job type identifier (e.g. 'meta_sync')
        parameters: Optional job-specific parameters
        trigger_source: 'manual' or 'api' (default: 'manual')
        name: Optional display name
        max_retries: Max retry attempts on failure (default: 3)

    Returns:
        Job ID string, or None on failure.
    """
    from viraltracker.core.database import get_supabase_client

    db = get_supabase_client()

    try:
        now = datetime.now(PST).isoformat()
        job_name = name or f"{job_type.replace('_', ' ').title()} - Manual Run"

        insert_data = {
            "brand_id": brand_id,
            "job_type": job_type,
            "name": job_name,
            "schedule_type": "one_time",
            "next_run_at": now,
            "max_runs": 1,
            "max_retries": max_retries,
            "status": "active",
            "parameters": parameters or {},
            "trigger_source": trigger_source,
        }

        result = db.table("scheduled_jobs").insert(insert_data).execute()
        job_id = result.data[0]["id"] if result.data else None
        logger.info(f"Queued one-time {job_type} job {job_id} for {'platform' if brand_id is None else f'brand {brand_id}'} (trigger: {trigger_source})")
        return job_id

    except Exception as e:
        logger.error(f"Failed to queue_one_time_job {job_type} for {'platform' if brand_id is None else f'brand {brand_id}'}: {e}")
        return None
