"""
Background job notification poller for Chainlit.

Polls scheduled_job_runs for status changes and sends push messages
to the user's chat session when jobs complete or fail.
"""

import asyncio
import logging
from datetime import datetime, timezone

import chainlit as cl

logger = logging.getLogger(__name__)

# Polling interval in seconds
POLL_INTERVAL = 30


async def start_job_notification_poller(org_id: str | None):
    """Background task that polls for job completions and sends chat notifications.

    Started on @cl.on_chat_start, runs for the lifetime of the session.
    Sends a cl.Message when a job completes or fails.

    Args:
        org_id: Organization ID to filter jobs by. If None, shows all jobs.
    """
    from viraltracker.core.database import get_supabase_client

    last_check = datetime.now(timezone.utc)

    # Give the session a moment to fully initialize
    await asyncio.sleep(5)

    logger.info(f"Job notification poller started (org: {org_id})")

    # One-time confirmation so user knows the poller is alive
    try:
        await cl.Message(
            content="🔔 Job notifications active. I'll let you know when background jobs complete."
        ).send()
    except Exception as e:
        logger.error(f"Poller cannot send messages (context lost?): {e}")
        return

    while True:
        try:
            await asyncio.sleep(POLL_INTERVAL)

            db = get_supabase_client()
            cutoff = last_check.isoformat()
            logger.info(f"Notification poll: checking since {cutoff}")

            # Find job runs that completed or failed since last check.
            # Note: scheduled_jobs.brand_id has no FK to brands, so we
            # cannot use nested PostgREST joins for brand names. Look
            # up brand names separately instead.
            query = (
                db.table("scheduled_job_runs")
                .select(
                    "id, status, started_at, completed_at, error_message, "
                    "scheduled_jobs(id, job_type, brand_id, name)"
                )
                .in_("status", ["completed", "failed"])
                .gte("completed_at", cutoff)
                .order("completed_at", desc=True)
                .limit(10)
            )

            result = query.execute()
            runs = result.data or []
            logger.info(f"Notification poll: {len(runs)} runs found since {cutoff}")

            if not runs:
                last_check = datetime.now(timezone.utc)
                continue

            # Collect brand IDs we need to resolve
            brand_ids_needed = set()
            for run in runs:
                job_info = run.get("scheduled_jobs") or {}
                bid = job_info.get("brand_id")
                if bid:
                    brand_ids_needed.add(bid)

            # Look up brand names (no FK, so separate query)
            brand_names = {}
            if brand_ids_needed:
                brand_result = (
                    db.table("brands")
                    .select("id, name")
                    .in_("id", list(brand_ids_needed))
                    .execute()
                )
                brand_names = {b["id"]: b["name"] for b in (brand_result.data or [])}

            # Filter to runs belonging to this org's brands (or platform jobs)
            org_brand_ids = None
            if org_id and org_id != "all":
                org_result = (
                    db.table("brands")
                    .select("id")
                    .eq("organization_id", org_id)
                    .execute()
                )
                org_brand_ids = {b["id"] for b in (org_result.data or [])}

            for run in runs:
                job_info = run.get("scheduled_jobs") or {}
                brand_id = job_info.get("brand_id")

                # Filter: only show jobs for this org's brands or platform-level jobs
                if org_brand_ids is not None and brand_id is not None:
                    if brand_id not in org_brand_ids:
                        logger.info(f"Notification poll: filtered out {job_info.get('job_type')} (brand {brand_id} not in org)")
                        continue

                job_type = job_info.get("job_type", "unknown")
                job_name = job_info.get("name", "")
                brand_name = brand_names.get(brand_id, "Platform") if brand_id else "Platform"
                status = run["status"]

                if status == "completed":
                    icon = "✅"
                    msg = f"{icon} **{job_type}** for **{brand_name}** completed"
                    if job_name:
                        msg += f"\n_{job_name}_"
                else:
                    icon = "❌"
                    error = (run.get("error_message") or "Unknown error")[:200]
                    msg = (
                        f"{icon} **{job_type}** for **{brand_name}** failed"
                        f"\n_{error}_"
                    )

                try:
                    await cl.Message(content=msg).send()
                except Exception as send_err:
                    logger.warning(f"Failed to send notification: {send_err}")
                    # Session likely closed, stop polling
                    return

            last_check = datetime.now(timezone.utc)

        except asyncio.CancelledError:
            logger.info("Job notification poller cancelled")
            return
        except Exception as e:
            logger.error(f"Job notification poller error: {e}")
            # Don't crash the poller on transient errors, just wait and retry
            await asyncio.sleep(POLL_INTERVAL)
