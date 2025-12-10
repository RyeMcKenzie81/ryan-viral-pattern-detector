"""
Scheduler Worker - Background process for executing scheduled ad generation jobs.

This worker:
1. Polls scheduled_jobs table every minute for due jobs
2. Executes ad creation workflow for each template
3. Tracks template usage for the "unused" feature
4. Handles email/Slack exports
5. Updates job run history

Run with: python -m viraltracker.worker.scheduler_worker
"""

import asyncio
import logging
import signal
import sys
from datetime import datetime, timedelta
from typing import List, Optional, Dict, Any
import pytz
import base64

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

# PST timezone
PST = pytz.timezone('America/Los_Angeles')

# Graceful shutdown flag
shutdown_requested = False


def handle_shutdown(signum, frame):
    """Handle shutdown signals gracefully."""
    global shutdown_requested
    logger.info(f"Received signal {signum}, initiating graceful shutdown...")
    shutdown_requested = True


# Register signal handlers
signal.signal(signal.SIGTERM, handle_shutdown)
signal.signal(signal.SIGINT, handle_shutdown)


# ============================================================================
# Database Functions
# ============================================================================

def get_supabase_client():
    """Get Supabase client."""
    from viraltracker.core.database import get_supabase_client
    return get_supabase_client()


def get_due_jobs() -> List[Dict]:
    """Fetch scheduled jobs that are due to run."""
    try:
        db = get_supabase_client()
        now = datetime.now(PST).isoformat()

        result = db.table("scheduled_jobs").select(
            "*, products(id, name, brand_id, brands(id, name, brand_colors))"
        ).eq(
            "status", "active"
        ).lte(
            "next_run_at", now
        ).execute()

        return result.data or []
    except Exception as e:
        logger.error(f"Failed to fetch due jobs: {e}")
        return []


def create_job_run(job_id: str) -> Optional[str]:
    """Create a new job run record. Returns run ID."""
    try:
        db = get_supabase_client()
        result = db.table("scheduled_job_runs").insert({
            "scheduled_job_id": job_id,
            "status": "running",
            "started_at": datetime.now(PST).isoformat()
        }).execute()

        return result.data[0]['id'] if result.data else None
    except Exception as e:
        logger.error(f"Failed to create job run: {e}")
        return None


def update_job_run(run_id: str, updates: Dict):
    """Update a job run record."""
    try:
        db = get_supabase_client()
        db.table("scheduled_job_runs").update(updates).eq("id", run_id).execute()
    except Exception as e:
        logger.error(f"Failed to update job run {run_id}: {e}")


def update_job(job_id: str, updates: Dict):
    """Update a scheduled job."""
    try:
        db = get_supabase_client()
        db.table("scheduled_jobs").update(updates).eq("id", job_id).execute()
    except Exception as e:
        logger.error(f"Failed to update job {job_id}: {e}")


def get_unused_templates(product_id: str, count: int) -> List[str]:
    """Get templates not yet used for this product, deduplicated by original filename."""
    try:
        db = get_supabase_client()

        # Get all templates from storage
        all_templates = db.storage.from_("reference-ads").list()

        # Deduplicate by original filename (files are named {uuid}_{original_filename})
        seen_originals = {}
        for item in all_templates:
            full_name = item.get('name', '')
            if not full_name.lower().endswith(('.jpg', '.jpeg', '.png', '.webp')):
                continue

            # Extract original filename (after UUID prefix)
            parts = full_name.split('_', 1)
            if len(parts) == 2 and len(parts[0]) == 36:  # UUID is 36 chars
                original_name = parts[1]
            else:
                original_name = full_name

            # Keep first occurrence of each original filename
            if original_name not in seen_originals:
                seen_originals[original_name] = full_name

        all_storage_names = set(seen_originals.values())

        # Get used templates for this product
        used_result = db.table("product_template_usage").select(
            "template_storage_name"
        ).eq("product_id", product_id).execute()

        used_names = set(r['template_storage_name'] for r in (used_result.data or []))

        # Also check original filenames of used templates (in case different UUID copies were used)
        used_originals = set()
        for used_name in used_names:
            parts = used_name.split('_', 1)
            if len(parts) == 2 and len(parts[0]) == 36:
                used_originals.add(parts[1])
            else:
                used_originals.add(used_name)

        # Filter out templates where original filename was already used
        unused = []
        for storage_name in all_storage_names:
            parts = storage_name.split('_', 1)
            if len(parts) == 2 and len(parts[0]) == 36:
                original = parts[1]
            else:
                original = storage_name

            if original not in used_originals and storage_name not in used_names:
                unused.append(storage_name)

        # Return up to 'count' templates
        return unused[:count]
    except Exception as e:
        logger.error(f"Failed to get unused templates: {e}")
        return []


def record_template_usage(product_id: str, template_storage_name: str, ad_run_id: str):
    """Record that a template was used for a product."""
    try:
        db = get_supabase_client()
        db.table("product_template_usage").upsert({
            "product_id": product_id,
            "template_storage_name": template_storage_name,
            "ad_run_id": ad_run_id,
            "used_at": datetime.now(PST).isoformat()
        }, on_conflict="product_id,template_storage_name").execute()
    except Exception as e:
        logger.error(f"Failed to record template usage: {e}")


def get_template_base64(storage_name: str) -> Optional[str]:
    """Download template and return as base64."""
    try:
        db = get_supabase_client()
        data = db.storage.from_("reference-ads").download(storage_name)
        return base64.b64encode(data).decode('utf-8')
    except Exception as e:
        logger.error(f"Failed to download template {storage_name}: {e}")
        return None


# ============================================================================
# Cron Helpers
# ============================================================================

def calculate_next_run(cron_expression: str) -> Optional[datetime]:
    """Calculate next run time from cron expression."""
    if not cron_expression:
        return None

    try:
        parts = cron_expression.split()
        if len(parts) != 5:
            return None

        minute, hour, day_of_month, month, day_of_week = parts
        hour = int(hour)

        now = datetime.now(PST)
        next_run = now.replace(hour=hour, minute=0, second=0, microsecond=0)

        if day_of_week != '*':
            # Weekly
            target_dow = int(day_of_week)
            days_ahead = target_dow - now.weekday()
            if days_ahead <= 0:
                days_ahead += 7
            if days_ahead == 0 and now.hour >= hour:
                days_ahead = 7
            next_run = next_run + timedelta(days=days_ahead)
        elif day_of_month != '*':
            # Monthly
            if now.day > 1 or (now.day == 1 and now.hour >= hour):
                if now.month == 12:
                    next_run = next_run.replace(year=now.year + 1, month=1, day=1)
                else:
                    next_run = next_run.replace(month=now.month + 1, day=1)
            else:
                next_run = next_run.replace(day=1)
        else:
            # Daily
            if now.hour >= hour:
                next_run = next_run + timedelta(days=1)

        return next_run
    except Exception as e:
        logger.error(f"Failed to calculate next run: {e}")
        return None


# ============================================================================
# Job Execution
# ============================================================================

async def execute_job(job: Dict) -> Dict[str, Any]:
    """Execute a single scheduled job."""
    job_id = job['id']
    job_name = job['name']
    product_id = job['product_id']
    product_info = job.get('products', {}) or {}
    brand_info = product_info.get('brands', {}) or {}
    params = job.get('parameters', {})

    logger.info(f"Starting job: {job_name} (ID: {job_id})")

    # Immediately clear next_run_at to prevent job being picked up again
    # This prevents race conditions if the job takes longer than the poll interval
    update_job(job_id, {"next_run_at": None})

    # Create job run record
    run_id = create_job_run(job_id)
    if not run_id:
        logger.error(f"Failed to create run record for job {job_id}")
        return {"success": False, "error": "Failed to create run record"}

    logs = []
    ad_run_ids = []
    templates_used = []

    try:
        # Get templates to use
        if job['template_mode'] == 'unused':
            template_count = job.get('template_count', 5)
            templates = get_unused_templates(product_id, template_count)
            logs.append(f"Selected {len(templates)} unused templates")
        else:
            templates = job.get('template_ids', [])
            logs.append(f"Using {len(templates)} specific templates")

        if not templates:
            raise Exception("No templates available for this job")

        # Import dependencies
        from pydantic_ai import RunContext
        from pydantic_ai.usage import RunUsage
        from viraltracker.agent.agents.ad_creation_agent import complete_ad_workflow
        from viraltracker.agent.dependencies import AgentDependencies

        # Create dependencies
        deps = AgentDependencies.create(project_name="scheduler")

        # Process each template sequentially
        for idx, template_storage_name in enumerate(templates):
            if shutdown_requested:
                logs.append("Shutdown requested, stopping job execution")
                break

            logs.append(f"Processing template {idx + 1}/{len(templates)}: {template_storage_name}")
            logger.info(f"Job {job_name}: Processing template {idx + 1}/{len(templates)}")

            # Download template
            template_base64 = get_template_base64(template_storage_name)
            if not template_base64:
                logs.append(f"  Failed to download template: {template_storage_name}")
                continue

            # Create RunContext
            ctx = RunContext(
                deps=deps,
                model=None,
                usage=RunUsage()
            )

            # Get brand colors if using brand color mode
            brand_colors_data = None
            if params.get('color_mode') == 'brand':
                brand_colors_data = brand_info.get('brand_colors')

            # Run ad creation workflow
            try:
                result = await complete_ad_workflow(
                    ctx=ctx,
                    product_id=product_id,
                    reference_ad_base64=template_base64,
                    reference_ad_filename=template_storage_name,
                    project_id="",
                    num_variations=params.get('num_variations', 5),
                    content_source=params.get('content_source', 'hooks'),
                    color_mode=params.get('color_mode', 'original'),
                    brand_colors=brand_colors_data,
                    image_selection_mode=params.get('image_selection_mode', 'auto'),
                    selected_image_paths=None,  # Auto mode selects best 1-2 images
                    persona_id=params.get('persona_id'),  # Optional persona for targeting
                    variant_id=params.get('variant_id')  # Optional variant (flavor, size, etc.)
                )

                if result and result.get('ad_run_id'):
                    ad_run_id = result['ad_run_id']
                    ad_run_ids.append(ad_run_id)
                    templates_used.append(template_storage_name)

                    # Record template usage
                    record_template_usage(product_id, template_storage_name, ad_run_id)

                    approved = result.get('approved_count', 0)
                    rejected = result.get('rejected_count', 0)
                    flagged = result.get('flagged_count', 0)
                    logs.append(f"  Completed: {approved} approved, {rejected} rejected, {flagged} flagged")

                    # Handle export
                    export_dest = params.get('export_destination', 'none')
                    if export_dest != 'none':
                        await handle_export(
                            result=result,
                            params=params,
                            product_name=product_info.get('name', 'Product'),
                            brand_name=brand_info.get('name', 'Brand'),
                            deps=deps
                        )
                        logs.append(f"  Exported to: {export_dest}")
                else:
                    logs.append(f"  No ad_run_id returned")

            except Exception as e:
                logs.append(f"  Error: {str(e)}")
                logger.error(f"Error processing template {template_storage_name}: {e}")

        # Job completed successfully
        update_job_run(run_id, {
            "status": "completed",
            "completed_at": datetime.now(PST).isoformat(),
            "ad_run_ids": ad_run_ids,
            "templates_used": templates_used,
            "logs": "\n".join(logs)
        })

        # Update job: increment runs_completed, calculate next_run
        runs_completed = job.get('runs_completed', 0) + 1
        max_runs = job.get('max_runs')

        job_updates = {
            "runs_completed": runs_completed
        }

        if max_runs and runs_completed >= max_runs:
            # Job has reached max runs
            job_updates["status"] = "completed"
            job_updates["next_run_at"] = None
            logs.append(f"Job completed: reached max runs ({max_runs})")
        elif job['schedule_type'] == 'recurring':
            # Calculate next run
            next_run = calculate_next_run(job['cron_expression'])
            if next_run:
                job_updates["next_run_at"] = next_run.isoformat()
                logs.append(f"Next run scheduled: {next_run}")
        else:
            # One-time job completed
            job_updates["status"] = "completed"
            job_updates["next_run_at"] = None

        update_job(job_id, job_updates)

        logger.info(f"Completed job: {job_name}")
        return {
            "success": True,
            "ad_run_ids": ad_run_ids,
            "templates_used": templates_used
        }

    except Exception as e:
        error_msg = str(e)
        logs.append(f"Job failed: {error_msg}")
        logger.error(f"Job {job_name} failed: {error_msg}")

        update_job_run(run_id, {
            "status": "failed",
            "completed_at": datetime.now(PST).isoformat(),
            "error_message": error_msg,
            "ad_run_ids": ad_run_ids,
            "templates_used": templates_used,
            "logs": "\n".join(logs)
        })

        return {"success": False, "error": error_msg}


async def handle_export(
    result: Dict,
    params: Dict,
    product_name: str,
    brand_name: str,
    deps
):
    """Handle exporting generated ads to email and/or Slack."""
    export_dest = params.get('export_destination', 'none')
    if export_dest == 'none':
        return

    # Collect image URLs
    db = get_supabase_client()
    image_urls = []

    generated_ads = result.get('generated_ads', [])
    for ad in generated_ads:
        storage_path = ad.get('storage_path')
        if storage_path and ad.get('final_status') in ['approved', 'flagged']:
            try:
                parts = storage_path.split('/', 1)
                if len(parts) == 2:
                    bucket, path = parts
                else:
                    bucket = "generated-ads"
                    path = storage_path
                signed = db.storage.from_(bucket).create_signed_url(path, 3600)
                if signed.get('signedURL'):
                    image_urls.append(signed['signedURL'])
            except Exception as e:
                logger.error(f"Failed to get signed URL: {e}")

    if not image_urls:
        logger.warning("No approved/flagged ads to export")
        return

    # Send to Email
    if export_dest in ['email', 'both'] and params.get('export_email'):
        try:
            from viraltracker.services.email_service import AdEmailContent

            content = AdEmailContent(
                product_name=product_name,
                brand_name=brand_name,
                image_urls=image_urls,
                ad_run_ids=[result.get('ad_run_id')]
            )

            email_result = await deps.email.send_ad_export_email(
                to_email=params['export_email'],
                content=content
            )

            if email_result.success:
                logger.info(f"Email sent to {params['export_email']}")
            else:
                logger.error(f"Email failed: {email_result.error}")

        except Exception as e:
            logger.error(f"Email export failed: {e}")

    # Send to Slack
    if export_dest in ['slack', 'both']:
        try:
            from viraltracker.services.slack_service import AdSlackContent

            content = AdSlackContent(
                product_name=product_name,
                brand_name=brand_name,
                image_urls=image_urls,
                ad_run_ids=[result.get('ad_run_id')]
            )

            slack_result = await deps.slack.send_ad_export_message(content=content)

            if slack_result.success:
                logger.info("Slack message sent")
            else:
                logger.error(f"Slack failed: {slack_result.error}")

        except Exception as e:
            logger.error(f"Slack export failed: {e}")


# ============================================================================
# Main Loop
# ============================================================================

async def run_scheduler():
    """Main scheduler loop."""
    logger.info("Scheduler worker started")
    logger.info(f"Polling interval: 60 seconds")

    while not shutdown_requested:
        try:
            # Check for due jobs
            due_jobs = get_due_jobs()

            if due_jobs:
                logger.info(f"Found {len(due_jobs)} due job(s)")

                for job in due_jobs:
                    if shutdown_requested:
                        break

                    try:
                        await execute_job(job)
                    except Exception as e:
                        logger.error(f"Error executing job {job['id']}: {e}")

            # Wait before next poll
            for _ in range(60):  # Check shutdown flag every second
                if shutdown_requested:
                    break
                await asyncio.sleep(1)

        except Exception as e:
            logger.error(f"Error in scheduler loop: {e}")
            await asyncio.sleep(10)  # Brief pause on error

    logger.info("Scheduler worker stopped")


def main():
    """Entry point for the scheduler worker."""
    logger.info("=" * 60)
    logger.info("Ad Scheduler Worker")
    logger.info("=" * 60)

    try:
        asyncio.run(run_scheduler())
    except KeyboardInterrupt:
        logger.info("Received keyboard interrupt")
    except Exception as e:
        logger.error(f"Fatal error: {e}")
        sys.exit(1)

    logger.info("Worker shutdown complete")


if __name__ == "__main__":
    main()
