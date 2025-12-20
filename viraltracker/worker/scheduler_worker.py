"""
Scheduler Worker - Background process for executing scheduled jobs.

This worker:
1. Polls scheduled_jobs table every minute for due jobs
2. Routes jobs by job_type:
   - ad_creation: Execute ad creation workflow for each template
   - meta_sync: Sync Meta Ads performance data for a brand
   - scorecard: Generate weekly performance scorecard
3. Tracks template usage for the "unused" feature (ad_creation)
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

        # Fetch all due jobs (job_type routing handled in execute_job)
        result = db.table("scheduled_jobs").select(
            "*, products(id, name, brand_id, brands(id, name, brand_colors)), brands!scheduled_jobs_brand_id_fkey(id, name)"
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
    """Route and execute a scheduled job based on job_type."""
    job_type = job.get('job_type', 'ad_creation')
    job_id = job['id']
    job_name = job['name']

    logger.info(f"Routing job: {job_name} (type: {job_type}, ID: {job_id})")

    # Route to appropriate handler
    if job_type == 'meta_sync':
        return await execute_meta_sync_job(job)
    elif job_type == 'scorecard':
        return await execute_scorecard_job(job)
    else:
        # Default to ad_creation for backward compatibility
        return await execute_ad_creation_job(job)


async def execute_ad_creation_job(job: Dict) -> Dict[str, Any]:
    """Execute an ad creation job."""
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
                    variant_id=params.get('variant_id'),  # Optional variant (flavor, size, etc.)
                    additional_instructions=params.get('additional_instructions')  # Optional run instructions
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
# Meta Sync Job Handler
# ============================================================================

async def execute_meta_sync_job(job: Dict) -> Dict[str, Any]:
    """
    Execute a Meta Ads sync job.

    Parameters (from job['parameters']):
        days_back: int - Number of days to sync (default: 7)
        include_inactive: bool - Include paused/deleted ads (default: False)
    """
    job_id = job['id']
    job_name = job['name']
    brand_id = job['brand_id']
    brand_info = job.get('brands', {}) or {}
    brand_name = brand_info.get('name', 'Unknown')
    params = job.get('parameters', {})

    logger.info(f"Starting Meta sync job: {job_name} for brand {brand_name}")

    # Immediately clear next_run_at to prevent duplicate execution
    update_job(job_id, {"next_run_at": None})

    # Create job run record
    run_id = create_job_run(job_id)
    if not run_id:
        logger.error(f"Failed to create run record for job {job_id}")
        return {"success": False, "error": "Failed to create run record"}

    logs = []

    try:
        # Get parameters
        days_back = params.get('days_back', 7)

        logs.append(f"Syncing Meta Ads for brand: {brand_name}")
        logs.append(f"Days back: {days_back}")

        # Get the ad account for this brand
        db = get_supabase_client()
        account_result = db.table("brand_ad_accounts").select(
            "meta_ad_account_id, account_name"
        ).eq("brand_id", brand_id).eq("is_primary", True).limit(1).execute()

        if not account_result.data:
            raise Exception(f"No ad account configured for brand {brand_name}")

        ad_account = account_result.data[0]
        ad_account_id = ad_account['meta_ad_account_id']
        logs.append(f"Ad account: {ad_account.get('account_name', ad_account_id)}")

        # Calculate date range
        from datetime import date
        date_end = date.today()
        date_start = date_end - timedelta(days=days_back)

        logs.append(f"Date range: {date_start} to {date_end}")

        # Import and run the sync
        from viraltracker.services.meta_ads_service import MetaAdsService
        service = MetaAdsService()

        # Run sync (this is an async function)
        result = await service.sync_performance_to_db(
            ad_account_id=ad_account_id,
            brand_id=brand_id,
            date_start=date_start.isoformat(),
            date_end=date_end.isoformat()
        )

        ads_synced = result.get('ads_synced', 0)
        rows_inserted = result.get('rows_inserted', 0)
        logs.append(f"Synced {ads_synced} ads, {rows_inserted} data rows")

        # Update job run as completed
        update_job_run(run_id, {
            "status": "completed",
            "completed_at": datetime.now(PST).isoformat(),
            "logs": "\n".join(logs)
        })

        # Update job: increment runs_completed, calculate next_run
        runs_completed = job.get('runs_completed', 0) + 1
        max_runs = job.get('max_runs')

        job_updates = {"runs_completed": runs_completed}

        if max_runs and runs_completed >= max_runs:
            job_updates["status"] = "completed"
            job_updates["next_run_at"] = None
            logs.append(f"Job completed: reached max runs ({max_runs})")
        elif job['schedule_type'] == 'recurring':
            next_run = calculate_next_run(job['cron_expression'])
            if next_run:
                job_updates["next_run_at"] = next_run.isoformat()
                logs.append(f"Next run scheduled: {next_run}")
        else:
            job_updates["status"] = "completed"
            job_updates["next_run_at"] = None

        update_job(job_id, job_updates)

        logger.info(f"Completed Meta sync job: {job_name} - {ads_synced} ads synced")
        return {"success": True, "ads_synced": ads_synced, "rows_inserted": rows_inserted}

    except Exception as e:
        error_msg = str(e)
        logs.append(f"Job failed: {error_msg}")
        logger.error(f"Meta sync job {job_name} failed: {error_msg}")

        update_job_run(run_id, {
            "status": "failed",
            "completed_at": datetime.now(PST).isoformat(),
            "error_message": error_msg,
            "logs": "\n".join(logs)
        })

        return {"success": False, "error": error_msg}


# ============================================================================
# Scorecard Job Handler
# ============================================================================

async def execute_scorecard_job(job: Dict) -> Dict[str, Any]:
    """
    Execute a weekly performance scorecard job.

    Generates AI-powered performance analysis and recommendations,
    then sends via email/Slack.

    Parameters (from job['parameters']):
        days_back: int - Analysis period (default: 7)
        export_email: str - Email to send report
        min_spend: float - Minimum spend to include ad (default: 10.0)
    """
    job_id = job['id']
    job_name = job['name']
    brand_id = job['brand_id']
    brand_info = job.get('brands', {}) or {}
    brand_name = brand_info.get('name', 'Unknown')
    params = job.get('parameters', {})

    logger.info(f"Starting scorecard job: {job_name} for brand {brand_name}")

    # Immediately clear next_run_at to prevent duplicate execution
    update_job(job_id, {"next_run_at": None})

    # Create job run record
    run_id = create_job_run(job_id)
    if not run_id:
        logger.error(f"Failed to create run record for job {job_id}")
        return {"success": False, "error": "Failed to create run record"}

    logs = []

    try:
        days_back = params.get('days_back', 7)
        min_spend = params.get('min_spend', 10.0)
        export_email = params.get('export_email')

        logs.append(f"Generating scorecard for: {brand_name}")
        logs.append(f"Analysis period: {days_back} days")
        logs.append(f"Min spend filter: ${min_spend}")

        # Get performance data
        db = get_supabase_client()
        from datetime import date
        date_end = date.today()
        date_start = date_end - timedelta(days=days_back)

        # Fetch aggregated performance data
        perf_result = db.table("meta_ads_performance").select(
            "meta_ad_id, ad_name, campaign_name, adset_name, "
            "spend, impressions, link_clicks, purchases, purchase_value, ad_status"
        ).eq("brand_id", brand_id).gte(
            "date", date_start.isoformat()
        ).lte(
            "date", date_end.isoformat()
        ).execute()

        if not perf_result.data:
            logs.append("No performance data found for this period")
            update_job_run(run_id, {
                "status": "completed",
                "completed_at": datetime.now(PST).isoformat(),
                "logs": "\n".join(logs)
            })
            return {"success": True, "message": "No data to analyze"}

        # Aggregate by ad
        from collections import defaultdict
        ad_metrics = defaultdict(lambda: {
            "spend": 0, "impressions": 0, "clicks": 0,
            "purchases": 0, "revenue": 0
        })

        for row in perf_result.data:
            ad_id = row['meta_ad_id']
            ad_metrics[ad_id]['name'] = row.get('ad_name', 'Unknown')
            ad_metrics[ad_id]['campaign'] = row.get('campaign_name', '')
            ad_metrics[ad_id]['adset'] = row.get('adset_name', '')
            ad_metrics[ad_id]['status'] = row.get('ad_status', '')
            ad_metrics[ad_id]['spend'] += float(row.get('spend') or 0)
            ad_metrics[ad_id]['impressions'] += int(row.get('impressions') or 0)
            ad_metrics[ad_id]['clicks'] += int(row.get('link_clicks') or 0)
            ad_metrics[ad_id]['purchases'] += int(row.get('purchases') or 0)
            ad_metrics[ad_id]['revenue'] += float(row.get('purchase_value') or 0)

        # Calculate ROAS and filter by min spend
        ads_analyzed = []
        for ad_id, metrics in ad_metrics.items():
            if metrics['spend'] >= min_spend:
                roas = metrics['revenue'] / metrics['spend'] if metrics['spend'] > 0 else 0
                ctr = (metrics['clicks'] / metrics['impressions'] * 100) if metrics['impressions'] > 0 else 0
                ads_analyzed.append({
                    'id': ad_id,
                    'name': metrics['name'],
                    'campaign': metrics['campaign'],
                    'spend': metrics['spend'],
                    'roas': roas,
                    'ctr': ctr,
                    'purchases': metrics['purchases'],
                    'status': metrics['status']
                })

        # Sort by ROAS
        ads_analyzed.sort(key=lambda x: x['roas'], reverse=True)

        logs.append(f"Analyzed {len(ads_analyzed)} ads with ${min_spend}+ spend")

        # Generate scorecard summary
        total_spend = sum(a['spend'] for a in ads_analyzed)
        total_revenue = sum(a['spend'] * a['roas'] for a in ads_analyzed)
        avg_roas = total_revenue / total_spend if total_spend > 0 else 0

        # Categorize ads
        top_performers = [a for a in ads_analyzed if a['roas'] >= 2.0][:5]
        needs_attention = [a for a in ads_analyzed if a['roas'] < 1.0][:5]
        active_ads = [a for a in ads_analyzed if a['status'] == 'ACTIVE']

        scorecard = {
            'brand': brand_name,
            'period': f"{date_start} to {date_end}",
            'total_spend': total_spend,
            'total_revenue': total_revenue,
            'avg_roas': avg_roas,
            'ads_analyzed': len(ads_analyzed),
            'active_ads': len(active_ads),
            'top_performers': top_performers,
            'needs_attention': needs_attention
        }

        logs.append(f"Total spend: ${total_spend:,.2f}")
        logs.append(f"Average ROAS: {avg_roas:.2f}x")
        logs.append(f"Top performers: {len(top_performers)}")
        logs.append(f"Needs attention: {len(needs_attention)}")

        # Send report via email if configured
        if export_email:
            try:
                # Format scorecard as email
                report_lines = [
                    f"Weekly Ad Performance Scorecard - {brand_name}",
                    f"Period: {date_start} to {date_end}",
                    "",
                    "SUMMARY",
                    f"  Total Spend: ${total_spend:,.2f}",
                    f"  Average ROAS: {avg_roas:.2f}x",
                    f"  Ads Analyzed: {len(ads_analyzed)}",
                    "",
                    "TOP PERFORMERS (ROAS >= 2x)",
                ]
                for ad in top_performers:
                    report_lines.append(f"  - {ad['name'][:40]}: {ad['roas']:.2f}x ROAS, ${ad['spend']:,.2f} spend")

                report_lines.append("")
                report_lines.append("NEEDS ATTENTION (ROAS < 1x)")
                for ad in needs_attention:
                    report_lines.append(f"  - {ad['name'][:40]}: {ad['roas']:.2f}x ROAS, ${ad['spend']:,.2f} spend")

                report_text = "\n".join(report_lines)

                # TODO: Send via email service (for now, just log)
                logs.append(f"Report would be sent to: {export_email}")
                logger.info(f"Scorecard report:\n{report_text}")

            except Exception as e:
                logs.append(f"Failed to send email: {e}")
                logger.error(f"Scorecard email failed: {e}")

        # Update job run as completed
        update_job_run(run_id, {
            "status": "completed",
            "completed_at": datetime.now(PST).isoformat(),
            "logs": "\n".join(logs)
        })

        # Update job scheduling
        runs_completed = job.get('runs_completed', 0) + 1
        max_runs = job.get('max_runs')

        job_updates = {"runs_completed": runs_completed}

        if max_runs and runs_completed >= max_runs:
            job_updates["status"] = "completed"
            job_updates["next_run_at"] = None
        elif job['schedule_type'] == 'recurring':
            next_run = calculate_next_run(job['cron_expression'])
            if next_run:
                job_updates["next_run_at"] = next_run.isoformat()
        else:
            job_updates["status"] = "completed"
            job_updates["next_run_at"] = None

        update_job(job_id, job_updates)

        logger.info(f"Completed scorecard job: {job_name}")
        return {"success": True, "scorecard": scorecard}

    except Exception as e:
        error_msg = str(e)
        logs.append(f"Job failed: {error_msg}")
        logger.error(f"Scorecard job {job_name} failed: {error_msg}")

        update_job_run(run_id, {
            "status": "failed",
            "completed_at": datetime.now(PST).isoformat(),
            "error_message": error_msg,
            "logs": "\n".join(logs)
        })

        return {"success": False, "error": error_msg}


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
