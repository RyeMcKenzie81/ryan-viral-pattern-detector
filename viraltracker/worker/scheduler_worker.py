"""
Scheduler Worker - Background process for executing scheduled jobs.

This worker:
1. Polls scheduled_jobs table every minute for due jobs
2. Routes jobs by job_type:
   - ad_creation: Execute ad creation workflow for each template
   - meta_sync: Sync Meta Ads performance data for a brand
   - scorecard: Generate weekly performance scorecard
   - ad_classification: Pre-compute ad classifications in background
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
from typing import List, Optional, Dict, Any, Union
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

# Maximum ads per scheduled run (configurable via system_settings)
MAX_ADS_PER_SCHEDULED_RUN = 50


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
            "*, products(id, name, brand_id, brands(id, name, brand_colors))"
        ).eq(
            "status", "active"
        ).lte(
            "next_run_at", now
        ).execute()

        jobs = result.data or []

        # For jobs without products (meta_sync, scorecard), fetch brand name separately
        brand_ids_needed = set()
        for job in jobs:
            if not job.get('products') and job.get('brand_id'):
                brand_ids_needed.add(job['brand_id'])

        if brand_ids_needed:
            brands_result = db.table("brands").select("id, name, organization_id").in_("id", list(brand_ids_needed)).execute()
            brand_map = {b['id']: b for b in (brands_result.data or [])}
            for job in jobs:
                if not job.get('products') and job.get('brand_id'):
                    job['brands'] = brand_map.get(job['brand_id'], {})

        return jobs
    except Exception as e:
        logger.error(f"Failed to fetch due jobs: {e}")
        return []


def create_job_run(job_id: str) -> Optional[str]:
    """Create a new job run record. Returns run ID.

    Automatically determines attempt_number:
    - If the last run for this job failed, increment its attempt_number
    - Otherwise, start at attempt_number=1
    """
    try:
        db = get_supabase_client()

        # Determine attempt number
        attempt_number = 1
        try:
            last_run = db.table("scheduled_job_runs").select(
                "status, attempt_number"
            ).eq("scheduled_job_id", job_id).order(
                "started_at", desc=True
            ).limit(1).execute()
            if last_run.data and last_run.data[0].get("status") == "failed":
                attempt_number = (last_run.data[0].get("attempt_number") or 1) + 1
        except Exception:
            pass  # Default to 1 if query fails

        result = db.table("scheduled_job_runs").insert({
            "scheduled_job_id": job_id,
            "status": "running",
            "started_at": datetime.now(PST).isoformat(),
            "attempt_number": attempt_number,
        }).execute()

        run_data = result.data[0] if result.data else None
        if run_data:
            return run_data['id']
        return None
    except Exception as e:
        logger.error(f"Failed to create job run: {e}")
        return None


def get_run_attempt_number(run_id: str) -> int:
    """Get the attempt_number for a run. Returns 1 if unknown."""
    try:
        db = get_supabase_client()
        result = db.table("scheduled_job_runs").select(
            "attempt_number"
        ).eq("id", run_id).limit(1).execute()
        if result.data:
            return result.data[0].get("attempt_number", 1) or 1
        return 1
    except Exception:
        return 1


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


def recover_stuck_runs(stuck_threshold_minutes: int = 30):
    """Find runs stuck in 'running' state for too long and mark them failed.

    Called at the start of each poll cycle. Marks stuck runs as failed and
    reschedules their parent jobs via _reschedule_after_failure.

    Args:
        stuck_threshold_minutes: How long a run can be 'running' before recovery.
    """
    try:
        db = get_supabase_client()
        cutoff = (datetime.now(PST) - timedelta(minutes=stuck_threshold_minutes)).isoformat()

        stuck = db.table("scheduled_job_runs").select(
            "id, scheduled_job_id, started_at, attempt_number"
        ).eq("status", "running").lt("started_at", cutoff).execute()

        for run in (stuck.data or []):
            logger.warning(f"Recovering stuck run {run['id']} (started {run['started_at']})")

            # Mark run as failed
            db.table("scheduled_job_runs").update({
                "status": "failed",
                "completed_at": datetime.now(PST).isoformat(),
                "error_message": f"Run stuck for >{stuck_threshold_minutes}m, marked failed by recovery sweep",
            }).eq("id", run["id"]).execute()

            # Reschedule the parent job
            try:
                job_result = db.table("scheduled_jobs").select("*").eq(
                    "id", run["scheduled_job_id"]
                ).limit(1).execute()
                if job_result.data:
                    _reschedule_after_failure(
                        job_result.data[0],
                        run["scheduled_job_id"],
                        run.get("attempt_number", 1),
                    )
            except Exception as e:
                logger.error(f"Failed to reschedule after stuck run recovery: {e}")

    except Exception as e:
        logger.error(f"Error in recover_stuck_runs: {e}")


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


def get_template_base64(template: Union[str, Dict]) -> Optional[str]:
    """Download template and return as base64.

    Args:
        template: Either storage_name (str) for uploaded templates,
                  or dict with {id, storage_path, bucket} for scraped templates

    Returns:
        Base64 encoded image data, or None on failure
    """
    try:
        db = get_supabase_client()

        if isinstance(template, dict):
            # Scraped template - get storage info from dict
            storage_path = template.get('storage_path', '')
            bucket = template.get('bucket', 'scraped-assets')

            # If storage_path contains bucket prefix, parse it
            if '/' in storage_path and not bucket:
                parts = storage_path.split('/', 1)
                bucket = parts[0]
                storage_path = parts[1]

            data = db.storage.from_(bucket).download(storage_path)
        else:
            # Uploaded template - reference-ads bucket
            data = db.storage.from_("reference-ads").download(template)

        return base64.b64encode(data).decode('utf-8')
    except Exception as e:
        template_ref = template.get('id', template) if isinstance(template, dict) else template
        logger.error(f"Failed to download template {template_ref}: {e}")
        return None


def get_scraped_templates_for_job(template_ids: List[str]) -> List[Dict]:
    """Fetch scraped templates by ID and return with storage info.

    Args:
        template_ids: List of template UUID strings

    Returns:
        List of dicts with {id, name, storage_path, bucket}
    """
    if not template_ids:
        return []

    try:
        db = get_supabase_client()
        result = db.table("scraped_templates").select(
            "id, name, storage_path"
        ).in_("id", template_ids).execute()

        templates = []
        for t in (result.data or []):
            storage_path = t.get('storage_path', '')
            # Parse bucket and path from storage_path (format: "bucket/path/to/file.jpg")
            parts = storage_path.split('/', 1) if storage_path else ['scraped-assets', '']
            bucket = parts[0] if len(parts) == 2 else 'scraped-assets'
            path = parts[1] if len(parts) == 2 else storage_path

            templates.append({
                'id': t['id'],
                'name': t.get('name', 'Template'),
                'storage_path': path,
                'bucket': bucket,
                'full_storage_path': storage_path
            })

        return templates
    except Exception as e:
        logger.error(f"Failed to fetch scraped templates: {e}")
        return []


def mark_recommendation_as_used(product_id: str, template_id: str):
    """Mark a template recommendation as used for a product.

    Args:
        product_id: Product UUID string
        template_id: Template UUID string
    """
    try:
        from viraltracker.services.template_recommendation_service import TemplateRecommendationService
        from uuid import UUID
        rec_service = TemplateRecommendationService()
        rec_service.mark_as_used(UUID(product_id), UUID(template_id))
    except Exception as e:
        # Non-critical - log and continue
        logger.debug(f"Failed to mark recommendation as used: {e}")


def get_belief_plan(plan_id: str) -> Optional[Dict]:
    """Fetch a belief plan with its angles and templates."""
    try:
        from viraltracker.services.planning_service import PlanningService
        from uuid import UUID
        service = PlanningService()
        plan = service.get_plan(UUID(plan_id))
        if plan:
            return {
                'id': str(plan.id),
                'name': plan.name,
                'product_id': str(plan.product_id),
                'persona_id': str(plan.persona_id),
                'jtbd_framed_id': str(plan.jtbd_framed_id),
                'ads_per_angle': plan.ads_per_angle,
                'angles': [
                    {
                        'id': str(a.id),
                        'name': a.name,
                        'belief_statement': a.belief_statement
                    }
                    for a in plan.angles
                ],
                'templates': plan.templates
            }
        return None
    except Exception as e:
        logger.error(f"Failed to fetch belief plan {plan_id}: {e}")
        return None


def get_angles_by_ids(angle_ids: List[str]) -> List[Dict]:
    """Fetch belief angles by their IDs."""
    try:
        db = get_supabase_client()
        result = db.table("belief_angles").select(
            "id, name, belief_statement, jtbd_framed_id"
        ).in_("id", angle_ids).execute()
        return result.data or []
    except Exception as e:
        logger.error(f"Failed to fetch angles: {e}")
        return []


def get_offer_variant(offer_variant_id: str) -> Optional[Dict]:
    """Fetch a product offer variant by ID."""
    try:
        db = get_supabase_client()
        result = db.table("product_offer_variants").select(
            "id, name, landing_page_url, pain_points, desires_goals, benefits, target_audience"
        ).eq("id", offer_variant_id).execute()
        return result.data[0] if result.data else None
    except Exception as e:
        logger.error(f"Failed to fetch offer variant {offer_variant_id}: {e}")
        return None


def build_offer_variant_context(offer_variant: Dict, brand_disallowed_claims: Optional[List[str]] = None) -> str:
    """Build context string from offer variant data for ad generation.

    Args:
        offer_variant: Offer variant dict with messaging and compliance data
        brand_disallowed_claims: Optional brand-level disallowed claims to include
    """
    lines = []
    lines.append("=== OFFER VARIANT CONTEXT ===")
    lines.append(f"Landing Page: {offer_variant.get('landing_page_url', 'N/A')}")

    pain_points = offer_variant.get('pain_points') or []
    if pain_points:
        lines.append(f"Target Pain Points: {', '.join(pain_points)}")

    desires = offer_variant.get('desires_goals') or []
    if desires:
        lines.append(f"Target Desires: {', '.join(desires)}")

    benefits = offer_variant.get('benefits') or []
    if benefits:
        lines.append(f"Key Benefits: {', '.join(benefits)}")

    target_audience = offer_variant.get('target_audience')
    if target_audience:
        lines.append(f"Target Audience: {target_audience}")

    # Compliance section
    all_disallowed = []
    if brand_disallowed_claims:
        all_disallowed.extend(brand_disallowed_claims)
    variant_disallowed = offer_variant.get('disallowed_claims') or []
    if variant_disallowed:
        all_disallowed.extend(variant_disallowed)

    if all_disallowed:
        lines.append("")
        lines.append("⚠️ DISALLOWED CLAIMS (DO NOT USE):")
        for claim in all_disallowed:
            lines.append(f"  - {claim}")

    required_disclaimers = offer_variant.get('required_disclaimers')
    if required_disclaimers:
        lines.append("")
        lines.append(f"📋 REQUIRED DISCLAIMER: {required_disclaimers}")

    lines.append("=== END OFFER CONTEXT ===")
    return "\n".join(lines)


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
    elif job_type == 'template_scrape':
        return await execute_template_scrape_job(job)
    elif job_type == 'template_approval':
        return await execute_template_approval_job(job)
    elif job_type == 'congruence_reanalysis':
        return await execute_congruence_reanalysis_job(job)
    elif job_type == 'ad_classification':
        return await execute_ad_classification_job(job)
    elif job_type == 'asset_download':
        return await execute_asset_download_job(job)
    elif job_type == 'competitor_scrape':
        return await execute_competitor_scrape_job(job)
    elif job_type == 'reddit_scrape':
        return await execute_reddit_scrape_job(job)
    elif job_type == 'amazon_review_scrape':
        return await execute_amazon_review_scrape_job(job)
    elif job_type == 'ad_creation_v2':
        return await execute_ad_creation_v2_job(job)
    elif job_type == 'ad_creation':
        return await execute_ad_creation_job(job)
    else:
        # Hard-fail on unknown job types — never silently fall through to V1
        logger.error(f"Unknown job_type '{job_type}' for job {job_id} ({job_name}). "
                     f"No handler registered. Refusing to execute.")
        raise ValueError(f"Unknown job_type: {job_type}")


async def execute_ad_creation_v2_job(job: Dict) -> Dict[str, Any]:
    """Stub handler for V2 ad creation jobs.

    Marks the run as completed with metadata indicating the V2 pipeline
    is not yet implemented. Full implementation replaces this in Phase 1.
    """
    job_id = job['id']
    job_name = job['name']

    logger.info(f"V2 ad creation job received: {job_name} (ID: {job_id}) — stub handler")

    # Create job run record
    run_id = create_job_run(job_id)
    if not run_id:
        logger.error(f"Failed to create run record for V2 job {job_id}")
        return {"success": False, "error": "Failed to create run record"}

    # Mark as completed with stub metadata
    update_job_run(run_id, {
        "status": "completed",
        "completed_at": datetime.now(PST).isoformat(),
        "metadata": {"stub": True, "reason": "V2 pipeline not yet implemented"},
        "logs": "V2 ad creation stub: pipeline not yet implemented. "
                "This job type will be functional after Phase 1."
    })

    # Update parent job: increment runs_completed, schedule next run
    runs_completed = job.get('runs_completed', 0) + 1
    max_runs = job.get('max_runs')
    job_updates = {"runs_completed": runs_completed}

    if max_runs and runs_completed >= max_runs:
        job_updates["status"] = "completed"
        job_updates["next_run_at"] = None
    elif job.get('schedule_type') == 'recurring':
        next_run = calculate_next_run(job.get('cron_expression'))
        if next_run:
            job_updates["next_run_at"] = next_run.isoformat()
    else:
        job_updates["status"] = "completed"
        job_updates["next_run_at"] = None

    update_job(job_id, job_updates)

    logger.info(f"V2 stub completed: {job_name} (run_id: {run_id})")
    return {"success": True, "stub": True, "run_id": run_id}


async def execute_ad_creation_job(job: Dict) -> Dict[str, Any]:
    """Execute an ad creation job with support for belief-first modes."""
    job_id = job['id']
    job_name = job['name']
    product_id = job['product_id']
    product_info = job.get('products', {}) or {}
    brand_info = product_info.get('brands', {}) or {}
    params = job.get('parameters', {}) or {}

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
    angles_used = []
    ads_generated = 0

    # Dataset freshness tracking (brand_id comes from product's brand join)
    from viraltracker.services.dataset_freshness_service import DatasetFreshnessService
    freshness = DatasetFreshnessService()
    brand_id = brand_info.get('id')

    # Build offer variant context if specified
    offer_variant_context = ""
    offer_variant_id = params.get('offer_variant_id')
    destination_url = params.get('destination_url')

    # Get brand-level disallowed claims for compliance
    brand_disallowed_claims = brand_info.get('disallowed_claims') or []

    if offer_variant_id:
        offer_variant = get_offer_variant(offer_variant_id)
        if offer_variant:
            offer_variant_context = build_offer_variant_context(
                offer_variant, brand_disallowed_claims=brand_disallowed_claims
            )
            destination_url = offer_variant.get('landing_page_url') or destination_url
            logs.append(f"Offer variant: {offer_variant.get('name', 'Unknown')}")
            logs.append(f"Destination URL: {destination_url}")
        else:
            logs.append(f"Warning: Offer variant {offer_variant_id} not found")

    try:
        if brand_id:
            freshness.record_start(brand_id, "ad_creations", run_id=run_id)

        # Determine content source mode
        content_source = params.get('content_source', 'hooks')
        logs.append(f"Content source: {content_source}")

        # Determine template source (default to 'uploaded' for backward compatibility)
        template_source = job.get('template_source', 'uploaded')
        is_scraped_source = template_source == 'scraped'
        logs.append(f"Template source: {template_source}")

        # Get templates to use
        if is_scraped_source:
            # Scraped template library
            scraped_template_ids = job.get('scraped_template_ids') or []
            templates = get_scraped_templates_for_job(scraped_template_ids)
            logs.append(f"Loaded {len(templates)} scraped templates from library")
        elif job.get('template_mode') == 'unused':
            template_count = job.get('template_count', 5)
            templates = get_unused_templates(product_id, template_count)
            logs.append(f"Selected {len(templates)} unused templates")
        else:
            templates = job.get('template_ids') or []
            logs.append(f"Using {len(templates)} specific templates")

        if not templates:
            raise Exception("No templates available for this job")

        # Import dependencies
        from viraltracker.pipelines.ad_creation.orchestrator import run_ad_creation
        from viraltracker.agent.dependencies import AgentDependencies

        # Create dependencies
        deps = AgentDependencies.create(project_name="scheduler")

        # Get brand colors if using brand color mode
        brand_colors_data = None
        if params.get('color_mode') == 'brand':
            brand_colors_data = brand_info.get('brand_colors')

        # Determine angles to process based on content_source
        angles_to_process = []

        if content_source == 'plan':
            # Load belief plan and get its angles
            plan_id = params.get('plan_id')
            if not plan_id:
                raise Exception("plan_id required for content_source='plan'")

            plan = get_belief_plan(plan_id)
            if not plan:
                raise Exception(f"Belief plan not found: {plan_id}")

            angles_to_process = plan.get('angles', [])
            logs.append(f"Loaded plan '{plan['name']}' with {len(angles_to_process)} angles")

            # Use plan's templates if specified, otherwise use job's templates
            if plan.get('templates'):
                # Plan has its own templates - we could use them, but for scheduler
                # we typically use the job's template configuration
                logs.append(f"Using job templates (plan has {len(plan['templates'])} templates)")

        elif content_source == 'angles':
            # Load specific angles by ID
            angle_ids = params.get('angle_ids', [])
            if not angle_ids:
                raise Exception("angle_ids required for content_source='angles'")

            angles_to_process = get_angles_by_ids(angle_ids)
            logs.append(f"Loaded {len(angles_to_process)} direct angles")

        # Calculate total ads and enforce limit
        if angles_to_process:
            num_variations = params.get('num_variations', 5)
            total_potential_ads = len(angles_to_process) * len(templates) * num_variations
            logs.append(f"Potential ads: {len(angles_to_process)} angles × {len(templates)} templates × {num_variations} variations = {total_potential_ads}")

            if total_potential_ads > MAX_ADS_PER_SCHEDULED_RUN:
                logs.append(f"⚠️ Exceeds limit of {MAX_ADS_PER_SCHEDULED_RUN}. Will stop after limit reached.")

        # Process based on content source
        if content_source in ['plan', 'angles']:
            # Belief-first mode: Loop through angles × templates
            for angle_idx, angle in enumerate(angles_to_process):
                if shutdown_requested:
                    logs.append("Shutdown requested, stopping job execution")
                    break

                if ads_generated >= MAX_ADS_PER_SCHEDULED_RUN:
                    logs.append(f"Reached max ads limit ({MAX_ADS_PER_SCHEDULED_RUN}), stopping")
                    break

                angle_name = angle.get('name', 'Unknown')
                angle_id = angle.get('id')
                belief_statement = angle.get('belief_statement', '')
                logs.append(f"\n--- Angle {angle_idx + 1}/{len(angles_to_process)}: {angle_name} ---")

                for template_idx, template in enumerate(templates):
                    if shutdown_requested:
                        break

                    if ads_generated >= MAX_ADS_PER_SCHEDULED_RUN:
                        break

                    # Get template reference for logging (handle both dict and str)
                    if is_scraped_source:
                        template_ref = template.get('name', template.get('id', 'Unknown'))
                        template_id = template.get('id')
                    else:
                        template_ref = template
                        template_id = None

                    logs.append(f"  Template {template_idx + 1}/{len(templates)}: {template_ref}")

                    # Download template
                    template_base64 = get_template_base64(template)
                    if not template_base64:
                        logs.append(f"    Failed to download template")
                        continue

                    # Build additional instructions with angle and offer variant context
                    angle_instructions = f"ANGLE: {angle_name}\nBELIEF: {belief_statement}"
                    full_instructions = angle_instructions
                    if offer_variant_context:
                        full_instructions += f"\n\n{offer_variant_context}"
                    if params.get('additional_instructions'):
                        full_instructions += f"\n\n{params['additional_instructions']}"

                    # Run ad creation workflow with angle-specific content
                    try:
                        result = await run_ad_creation(
                            product_id=product_id,
                            reference_ad_base64=template_base64,
                            reference_ad_filename=template_ref,
                            num_variations=params.get('num_variations', 5),
                            content_source='hooks',  # Use hooks mode but with angle as context
                            color_mode=params.get('color_mode', 'original'),
                            brand_colors=brand_colors_data,
                            image_selection_mode=params.get('image_selection_mode', 'auto'),
                            persona_id=params.get('persona_id') or params.get('belief_persona_id'),
                            variant_id=params.get('variant_id'),
                            additional_instructions=full_instructions,
                            image_resolution=params.get('image_resolution', '2K'),
                            deps=deps,
                        )

                        if result and result.get('ad_run_id'):
                            ad_run_id = result['ad_run_id']
                            ad_run_ids.append(ad_run_id)
                            templates_used.append(template_ref)
                            if angle_id and angle_id not in angles_used:
                                angles_used.append(angle_id)

                            # Record template usage based on source
                            if is_scraped_source and template_id:
                                # Mark recommendation as used for scraped templates
                                mark_recommendation_as_used(product_id, template_id)
                            else:
                                # Record in product_template_usage for uploaded templates
                                record_template_usage(product_id, template_ref, ad_run_id)

                            approved = result.get('approved_count', 0)
                            rejected = result.get('rejected_count', 0)
                            ads_generated += approved
                            logs.append(f"    ✓ {approved} approved, {rejected} rejected")

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
                        else:
                            logs.append(f"    No ad_run_id returned")

                    except Exception as e:
                        logs.append(f"    Error: {str(e)}")
                        logger.error(f"Error processing angle {angle_name} + template {template_ref}: {e}")

        else:
            # Traditional mode (hooks, recreate_template): Loop through templates only
            for idx, template in enumerate(templates):
                if shutdown_requested:
                    logs.append("Shutdown requested, stopping job execution")
                    break

                if ads_generated >= MAX_ADS_PER_SCHEDULED_RUN:
                    logs.append(f"Reached max ads limit ({MAX_ADS_PER_SCHEDULED_RUN}), stopping")
                    break

                # Get template reference for logging (handle both dict and str)
                if is_scraped_source:
                    template_ref = template.get('name', template.get('id', 'Unknown'))
                    template_id = template.get('id')
                else:
                    template_ref = template
                    template_id = None

                logs.append(f"Processing template {idx + 1}/{len(templates)}: {template_ref}")
                logger.info(f"Job {job_name}: Processing template {idx + 1}/{len(templates)}")

                # Download template
                template_base64 = get_template_base64(template)
                if not template_base64:
                    logs.append(f"  Failed to download template: {template_ref}")
                    continue

                # Build combined additional instructions with offer variant context
                combined_instructions = ""
                if offer_variant_context:
                    combined_instructions = offer_variant_context
                if params.get('additional_instructions'):
                    if combined_instructions:
                        combined_instructions += f"\n\n{params['additional_instructions']}"
                    else:
                        combined_instructions = params['additional_instructions']

                # Run ad creation workflow
                try:
                    result = await run_ad_creation(
                        product_id=product_id,
                        reference_ad_base64=template_base64,
                        reference_ad_filename=template_ref,
                        num_variations=params.get('num_variations', 5),
                        content_source=content_source,
                        color_mode=params.get('color_mode', 'original'),
                        brand_colors=brand_colors_data,
                        image_selection_mode=params.get('image_selection_mode', 'auto'),
                        persona_id=params.get('persona_id'),
                        variant_id=params.get('variant_id'),
                        additional_instructions=combined_instructions if combined_instructions else None,
                        image_resolution=params.get('image_resolution', '2K'),
                        deps=deps,
                    )

                    if result and result.get('ad_run_id'):
                        ad_run_id = result['ad_run_id']
                        ad_run_ids.append(ad_run_id)
                        templates_used.append(template_ref)

                        # Record template usage based on source
                        if is_scraped_source and template_id:
                            # Mark recommendation as used for scraped templates
                            mark_recommendation_as_used(product_id, template_id)
                        else:
                            # Record in product_template_usage for uploaded templates
                            record_template_usage(product_id, template_ref, ad_run_id)

                        approved = result.get('approved_count', 0)
                        rejected = result.get('rejected_count', 0)
                        flagged = result.get('flagged_count', 0)
                        ads_generated += approved
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
                    logger.error(f"Error processing template {template_ref}: {e}")

        logs.append(f"\n=== Summary: {ads_generated} ads generated, {len(ad_run_ids)} runs created ===")

        if brand_id:
            freshness.record_success(brand_id, "ad_creations", records_affected=ads_generated, run_id=run_id)

        # Job completed successfully
        job_run_data = {
            "status": "completed",
            "completed_at": datetime.now(PST).isoformat(),
            "ad_run_ids": ad_run_ids,
            "templates_used": templates_used,
            "logs": "\n".join(logs)
        }
        # Include angles_used if belief-first mode was used
        if angles_used:
            job_run_data["angles_used"] = angles_used
        update_job_run(run_id, job_run_data)

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
        result = {
            "success": True,
            "ad_run_ids": ad_run_ids,
            "templates_used": templates_used,
            "ads_generated": ads_generated
        }
        if angles_used:
            result["angles_used"] = angles_used
        return result

    except Exception as e:
        error_msg = str(e)
        logs.append(f"Job failed: {error_msg}")
        logger.error(f"Job {job_name} failed: {error_msg}")

        if brand_id:
            freshness.record_failure(brand_id, "ad_creations", error_msg, run_id=run_id)

        update_job_run(run_id, {
            "status": "failed",
            "completed_at": datetime.now(PST).isoformat(),
            "error_message": error_msg,
            "ad_run_ids": ad_run_ids,
            "templates_used": templates_used,
            "logs": "\n".join(logs)
        })

        # Reschedule recurring jobs so they run again next cycle
        _reschedule_after_failure(job, job_id, get_run_attempt_number(run_id))

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
    brand_id = job.get('brand_id')
    brand_info = job.get('brands') or {}
    brand_name = brand_info.get('name', 'Unknown')
    params = job.get('parameters') or {}

    logger.info(f"Starting Meta sync job: {job_name} for brand {brand_name}")

    # Immediately clear next_run_at to prevent duplicate execution
    update_job(job_id, {"next_run_at": None})

    # Create job run record
    run_id = create_job_run(job_id)
    if not run_id:
        logger.error(f"Failed to create run record for job {job_id}")
        return {"success": False, "error": "Failed to create run record"}

    # Dataset freshness tracking
    from viraltracker.services.dataset_freshness_service import DatasetFreshnessService
    freshness = DatasetFreshnessService()

    logs = []

    try:
        # Get parameters
        days_back = params.get('days_back', 7)

        logs.append(f"Syncing Meta Ads for brand: {brand_name}")
        logs.append(f"Days back: {days_back}")

        # Import the service
        from viraltracker.services.meta_ads_service import MetaAdsService
        from uuid import UUID
        service = MetaAdsService()

        logs.append(f"Fetching insights for last {days_back} days...")

        # Step 1-2: Fetch insights + save to DB
        freshness.record_start(brand_id, "meta_ads_performance", run_id=run_id)

        insights = await service.get_ad_insights(
            brand_id=UUID(brand_id),
            days_back=days_back
        )

        if not insights:
            logs.append("No insights returned from Meta API")
            ads_synced = 0
            rows_inserted = 0
        else:
            logs.append(f"Fetched {len(insights)} insight records")

            rows_inserted = await service.sync_performance_to_db(
                insights=insights,
                brand_id=UUID(brand_id)
            )

            ads_synced = len(set(i.get('ad_id') for i in insights if i.get('ad_id')))
            logs.append(f"Synced {ads_synced} ads, {rows_inserted} data rows")

        freshness.record_success(brand_id, "meta_ads_performance", records_affected=rows_inserted, run_id=run_id)

        # Step 3: Update missing thumbnails (NON-FATAL)
        freshness.record_start(brand_id, "ad_thumbnails", run_id=run_id)
        try:
            thumbs_updated = await service.update_missing_thumbnails(
                brand_id=UUID(brand_id), limit=100
            )
            if thumbs_updated > 0:
                logs.append(f"Updated {thumbs_updated} missing thumbnails")
            freshness.record_success(brand_id, "ad_thumbnails", records_affected=thumbs_updated, run_id=run_id)
        except Exception as thumb_err:
            freshness.record_failure(brand_id, "ad_thumbnails", str(thumb_err), run_id=run_id)
            logs.append(f"Thumbnail update error (non-fatal): {thumb_err}")
            logger.warning(f"Thumbnail update failed for {brand_name}: {thumb_err}")

        # Step 4: Download new ad assets (NON-FATAL)
        freshness.record_start(brand_id, "ad_assets", run_id=run_id)
        try:
            asset_counts = await service.download_new_ad_assets(
                brand_id=UUID(brand_id),
                max_videos=params.get('download_max_videos', 20),
                max_images=params.get('download_max_images', 40),
            )
            total_assets = asset_counts.get("videos", 0) + asset_counts.get("images", 0)
            if total_assets > 0:
                logs.append(
                    f"Downloaded {asset_counts['videos']} videos, "
                    f"{asset_counts['images']} images to storage"
                )
            freshness.record_success(brand_id, "ad_assets", records_affected=total_assets, run_id=run_id)
        except Exception as asset_err:
            freshness.record_failure(brand_id, "ad_assets", str(asset_err), run_id=run_id)
            logs.append(f"Asset download error (non-fatal): {asset_err}")
            logger.warning(f"Asset download failed for {brand_name}: {asset_err}")

        # Step 4.5: Fetch destination URLs for new ads (NON-FATAL)
        freshness.record_start(brand_id, "ad_destinations", run_id=run_id)
        try:
            org_id = brand_info.get("organization_id")
            if org_id:
                from uuid import UUID as _UUID_dest
                dest_stats = await service.sync_ad_destinations_to_db(
                    brand_id=_UUID_dest(brand_id),
                    organization_id=_UUID_dest(org_id),
                    limit=params.get('destination_limit', 100),
                )
                if dest_stats["stored"] > 0:
                    logs.append(f"Fetched {dest_stats['fetched']} / stored {dest_stats['stored']} destination URLs")
                freshness.record_success(brand_id, "ad_destinations", records_affected=dest_stats.get("stored", 0), run_id=run_id)
            else:
                logs.append("Skipped destination sync (no organization_id)")
        except Exception as dest_err:
            freshness.record_failure(brand_id, "ad_destinations", str(dest_err), run_id=run_id)
            logs.append(f"Destination URL fetch error (non-fatal): {dest_err}")
            logger.warning(f"Destination URL fetch failed for {brand_name}: {dest_err}")

        # Step 5: Auto-classify ads if enabled (NON-FATAL)
        if params.get('auto_classify', False):
            freshness.record_start(brand_id, "ad_classifications", run_id=run_id)
            try:
                from uuid import UUID
                logs.append("")
                logs.append("--- Auto-classification ---")
                classify_result = await _run_classification_for_brand(
                    brand_id=UUID(brand_id),
                    logs=logs,
                    max_new=params.get('classify_max_new', 200),
                    max_video=params.get('classify_max_video', 15),
                    days_back=params.get('classify_days_back', days_back),
                    scrape_missing_lp=params.get('scrape_missing_lp', True),
                )
                logs.append(
                    f"Classified: {classify_result['classified']} "
                    f"({classify_result['new']} new, {classify_result['cached']} cached), "
                    f"{classify_result['video']} video"
                )
                if classify_result['skipped'] > 0:
                    logs.append(f"Skipped (cap or missing media): {classify_result['skipped']}")
                if classify_result['errors'] > 0:
                    logs.append(f"Classification errors: {classify_result['errors']}")
                freshness.record_success(brand_id, "ad_classifications", records_affected=classify_result.get('classified', 0), run_id=run_id)
            except Exception as classify_err:
                freshness.record_failure(brand_id, "ad_classifications", str(classify_err), run_id=run_id)
                logs.append(f"Auto-classification error (non-fatal): {classify_err}")
                logger.warning(f"Auto-classification failed for {brand_name}: {classify_err}")

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

        # Record freshness failure for performance data (step 1-2 is the fatal path)
        freshness.record_failure(brand_id, "meta_ads_performance", error_msg, run_id=run_id)

        update_job_run(run_id, {
            "status": "failed",
            "completed_at": datetime.now(PST).isoformat(),
            "error_message": error_msg,
            "logs": "\n".join(logs)
        })

        # Reschedule recurring jobs so they run again next cycle
        _reschedule_after_failure(job, job_id, get_run_attempt_number(run_id))

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
    brand_id = job.get('brand_id')
    brand_info = job.get('brands') or {}
    brand_name = brand_info.get('name', 'Unknown')
    params = job.get('parameters') or {}

    logger.info(f"Starting scorecard job: {job_name} for brand {brand_name}")

    # Immediately clear next_run_at to prevent duplicate execution
    update_job(job_id, {"next_run_at": None})

    # Create job run record
    run_id = create_job_run(job_id)
    if not run_id:
        logger.error(f"Failed to create run record for job {job_id}")
        return {"success": False, "error": "Failed to create run record"}

    # Dataset freshness tracking
    from viraltracker.services.dataset_freshness_service import DatasetFreshnessService
    freshness = DatasetFreshnessService()

    logs = []

    try:
        freshness.record_start(brand_id, "scorecard", run_id=run_id)

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

        freshness.record_success(brand_id, "scorecard", records_affected=len(ads_analyzed), run_id=run_id)

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

        freshness.record_failure(brand_id, "scorecard", error_msg, run_id=run_id)

        update_job_run(run_id, {
            "status": "failed",
            "completed_at": datetime.now(PST).isoformat(),
            "error_message": error_msg,
            "logs": "\n".join(logs)
        })

        # Reschedule recurring jobs so they run again next cycle
        _reschedule_after_failure(job, job_id, get_run_attempt_number(run_id))

        return {"success": False, "error": error_msg}


# ============================================================================
# Template Scrape Job Handler
# ============================================================================

async def execute_template_scrape_job(job: Dict) -> Dict[str, Any]:
    """
    Execute a template scraping job.

    Scrapes Facebook Ad Library for competitor/industry ads and stores them
    with longevity tracking. Optionally queues new ads for template review.

    This is thin orchestration - all business logic is in services:
    - FacebookService.search_ads() - scraping logic
    - AdScrapingService.save_facebook_ad_with_tracking() - storage + dedup + longevity
    - AdScrapingService.scrape_and_store_assets() - asset handling
    - TemplateQueueService.add_to_queue() - queue management

    Parameters (from job['parameters']):
        search_url: str - Facebook Ad Library search URL (required)
        max_ads: int - Max ads per scrape (default: 50)
        images_only: bool - Skip video ads (default: True)
        auto_queue: bool - Auto-add to review queue (default: True)
    """
    job_id = job['id']
    job_name = job['name']
    brand_id = job.get('brand_id')
    brand_info = job.get('brands') or {}
    brand_name = brand_info.get('name', 'Unknown')
    params = job.get('parameters') or {}

    logger.info(f"Starting template scrape job: {job_name} (ID: {job_id}) for brand {brand_name}")
    logger.info(f"Job parameters: {params}")

    # Immediately clear next_run_at to prevent duplicate execution
    update_job(job_id, {"next_run_at": None})

    # Create job run record
    run_id = create_job_run(job_id)
    if not run_id:
        logger.error(f"Failed to create run record for job {job_id}")
        return {"success": False, "error": "Failed to create run record"}

    # Dataset freshness tracking
    from viraltracker.services.dataset_freshness_service import DatasetFreshnessService
    freshness = DatasetFreshnessService()

    logs = []

    try:
        if brand_id:
            freshness.record_start(brand_id, "templates_scraped", run_id=run_id)

        # Get parameters
        search_url = params.get('search_url')
        if not search_url:
            raise ValueError("search_url is required for template_scrape jobs")

        max_ads = params.get('max_ads', 50)
        images_only = params.get('images_only', True)
        auto_queue = params.get('auto_queue', True)

        logs.append(f"Scraping templates for brand: {brand_name}")
        logs.append(f"Search URL: {search_url}")
        logs.append(f"Max ads: {max_ads}, Images only: {images_only}, Auto queue: {auto_queue}")

        # Also log full URL to console for debugging
        logger.info(f"Template scrape URL (full): {search_url}")

        # Import services
        from viraltracker.services.facebook_service import FacebookService
        from viraltracker.services.ad_scraping_service import AdScrapingService
        from viraltracker.services.template_queue_service import TemplateQueueService
        from uuid import UUID

        facebook_service = FacebookService()
        scraping_service = AdScrapingService()
        queue_service = TemplateQueueService()

        # Step 1: Scrape ads from Facebook Ad Library
        logs.append(f"Scraping Facebook Ad Library...")
        ads = await facebook_service.search_ads(
            search_url=search_url,
            project="scheduled_scrape",
            count=max_ads,
            save_to_db=False  # We'll save manually with tracking
        )

        if not ads:
            logs.append("No ads found at the specified URL")
            update_job_run(run_id, {
                "status": "completed",
                "completed_at": datetime.now(PST).isoformat(),
                "logs": "\n".join(logs)
            })
            # Still calculate next run
            _update_job_next_run(job, job_id)
            return {"success": True, "new_ads": 0, "updated_ads": 0, "message": "No ads found"}

        logs.append(f"Scraped {len(ads)} ads from Facebook Ad Library")

        # Step 2: Process each ad with longevity tracking
        new_count = 0
        updated_count = 0
        queued_count = 0
        skipped_videos = 0
        failed_saves = 0

        # Log first ad for debugging
        if ads:
            first_ad = ads[0]
            logger.info(f"First ad sample - ad_archive_id: {first_ad.ad_archive_id}, page_name: {first_ad.page_name}")
            logs.append(f"First ad: {first_ad.page_name} (archive_id: {first_ad.ad_archive_id[:20]}...)")

        for ad in ads:
            try:
                # Build dict manually to match template_ingestion pattern exactly
                ad_dict = {
                    "id": ad.id,
                    "ad_archive_id": ad.ad_archive_id,
                    "page_id": ad.page_id,
                    "page_name": ad.page_name,
                    "is_active": ad.is_active,
                    "start_date": ad.start_date.isoformat() if ad.start_date else None,
                    "end_date": ad.end_date.isoformat() if ad.end_date else None,
                    "currency": ad.currency,
                    "spend": ad.spend,
                    "impressions": ad.impressions,
                    "reach_estimate": ad.reach_estimate,
                    "snapshot": ad.snapshot,
                    "categories": ad.categories,
                    "publisher_platform": ad.publisher_platform,
                    "political_countries": ad.political_countries,
                    "entity_type": ad.entity_type,
                }

                # Skip video ads if images_only is True
                if images_only:
                    snapshot = ad_dict.get('snapshot', {})
                    if isinstance(snapshot, str):
                        import json
                        try:
                            snapshot = json.loads(snapshot)
                        except:
                            snapshot = {}
                    # Check for video indicators
                    has_video = bool(
                        snapshot.get('video_hd_url') or
                        snapshot.get('video_sd_url') or
                        snapshot.get('videos')
                    )
                    has_image = bool(
                        snapshot.get('original_image_url') or
                        snapshot.get('resized_image_url') or
                        snapshot.get('images') or
                        snapshot.get('cards')
                    )
                    if has_video and not has_image:
                        skipped_videos += 1
                        continue

                # Save ad using same method as template_ingestion
                # Note: Not passing brand_id to match working pattern
                result = scraping_service.save_facebook_ad_with_tracking(
                    ad_data=ad_dict,
                    scrape_source="scheduled_scrape"
                )

                if not result or result.get('error'):
                    failed_saves += 1
                    ad_archive_id = ad_dict.get('ad_archive_id', 'missing')
                    error_msg = result.get('error', 'Unknown error') if result else 'None returned'
                    logger.warning(f"save_facebook_ad_with_tracking failed for ad_archive_id: {ad_archive_id}: {error_msg}")
                    # Log first few failures with error details
                    if failed_saves <= 3:
                        logs.append(f"Save failed: {error_msg[:50]}...")
                    continue

                ad_id = result['ad_id']
                is_new = result['is_new']

                if is_new:
                    new_count += 1
                    # Download and store assets for new ads
                    snapshot = ad_dict.get('snapshot', {})
                    if isinstance(snapshot, str):
                        import json
                        try:
                            snapshot = json.loads(snapshot)
                        except:
                            snapshot = {}

                    if snapshot:
                        asset_result = await scraping_service.scrape_and_store_assets(
                            facebook_ad_id=ad_id,
                            snapshot=snapshot,
                            brand_id=UUID(brand_id) if brand_id else None,
                            scrape_source="scheduled_scrape"
                        )

                        # Queue for review if auto_queue enabled and we got assets
                        if auto_queue:
                            asset_ids = asset_result.get('images', []) + asset_result.get('videos', [])
                            if asset_ids:
                                try:
                                    queued = await queue_service.add_to_queue(
                                        asset_ids=asset_ids,
                                        run_ai_analysis=False  # Skip AI analysis for scheduled scrapes
                                    )
                                    queued_count += queued
                                except Exception as qe:
                                    logger.warning(f"Failed to queue assets: {qe}")
                else:
                    updated_count += 1
                    # Longevity tracking already updated by save_facebook_ad_with_tracking

            except Exception as e:
                logger.warning(f"Error processing ad {ad_dict.get('ad_archive_id', 'unknown')}: {e}")
                logs.append(f"Error processing ad: {e}")
                continue

        # Summary
        logs.append(f"")
        logs.append(f"=== Summary ===")
        logs.append(f"New ads: {new_count}")
        logs.append(f"Updated ads: {updated_count}")
        if skipped_videos > 0:
            logs.append(f"Skipped videos: {skipped_videos}")
        if failed_saves > 0:
            logs.append(f"Failed to save: {failed_saves}")
        if auto_queue:
            logs.append(f"Queued for review: {queued_count}")

        if brand_id:
            freshness.record_success(brand_id, "templates_scraped", records_affected=new_count, run_id=run_id)

        # Update job run as completed
        update_job_run(run_id, {
            "status": "completed",
            "completed_at": datetime.now(PST).isoformat(),
            "logs": "\n".join(logs)
        })

        # Update job: increment runs_completed, calculate next_run
        _update_job_next_run(job, job_id)

        logger.info(f"Completed template scrape job: {job_name} - {new_count} new, {updated_count} updated")
        return {
            "success": True,
            "new_ads": new_count,
            "updated_ads": updated_count,
            "queued": queued_count
        }

    except Exception as e:
        error_msg = str(e)
        logs.append(f"Job failed: {error_msg}")
        logger.error(f"Template scrape job {job_name} failed: {error_msg}")

        if brand_id:
            freshness.record_failure(brand_id, "templates_scraped", error_msg, run_id=run_id)

        update_job_run(run_id, {
            "status": "failed",
            "completed_at": datetime.now(PST).isoformat(),
            "error_message": error_msg,
            "logs": "\n".join(logs)
        })

        # Reschedule recurring jobs so they run again next cycle
        _reschedule_after_failure(job, job_id, get_run_attempt_number(run_id))

        return {"success": False, "error": error_msg}


def _reschedule_after_failure(job: Dict, job_id: str, run_attempt_number: int = 1):
    """Reschedule a job after a failed run, with retry support.

    Retries with exponential backoff (5m, 10m, 20m, capped at 60m) up to
    max_retries. After retries exhausted, falls back to the regular cron
    schedule for recurring jobs. One-time jobs that exhaust retries stay dead.

    Args:
        job: The scheduled_jobs row dict
        job_id: Job UUID string
        run_attempt_number: The attempt_number from the failed run
    """
    max_retries = job.get('max_retries', 3)

    if run_attempt_number < max_retries:
        # Retry with exponential backoff: 5min, 10min, 20min, capped at 60min
        backoff_minutes = min(5 * (2 ** (run_attempt_number - 1)), 60)
        retry_at = datetime.now(PST) + timedelta(minutes=backoff_minutes)

        update_job(job_id, {
            "next_run_at": retry_at.isoformat(),
            "last_error": f"Attempt {run_attempt_number} failed, retrying at {retry_at.strftime('%I:%M %p')}",
        })
        logger.info(f"Job {job_id}: attempt {run_attempt_number} failed, retry in {backoff_minutes}m")
    else:
        # Retries exhausted — fall back to normal schedule (or stay dead for one-time)
        job_updates = {"last_error": f"All {max_retries} attempts failed"}
        if job.get('schedule_type') == 'recurring' and job.get('cron_expression'):
            next_run = calculate_next_run(job['cron_expression'])
            if next_run:
                job_updates["next_run_at"] = next_run.isoformat()
                logger.info(f"Job {job_id}: retries exhausted, rescheduled for {next_run}")
            else:
                logger.error(f"Job {job_id}: retries exhausted, could not calculate next run")
        else:
            logger.warning(f"Job {job_id}: one-time job retries exhausted, staying dead")
        update_job(job_id, job_updates)


def _update_job_next_run(job: Dict, job_id: str):
    """Helper to update job runs_completed and next_run_at."""
    runs_completed = job.get('runs_completed', 0) + 1
    max_runs = job.get('max_runs')

    job_updates = {"runs_completed": runs_completed, "last_error": None}

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

    # Auto-archive completed one-time manual jobs to prevent table clutter
    if job.get('schedule_type') == 'one_time' and job.get('trigger_source') == 'manual':
        job_updates["status"] = "archived"

    update_job(job_id, job_updates)


# ============================================================================
# Template Approval Job Handler
# ============================================================================

async def execute_template_approval_job(job: Dict) -> Dict[str, Any]:
    """
    Execute a batch template approval job.

    Processes pending template queue items with AI analysis in batches,
    respecting API rate limits. Items are processed with auto-approval
    using AI suggestions.

    Parameters (from job['parameters']):
        batch_size: int - Items to process per run (default: 100)
        auto_approve: bool - Auto-accept AI suggestions (default: True)
    """
    job_id = job['id']
    job_name = job['name']
    params = job.get('parameters') or {}

    logger.info(f"Starting template approval job: {job_name} (ID: {job_id})")

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
        batch_size = params.get('batch_size', 100)
        auto_approve = params.get('auto_approve', True)

        logs.append(f"Batch size: {batch_size}, Auto-approve: {auto_approve}")

        # Import services
        from viraltracker.services.template_queue_service import TemplateQueueService
        from uuid import UUID

        queue_service = TemplateQueueService()

        # Get pending queue items (status='pending')
        db = get_supabase_client()
        pending_result = db.table("template_queue").select(
            "id"
        ).eq("status", "pending").limit(batch_size).execute()

        pending_items = pending_result.data or []

        if not pending_items:
            logs.append("No pending items in queue")
            update_job_run(run_id, {
                "status": "completed",
                "completed_at": datetime.now(PST).isoformat(),
                "logs": "\n".join(logs)
            })
            _update_job_next_run(job, job_id)
            return {"success": True, "approved": 0, "message": "No pending items"}

        logs.append(f"Found {len(pending_items)} pending items to process")

        # Convert to UUIDs
        queue_ids = [UUID(item['id']) for item in pending_items]

        # Step 1: Run AI analysis on all items
        logs.append(f"Running AI analysis on {len(queue_ids)} items...")
        logger.info(f"Running AI analysis on {len(queue_ids)} items")

        try:
            analyzed_items = await queue_service.start_bulk_approval(queue_ids)
            logs.append(f"AI analysis completed: {len(analyzed_items)} successful")
        except Exception as e:
            logs.append(f"AI analysis failed: {e}")
            raise

        if not analyzed_items:
            logs.append("No items were successfully analyzed")
            update_job_run(run_id, {
                "status": "completed",
                "completed_at": datetime.now(PST).isoformat(),
                "logs": "\n".join(logs)
            })
            _update_job_next_run(job, job_id)
            return {"success": True, "approved": 0, "message": "No items analyzed"}

        # Step 2: Finalize approvals (auto-approve with AI suggestions)
        detected_ok = 0
        detected_fail = 0
        if auto_approve:
            logs.append(f"Auto-approving {len(analyzed_items)} items...")
            result = queue_service.finalize_bulk_approval(
                items=analyzed_items,
                reviewed_by="scheduler_worker"
            )
            approved_count = result["approved"]
            template_ids = result["template_ids"]
            logs.append(f"Approved: {approved_count} items")

            # Step 3: Element detection on newly created templates
            if template_ids:
                logs.append(f"Running element detection on {len(template_ids)} templates...")
                try:
                    from viraltracker.services.template_element_service import TemplateElementService
                    element_service = TemplateElementService()
                    detection = await element_service.batch_analyze_templates(
                        template_ids=[UUID(tid) for tid in template_ids],
                        batch_size=10
                    )
                    detected_ok = len(detection["successful"])
                    detected_fail = len(detection["failed"])
                    logs.append(f"Element detection: {detected_ok} OK, {detected_fail} failed")
                except Exception as e:
                    logs.append(f"Element detection failed: {e}")
                    logger.error(f"Element detection failed in template approval job: {e}")
        else:
            # Leave in pending_details for manual review
            approved_count = 0
            logs.append(f"Left {len(analyzed_items)} items in pending_details for manual review")

        # Summary
        logs.append(f"")
        logs.append(f"=== Summary ===")
        logs.append(f"Processed: {len(queue_ids)}")
        logs.append(f"Analyzed: {len(analyzed_items)}")
        logs.append(f"Approved: {approved_count}")
        if detected_ok or detected_fail:
            logs.append(f"Element detection: {detected_ok} OK, {detected_fail} failed")

        # Update job run as completed
        update_job_run(run_id, {
            "status": "completed",
            "completed_at": datetime.now(PST).isoformat(),
            "logs": "\n".join(logs)
        })

        # Update job scheduling
        _update_job_next_run(job, job_id)

        logger.info(f"Completed template approval job: {job_name} - {approved_count} approved, {detected_ok} detected")
        return {
            "success": True,
            "processed": len(queue_ids),
            "analyzed": len(analyzed_items),
            "approved": approved_count,
            "element_detection": {"successful": detected_ok, "failed": detected_fail}
        }

    except Exception as e:
        error_msg = str(e)
        logs.append(f"Job failed: {error_msg}")
        logger.error(f"Template approval job {job_name} failed: {error_msg}")

        update_job_run(run_id, {
            "status": "failed",
            "completed_at": datetime.now(PST).isoformat(),
            "error_message": error_msg,
            "logs": "\n".join(logs)
        })

        # Reschedule recurring jobs so they run again next cycle
        _reschedule_after_failure(job, job_id, get_run_attempt_number(run_id))

        return {"success": False, "error": error_msg}


# ============================================================================
# Congruence Re-analysis Job Handler
# ============================================================================

async def execute_congruence_reanalysis_job(job: Dict) -> Dict[str, Any]:
    """
    Execute a congruence re-analysis job.

    Finds ads with video analysis + landing page data but missing congruence
    components, and re-runs classification with force=True to generate
    the per-dimension congruence analysis.

    Parameters (from job['parameters']):
        batch_size: int - Max ads to fetch per run (default: 50)
        max_gemini_calls: int - Max Gemini API calls per run (default: 20)
        brand_id: Optional[str] - Specific brand to process (None = all brands)
    """
    job_id = job['id']
    job_name = job['name']
    params = job.get('parameters') or {}

    logger.info(f"Starting congruence re-analysis job: {job_name} (ID: {job_id})")

    # Immediately clear next_run_at to prevent duplicate execution
    update_job(job_id, {"next_run_at": None})

    # Create job run record
    run_id = create_job_run(job_id)
    if not run_id:
        logger.error(f"Failed to create run record for job {job_id}")
        return {"success": False, "error": "Failed to create run record"}

    # Dataset freshness tracking (only when brand-scoped)
    from viraltracker.services.dataset_freshness_service import DatasetFreshnessService
    freshness = DatasetFreshnessService()

    logs = []

    try:
        # Get parameters
        batch_size = params.get('batch_size', 50)
        max_gemini_calls = params.get('max_gemini_calls', 20)
        target_brand_id = params.get('brand_id')

        if target_brand_id:
            freshness.record_start(target_brand_id, "congruence_analysis", run_id=run_id)

        logs.append(f"Batch size: {batch_size}, Max Gemini calls: {max_gemini_calls}")
        if target_brand_id:
            logs.append(f"Target brand: {target_brand_id}")
        else:
            logs.append("Processing all brands")

        # Import services
        from viraltracker.services.ad_intelligence.congruence_insights_service import CongruenceInsightsService
        from viraltracker.services.ad_intelligence.classifier_service import ClassifierService
        from viraltracker.services.ad_intelligence.congruence_analyzer import CongruenceAnalyzer
        from viraltracker.services.video_analysis_service import VideoAnalysisService
        from viraltracker.services.gemini_service import GeminiService
        from uuid import UUID

        db = get_supabase_client()

        # Initialize services
        insights_service = CongruenceInsightsService(db)
        gemini_service = GeminiService()
        congruence_analyzer = CongruenceAnalyzer(gemini_service)
        video_analysis_service = VideoAnalysisService()

        # Initialize classifier with congruence analyzer
        classifier = ClassifierService(
            supabase_client=db,
            gemini_service=gemini_service,
            video_analysis_service=video_analysis_service,
            congruence_analyzer=congruence_analyzer,
        )

        # Get eligible ads
        brand_uuid = UUID(target_brand_id) if target_brand_id else None
        eligible_ads = insights_service.get_eligible_for_reanalysis(
            brand_id=brand_uuid,
            limit=batch_size,
        )

        if not eligible_ads:
            logs.append("No eligible ads found for re-analysis")
            update_job_run(run_id, {
                "status": "completed",
                "completed_at": datetime.now(PST).isoformat(),
                "logs": "\n".join(logs)
            })
            _update_job_next_run(job, job_id)
            return {"success": True, "analyzed": 0, "message": "No eligible ads"}

        logs.append(f"Found {len(eligible_ads)} eligible ads")

        # Process ads
        analyzed_count = 0
        error_count = 0
        gemini_calls = 0

        for ad in eligible_ads:
            if gemini_calls >= max_gemini_calls:
                logs.append(f"Reached max Gemini calls ({max_gemini_calls}), stopping")
                break

            meta_ad_id = ad.get("meta_ad_id")
            ad_brand_id = ad.get("brand_id")
            ad_org_id = ad.get("organization_id")

            try:
                # Create a dummy run_id for classification (we reuse the job run id)
                classification_run_id = UUID(run_id)

                # Re-classify with force=True to trigger congruence analysis
                result = await classifier.classify_ad(
                    meta_ad_id=meta_ad_id,
                    brand_id=UUID(ad_brand_id),
                    org_id=UUID(ad_org_id),
                    run_id=classification_run_id,
                    force=True,  # Force re-analysis
                    scrape_missing_lp=False,  # LP already exists
                )

                gemini_calls += 1

                # Check if congruence was populated
                if result and result.congruence_components:
                    analyzed_count += 1
                    logs.append(f"  ✓ {meta_ad_id}: congruence analyzed ({len(result.congruence_components)} components)")
                else:
                    logs.append(f"  - {meta_ad_id}: classified but no congruence components")

            except Exception as e:
                error_count += 1
                logs.append(f"  ✗ {meta_ad_id}: {str(e)[:50]}")
                logger.warning(f"Error re-analyzing ad {meta_ad_id}: {e}")

        # Summary
        logs.append(f"")
        logs.append(f"=== Summary ===")
        logs.append(f"Analyzed: {analyzed_count}")
        logs.append(f"Errors: {error_count}")
        logs.append(f"Gemini calls: {gemini_calls}")

        if target_brand_id:
            freshness.record_success(target_brand_id, "congruence_analysis", records_affected=analyzed_count, run_id=run_id)

        # Update job run as completed
        update_job_run(run_id, {
            "status": "completed",
            "completed_at": datetime.now(PST).isoformat(),
            "logs": "\n".join(logs)
        })

        # Update job scheduling
        _update_job_next_run(job, job_id)

        logger.info(f"Completed congruence re-analysis job: {job_name} - {analyzed_count} analyzed")
        return {
            "success": True,
            "analyzed": analyzed_count,
            "errors": error_count,
            "gemini_calls": gemini_calls,
        }

    except Exception as e:
        error_msg = str(e)
        logs.append(f"Job failed: {error_msg}")
        logger.error(f"Congruence re-analysis job {job_name} failed: {error_msg}")

        if target_brand_id:
            freshness.record_failure(target_brand_id, "congruence_analysis", error_msg, run_id=run_id)

        update_job_run(run_id, {
            "status": "failed",
            "completed_at": datetime.now(PST).isoformat(),
            "error_message": error_msg,
            "logs": "\n".join(logs)
        })

        # Reschedule recurring jobs so they run again next cycle
        _reschedule_after_failure(job, job_id, get_run_attempt_number(run_id))

        return {"success": False, "error": error_msg}


# ============================================================================
# Ad Classification Job Handler
# ============================================================================

async def _run_classification_for_brand(
    brand_id: "UUID",
    logs: List[str],
    max_new: int = 200,
    max_video: int = 15,
    days_back: int = 30,
    scrape_missing_lp: bool = False,
) -> Dict[str, Any]:
    """Shared helper: classify active ads for a brand.

    Used by both the standalone ad_classification job and the auto_classify
    chain in meta_sync. Initializes services, fetches active ads, creates
    an ad_intelligence_runs record, and calls classify_batch().

    Args:
        brand_id: Brand UUID.
        logs: Mutable log list to append progress messages.
        max_new: Max new Gemini classification calls (default: 200).
        max_video: Max video classification calls (default: 15).
        days_back: Number of days to look back for active ads (default: 30).
        scrape_missing_lp: If True, create and scrape landing pages for
            unmatched destination URLs during classification.

    Returns:
        Dict with keys: total_active, classified, video, errors.
    """
    from uuid import UUID as _UUID
    from datetime import date as _date
    from viraltracker.services.gemini_service import GeminiService
    from viraltracker.services.ad_intelligence.classifier_service import ClassifierService
    from viraltracker.services.ad_intelligence.ad_intelligence_service import AdIntelligenceService
    from viraltracker.services.ad_intelligence.congruence_analyzer import CongruenceAnalyzer
    from viraltracker.services.ad_intelligence.helpers import get_active_ad_ids
    from viraltracker.services.video_analysis_service import VideoAnalysisService

    db = get_supabase_client()

    # Look up organization_id from brands table
    brand_result = db.table("brands").select("organization_id").eq(
        "id", str(brand_id)
    ).limit(1).execute()

    if not brand_result.data:
        raise ValueError(f"Brand {brand_id} not found")

    org_id = _UUID(brand_result.data[0]["organization_id"])

    # Initialize services
    gemini_service = GeminiService()
    video_analysis_service = VideoAnalysisService(db)
    congruence_analyzer = CongruenceAnalyzer(gemini_service)
    classifier = ClassifierService(
        supabase_client=db,
        gemini_service=gemini_service,
        video_analysis_service=video_analysis_service,
        congruence_analyzer=congruence_analyzer,
    )

    # Get active ad IDs
    date_range_end = _date.today()
    active_ids = await get_active_ad_ids(
        db, brand_id, date_range_end, active_window_days=days_back
    )

    if not active_ids:
        logs.append("No active ads found for classification")
        return {
            "total_active": 0,
            "classified": 0,
            "video": 0,
            "errors": 0,
        }

    logs.append(f"Found {len(active_ids)} active ads")

    # Create ad_intelligence_runs record for audit trail
    intel_service = AdIntelligenceService(db, gemini_service=gemini_service)
    run = await intel_service.create_classification_run(
        brand_id=brand_id,
        org_id=org_id,
    )

    logs.append(f"Classification run: {run.id}")

    # Run classification (classify_batch logs new vs cached counts internally)
    try:
        batch_result = await classifier.classify_batch(
            brand_id=brand_id,
            org_id=org_id,
            run_id=run.id,
            meta_ad_ids=active_ids,
            max_new=max_new,
            max_video=max_video,
            scrape_missing_lp=scrape_missing_lp,
        )

        total_classified = len(batch_result.classifications)
        video_count = sum(
            1 for c in batch_result.classifications if c.source == "gemini_video"
        )

        # Complete the run
        await intel_service._complete_run(run.id, "completed", {
            "total_ads": len(active_ids),
            "classified": total_classified,
            "new": batch_result.new_count,
            "cached": batch_result.cached_count,
            "video": video_count,
            "skipped": batch_result.skipped_count,
            "errors": batch_result.error_count,
        })

        logs.append(
            f"Classified {total_classified} ads "
            f"({batch_result.new_count} new, {batch_result.cached_count} cached, "
            f"{video_count} video)"
        )
        if batch_result.skipped_count > 0:
            logs.append(
                f"Skipped {batch_result.skipped_count} ads (cap or missing media)"
            )
        if batch_result.error_count > 0:
            logs.append(f"Errors: {batch_result.error_count}")

        return {
            "total_active": len(active_ids),
            "classified": total_classified,
            "new": batch_result.new_count,
            "cached": batch_result.cached_count,
            "video": video_count,
            "skipped": batch_result.skipped_count,
            "errors": batch_result.error_count,
        }

    except Exception as e:
        await intel_service._complete_run(run.id, "failed", error_message=str(e))
        raise


async def execute_ad_classification_job(job: Dict) -> Dict[str, Any]:
    """Execute a standalone ad classification job.

    Pre-computes classifications for active ads so that subsequent
    full_analysis() calls find fresh cached results, making analysis
    near-instant.

    Parameters (from job['parameters']):
        max_new: int - Max new Gemini classifications (default: 200)
        max_video: int - Max video classifications (default: 15)
        days_back: int - Days to look back for active ads (default: 30)
    """
    job_id = job['id']
    job_name = job['name']
    brand_id = job.get('brand_id')
    brand_info = job.get('brands') or {}
    brand_name = brand_info.get('name', 'Unknown')
    params = job.get('parameters') or {}

    logger.info(f"Starting ad classification job: {job_name} for brand {brand_name}")

    # Immediately clear next_run_at to prevent duplicate execution
    update_job(job_id, {"next_run_at": None})

    # Create job run record
    run_id = create_job_run(job_id)
    if not run_id:
        logger.error(f"Failed to create run record for job {job_id}")
        return {"success": False, "error": "Failed to create run record"}

    # Dataset freshness tracking
    from viraltracker.services.dataset_freshness_service import DatasetFreshnessService
    freshness = DatasetFreshnessService()

    logs = []

    try:
        from uuid import UUID

        freshness.record_start(brand_id, "ad_classifications", run_id=run_id)

        max_new = params.get('max_new', 200)
        max_video = params.get('max_video', 15)
        days_back = params.get('days_back', 30)

        logs.append(f"Classifying ads for brand: {brand_name}")
        logs.append(f"Max new: {max_new}, Max video: {max_video}, Days back: {days_back}")

        result = await _run_classification_for_brand(
            brand_id=UUID(brand_id),
            logs=logs,
            max_new=max_new,
            max_video=max_video,
            days_back=days_back,
        )

        logs.append("")
        logs.append("=== Summary ===")
        logs.append(f"Active ads: {result['total_active']}")
        logs.append(f"Classified: {result['classified']} ({result['new']} new, {result['cached']} cached)")
        logs.append(f"Video classifications: {result['video']}")
        if result['skipped'] > 0:
            logs.append(f"Skipped (cap): {result['skipped']}")
        if result['errors'] > 0:
            logs.append(f"Errors: {result['errors']}")

        freshness.record_success(brand_id, "ad_classifications", records_affected=result.get('classified', 0), run_id=run_id)

        # Update job run as completed
        update_job_run(run_id, {
            "status": "completed",
            "completed_at": datetime.now(PST).isoformat(),
            "logs": "\n".join(logs)
        })

        # Update job scheduling
        _update_job_next_run(job, job_id)

        logger.info(
            f"Completed ad classification job: {job_name} - "
            f"{result['classified']} classified, {result['video']} video"
        )
        return {"success": True, **result}

    except Exception as e:
        error_msg = str(e)
        logs.append(f"Job failed: {error_msg}")
        logger.error(f"Ad classification job {job_name} failed: {error_msg}")

        freshness.record_failure(brand_id, "ad_classifications", error_msg, run_id=run_id)

        update_job_run(run_id, {
            "status": "failed",
            "completed_at": datetime.now(PST).isoformat(),
            "error_message": error_msg,
            "logs": "\n".join(logs)
        })

        # Reschedule recurring jobs so they run again next cycle
        _reschedule_after_failure(job, job_id, get_run_attempt_number(run_id))

        return {"success": False, "error": error_msg}


async def execute_asset_download_job(job: Dict) -> Dict[str, Any]:
    """Execute a standalone asset download job.

    Downloads ad creatives (videos + images) from Meta CDN to Supabase
    storage so they're available for classification and analysis.

    Parameters (from job['parameters']):
        max_videos: int - Max videos to download (default: 20)
        max_images: int - Max images to download (default: 40)
    """
    job_id = job['id']
    job_name = job['name']
    brand_id = job.get('brand_id')
    brand_info = job.get('brands') or {}
    brand_name = brand_info.get('name', 'Unknown')
    params = job.get('parameters') or {}

    logger.info(f"Starting asset download job: {job_name} for brand {brand_name}")

    # Immediately clear next_run_at to prevent duplicate execution
    update_job(job_id, {"next_run_at": None})

    # Create job run record
    run_id = create_job_run(job_id)
    if not run_id:
        logger.error(f"Failed to create run record for job {job_id}")
        return {"success": False, "error": "Failed to create run record"}

    # Dataset freshness tracking
    from viraltracker.services.dataset_freshness_service import DatasetFreshnessService
    freshness = DatasetFreshnessService()

    logs = []

    try:
        from uuid import UUID
        from viraltracker.services.meta_ads_service import MetaAdsService

        freshness.record_start(brand_id, "ad_assets", run_id=run_id)

        max_videos = params.get('max_videos', 20)
        max_images = params.get('max_images', 40)

        logs.append(f"Downloading assets for brand: {brand_name}")
        logs.append(f"Max videos: {max_videos}, Max images: {max_images}")

        service = MetaAdsService()
        asset_counts = await service.download_new_ad_assets(
            brand_id=UUID(brand_id),
            max_videos=max_videos,
            max_images=max_images,
        )

        videos_downloaded = asset_counts.get("videos", 0)
        images_downloaded = asset_counts.get("images", 0)
        total = videos_downloaded + images_downloaded

        logs.append("")
        logs.append("=== Summary ===")
        logs.append(f"Videos downloaded: {videos_downloaded}")
        logs.append(f"Images downloaded: {images_downloaded}")
        logs.append(f"Total: {total}")

        freshness.record_success(brand_id, "ad_assets", records_affected=total, run_id=run_id)

        # Update job run as completed
        update_job_run(run_id, {
            "status": "completed",
            "completed_at": datetime.now(PST).isoformat(),
            "logs": "\n".join(logs)
        })

        # Update job scheduling
        _update_job_next_run(job, job_id)

        logger.info(
            f"Completed asset download job: {job_name} - "
            f"{videos_downloaded} videos, {images_downloaded} images"
        )
        return {"success": True, "videos": videos_downloaded, "images": images_downloaded}

    except Exception as e:
        error_msg = str(e)
        logs.append(f"Job failed: {error_msg}")
        logger.error(f"Asset download job {job_name} failed: {error_msg}")

        freshness.record_failure(brand_id, "ad_assets", error_msg, run_id=run_id)

        update_job_run(run_id, {
            "status": "failed",
            "completed_at": datetime.now(PST).isoformat(),
            "error_message": error_msg,
            "logs": "\n".join(logs)
        })

        # Reschedule recurring jobs so they run again next cycle
        _reschedule_after_failure(job, job_id, get_run_attempt_number(run_id))

        return {"success": False, "error": error_msg}


async def execute_competitor_scrape_job(job: Dict) -> Dict[str, Any]:
    """Execute a competitor ad scrape job.

    Scrapes ads from Facebook Ad Library for a competitor and saves them
    to the competitor_ads table.

    Parameters (from job['parameters']):
        competitor_id: str - Competitor UUID to link ads to
        ad_library_url: str - Facebook Ad Library URL to scrape
        max_ads: int - Max ads to scrape (default: 500)
    """
    job_id = job['id']
    job_name = job['name']
    brand_id = job.get('brand_id')
    brand_info = job.get('brands') or {}
    brand_name = brand_info.get('name', 'Unknown')
    params = job.get('parameters') or {}

    logger.info(f"Starting competitor scrape job: {job_name} for brand {brand_name}")

    # Immediately clear next_run_at to prevent duplicate execution
    update_job(job_id, {"next_run_at": None})

    # Create job run record
    run_id = create_job_run(job_id)
    if not run_id:
        logger.error(f"Failed to create run record for job {job_id}")
        return {"success": False, "error": "Failed to create run record"}

    # Dataset freshness tracking
    from viraltracker.services.dataset_freshness_service import DatasetFreshnessService
    freshness = DatasetFreshnessService()

    logs = []

    try:
        from uuid import UUID
        from viraltracker.scrapers.facebook_ads import FacebookAdsScraper
        from viraltracker.services.competitor_service import CompetitorService

        freshness.record_start(brand_id, "competitor_ads", run_id=run_id)

        competitor_id = params.get('competitor_id')
        ad_library_url = params.get('ad_library_url')
        max_ads = params.get('max_ads', 500)

        if not competitor_id or not ad_library_url:
            raise ValueError("competitor_id and ad_library_url are required parameters")

        logs.append(f"Scraping competitor ads for brand: {brand_name}")
        logs.append(f"Ad Library URL: {ad_library_url}")
        logs.append(f"Max ads: {max_ads}")

        # Scrape ads from Ad Library
        scraper = FacebookAdsScraper()
        df = scraper.search_ad_library(
            search_url=ad_library_url,
            count=max_ads,
            scrape_details=False,
            timeout=900  # 15 min timeout for large scrapes
        )

        ads_found = len(df)
        logs.append(f"Ads found: {ads_found}")

        saved = 0
        if ads_found > 0:
            # Convert DataFrame to list of dicts and save
            ads_data = df.to_dict('records')
            service = CompetitorService()
            stats = service.save_competitor_ads_batch(
                competitor_id=UUID(competitor_id),
                brand_id=UUID(brand_id),
                ads=ads_data,
                scrape_source="ad_library_search"
            )
            saved = stats.get("saved", 0)
            failed = stats.get("failed", 0)
            logs.append(f"Saved: {saved}, Failed: {failed}")
        else:
            logs.append("No ads found at this URL")

        logs.append("")
        logs.append("=== Summary ===")
        logs.append(f"Ads found: {ads_found}")
        logs.append(f"Ads saved: {saved}")

        freshness.record_success(brand_id, "competitor_ads", records_affected=saved, run_id=run_id)

        # Update job run as completed
        update_job_run(run_id, {
            "status": "completed",
            "completed_at": datetime.now(PST).isoformat(),
            "logs": "\n".join(logs)
        })

        # Update job scheduling
        _update_job_next_run(job, job_id)

        logger.info(f"Completed competitor scrape job: {job_name} - {saved} ads saved")
        return {"success": True, "ads_found": ads_found, "ads_saved": saved}

    except Exception as e:
        error_msg = str(e)
        logs.append(f"Job failed: {error_msg}")
        logger.error(f"Competitor scrape job {job_name} failed: {error_msg}")

        freshness.record_failure(brand_id, "competitor_ads", error_msg, run_id=run_id)

        update_job_run(run_id, {
            "status": "failed",
            "completed_at": datetime.now(PST).isoformat(),
            "error_message": error_msg,
            "logs": "\n".join(logs)
        })

        # Reschedule recurring jobs so they run again next cycle
        _reschedule_after_failure(job, job_id, get_run_attempt_number(run_id))

        return {"success": False, "error": error_msg}


async def execute_reddit_scrape_job(job: Dict) -> Dict[str, Any]:
    """Execute a Reddit sentiment analysis pipeline job.

    Runs the full reddit_sentiment pipeline (scrape → filter → categorize → save)
    as a background job instead of blocking the UI.

    Parameters (from job['parameters']):
        search_queries: list[str] - Search terms (required)
        subreddits: list[str] | None - Subreddits to search (optional)
        timeframe: str - Time range: hour/day/week/month/year/all (default: month)
        max_posts: int - Max posts to scrape (default: 500)
        min_upvotes: int - Min upvotes filter (default: 20)
        min_comments: int - Min comments filter (default: 5)
        relevance_threshold: float - Relevance cutoff 0-1 (default: 0.6)
        signal_threshold: float - Signal cutoff 0-1 (default: 0.5)
        top_percentile: float - Top % to keep (default: 0.20)
        persona_id: str | None - Persona UUID to sync quotes to
        auto_sync_to_persona: bool - Whether to sync quotes (default: False)
        persona_context: str | None - Persona description for LLM
        topic_context: str | None - Topic/domain focus for LLM
    """
    job_id = job['id']
    job_name = job['name']
    brand_id = job.get('brand_id')
    brand_info = job.get('brands') or {}
    brand_name = brand_info.get('name', 'Unknown')
    params = job.get('parameters') or {}

    logger.info(f"Starting reddit scrape job: {job_name} for brand {brand_name}")

    # Immediately clear next_run_at to prevent duplicate execution
    update_job(job_id, {"next_run_at": None})

    # Create job run record
    run_id = create_job_run(job_id)
    if not run_id:
        logger.error(f"Failed to create run record for job {job_id}")
        return {"success": False, "error": "Failed to create run record"}

    # Dataset freshness tracking
    from viraltracker.services.dataset_freshness_service import DatasetFreshnessService
    freshness = DatasetFreshnessService()

    logs = []

    try:
        from uuid import UUID
        from viraltracker.pipelines.reddit_sentiment import run_reddit_sentiment

        freshness.record_start(brand_id, "reddit_data", run_id=run_id)

        # Extract and validate parameters
        search_queries = params.get('search_queries', [])
        if not search_queries:
            raise ValueError("search_queries is required (list of search terms)")

        subreddits = params.get('subreddits')
        timeframe = params.get('timeframe', 'month')
        max_posts = params.get('max_posts', 500)
        min_upvotes = params.get('min_upvotes', 20)
        min_comments = params.get('min_comments', 5)
        relevance_threshold = params.get('relevance_threshold', 0.6)
        signal_threshold = params.get('signal_threshold', 0.5)
        top_percentile = params.get('top_percentile', 0.20)
        persona_id = params.get('persona_id')
        auto_sync_to_persona = params.get('auto_sync_to_persona', False)
        persona_context = params.get('persona_context')
        topic_context = params.get('topic_context')

        logs.append(f"Reddit scrape for brand: {brand_name}")
        logs.append(f"Queries: {', '.join(search_queries)}")
        if subreddits:
            logs.append(f"Subreddits: {', '.join(subreddits)}")
        logs.append(f"Timeframe: {timeframe}, Max posts: {max_posts}")

        # Run the full pipeline
        result = await run_reddit_sentiment(
            search_queries=search_queries,
            brand_id=UUID(brand_id) if brand_id else None,
            persona_id=UUID(persona_id) if persona_id else None,
            subreddits=subreddits,
            timeframe=timeframe,
            max_posts=max_posts,
            min_upvotes=min_upvotes,
            min_comments=min_comments,
            relevance_threshold=relevance_threshold,
            signal_threshold=signal_threshold,
            top_percentile=top_percentile,
            auto_sync_to_persona=auto_sync_to_persona and persona_id is not None,
            persona_context=persona_context,
            topic_context=topic_context,
        )

        status = result.get("status", "unknown")
        posts_scraped = result.get("posts_scraped", 0)
        quotes_extracted = result.get("quotes_extracted", 0)
        pipeline_run_id = result.get("run_id", "")

        logs.append("")
        logs.append("=== Pipeline Result ===")
        logs.append(f"Status: {status}")
        logs.append(f"Posts scraped: {posts_scraped}")
        logs.append(f"Quotes extracted: {quotes_extracted}")
        if result.get("quotes_synced"):
            logs.append(f"Quotes synced to persona: {result['quotes_synced']}")
        if pipeline_run_id:
            logs.append(f"Pipeline run ID: {pipeline_run_id}")

        if status == "success":
            freshness.record_success(brand_id, "reddit_data", records_affected=quotes_extracted, run_id=run_id)

            update_job_run(run_id, {
                "status": "completed",
                "completed_at": datetime.now(PST).isoformat(),
                "logs": "\n".join(logs)
            })

            _update_job_next_run(job, job_id)

            logger.info(f"Completed reddit scrape job: {job_name} - {quotes_extracted} quotes extracted")
            return {"success": True, "posts_scraped": posts_scraped, "quotes_extracted": quotes_extracted}
        else:
            error_msg = result.get("error", f"Pipeline returned status: {status}")
            raise Exception(error_msg)

    except Exception as e:
        error_msg = str(e)
        logs.append(f"Job failed: {error_msg}")
        logger.error(f"Reddit scrape job {job_name} failed: {error_msg}")

        freshness.record_failure(brand_id, "reddit_data", error_msg, run_id=run_id)

        update_job_run(run_id, {
            "status": "failed",
            "completed_at": datetime.now(PST).isoformat(),
            "error_message": error_msg,
            "logs": "\n".join(logs)
        })

        _reschedule_after_failure(job, job_id, get_run_attempt_number(run_id))

        return {"success": False, "error": error_msg}


async def execute_amazon_review_scrape_job(job: Dict) -> Dict[str, Any]:
    """Execute an Amazon review scrape job.

    Scrapes Amazon reviews for a competitor product using the Apify-based
    multi-layer strategy and saves them to the competitor_amazon_reviews table.

    Parameters (from job['parameters']):
        competitor_amazon_url_id: str - UUID of the competitor_amazon_urls record (required)
        include_keywords: bool - Include keyword filter configs (default: True)
        include_helpful: bool - Include helpful-sort configs (default: True)
    """
    job_id = job['id']
    job_name = job['name']
    brand_id = job.get('brand_id')
    brand_info = job.get('brands') or {}
    brand_name = brand_info.get('name', 'Unknown')
    params = job.get('parameters') or {}

    logger.info(f"Starting amazon review scrape job: {job_name} for brand {brand_name}")

    # Immediately clear next_run_at to prevent duplicate execution
    update_job(job_id, {"next_run_at": None})

    # Create job run record
    run_id = create_job_run(job_id)
    if not run_id:
        logger.error(f"Failed to create run record for job {job_id}")
        return {"success": False, "error": "Failed to create run record"}

    # Dataset freshness tracking
    from viraltracker.services.dataset_freshness_service import DatasetFreshnessService
    freshness = DatasetFreshnessService()

    logs = []

    try:
        from uuid import UUID
        from viraltracker.services.competitor_service import CompetitorService

        freshness.record_start(brand_id, "amazon_reviews", run_id=run_id)

        competitor_amazon_url_id = params.get('competitor_amazon_url_id')
        include_keywords = params.get('include_keywords', True)
        include_helpful = params.get('include_helpful', True)

        if not competitor_amazon_url_id:
            raise ValueError("competitor_amazon_url_id is a required parameter")

        asin = params.get('asin', 'Unknown')
        logs.append(f"Amazon review scrape for brand: {brand_name}")
        logs.append(f"ASIN: {asin}")
        logs.append(f"Include keywords: {include_keywords}, Include helpful: {include_helpful}")

        # Scrape reviews via CompetitorService
        service = CompetitorService()
        result = service.scrape_amazon_reviews_for_competitor(
            competitor_amazon_url_id=UUID(competitor_amazon_url_id),
            include_keywords=include_keywords,
            include_helpful=include_helpful,
            timeout=900
        )

        reviews_saved = result.get('reviews_saved', 0)
        raw_count = result.get('raw_reviews_count', 0)
        unique_count = result.get('unique_reviews_count', 0)
        cost = result.get('cost_estimate', 0.0)
        errors = result.get('errors', [])

        logs.append("")
        logs.append("=== Summary ===")
        logs.append(f"Raw reviews fetched: {raw_count}")
        logs.append(f"Unique reviews: {unique_count}")
        logs.append(f"Reviews saved: {reviews_saved}")
        logs.append(f"Estimated cost: ${cost:.2f}")

        if errors:
            for err in errors:
                logs.append(f"Error: {err}")
            raise Exception(f"Scrape completed with errors: {'; '.join(errors)}")

        freshness.record_success(brand_id, "amazon_reviews", records_affected=reviews_saved, run_id=run_id)

        update_job_run(run_id, {
            "status": "completed",
            "completed_at": datetime.now(PST).isoformat(),
            "logs": "\n".join(logs)
        })

        _update_job_next_run(job, job_id)

        logger.info(f"Completed amazon review scrape job: {job_name} - {reviews_saved} reviews saved")
        return {"success": True, "raw_reviews": raw_count, "reviews_saved": reviews_saved}

    except Exception as e:
        error_msg = str(e)
        logs.append(f"Job failed: {error_msg}")
        logger.error(f"Amazon review scrape job {job_name} failed: {error_msg}")

        freshness.record_failure(brand_id, "amazon_reviews", error_msg, run_id=run_id)

        update_job_run(run_id, {
            "status": "failed",
            "completed_at": datetime.now(PST).isoformat(),
            "error_message": error_msg,
            "logs": "\n".join(logs)
        })

        _reschedule_after_failure(job, job_id, get_run_attempt_number(run_id))

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
            # Recover any stuck runs before checking for new work
            recover_stuck_runs()

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
    logger.info("Scheduler Worker")
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
