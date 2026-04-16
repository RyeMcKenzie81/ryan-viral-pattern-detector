"""Operations Specialist Agent

Handles operational queries: job management, system status, brand lookups.
This is the "Ops Copilot" agent from the chat-first service access design.
"""
import logging
import os
from datetime import datetime, timedelta, timezone
from typing import Optional

from pydantic_ai import Agent, RunContext

from ..dependencies import AgentDependencies
from ...core.config import Config

logger = logging.getLogger(__name__)

# Valid job types matching the scheduled_jobs CHECK constraint.
# Keep in sync with the latest migration.
VALID_JOB_TYPES = {
    "ad_creation", "ad_creation_v2", "meta_sync", "scorecard",
    "template_scrape", "template_approval", "congruence_reanalysis",
    "ad_classification", "asset_download", "competitor_scrape",
    "reddit_scrape", "amazon_review_scrape", "creative_genome_update",
    "creative_deep_analysis", "genome_validation", "winner_evolution",
    "experiment_analysis", "quality_calibration", "ad_intelligence_analysis",
    "analytics_sync", "seo_status_sync", "iteration_auto_run",
    "size_variant", "smart_edit", "seo_content_eval", "seo_publish",
    "seo_auto_interlink", "demographic_backfill", "seo_opportunity_scan",
    "token_refresh", "competitor_intel_analysis",
}

# Rough completion time estimates per job type (minutes)
JOB_TIME_ESTIMATES = {
    "meta_sync": 5,
    "ad_classification": 10,
    "template_scrape": 5,
    "template_approval": 3,
    "ad_creation": 10,
    "ad_creation_v2": 10,
    "asset_download": 5,
    "scorecard": 3,
    "competitor_scrape": 5,
    "competitor_intel_analysis": 15,
    "creative_deep_analysis": 15,
    "ad_intelligence_analysis": 10,
}

ops_agent = Agent(
    model=Config.get_model("orchestrator"),
    deps_type=AgentDependencies,
    system_prompt="""You are the Operations agent for ViralTracker.

Your responsibilities:
- Queue background jobs (meta sync, ad creation, classification, etc.)
- Check job status and list recent jobs
- List brands the user has access to
- Provide system health summaries

**Important rules:**
- Always include job IDs in responses so users can reference them later.
- When queueing a job, confirm what you're about to do and include the estimated completion time.
- When listing jobs, format them clearly with status, type, brand, and timestamps.
- For job failures, include the error message and whether retries are remaining.
- End responses with a source line: Source: OpsAgent | {current timestamp}

**Available job types (use these EXACT strings):**

Ad operations:
- ad_creation / ad_creation_v2 — generate ad creatives
- ad_classification — classify ads by awareness level and format
- ad_intelligence_analysis — full ad account analysis
- congruence_reanalysis — creative-copy-landing page alignment check

Template operations:
- template_scrape — scrape ad templates from Facebook Ad Library
- template_approval — AI review of scraped templates (approve/reject)

Meta/Facebook:
- meta_sync — sync ad data from Meta Ads API
- asset_download — download ad creative assets
- analytics_sync — sync analytics data

Content/SEO:
- seo_content_eval — evaluate SEO content quality
- seo_publish — publish SEO content to CMS
- seo_auto_interlink — auto-interlink SEO articles
- seo_status_sync — sync SEO keyword rankings
- seo_opportunity_scan — scan for SEO opportunities

Research:
- competitor_scrape — scrape competitor social media
- competitor_intel_analysis — deep competitor intelligence analysis
- reddit_scrape — scrape Reddit threads
- amazon_review_scrape — scrape Amazon reviews

Creative genome:
- creative_genome_update / creative_deep_analysis / genome_validation
- winner_evolution / experiment_analysis / quality_calibration

Other:
- scorecard — generate brand scorecard
- iteration_auto_run / size_variant / smart_edit
- demographic_backfill / token_refresh

**IMPORTANT:** "template evaluation" or "evaluate templates" means template_approval.
"template scrape" means template_scrape. These are different operations.
""",
)


async def _resolve_brand(db, brand_id: str, ctx) -> str:
    """Resolve a brand name or UUID to a valid brand UUID.

    Accepts a UUID (returned as-is) or a brand name (fuzzy matched via
    case-insensitive substring search). Returns "Error: ..." on failure.
    """
    import re

    # If it looks like a UUID, return as-is
    if re.match(r'^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$', brand_id, re.I):
        return brand_id

    # It's a name — search for it
    try:
        query = db.table("brands").select("id, name")
        org_id = getattr(ctx.deps, "_organization_id", None)
        if org_id and org_id != "all":
            query = query.eq("organization_id", org_id)
        result = query.execute()
        brands = result.data or []
    except Exception as e:
        return f"Error: Failed to look up brands: {e}"

    if not brands:
        return "Error: No brands found in your organization."

    search = brand_id.lower().strip()

    # Exact match first
    for b in brands:
        if b["name"].lower() == search:
            return b["id"]

    # Substring / fuzzy match: check if search is contained in name or vice versa
    matches = []
    for b in brands:
        name_lower = b["name"].lower()
        if search in name_lower or name_lower in search:
            matches.append(b)

    if len(matches) == 1:
        return matches[0]["id"]
    elif len(matches) > 1:
        names = ", ".join(f"**{m['name']}**" for m in matches)
        return f"Error: Multiple brands match '{brand_id}': {names}. Please be more specific."

    # No substring match — try word overlap
    search_words = set(search.split())
    for b in brands:
        name_words = set(b["name"].lower().split())
        if search_words & name_words:
            matches.append(b)

    if len(matches) == 1:
        return matches[0]["id"]
    elif len(matches) > 1:
        names = ", ".join(f"**{m['name']}**" for m in matches)
        return f"Error: Multiple brands match '{brand_id}': {names}. Please be more specific."

    available = ", ".join(f"**{b['name']}**" for b in brands)
    return f"Error: No brand matching '{brand_id}'. Available brands: {available}"


# ============================================================================
# Job Management Tools
# ============================================================================


@ops_agent.tool(
    metadata={
        "category": "Operations",
        "platform": "System",
        "use_cases": [
            "Queue a meta sync for a brand",
            "Run ad classification now",
            "Trigger a template scrape",
            "Start a competitor scrape job",
        ],
        "examples": [
            "Queue a meta sync for BobaNutrition",
            "Run ad classification for Wonder Paws",
            "Start a template scrape",
        ],
    }
)
async def queue_job(
    ctx: RunContext[AgentDependencies],
    job_type: str,
    brand_id: str,
    parameters: Optional[dict] = None,
    name: Optional[str] = None,
) -> str:
    """
    Queue a background job for immediate execution.

    Creates a one-time job that the scheduler worker picks up within 60 seconds.

    Args:
        ctx: Run context with AgentDependencies
        job_type: Type of job (e.g., 'meta_sync', 'ad_classification', 'template_scrape')
        brand_id: UUID of the brand, OR the brand name (fuzzy matched)
        parameters: Optional job-specific parameters as a dict
        name: Optional display name for the job

    Returns:
        Confirmation with job ID and estimated completion time, or error message.
    """
    if job_type not in VALID_JOB_TYPES:
        return (
            f"Invalid job type '{job_type}'. Valid types: "
            + ", ".join(sorted(VALID_JOB_TYPES))
        )

    from viraltracker.core.database import get_supabase_client

    db = get_supabase_client()

    # Resolve brand_id: accept UUID or fuzzy name match
    brand_id = await _resolve_brand(db, brand_id, ctx)
    if brand_id.startswith("Error:"):
        return brand_id

    # Duplicate detection: check for same job_type + brand_id created in last 5 minutes
    try:
        five_min_ago = (datetime.now(timezone.utc) - timedelta(minutes=5)).isoformat()
        existing = (
            db.table("scheduled_jobs")
            .select("id, status, created_at")
            .eq("job_type", job_type)
            .eq("brand_id", brand_id)
            .eq("schedule_type", "one_time")
            .in_("status", ["active"])
            .gte("created_at", five_min_ago)
            .limit(1)
            .execute()
        )
        if existing.data:
            existing_job = existing.data[0]
            return (
                f"A {job_type} job for this brand was already queued "
                f"{_time_ago(existing_job['created_at'])} "
                f"(ID: {existing_job['id']}, status: {existing_job['status']}). "
                "Do you want to queue another one anyway?"
            )
    except Exception as e:
        logger.warning(f"Duplicate check failed, proceeding: {e}")

    # Queue the job using the existing helper
    from viraltracker.services.pipeline_helpers import queue_one_time_job

    job_id = queue_one_time_job(
        brand_id=brand_id,
        job_type=job_type,
        parameters=parameters,
        trigger_source="api",
        name=name,
    )

    if not job_id:
        return f"Failed to queue {job_type} job. Check logs for details."

    est_minutes = JOB_TIME_ESTIMATES.get(job_type, 10)
    return (
        f"Queued {job_type} job (ID: {job_id}). "
        f"Estimated completion: ~{est_minutes} minutes. "
        "Ask me to check the status anytime."
    )


@ops_agent.tool(
    metadata={
        "category": "Operations",
        "platform": "System",
        "use_cases": [
            "Check if a job finished",
            "See why a job failed",
            "Get job progress",
        ],
        "examples": [
            "Check status of job abc-123",
            "Is my meta sync done?",
            "What happened to that classification job?",
        ],
    }
)
async def check_job_status(
    ctx: RunContext[AgentDependencies],
    job_id: Optional[str] = None,
) -> str:
    """
    Check the current status of a scheduled job.

    If no job_id is provided, shows the most recently created job.
    Use this when the user asks "check on the job" or "is my job done?"
    without specifying an ID.

    Args:
        ctx: Run context with AgentDependencies
        job_id: Optional UUID of the job. If not provided, checks the most recent job.

    Returns:
        Job status details including type, status, timestamps, and any errors.
    """
    from viraltracker.core.database import get_supabase_client

    db = get_supabase_client()

    try:
        if not job_id:
            # Find the most recent job for the user's org
            query = (
                db.table("scheduled_jobs")
                .select("id")
                .eq("schedule_type", "one_time")
                .order("created_at", desc=True)
                .limit(1)
            )
            org_id = getattr(ctx.deps, "_organization_id", None)
            if org_id and org_id != "all":
                brand_result = db.table("brands").select("id").eq("organization_id", org_id).execute()
                org_brand_ids = [b["id"] for b in (brand_result.data or [])]
                if org_brand_ids:
                    query = query.in_("brand_id", org_brand_ids)
            recent = query.execute()
            if not recent.data:
                return "No recent jobs found. Queue a job first."
            job_id = recent.data[0]["id"]

        result = (
            db.table("scheduled_jobs")
            .select("id, job_type, brand_id, name, status, schedule_type, "
                    "created_at, updated_at, next_run_at, last_error, "
                    "runs_completed, max_retries, parameters, trigger_source, "
                    "brands(id, name)")
            .eq("id", job_id)
            .limit(1)
            .execute()
        )

        if not result.data:
            return f"No job found with ID {job_id}."

        job = result.data[0]
        brand_info = job.get("brands") or {}
        brand_name = brand_info.get("name", "Unknown")

        # Also check most recent run
        run_result = (
            db.table("scheduled_job_runs")
            .select("id, status, started_at, completed_at, error_message")
            .eq("scheduled_job_id", job_id)
            .order("started_at", desc=True)
            .limit(1)
            .execute()
        )
        latest_run = run_result.data[0] if run_result.data else None

        # Count total failures for this job
        fail_count_result = (
            db.table("scheduled_job_runs")
            .select("id", count="exact")
            .eq("scheduled_job_id", job_id)
            .eq("status", "failed")
            .execute()
        )
        total_failures = fail_count_result.count or 0

        lines = [
            f"**Job:** {job['name'] or job['job_type']}",
            f"**ID:** {job['id']}",
            f"**Type:** {job['job_type']}",
            f"**Brand:** {brand_name}",
            f"**Status:** {job['status']}",
            f"**Schedule:** {job.get('schedule_type', 'unknown')}",
            f"**Created:** {job['created_at']}",
            f"**Runs completed:** {job['runs_completed'] or 0}",
            f"**Total failures:** {total_failures}",
        ]

        if job.get("parameters"):
            params = job["parameters"]
            # Show key parameters without dumping the whole blob
            param_keys = list(params.keys())[:5]
            if param_keys:
                lines.append(f"**Parameters:** {', '.join(f'{k}={params[k]}' for k in param_keys)}")

        if job["last_error"]:
            lines.append(f"**Last error:** {job['last_error']}")

        if latest_run:
            lines.append(f"\n**Latest run:** {latest_run['status']}")
            if latest_run.get("started_at"):
                lines.append(f"**Started:** {latest_run['started_at']}")
            if latest_run.get("completed_at"):
                lines.append(f"**Completed:** {latest_run['completed_at']}")
            if latest_run.get("error_message"):
                lines.append(f"**Run error:** {latest_run['error_message'][:500]}")

        return "\n".join(lines)

    except Exception as e:
        logger.error(f"Error checking job status: {e}")
        return f"Error checking job status: {e}"


@ops_agent.tool(
    metadata={
        "category": "Operations",
        "platform": "System",
        "use_cases": [
            "See what jobs ran recently",
            "List failed jobs",
            "Check what's currently running",
        ],
        "examples": [
            "Show recent jobs for BobaNutrition",
            "List failed jobs",
            "What's running right now?",
        ],
    }
)
async def list_recent_jobs(
    ctx: RunContext[AgentDependencies],
    brand_id: Optional[str] = None,
    status_filter: Optional[str] = None,
    limit: int = 10,
) -> str:
    """
    List recent scheduled jobs, optionally filtered by brand and status.

    Args:
        ctx: Run context with AgentDependencies
        brand_id: Optional brand UUID or name (fuzzy matched) to filter by. If not provided, shows all brands in the user's org.
        status_filter: Optional status filter ('active', 'paused', 'completed', 'archived')
        limit: Max number of jobs to return (default: 10, max: 25)

    Returns:
        Formatted list of recent jobs with status, type, and timestamps.
    """
    from viraltracker.core.database import get_supabase_client

    db = get_supabase_client()
    limit = min(limit, 25)

    # Resolve brand name to UUID if provided
    if brand_id:
        brand_id = await _resolve_brand(db, brand_id, ctx)
        if brand_id.startswith("Error:"):
            return brand_id

    try:
        query = (
            db.table("scheduled_jobs")
            .select("id, job_type, brand_id, name, status, schedule_type, "
                    "created_at, updated_at, runs_completed, last_error, trigger_source")
            .order("updated_at", desc=True)
            .limit(limit)
        )

        if brand_id:
            query = query.eq("brand_id", brand_id)

        if status_filter:
            query = query.eq("status", status_filter)

        result = query.execute()

        if not result.data:
            return "No jobs found matching your criteria."

        lines = [f"**Recent Jobs** ({len(result.data)} shown)\n"]
        for job in result.data:
            status_icon = {
                "active": "🟢", "paused": "⏸️",
                "completed": "✅", "archived": "📦",
            }.get(job["status"], "❓")

            line = (
                f"{status_icon} **{job['job_type']}** — {job['status']}"
                f" | {_time_ago(job['updated_at'])}"
            )
            if job.get("name"):
                line += f" | {job['name']}"
            if job.get("last_error"):
                line += f" | ⚠️ {job['last_error'][:80]}"
            line += f"\n   ID: `{job['id']}`"
            lines.append(line)

        return "\n".join(lines)

    except Exception as e:
        logger.error(f"Error listing jobs: {e}")
        return f"Error listing jobs: {e}"


# ============================================================================
# Brand & System Tools
# ============================================================================


@ops_agent.tool(
    metadata={
        "category": "Operations",
        "platform": "System",
        "use_cases": [
            "List available brands",
            "Find a brand ID",
            "See which brands I can manage",
        ],
        "examples": [
            "List my brands",
            "What brands do I have?",
            "Find the brand ID for BobaNutrition",
        ],
    }
)
async def list_brands(
    ctx: RunContext[AgentDependencies],
) -> str:
    """
    List all brands the user has access to in their organization.

    Args:
        ctx: Run context with AgentDependencies

    Returns:
        Formatted list of brands with IDs, names, and product counts.
    """
    from viraltracker.core.database import get_supabase_client

    db = get_supabase_client()

    try:
        query = db.table("brands").select(
            "id, name, website, created_at, products(id)"
        )

        # Filter by org if not superuser
        org_id = getattr(ctx.deps, "_organization_id", None)
        if org_id and org_id != "all":
            query = query.eq("organization_id", org_id)

        result = query.order("name").execute()

        if not result.data:
            return "No brands found."

        lines = [f"**Your Brands** ({len(result.data)} total)\n"]
        for brand in result.data:
            product_count = len(brand.get("products") or [])
            line = f"- **{brand['name']}** — {product_count} product(s)"
            if brand.get("website"):
                line += f" | {brand['website']}"
            line += f"\n  ID: `{brand['id']}`"
            lines.append(line)

        return "\n".join(lines)

    except Exception as e:
        logger.error(f"Error listing brands: {e}")
        return f"Error listing brands: {e}"


@ops_agent.tool(
    metadata={
        "category": "Operations",
        "platform": "System",
        "use_cases": [
            "Get system overview",
            "Check what ran overnight",
            "See if anything failed",
        ],
        "examples": [
            "System health",
            "What happened overnight?",
            "Any failed jobs?",
        ],
    }
)
async def get_system_health(
    ctx: RunContext[AgentDependencies],
    hours_back: int = 24,
) -> str:
    """
    Get a summary of system health: jobs run, failures, and current status.

    Args:
        ctx: Run context with AgentDependencies
        hours_back: How many hours to look back (default: 24)

    Returns:
        System health summary with job counts, failures, and active jobs.
    """
    from viraltracker.core.database import get_supabase_client

    db = get_supabase_client()
    cutoff = (datetime.now(timezone.utc) - timedelta(hours=hours_back)).isoformat()

    try:
        # Get recent job runs with parent job info
        runs = (
            db.table("scheduled_job_runs")
            .select("status, scheduled_job_id, started_at, completed_at, error_message, "
                    "scheduled_jobs(id, job_type, brand_id, name)")
            .gte("started_at", cutoff)
            .execute()
        )

        run_data = runs.data or []
        total = len(run_data)
        completed = sum(1 for r in run_data if r["status"] == "completed")
        failed = sum(1 for r in run_data if r["status"] == "failed")
        running = sum(1 for r in run_data if r["status"] == "running")

        # Get currently active jobs
        active = (
            db.table("scheduled_jobs")
            .select("id, job_type, brand_id, status")
            .eq("status", "active")
            .execute()
        )
        active_count = len(active.data or [])

        lines = [
            f"**System Health** (last {hours_back}h)\n",
            f"- **Job runs:** {total} total",
            f"  - ✅ Completed: {completed}",
            f"  - ❌ Failed: {failed}",
            f"  - 🔄 Running: {running}",
            f"- **Active schedules:** {active_count}",
        ]

        # Show recent failures with full job context
        failures = [r for r in run_data if r["status"] == "failed"]
        if failures:
            # Build brand name lookup
            brand_ids = set()
            for f in failures:
                job_info = f.get("scheduled_jobs") or {}
                if job_info.get("brand_id"):
                    brand_ids.add(job_info["brand_id"])
            brand_names = {}
            if brand_ids:
                try:
                    brands_result = db.table("brands").select("id, name").in_("id", list(brand_ids)).execute()
                    brand_names = {b["id"]: b["name"] for b in (brands_result.data or [])}
                except Exception:
                    pass

            # Deduplicate by job ID and count occurrences
            job_failure_counts: dict = {}
            for f in failures:
                jid = f.get("scheduled_job_id", "unknown")
                if jid not in job_failure_counts:
                    job_info = f.get("scheduled_jobs") or {}
                    bid = job_info.get("brand_id", "")
                    job_failure_counts[jid] = {
                        "count": 0,
                        "job_type": job_info.get("job_type", "unknown"),
                        "name": job_info.get("name", ""),
                        "brand_id": bid,
                        "brand_name": brand_names.get(bid, "Unknown"),
                        "latest_error": f.get("error_message") or "Unknown error",
                        "latest_at": f.get("started_at", ""),
                    }
                job_failure_counts[jid]["count"] += 1
                # Keep the most recent error
                if f.get("started_at", "") > job_failure_counts[jid]["latest_at"]:
                    job_failure_counts[jid]["latest_error"] = f.get("error_message") or "Unknown error"
                    job_failure_counts[jid]["latest_at"] = f.get("started_at", "")

            lines.append(f"\n**Failing Jobs ({len(job_failure_counts)} unique, {len(failures)} total failures):**")
            for jid, info in sorted(job_failure_counts.items(), key=lambda x: -x[1]["count"])[:10]:
                err = info["latest_error"][:120]
                lines.append(
                    f"- **{info['job_type']}** for **{info['brand_name']}** — {info['count']}x failures"
                    f"\n  Job ID: `{jid}`"
                    f"\n  Latest error: {err}"
                )

        if not failures:
            lines.append("\n✅ No failures in this period.")

        return "\n".join(lines)

    except Exception as e:
        logger.error(f"Error getting system health: {e}")
        return f"Error getting system health: {e}"


# ============================================================================
# Helpers
# ============================================================================


def _time_ago(timestamp_str: str) -> str:
    """Convert an ISO timestamp to a human-readable 'X ago' string."""
    try:
        ts = datetime.fromisoformat(timestamp_str.replace("Z", "+00:00"))
        now = datetime.now(timezone.utc)
        delta = now - ts

        if delta.total_seconds() < 60:
            return "just now"
        elif delta.total_seconds() < 3600:
            mins = int(delta.total_seconds() / 60)
            return f"{mins}m ago"
        elif delta.total_seconds() < 86400:
            hours = int(delta.total_seconds() / 3600)
            return f"{hours}h ago"
        else:
            days = int(delta.total_seconds() / 86400)
            return f"{days}d ago"
    except Exception:
        return timestamp_str


logger.info("Ops Agent initialized with 5 tools")
